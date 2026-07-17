"""Read-only adapter from real MaskFactory coverage deficits to DAZ demands."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...datasets.coverage import ATTRIBUTES, CONTEXTS, POSES, VIEWS
from ...datasets.coverage_v2 import (
    OntologyV2OperationsError,
    coverage_v2_deficit_report,
)
from ...models.ontology_contract import V2_PART_CLASS_NAMES
from ...validation import require_valid_document
from .vocabulary import validate_coverage_vocabulary_report

TOKEN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_POLICY_SHA256 = "c6e03cca2f5427f5d5e8b79d61c7233b9667e909d27775188a3380cb01fac93c"
VISIBILITY_PROJECTION = {
    "visible": "visible",
    "partially_visible": "partially_visible",
    "occluded": "occluded",
    "cropped_out": "cropped_out",
    "not_applicable": "not_applicable",
}


class RealDeficitSignalError(ValueError):
    """A source matrix, adapter policy, report, or publication is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_deficit_adapter_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_deficit_adapter_policy(document)
    return document


def validate_deficit_adapter_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "adapter_version",
        "vocabulary_version",
        "supported_sources",
        "actionability",
        "authority",
        "publication",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise RealDeficitSignalError("deficit_adapter_policy_fields_invalid", str(policy))
    if (
        policy["schema_version"] != "1.0.0"
        or policy["adapter_version"] != "1.0.0"
        or policy["vocabulary_version"] != "1.0.0"
    ):
        raise RealDeficitSignalError("deficit_adapter_policy_identity_invalid", str(policy))
    if policy["supported_sources"] != {
        "coverage_matrix_v1": {
            "schema_version": "1.0.0",
            "ontology_version": "body_parts_v1",
            "authority_namespace": "real_certified_coverage",
            "target_per_cell": 8,
            "target_per_attribute": 40,
            "production_activation_granted": True,
        },
        "coverage_matrix_v2": {
            "schema_version": "2.0.0",
            "ontology_version": "body_parts_v2",
            "authority_namespace": "real_certified_coverage",
            "production_activation_granted": False,
        },
    }:
        raise RealDeficitSignalError("deficit_adapter_sources_invalid", str(policy))
    if policy["actionability"] != {
        "canonical_minimum_deficit": "eligible",
        "inactive_ontology_minimum_deficit": "inactive_ontology_observation",
        "maximum_constraint_violation": "source_gate_only",
    }:
        raise RealDeficitSignalError("deficit_adapter_actionability_invalid", str(policy))
    if policy["authority"] != {
        "source_counts_are_read_only": True,
        "source_authority_is_preserved": True,
        "synthetic_counts_close_real_deficits": False,
        "imported_signals_create_gold": False,
        "imported_signals_create_recipes": False,
        "inactive_ontology_grants_production_activation": False,
    }:
        raise RealDeficitSignalError("deficit_adapter_authority_invalid", str(policy))
    if policy["publication"] != {"immutable": True, "atomic": True}:
        raise RealDeficitSignalError("deficit_adapter_publication_invalid", str(policy))


def build_real_deficit_signal_report(
    source: Mapping[str, Any],
    *,
    source_id: str,
    source_sha256: str,
    policy: Mapping[str, Any],
    vocabulary_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one real coverage matrix and emit normalized, authority-safe demands."""

    validate_deficit_adapter_policy(policy)
    validate_coverage_vocabulary_report(vocabulary_report)
    if not TOKEN.fullmatch(source_id):
        raise RealDeficitSignalError("deficit_source_id_invalid", source_id)
    if not SHA256.fullmatch(source_sha256):
        raise RealDeficitSignalError("deficit_source_hash_invalid", source_sha256)
    if source_sha256 != _canonical_sha(source):
        raise RealDeficitSignalError("deficit_source_hash_mismatch", source_id)
    schema_version = source.get("schema_version")
    if schema_version == "1.0.0":
        source_kind = "coverage_matrix_v1"
        demands = _v1_demands(source, source_id=source_id, policy=policy)
    elif schema_version == "2.0.0":
        source_kind = "coverage_matrix_v2"
        demands = _v2_demands(source, source_id=source_id, policy=policy)
    else:
        raise RealDeficitSignalError("deficit_source_schema_unsupported", str(schema_version))
    source_policy = policy["supported_sources"][source_kind]
    source_record = {
        "source_id": source_id,
        "source_kind": source_kind,
        "source_schema_version": schema_version,
        "source_sha256": source_sha256,
        "generated_at": source["generated_at"],
        "ontology_version": source_policy["ontology_version"],
        "authority_namespace": source_policy["authority_namespace"],
        "production_activation_granted": source_policy["production_activation_granted"],
    }
    demands.sort(
        key=lambda row: (
            -row["normalized_deficit"],
            row["actionability"],
            row["demand_id"],
        )
    )
    summary = _summary(demands)
    content = {
        "adapter_version": policy["adapter_version"],
        "policy_sha256": _canonical_sha(policy),
        "vocabulary": {
            "report_id": vocabulary_report["report_id"],
            "report_sha256": vocabulary_report["report_sha256"],
            "vocabulary_version": vocabulary_report["vocabulary_version"],
        },
        "source": source_record,
        "demands": demands,
        "summary": summary,
        "authority": dict(policy["authority"]),
        "publication": dict(policy["publication"]),
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"drds_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    validate_real_deficit_signal_report(report)
    return report


def validate_real_deficit_signal_report(report: Mapping[str, Any]) -> None:
    require_valid_document(report, "daz_real_deficit_signal_report")
    _verify_hashed_document(report, "report_id", "report_sha256", "drds")
    if report["policy_sha256"] != EXPECTED_POLICY_SHA256:
        raise RealDeficitSignalError("deficit_report_policy_hash_invalid", report["policy_sha256"])
    _validate_source_record(report["source"])
    demands = report["demands"]
    if len({row["demand_id"] for row in demands}) != len(demands):
        raise RealDeficitSignalError("deficit_report_duplicate_demand", report["report_id"])
    for demand in demands:
        expected_id = f"drd_{_canonical_sha(_without(demand, 'demand_id'))[:24]}"
        if demand["demand_id"] != expected_id:
            raise RealDeficitSignalError("deficit_demand_hash_invalid", demand["demand_id"])
        expected_normalized = demand["deficit"] / max(1, demand["target"])
        if demand["normalized_deficit"] != expected_normalized:
            raise RealDeficitSignalError(
                "deficit_demand_normalization_invalid", demand["demand_id"]
            )
        _validate_demand_semantics(demand, report["source"])
    expected_order = sorted(
        demands,
        key=lambda row: (
            -row["normalized_deficit"],
            row["actionability"],
            row["demand_id"],
        ),
    )
    if list(demands) != expected_order or report["summary"] != _summary(demands):
        raise RealDeficitSignalError("deficit_report_semantics_invalid", report["report_id"])


def publish_real_deficit_signal_report(
    report: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    validate_real_deficit_signal_report(report)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{report['report_id']}.json"
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise RealDeficitSignalError("deficit_report_publication_conflict", str(target))
        return target, False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=root
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, True


def _v1_demands(
    source: Mapping[str, Any], *, source_id: str, policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    require_valid_document(source, "coverage_matrix")
    expected_cells = {
        (view, pose, context) for view in VIEWS for pose in POSES for context in CONTEXTS
    }
    actual: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for cell in source["cells"]:
        key = (cell["view"], cell["pose"], cell["instance_context"])
        if key in actual:
            raise RealDeficitSignalError("deficit_source_duplicate_cell", str(key))
        actual[key] = cell
    if set(actual) != expected_cells:
        raise RealDeficitSignalError("deficit_source_cells_incomplete", str(len(actual)))
    settings = policy["supported_sources"]["coverage_matrix_v1"]
    demands = []
    target = settings["target_per_cell"]
    for key, cell in sorted(actual.items()):
        current = int(cell["approved_gold_count"])
        deficit = max(0, target - current)
        if deficit:
            coordinates = [
                {"axis_id": "canonical_view", "value": key[0]},
                {"axis_id": "canonical_pose", "value": key[1]},
                {"axis_id": "instance_context", "value": key[2]},
            ]
            demands.append(
                _demand(
                    source_id=source_id,
                    signal_kind="canonical_cell",
                    ontology_version="body_parts_v1",
                    source_coordinates=coordinates,
                    closed_axis_projection=coordinates,
                    target=target,
                    current=current,
                    deficit=deficit,
                    target_kind="minimum",
                    actionability="eligible",
                    mapping_required=False,
                )
            )
    attribute_target = settings["target_per_attribute"]
    if set(source["attribute_totals"]) != set(ATTRIBUTES):
        raise RealDeficitSignalError("deficit_source_attributes_incomplete", source_id)
    for attribute in ATTRIBUTES:
        current = int(source["attribute_totals"][attribute])
        deficit = max(0, attribute_target - current)
        if deficit:
            coordinates = [{"axis_id": "canonical_attribute", "value": attribute}]
            demands.append(
                _demand(
                    source_id=source_id,
                    signal_kind="canonical_attribute",
                    ontology_version="body_parts_v1",
                    source_coordinates=coordinates,
                    closed_axis_projection=coordinates,
                    target=attribute_target,
                    current=current,
                    deficit=deficit,
                    target_kind="minimum",
                    actionability="eligible",
                    mapping_required=False,
                )
            )
    return demands


def _v2_demands(
    source: Mapping[str, Any], *, source_id: str, policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    try:
        deficit_report = coverage_v2_deficit_report(source)
    except OntologyV2OperationsError as exc:
        raise RealDeficitSignalError("deficit_source_v2_invalid", str(exc)) from exc
    if deficit_report["production_activation_granted"] is not False:
        raise RealDeficitSignalError("deficit_source_v2_activation_invalid", source_id)
    allowed_labels = set(V2_PART_CLASS_NAMES[1:])
    demands = []
    for cell in deficit_report["cells"]:
        deficit = int(cell["deficit"])
        if not deficit:
            continue
        if cell["label"] not in allowed_labels:
            raise RealDeficitSignalError("deficit_source_v2_label_invalid", cell["label"])
        coordinates = [
            {"axis_id": "ontology_label", "value": cell["label"]},
            {"axis_id": cell["dimension"], "value": cell["value"]},
        ]
        projection = [
            {"axis_id": "ontology_version", "value": "body_parts_v2"},
            {"axis_id": "ontology_label", "value": cell["label"]},
        ]
        if cell["dimension"] == "view":
            projection.append({"axis_id": "canonical_view", "value": cell["value"]})
        elif cell["dimension"] == "pose":
            projection.append({"axis_id": "canonical_pose", "value": cell["value"]})
        elif cell["dimension"] == "review_state" and cell["value"] in VISIBILITY_PROJECTION:
            projection.append(
                {
                    "axis_id": "label_visibility_state",
                    "value": VISIBILITY_PROJECTION[cell["value"]],
                }
            )
        actionability = (
            "source_gate_only"
            if cell["target_kind"] == "maximum"
            else "inactive_ontology_observation"
        )
        demands.append(
            _demand(
                source_id=source_id,
                signal_kind="ontology_cell",
                ontology_version="body_parts_v2",
                source_coordinates=coordinates,
                closed_axis_projection=projection,
                target=int(cell["target"]),
                current=int(cell["approved_gold_count"]),
                deficit=deficit,
                target_kind=cell["target_kind"],
                actionability=actionability,
                mapping_required=True,
            )
        )
    for row in deficit_report["new_class_positive_targets"]:
        deficit = int(row["target_deficit"])
        if not deficit:
            continue
        coordinates = [
            {"axis_id": "ontology_label", "value": row["label"]},
            {"axis_id": "clear_positive_target", "value": "target"},
        ]
        projection = [
            {"axis_id": "ontology_version", "value": "body_parts_v2"},
            {"axis_id": "ontology_label", "value": row["label"]},
        ]
        demands.append(
            _demand(
                source_id=source_id,
                signal_kind="ontology_positive_target",
                ontology_version="body_parts_v2",
                source_coordinates=coordinates,
                closed_axis_projection=projection,
                target=int(row["target"]),
                current=int(row["clear_positive_count"]),
                deficit=deficit,
                target_kind="minimum",
                actionability="inactive_ontology_observation",
                mapping_required=True,
            )
        )
    return demands


def _demand(
    *,
    source_id: str,
    signal_kind: str,
    ontology_version: str,
    source_coordinates: list[dict[str, Any]],
    closed_axis_projection: list[dict[str, Any]],
    target: int,
    current: int,
    deficit: int,
    target_kind: str,
    actionability: str,
    mapping_required: bool,
) -> dict[str, Any]:
    content = {
        "source_id": source_id,
        "signal_kind": signal_kind,
        "ontology_version": ontology_version,
        "source_coordinates": source_coordinates,
        "closed_axis_projection": closed_axis_projection,
        "target": target,
        "current": current,
        "deficit": deficit,
        "normalized_deficit": deficit / max(1, target),
        "target_kind": target_kind,
        "actionability": actionability,
        "synthetic_recipe_mapping_required": mapping_required,
    }
    return {"demand_id": f"drd_{_canonical_sha(content)[:24]}", **content}


def _validate_demand_semantics(demand: Mapping[str, Any], source: Mapping[str, Any]) -> None:
    if demand["source_id"] != source["source_id"]:
        raise RealDeficitSignalError("deficit_demand_source_invalid", demand["demand_id"])
    coordinates = {row["axis_id"]: row["value"] for row in demand["source_coordinates"]}
    projections = {row["axis_id"]: row["value"] for row in demand["closed_axis_projection"]}
    if len(coordinates) != len(demand["source_coordinates"]) or len(projections) != len(
        demand["closed_axis_projection"]
    ):
        raise RealDeficitSignalError("deficit_demand_coordinates_invalid", demand["demand_id"])
    if demand["ontology_version"] == "body_parts_v1":
        _validate_v1_demand_coordinates(demand, coordinates, projections)
        if (
            source["source_kind"] != "coverage_matrix_v1"
            or demand["actionability"] != "eligible"
            or demand["target_kind"] != "minimum"
            or demand["synthetic_recipe_mapping_required"]
            or demand["signal_kind"] not in {"canonical_cell", "canonical_attribute"}
            or coordinates != projections
        ):
            raise RealDeficitSignalError("deficit_demand_v1_semantics_invalid", demand["demand_id"])
    else:
        _validate_v2_demand_coordinates(demand, coordinates, projections)
        expected_actionability = (
            "source_gate_only"
            if demand["target_kind"] == "maximum"
            else "inactive_ontology_observation"
        )
        if (
            source["source_kind"] != "coverage_matrix_v2"
            or source["production_activation_granted"]
            or demand["actionability"] != expected_actionability
            or not demand["synthetic_recipe_mapping_required"]
            or projections.get("ontology_version") != "body_parts_v2"
            or projections.get("ontology_label") != coordinates.get("ontology_label")
        ):
            raise RealDeficitSignalError("deficit_demand_v2_semantics_invalid", demand["demand_id"])


def _validate_source_record(source: Mapping[str, Any]) -> None:
    expected = {
        "coverage_matrix_v1": {
            "source_schema_version": "1.0.0",
            "ontology_version": "body_parts_v1",
            "production_activation_granted": True,
        },
        "coverage_matrix_v2": {
            "source_schema_version": "2.0.0",
            "ontology_version": "body_parts_v2",
            "production_activation_granted": False,
        },
    }
    actual = {
        key: source[key]
        for key in (
            "source_schema_version",
            "ontology_version",
            "production_activation_granted",
        )
    }
    if actual != expected[source["source_kind"]]:
        raise RealDeficitSignalError("deficit_report_source_semantics_invalid", str(source))


def _validate_v1_demand_coordinates(
    demand: Mapping[str, Any],
    coordinates: Mapping[str, Any],
    projections: Mapping[str, Any],
) -> None:
    if demand["signal_kind"] == "canonical_cell":
        valid = (
            list(coordinates) == ["canonical_view", "canonical_pose", "instance_context"]
            and coordinates["canonical_view"] in VIEWS
            and coordinates["canonical_pose"] in POSES
            and coordinates["instance_context"] in CONTEXTS
            and demand["target"] == 8
        )
    elif demand["signal_kind"] == "canonical_attribute":
        valid = (
            list(coordinates) == ["canonical_attribute"]
            and coordinates["canonical_attribute"] in ATTRIBUTES
            and demand["target"] == 40
        )
    else:
        valid = False
    if (
        not valid
        or coordinates != projections
        or demand["deficit"] != max(0, demand["target"] - demand["current"])
    ):
        raise RealDeficitSignalError("deficit_demand_v1_coordinates_invalid", demand["demand_id"])


def _validate_v2_demand_coordinates(
    demand: Mapping[str, Any],
    coordinates: Mapping[str, Any],
    projections: Mapping[str, Any],
) -> None:
    label = coordinates.get("ontology_label")
    if label not in V2_PART_CLASS_NAMES[1:]:
        raise RealDeficitSignalError("deficit_demand_v2_label_invalid", demand["demand_id"])
    if demand["signal_kind"] == "ontology_positive_target":
        valid = (
            list(coordinates) == ["ontology_label", "clear_positive_target"]
            and coordinates["clear_positive_target"] == "target"
            and demand["target"] == 100
            and list(projections) == ["ontology_version", "ontology_label"]
        )
    elif demand["signal_kind"] == "ontology_cell":
        dimensions = [key for key in coordinates if key != "ontology_label"]
        valid = len(dimensions) == 1 and dimensions[0] in {
            "view",
            "pose",
            "review_state",
            "occlusion_context",
        }
        if valid:
            dimension = dimensions[0]
            value = coordinates[dimension]
            expected_projection = {
                "ontology_version": "body_parts_v2",
                "ontology_label": label,
            }
            if dimension == "view":
                valid = value in VIEWS
                expected_projection["canonical_view"] = value
            elif dimension == "pose":
                valid = value in POSES
                expected_projection["canonical_pose"] = value
            elif dimension == "review_state":
                valid = value in {
                    "visible",
                    "partially_visible",
                    "occluded",
                    "occluded_by_clothing",
                    "cropped_out",
                    "not_visible",
                    "not_applicable",
                    "unreviewed_for_v2",
                    "ambiguous_do_not_use",
                }
                if value in VISIBILITY_PROJECTION:
                    expected_projection["label_visibility_state"] = VISIBILITY_PROJECTION[value]
            else:
                valid = value in {
                    "none_visible",
                    "self_occlusion",
                    "other_body_part",
                    "hair",
                    "prop",
                    "clothing",
                    "frame_crop",
                    "interperson_contact",
                }
            valid = valid and projections == expected_projection
    else:
        valid = False
    expected_deficit = (
        demand["current"]
        if demand["target_kind"] == "maximum"
        else max(0, demand["target"] - demand["current"])
    )
    if (
        not valid
        or projections.get("ontology_version") != "body_parts_v2"
        or projections.get("ontology_label") != label
        or demand["deficit"] != expected_deficit
    ):
        raise RealDeficitSignalError("deficit_demand_v2_coordinates_invalid", demand["demand_id"])


def _summary(demands: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "positive_deficit_count": len(demands),
        "eligible_count": sum(row["actionability"] == "eligible" for row in demands),
        "inactive_ontology_observation_count": sum(
            row["actionability"] == "inactive_ontology_observation" for row in demands
        ),
        "source_gate_only_count": sum(
            row["actionability"] == "source_gate_only" for row in demands
        ),
        "total_deficit_units": sum(int(row["deficit"]) for row in demands),
        "maximum_normalized_deficit": max(
            (float(row["normalized_deficit"]) for row in demands), default=0.0
        ),
    }


def _without(document: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in document.items() if name != key}


def _canonical_sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _verify_hashed_document(
    document: Mapping[str, Any], id_field: str, sha_field: str, prefix: str
) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, sha_field}
    }
    digest = _canonical_sha(content)
    if document[sha_field] != digest or document[id_field] != f"{prefix}_{digest[:24]}":
        raise RealDeficitSignalError("deficit_report_hash_invalid", str(document[id_field]))
