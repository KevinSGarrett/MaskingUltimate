"""Additive builders for operational-policy perturbation, seeded-defect, and replay evidence.

Produces the exact contracts consumed by ``maskfactory.authority.operational_policy``:
resize/crop/color/prompt/horizontal-flip (flip-with-side-swap), exact synthetic truth,
seeded-defect metamorphic cases, and deterministic two-replay observations.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from maskfactory.autonomy.stability import (
    PERTURBATIONS,
    evaluate_candidate_stability,
    load_stability_policy,
)
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.ontology import get_ontology


def _load_operational_policy():
    from maskfactory.authority.operational_policy import load_operational_policy

    return load_operational_policy()


def _prepare_operational_policy_replay(*args, **kwargs):
    from maskfactory.authority.operational_policy import prepare_operational_policy_replay

    return prepare_operational_policy_replay(*args, **kwargs)


def _evaluate_operational_policy(*args, **kwargs):
    from maskfactory.authority.operational_policy import evaluate_operational_policy

    return evaluate_operational_policy(*args, **kwargs)


SEEDED_DEFECT_KINDS = frozenset({"boundary_shift", "missing_area", "side_inconsistency"})
SYNTHETIC_CASE_KINDS = frozenset({"exact_truth"} | set(SEEDED_DEFECT_KINDS))
DEFAULT_EVALUATOR_ID = "maskfactory.operational_policy.v1"
DEFAULT_EVALUATOR_SHA256 = hashlib.sha256(b"maskfactory.operational_policy.suite.v1").hexdigest()


class OperationalPolicySuiteError(ValueError):
    """Operational policy suite inputs or produced evidence are invalid."""


def build_candidate_scope(
    *,
    candidate_id: str = "operational-suite-candidate",
    label: str = "left_hand",
    risk_bucket: str = "large_parts",
    source_decoded_pixel_sha256: str | None = None,
    output_artifact_identity_sha256s: Sequence[str] | None = None,
    pipeline_fingerprint: str | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    policy = _load_operational_policy()
    get_ontology().label(label, require_enabled=True)
    return {
        "candidate_id": candidate_id,
        "source_decoded_pixel_sha256": (
            source_decoded_pixel_sha256 or hashlib.sha256(b"operational-suite-source").hexdigest()
        ),
        "output_artifact_identity_sha256s": list(
            output_artifact_identity_sha256s
            or [hashlib.sha256(b"operational-suite-output").hexdigest()]
        ),
        "pipeline_fingerprint": (
            pipeline_fingerprint or hashlib.sha256(b"operational-suite-pipeline").hexdigest()
        ),
        "risk_bucket": risk_bucket,
        "label": label,
        "seed": policy["fixed_seed"] if seed is None else seed,
    }


def build_base_mask(root: Path, *, shape: tuple[int, int] = (80, 72)) -> tuple[Path, np.ndarray]:
    height, width = shape
    mask = np.zeros((height, width), dtype=bool)
    mask[height // 5 : (4 * height) // 5, width // 4 : (3 * width) // 4] = True
    path = write_binary_mask(Path(root) / "base.png", mask)
    return path, mask


def build_perturbation_variants(
    root: Path,
    base_mask: np.ndarray,
    *,
    label: str,
    unstable_perturbation: str | None = None,
    side_inconsistent: bool = False,
    roll_shift: int = 8,
) -> list[dict[str, Any]]:
    """Build the five required variants with ontology-aware flip-with-side-swap."""
    if unstable_perturbation is not None and unstable_perturbation not in PERTURBATIONS:
        raise OperationalPolicySuiteError(
            f"unstable perturbation is unknown: {unstable_perturbation}"
        )
    ontology_label = get_ontology().label(label, require_enabled=True)
    swap = ontology_label.swap_partner or label
    out_root = Path(root)
    out_root.mkdir(parents=True, exist_ok=True)
    variants: list[dict[str, Any]] = []
    for perturbation in ("resize", "crop", "color", "prompt", "horizontal_flip"):
        mask = np.flip(base_mask, axis=1) if perturbation == "horizontal_flip" else base_mask
        if unstable_perturbation == perturbation:
            mask = np.roll(mask, roll_shift, axis=1)
        path = write_binary_mask(out_root / f"{perturbation}.png", mask)
        if perturbation == "horizontal_flip":
            reported = label if side_inconsistent else swap
            inverse_aligned = False
        else:
            reported = label
            inverse_aligned = True
        variants.append(
            {
                "perturbation": perturbation,
                "mask_path": path,
                "reported_label": reported,
                "inverse_aligned": inverse_aligned,
            }
        )
    return variants


def build_seeded_defect_synthetic_cases(
    root: Path,
    *,
    label: str = "left_hand",
    shape: tuple[int, int] = (48, 48),
) -> list[dict[str, Any]]:
    """Build exact synthetic truth plus three named seeded-defect metamorphic cases."""
    get_ontology().label(label, require_enabled=True)
    swap = get_ontology().label(label).swap_partner or label
    height, width = shape
    truth = np.zeros((height, width), dtype=bool)
    truth[height // 4 : (3 * height) // 4, width // 3 : (2 * width) // 3] = True
    out_root = Path(root)
    out_root.mkdir(parents=True, exist_ok=True)
    truth_path = write_binary_mask(out_root / "truth.png", truth)
    shifted = np.roll(truth, 3, axis=1)
    missing = truth.copy()
    missing[(2 * height) // 3 : (3 * height) // 4, :] = False
    candidates = {
        "exact_truth": write_binary_mask(out_root / "exact.png", truth),
        "boundary_shift": write_binary_mask(out_root / "shifted.png", shifted),
        "missing_area": write_binary_mask(out_root / "missing.png", missing),
        "side_inconsistency": write_binary_mask(out_root / "side.png", truth),
    }
    return [
        {
            "case_id": f"synthetic-{kind}",
            "case_kind": kind,
            "truth_mask_path": truth_path,
            "candidate_mask_path": candidates[kind],
            "expected_label": label,
            "reported_label": swap if kind == "side_inconsistency" else label,
        }
        for kind in ("exact_truth", "boundary_shift", "missing_area", "side_inconsistency")
    ]


def evaluate_stability_for_suite(
    root: Path,
    *,
    candidate_scope: Mapping[str, Any],
    unstable_perturbation: str | None = None,
    side_inconsistent: bool = False,
) -> dict[str, Any]:
    base_path, base = build_base_mask(Path(root) / "base")
    variants = build_perturbation_variants(
        Path(root) / "variants",
        base,
        label=str(candidate_scope["label"]),
        unstable_perturbation=unstable_perturbation,
        side_inconsistent=side_inconsistent,
    )
    return evaluate_candidate_stability(
        base_path,
        variants,
        candidate_id=str(candidate_scope["candidate_id"]),
        pipeline_fingerprint=str(candidate_scope["pipeline_fingerprint"]),
        risk_bucket=str(candidate_scope["risk_bucket"]),
        label=str(candidate_scope["label"]),
        policy=load_stability_policy(),
    )


def run_operational_policy_evidence_suite(
    root: Path,
    *,
    report_id: str = "operational-policy-suite",
    candidate_scope: Mapping[str, Any] | None = None,
    unstable_perturbation: str | None = None,
    side_inconsistent: bool = False,
    mutate_second_replay: bool = False,
    break_seeded_defect_kind: str | None = None,
    evaluator_id: str = DEFAULT_EVALUATOR_ID,
    evaluator_sha256: str = DEFAULT_EVALUATOR_SHA256,
) -> dict[str, Any]:
    """Evaluate the full operational policy evidence path under a frozen seed."""
    if (
        break_seeded_defect_kind is not None
        and break_seeded_defect_kind not in SYNTHETIC_CASE_KINDS
    ):
        raise OperationalPolicySuiteError(
            f"seeded-defect break kind is unknown: {break_seeded_defect_kind}"
        )
    policy = _load_operational_policy()
    stability_policy = load_stability_policy()
    scope = dict(candidate_scope or build_candidate_scope())
    suite_root = Path(root)
    stability = evaluate_stability_for_suite(
        suite_root / "stability",
        candidate_scope=scope,
        unstable_perturbation=unstable_perturbation,
        side_inconsistent=side_inconsistent,
    )
    synthetic = build_seeded_defect_synthetic_cases(
        suite_root / "synthetic",
        label=str(scope["label"]),
    )
    if break_seeded_defect_kind is not None:
        synthetic = _break_seeded_defect_case(synthetic, break_seeded_defect_kind)
    replay = list(
        _prepare_operational_policy_replay(
            stability,
            synthetic,
            candidate_scope=scope,
            policy=policy,
            stability_policy=stability_policy,
        )
    )
    if mutate_second_replay:
        replay[1] = dict(replay[1])
        replay[1]["decision"] = dict(replay[1]["decision"])
        replay[1]["decision"]["output_artifact_identity_sha256s"] = [
            hashlib.sha256(b"nondeterministic-suite-output").hexdigest()
        ]
        from maskfactory.autonomy.risk_buckets import canonical_sha256

        replay[1]["decision_sha256"] = canonical_sha256(replay[1]["decision"])
    return _evaluate_operational_policy(
        stability,
        synthetic,
        replay,
        report_id=report_id,
        candidate_scope=scope,
        policy=policy,
        stability_policy=stability_policy,
        evaluator_id=evaluator_id,
        evaluator_sha256=evaluator_sha256,
    )


def _break_seeded_defect_case(
    cases: Sequence[Mapping[str, Any]], kind: str
) -> list[dict[str, Any]]:
    """Corrupt one metamorphic case so the synthetic self-test must fail closed."""
    broken: list[dict[str, Any]] = []
    for raw in cases:
        row = dict(raw)
        if row["case_kind"] != kind:
            broken.append(row)
            continue
        if kind == "exact_truth":
            # Exact truth must match; report the swap partner to force detection failure.
            swap = get_ontology().label(str(row["expected_label"])).swap_partner
            row["reported_label"] = swap or f"{row['expected_label']}_broken"
        elif kind == "side_inconsistency":
            # Seeded side defect must be reported as the swap partner.
            row["reported_label"] = row["expected_label"]
        else:
            # Seeded geometry defects must differ from truth; restore exact match.
            row["candidate_mask_path"] = row["truth_mask_path"]
        broken.append(row)
    return broken


__all__ = [
    "DEFAULT_EVALUATOR_ID",
    "DEFAULT_EVALUATOR_SHA256",
    "OperationalPolicySuiteError",
    "PERTURBATIONS",
    "SEEDED_DEFECT_KINDS",
    "SYNTHETIC_CASE_KINDS",
    "build_base_mask",
    "build_candidate_scope",
    "build_perturbation_variants",
    "build_seeded_defect_synthetic_cases",
    "evaluate_stability_for_suite",
    "run_operational_policy_evidence_suite",
]
