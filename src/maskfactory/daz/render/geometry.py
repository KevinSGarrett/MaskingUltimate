"""Linear camera depth, right-handed normals, and coordinate sidecars."""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

from ...validation import require_valid_document
from .instance import decode_u16_png_exact


class GeometryPassContractError(ValueError):
    """A geometry policy, coordinate sidecar, contract, execution, or EXR is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_geometry_pass_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_geometry_pass_policy(document)
    return document


def validate_geometry_pass_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "eligible_profiles",
        "exr",
        "depth",
        "normals",
        "coordinates",
        "visibility",
        "freeze",
        "forbidden_effects",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise GeometryPassContractError("geometry_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise GeometryPassContractError("geometry_policy_identity_invalid", str(policy))
    if policy["eligible_profiles"] != [
        "training_standard",
        "training_relationship",
        "diagnostic_full",
    ]:
        raise GeometryPassContractError(
            "geometry_policy_profiles_invalid", str(policy["eligible_profiles"])
        )
    if policy["exr"] != {
        "magic_hex": "762f3101",
        "version": 2,
        "compression": "zip_scanline_16",
        "compression_code": 3,
        "pixel_type": "float32",
        "pixel_type_code": 2,
        "sampling": [1, 1],
        "data_window_origin": [0, 0],
        "display_window_matches_data_window": True,
        "line_order": "increasing_y",
        "line_order_code": 0,
        "pixel_aspect_ratio": 1.0,
        "multipart_deep_tiled_forbidden": True,
    }:
        raise GeometryPassContractError("geometry_policy_exr_invalid", str(policy["exr"]))
    if policy["depth"] != {
        "encoding": "float32_exr",
        "channel": "Y",
        "quantity": "camera_view_axis_z",
        "unit": "meter",
        "positive_direction": "forward",
        "nonlinear_device_depth_forbidden": True,
        "background_sentinel": "positive_infinity",
        "train_eligible": False,
    }:
        raise GeometryPassContractError("geometry_policy_depth_invalid", str(policy["depth"]))
    if policy["normals"] != {
        "encoding": "float32_rgb_exr",
        "file_channels": {"R": "x", "G": "y", "B": "z"},
        "coordinate_space": "camera",
        "handedness": "right_handed",
        "axes": {"x": "right", "y": "down", "z": "forward"},
        "vector_kind": "geometric_surface_normal_after_deformation_subdivision",
        "unit_length_tolerance": 0.00001,
        "background_sentinel": [0.0, 0.0, 0.0],
        "train_eligible": False,
    }:
        raise GeometryPassContractError("geometry_policy_normals_invalid", str(policy["normals"]))
    if policy["coordinates"] != {
        "matrix_layout": "row_major",
        "vector_convention": "column_vector",
        "image_origin": "top_left",
        "pixel_center": "half_integer",
        "ndc_x_range": [-1.0, 1.0],
        "ndc_y_range": [-1.0, 1.0],
        "ndc_z_range": [0.0, 1.0],
        "matrix_inverse_tolerance": 0.000001,
        "rotation_orthonormal_tolerance": 0.000001,
        "rotation_determinant": 1.0,
        "perspective_last_row": [0.0, 0.0, 1.0, 0.0],
        "orthographic_last_row": [0.0, 0.0, 0.0, 1.0],
    }:
        raise GeometryPassContractError(
            "geometry_policy_coordinates_invalid", str(policy["coordinates"])
        )
    if policy["visibility"] != {
        "authority": "coverage_alpha",
        "minimum_nonzero_u16": 257,
        "finite_depth_and_unit_normal_required_at_visible_pixels": True,
        "exact_sentinels_required_at_background_pixels": True,
    }:
        raise GeometryPassContractError(
            "geometry_policy_visibility_invalid", str(policy["visibility"])
        )
    if policy["freeze"] != {
        "exact_scene_state_before_sidecar_after_restore_terminal": True,
        "exact_plan_contract_coordinate_sidecars": True,
        "exact_coverage_alpha_authority_hash": True,
        "repeated_depth_and_normal_hashes_required": True,
    }:
        raise GeometryPassContractError("geometry_policy_freeze_invalid", str(policy["freeze"]))
    if policy["forbidden_effects"] != [
        "jpeg",
        "palette_quantization",
        "color_management",
        "tone_mapping",
        "denoising",
        "bloom",
        "motion_blur",
        "depth_of_field",
        "lossy_resize",
        "nonlinear_depth_encoding",
        "normal_remap_to_0_1",
    ]:
        raise GeometryPassContractError(
            "geometry_policy_effects_invalid", str(policy["forbidden_effects"])
        )


def build_camera_coordinate_sidecar(
    *,
    scene_id: str,
    scene_state_sha256: str,
    camera_id: str,
    projection_type: str,
    near_clip_m: float,
    far_clip_m: float,
    subdivision_level: int,
    resolution: Sequence[int],
    crop: Sequence[int],
    world_to_camera: Sequence[float],
    camera_to_world: Sequence[float],
    projection_matrix: Sequence[float],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal final camera readback and the exact geometry coordinate convention."""

    validate_geometry_pass_policy(policy)
    content = {
        "scene_id": scene_id,
        "scene_state_sha256": scene_state_sha256,
        "camera_id": camera_id,
        "projection_type": projection_type,
        "near_clip_m": near_clip_m,
        "far_clip_m": far_clip_m,
        "subdivision_level": subdivision_level,
        "resolution": list(resolution),
        "crop": list(crop),
        "world_to_camera": list(world_to_camera),
        "camera_to_world": list(camera_to_world),
        "projection_matrix": list(projection_matrix),
        "coordinate_convention": {
            **policy["coordinates"],
            "depth_quantity": policy["depth"]["quantity"],
            "depth_unit": policy["depth"]["unit"],
            "depth_positive_direction": policy["depth"]["positive_direction"],
            "normal_coordinate_space": policy["normals"]["coordinate_space"],
            "normal_handedness": policy["normals"]["handedness"],
            "normal_axes": policy["normals"]["axes"],
        },
    }
    _validate_coordinate_content(content, policy)
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "sidecar_id": f"dgc_{digest[:24]}",
        "sidecar_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_geometry_coordinates")
    return document


def build_geometry_pass_contract(
    pass_plan: Mapping[str, Any],
    coordinate_sidecar: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind depth and normals to an immutable pass plan and final camera readback."""

    validate_geometry_pass_policy(policy)
    require_valid_document(pass_plan, "daz_render_pass_plan")
    _verify_hashed_document(pass_plan, "plan_id", "plan_sha256", "dcrp")
    require_valid_document(coordinate_sidecar, "daz_geometry_coordinates")
    _verify_hashed_document(coordinate_sidecar, "sidecar_id", "sidecar_sha256", "dgc")
    _validate_coordinate_content(coordinate_sidecar, policy)
    if (
        pass_plan["profile"] not in policy["eligible_profiles"]
        or pass_plan["scene_id"] != coordinate_sidecar["scene_id"]
        or pass_plan["scene_state_sha256"] != coordinate_sidecar["scene_state_sha256"]
    ):
        raise GeometryPassContractError("geometry_lineage_invalid", pass_plan["plan_id"])
    outputs = {row["role"]: row for row in pass_plan["outputs"]}
    if (
        "depth" not in outputs
        or outputs["depth"]["encoding"] != "float32_exr"
        or "normals" not in outputs
        or outputs["normals"]["encoding"] != "float_exr_camera_space"
    ):
        raise GeometryPassContractError("geometry_outputs_missing", pass_plan["profile"])
    if (
        outputs["depth"]["resolution"] != outputs["normals"]["resolution"]
        or outputs["depth"]["crop"] != outputs["normals"]["crop"]
    ):
        raise GeometryPassContractError("geometry_output_alignment_invalid", pass_plan["plan_id"])
    if (
        coordinate_sidecar["resolution"] != outputs["depth"]["resolution"]
        or coordinate_sidecar["crop"] != outputs["depth"]["crop"]
    ):
        raise GeometryPassContractError(
            "geometry_coordinate_raster_alignment_invalid", coordinate_sidecar["camera_id"]
        )
    content = {
        "scene_id": pass_plan["scene_id"],
        "scene_state_sha256": pass_plan["scene_state_sha256"],
        "plan_id": pass_plan["plan_id"],
        "plan_sha256": pass_plan["plan_sha256"],
        "coordinate_sidecar_id": coordinate_sidecar["sidecar_id"],
        "coordinate_sidecar_sha256": coordinate_sidecar["sidecar_sha256"],
        "policy_sha256": _canonical_sha(policy),
        "policy_version": policy["policy_version"],
        "profile": pass_plan["profile"],
        "near_clip_m": coordinate_sidecar["near_clip_m"],
        "far_clip_m": coordinate_sidecar["far_clip_m"],
        "subdivision_level": coordinate_sidecar["subdivision_level"],
        "coordinate_convention": coordinate_sidecar["coordinate_convention"],
        "world_to_camera": coordinate_sidecar["world_to_camera"],
        "camera_to_world": coordinate_sidecar["camera_to_world"],
        "projection_matrix": coordinate_sidecar["projection_matrix"],
        "visibility_minimum_u16": policy["visibility"]["minimum_nonzero_u16"],
        "outputs": {
            "depth": {
                "role": "depth",
                "encoding": policy["depth"]["encoding"],
                "resolution": outputs["depth"]["resolution"],
                "crop": outputs["depth"]["crop"],
                "channels": [policy["depth"]["channel"]],
                "unit": policy["depth"]["unit"],
                "background_sentinel": policy["depth"]["background_sentinel"],
                "compression": policy["exr"]["compression"],
                "train_eligible": False,
            },
            "normals": {
                "role": "normals",
                "encoding": policy["normals"]["encoding"],
                "resolution": outputs["normals"]["resolution"],
                "crop": outputs["normals"]["crop"],
                "channels": ["R", "G", "B"],
                "channel_semantics": policy["normals"]["file_channels"],
                "background_sentinel": policy["normals"]["background_sentinel"],
                "compression": policy["exr"]["compression"],
                "train_eligible": False,
            },
        },
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "contract_id": f"dgpc_{digest[:24]}",
        "contract_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_geometry_pass_contract")
    return document


def decode_float32_exr(
    path: Path,
    *,
    role: str,
    expected_resolution: Sequence[int],
    policy: Mapping[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Decode a real, scanline, ZIP-compressed float32 EXR with exact channels."""

    validate_geometry_pass_policy(policy)
    payload = Path(path).read_bytes()
    header = _parse_exr_header(payload)
    expected_channels = ["Y"] if role == "depth" else ["B", "G", "R"]
    if role not in {"depth", "normals"}:
        raise GeometryPassContractError("geometry_exr_role_invalid", role)
    if (
        header["version"] != policy["exr"]["version"]
        or header["flags"] != 0
        or header["compression_code"] != policy["exr"]["compression_code"]
        or header["data_window_origin"] != policy["exr"]["data_window_origin"]
        or header["display_window_origin"] != header["data_window_origin"]
        or header["display_resolution"] != header["resolution"]
        or header["line_order_code"] != policy["exr"]["line_order_code"]
        or header["pixel_aspect_ratio"] != policy["exr"]["pixel_aspect_ratio"]
        or header["resolution"] != list(expected_resolution)
        or [row["name"] for row in header["channels"]] != expected_channels
        or any(
            row["pixel_type_code"] != policy["exr"]["pixel_type_code"]
            or [row["x_sampling"], row["y_sampling"]] != policy["exr"]["sampling"]
            for row in header["channels"]
        )
    ):
        raise GeometryPassContractError("geometry_exr_header_invalid", json.dumps(header))
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - environment gate
        raise GeometryPassContractError("geometry_exr_decoder_unavailable", str(exc)) from exc
    decoded = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if decoded is None or decoded.dtype != np.float32:
        raise GeometryPassContractError("geometry_exr_decode_invalid", str(path))
    if role == "depth":
        if decoded.ndim != 2:
            raise GeometryPassContractError("geometry_depth_channels_invalid", str(decoded.shape))
        result = decoded
    else:
        if decoded.ndim != 3 or decoded.shape[2] != 3:
            raise GeometryPassContractError("geometry_normal_channels_invalid", str(decoded.shape))
        result = decoded[..., ::-1].copy()
    return result, {
        **header,
        "format": "OPENEXR",
        "dtype": "float32",
        "bytes": len(payload),
    }


def evaluate_geometry_passes(
    contract: Mapping[str, Any],
    coordinate_sidecar: Mapping[str, Any],
    execution: Mapping[str, Any],
    *,
    depth_path: Path,
    normals_path: Path,
    coverage_alpha_path: Path,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate EXR structure, coordinates, visibility, finite values, norms, and replay."""

    validate_geometry_pass_policy(policy)
    require_valid_document(contract, "daz_geometry_pass_contract")
    _verify_hashed_document(contract, "contract_id", "contract_sha256", "dgpc")
    require_valid_document(coordinate_sidecar, "daz_geometry_coordinates")
    _verify_hashed_document(coordinate_sidecar, "sidecar_id", "sidecar_sha256", "dgc")
    _validate_coordinate_content(coordinate_sidecar, policy)
    _validate_execution(execution)
    if (
        coordinate_sidecar["sidecar_id"] != contract["coordinate_sidecar_id"]
        or coordinate_sidecar["sidecar_sha256"] != contract["coordinate_sidecar_sha256"]
        or any(
            contract[field] != coordinate_sidecar[field]
            for field in (
                "near_clip_m",
                "far_clip_m",
                "subdivision_level",
                "coordinate_convention",
                "world_to_camera",
                "camera_to_world",
                "projection_matrix",
            )
        )
        or any(
            execution[field] != contract[field]
            for field in ("scene_id", "contract_id", "contract_sha256", "plan_id", "plan_sha256")
        )
    ):
        raise GeometryPassContractError(
            "geometry_execution_lineage_invalid", execution["contract_id"]
        )
    resolution = contract["outputs"]["depth"]["resolution"]
    depth, depth_codec = decode_float32_exr(
        depth_path, role="depth", expected_resolution=resolution, policy=policy
    )
    normals, normals_codec = decode_float32_exr(
        normals_path, role="normals", expected_resolution=resolution, policy=policy
    )
    alpha, alpha_codec = decode_u16_png_exact(coverage_alpha_path)
    payloads = {
        "depth": Path(depth_path).read_bytes(),
        "normals": Path(normals_path).read_bytes(),
        "coverage_alpha": Path(coverage_alpha_path).read_bytes(),
    }
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in payloads.items()}
    findings: list[dict[str, str]] = []
    state = contract["scene_state_sha256"]
    for field in (
        "scene_state_before_sha256",
        "sidecar_scene_state_sha256",
        "scene_state_after_sha256",
        "annotation_restore_scene_state_sha256",
        "terminal_scene_state_sha256",
    ):
        if execution[field] != state:
            _finding(findings, "GEOMETRY_SCENE_STATE_MUTATION", f"/{field}", execution[field])
    for field, expected, code in (
        ("sidecar_plan_sha256", contract["plan_sha256"], "GEOMETRY_SIDECAR_PLAN_MISMATCH"),
        (
            "sidecar_contract_sha256",
            contract["contract_sha256"],
            "GEOMETRY_SIDECAR_CONTRACT_MISMATCH",
        ),
        (
            "sidecar_coordinate_sha256",
            contract["coordinate_sidecar_sha256"],
            "GEOMETRY_SIDECAR_COORDINATE_MISMATCH",
        ),
        (
            "coverage_alpha_file_sha256",
            hashes["coverage_alpha"],
            "GEOMETRY_ALPHA_AUTHORITY_HASH_MISMATCH",
        ),
        (
            "repeated_depth_file_sha256",
            hashes["depth"],
            "GEOMETRY_DEPTH_REPLAY_MISMATCH",
        ),
        (
            "repeated_normals_file_sha256",
            hashes["normals"],
            "GEOMETRY_NORMAL_REPLAY_MISMATCH",
        ),
    ):
        if execution[field] != expected:
            _finding(findings, code, f"/{field}", execution[field])
    for role in ("depth", "normals"):
        output = execution["outputs"][role]
        expected_output = contract["outputs"][role]
        for field in ("role", "encoding", "resolution", "crop", "compression"):
            if output[field] != expected_output[field]:
                _finding(
                    findings,
                    "GEOMETRY_OUTPUT_CONTRACT_MISMATCH",
                    f"/outputs/{role}/{field}",
                    str(output[field]),
                )
        forbidden = sorted(set(output["effects"]) & set(policy["forbidden_effects"]))
        if forbidden:
            _finding(
                findings,
                "GEOMETRY_EFFECT_FORBIDDEN",
                f"/outputs/{role}/effects",
                ",".join(forbidden),
            )
        if output["file_sha256"] != hashes[role]:
            _finding(
                findings,
                "GEOMETRY_FILE_HASH_MISMATCH",
                f"/outputs/{role}/file_sha256",
                output["file_sha256"],
            )
        if output["bytes"] != len(payloads[role]) or not payloads[role]:
            _finding(
                findings,
                "GEOMETRY_BYTE_COUNT_MISMATCH",
                f"/outputs/{role}/bytes",
                str(output["bytes"]),
            )
        if output["completed"] is not True or output["interrupted"] is not False:
            _finding(
                findings,
                "GEOMETRY_OUTPUT_INCOMPLETE",
                f"/outputs/{role}/completed",
                str(output),
            )
    if depth.shape != alpha.shape or normals.shape[:2] != alpha.shape:
        _finding(
            findings,
            "GEOMETRY_RESOLUTION_MISMATCH",
            "/rasters",
            str((depth.shape, normals.shape, alpha.shape)),
        )
        metrics = _empty_metrics()
        statistics = _empty_statistics()
    else:
        metrics, statistics = _geometry_metrics(depth, normals, alpha, contract, policy)
        for key, code in (
            ("visible_depth_nonfinite_pixels", "GEOMETRY_VISIBLE_DEPTH_NONFINITE"),
            ("visible_depth_clip_pixels", "GEOMETRY_VISIBLE_DEPTH_OUTSIDE_CLIP"),
            ("background_depth_not_positive_inf_pixels", "GEOMETRY_DEPTH_SENTINEL_INVALID"),
            ("visible_normal_nonfinite_pixels", "GEOMETRY_VISIBLE_NORMAL_NONFINITE"),
            ("visible_normal_nonunit_pixels", "GEOMETRY_VISIBLE_NORMAL_NONUNIT"),
            ("background_normal_nonzero_pixels", "GEOMETRY_NORMAL_SENTINEL_INVALID"),
        ):
            if metrics[key]:
                _finding(findings, code, f"/metrics/{key}", str(metrics[key]))
    findings.sort(key=lambda row: (row["code"], row["path"], row["detail"]))
    content = {
        "scene_id": contract["scene_id"],
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "plan_id": contract["plan_id"],
        "plan_sha256": contract["plan_sha256"],
        "scene_state_sha256": contract["scene_state_sha256"],
        "coordinate_sidecar_id": contract["coordinate_sidecar_id"],
        "coordinate_sidecar_sha256": contract["coordinate_sidecar_sha256"],
        "execution_sha256": _canonical_sha(execution),
        "file_hashes": hashes,
        "depth_codec": depth_codec,
        "normals_codec": normals_codec,
        "alpha_codec": alpha_codec,
        "metrics": metrics,
        "statistics": statistics,
        "findings": findings,
        "summary": {
            "passed": not findings,
            "finding_count": len(findings),
            "failure_codes": sorted({row["code"] for row in findings}),
            "scene_state_unchanged": not any("MUTATION" in row["code"] for row in findings),
            "finite_and_convention_exact": not any(
                token in row["code"]
                for row in findings
                for token in ("NONFINITE", "NONUNIT", "SENTINEL", "CLIP", "COORDINATE")
            ),
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dgpr_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_geometry_pass_report")
    return report


def transform_world_to_camera(
    points_xyz: Sequence[Sequence[float]], world_to_camera: Sequence[float]
) -> np.ndarray:
    """Transform finite world points using the declared row-major/column-vector convention."""

    points = np.asarray(points_xyz, dtype=np.float64)
    matrix = np.asarray(world_to_camera, dtype=np.float64).reshape(4, 4)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise GeometryPassContractError("geometry_points_invalid", str(points.shape))
    homogeneous = np.concatenate([points, np.ones((len(points), 1))], axis=1)
    transformed = (matrix @ homogeneous.T).T
    if not np.allclose(transformed[:, 3], 1.0, atol=1e-9, rtol=0):
        raise GeometryPassContractError(
            "geometry_camera_homogeneous_invalid", str(transformed[:, 3])
        )
    return transformed[:, :3]


def project_camera_points(
    points_xyz: Sequence[Sequence[float]], projection_matrix: Sequence[float]
) -> np.ndarray:
    """Project camera points to right-handed NDC using a frozen 4x4 projection matrix."""

    points = np.asarray(points_xyz, dtype=np.float64)
    matrix = np.asarray(projection_matrix, dtype=np.float64).reshape(4, 4)
    if (
        points.ndim != 2
        or points.shape[1] != 3
        or not np.isfinite(points).all()
        or np.any(points[:, 2] <= 0)
    ):
        raise GeometryPassContractError("geometry_projection_points_invalid", str(points))
    homogeneous = np.concatenate([points, np.ones((len(points), 1))], axis=1)
    clip = (matrix @ homogeneous.T).T
    if np.any(np.abs(clip[:, 3]) <= 1e-12):
        raise GeometryPassContractError("geometry_projection_w_invalid", str(clip[:, 3]))
    return clip[:, :3] / clip[:, 3, None]


def publish_geometry_document(document: Mapping[str, Any], output_root: Path) -> tuple[Path, bool]:
    if "report_id" in document:
        schema, name = "daz_geometry_pass_report", document["report_id"]
    elif "contract_id" in document:
        schema, name = "daz_geometry_pass_contract", document["contract_id"]
    elif "sidecar_id" in document:
        schema, name = "daz_geometry_coordinates", document["sidecar_id"]
    else:
        raise GeometryPassContractError("geometry_publication_document_unknown", str(document))
    require_valid_document(document, schema)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{name}.json"
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise GeometryPassContractError("geometry_publication_conflict", str(target))
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


def _validate_coordinate_content(document: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    if (
        not isinstance(document.get("scene_id"), str)
        or not document["scene_id"]
        or not _sha256(document.get("scene_state_sha256"))
        or not isinstance(document.get("camera_id"), str)
        or not document["camera_id"]
        or document.get("projection_type") not in {"perspective", "orthographic"}
        or not _finite_positive(document.get("near_clip_m"))
        or not _finite_positive(document.get("far_clip_m"))
        or document["far_clip_m"] <= document["near_clip_m"]
        or isinstance(document.get("subdivision_level"), bool)
        or not isinstance(document.get("subdivision_level"), int)
        or not 0 <= document["subdivision_level"] <= 8
        or not _valid_resolution(document.get("resolution"))
        or not _valid_crop(document.get("crop"), document.get("resolution"))
    ):
        raise GeometryPassContractError("geometry_coordinate_identity_invalid", str(document))
    expected_convention = {
        **policy["coordinates"],
        "depth_quantity": policy["depth"]["quantity"],
        "depth_unit": policy["depth"]["unit"],
        "depth_positive_direction": policy["depth"]["positive_direction"],
        "normal_coordinate_space": policy["normals"]["coordinate_space"],
        "normal_handedness": policy["normals"]["handedness"],
        "normal_axes": policy["normals"]["axes"],
    }
    if document.get("coordinate_convention") != expected_convention:
        raise GeometryPassContractError(
            "geometry_coordinate_convention_invalid", str(document.get("coordinate_convention"))
        )
    matrices = {}
    for field in ("world_to_camera", "camera_to_world", "projection_matrix"):
        value = document.get(field)
        if (
            not isinstance(value, list)
            or len(value) != 16
            or any(
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(float(item))
                for item in value
            )
        ):
            raise GeometryPassContractError("geometry_coordinate_matrix_invalid", field)
        matrices[field] = np.asarray(value, dtype=np.float64).reshape(4, 4)
    tolerance = policy["coordinates"]["matrix_inverse_tolerance"]
    affine = np.asarray([0.0, 0.0, 0.0, 1.0])
    if (
        not np.allclose(matrices["world_to_camera"][3], affine, atol=tolerance, rtol=0)
        or not np.allclose(matrices["camera_to_world"][3], affine, atol=tolerance, rtol=0)
        or not np.allclose(
            matrices["world_to_camera"] @ matrices["camera_to_world"],
            np.eye(4),
            atol=tolerance,
            rtol=0,
        )
        or not np.allclose(
            matrices["camera_to_world"] @ matrices["world_to_camera"],
            np.eye(4),
            atol=tolerance,
            rtol=0,
        )
    ):
        raise GeometryPassContractError(
            "geometry_coordinate_inverse_invalid", document["camera_id"]
        )
    rotation = matrices["world_to_camera"][:3, :3]
    rotation_tolerance = policy["coordinates"]["rotation_orthonormal_tolerance"]
    if not np.allclose(
        rotation @ rotation.T, np.eye(3), atol=rotation_tolerance, rtol=0
    ) or not math.isclose(
        float(np.linalg.det(rotation)),
        policy["coordinates"]["rotation_determinant"],
        abs_tol=rotation_tolerance,
        rel_tol=0,
    ):
        raise GeometryPassContractError(
            "geometry_coordinate_handedness_invalid", document["camera_id"]
        )
    expected_last = policy["coordinates"][
        (
            "perspective_last_row"
            if document["projection_type"] == "perspective"
            else "orthographic_last_row"
        )
    ]
    if not np.allclose(matrices["projection_matrix"][3], expected_last, atol=tolerance, rtol=0):
        raise GeometryPassContractError(
            "geometry_projection_convention_invalid", document["camera_id"]
        )
    projection = matrices["projection_matrix"]
    if document["projection_type"] == "perspective":
        structure = np.asarray(
            [
                [projection[0, 0], 0.0, projection[0, 2], 0.0],
                [0.0, projection[1, 1], projection[1, 2], 0.0],
                [0.0, 0.0, projection[2, 2], projection[2, 3]],
                [0.0, 0.0, 1.0, 0.0],
            ]
        )
        principal_x, principal_y = projection[0, 2], projection[1, 2]
    else:
        structure = np.asarray(
            [
                [projection[0, 0], 0.0, 0.0, projection[0, 3]],
                [0.0, projection[1, 1], 0.0, projection[1, 3]],
                [0.0, 0.0, projection[2, 2], projection[2, 3]],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        principal_x, principal_y = projection[0, 3], projection[1, 3]
    if (
        projection[0, 0] <= 0
        or projection[1, 1] <= 0
        or not -1 <= principal_x <= 1
        or not -1 <= principal_y <= 1
        or not np.allclose(projection, structure, atol=tolerance, rtol=0)
    ):
        raise GeometryPassContractError(
            "geometry_projection_structure_invalid", document["camera_id"]
        )
    depths = np.asarray([[0.0, 0.0, document["near_clip_m"]], [0.0, 0.0, document["far_clip_m"]]])
    projected = project_camera_points(depths, document["projection_matrix"])
    if not np.allclose(projected[:, 2], [0.0, 1.0], atol=tolerance, rtol=0):
        raise GeometryPassContractError("geometry_projection_clip_invalid", str(projected[:, 2]))


def _parse_exr_header(payload: bytes) -> dict[str, Any]:
    if len(payload) < 16 or payload[:4].hex() != "762f3101":
        raise GeometryPassContractError("geometry_exr_magic_invalid", payload[:4].hex())
    version_field = struct.unpack_from("<I", payload, 4)[0]
    position = 8
    attributes: dict[str, tuple[str, bytes]] = {}
    while True:
        if position >= len(payload):
            raise GeometryPassContractError("geometry_exr_header_truncated", str(position))
        if payload[position] == 0:
            position += 1
            break
        name, position = _read_c_string(payload, position)
        type_name, position = _read_c_string(payload, position)
        if position + 4 > len(payload):
            raise GeometryPassContractError("geometry_exr_header_truncated", name)
        size = struct.unpack_from("<I", payload, position)[0]
        position += 4
        if size > 1_048_576 or position + size > len(payload) or name in attributes:
            raise GeometryPassContractError("geometry_exr_attribute_invalid", name)
        attributes[name] = (type_name, payload[position : position + size])
        position += size
        if len(attributes) > 128:
            raise GeometryPassContractError("geometry_exr_attribute_overflow", str(len(attributes)))
    required = {"channels", "compression", "dataWindow", "displayWindow", "lineOrder"}
    if not required.issubset(attributes):
        raise GeometryPassContractError("geometry_exr_attributes_missing", str(sorted(attributes)))
    channels = _parse_exr_channels(attributes["channels"])
    compression = attributes["compression"]
    data_window = attributes["dataWindow"]
    display_window = attributes["displayWindow"]
    line_order = attributes["lineOrder"]
    pixel_aspect = attributes.get("pixelAspectRatio")
    if compression[0] != "compression" or len(compression[1]) != 1:
        raise GeometryPassContractError("geometry_exr_compression_invalid", str(compression))
    if data_window[0] != "box2i" or len(data_window[1]) != 16:
        raise GeometryPassContractError("geometry_exr_data_window_invalid", str(data_window[0]))
    if display_window[0] != "box2i" or len(display_window[1]) != 16:
        raise GeometryPassContractError(
            "geometry_exr_display_window_invalid", str(display_window[0])
        )
    if line_order[0] != "lineOrder" or len(line_order[1]) != 1:
        raise GeometryPassContractError("geometry_exr_line_order_invalid", str(line_order[0]))
    if pixel_aspect is None or pixel_aspect[0] != "float" or len(pixel_aspect[1]) != 4:
        raise GeometryPassContractError("geometry_exr_pixel_aspect_invalid", str(pixel_aspect))
    minimum_x, minimum_y, maximum_x, maximum_y = struct.unpack("<iiii", data_window[1])
    display_minimum_x, display_minimum_y, display_maximum_x, display_maximum_y = struct.unpack(
        "<iiii", display_window[1]
    )
    return {
        "version": version_field & 0xFF,
        "flags": version_field & 0xFFFFFF00,
        "compression_code": compression[1][0],
        "data_window_origin": [minimum_x, minimum_y],
        "resolution": [maximum_x - minimum_x + 1, maximum_y - minimum_y + 1],
        "display_window_origin": [display_minimum_x, display_minimum_y],
        "display_resolution": [
            display_maximum_x - display_minimum_x + 1,
            display_maximum_y - display_minimum_y + 1,
        ],
        "line_order_code": line_order[1][0],
        "pixel_aspect_ratio": struct.unpack("<f", pixel_aspect[1])[0],
        "channels": channels,
        "header_attribute_names": sorted(attributes),
    }


def _parse_exr_channels(attribute: tuple[str, bytes]) -> list[dict[str, Any]]:
    type_name, payload = attribute
    if type_name != "chlist":
        raise GeometryPassContractError("geometry_exr_channels_type_invalid", type_name)
    channels = []
    position = 0
    while position < len(payload) and payload[position] != 0:
        name, position = _read_c_string(payload, position)
        if position + 16 > len(payload):
            raise GeometryPassContractError("geometry_exr_channels_truncated", name)
        (pixel_type,) = struct.unpack_from("<i", payload, position)
        p_linear = payload[position + 4]
        x_sampling, y_sampling = struct.unpack_from("<ii", payload, position + 8)
        position += 16
        channels.append(
            {
                "name": name,
                "pixel_type_code": pixel_type,
                "p_linear": p_linear,
                "x_sampling": x_sampling,
                "y_sampling": y_sampling,
            }
        )
    if position != len(payload) - 1 or not channels:
        raise GeometryPassContractError("geometry_exr_channels_terminator_invalid", str(position))
    return channels


def _read_c_string(payload: bytes, position: int) -> tuple[str, int]:
    try:
        end = payload.index(0, position, min(len(payload), position + 256))
        value = payload[position:end].decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise GeometryPassContractError("geometry_exr_string_invalid", str(position)) from exc
    if not value:
        raise GeometryPassContractError("geometry_exr_string_empty", str(position))
    return value, end + 1


def _geometry_metrics(
    depth: np.ndarray,
    normals: np.ndarray,
    alpha: np.ndarray,
    contract: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> tuple[dict[str, int], dict[str, Any]]:
    visible = alpha >= contract["visibility_minimum_u16"]
    background = ~visible
    normal_finite = np.isfinite(normals).all(axis=2)
    normal_length = np.linalg.norm(normals, axis=2)
    visible_depth = depth[visible]
    visible_norms = normal_length[visible]
    tolerance = policy["normals"]["unit_length_tolerance"]
    metrics = {
        "visible_pixels": int(np.count_nonzero(visible)),
        "background_pixels": int(np.count_nonzero(background)),
        "visible_depth_nonfinite_pixels": int(np.count_nonzero(visible & ~np.isfinite(depth))),
        "visible_depth_clip_pixels": int(
            np.count_nonzero(
                visible & ((depth < contract["near_clip_m"]) | (depth > contract["far_clip_m"]))
            )
        ),
        "background_depth_not_positive_inf_pixels": int(
            np.count_nonzero(background & ~np.isposinf(depth))
        ),
        "visible_normal_nonfinite_pixels": int(np.count_nonzero(visible & ~normal_finite)),
        "visible_normal_nonunit_pixels": int(
            np.count_nonzero(visible & (np.abs(normal_length - 1.0) > tolerance))
        ),
        "background_normal_nonzero_pixels": int(
            np.count_nonzero(background & np.any(normals != 0.0, axis=2))
        ),
    }
    finite_depth = visible_depth[np.isfinite(visible_depth)]
    finite_norms = visible_norms[np.isfinite(visible_norms)]
    statistics = {
        "depth": {
            "finite_count": int(finite_depth.size),
            "positive_infinity_count": int(np.count_nonzero(np.isposinf(depth))),
            "negative_infinity_count": int(np.count_nonzero(np.isneginf(depth))),
            "nan_count": int(np.count_nonzero(np.isnan(depth))),
            "minimum_finite_m": float(finite_depth.min()) if finite_depth.size else None,
            "maximum_finite_m": float(finite_depth.max()) if finite_depth.size else None,
            "mean_finite_m": float(finite_depth.mean()) if finite_depth.size else None,
        },
        "normals": {
            "finite_vector_count": int(np.count_nonzero(normal_finite)),
            "nonfinite_vector_count": int(np.count_nonzero(~normal_finite)),
            "minimum_visible_length": float(finite_norms.min()) if finite_norms.size else None,
            "maximum_visible_length": float(finite_norms.max()) if finite_norms.size else None,
            "mean_visible_length": float(finite_norms.mean()) if finite_norms.size else None,
        },
    }
    return metrics, statistics


def _empty_metrics() -> dict[str, int]:
    return {
        "visible_pixels": -1,
        "background_pixels": -1,
        "visible_depth_nonfinite_pixels": -1,
        "visible_depth_clip_pixels": -1,
        "background_depth_not_positive_inf_pixels": -1,
        "visible_normal_nonfinite_pixels": -1,
        "visible_normal_nonunit_pixels": -1,
        "background_normal_nonzero_pixels": -1,
    }


def _empty_statistics() -> dict[str, Any]:
    return {
        "depth": {
            "finite_count": 0,
            "positive_infinity_count": 0,
            "negative_infinity_count": 0,
            "nan_count": 0,
            "minimum_finite_m": None,
            "maximum_finite_m": None,
            "mean_finite_m": None,
        },
        "normals": {
            "finite_vector_count": 0,
            "nonfinite_vector_count": 0,
            "minimum_visible_length": None,
            "maximum_visible_length": None,
            "mean_visible_length": None,
        },
    }


def _validate_execution(execution: Any) -> None:
    expected = {
        "schema_version",
        "scene_id",
        "contract_id",
        "contract_sha256",
        "plan_id",
        "plan_sha256",
        "scene_state_before_sha256",
        "sidecar_scene_state_sha256",
        "scene_state_after_sha256",
        "annotation_restore_scene_state_sha256",
        "terminal_scene_state_sha256",
        "sidecar_plan_sha256",
        "sidecar_contract_sha256",
        "sidecar_coordinate_sha256",
        "coverage_alpha_file_sha256",
        "repeated_depth_file_sha256",
        "repeated_normals_file_sha256",
        "outputs",
    }
    if not isinstance(execution, Mapping) or set(execution) != expected:
        raise GeometryPassContractError("geometry_execution_fields_invalid", str(execution))
    for field, value in execution.items():
        if field.endswith("_sha256") and not _sha256(value):
            raise GeometryPassContractError("geometry_execution_hash_invalid", field)
    if execution["schema_version"] != "1.0.0" or set(execution["outputs"]) != {
        "depth",
        "normals",
    }:
        raise GeometryPassContractError(
            "geometry_execution_outputs_invalid", str(execution["outputs"])
        )
    fields = {
        "role",
        "encoding",
        "resolution",
        "crop",
        "compression",
        "effects",
        "file_sha256",
        "bytes",
        "completed",
        "interrupted",
    }
    for role, output in execution["outputs"].items():
        if (
            not isinstance(output, Mapping)
            or set(output) != fields
            or output["role"] != role
            or not isinstance(output["effects"], list)
        ):
            raise GeometryPassContractError("geometry_execution_output_invalid", role)


def _verify_hashed_document(
    document: Mapping[str, Any], id_field: str, hash_field: str, prefix: str
) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, hash_field}
    }
    digest = _canonical_sha(content)
    if document.get(hash_field) != digest or document.get(id_field) != f"{prefix}_{digest[:24]}":
        raise GeometryPassContractError(
            "geometry_document_hash_invalid", str(document.get(id_field))
        )


def _canonical_sha(document: Mapping[str, Any]) -> str:
    try:
        payload = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise GeometryPassContractError("geometry_document_nonfinite", str(exc)) from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite_positive(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _valid_resolution(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(not isinstance(item, bool) and isinstance(item, int) and item > 0 for item in value)
    )


def _valid_crop(value: Any, resolution: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(
            not isinstance(item, bool) and isinstance(item, int) and item >= 0 for item in value
        )
        and _valid_resolution(resolution)
        and value[2] > value[0]
        and value[3] > value[1]
        and value[2] <= resolution[0]
        and value[3] <= resolution[1]
    )


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _finding(findings: list[dict[str, str]], code: str, path: str, detail: str) -> None:
    findings.append({"code": code, "path": path, "detail": detail})
