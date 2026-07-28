"""D8 p-index-bound reciprocal contact and occlusion records."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..validation import require_valid_document
from .scenes import (
    DuoRecipeSelectionError,
    PIndexAssignmentError,
    validate_duo_recipe_selection,
    validate_p_index_assignment,
)


class MultiPersonRelationshipError(ValueError):
    """A D8 relationship policy, source artifact, or projected record is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_multi_person_relationship_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_multi_person_relationship_policy(document)
    return document


def validate_multi_person_relationship_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "scope",
        "maximum_people",
        "requirements",
        "authority",
        "publication",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise MultiPersonRelationshipError("multi_relationship_policy_fields_invalid", str(policy))
    if (
        policy["schema_version"] != "1.0.0"
        or policy["policy_version"] != "1.0.0"
        or policy["scope"] != "d8_reciprocal_contact_occlusion_records"
        or policy["maximum_people"] != 4
        or policy["requirements"]
        != {
            "passed_relationship_report": True,
            "accepted_p_index_assignment": True,
            "replayed_duo_selection": True,
            "exact_unordered_pair_set": True,
            "exact_reciprocal_directed_records": True,
            "relationship_family_consistency": True,
            "geometry_only_contact": True,
            "instance_and_linear_depth_occlusion": True,
            "p_index_projection_only_after_final_camera": True,
            "source_records_read_only": True,
        }
        or policy["authority"]
        != {
            "owner": "maskfactory",
            "stage": "technical_d8_relationship_record",
            "can_raise_truth_tier": False,
            "can_mutate_gold": False,
        }
        or policy["publication"]
        != {"immutable": True, "atomic": True, "failure_blocks_acceptance": True}
    ):
        raise MultiPersonRelationshipError(
            "multi_relationship_policy_identity_invalid", str(policy)
        )


def build_multi_person_relationship_record(
    relationship_report: Mapping[str, Any],
    assignment: Mapping[str, Any],
    duo_selection: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    duo_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Replay D6 relationship truth and project it into accepted final p-indices."""

    validate_multi_person_relationship_policy(policy)
    require_valid_document(relationship_report, "daz_relationship_pass_report")
    _verify_hashed_document(relationship_report, "report_id", "report_sha256", "drpr")
    try:
        validate_p_index_assignment(assignment)
    except PIndexAssignmentError as exc:
        raise MultiPersonRelationshipError(
            "multi_relationship_assignment_invalid", exc.reason
        ) from exc
    try:
        validate_duo_recipe_selection(duo_selection, duo_policy)
    except DuoRecipeSelectionError as exc:
        raise MultiPersonRelationshipError(
            "multi_relationship_duo_selection_invalid", exc.reason
        ) from exc
    if (
        assignment["summary"]["accepted"] is not True
        or assignment["summary"]["all_declared_people_retained"] is not True
        or len(assignment["mapping"]) != 2
    ):
        raise MultiPersonRelationshipError(
            "multi_relationship_assignment_not_accepted", assignment["assignment_id"]
        )
    if (
        relationship_report["scene_id"] != assignment["scene_id"]
        or relationship_report["scene_state_sha256"] != assignment["lineage"]["scene_state_sha256"]
        or relationship_report["instance_codec"]["resolution"]
        != assignment["final_frame"]["resolution"]
        or assignment["lineage"]["duo_selection_id"] != duo_selection["selection_id"]
        or assignment["lineage"]["duo_selection_sha256"] != duo_selection["selection_sha256"]
    ):
        raise MultiPersonRelationshipError(
            "multi_relationship_lineage_mismatch", assignment["assignment_id"]
        )

    mapping = sorted(
        (
            {
                "slot_id": row["slot_id"],
                "construction_id": row["construction_id"],
                "instance_id": row["instance_id"],
                "p_index": row["p_index"],
            }
            for row in assignment["mapping"]
        ),
        key=lambda row: row["instance_id"],
    )
    if [row["instance_id"] for row in mapping] != [1, 2] or [row["p_index"] for row in mapping] != [
        "p0",
        "p1",
    ]:
        raise MultiPersonRelationshipError("multi_relationship_mapping_invalid", str(mapping))
    by_instance = {row["instance_id"]: row for row in mapping}
    expected_pairs = [list(pair) for pair in itertools.combinations(by_instance, 2)]
    pair_records_by_pair = _validate_source_report(relationship_report, expected_pairs)
    relationship_family = duo_selection["request"]["relationship_family"]
    projected_pairs = []
    for pair in expected_pairs:
        source = pair_records_by_pair[tuple(pair)]
        _validate_family_consistency(source, relationship_family)
        first, second = (by_instance[value] for value in pair)
        projected_pairs.append(
            {
                "pair": [first["p_index"], second["p_index"]],
                "instance_pair": pair,
                "construction_pair": [first["construction_id"], second["construction_id"]],
                "minimum_surface_distance_mm": source["minimum_surface_distance_mm"],
                "maximum_penetration_mm": source["maximum_penetration_mm"],
                "minimum_normal_dot": source["minimum_normal_dot"],
                "contact": source["contact"],
                "contact_regions": [
                    {
                        "first_part_id": region["a_part_id"],
                        "second_part_id": region["b_part_id"],
                        "area_mm2": region["area_mm2"],
                    }
                    for region in source["contact_regions"]
                ],
                "visible_boundary_pixels": source["visible_boundary_pixels"],
                "front_owner_counts": {
                    first["p_index"]: source["front_owner_counts"][str(pair[0])],
                    second["p_index"]: source["front_owner_counts"][str(pair[1])],
                },
                "depth_sample_count": source["depth_sample_count"],
                "depth_tie_count": source["depth_tie_count"],
                "occlusion_direction": {
                    "none": "none",
                    "a_front": "first_front",
                    "b_front": "second_front",
                    "mixed": "mixed",
                }[source["occlusion_direction"]],
                "depth_order_confidence": source["depth_order_confidence"],
            }
        )
    projected_directed = [
        {
            "source_p_index": by_instance[row["source_instance_id"]]["p_index"],
            "target_p_index": by_instance[row["target_instance_id"]]["p_index"],
            "source_instance_id": row["source_instance_id"],
            "target_instance_id": row["target_instance_id"],
            "type": row["type"],
        }
        for row in relationship_report["directed_relationships"]
    ]
    projected_directed.sort(key=_directed_sort_key)
    content = {
        "policy_version": policy["policy_version"],
        "policy_sha256": _canonical_sha(policy),
        "scene_id": assignment["scene_id"],
        "relationship_report_id": relationship_report["report_id"],
        "relationship_report_sha256": relationship_report["report_sha256"],
        "assignment_id": assignment["assignment_id"],
        "assignment_sha256": assignment["assignment_sha256"],
        "duo_selection_id": duo_selection["selection_id"],
        "duo_selection_sha256": duo_selection["selection_sha256"],
        "duo_policy_sha256": _canonical_sha(duo_policy),
        "relationship_family": relationship_family,
        "mapping": mapping,
        "pair_records": projected_pairs,
        "directed_relationships": projected_directed,
        "summary": _summary(mapping, projected_pairs, projected_directed),
        "authority": dict(policy["authority"]),
    }
    digest = _canonical_sha(content)
    record = {
        "schema_version": "1.0.0",
        "record_id": f"dmrr_{digest[:24]}",
        "record_sha256": digest,
        **content,
    }
    validate_multi_person_relationship_record(record)
    return record


def validate_multi_person_relationship_record(record: Mapping[str, Any]) -> None:
    require_valid_document(record, "daz_multi_person_relationship_record")
    _verify_hashed_document(record, "record_id", "record_sha256", "dmrr")
    mapping = record["mapping"]
    by_instance = {row["instance_id"]: row for row in mapping}
    expected_pairs = [list(pair) for pair in itertools.combinations(sorted(by_instance), 2)]
    pair_records = record["pair_records"]
    if (
        len(by_instance) != len(mapping)
        or [row["instance_id"] for row in mapping] != list(range(1, len(mapping) + 1))
        or [row["p_index"] for row in mapping] != [f"p{i}" for i in range(len(mapping))]
        or [row["instance_pair"] for row in pair_records] != expected_pairs
    ):
        raise MultiPersonRelationshipError(
            "multi_relationship_record_mapping_invalid", record["record_id"]
        )
    for pair_record in pair_records:
        first, second = (by_instance[value] for value in pair_record["instance_pair"])
        if (
            pair_record["pair"] != [first["p_index"], second["p_index"]]
            or pair_record["construction_pair"]
            != [first["construction_id"], second["construction_id"]]
            or set(pair_record["front_owner_counts"]) != set(pair_record["pair"])
        ):
            raise MultiPersonRelationshipError(
                "multi_relationship_record_pair_invalid", str(pair_record["pair"])
            )
    expected_directed = _projected_directed_from_pairs(pair_records)
    if record["directed_relationships"] != expected_directed or record["summary"] != _summary(
        mapping, pair_records, expected_directed
    ):
        raise MultiPersonRelationshipError(
            "multi_relationship_record_reciprocity_invalid", record["record_id"]
        )


def publish_multi_person_relationship_record(
    record: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    validate_multi_person_relationship_record(record)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{record['record_id']}.json"
    payload = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise MultiPersonRelationshipError(
                "multi_relationship_publication_conflict", str(target)
            )
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


def _validate_source_report(
    report: Mapping[str, Any], expected_pairs: list[list[int]]
) -> dict[tuple[int, int], Mapping[str, Any]]:
    summary = report["summary"]
    records = report["pair_records"]
    by_pair = {tuple(row["pair"]): row for row in records}
    if (
        summary["passed"] is not True
        or summary["finding_count"] != 0
        or summary["failure_codes"] != []
        or summary["scene_state_unchanged"] is not True
        or summary["reciprocal_relationships_exact"] is not True
        or report["findings"] != []
        or len(by_pair) != len(records)
        or list(by_pair) != [tuple(pair) for pair in expected_pairs]
        or summary["pair_count"] != len(expected_pairs)
        or summary["contact_pair_count"] != sum(row["contact"] for row in records)
    ):
        raise MultiPersonRelationshipError(
            "multi_relationship_source_report_invalid", report["report_id"]
        )
    for pair, row in by_pair.items():
        if set(row["front_owner_counts"]) != {str(pair[0]), str(pair[1])} or row["contact"] != (
            0.0 <= row["minimum_surface_distance_mm"] <= 4.0
            and row["maximum_penetration_mm"] <= 2.0
            and row["minimum_normal_dot"] >= 0.0
            and bool(row["contact_regions"])
        ):
            raise MultiPersonRelationshipError("multi_relationship_source_pair_invalid", str(pair))
    if report["directed_relationships"] != _source_directed_from_pairs(records):
        raise MultiPersonRelationshipError(
            "multi_relationship_source_reciprocity_invalid", report["report_id"]
        )
    return by_pair


def _validate_family_consistency(record: Mapping[str, Any], family: str) -> None:
    contact = record["contact"]
    boundary = record["visible_boundary_pixels"]
    direction = record["occlusion_direction"]
    valid = {
        "no_contact": not contact and boundary == 0 and direction == "none",
        "overlap_no_contact": not contact and boundary > 0 and direction != "none",
        "contact_support": contact and boundary > 0 and bool(record["contact_regions"]),
    }[family]
    if not valid:
        raise MultiPersonRelationshipError(
            "multi_relationship_family_mismatch", f"{family}:{record['pair']}"
        )


def _source_directed_from_pairs(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in records:
        first, second = record["pair"]
        if record["contact"]:
            result.extend(
                [
                    {"source_instance_id": first, "target_instance_id": second, "type": "contact"},
                    {"source_instance_id": second, "target_instance_id": first, "type": "contact"},
                ]
            )
        if record["occlusion_direction"] in {"a_front", "mixed"}:
            result.extend(
                [
                    {"source_instance_id": first, "target_instance_id": second, "type": "occludes"},
                    {
                        "source_instance_id": second,
                        "target_instance_id": first,
                        "type": "occluded_by",
                    },
                ]
            )
        if record["occlusion_direction"] in {"b_front", "mixed"}:
            result.extend(
                [
                    {"source_instance_id": second, "target_instance_id": first, "type": "occludes"},
                    {
                        "source_instance_id": first,
                        "target_instance_id": second,
                        "type": "occluded_by",
                    },
                ]
            )
    result.sort(key=lambda row: (row["source_instance_id"], row["target_instance_id"], row["type"]))
    return result


def _projected_directed_from_pairs(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in records:
        first_p, second_p = record["pair"]
        first_i, second_i = record["instance_pair"]
        if record["contact"]:
            result.extend(
                [
                    _directed(first_p, second_p, first_i, second_i, "contact"),
                    _directed(second_p, first_p, second_i, first_i, "contact"),
                ]
            )
        if record["occlusion_direction"] in {"first_front", "mixed"}:
            result.extend(
                [
                    _directed(first_p, second_p, first_i, second_i, "occludes"),
                    _directed(second_p, first_p, second_i, first_i, "occluded_by"),
                ]
            )
        if record["occlusion_direction"] in {"second_front", "mixed"}:
            result.extend(
                [
                    _directed(second_p, first_p, second_i, first_i, "occludes"),
                    _directed(first_p, second_p, first_i, second_i, "occluded_by"),
                ]
            )
    result.sort(key=_directed_sort_key)
    return result


def _directed(
    source_p: str, target_p: str, source_i: int, target_i: int, relation: str
) -> dict[str, Any]:
    return {
        "source_p_index": source_p,
        "target_p_index": target_p,
        "source_instance_id": source_i,
        "target_instance_id": target_i,
        "type": relation,
    }


def _directed_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (row["source_instance_id"], row["target_instance_id"], row["type"])


def _summary(
    mapping: list[Mapping[str, Any]],
    pairs: list[Mapping[str, Any]],
    directed: list[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "passed": True,
        "acceptance_eligible": True,
        "person_count": len(mapping),
        "pair_count": len(pairs),
        "contact_pair_count": sum(row["contact"] for row in pairs),
        "occlusion_pair_count": sum(row["occlusion_direction"] != "none" for row in pairs),
        "directed_relationship_count": len(directed),
        "reciprocal_relationships_exact": True,
    }


def _verify_hashed_document(
    document: Mapping[str, Any], id_field: str, hash_field: str, prefix: str
) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, hash_field}
    }
    digest = _canonical_sha(content)
    if document[hash_field] != digest or document[id_field] != f"{prefix}_{digest[:24]}":
        raise MultiPersonRelationshipError(
            "multi_relationship_document_hash_invalid", str(document.get(id_field))
        )


def _canonical_sha(value: Any) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiPersonRelationshipError(
            "multi_relationship_noncanonical_value", str(exc)
        ) from exc
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "MultiPersonRelationshipError",
    "build_multi_person_relationship_record",
    "load_multi_person_relationship_policy",
    "publish_multi_person_relationship_record",
    "validate_multi_person_relationship_policy",
    "validate_multi_person_relationship_record",
]
