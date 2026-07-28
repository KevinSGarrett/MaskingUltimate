"""Final-camera, raster-derived prominence ranking and p-index assignment."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from ...validation import require_valid_document
from ..render.instance import InstancePassContractError, decode_u16_png_exact


class PIndexAssignmentError(ValueError):
    """A p-index policy, observation, raster, or assignment is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_p_index_assignment_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_p_index_assignment_policy(document)
    return document


def validate_p_index_assignment_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "scope",
        "maximum_people",
        "minimum_visible_area_fraction",
        "prominence_formula",
        "deterministic_tie_break",
        "construction_map",
        "camera",
        "retry",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise PIndexAssignmentError("p_index_policy_fields_invalid", str(policy))
    if (
        policy["schema_version"] != "1.0.0"
        or policy["policy_version"] != "1.0.0"
        or policy["scope"] != "final_camera_prominence_p_index"
        or policy["maximum_people"] != 4
        or not _finite(policy["minimum_visible_area_fraction"])
        or policy["minimum_visible_area_fraction"] != 0.04
        or policy["prominence_formula"] != "visible_pixels_divided_by_final_output_pixels"
        or policy["deterministic_tie_break"]
        != ["prominence_desc", "visible_area_desc", "construction_id_asc"]
    ):
        raise PIndexAssignmentError("p_index_policy_identity_invalid", str(policy))
    if policy["construction_map"] != {
        "encoding": "uint16_png",
        "background_value": 0,
        "decode_filter": "nearest_neighbor_exact",
        "unknown_ids_rejected": True,
    }:
        raise PIndexAssignmentError(
            "p_index_policy_construction_map_invalid", str(policy["construction_map"])
        )
    if policy["camera"] != {"normalized_readback_must_equal_final_camera": True}:
        raise PIndexAssignmentError("p_index_policy_camera_invalid", str(policy["camera"]))
    if policy["retry"] != {
        "maximum_framing_retries": 2,
        "below_minimum_when_promotion_required": "retry_framing",
        "below_minimum_otherwise": "reject_resample",
        "partial_mapping_forbidden": True,
    }:
        raise PIndexAssignmentError("p_index_policy_retry_invalid", str(policy["retry"]))


def build_p_index_assignment(
    duo_selection: Mapping[str, Any],
    observation: Mapping[str, Any],
    construction_map_path: Path,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Assign p0..pN from an exact construction-owner raster at the final camera."""

    validate_p_index_assignment_policy(policy)
    require_valid_document(duo_selection, "daz_duo_recipe_selection")
    _verify_hashed_document(
        duo_selection,
        id_field="selection_id",
        hash_field="selection_sha256",
        prefix="dcds",
    )
    _validate_observation(observation, duo_selection, policy)
    try:
        pixels, codec = decode_u16_png_exact(Path(construction_map_path))
    except InstancePassContractError as exc:
        raise PIndexAssignmentError("p_index_construction_map_invalid", exc.reason) from exc
    if codec["resolution"] != observation["resolution"]:
        raise PIndexAssignmentError(
            "p_index_resolution_mismatch",
            f"{codec['resolution']} != {observation['resolution']}",
        )
    owners = observation["construction_owners"]
    declared_ids = {row["source_instance_id"] for row in owners}
    observed_ids = {int(value) for value in np.unique(pixels)}
    unknown_ids = sorted(observed_ids - {0, *declared_ids})
    if unknown_ids:
        raise PIndexAssignmentError("p_index_unknown_construction_ids", str(unknown_ids))

    width, height = observation["resolution"]
    frame_pixels = width * height
    measured = []
    for owner in owners:
        ys, xs = np.nonzero(pixels == owner["source_instance_id"])
        visible_pixels = int(xs.size)
        bbox = (
            None
            if not visible_pixels
            else [
                int(xs.min()),
                int(ys.min()),
                int(xs.max() - xs.min() + 1),
                int(ys.max() - ys.min() + 1),
            ]
        )
        bbox_pixels = 0 if bbox is None else bbox[2] * bbox[3]
        fraction = visible_pixels / frame_pixels
        measured.append(
            {
                "slot_id": owner["slot_id"],
                "construction_id": owner["construction_id"],
                "source_instance_id": owner["source_instance_id"],
                "bbox_xywh": bbox,
                "bbox_area_pixels": bbox_pixels,
                "visible_pixels": visible_pixels,
                "visible_area_fraction": fraction,
                "prominence_score": fraction,
                "meets_minimum": fraction >= policy["minimum_visible_area_fraction"],
            }
        )
    ranked = sorted(
        measured,
        key=lambda row: (
            -row["prominence_score"],
            -row["visible_pixels"],
            row["construction_id"],
        ),
    )
    below = sorted(row["construction_id"] for row in ranked if not row["meets_minimum"])
    accepted = not below
    if accepted:
        disposition = "accepted"
    elif (
        observation["promotion_required"]
        and observation["framing_retry_attempt"] < policy["retry"]["maximum_framing_retries"]
    ):
        disposition = policy["retry"]["below_minimum_when_promotion_required"]
    else:
        disposition = policy["retry"]["below_minimum_otherwise"]
    mapping = (
        [
            {
                "slot_id": row["slot_id"],
                "construction_id": row["construction_id"],
                "p_index": f"p{index}",
                "instance_id": index + 1,
            }
            for index, row in enumerate(ranked)
        ]
        if accepted
        else []
    )
    rank_by_construction = {row["construction_id"]: index for index, row in enumerate(ranked)}
    persons = [
        {
            **row,
            "p_index": f"p{rank_by_construction[row['construction_id']]}" if accepted else None,
            "instance_id": rank_by_construction[row["construction_id"]] + 1 if accepted else None,
        }
        for row in sorted(measured, key=lambda value: value["construction_id"])
    ]
    raster_path = Path(construction_map_path)
    raster_payload = raster_path.read_bytes()
    expected_camera_sha256 = _sha(observation["final_camera"])
    observed_camera_sha256 = _sha(observation["camera_readback"])
    content = {
        "scene_id": observation["scene_id"],
        "lineage": {
            "duo_selection_id": duo_selection["selection_id"],
            "duo_selection_sha256": duo_selection["selection_sha256"],
            "resolved_state_id": observation["resolved_state_id"],
            "resolved_state_sha256": observation["resolved_state_sha256"],
            "scene_state_sha256": observation["scene_state_sha256"],
        },
        "policy_version": policy["policy_version"],
        "policy_sha256": _sha(policy),
        "final_frame": {
            "resolution": list(observation["resolution"]),
            "crop": list(observation["crop"]),
            "frame_pixels": frame_pixels,
            "expected_camera_sha256": expected_camera_sha256,
            "observed_camera_sha256": observed_camera_sha256,
            "camera_readback_matches": True,
            "construction_map_sha256": hashlib.sha256(raster_payload).hexdigest(),
            "construction_map_bytes": len(raster_payload),
            "construction_map_encoding": policy["construction_map"]["encoding"],
            "observed_source_instance_ids": sorted(observed_ids - {0}),
        },
        "ranking": {
            "prominence_formula": policy["prominence_formula"],
            "deterministic_tie_break": list(policy["deterministic_tie_break"]),
            "minimum_visible_area_fraction": policy["minimum_visible_area_fraction"],
            "construction_order_is_not_p_index": True,
        },
        "promotion": {
            "required": observation["promotion_required"],
            "framing_retry_attempt": observation["framing_retry_attempt"],
            "maximum_framing_retries": policy["retry"]["maximum_framing_retries"],
            "disposition": disposition,
            "below_minimum_construction_ids": below,
            "partial_mapping_forbidden": True,
        },
        "persons": persons,
        "mapping": mapping,
        "summary": {
            "accepted": accepted,
            "person_count": len(persons),
            "mapping_count": len(mapping),
            "all_declared_people_retained": accepted and len(mapping) == len(persons),
        },
    }
    digest = _sha(content)
    document = {
        "schema_version": "1.0.0",
        "assignment_id": f"dpia_{digest[:24]}",
        "assignment_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_p_index_assignment")
    return document


def validate_p_index_assignment(assignment: Mapping[str, Any]) -> None:
    require_valid_document(assignment, "daz_p_index_assignment")
    _verify_hashed_document(
        assignment,
        id_field="assignment_id",
        hash_field="assignment_sha256",
        prefix="dpia",
    )
    persons = assignment["persons"]
    mapping = assignment["mapping"]
    summary = assignment["summary"]
    promotion = assignment["promotion"]
    accepted = summary["accepted"]
    construction_ids = [row["construction_id"] for row in persons]
    frame_pixels = assignment["final_frame"]["frame_pixels"]
    expected_rank = sorted(
        persons,
        key=lambda row: (
            -row["prominence_score"],
            -row["visible_pixels"],
            row["construction_id"],
        ),
    )
    expected_below = sorted(row["construction_id"] for row in persons if not row["meets_minimum"])
    if (
        construction_ids != sorted(construction_ids)
        or len(construction_ids) != len(set(construction_ids))
        or summary["person_count"] != len(persons)
        or summary["mapping_count"] != len(mapping)
        or promotion["below_minimum_construction_ids"] != expected_below
        or accepted != (promotion["disposition"] == "accepted")
        or assignment["final_frame"]["expected_camera_sha256"]
        != assignment["final_frame"]["observed_camera_sha256"]
    ):
        raise PIndexAssignmentError(
            "p_index_assignment_summary_invalid", assignment["assignment_id"]
        )
    for row in persons:
        fraction = row["visible_pixels"] / frame_pixels
        bbox = row["bbox_xywh"]
        bbox_area = 0 if bbox is None else bbox[2] * bbox[3]
        if (
            row["visible_area_fraction"] != fraction
            or row["prominence_score"] != fraction
            or row["bbox_area_pixels"] != bbox_area
            or row["visible_pixels"] > bbox_area
            or row["meets_minimum"]
            != (fraction >= assignment["ranking"]["minimum_visible_area_fraction"])
        ):
            raise PIndexAssignmentError("p_index_assignment_measurement_invalid", str(row))
    observed_ids = sorted(row["source_instance_id"] for row in persons if row["visible_pixels"] > 0)
    if observed_ids != assignment["final_frame"]["observed_source_instance_ids"]:
        raise PIndexAssignmentError("p_index_assignment_observed_ids_invalid", str(observed_ids))
    if accepted:
        expected_mapping = [
            {
                "slot_id": row["slot_id"],
                "construction_id": row["construction_id"],
                "p_index": f"p{index}",
                "instance_id": index + 1,
            }
            for index, row in enumerate(expected_rank)
        ]
        person_mapping = {
            row["construction_id"]: (row["p_index"], row["instance_id"]) for row in persons
        }
        if (
            expected_below
            or mapping != expected_mapping
            or any(
                person_mapping[row["construction_id"]] != (row["p_index"], row["instance_id"])
                for row in mapping
            )
            or summary["all_declared_people_retained"] is not True
        ):
            raise PIndexAssignmentError("p_index_assignment_mapping_invalid", str(mapping))
    elif (
        not expected_below
        or mapping
        or any(row["p_index"] is not None or row["instance_id"] is not None for row in persons)
        or summary["all_declared_people_retained"] is not False
    ):
        raise PIndexAssignmentError(
            "p_index_assignment_partial_mapping", assignment["assignment_id"]
        )


def publish_p_index_assignment(
    assignment: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    validate_p_index_assignment(assignment)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{assignment['assignment_id']}.json"
    payload = json.dumps(assignment, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise PIndexAssignmentError("p_index_publication_conflict", str(target))
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


def _validate_observation(
    observation: Any, duo_selection: Mapping[str, Any], policy: Mapping[str, Any]
) -> None:
    expected = {
        "schema_version",
        "scene_id",
        "resolved_state_id",
        "resolved_state_sha256",
        "scene_state_sha256",
        "resolution",
        "crop",
        "final_camera",
        "camera_readback",
        "promotion_required",
        "framing_retry_attempt",
        "construction_owners",
    }
    if not isinstance(observation, Mapping) or set(observation) != expected:
        raise PIndexAssignmentError("p_index_observation_fields_invalid", str(observation))
    if (
        observation["schema_version"] != "1.0.0"
        or not isinstance(observation["scene_id"], str)
        or not observation["scene_id"].startswith("daz_scene_")
        or not isinstance(observation["resolved_state_id"], str)
        or not observation["resolved_state_id"].startswith("dcrs_")
        or any(
            not _sha256(observation[field])
            for field in ("resolved_state_sha256", "scene_state_sha256")
        )
    ):
        raise PIndexAssignmentError("p_index_observation_identity_invalid", str(observation))
    resolution = observation["resolution"]
    crop = observation["crop"]
    if (
        not _positive_int_pair(resolution)
        or not isinstance(crop, list)
        or len(crop) != 4
        or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in crop)
        or crop[2] <= 0
        or crop[3] <= 0
        or crop[0] + crop[2] > resolution[0]
        or crop[1] + crop[3] > resolution[1]
    ):
        raise PIndexAssignmentError("p_index_observation_frame_invalid", str(crop))
    if (
        not isinstance(observation["final_camera"], Mapping)
        or not observation["final_camera"]
        or observation["final_camera"] != observation["camera_readback"]
    ):
        raise PIndexAssignmentError("p_index_camera_readback_mismatch", observation["scene_id"])
    try:
        _sha(observation["final_camera"])
    except (TypeError, ValueError) as exc:
        raise PIndexAssignmentError("p_index_camera_noncanonical", str(exc)) from exc
    if (
        not isinstance(observation["promotion_required"], bool)
        or not isinstance(observation["framing_retry_attempt"], int)
        or isinstance(observation["framing_retry_attempt"], bool)
        or observation["framing_retry_attempt"] < 0
    ):
        raise PIndexAssignmentError("p_index_retry_observation_invalid", str(observation))
    owners = observation["construction_owners"]
    expected_slots = {(row["slot_id"], row["construction_id"]) for row in duo_selection["slots"]}
    if (
        not isinstance(owners, list)
        or not 1 <= len(owners) <= policy["maximum_people"]
        or any(
            not isinstance(row, Mapping)
            or set(row) != {"slot_id", "construction_id", "source_instance_id"}
            or not isinstance(row["source_instance_id"], int)
            or isinstance(row["source_instance_id"], bool)
            or not 1 <= row["source_instance_id"] <= 65535
            for row in owners
        )
        or {(row["slot_id"], row["construction_id"]) for row in owners} != expected_slots
        or len({row["source_instance_id"] for row in owners}) != len(owners)
    ):
        raise PIndexAssignmentError("p_index_construction_owners_invalid", str(owners))


def _verify_hashed_document(
    document: Mapping[str, Any], *, id_field: str, hash_field: str, prefix: str
) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, hash_field}
    }
    digest = _sha(content)
    if document[hash_field] != digest or document[id_field] != f"{prefix}_{digest[:24]}":
        raise PIndexAssignmentError("p_index_document_hash_invalid", str(document[id_field]))


def _positive_int_pair(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in value)
    )


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "PIndexAssignmentError",
    "build_p_index_assignment",
    "load_p_index_assignment_policy",
    "publish_p_index_assignment",
    "validate_p_index_assignment",
    "validate_p_index_assignment_policy",
]
