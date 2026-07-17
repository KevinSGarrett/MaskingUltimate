"""Independent V5 render and V6 full-raster semantic validators."""

from __future__ import annotations

import hashlib
import json
import struct
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml
from PIL import Image, UnidentifiedImageError

from ..ontology_source import PART_LABELS
from ..validation import require_valid_document
from .render.instance import decode_u16_png_exact
from .render.relationship import decode_pair_u16_png
from .validation_registry import validate_validation_registry, validate_validation_result


class PassSemanticValidationError(ValueError):
    """A strict V5/V6 policy or authority input is malformed."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_pass_semantic_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_pass_semantic_policy(document)
    return document


def validate_pass_semantic_policy(policy: Mapping[str, Any]) -> None:
    if not isinstance(policy, Mapping) or set(policy) != {
        "schema_version",
        "policy_version",
        "render",
        "semantic",
    }:
        raise PassSemanticValidationError("pass_semantic_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise PassSemanticValidationError("pass_semantic_policy_identity_invalid", str(policy))
    render = policy["render"]
    if not isinstance(render, Mapping) or set(render) != {
        "eligible_profiles",
        "require_execution_report",
        "require_same_state_replay",
        "require_independent_file_hashes",
        "rgb",
        "exr_policy_path",
    }:
        raise PassSemanticValidationError("pass_semantic_render_policy_invalid", str(render))
    if (
        render["eligible_profiles"]
        != ["engineering_minimal", "training_standard", "training_relationship", "diagnostic_full"]
        or render["require_execution_report"] is not True
        or render["require_same_state_replay"] is not True
        or render["require_independent_file_hashes"] is not True
        or render["rgb"]
        != {
            "minimum_unique_colors": 8,
            "minimum_luminance_range": 0.05,
            "maximum_black_or_white_fraction": 0.98,
        }
        or render["exr_policy_path"] != "configs/daz/geometry_pass.yaml"
    ):
        raise PassSemanticValidationError("pass_semantic_render_policy_invalid", str(render))
    semantic = policy["semantic"]
    expected = {
        "ontology_version",
        "allowed_instance_ids",
        "allowed_part_ids",
        "allowed_material_ids",
        "allowed_protected_ids",
        "hard_owner_alpha_minimum",
        "boundary_radius_pixels",
        "minimum_boundary_precision",
        "minimum_boundary_recall",
        "minimum_silhouette_depth_agreement",
        "left_skeleton_value",
        "right_skeleton_value",
        "front_surface_value",
        "back_surface_value",
        "protected_material_ids",
        "front_part_ids",
        "back_part_ids",
    }
    active_parts = [row.id for row in PART_LABELS if row.enabled]
    if (
        not isinstance(semantic, Mapping)
        or set(semantic) != expected
        or semantic["ontology_version"] != "body_parts_v1"
        or semantic["allowed_instance_ids"] != [0, 1, 2, 3, 4]
        or semantic["allowed_part_ids"] != active_parts
        or semantic["allowed_material_ids"] != list(range(16))
        or semantic["allowed_protected_ids"] != [0, 50, 51, 52, 53]
        or semantic["hard_owner_alpha_minimum"] != 32768
        or semantic["boundary_radius_pixels"] != 1
        or not 0 <= semantic["minimum_boundary_precision"] <= 1
        or not 0 <= semantic["minimum_boundary_recall"] <= 1
        or not 0 <= semantic["minimum_silhouette_depth_agreement"] <= 1
        or semantic["protected_material_ids"] != {"50": [13], "51": [14], "52": [14], "53": [9, 14]}
        or semantic["front_part_ids"] != [4, 5, 6, 7, 8, 9, 10, 11]
        or semantic["back_part_ids"] != [34, 35, 48, 49]
    ):
        raise PassSemanticValidationError("pass_semantic_semantic_policy_invalid", str(semantic))


def validate_render_layer(
    plan: Mapping[str, Any],
    execution: Mapping[str, Any],
    execution_report: Mapping[str, Any],
    replay_report: Mapping[str, Any],
    output_paths: Mapping[str, Path],
    *,
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
    evidence_paths: Sequence[str],
) -> dict[str, Any]:
    """Normalize actual-file, D6 execution, and replay defects into V5."""

    validate_pass_semantic_policy(policy)
    validate_validation_registry(registry)
    require_valid_document(plan, "daz_render_pass_plan")
    _verify_hashed(plan, "plan_id", "plan_sha256", "dcrp")
    require_valid_document(execution_report, "daz_render_pass_execution_report")
    _verify_hashed(execution_report, "report_id", "report_sha256", "dcrx")
    require_valid_document(replay_report, "daz_same_state_replay_report")
    _verify_hashed(replay_report, "report_id", "report_sha256", "dssr")
    if plan["profile"] not in policy["render"]["eligible_profiles"]:
        raise PassSemanticValidationError("render_profile_ineligible", plan["profile"])
    _validate_execution_shape(execution)
    findings: list[dict[str, str]] = []
    expected_roles = [row["role"] for row in plan["outputs"]]
    if (
        list(output_paths) != expected_roles
        or [row["role"] for row in execution["passes"]] != expected_roles
    ):
        findings.append(_finding("RENDER_PASS_SET_INVALID", "/outputs", "role_order_or_set"))
    if any(
        value != plan[key]
        for key, value in (
            ("scene_id", execution_report["scene_id"]),
            ("plan_id", execution_report["plan_id"]),
            ("plan_sha256", execution_report["plan_sha256"]),
            ("scene_state_sha256", execution_report["scene_state_sha256"]),
        )
    ):
        findings.append(_finding("RENDER_PROCESS_FAILED", "/execution_report", "lineage"))
    if not execution_report["summary"]["passed"]:
        findings.append(_finding("RENDER_PROCESS_FAILED", "/execution_report", "d6_failed"))
    execution_sha256 = _canonical_sha(execution)
    pass_file_map_sha256 = _canonical_sha(
        [
            {"role": row["role"], "sha256": row["file_sha256"], "bytes": row["bytes"]}
            for row in execution["passes"]
        ]
    )
    if (
        execution_report["execution_sha256"] != execution_sha256
        or execution_report["pass_file_map_sha256"] != pass_file_map_sha256
    ):
        findings.append(_finding("RENDER_PROCESS_FAILED", "/execution", "report_binding"))
    if (
        replay_report["scene_id"] != plan["scene_id"]
        or replay_report["plan_id"] != plan["plan_id"]
        or replay_report["plan_sha256"] != plan["plan_sha256"]
        or replay_report["scene_state_sha256"] != plan["scene_state_sha256"]
        or replay_report["original_execution_sha256"] != execution_report["execution_sha256"]
        or not replay_report["summary"]["passed"]
        or not replay_report["summary"]["semantic_hashes_byte_identical"]
    ):
        findings.append(_finding("RENDER_REPLAY_DRIFT", "/replay_report", "lineage_or_exactness"))
    planned_by_role = {row["role"]: row for row in plan["outputs"]}
    executed_by_role = {row["role"]: row for row in execution["passes"]}
    for role in expected_roles:
        path = Path(output_paths[role]) if role in output_paths else Path("__missing__")
        planned = planned_by_role[role]
        actual = executed_by_role.get(role)
        if actual is None or not path.exists():
            findings.append(_finding("RENDER_PROCESS_FAILED", f"/outputs/{role}", "missing"))
            continue
        try:
            digest, byte_count = _path_digest(path)
            if digest != actual["file_sha256"] or byte_count != actual["bytes"]:
                findings.append(_finding("RENDER_HASH_MISMATCH", f"/outputs/{role}", digest))
            resolution = _decode_render_output(path, planned, policy)
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            findings.append(
                _finding("RENDER_PROCESS_FAILED", f"/outputs/{role}", type(exc).__name__)
            )
            continue
        if resolution != planned["resolution"]:
            findings.append(
                _finding("RENDER_DIMENSION_MISMATCH", f"/outputs/{role}", str(resolution))
            )
    findings.sort(key=lambda row: (row["code"], row["path"], row["detail"]))
    if findings:
        reason = _first_code(
            findings,
            [
                "RENDER_PROCESS_FAILED",
                "RENDER_PASS_SET_INVALID",
                "RENDER_DIMENSION_MISMATCH",
                "RENDER_HASH_MISMATCH",
                "RENDER_REPLAY_DRIFT",
            ],
        )
        status, retryability = "fail", "same_recipe"
    else:
        status, reason, retryability = "pass", "RENDER_VALID", "none"
    return _result(
        "DAZ-V5-001",
        plan["scene_id"],
        status,
        reason,
        findings,
        evidence_paths,
        retryability,
        registry,
    )


def validate_semantic_layer(
    scene_id: str,
    raster_paths: Mapping[str, Path],
    authority: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
    evidence_paths: Sequence[str],
) -> dict[str, Any]:
    """Scan every pixel and normalize cross-map defects into V6."""

    validate_pass_semantic_policy(policy)
    validate_validation_registry(registry)
    _validate_semantic_authority(authority, scene_id, policy)
    expected_roles = [
        "rgb",
        "instance",
        "part",
        "material",
        "protected",
        "coverage_alpha",
        "skeleton_owner",
        "surface_orientation",
        "depth_discontinuity",
    ]
    if list(raster_paths) != expected_roles:
        raise PassSemanticValidationError("semantic_raster_role_order_invalid", str(raster_paths))
    findings: list[dict[str, str]] = []
    try:
        arrays = {
            role: decode_u16_png_exact(Path(raster_paths[role]))[0]
            for role in expected_roles
            if role != "rgb"
        }
        with Image.open(raster_paths["rgb"]) as image:
            if image.format != "PNG" or image.mode != "RGB":
                raise ValueError("rgb_codec")
            rgb = np.asarray(image, dtype=np.uint8)
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        findings.append(_finding("ID_CODEC_INVALID", "/rasters", type(exc).__name__))
        return _semantic_result(scene_id, findings, evidence_paths, registry)
    shape = arrays["instance"].shape
    if rgb.shape[:2] != shape or any(array.shape != shape for array in arrays.values()):
        findings.append(_finding("ID_CODEC_INVALID", "/rasters", "dimension_mismatch"))
        return _semantic_result(scene_id, findings, evidence_paths, registry)
    semantic = policy["semantic"]
    for role, allowed in (
        ("instance", semantic["allowed_instance_ids"]),
        ("part", semantic["allowed_part_ids"]),
        ("material", semantic["allowed_material_ids"]),
        ("protected", semantic["allowed_protected_ids"]),
    ):
        unknown = sorted(set(np.unique(arrays[role]).tolist()) - set(allowed))
        if unknown:
            findings.append(_finding("ID_UNKNOWN_VALUE", f"/{role}", str(unknown)))
    for role, allowed in (
        ("skeleton_owner", [0, 1, 2]),
        ("surface_orientation", [0, 1, 2]),
        ("depth_discontinuity", [0, 1]),
    ):
        unknown = sorted(set(np.unique(arrays[role]).tolist()) - set(allowed))
        if unknown:
            findings.append(_finding("ID_UNKNOWN_VALUE", f"/{role}", str(unknown)))
    instance = arrays["instance"]
    part = arrays["part"]
    material = arrays["material"]
    protected = arrays["protected"]
    alpha = arrays["coverage_alpha"]
    target = authority["target_instance_id"]
    other = set(authority["other_instance_ids"])
    hard_owner = instance > 0
    observed_owners = set(np.unique(instance).tolist()) - {0}
    if observed_owners != {target, *other}:
        findings.append(_finding("ID_OWNERSHIP_INVALID", "/instance", "declared_owner_set"))
    if np.any(hard_owner & ((part == 0) | (material == 0))):
        findings.append(_finding("ID_OWNERSHIP_INVALID", "/owner_maps", "unlabeled_owner_pixel"))
    if np.any(hard_owner & (alpha < semantic["hard_owner_alpha_minimum"])):
        findings.append(_finding("ID_OWNERSHIP_INVALID", "/coverage_alpha", "hard_owner_below_min"))
    if np.any((instance == 0) & (part > 0) & (part < 50)):
        findings.append(_finding("ID_OWNERSHIP_INVALID", "/part", "atomic_part_without_owner"))
    if np.any((instance == 0) & (protected == 0) & (material > 0)):
        findings.append(_finding("ID_OWNERSHIP_INVALID", "/material", "material_without_owner"))
    if np.any((instance == 0) & (protected == 0) & (alpha > 0)):
        findings.append(_finding("ID_OWNERSHIP_INVALID", "/coverage_alpha", "alpha_without_owner"))
    target_mask = instance == target
    other_mask = np.isin(instance, list(other))
    if np.any(target_mask & (protected == 50)) or np.any(other_mask & (protected != 50)):
        findings.append(_finding("ID_OWNERSHIP_INVALID", "/protected/50", "target_other_person"))
    protected_mask = protected > 0
    if np.any(protected_mask & (part != protected)):
        findings.append(_finding("SEMANTIC_MAPPING_INVALID", "/protected", "part_relation"))
    for protected_id, material_ids in semantic["protected_material_ids"].items():
        mask = protected == int(protected_id)
        if np.any(mask & ~np.isin(material, material_ids)):
            findings.append(
                _finding(
                    "SEMANTIC_MAPPING_INVALID", f"/protected/{protected_id}", "material_relation"
                )
            )
    if np.any((part == 1) & (material != 2)):
        findings.append(_finding("SEMANTIC_MAPPING_INVALID", "/part/1", "hair_material"))
    expected_parts = set(authority["expected_visible_part_ids"])
    observed_parts = set(np.unique(part[target_mask]).tolist()) - {0}
    if not expected_parts <= observed_parts or observed_parts & set(authority["absent_part_ids"]):
        findings.append(
            _finding("SEMANTIC_MAPPING_INVALID", "/part/visibility", "expected_or_absent")
        )
    target_pixels = max(1, int(np.sum(target_mask)))
    area_ranges = {row.id: row.expected_area_pct_range for row in PART_LABELS if row.enabled}
    for part_id in authority["area_check_part_ids"]:
        fraction = 100.0 * float(np.sum((part == part_id) & target_mask)) / target_pixels
        minimum, maximum = area_ranges[part_id]
        if not minimum <= fraction <= maximum:
            findings.append(
                _finding(
                    "SEMANTIC_MAPPING_INVALID",
                    f"/part/{part_id}/area",
                    f"pct={fraction:.6f}:expected={minimum:.6f}-{maximum:.6f}",
                )
            )
    _component_findings(part, target_mask, findings)
    _adjacency_findings(part, target_mask, findings)
    skeleton = arrays["skeleton_owner"]
    left_ids = {row.id for row in PART_LABELS if row.enabled and row.side == "left"}
    right_ids = {row.id for row in PART_LABELS if row.enabled and row.side == "right"}
    if np.any(
        np.isin(part, list(left_ids)) & (skeleton != semantic["left_skeleton_value"])
    ) or np.any(np.isin(part, list(right_ids)) & (skeleton != semantic["right_skeleton_value"])):
        findings.append(_finding("SEMANTIC_MAPPING_INVALID", "/skeleton_owner", "left_right"))
    sided_mask = np.isin(part, list(left_ids | right_ids))
    if np.any(~sided_mask & (skeleton != 0)):
        findings.append(_finding("SEMANTIC_MAPPING_INVALID", "/skeleton_owner", "unscoped_vote"))
    surface = arrays["surface_orientation"]
    if np.any(
        np.isin(part, semantic["front_part_ids"]) & (surface != semantic["front_surface_value"])
    ) or np.any(
        np.isin(part, semantic["back_part_ids"]) & (surface != semantic["back_surface_value"])
    ):
        findings.append(_finding("SEMANTIC_MAPPING_INVALID", "/surface_orientation", "front_back"))
    part_boundary = _label_boundary(part) & target_mask
    rgb_boundary = _rgb_boundary(rgb) & _dilate(part_boundary, semantic["boundary_radius_pixels"])
    precision, recall = _boundary_scores(
        part_boundary, rgb_boundary, semantic["boundary_radius_pixels"]
    )
    silhouette_boundary = _binary_boundary(target_mask)
    depth_boundary = arrays["depth_discontinuity"] > 0
    _depth_precision, depth_recall = _boundary_scores(
        silhouette_boundary, depth_boundary, semantic["boundary_radius_pixels"]
    )
    if (
        precision < semantic["minimum_boundary_precision"]
        or recall < semantic["minimum_boundary_recall"]
        or depth_recall < semantic["minimum_silhouette_depth_agreement"]
        or np.any(part_boundary & (alpha == 0))
    ):
        findings.append(
            _finding(
                "SEMANTIC_BOUNDARY_INVALID",
                "/boundaries",
                f"precision={precision:.6f}:recall={recall:.6f}:depth={depth_recall:.6f}",
            )
        )
    findings.sort(key=lambda row: (row["code"], row["path"], row["detail"]))
    return _semantic_result(scene_id, findings, evidence_paths, registry)


def _semantic_result(
    scene_id: str,
    findings: list[dict[str, str]],
    evidence_paths: Sequence[str],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    if findings:
        reason = _first_code(
            findings,
            [
                "ID_CODEC_INVALID",
                "ID_UNKNOWN_VALUE",
                "ID_OWNERSHIP_INVALID",
                "SEMANTIC_MAPPING_INVALID",
                "SEMANTIC_BOUNDARY_INVALID",
            ],
        )
        status, retryability = "fail", "asset_retest"
    else:
        status, reason, retryability = "pass", "SEMANTIC_VALID", "none"
    return _result(
        "DAZ-V6-001",
        scene_id,
        status,
        reason,
        findings,
        evidence_paths,
        retryability,
        registry,
    )


def _validate_semantic_authority(
    authority: Mapping[str, Any], scene_id: str, policy: Mapping[str, Any]
) -> None:
    expected = {
        "schema_version",
        "scene_id",
        "provider_id",
        "authority_tier",
        "ontology_version",
        "ontology_sha256",
        "owner",
        "package_revision",
        "certificate_id",
        "certificate_sha256",
        "certificate_scope",
        "transform_chain_sha256",
        "target_instance_id",
        "other_instance_ids",
        "expected_visible_part_ids",
        "absent_part_ids",
        "area_check_part_ids",
    }
    if not isinstance(authority, Mapping) or set(authority) != expected:
        raise PassSemanticValidationError("semantic_authority_fields_invalid", str(authority))
    scalar_strings = [
        "provider_id",
        "authority_tier",
        "owner",
        "package_revision",
        "certificate_id",
        "certificate_scope",
    ]
    sha_fields = ["ontology_sha256", "certificate_sha256", "transform_chain_sha256"]
    if (
        authority["schema_version"] != "1.0.0"
        or authority["scene_id"] != scene_id
        or authority["ontology_version"] != policy["semantic"]["ontology_version"]
        or any(
            not isinstance(authority[field], str) or not authority[field]
            for field in scalar_strings
        )
        or authority["owner"] != "maskfactory"
        or any(not _sha256(authority[field]) for field in sha_fields)
        or authority["target_instance_id"] not in {1, 2, 3, 4}
        or not _unique_ints(authority["other_instance_ids"], allow_empty=True)
        or authority["target_instance_id"] in authority["other_instance_ids"]
        or not set(authority["other_instance_ids"]) <= {1, 2, 3, 4}
        or not _unique_ints(authority["expected_visible_part_ids"], allow_empty=True)
        or not _unique_ints(authority["absent_part_ids"], allow_empty=True)
        or not _unique_ints(authority["area_check_part_ids"], allow_empty=True)
        or not set(authority["expected_visible_part_ids"])
        <= set(policy["semantic"]["allowed_part_ids"])
        or not set(authority["absent_part_ids"]) <= set(policy["semantic"]["allowed_part_ids"])
        or not set(authority["area_check_part_ids"]) <= set(authority["expected_visible_part_ids"])
        or set(authority["expected_visible_part_ids"]) & set(authority["absent_part_ids"])
    ):
        raise PassSemanticValidationError("semantic_authority_invalid", str(authority))


def _decode_render_output(
    path: Path, planned: Mapping[str, Any], policy: Mapping[str, Any]
) -> list[int]:
    encoding = planned["encoding"]
    if encoding == "lossless_rgb_png":
        with Image.open(path) as image:
            if image.format != "PNG" or image.mode != "RGB":
                raise ValueError("rgb_codec_invalid")
            array = np.asarray(image, dtype=np.uint8)
        flat = array.reshape(-1, 3)
        luminance = array.astype(np.float32).mean(axis=2) / 255.0
        black_or_white = np.mean((luminance <= 1 / 255) | (luminance >= 254 / 255))
        rgb_policy = policy["render"]["rgb"]
        if (
            len(np.unique(flat, axis=0)) < rgb_policy["minimum_unique_colors"]
            or float(np.ptp(luminance)) < rgb_policy["minimum_luminance_range"]
            or black_or_white > rgb_policy["maximum_black_or_white_fraction"]
        ):
            raise ValueError("rgb_content_invalid")
        return [int(array.shape[1]), int(array.shape[0])]
    if encoding in {"uint16_png", "uint16_linear_png"}:
        array, _codec = decode_u16_png_exact(path)
        return [int(array.shape[1]), int(array.shape[0])]
    if encoding == "two_channel_uint16_png":
        array, _codec = decode_pair_u16_png(path)
        return [int(array.shape[1]), int(array.shape[0])]
    if encoding in {"float32_exr", "float_exr_camera_space", "uint32_exr"}:
        return _inspect_exr_resolution(path, encoding)
    if encoding == "diagnostic_tree":
        if not path.is_dir() or not any(row.is_file() for row in path.rglob("*")):
            raise ValueError("diagnostic_tree_invalid")
        return list(planned["resolution"])
    raise ValueError(f"encoding_unknown:{encoding}")


def _component_findings(
    part: np.ndarray, target_mask: np.ndarray, findings: list[dict[str, str]]
) -> None:
    limits = {row.id: row.max_components for row in PART_LABELS if row.enabled}
    for part_id in sorted(set(np.unique(part[target_mask]).tolist()) - {0}):
        count = _component_count((part == part_id) & target_mask)
        limit = limits.get(part_id)
        if limit is not None and count > limit:
            findings.append(
                _finding(
                    "SEMANTIC_MAPPING_INVALID", f"/part/{part_id}", f"components={count}>{limit}"
                )
            )


def _adjacency_findings(
    part: np.ndarray, target_mask: np.ndarray, findings: list[dict[str, str]]
) -> None:
    names = {row.name: row.id for row in PART_LABELS if row.enabled}
    chains = {
        "left_wrist": ("left_hand_base", "left_forearm"),
        "right_wrist": ("right_hand_base", "right_forearm"),
        "left_elbow": ("left_upper_arm", "left_forearm"),
        "right_elbow": ("right_upper_arm", "right_forearm"),
        "left_knee": ("left_thigh", "left_calf"),
        "right_knee": ("right_thigh", "right_calf"),
        "left_ankle": ("left_calf", "left_foot_base"),
        "right_ankle": ("right_calf", "right_foot_base"),
        "left_toes": ("left_foot_base",),
        "right_toes": ("right_foot_base",),
        "neck": ("head_face",),
        "left_thumb": ("left_hand_base",),
        "right_thumb": ("right_hand_base",),
        "left_index_finger": ("left_hand_base",),
        "right_index_finger": ("right_hand_base",),
        "left_middle_finger": ("left_hand_base",),
        "right_middle_finger": ("right_hand_base",),
        "left_ring_finger": ("left_hand_base",),
        "right_ring_finger": ("right_hand_base",),
        "left_pinky": ("left_hand_base",),
        "right_pinky": ("right_hand_base",),
    }
    observed = set(np.unique(part[target_mask]).tolist())
    for name, neighbors in chains.items():
        part_id = names[name]
        if part_id not in observed:
            continue
        mask = (part == part_id) & target_mask
        for neighbor in neighbors:
            neighbor_id = names[neighbor]
            if neighbor_id in observed and not np.any(_dilate(mask, 1) & (part == neighbor_id)):
                findings.append(
                    _finding(
                        "SEMANTIC_MAPPING_INVALID",
                        f"/part/{part_id}/adjacency/{neighbor_id}",
                        f"{name}:{neighbor}",
                    )
                )


def _inspect_exr_resolution(path: Path, encoding: str) -> list[int]:
    payload = path.read_bytes()
    if len(payload) < 32 or payload[:4] != bytes.fromhex("762f3101"):
        raise ValueError("exr_header_invalid")
    position = 8
    attributes: dict[str, tuple[str, bytes]] = {}
    while position < len(payload):
        end = payload.find(b"\0", position)
        if end < 0:
            raise ValueError("exr_attribute_name_invalid")
        if end == position:
            break
        name = payload[position:end].decode("ascii")
        position = end + 1
        end = payload.find(b"\0", position)
        if end < 0:
            raise ValueError("exr_attribute_type_invalid")
        kind = payload[position:end].decode("ascii")
        position = end + 1
        if position + 4 > len(payload):
            raise ValueError("exr_attribute_size_invalid")
        size = struct.unpack_from("<I", payload, position)[0]
        position += 4
        if size > 16_777_216 or position + size > len(payload):
            raise ValueError("exr_attribute_payload_invalid")
        attributes[name] = (kind, payload[position : position + size])
        position += size
    kind, data = attributes.get("dataWindow", ("", b""))
    channel_kind, channel_data = attributes.get("channels", ("", b""))
    if kind != "box2i" or len(data) != 16 or channel_kind != "chlist":
        raise ValueError("exr_required_attributes_missing")
    xmin, ymin, xmax, ymax = struct.unpack("<iiii", data)
    if xmin != 0 or ymin != 0 or xmax < xmin or ymax < ymin:
        raise ValueError("exr_data_window_invalid")
    channels = []
    position = 0
    while position < len(channel_data) and channel_data[position] != 0:
        end = channel_data.find(b"\0", position)
        if end < 0 or end + 17 > len(channel_data):
            raise ValueError("exr_channel_list_invalid")
        name = channel_data[position:end].decode("ascii")
        pixel_type = struct.unpack_from("<i", channel_data, end + 1)[0]
        x_sampling, y_sampling = struct.unpack_from("<ii", channel_data, end + 9)
        if x_sampling != 1 or y_sampling != 1:
            raise ValueError("exr_channel_sampling_invalid")
        channels.append((name, pixel_type))
        position = end + 17
    expected_pixel_type = 0 if encoding == "uint32_exr" else 2
    expected_count = 3 if encoding == "float_exr_camera_space" else 1
    if len(channels) != expected_count or any(
        pixel_type != expected_pixel_type for _name, pixel_type in channels
    ):
        raise ValueError("exr_channel_contract_invalid")
    return [xmax - xmin + 1, ymax - ymin + 1]


def _path_digest(path: Path) -> tuple[str, int]:
    if path.is_file():
        payload = path.read_bytes()
        return hashlib.sha256(payload).hexdigest(), len(payload)
    if not path.is_dir():
        raise ValueError("output_path_missing")
    records = []
    total = 0
    for child in sorted(path.rglob("*")):
        if child.is_file():
            payload = child.read_bytes()
            total += len(payload)
            records.append(
                {
                    "path": child.relative_to(path).as_posix(),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "bytes": len(payload),
                }
            )
    if not records:
        raise ValueError("output_directory_empty")
    digest = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return digest, total


def _component_count(mask: np.ndarray) -> int:
    visited = np.zeros(mask.shape, dtype=bool)
    count = 0
    height, width = mask.shape
    for y, x in np.argwhere(mask):
        if visited[y, x]:
            continue
        count += 1
        visited[y, x] = True
        queue: deque[tuple[int, int]] = deque([(int(y), int(x))])
        while queue:
            cy, cx = queue.popleft()
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    queue.append((ny, nx))
    return count


def _label_boundary(labels: np.ndarray) -> np.ndarray:
    result = np.zeros(labels.shape, dtype=bool)
    result[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    result[:, :-1] |= labels[:, 1:] != labels[:, :-1]
    result[1:, :] |= labels[1:, :] != labels[:-1, :]
    result[:-1, :] |= labels[1:, :] != labels[:-1, :]
    return result & (labels > 0)


def _binary_boundary(mask: np.ndarray) -> np.ndarray:
    return _label_boundary(mask.astype(np.uint16))


def _rgb_boundary(rgb: np.ndarray) -> np.ndarray:
    difference = np.zeros(rgb.shape[:2], dtype=np.uint16)
    horizontal = np.max(np.abs(rgb[:, 1:].astype(np.int16) - rgb[:, :-1].astype(np.int16)), axis=2)
    vertical = np.max(np.abs(rgb[1:, :].astype(np.int16) - rgb[:-1, :].astype(np.int16)), axis=2)
    difference[:, 1:] = np.maximum(difference[:, 1:], horizontal)
    difference[:, :-1] = np.maximum(difference[:, :-1], horizontal)
    difference[1:, :] = np.maximum(difference[1:, :], vertical)
    difference[:-1, :] = np.maximum(difference[:-1, :], vertical)
    return difference >= 8


def _boundary_scores(
    reference: np.ndarray, candidate: np.ndarray, radius: int
) -> tuple[float, float]:
    candidate_near = _dilate(candidate, radius)
    reference_near = _dilate(reference, radius)
    precision = float(np.sum(candidate & reference_near) / max(1, np.sum(candidate)))
    recall = float(np.sum(reference & candidate_near) / max(1, np.sum(reference)))
    return precision, recall


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    result = mask.copy()
    for _ in range(radius):
        expanded = result.copy()
        expanded[1:, :] |= result[:-1, :]
        expanded[:-1, :] |= result[1:, :]
        expanded[:, 1:] |= result[:, :-1]
        expanded[:, :-1] |= result[:, 1:]
        result = expanded
    return result


def _validate_execution_shape(execution: Mapping[str, Any]) -> None:
    if (
        not isinstance(execution, Mapping)
        or set(execution)
        != {
            "schema_version",
            "scene_id",
            "plan_id",
            "plan_sha256",
            "passes",
            "semantic_passes_rendered",
            "parent_semantic_set_sha256",
            "terminal_scene_state_sha256",
        }
        or not isinstance(execution["passes"], list)
    ):
        raise PassSemanticValidationError("render_execution_invalid", str(execution))


def _result(
    validator_id: str,
    entity_id: str,
    status: str,
    reason_code: str,
    findings: Sequence[Mapping[str, str]],
    evidence_paths: Sequence[str],
    retryability: str,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    validator = next(row for row in registry["validators"] if row["validator_id"] == validator_id)
    result = {
        "validator_id": validator_id,
        "validator_version": validator["validator_version"],
        "entity_id": entity_id,
        "status": status,
        "reason_code": reason_code,
        "metric": "defect_count",
        "observed": {"defect_count": len(findings), "findings": list(findings)},
        "expected": {"operator": "eq", "value": 0},
        "evidence_paths": sorted(set(evidence_paths)),
        "retryability": retryability,
        "affected_asset_ids": [],
        "affected_mapping_ids": [],
    }
    validate_validation_result(result, registry)
    return result


def _verify_hashed(
    document: Mapping[str, Any], id_field: str, hash_field: str, prefix: str
) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, hash_field}
    }
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    if document[hash_field] != digest or document[id_field] != f"{prefix}_{digest[:24]}":
        raise PassSemanticValidationError("bound_report_hash_invalid", str(document[id_field]))


def _canonical_sha(document: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _finding(code: str, path: str, detail: str) -> dict[str, str]:
    return {"code": code, "path": path, "detail": detail}


def _first_code(findings: Sequence[Mapping[str, str]], priorities: Sequence[str]) -> str:
    codes = {row["code"] for row in findings}
    return next(code for code in priorities if code in codes)


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _unique_ints(values: Any, *, allow_empty: bool) -> bool:
    return (
        isinstance(values, list)
        and (allow_empty or bool(values))
        and values == sorted(set(values))
        and all(isinstance(value, int) and not isinstance(value, bool) for value in values)
    )
