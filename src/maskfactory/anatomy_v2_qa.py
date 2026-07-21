"""Inactive hard QA for the proposed body_parts_v2 anatomy extension.

The checks in this module implement QC-V2-001..010 and QC-V2-012 without
activating the ontology.  Results are QA evidence only: they cannot author a
mask, approve gold, clear a block, or enable production routing.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from scipy import ndimage

from .anatomy_v2_drafting import NEW_LABELS
from .ontology import load_ontology
from .ontology_v2 import DEFAULT_ONTOLOGY_V2, load_v2_proposal
from .ontology_v2_manifest import V2_NULL_MASK_STATES, V2_REVIEW_STATES, V2_VISIBLE_STATES
from .qa.checks import QcResult

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "anatomy_v2_qa.yaml"
QC_IDS = tuple(f"QC-V2-{index:03d}" for index in (*range(1, 11), 12))
CHEST_CHILDREN = {
    "left_breast_full": ("left_breast", "left_areola", "left_nipple"),
    "right_breast_full": ("right_breast", "right_areola", "right_nipple"),
}
PELVIC_CHILDREN = (
    "pelvic_region",
    "vulva",
    "penis_shaft",
    "glans_penis",
    "left_scrotal_region",
    "right_scrotal_region",
)


class AnatomyV2QaError(ValueError):
    """The inactive v2 QA inputs or policy are malformed."""


@dataclass(frozen=True)
class AnatomyV2QaInputs:
    manifest: Mapping[str, Any]
    part_map: np.ndarray
    material_map: np.ndarray
    atomic_masks: Mapping[str, np.ndarray]
    derived_masks: Mapping[str, np.ndarray]
    ambiguity_masks: Mapping[str, np.ndarray] = field(default_factory=dict)
    review_rois: Mapping[str, np.ndarray] = field(default_factory=dict)
    label_provenance: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    projected_or_amodal_labels: frozenset[str] = frozenset()
    midline_x: int = 0
    character_left_is_lower_x: bool = True


@dataclass(frozen=True)
class ClothedSweepCase:
    case_id: str
    part_map: np.ndarray
    material_map: np.ndarray
    reviewed_clothing_roi: np.ndarray


def load_anatomy_v2_qa_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AnatomyV2QaError(f"cannot load anatomy-v2 QA config: {exc}") from exc
    if not isinstance(document, dict):
        raise AnatomyV2QaError("anatomy-v2 QA config root must be an object")
    if (
        document.get("config_version") != "1.0.0"
        or document.get("ontology_version") != "body_parts_v2"
        or document.get("activation_status") != "approved_design_not_active"
        or tuple(document.get("hard_checks", ())) != QC_IDS
    ):
        raise AnatomyV2QaError("anatomy-v2 QA identity/check list drifted")
    governance = document.get("governance")
    if not isinstance(governance, dict) or governance != {
        "permitted_source_origins": [
            "generated",
            "owned_photo",
            "licensed",
            "consented_subject",
        ],
        "ignore_index": 255,
        "production_activation_allowed": False,
    }:
        raise AnatomyV2QaError("anatomy-v2 QA governance drifted")
    if document.get("clothing_material_ids") != [3, 4, 5, 6, 7, 10, 11, 12, 15]:
        raise AnatomyV2QaError("anatomy-v2 clothing material authority drifted")
    vlm = document.get("vlm")
    if not isinstance(vlm, dict) or (
        vlm.get("role") != "qa_only"
        or vlm.get("may_author_masks") is not False
        or vlm.get("may_approve_gold") is not False
        or vlm.get("may_clear_blocks") is not False
        or tuple(vlm.get("canonical_anatomy_vocabulary", ())) != NEW_LABELS
        or tuple(vlm.get("problem_types", ()))
        != (
            "anatomy_boundary",
            "anatomy_clothing_false_positive",
            "anatomy_left_right_swap",
            "anatomy_state_inconsistency",
            "anatomy_topology",
        )
    ):
        raise AnatomyV2QaError("anatomy-v2 VLM vocabulary/governance drifted")
    aliases = set(load_v2_proposal()["aliases"])
    if aliases & set(vlm["canonical_anatomy_vocabulary"]):
        raise AnatomyV2QaError("anatomy-v2 VLM vocabulary contains aliases")
    return document


def run_anatomy_v2_qc(
    inputs: AnatomyV2QaInputs,
    *,
    config_path: Path | str = DEFAULT_CONFIG,
    ontology_path: Path | str = DEFAULT_ONTOLOGY_V2,
) -> tuple[QcResult, ...]:
    """Run the twelve inactive hard checks and always return one result per ID."""
    config = load_anatomy_v2_qa_config(config_path)
    ontology = load_ontology(ontology_path)
    if ontology.version != "body_parts_v2":
        raise AnatomyV2QaError("anatomy-v2 QA requires the inactive body_parts_v2 ontology")
    part, material, atomics, derived, ambiguity, rois = _prepare(inputs, ontology)
    parts = inputs.manifest.get("parts")
    part_entries = parts if isinstance(parts, Mapping) else {}
    expected = {
        label.name: int(label.id)
        for label in ontology.labels_for_map("part", enabled_only=True)
        if label.id is not None
    }
    return (
        _qc001(inputs.manifest, part_entries, expected),
        _qc002(part_entries, atomics, ambiguity, expected),
        _qc003(part, atomics, expected),
        _qc004(atomics, inputs.midline_x, inputs.character_left_is_lower_x),
        _qc005(atomics, derived),
        _qc006(atomics, derived),
        _qc007(atomics, part_entries),
        _qc008(
            atomics, part_entries, ambiguity, inputs.midline_x, inputs.character_left_is_lower_x
        ),
        _qc009(part_entries, atomics, material, rois, set(config["clothing_material_ids"])),
        _qc010(atomics, part_entries, inputs.label_provenance, inputs.projected_or_amodal_labels),
        _qc012(inputs, part, expected),
    )


def clothed_false_positive_sweep(
    cases: tuple[ClothedSweepCase, ...],
    *,
    config_path: Path | str = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Require zero anatomy pixels in explicitly reviewed clothing regions."""
    config = load_anatomy_v2_qa_config(config_path)
    if not cases:
        raise AnatomyV2QaError("clothed false-positive sweep requires at least one reviewed case")
    garment_ids = set(config["clothing_material_ids"])
    records = []
    seen = set()
    for case in cases:
        if not case.case_id or case.case_id in seen:
            raise AnatomyV2QaError("clothed sweep case IDs must be nonempty and unique")
        seen.add(case.case_id)
        part = _map(case.part_map, "part_map")
        material = _matching_map(case.material_map, part, "material_map")
        roi = _matching_mask(case.reviewed_clothing_roi, part, "reviewed_clothing_roi")
        clothing = roi & np.isin(material, tuple(garment_ids))
        if not clothing.any():
            raise AnatomyV2QaError(
                f"clothed sweep case lacks reviewed garment pixels: {case.case_id}"
            )
        anatomy = roi & np.isin(part, tuple(range(56, 65)))
        records.append(
            {
                "case_id": case.case_id,
                "reviewed_clothing_pixels": int(clothing.sum()),
                "anatomy_false_positive_pixels": int(anatomy.sum()),
                "false_positive_rate": float(anatomy.sum() / clothing.sum()),
                "passed": not anatomy.any(),
            }
        )
    return {
        "schema_version": "1.0.0",
        "ontology_version": "body_parts_v2",
        "activation_status": "approved_design_not_active",
        "authority": "qa_only",
        "case_count": len(records),
        "cases": records,
        "passed": all(record["passed"] for record in records),
        "production_activation_granted": False,
    }


def write_anatomy_v2_qa_report(
    path: Path,
    results: tuple[QcResult, ...],
    *,
    clothed_sweep: Mapping[str, Any] | None = None,
) -> Path:
    if tuple(result.qc_id for result in results) != QC_IDS:
        raise AnatomyV2QaError("anatomy-v2 QA report requires the eleven active v2 checks")
    if clothed_sweep is not None and type(clothed_sweep.get("passed")) is not bool:
        raise AnatomyV2QaError("anatomy-v2 QA clothed sweep requires an exact passed boolean")
    passed = all(result.passed for result in results) and (
        clothed_sweep is None or clothed_sweep["passed"] is True
    )
    document = {
        "schema_version": "1.0.0",
        "ontology_version": "body_parts_v2",
        "activation_status": "approved_design_not_active",
        "authority": "qa_only",
        "checks": [
            {
                "id": result.qc_id,
                "name": result.name,
                "result": "pass" if result.passed else "fail",
                "detail": result.detail,
                "severity": result.severity,
            }
            for result in results
        ],
        "overall": "pass" if passed else "fail",
        "clothed_false_positive_sweep": dict(clothed_sweep) if clothed_sweep else None,
        "may_author_masks": False,
        "may_approve_gold": False,
        "may_clear_blocks": False,
        "production_activation_granted": False,
    }
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _prepare(inputs, ontology):
    part = _map(inputs.part_map, "part_map")
    material = _matching_map(inputs.material_map, part, "material_map")
    if not 0 <= inputs.midline_x < part.shape[1]:
        raise AnatomyV2QaError("anatomy-v2 QA midline is outside the frame")
    canonical = {label.name for label in ontology.labels_for_map("part", enabled_only=True)}
    atomics = {
        name: _matching_mask(value, part, f"atomic_masks/{name}")
        for name, value in inputs.atomic_masks.items()
    }
    missing = sorted(canonical - set(atomics))
    if missing:
        raise AnatomyV2QaError("anatomy-v2 QA atomic masks missing: " + ", ".join(missing))
    derived = {
        name: _matching_mask(value, part, f"derived_masks/{name}")
        for name, value in inputs.derived_masks.items()
    }
    ambiguity = {
        name: _matching_mask(value, part, f"ambiguity_masks/{name}")
        for name, value in inputs.ambiguity_masks.items()
    }
    rois = {
        name: _matching_mask(value, part, f"review_rois/{name}")
        for name, value in inputs.review_rois.items()
    }
    return part, material, atomics, derived, ambiguity, rois


def _qc001(manifest, entries, expected):
    missing = sorted(set(expected) - set(entries))
    approved = manifest.get("workflow_status") in {"approved_gold", "exported"}
    unreviewed = sorted(
        name
        for name in set(expected) & set(entries)
        if isinstance(entries[name], Mapping)
        and entries[name].get("visibility") == "unreviewed_for_v2"
    )
    wrong_version = approved and manifest.get("reviewed_ontology_version") != "body_parts_v2"
    passed = not missing and not (approved and unreviewed) and not wrong_version
    return QcResult(
        "QC-V2-001",
        "state_completeness",
        passed,
        f"missing={missing}, approved_unreviewed={unreviewed if approved else []}, wrong_version={wrong_version}",
    )


def _qc002(entries, atomics, ambiguity, expected):
    failures = []
    for name, label_id in expected.items():
        entry = entries.get(name)
        state = entry.get("visibility") if isinstance(entry, Mapping) else None
        mask = atomics[name]
        if state not in V2_REVIEW_STATES and not (label_id <= 55 and state == "n/a"):
            failures.append(f"{name}:invalid_state={state}")
            continue
        if state in V2_VISIBLE_STATES and not mask.any():
            failures.append(f"{name}:visible_without_mask")
        if state in V2_NULL_MASK_STATES | {"ambiguous_do_not_use", "n/a"} and mask.any():
            failures.append(f"{name}:null_state_with_mask")
        if state == "ambiguous_do_not_use" and not ambiguity.get(name, np.zeros_like(mask)).any():
            failures.append(f"{name}:ambiguity_without_ignore")
    return QcResult("QC-V2-002", "state_mask_consistency", not failures, f"violations={failures}")


def _qc003(part, atomics, expected):
    failures = []
    claimed = np.zeros(part.shape, dtype=bool)
    for name, label_id in sorted(expected.items(), key=lambda item: item[1]):
        mask = atomics[name]
        overlap = claimed & mask
        if overlap.any():
            failures.append(f"{name}:overlap={int(overlap.sum())}")
        claimed |= mask
        expected_mask = part == label_id
        if not np.array_equal(mask, expected_mask):
            failures.append(f"{name}:map_mismatch={int(np.count_nonzero(mask ^ expected_mask))}")
    return QcResult("QC-V2-003", "atomic_exclusivity", not failures, f"violations={failures}")


def _qc004(atomics, midline, left_lower):
    failures = []
    radius = max(1, round(atomics["left_areola"].shape[1] / 512))
    for side in ("left", "right"):
        areola = atomics[f"{side}_areola"]
        nipple = atomics[f"{side}_nipple"]
        if areola.any() and nipple.any():
            near = ndimage.binary_dilation(areola, iterations=radius)
            if np.any(nipple & ~near):
                failures.append(f"{side}:nipple_not_adjacent_or_enclosed")
        for name, mask in ((f"{side}_areola", areola), (f"{side}_nipple", nipple)):
            if mask.any() and _wrong_side(mask, side, midline, left_lower).any():
                failures.append(f"{name}:crosses_midline")
    return QcResult("QC-V2-004", "nipple_areola_topology", not failures, f"violations={failures}")


def _qc005(atomics, derived):
    failures = []
    for full_name, children in CHEST_CHILDREN.items():
        child_union = np.logical_or.reduce([atomics[name] for name in children[1:]])
        if np.any(atomics[children[0]] & child_union):
            failures.append(f"{children[0]}:child_overlap")
        expected_full = np.logical_or.reduce([atomics[name] for name in children])
        if full_name not in derived or not np.array_equal(derived[full_name], expected_full):
            failures.append(f"{full_name}:restoration_mismatch")
    return QcResult("QC-V2-005", "breast_carveout", not failures, f"violations={failures}")


def _qc006(atomics, derived):
    genital = np.logical_or.reduce([atomics[name] for name in PELVIC_CHILDREN[1:]])
    expected = atomics["pelvic_region"] | genital
    failures = []
    if np.any(atomics["pelvic_region"] & genital):
        failures.append("pelvic_region:genital_overlap")
    if "pelvic_anatomy_visible" not in derived or not np.array_equal(
        derived["pelvic_anatomy_visible"], expected
    ):
        failures.append("pelvic_anatomy_visible:restoration_mismatch")
    return QcResult("QC-V2-006", "genital_carveout", not failures, f"violations={failures}")


def _qc007(atomics, entries):
    shaft, glans = atomics["penis_shaft"], atomics["glans_penis"]
    failures = []
    if np.any(shaft & glans):
        failures.append("shaft_glans_overlap")
    states = {
        name: entries.get(name, {}).get("visibility") for name in ("penis_shaft", "glans_penis")
    }
    honestly_occluded = "occluded" in states.values()
    if shaft.any() and glans.any() and not honestly_occluded:
        if not np.any(ndimage.binary_dilation(shaft, iterations=1) & glans):
            failures.append("shaft_glans_not_adjacent")
        if ndimage.label(shaft | glans)[1] != 1:
            failures.append("penis_visible_not_one_component")
    return QcResult("QC-V2-007", "penis_topology", not failures, f"violations={failures}")


def _qc008(atomics, entries, ambiguity, midline, left_lower):
    failures = []
    for side in ("left", "right"):
        name = f"{side}_scrotal_region"
        if atomics[name].any() and _wrong_side(atomics[name], side, midline, left_lower).any():
            failures.append(f"{name}:wrong_character_side")
        if (
            entries.get(name, {}).get("visibility") == "ambiguous_do_not_use"
            and not ambiguity.get(name, np.zeros_like(atomics[name])).any()
        ):
            failures.append(f"{name}:unresolved_without_ambiguity")
    return QcResult("QC-V2-008", "scrotal_side_integrity", not failures, f"violations={failures}")


def _qc009(entries, atomics, material, rois, garment_ids):
    failures = []
    for name in NEW_LABELS:
        if entries.get(name, {}).get("visibility") != "occluded_by_clothing":
            continue
        if atomics[name].any():
            failures.append(f"{name}:covered_state_has_mask")
        roi = rois.get(name)
        if roi is None or not np.any(roi & np.isin(material, tuple(garment_ids))):
            failures.append(f"{name}:no_clothing_evidence")
    return QcResult("QC-V2-009", "clothing_authority", not failures, f"violations={failures}")


def _qc010(atomics, entries, provenance, projected_labels):
    failures = []
    for name in NEW_LABELS:
        if not atomics[name].any():
            continue
        record = provenance.get(name, {})
        authority = str(record.get("authority", ""))
        if (
            name in projected_labels
            or "projected" in authority
            or "amodal" in authority
            or record.get("visible_surface_only") is not True
            or entries.get(name, {}).get("visibility") not in V2_VISIBLE_STATES | {"occluded"}
        ):
            failures.append(name)
    return QcResult("QC-V2-010", "no_hidden_authority_leak", not failures, f"violations={failures}")


def _qc012(inputs, part, expected):
    aliases = set(load_v2_proposal()["aliases"])
    namespaces = (
        set(inputs.manifest.get("parts", {})),
        set(inputs.atomic_masks),
        set(inputs.ambiguity_masks),
        set(inputs.review_rois),
        set(inputs.label_provenance),
        set(inputs.projected_or_amodal_labels),
    )
    persisted = sorted(set().union(*(namespace & aliases for namespace in namespaces)))
    values = set(np.unique(part).tolist())
    invalid_ids = sorted(values - set(expected.values()) - {255})
    return QcResult(
        "QC-V2-012",
        "alias_canonicalization",
        not persisted and not invalid_ids,
        f"persisted_aliases={persisted}, invalid_part_ids={invalid_ids}",
    )


def _wrong_side(mask, side, midline, left_lower):
    xx = np.indices(mask.shape)[1]
    lower = xx < midline
    expected = lower if (side == "left") == left_lower else ~lower
    return mask & ~expected


def _map(value, name):
    array = np.asarray(value)
    if array.ndim != 2 or not np.issubdtype(array.dtype, np.integer):
        raise AnatomyV2QaError(f"anatomy-v2 QA {name} must be a 2-D integer map")
    if array.size and (int(array.min()) < 0 or int(array.max()) > 255):
        raise AnatomyV2QaError(f"anatomy-v2 QA {name} values must be in 0..255")
    return array.copy()


def _matching_map(value, reference, name):
    array = np.asarray(value)
    if (
        array.ndim != 2
        or array.shape != reference.shape
        or not np.issubdtype(array.dtype, np.integer)
    ):
        raise AnatomyV2QaError(f"anatomy-v2 QA {name} dimensions differ")
    return array.copy()


def _matching_mask(value, reference, name):
    array = np.asarray(value)
    if array.ndim != 2 or array.shape != reference.shape:
        raise AnatomyV2QaError(f"anatomy-v2 QA {name} dimensions differ")
    return array.astype(bool)
