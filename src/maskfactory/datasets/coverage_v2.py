"""Inactive body_parts_v2 per-class coverage and acquisition authority."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from ..models.ontology_contract import V2_ONTOLOGY_VERSION, V2_PART_CLASS_NAMES
from ..ontology_v2_manifest import V2_REVIEW_STATES
from ..validation import validate_document
from .coverage import POSES, VIEWS

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY = ROOT / "configs" / "ontology_v2_operations.yaml"
OCCLUSION_CONTEXTS = (
    "none_visible",
    "self_occlusion",
    "other_body_part",
    "hair",
    "prop",
    "clothing",
    "frame_crop",
    "interperson_contact",
)
FAILURE_ACQUISITION_CATEGORIES = {
    "v2_boundary_loose": "boundary",
    "v2_boundary_tight": "boundary",
    "v2_areola_nipple_boundary": "boundary",
    "v2_shaft_glans_boundary": "boundary",
    "v2_lr_swap": "side",
    "v2_scrotal_side_ambiguous": "side",
    "v2_clothing_false_positive": "clothing",
    "v2_clothing_authority_conflict": "clothing",
    "v2_hidden_anatomy_leak": "clothing",
}
SAFE_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


class OntologyV2OperationsError(ValueError):
    """Coverage or acquisition evidence violates the inactive v2 contract."""


def load_v2_operations_policy(path: Path | str = DEFAULT_POLICY) -> dict[str, Any]:
    """Load and prove the complete closed-vocabulary operations policy."""
    source = Path(path)
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OntologyV2OperationsError(
            f"cannot load ontology-v2 operations policy: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise OntologyV2OperationsError("ontology-v2 operations policy root must be an object")
    exact_root = {
        "schema_version": "1.0.0",
        "ontology_version": V2_ONTOLOGY_VERSION,
        "activation_status": "approved_design_not_active",
    }
    for key, expected in exact_root.items():
        if document.get(key) != expected:
            raise OntologyV2OperationsError(f"operations policy {key} must equal {expected!r}")
    coverage = document.get("coverage")
    if not isinstance(coverage, dict):
        raise OntologyV2OperationsError("operations policy coverage must be an object")
    if coverage.get("foreground_class_ids") != [1, 65] or coverage.get("excluded_class_ids") != {
        0: "background_is_not_a_body_part_acquisition_target"
    }:
        raise OntologyV2OperationsError("coverage must target exact foreground IDs 1..65")
    minimum = coverage.get("minimum_clear_positive_instances_per_new_class")
    target = coverage.get("target_clear_positive_instances_per_new_class")
    if not isinstance(minimum, int) or not isinstance(target, int) or not 50 <= minimum <= target:
        raise OntologyV2OperationsError("clear-positive targets must preserve the 50..100 gate")
    dimensions = coverage.get("dimensions")
    expected_dimensions = {
        "review_state": tuple(sorted(V2_REVIEW_STATES)),
        "view": VIEWS,
        "pose": POSES,
        "occlusion_context": OCCLUSION_CONTEXTS,
    }
    if not isinstance(dimensions, dict) or set(dimensions) != set(expected_dimensions):
        raise OntologyV2OperationsError("coverage dimensions are incomplete")
    for dimension, expected_values in expected_dimensions.items():
        values = dimensions.get(dimension)
        if not isinstance(values, dict) or set(values) != set(expected_values):
            raise OntologyV2OperationsError(f"coverage {dimension} vocabulary is not exact")
        if any(not isinstance(value, int) or value < 0 for value in values.values()):
            raise OntologyV2OperationsError(f"coverage {dimension} targets must be nonnegative")
    if dimensions["review_state"]["unreviewed_for_v2"] != 0:
        raise OntologyV2OperationsError("unreviewed_for_v2 target must remain zero")

    mappings = document.get("failure_acquisition")
    if not isinstance(mappings, dict) or set(mappings) != set(FAILURE_ACQUISITION_CATEGORIES):
        raise OntologyV2OperationsError("failure-acquisition reason vocabulary is not exact")
    actions = set()
    for reason, expected_category in FAILURE_ACQUISITION_CATEGORIES.items():
        mapping = mappings[reason]
        if not isinstance(mapping, dict) or mapping.get("category") != expected_category:
            raise OntologyV2OperationsError(f"failure mapping category mismatch: {reason}")
        action = mapping.get("action")
        if not isinstance(action, str) or not SAFE_SLUG.fullmatch(action) or action in actions:
            raise OntologyV2OperationsError(
                f"failure mapping action is unsafe or duplicate: {reason}"
            )
        actions.add(action)
        _require_subset(mapping, "required_review_states", V2_REVIEW_STATES, reason)
        _require_subset(mapping, "required_views", VIEWS, reason)
        _require_subset(
            mapping,
            "required_occlusion_contexts",
            OCCLUSION_CONTEXTS,
            reason,
        )
    invariants = document.get("acquisition_invariants")
    expected_invariants = {
        "destination": "hard_case_holdout",
        "authority_resolution_required": True,
        "mandatory_human_review": False,
        "governed_source_required": True,
        "fabricated_positive_allowed": False,
        "aliases_allowed_in_failure_queue": False,
        "unreviewed_counts_as_negative": False,
        "projected_or_amodal_counts_as_positive": False,
    }
    if invariants != expected_invariants:
        raise OntologyV2OperationsError("acquisition invariants differ from Document 18")
    return document


def _require_subset(
    mapping: Mapping[str, Any], key: str, allowed: Iterable[str], reason: str
) -> None:
    values = mapping.get(key)
    if (
        not isinstance(values, list)
        or not values
        or len(values) != len(set(values))
        or not set(values) <= set(allowed)
    ):
        raise OntologyV2OperationsError(f"failure mapping {reason} has invalid {key}")


def build_v2_coverage_matrix(
    packages: Iterable[Mapping[str, Any]],
    *,
    policy_path: Path | str = DEFAULT_POLICY,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Count every foreground class against every governed v2 coverage dimension."""
    policy = load_v2_operations_policy(policy_path)
    dimensions = policy["coverage"]["dimensions"]
    foreground = V2_PART_CLASS_NAMES[1:]
    counts = {
        (label, dimension, value): 0
        for label in foreground
        for dimension, targets in dimensions.items()
        for value in targets
    }
    new_class_positive_counts = {label: 0 for label in V2_PART_CLASS_NAMES[56:]}
    package_count = 0
    for package in packages:
        if _package_status(package) not in {"approved_gold", "human_approved_gold"}:
            continue
        if package.get("reviewed_ontology_version") != V2_ONTOLOGY_VERSION:
            raise OntologyV2OperationsError(
                "approved coverage package is not reviewed as body_parts_v2"
            )
        parts = package.get("parts")
        if not isinstance(parts, Mapping) or set(parts) != set(V2_PART_CLASS_NAMES):
            raise OntologyV2OperationsError(
                "approved coverage package must contain exact IDs 0..65"
            )
        view = _person_value(package, "view")
        poses = _person_value(package, "pose_tags")
        if (
            view not in VIEWS
            or not isinstance(poses, list)
            or not poses
            or not set(poses) <= set(POSES)
        ):
            raise OntologyV2OperationsError(
                "approved coverage package has invalid view/pose evidence"
            )
        contexts = package.get("coverage_contexts")
        if not isinstance(contexts, Mapping) or set(contexts) != set(foreground):
            raise OntologyV2OperationsError("coverage_contexts must cover every foreground class")
        for label in foreground:
            entry = parts[label]
            state = entry.get("visibility") if isinstance(entry, Mapping) else None
            if state not in V2_REVIEW_STATES or state == "unreviewed_for_v2":
                raise OntologyV2OperationsError(f"approved coverage state is unsafe for {label}")
            raw_contexts = contexts[label]
            if (
                not isinstance(raw_contexts, list)
                or not raw_contexts
                or len(raw_contexts) != len(set(raw_contexts))
                or not set(raw_contexts) <= set(OCCLUSION_CONTEXTS)
            ):
                raise OntologyV2OperationsError(
                    f"occlusion context evidence is invalid for {label}"
                )
            _validate_state_context(label, str(state), raw_contexts)
            counts[(label, "review_state", str(state))] += 1
            if label in new_class_positive_counts and state in {"visible", "partially_visible"}:
                new_class_positive_counts[label] += 1
            counts[(label, "view", str(view))] += 1
            for pose in poses:
                counts[(label, "pose", pose)] += 1
            for context in raw_contexts:
                counts[(label, "occlusion_context", context)] += 1
        package_count += 1
    cells = []
    for (label, dimension, value), count in sorted(counts.items()):
        target = int(dimensions[dimension][value])
        forbidden = dimension == "review_state" and value == "unreviewed_for_v2"
        cells.append(
            {
                "label": label,
                "dimension": dimension,
                "value": value,
                "approved_gold_count": count,
                "target": target,
                "deficit": count if forbidden else max(0, target - count),
                "target_kind": "maximum" if forbidden else "minimum",
            }
        )
    minimum_positive = policy["coverage"]["minimum_clear_positive_instances_per_new_class"]
    target_positive = policy["coverage"]["target_clear_positive_instances_per_new_class"]
    positive_targets = [
        {
            "label": label,
            "clear_positive_count": count,
            "minimum_required": minimum_positive,
            "target": target_positive,
            "minimum_deficit": max(0, minimum_positive - count),
            "target_deficit": max(0, target_positive - count),
        }
        for label, count in new_class_positive_counts.items()
    ]
    document = {
        "schema_version": "2.0.0",
        "ontology_version": V2_ONTOLOGY_VERSION,
        "activation_status": "approved_design_not_active",
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "approved_package_count": package_count,
        "foreground_class_count": len(foreground),
        "policy_sha256": _sha256(Path(policy_path)),
        "cells": cells,
        "new_class_positive_targets": positive_targets,
        "production_activation_granted": False,
    }
    issues = validate_document(document, "coverage_matrix_v2")
    if issues:
        raise OntologyV2OperationsError(
            "invalid v2 coverage matrix: " + "; ".join(str(issue) for issue in issues)
        )
    _validate_matrix_semantics(document, policy, policy_path=Path(policy_path))
    return document


def _package_status(package: Mapping[str, Any]) -> object:
    return package.get("workflow_status", package.get("status"))


def _person_value(package: Mapping[str, Any], key: str) -> object:
    person = package.get("person")
    if isinstance(person, Mapping) and key in person:
        return person[key]
    return package.get(key)


def _validate_state_context(label: str, state: str, contexts: list[str]) -> None:
    values = set(contexts)
    if state == "occluded_by_clothing" and values != {"clothing"}:
        raise OntologyV2OperationsError(
            f"occluded_by_clothing requires only clothing context for {label}"
        )
    if state == "cropped_out" and "frame_crop" not in values:
        raise OntologyV2OperationsError(f"cropped_out requires frame_crop context for {label}")
    if state == "visible" and values != {"none_visible"}:
        raise OntologyV2OperationsError(f"visible requires none_visible context for {label}")


def coverage_v2_deficit_report(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate then rank exact v2 class/dimension acquisition deficits."""
    issues = validate_document(document, "coverage_matrix_v2")
    if issues:
        raise OntologyV2OperationsError("invalid v2 coverage matrix")
    _validate_matrix_semantics(document, load_v2_operations_policy())
    rows = []
    for cell in document["cells"]:
        target = int(cell["target"])
        deficit = int(cell["deficit"])
        severity = deficit / max(1, target)
        rows.append({**cell, "normalized_deficit": severity})
    rows.sort(
        key=lambda row: (
            -row["normalized_deficit"],
            row["label"],
            row["dimension"],
            row["value"],
        )
    )
    return {
        "ontology_version": V2_ONTOLOGY_VERSION,
        "approved_package_count": document["approved_package_count"],
        "deficit_cell_count": sum(row["deficit"] > 0 for row in rows),
        "cells": rows,
        "new_class_positive_targets": list(document["new_class_positive_targets"]),
        "production_activation_granted": False,
    }


def acquisition_action_for_v2_failure(
    reason: str,
    *,
    label: str,
    policy_path: Path | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Return a governed hard-case acquisition action for one canonical v2 failure."""
    policy = load_v2_operations_policy(policy_path)
    if label not in V2_PART_CLASS_NAMES[1:]:
        raise OntologyV2OperationsError(f"failure label is not canonical foreground v2: {label}")
    mapping = policy["failure_acquisition"].get(reason)
    if mapping is None:
        raise OntologyV2OperationsError(f"unknown ontology-v2 failure reason: {reason}")
    return {
        "ontology_version": V2_ONTOLOGY_VERSION,
        "failed_body_part": label,
        "failure_reason": reason,
        **mapping,
        **policy["acquisition_invariants"],
        "production_activation_granted": False,
    }


def write_v2_coverage_matrix(path: Path, document: Mapping[str, Any]) -> Path:
    issues = validate_document(document, "coverage_matrix_v2")
    if issues:
        raise OntologyV2OperationsError("invalid v2 coverage matrix")
    _validate_matrix_semantics(document, load_v2_operations_policy())
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_matrix_semantics(
    document: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    policy_path: Path = DEFAULT_POLICY,
) -> None:
    if document.get("policy_sha256") != _sha256(policy_path):
        raise OntologyV2OperationsError("v2 coverage matrix policy hash is stale")
    targets = policy["coverage"]["dimensions"]
    expected = {
        (label, dimension, value): int(target)
        for label in V2_PART_CLASS_NAMES[1:]
        for dimension, values in targets.items()
        for value, target in values.items()
    }
    actual: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for cell in document["cells"]:
        key = (str(cell["label"]), str(cell["dimension"]), str(cell["value"]))
        if key in actual:
            raise OntologyV2OperationsError(f"duplicate v2 coverage cell: {key}")
        actual[key] = cell
    if set(actual) != set(expected):
        raise OntologyV2OperationsError(
            "v2 coverage matrix cells are not the exact class cross-product"
        )
    for key, target in expected.items():
        cell = actual[key]
        count = int(cell["approved_gold_count"])
        forbidden = key[1:] == ("review_state", "unreviewed_for_v2")
        expected_kind = "maximum" if forbidden else "minimum"
        expected_deficit = count if forbidden else max(0, target - count)
        if (
            cell["target"] != target
            or cell["target_kind"] != expected_kind
            or cell["deficit"] != expected_deficit
        ):
            raise OntologyV2OperationsError(f"v2 coverage target/deficit drift: {key}")
    positives = document["new_class_positive_targets"]
    if [row["label"] for row in positives] != list(V2_PART_CLASS_NAMES[56:]):
        raise OntologyV2OperationsError("v2 clear-positive rows are not exact IDs 56..65")
    minimum = policy["coverage"]["minimum_clear_positive_instances_per_new_class"]
    target = policy["coverage"]["target_clear_positive_instances_per_new_class"]
    for row in positives:
        count = int(row["clear_positive_count"])
        if row != {
            "label": row["label"],
            "clear_positive_count": count,
            "minimum_required": minimum,
            "target": target,
            "minimum_deficit": max(0, minimum - count),
            "target_deficit": max(0, target - count),
        }:
            raise OntologyV2OperationsError(
                f"v2 clear-positive target/deficit drift: {row['label']}"
            )
