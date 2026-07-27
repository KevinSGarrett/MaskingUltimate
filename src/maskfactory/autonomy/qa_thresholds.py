"""Fail-closed per-label/context QA threshold registry for autonomous gold."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from ..io.hashing import sha256_file
from ..ontology import Ontology, load_ontology
from ..validation import ArtifactValidationError, require_valid_document

DEFAULT_REGISTRY = Path("configs/autonomous_gold_qa_thresholds.yaml")
EXPECTED_TOP_LEVEL = {
    "schema_version",
    "registry_id",
    "qualification_status",
    "authority_eligible",
    "ontology_path",
    "metric_catalog",
    "profiles",
    "contexts",
    "thin_structure_labels",
    "calibration",
}
PROFILE_FIELDS = {
    "default_max_components",
    "maximum_holes",
    "minimum_owner_containment",
    "maximum_protected_overlap",
    "maximum_exclusive_overlap",
    "maximum_cross_person_bleed",
    "minimum_boundary_edge_alignment",
    "minimum_boundary_precision",
    "minimum_boundary_recall",
    "minimum_boundary_f_score",
    "maximum_symmetric_boundary_distance_px",
    "maximum_p95_edge_error_px",
    "maximum_underfill_fraction",
    "maximum_overfill_fraction",
    "maximum_leakage_fraction",
    "maximum_missing_visible_fraction",
    "maximum_unsupported_fraction",
    "minimum_thin_structure_retention",
}
CONTEXT_FIELDS = {
    "expected_presence_policy",
    "component_allowance",
    "edge_error_allowance_px",
    "cross_person_bleed_ceiling",
}
REQUIRED_METRICS = {
    "expected_presence",
    "area_image",
    "area_person",
    "area_parent",
    "area_proposal",
    "connected_components",
    "holes",
    "owner_containment",
    "protected_region_overlap",
    "mutually_exclusive_overlap",
    "cross_person_bleed",
    "laterality_consistency",
    "front_back_consistency",
    "parent_child_coverage",
    "atomic_map_exclusivity",
    "boundary_edge_alignment",
    "boundary_precision",
    "boundary_recall",
    "boundary_f_score",
    "symmetric_boundary_distance",
    "p95_edge_error",
    "underfill",
    "overfill",
    "leakage",
    "missing_visible_area",
    "unsupported_pixels",
    "thin_structure_preservation",
    "topology_plausibility",
    "transform_roundtrip",
    "perturbation_stability",
    "duplicate_person",
    "duplicate_mask",
    "complete_map_recomposition",
}


class QaThresholdRegistryError(ValueError):
    """Registry or lookup is incomplete, ambiguous, drifted, or non-authorizing."""


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_qa_threshold_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    source = Path(path)
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise QaThresholdRegistryError(f"cannot load QA threshold registry: {exc}") from exc
    if not isinstance(document, dict) or set(document) != EXPECTED_TOP_LEVEL:
        raise QaThresholdRegistryError("QA threshold registry has the wrong top-level contract")
    if document["schema_version"] != "0.1.0" or document["authority_eligible"] is not False:
        raise QaThresholdRegistryError("candidate registry must remain non-authorizing")
    if document["qualification_status"] != "uncalibrated_no_gold_authority":
        raise QaThresholdRegistryError("candidate registry qualification status is invalid")
    if set(document["metric_catalog"]) != REQUIRED_METRICS or len(
        document["metric_catalog"]
    ) != len(REQUIRED_METRICS):
        raise QaThresholdRegistryError("QA metric coverage is incomplete or duplicated")
    if set(document["profiles"]) != {
        "atomic_exclusive",
        "derived_union",
        "material",
        "region_band",
        "protected_qa",
        "projected_amodal",
    }:
        raise QaThresholdRegistryError("QA mask-type profile coverage is incomplete")
    fraction_fields = PROFILE_FIELDS - {
        "default_max_components",
        "maximum_holes",
        "maximum_symmetric_boundary_distance_px",
        "maximum_p95_edge_error_px",
    }
    for name, profile in document["profiles"].items():
        if not isinstance(profile, Mapping) or set(profile) != PROFILE_FIELDS:
            raise QaThresholdRegistryError(f"QA profile contract is invalid: {name}")
        for field, value in profile.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or float(value) < 0:
                raise QaThresholdRegistryError(f"QA profile value is invalid: {name}/{field}")
        if any(float(profile[field]) > 1 for field in fraction_fields):
            raise QaThresholdRegistryError(f"QA profile fraction is outside [0,1]: {name}")
    if "default" not in document["contexts"]:
        raise QaThresholdRegistryError("default QA context is missing")
    for name, context in document["contexts"].items():
        if not isinstance(context, Mapping) or set(context) != CONTEXT_FIELDS:
            raise QaThresholdRegistryError(f"QA context contract is invalid: {name}")
        if (
            not isinstance(context["expected_presence_policy"], str)
            or not context["expected_presence_policy"]
        ):
            raise QaThresholdRegistryError(f"QA context presence policy is invalid: {name}")
        if (
            not isinstance(context["component_allowance"], int)
            or context["component_allowance"] < 0
        ):
            raise QaThresholdRegistryError(f"QA context component allowance is invalid: {name}")
        if (
            float(context["edge_error_allowance_px"]) < 0
            or float(context["cross_person_bleed_ceiling"]) != 0
        ):
            raise QaThresholdRegistryError(f"QA context safety ceiling is invalid: {name}")
    calibration = document["calibration"]
    if (
        calibration.get("required") is not True
        or calibration.get("evidence_sha256") is not None
        or calibration.get("promotion_rule") != "new_immutable_registry_version_only"
    ):
        raise QaThresholdRegistryError(
            "uncalibrated registry must require future immutable calibration"
        )
    ontology = load_ontology(document["ontology_path"])
    thin_labels = document["thin_structure_labels"]
    if (
        not isinstance(thin_labels, list)
        or len(thin_labels) != len(set(thin_labels))
        or any(not isinstance(name, str) or not name for name in thin_labels)
    ):
        raise QaThresholdRegistryError("thin-structure label coverage is invalid")
    try:
        for name in thin_labels:
            ontology.label(name, require_enabled=True)
    except ValueError as exc:
        raise QaThresholdRegistryError("thin-structure label is not enabled in ontology") from exc
    document["registry_file_sha256"] = sha256_file(source)
    return document


def resolve_qa_thresholds(
    label_name: str,
    *,
    contexts: Sequence[str] = ("default",),
    registry: Mapping[str, Any] | None = None,
    ontology: Ontology | None = None,
) -> dict[str, Any]:
    policy = dict(registry) if registry is not None else load_qa_threshold_registry()
    onto = ontology or load_ontology(policy["ontology_path"])
    label = onto.label(label_name, require_enabled=True)
    if not contexts or len(set(contexts)) != len(contexts):
        raise QaThresholdRegistryError("QA contexts are empty or duplicated")
    unknown = set(contexts) - set(policy["contexts"])
    if unknown:
        raise QaThresholdRegistryError(f"unregistered QA contexts: {sorted(unknown)}")
    profile = dict(policy["profiles"][label.mask_type])
    area = label.expected_area_pct_range or (0.0, 100.0)
    max_components = int(label.max_components or profile["default_max_components"])
    edge_allowance = 0.0
    for name in contexts:
        max_components += int(policy["contexts"][name]["component_allowance"])
        edge_allowance = max(
            edge_allowance, float(policy["contexts"][name]["edge_error_allowance_px"])
        )
    excluded = {
        "default_max_components",
        "maximum_holes",
        "maximum_symmetric_boundary_distance_px",
        "maximum_p95_edge_error_px",
    }
    resolved = {
        "schema_version": "0.1.0",
        "registry_id": policy["registry_id"],
        "registry_file_sha256": policy["registry_file_sha256"],
        "ontology_version": onto.version,
        "ontology_sha256": sha256_file(onto.source),
        "label": label.name,
        "label_id": label.id,
        "mask_type": label.mask_type,
        "map": label.map,
        "side": label.side,
        "parent_union": label.parent_union,
        "exclusivity_group": label.exclusivity_group,
        "contexts": list(contexts),
        "expected_presence_policy": [
            policy["contexts"][name]["expected_presence_policy"] for name in contexts
        ],
        "area_image_pct_range": [float(area[0]), float(area[1])],
        "maximum_components": max_components,
        "maximum_holes": int(profile["maximum_holes"]),
        "maximum_symmetric_boundary_distance_px": float(
            profile["maximum_symmetric_boundary_distance_px"]
        )
        + edge_allowance,
        "maximum_p95_edge_error_px": float(profile["maximum_p95_edge_error_px"]) + edge_allowance,
        "thin_structure": label.name in set(policy["thin_structure_labels"]),
        "thresholds": {key: value for key, value in profile.items() if key not in excluded},
        "hard_invariants": {
            "strict_binary_values": [0, 255],
            "cross_person_bleed_ceiling": 0.0,
            "transform_roundtrip_required": True,
            "duplicate_person_forbidden": True,
            "duplicate_mask_forbidden": True,
            "complete_map_recomposition_required": True,
        },
        "qualification_status": policy["qualification_status"],
        "authority_eligible": False,
    }
    resolved["resolved_sha256"] = _canonical_sha256(resolved)
    try:
        require_valid_document(resolved, "autonomous_gold_qa_threshold_resolution")
    except ArtifactValidationError as exc:
        raise QaThresholdRegistryError(f"resolved QA threshold contract is invalid: {exc}") from exc
    return resolved


def expand_registry(*, registry_path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    policy = load_qa_threshold_registry(registry_path)
    ontology = load_ontology(policy["ontology_path"])
    labels = [
        resolve_qa_thresholds(label.name, registry=policy, ontology=ontology)
        for label in ontology.labels
        if label.enabled
    ]
    result = {
        "schema_version": "0.1.0",
        "registry_id": policy["registry_id"],
        "registry_file_sha256": policy["registry_file_sha256"],
        "ontology_sha256": sha256_file(ontology.source),
        "enabled_label_count": len(labels),
        "labels": labels,
        "qualification_status": policy["qualification_status"],
        "authority_eligible": False,
    }
    result["resolved_registry_sha256"] = _canonical_sha256(result)
    return result


def require_gold_authority(registry: Mapping[str, Any]) -> None:
    if (
        registry.get("authority_eligible") is not True
        or registry.get("qualification_status") != "qualified_for_autonomous_gold"
    ):
        raise QaThresholdRegistryError(
            "QA threshold registry is not qualified for autonomous-gold authority"
        )


__all__ = [
    "DEFAULT_REGISTRY",
    "QaThresholdRegistryError",
    "expand_registry",
    "load_qa_threshold_registry",
    "require_gold_authority",
    "resolve_qa_thresholds",
]
