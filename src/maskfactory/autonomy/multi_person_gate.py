"""Non-overridable image-level gates for autonomous multi-person candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

from ..qa.multi_instance import MultiInstanceQcInputs, run_multi_instance_qc

_RECIPROCAL_RELATION = {
    "contact": "contact",
    "occludes": "occluded_by",
    "occluded_by": "occludes",
}


@dataclass(frozen=True)
class MultiPersonGateCheck:
    check_id: str
    passed: bool
    message: str


@dataclass(frozen=True)
class MultiPersonCandidateGateResult:
    instance_context: str
    promoted_instances: tuple[str, ...]
    checks: tuple[MultiPersonGateCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(check.check_id for check in self.checks if not check.passed)


def evaluate_multi_person_candidate_gate(
    inputs: MultiInstanceQcInputs,
    *,
    instance_context: str,
    promoted_instances: tuple[str, ...],
    relationships: Mapping[tuple[str, str], str],
) -> MultiPersonCandidateGateResult:
    """Require exact identity ownership and reciprocal multi-person relationships.

    This gate operates on the complete image candidate, not one isolated atomic mask.
    It deliberately promotes QC-037-style relationship failures to a hard autonomy
    blocker while leaving the existing review-routing severity unchanged.
    """
    if instance_context not in {"duo", "small_group"}:
        raise ValueError("multi-person candidate context must be duo or small_group")
    expected_count = 2 if instance_context == "duo" else None
    if expected_count is not None and len(promoted_instances) != expected_count:
        raise ValueError("duo autonomy evidence must contain exactly two promoted instances")
    if instance_context == "small_group" and len(promoted_instances) < 3:
        raise ValueError("small-group autonomy evidence must contain at least three instances")
    expected = tuple(f"p{index}" for index in range(len(promoted_instances)))
    if promoted_instances != expected:
        raise ValueError("promoted instances must be contiguous p0..pN in rank order")
    if (
        set(inputs.silhouettes) != set(promoted_instances)
        or set(inputs.atomic_unions) != set(promoted_instances)
        or inputs.expected_promoted_count != len(promoted_instances)
    ):
        raise ValueError("multi-person candidate identity/count differs from promoted instances")

    qc = {result.qc_id: result for result in run_multi_instance_qc(inputs)}
    checks = [
        MultiPersonGateCheck("QC-035", qc["QC-035"].passed, qc["QC-035"].detail),
        MultiPersonGateCheck("QC-036", qc["QC-036"].passed, qc["QC-036"].detail),
    ]

    shape = np.asarray(inputs.silhouettes[promoted_instances[0]]).shape
    containment_failures: dict[str, dict[str, int]] = {}
    for instance_id in promoted_instances:
        silhouette = _boolean_mask(inputs.silhouettes[instance_id], shape, instance_id)
        atomic_union = _boolean_mask(inputs.atomic_unions[instance_id], shape, instance_id)
        outside = int(np.count_nonzero(atomic_union & ~silhouette))
        missing = int(np.count_nonzero(silhouette & ~atomic_union))
        if outside or missing:
            containment_failures[instance_id] = {
                "outside_promoted_silhouette_px": outside,
                "missing_promoted_visible_px": missing,
            }
    checks.append(
        MultiPersonGateCheck(
            "AUT-MP-001",
            not containment_failures,
            f"promoted_person_containment={containment_failures}",
        )
    )

    normalized_relationships: dict[tuple[str, str], str] = {}
    relationship_failures: list[str] = []
    for raw_pair, raw_kind in relationships.items():
        if not isinstance(raw_pair, tuple) or len(raw_pair) != 2:
            raise ValueError("multi-person relationship keys must be (source, target) pairs")
        source, target = (str(raw_pair[0]), str(raw_pair[1]))
        kind = str(raw_kind)
        if source not in promoted_instances or target not in promoted_instances or source == target:
            raise ValueError("multi-person relationship references an invalid promoted instance")
        if kind not in _RECIPROCAL_RELATION:
            raise ValueError(f"unsupported multi-person relationship: {kind}")
        normalized_relationships[(source, target)] = kind

    expected_neighbors = {instance_id: set() for instance_id in promoted_instances}
    for (source, target), kind in sorted(normalized_relationships.items()):
        expected_neighbors[source].add(target)
        reciprocal = normalized_relationships.get((target, source))
        if reciprocal != _RECIPROCAL_RELATION[kind]:
            relationship_failures.append(f"{source}->{target}:{kind}:reciprocal={reciprocal}")

    recorded = {
        instance_id: set(inputs.recorded_relationships.get(instance_id, frozenset()))
        for instance_id in promoted_instances
    }
    for instance_id in promoted_instances:
        if recorded[instance_id] != expected_neighbors[instance_id]:
            relationship_failures.append(
                f"{instance_id}:recorded={sorted(recorded[instance_id])}:"
                f"expected={sorted(expected_neighbors[instance_id])}"
            )
    checks.append(
        MultiPersonGateCheck(
            "AUT-MP-002",
            not relationship_failures,
            f"reciprocal_relationship_failures={relationship_failures}",
        )
    )

    band_failures: list[str] = []
    relationship_pairs = set(normalized_relationships)
    if set(inputs.contact_bands) != relationship_pairs:
        missing = sorted(relationship_pairs - set(inputs.contact_bands))
        unexpected = sorted(set(inputs.contact_bands) - relationship_pairs)
        band_failures.append(f"band_key_mismatch:missing={missing}:unexpected={unexpected}")
    for pair in sorted(relationship_pairs & set(inputs.contact_bands)):
        band = _boolean_mask(inputs.contact_bands[pair], shape, f"contact_band:{pair}")
        if not band.any():
            band_failures.append(f"{pair[0]}->{pair[1]}:empty_contact_band")
    checks.append(
        MultiPersonGateCheck(
            "AUT-MP-003",
            not band_failures,
            f"reciprocal_contact_band_failures={band_failures}",
        )
    )
    return MultiPersonCandidateGateResult(instance_context, promoted_instances, tuple(checks))


def _boolean_mask(value: np.ndarray, shape: tuple[int, ...], name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 2 or array.shape != shape:
        raise ValueError(f"multi-person candidate evidence dimensions differ for {name}")
    return array.astype(bool)


__all__ = [
    "MultiPersonCandidateGateResult",
    "MultiPersonGateCheck",
    "evaluate_multi_person_candidate_gate",
]
