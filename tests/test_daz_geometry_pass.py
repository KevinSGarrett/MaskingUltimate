from __future__ import annotations

import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maskfactory.cli import main  # noqa: E402
from maskfactory.daz.render import (  # noqa: E402
    GeometryPassContractError,
    build_camera_coordinate_sidecar,
    build_geometry_pass_contract,
    decode_float32_exr,
    evaluate_geometry_passes,
    load_geometry_pass_policy,
    project_camera_points,
    publish_geometry_document,
    transform_world_to_camera,
    validate_geometry_pass_policy,
)
from test_daz_render_pass_profiles import _plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "geometry_pass.yaml"


def _sha(document: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _compact_plan(profile: str = "training_standard") -> dict:
    _state, _pass_policy, plan = _plan(profile)
    result = deepcopy(plan)
    for output in result["outputs"]:
        output["resolution"] = [64, 48]
        output["crop"] = [0, 0, 64, 48]
    content = {
        key: value
        for key, value in result.items()
        if key not in {"schema_version", "plan_id", "plan_sha256"}
    }
    digest = _sha(content)
    result["plan_id"] = f"dcrp_{digest[:24]}"
    result["plan_sha256"] = digest
    return result


def _perspective(near: float = 0.1, far: float = 100.0) -> list[float]:
    a = far / (far - near)
    b = -(far * near) / (far - near)
    return [
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        a,
        b,
        0.0,
        0.0,
        1.0,
        0.0,
    ]


def _orthographic(near: float = 0.1, far: float = 100.0) -> list[float]:
    a = 1.0 / (far - near)
    b = -near / (far - near)
    return [
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        a,
        b,
        0.0,
        0.0,
        0.0,
        1.0,
    ]


def _sidecar_args(plan: dict, projection_type: str = "perspective") -> dict:
    identity = np.eye(4, dtype=np.float64).reshape(-1).tolist()
    return {
        "scene_id": plan["scene_id"],
        "scene_state_sha256": plan["scene_state_sha256"],
        "camera_id": "camera_fixture",
        "projection_type": projection_type,
        "near_clip_m": 0.1,
        "far_clip_m": 100.0,
        "subdivision_level": 2,
        "resolution": deepcopy(plan["outputs"][0]["resolution"]),
        "crop": deepcopy(plan["outputs"][0]["crop"]),
        "world_to_camera": identity.copy(),
        "camera_to_world": identity.copy(),
        "projection_matrix": (
            _perspective() if projection_type == "perspective" else _orthographic()
        ),
    }


def _contract(profile: str = "training_standard") -> tuple[dict, dict, dict, dict]:
    policy = load_geometry_pass_policy(POLICY_PATH)
    plan = _compact_plan(profile)
    sidecar = build_camera_coordinate_sidecar(**_sidecar_args(plan), policy=policy)
    contract = build_geometry_pass_contract(plan, sidecar, policy=policy)
    return policy, plan, sidecar, contract


def _arrays(resolution: list[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    width, height = resolution
    alpha = np.zeros((height, width), dtype=np.uint16)
    depth = np.full((height, width), np.inf, dtype=np.float32)
    normals = np.zeros((height, width, 3), dtype=np.float32)
    alpha[8:40, 10:54] = 65535
    depth[8:40, 10:54] = np.linspace(1.0, 8.0, 32 * 44, dtype=np.float32).reshape(32, 44)
    normals[8:40, 10:54] = [0.0, 0.0, -1.0]
    alpha[4:7, 4:8] = 257
    depth[4:7, 4:8] = 2.0
    normals[4:7, 4:8] = [0.0, 1.0, 0.0]
    return depth, normals, alpha


def _write_maps(
    root: Path, depth: np.ndarray, normals_xyz: np.ndarray, alpha: np.ndarray
) -> dict[str, Path]:
    import cv2

    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "depth": root / "depth.exr",
        "normals": root / "normals.exr",
        "coverage_alpha": root / "coverage_alpha.png",
    }
    assert cv2.imwrite(str(paths["depth"]), depth)
    assert cv2.imwrite(str(paths["normals"]), normals_xyz[..., ::-1])
    Image.fromarray(alpha).save(paths["coverage_alpha"], format="PNG")
    return paths


def _execution(contract: dict, paths: dict[str, Path]) -> dict:
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    outputs = {}
    for role in ("depth", "normals"):
        outputs[role] = {
            "role": role,
            "encoding": contract["outputs"][role]["encoding"],
            "resolution": deepcopy(contract["outputs"][role]["resolution"]),
            "crop": deepcopy(contract["outputs"][role]["crop"]),
            "compression": "zip_scanline_16",
            "effects": [],
            "file_sha256": hashes[role],
            "bytes": paths[role].stat().st_size,
            "completed": True,
            "interrupted": False,
        }
    return {
        "schema_version": "1.0.0",
        "scene_id": contract["scene_id"],
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "plan_id": contract["plan_id"],
        "plan_sha256": contract["plan_sha256"],
        "scene_state_before_sha256": contract["scene_state_sha256"],
        "sidecar_scene_state_sha256": contract["scene_state_sha256"],
        "scene_state_after_sha256": contract["scene_state_sha256"],
        "annotation_restore_scene_state_sha256": contract["scene_state_sha256"],
        "terminal_scene_state_sha256": contract["scene_state_sha256"],
        "sidecar_plan_sha256": contract["plan_sha256"],
        "sidecar_contract_sha256": contract["contract_sha256"],
        "sidecar_coordinate_sha256": contract["coordinate_sidecar_sha256"],
        "coverage_alpha_file_sha256": hashes["coverage_alpha"],
        "repeated_depth_file_sha256": hashes["depth"],
        "repeated_normals_file_sha256": hashes["normals"],
        "outputs": outputs,
    }


def _fixture(tmp_path: Path):
    policy, _plan_document, sidecar, contract = _contract()
    paths = _write_maps(
        tmp_path,
        *_arrays(contract["outputs"]["depth"]["resolution"]),
    )
    return policy, sidecar, contract, paths, _execution(contract, paths)


def _evaluate(policy, sidecar, contract, paths, execution):
    return evaluate_geometry_passes(
        contract,
        sidecar,
        execution,
        depth_path=paths["depth"],
        normals_path=paths["normals"],
        coverage_alpha_path=paths["coverage_alpha"],
        policy=policy,
    )


def _codes(report: dict) -> set[str]:
    return set(report["summary"]["failure_codes"])


def test_policy_freezes_linear_depth_and_right_handed_camera_normals() -> None:
    policy = load_geometry_pass_policy(POLICY_PATH)
    validate_geometry_pass_policy(policy)
    assert policy["depth"]["quantity"] == "camera_view_axis_z"
    assert policy["depth"]["unit"] == "meter"
    assert policy["normals"]["handedness"] == "right_handed"
    assert policy["normals"]["axes"] == {"x": "right", "y": "down", "z": "forward"}


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p.__setitem__("policy_version", "2.0.0"), "identity"),
        (lambda p: p["eligible_profiles"].append("engineering_minimal"), "profiles"),
        (lambda p: p["exr"].__setitem__("pixel_type", "float16"), "exr"),
        (lambda p: p["depth"].__setitem__("quantity", "device_z"), "depth"),
        (lambda p: p["normals"].__setitem__("handedness", "left_handed"), "normals"),
        (lambda p: p["coordinates"].__setitem__("image_origin", "bottom_left"), "coordinates"),
        (lambda p: p["visibility"].__setitem__("minimum_nonzero_u16", 1), "visibility"),
        (
            lambda p: p["freeze"].__setitem__("repeated_depth_and_normal_hashes_required", False),
            "freeze",
        ),
        (lambda p: p["forbidden_effects"].pop(), "effects"),
    ],
)
def test_closed_policy_drift_fails(mutation, reason: str) -> None:
    policy = load_geometry_pass_policy(POLICY_PATH)
    mutation(policy)
    with pytest.raises(GeometryPassContractError, match=f"geometry_policy_{reason}_invalid"):
        validate_geometry_pass_policy(policy)


@pytest.mark.parametrize("projection_type", ["perspective", "orthographic"])
def test_coordinate_sidecar_maps_near_and_far_to_canonical_ndc(projection_type: str) -> None:
    policy = load_geometry_pass_policy(POLICY_PATH)
    plan = _compact_plan()
    sidecar = build_camera_coordinate_sidecar(**_sidecar_args(plan, projection_type), policy=policy)
    projected = project_camera_points(
        [[0, 0, sidecar["near_clip_m"]], [0, 0, sidecar["far_clip_m"]]],
        sidecar["projection_matrix"],
    )
    assert np.allclose(projected[:, 2], [0.0, 1.0], atol=1e-6)


def test_world_camera_transform_uses_row_major_column_vectors() -> None:
    matrix = np.eye(4)
    matrix[:3, 3] = [-1, -2, 3]
    transformed = transform_world_to_camera([[1, 2, 4]], matrix.reshape(-1).tolist())
    assert transformed.tolist() == [[0.0, 0.0, 7.0]]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda a: a.__setitem__("near_clip_m", 0.0), "identity"),
        (lambda a: a.__setitem__("far_clip_m", 0.05), "identity"),
        (lambda a: a.__setitem__("subdivision_level", 9), "identity"),
        (lambda a: a.__setitem__("world_to_camera", [1.0] * 16), "inverse"),
        (lambda a: a["world_to_camera"].__setitem__(0, -1.0), "inverse"),
        (lambda a: a["projection_matrix"].__setitem__(15, 1.0), "projection_convention"),
        (lambda a: a["projection_matrix"].__setitem__(11, 0.0), "projection_clip"),
        (lambda a: a["projection_matrix"].__setitem__(1, 0.1), "projection_structure"),
    ],
)
def test_invalid_coordinate_readback_fails(mutation, reason: str) -> None:
    policy = load_geometry_pass_policy(POLICY_PATH)
    plan = _compact_plan()
    arguments = _sidecar_args(plan)
    mutation(arguments)
    with pytest.raises(
        GeometryPassContractError,
        match=f"geometry_coordinate_{reason}_invalid|geometry_projection_{reason.removeprefix('projection_')}_invalid",
    ):
        build_camera_coordinate_sidecar(**arguments, policy=policy)


def test_reflection_rotation_fails_right_handed_gate() -> None:
    policy = load_geometry_pass_policy(POLICY_PATH)
    plan = _compact_plan()
    arguments = _sidecar_args(plan)
    reflection = np.diag([-1.0, 1.0, 1.0, 1.0])
    arguments["world_to_camera"] = reflection.reshape(-1).tolist()
    arguments["camera_to_world"] = reflection.reshape(-1).tolist()
    with pytest.raises(GeometryPassContractError, match="geometry_coordinate_handedness_invalid"):
        build_camera_coordinate_sidecar(**arguments, policy=policy)


def test_contract_is_diagnostic_and_binds_coordinate_sidecar() -> None:
    _policy, _plan_document, sidecar, contract = _contract()
    assert contract["coordinate_sidecar_sha256"] == sidecar["sidecar_sha256"]
    assert contract["outputs"]["depth"]["train_eligible"] is False
    assert contract["outputs"]["normals"]["train_eligible"] is False


def test_engineering_profile_is_ineligible() -> None:
    with pytest.raises(GeometryPassContractError, match="geometry_lineage_invalid"):
        _contract("engineering_minimal")


def test_real_float32_exr_headers_and_channel_semantics_decode(tmp_path: Path) -> None:
    policy, _plan_document, _sidecar, contract = _contract()
    depth, normals, alpha = _arrays(contract["outputs"]["depth"]["resolution"])
    paths = _write_maps(tmp_path, depth, normals, alpha)
    decoded_depth, depth_header = decode_float32_exr(
        paths["depth"],
        role="depth",
        expected_resolution=contract["outputs"]["depth"]["resolution"],
        policy=policy,
    )
    decoded_normals, normal_header = decode_float32_exr(
        paths["normals"],
        role="normals",
        expected_resolution=contract["outputs"]["normals"]["resolution"],
        policy=policy,
    )
    assert np.array_equal(decoded_depth, depth)
    assert np.array_equal(decoded_normals, normals)
    assert [row["name"] for row in depth_header["channels"]] == ["Y"]
    assert [row["name"] for row in normal_header["channels"]] == ["B", "G", "R"]


@pytest.mark.parametrize(
    "corruption",
    [
        "magic",
        "flags",
        "half",
        "compression",
        "channels",
        "display_window",
        "line_order",
        "pixel_aspect",
    ],
)
def test_corrupt_or_wrong_exr_header_fails(tmp_path: Path, corruption: str) -> None:
    policy, _plan_document, _sidecar, contract = _contract()
    depth, normals, alpha = _arrays(contract["outputs"]["depth"]["resolution"])
    paths = _write_maps(tmp_path, depth, normals, alpha)
    path = paths["depth"]
    payload = bytearray(path.read_bytes())
    if corruption == "magic":
        payload[0] = 0
    elif corruption == "flags":
        payload[5] = 1
    elif corruption == "half":
        marker = payload.index(b"Y\x00\x02\x00\x00\x00")
        payload[marker + 2] = 1
    elif corruption == "compression":
        marker = payload.index(b"compression\x00compression\x00")
        payload[marker + len(b"compression\x00compression\x00") + 4] = 4
    elif corruption == "display_window":
        marker = payload.index(b"displayWindow\x00box2i\x00")
        start = marker + len(b"displayWindow\x00box2i\x00") + 4
        payload[start + 8 : start + 12] = (100).to_bytes(4, "little", signed=True)
    elif corruption == "line_order":
        marker = payload.index(b"lineOrder\x00lineOrder\x00")
        payload[marker + len(b"lineOrder\x00lineOrder\x00") + 4] = 1
    elif corruption == "pixel_aspect":
        marker = payload.index(b"pixelAspectRatio\x00float\x00")
        start = marker + len(b"pixelAspectRatio\x00float\x00") + 4
        payload[start : start + 4] = np.float32(2.0).tobytes()
    if corruption != "channels":
        path.write_bytes(payload)
    with pytest.raises(GeometryPassContractError, match="geometry_exr_"):
        decode_float32_exr(
            path,
            role="normals" if corruption == "channels" else "depth",
            expected_resolution=contract["outputs"]["depth"]["resolution"],
            policy=policy,
        )


def test_coordinate_sidecar_resolution_and_crop_must_match_plan() -> None:
    policy = load_geometry_pass_policy(POLICY_PATH)
    plan = _compact_plan()
    arguments = _sidecar_args(plan)
    arguments["resolution"] = [32, 32]
    arguments["crop"] = [0, 0, 32, 32]
    sidecar = build_camera_coordinate_sidecar(**arguments, policy=policy)
    with pytest.raises(
        GeometryPassContractError, match="geometry_coordinate_raster_alignment_invalid"
    ):
        build_geometry_pass_contract(plan, sidecar, policy=policy)


def test_resealed_contract_coordinate_drift_rejects_at_evaluation(tmp_path: Path) -> None:
    policy, sidecar, contract, paths, execution = _fixture(tmp_path)
    drifted = deepcopy(contract)
    drifted["near_clip_m"] = 0.2
    content = {
        key: value
        for key, value in drifted.items()
        if key not in {"schema_version", "contract_id", "contract_sha256"}
    }
    digest = _sha(content)
    drifted["contract_id"] = f"dgpc_{digest[:24]}"
    drifted["contract_sha256"] = digest
    execution["contract_id"] = drifted["contract_id"]
    execution["contract_sha256"] = drifted["contract_sha256"]
    with pytest.raises(GeometryPassContractError, match="geometry_execution_lineage_invalid"):
        _evaluate(policy, sidecar, drifted, paths, execution)


def test_valid_analytic_geometry_fixture_passes(tmp_path: Path) -> None:
    policy, sidecar, contract, paths, execution = _fixture(tmp_path)
    report = _evaluate(policy, sidecar, contract, paths, execution)
    assert report["summary"]["passed"] is True
    assert report["statistics"]["depth"]["finite_count"] == report["metrics"]["visible_pixels"]
    assert report["statistics"]["normals"]["mean_visible_length"] == 1.0


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda d, n, a: d.__setitem__((8, 10), np.nan), "GEOMETRY_VISIBLE_DEPTH_NONFINITE"),
        (lambda d, n, a: d.__setitem__((8, 10), 0.01), "GEOMETRY_VISIBLE_DEPTH_OUTSIDE_CLIP"),
        (lambda d, n, a: d.__setitem__((0, 0), 0.0), "GEOMETRY_DEPTH_SENTINEL_INVALID"),
        (
            lambda d, n, a: n.__setitem__((8, 10), [np.nan, 0, 0]),
            "GEOMETRY_VISIBLE_NORMAL_NONFINITE",
        ),
        (
            lambda d, n, a: n.__setitem__((8, 10), [0, 0, 0.5]),
            "GEOMETRY_VISIBLE_NORMAL_NONUNIT",
        ),
        (
            lambda d, n, a: n.__setitem__((0, 0), [1, 0, 0]),
            "GEOMETRY_NORMAL_SENTINEL_INVALID",
        ),
    ],
)
def test_seeded_geometry_defects_are_detected(tmp_path: Path, mutation, code: str) -> None:
    policy, _plan_document, sidecar, contract = _contract()
    depth, normals, alpha = _arrays(contract["outputs"]["depth"]["resolution"])
    mutation(depth, normals, alpha)
    paths = _write_maps(tmp_path, depth, normals, alpha)
    report = _evaluate(policy, sidecar, contract, paths, _execution(contract, paths))
    assert code in _codes(report)


@pytest.mark.parametrize(
    "field",
    [
        "scene_state_before_sha256",
        "sidecar_scene_state_sha256",
        "scene_state_after_sha256",
        "annotation_restore_scene_state_sha256",
        "terminal_scene_state_sha256",
    ],
)
def test_every_state_mutation_is_detected(tmp_path: Path, field: str) -> None:
    policy, sidecar, contract, paths, execution = _fixture(tmp_path)
    execution[field] = "0" * 64
    assert "GEOMETRY_SCENE_STATE_MUTATION" in _codes(
        _evaluate(policy, sidecar, contract, paths, execution)
    )


@pytest.mark.parametrize(
    "effect",
    [
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
    ],
)
def test_every_forbidden_effect_is_detected(tmp_path: Path, effect: str) -> None:
    policy, sidecar, contract, paths, execution = _fixture(tmp_path)
    execution["outputs"]["depth"]["effects"] = [effect]
    assert "GEOMETRY_EFFECT_FORBIDDEN" in _codes(
        _evaluate(policy, sidecar, contract, paths, execution)
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda e: e.__setitem__("sidecar_plan_sha256", "0" * 64),
            "GEOMETRY_SIDECAR_PLAN_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_contract_sha256", "0" * 64),
            "GEOMETRY_SIDECAR_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_coordinate_sha256", "0" * 64),
            "GEOMETRY_SIDECAR_COORDINATE_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("coverage_alpha_file_sha256", "0" * 64),
            "GEOMETRY_ALPHA_AUTHORITY_HASH_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("repeated_depth_file_sha256", "0" * 64),
            "GEOMETRY_DEPTH_REPLAY_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("repeated_normals_file_sha256", "0" * 64),
            "GEOMETRY_NORMAL_REPLAY_MISMATCH",
        ),
        (
            lambda e: e["outputs"]["depth"].__setitem__("encoding", "device_depth"),
            "GEOMETRY_OUTPUT_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e["outputs"]["depth"].__setitem__("file_sha256", "0" * 64),
            "GEOMETRY_FILE_HASH_MISMATCH",
        ),
        (
            lambda e: e["outputs"]["depth"].__setitem__("bytes", 1),
            "GEOMETRY_BYTE_COUNT_MISMATCH",
        ),
        (
            lambda e: e["outputs"]["depth"].__setitem__("completed", False),
            "GEOMETRY_OUTPUT_INCOMPLETE",
        ),
    ],
)
def test_sidecar_authority_output_and_replay_drift(tmp_path: Path, mutation, code: str) -> None:
    policy, sidecar, contract, paths, execution = _fixture(tmp_path)
    mutation(execution)
    assert code in _codes(_evaluate(policy, sidecar, contract, paths, execution))


def test_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    _policy, _plan_document, sidecar, contract = _contract()
    for document in (sidecar, contract):
        target, published = publish_geometry_document(document, tmp_path)
        assert published is True
        assert publish_geometry_document(document, tmp_path) == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(GeometryPassContractError, match="geometry_publication_conflict"):
        publish_geometry_document(contract, tmp_path)


def test_cli_contract_and_validation_are_idempotent(tmp_path: Path) -> None:
    plan = _compact_plan()
    readback = {
        key: value
        for key, value in _sidecar_args(plan).items()
        if key not in {"scene_id", "scene_state_sha256"}
    }
    plan_path = tmp_path / "plan.json"
    readback_path = tmp_path / "camera_readback.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    readback_path.write_text(json.dumps(readback), encoding="utf-8")
    contract_output = tmp_path / "contracts"
    plan_arguments = [
        "daz",
        "recipes",
        "plan-geometry-passes",
        "--pass-plan",
        str(plan_path),
        "--camera-readback",
        str(readback_path),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(contract_output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, plan_arguments)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["data"]["coordinate_publication"]["published"] is True
    assert payload["data"]["contract_publication"]["published"] is True
    replay = runner.invoke(main, plan_arguments)
    assert replay.exit_code == 0, replay.output
    replay_payload = json.loads(replay.output)
    assert replay_payload["data"]["coordinate_publication"]["published"] is False
    assert replay_payload["data"]["contract_publication"]["published"] is False

    contract_path = Path(payload["data"]["contract_publication"]["path"])
    sidecar_path = Path(payload["data"]["coordinate_publication"]["path"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    paths = _write_maps(
        tmp_path / "maps",
        *_arrays(contract["outputs"]["depth"]["resolution"]),
    )
    execution_path = tmp_path / "execution.json"
    execution_path.write_text(json.dumps(_execution(contract, paths)), encoding="utf-8")
    report_output = tmp_path / "reports"
    validate_arguments = [
        "daz",
        "recipes",
        "validate-geometry-passes",
        "--contract",
        str(contract_path),
        "--coordinate-sidecar",
        str(sidecar_path),
        "--execution",
        str(execution_path),
        "--depth-exr",
        str(paths["depth"]),
        "--normals-exr",
        str(paths["normals"]),
        "--coverage-alpha",
        str(paths["coverage_alpha"]),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(report_output),
    ]
    checked = runner.invoke(main, validate_arguments)
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.output)["data"]["summary"]["passed"] is True
    checked_replay = runner.invoke(main, validate_arguments)
    assert checked_replay.exit_code == 0, checked_replay.output
    assert json.loads(checked_replay.output)["data"]["publication"]["published"] is False
