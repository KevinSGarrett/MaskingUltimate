"""Seal and replay the fully evaluated DAZ character and scene state."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...validation import require_valid_document


class ResolvedSceneStateError(ValueError):
    """Final DAZ state does not exactly satisfy its selected upstream plan."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_resolved_scene_state_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_resolved_scene_state_policy(document)
    return document


def validate_resolved_scene_state_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "numeric_tolerances",
        "required_asset_roles",
        "optional_asset_roles",
        "required_scene_state_components",
        "default_scene_must_be_empty",
        "unexpected_renderable_nodes_allowed",
        "unresolved_textures_allowed",
        "locked_or_silently_ignored_requested_properties_allowed",
        "undeclared_controller_side_effects_allowed",
        "preflight_disposition_required",
        "semantic_replay_hash_must_match",
        "annotation_restore_hash_must_match",
        "finite_values_required",
        "immutable_publication",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise ResolvedSceneStateError("resolved_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise ResolvedSceneStateError("resolved_policy_version_invalid", "version")
    tolerances = policy["numeric_tolerances"]
    if (
        not isinstance(tolerances, Mapping)
        or set(tolerances) != {"property_value", "joint_degrees", "transform", "camera_scalar"}
        or any(not _finite(value) or value < 0 for value in tolerances.values())
    ):
        raise ResolvedSceneStateError("resolved_policy_tolerances_invalid", str(tolerances))
    for key in ("required_asset_roles", "optional_asset_roles", "required_scene_state_components"):
        values = policy[key]
        if not isinstance(values, list) or not values or len(values) != len(set(values)):
            raise ResolvedSceneStateError("resolved_policy_list_invalid", key)
    if set(policy["required_asset_roles"]) & set(policy["optional_asset_roles"]):
        raise ResolvedSceneStateError("resolved_policy_role_overlap", "roles")
    if (
        policy["default_scene_must_be_empty"] is not True
        or policy["unexpected_renderable_nodes_allowed"] != 0
        or policy["unresolved_textures_allowed"] != 0
        or policy["locked_or_silently_ignored_requested_properties_allowed"] != 0
        or policy["undeclared_controller_side_effects_allowed"] != 0
        or policy["preflight_disposition_required"] != "accept"
        or any(
            policy[key] is not True
            for key in (
                "semantic_replay_hash_must_match",
                "annotation_restore_hash_must_match",
                "finite_values_required",
                "immutable_publication",
            )
        )
    ):
        raise ResolvedSceneStateError("resolved_policy_fail_closed_invalid", "policy")


def seal_resolved_scene_state(
    foundation: Mapping[str, Any],
    profile: Mapping[str, Any],
    appearance: Mapping[str, Any],
    pose: Mapping[str, Any],
    formation: Mapping[str, Any],
    preflight: Mapping[str, Any],
    readback: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify all selected/applied values and seal one immutable semantic scene state."""

    validate_resolved_scene_state_policy(policy)
    schemas = (
        (foundation, "daz_character_foundation_selection", "selection"),
        (profile, "daz_character_variation_profile", "profile"),
        (appearance, "daz_character_appearance_selection", "selection"),
        (pose, "daz_solo_pose_selection", "selection"),
        (formation, "daz_scene_formation_selection", "selection"),
        (preflight, "daz_scene_preflight_report", "report"),
    )
    for document, schema, kind in schemas:
        require_valid_document(document, schema)
        _verify_document_hash(document, kind)
    for document, label in ((appearance, "appearance"), (pose, "pose"), (formation, "formation")):
        if (
            document["foundation_selection_id"] != foundation["selection_id"]
            or document["foundation_selection_sha256"] != foundation["selection_sha256"]
        ):
            raise ResolvedSceneStateError("resolved_foundation_lineage_mismatch", label)
    if profile["anatomy_configuration"] != appearance["request"]["anatomy_configuration"]:
        raise ResolvedSceneStateError("resolved_profile_anatomy_mismatch", profile["profile_id"])
    if (
        preflight["pose_selection_id"] != pose["selection_id"]
        or preflight["pose_selection_sha256"] != pose["selection_sha256"]
        or preflight["formation_selection_id"] != formation["selection_id"]
        or preflight["formation_selection_sha256"] != formation["selection_sha256"]
    ):
        raise ResolvedSceneStateError("resolved_preflight_lineage_mismatch", preflight["report_id"])
    if preflight["summary"]["disposition"] != policy["preflight_disposition_required"]:
        raise ResolvedSceneStateError("resolved_preflight_not_accepted", preflight["report_id"])
    _validate_readback(readback, policy)
    if readback["scene_id"] != preflight["scene_id"]:
        raise ResolvedSceneStateError("resolved_scene_id_mismatch", readback["scene_id"])
    lineage = {
        "foundation_selection_id": foundation["selection_id"],
        "foundation_selection_sha256": foundation["selection_sha256"],
        "profile_id": profile["profile_id"],
        "profile_sha256": profile["profile_sha256"],
        "appearance_selection_id": appearance["selection_id"],
        "appearance_selection_sha256": appearance["selection_sha256"],
        "pose_selection_id": pose["selection_id"],
        "pose_selection_sha256": pose["selection_sha256"],
        "formation_selection_id": formation["selection_id"],
        "formation_selection_sha256": formation["selection_sha256"],
        "preflight_report_id": preflight["report_id"],
        "preflight_report_sha256": preflight["report_sha256"],
    }
    if readback["lineage"] != lineage:
        raise ResolvedSceneStateError("resolved_readback_lineage_mismatch", readback["scene_id"])
    expected_assets = _expected_assets(foundation, appearance, pose, formation)
    actual_assets = {row["role"]: row["asset_id"] for row in readback["assets"]}
    if len(actual_assets) != len(readback["assets"]) or actual_assets != expected_assets:
        raise ResolvedSceneStateError(
            "resolved_asset_readback_mismatch",
            json.dumps({"expected": expected_assets, "actual": actual_assets}, sort_keys=True),
        )
    _verify_properties(readback["property_values"], profile, appearance, policy)
    _verify_joints(readback["joint_values"], pose, policy)
    _compare_value(
        formation["selected"]["camera"],
        readback["camera"],
        policy["numeric_tolerances"]["camera_scalar"],
        "camera",
    )
    expected_formation = {
        "light_asset_id": formation["selected"]["light"]["asset_id"],
        "environment_asset_id": formation["selected"]["environment"]["asset_id"],
        "prop_asset_id": (
            formation["selected"]["prop"]["asset_id"]
            if formation["selected"]["prop"] is not None
            else None
        ),
    }
    if readback["lighting_environment"] != expected_formation:
        raise ResolvedSceneStateError("resolved_formation_readback_mismatch", readback["scene_id"])
    if not readback["default_scene_empty_before_load"]:
        raise ResolvedSceneStateError("resolved_default_scene_not_empty", readback["scene_id"])
    if readback["unexpected_renderable_node_count"] != 0:
        raise ResolvedSceneStateError("resolved_unexpected_renderable_nodes", readback["scene_id"])
    if readback["unresolved_textures"]:
        raise ResolvedSceneStateError(
            "resolved_unresolved_textures", ",".join(readback["unresolved_textures"])
        )
    state_content = {
        key: value
        for key, value in readback.items()
        if key
        not in {"semantic_replay_scene_state_sha256", "annotation_restore_scene_state_sha256"}
    }
    scene_state_sha256 = _canonical_sha(state_content)
    if readback["semantic_replay_scene_state_sha256"] != scene_state_sha256:
        raise ResolvedSceneStateError("resolved_semantic_replay_mismatch", readback["scene_id"])
    if readback["annotation_restore_scene_state_sha256"] != scene_state_sha256:
        raise ResolvedSceneStateError("resolved_annotation_restore_mismatch", readback["scene_id"])
    content = {
        "scene_id": readback["scene_id"],
        "lineage": lineage,
        "runtime_snapshot_sha256": readback["runtime_snapshot_sha256"],
        "script_bundle_sha256": readback["script_bundle_sha256"],
        "mapping_set_sha256": readback["mapping_set_sha256"],
        "scene_state_sha256": scene_state_sha256,
        "state": state_content,
        "replay_evidence": {
            "semantic_replay_scene_state_sha256": readback["semantic_replay_scene_state_sha256"],
            "annotation_restore_scene_state_sha256": readback[
                "annotation_restore_scene_state_sha256"
            ],
            "semantic_replay_matches": True,
            "annotation_restore_matches": True,
        },
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "resolved_state_id": f"dcrs_{digest[:24]}",
        "resolved_state_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_resolved_scene_state")
    return document


def validate_resolved_scene_state(
    document: Mapping[str, Any],
    foundation: Mapping[str, Any],
    profile: Mapping[str, Any],
    appearance: Mapping[str, Any],
    pose: Mapping[str, Any],
    formation: Mapping[str, Any],
    preflight: Mapping[str, Any],
    readback: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    require_valid_document(document, "daz_resolved_scene_state")
    expected = seal_resolved_scene_state(
        foundation, profile, appearance, pose, formation, preflight, readback, policy
    )
    if document != expected:
        raise ResolvedSceneStateError(
            "resolved_state_replay_mismatch", document["resolved_state_id"]
        )


def publish_resolved_scene_state(
    document: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    require_valid_document(document, "daz_resolved_scene_state")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{document['resolved_state_id']}.json"
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise ResolvedSceneStateError("resolved_state_publication_conflict", str(target))
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


def _expected_assets(
    foundation: Mapping[str, Any],
    appearance: Mapping[str, Any],
    pose: Mapping[str, Any],
    formation: Mapping[str, Any],
) -> dict[str, str]:
    result = {
        "figure": foundation["selected"]["figure_asset_id"],
        "character_preset": foundation["selected"]["character_preset_asset_id"],
        "skin_material": foundation["selected"]["skin_material_asset_id"],
        "anatomy": appearance["selected"]["anatomy_asset_id"],
        "pose": pose["selected"]["pose_asset_id"],
        "light": formation["selected"]["light"]["asset_id"],
        "environment": formation["selected"]["environment"]["asset_id"],
    }
    if appearance["selected"]["hair_asset_id"] is not None:
        result["hair"] = appearance["selected"]["hair_asset_id"]
    for index, item in enumerate(appearance["selected"]["wardrobe_items_inner_to_outer"]):
        result[f"wardrobe_{index:02d}"] = item["asset_id"]
    if formation["selected"]["prop"] is not None:
        result["prop"] = formation["selected"]["prop"]["asset_id"]
    return dict(sorted(result.items()))


def _verify_properties(
    rows: list[Mapping[str, Any]],
    profile: Mapping[str, Any],
    appearance: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    if not rows:
        raise ResolvedSceneStateError("resolved_property_readback_empty", profile["profile_id"])
    allowed_sources = {profile["profile_id"], appearance["selection_id"]}
    seen = set()
    for row in rows:
        uri = row["uri"]
        if uri in seen:
            raise ResolvedSceneStateError("resolved_property_duplicate", uri)
        seen.add(uri)
        if row["source_id"] not in allowed_sources:
            raise ResolvedSceneStateError("resolved_property_source_invalid", uri)
        if row["locked"] or row["silently_ignored"]:
            raise ResolvedSceneStateError("resolved_property_not_applied", uri)
        if not row["minimum"] <= row["final_value"] <= row["maximum"]:
            raise ResolvedSceneStateError("resolved_property_out_of_range", uri)
        tolerance = min(row["tolerance"], policy["numeric_tolerances"]["property_value"])
        if abs(row["requested_value"] - row["final_value"]) > tolerance:
            raise ResolvedSceneStateError("resolved_property_readback_mismatch", uri)


def _verify_joints(
    rows: list[Mapping[str, Any]], pose: Mapping[str, Any], policy: Mapping[str, Any]
) -> None:
    expected = {
        (bone, axis): value
        for bone, axes in pose["selected"]["bone_rotations_deg"].items()
        for axis, value in axes.items()
    }
    actual = {(row["bone"], row["axis"]): row for row in rows}
    if len(actual) != len(rows) or set(actual) != set(expected):
        raise ResolvedSceneStateError("resolved_joint_set_mismatch", pose["selection_id"])
    tolerance = policy["numeric_tolerances"]["joint_degrees"]
    for key, requested in expected.items():
        row = actual[key]
        if (
            row["requested_degrees"] != requested
            or abs(row["final_degrees"] - requested) > tolerance
        ):
            raise ResolvedSceneStateError("resolved_joint_readback_mismatch", f"{key[0]}:{key[1]}")
        if not row["minimum_degrees"] <= row["final_degrees"] <= row["maximum_degrees"]:
            raise ResolvedSceneStateError("resolved_joint_out_of_range", f"{key[0]}:{key[1]}")


def _validate_readback(readback: Any, policy: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "scene_id",
        "lineage",
        "runtime_snapshot_sha256",
        "script_bundle_sha256",
        "mapping_set_sha256",
        "default_scene_empty_before_load",
        "unexpected_renderable_node_count",
        "assets",
        "property_values",
        "controller_side_effects",
        "joint_values",
        "node_hierarchy",
        "geometry_fingerprints",
        "world_transforms",
        "material_assignments",
        "opacity_parameters",
        "camera",
        "lighting_environment",
        "visibility_flags",
        "renderer",
        "pass_profile",
        "unresolved_textures",
        "semantic_replay_scene_state_sha256",
        "annotation_restore_scene_state_sha256",
    }
    if not isinstance(readback, Mapping) or set(readback) != required:
        raise ResolvedSceneStateError("resolved_readback_fields_invalid", str(readback))
    if readback["schema_version"] != "1.0.0" or not readback["scene_id"].startswith("daz_scene_"):
        raise ResolvedSceneStateError(
            "resolved_readback_identity_invalid", str(readback.get("scene_id"))
        )
    _assert_json_finite(readback)
    for key in (
        "runtime_snapshot_sha256",
        "script_bundle_sha256",
        "mapping_set_sha256",
        "semantic_replay_scene_state_sha256",
        "annotation_restore_scene_state_sha256",
    ):
        if not isinstance(readback[key], str) or len(readback[key]) != 64:
            raise ResolvedSceneStateError("resolved_readback_hash_invalid", key)
    if not isinstance(readback["unexpected_renderable_node_count"], int):
        raise ResolvedSceneStateError("resolved_readback_count_invalid", "nodes")
    for key in (
        "assets",
        "property_values",
        "controller_side_effects",
        "joint_values",
        "unresolved_textures",
    ):
        if not isinstance(readback[key], list):
            raise ResolvedSceneStateError("resolved_readback_collection_invalid", key)
    for row in readback["controller_side_effects"]:
        if not row.get("declared", False):
            raise ResolvedSceneStateError(
                "resolved_controller_side_effect_undeclared", str(row.get("uri"))
            )
    for component in policy["required_scene_state_components"]:
        if component not in readback:
            raise ResolvedSceneStateError("resolved_state_component_missing", component)


def _verify_document_hash(document: Mapping[str, Any], kind: str) -> None:
    if kind == "profile":
        id_key, hash_key, prefix = "profile_id", "profile_sha256", "dcvp_"
    elif kind == "report":
        id_key, hash_key, prefix = "report_id", "report_sha256", "dcpf_"
    else:
        id_key, hash_key = "selection_id", "selection_sha256"
        prefix = document[id_key].split("_", 1)[0] + "_"
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_key, hash_key}
    }
    digest = _canonical_sha(content)
    if document[hash_key] != digest or document[id_key] != f"{prefix}{digest[:24]}":
        raise ResolvedSceneStateError("resolved_upstream_hash_invalid", str(document[id_key]))


def _compare_value(expected: Any, actual: Any, tolerance: float, path: str) -> None:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping) or set(expected) != set(actual):
            raise ResolvedSceneStateError("resolved_value_shape_mismatch", path)
        for key in expected:
            _compare_value(expected[key], actual[key], tolerance, f"{path}/{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise ResolvedSceneStateError("resolved_value_shape_mismatch", path)
        for index, value in enumerate(expected):
            _compare_value(value, actual[index], tolerance, f"{path}/{index}")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not _finite(actual) or abs(float(expected) - float(actual)) > tolerance:
            raise ResolvedSceneStateError("resolved_numeric_readback_mismatch", path)
    elif expected != actual:
        raise ResolvedSceneStateError("resolved_value_readback_mismatch", path)


def _assert_json_finite(value: Any, path: str = "") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ResolvedSceneStateError("resolved_nonfinite_value", path or "/")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_finite(item, f"{path}/{index}")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _assert_json_finite(item, f"{path}/{key}")


def _canonical_sha(document: Any) -> str:
    try:
        payload = json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ResolvedSceneStateError("resolved_noncanonical_value", str(exc)) from exc
    return hashlib.sha256(payload).hexdigest()


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


__all__ = [
    "ResolvedSceneStateError",
    "load_resolved_scene_state_policy",
    "publish_resolved_scene_state",
    "seal_resolved_scene_state",
    "validate_resolved_scene_state",
    "validate_resolved_scene_state_policy",
]
