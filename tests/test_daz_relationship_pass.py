from __future__ import annotations

import binascii
import hashlib
import json
import os
import struct
import sys
import zlib
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
    RelationshipPassContractError,
    build_camera_coordinate_sidecar,
    build_geometry_pass_contract,
    build_instance_pass_contract,
    build_relationship_pass_contract,
    decode_pair_u16_png,
    evaluate_relationship_passes,
    load_geometry_pass_policy,
    load_instance_pass_policy,
    load_relationship_pass_policy,
    publish_relationship_document,
    validate_relationship_pass_policy,
)
from test_daz_instance_pass import _owners  # noqa: E402
from test_daz_render_pass_profiles import _plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "relationship_pass.yaml"
INSTANCE_POLICY = ROOT / "configs" / "daz" / "instance_pass.yaml"
GEOMETRY_POLICY = ROOT / "configs" / "daz" / "geometry_pass.yaml"


def _sha(document: dict) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _compact(state: dict, plan: dict) -> dict:
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
    assert result["resolved_state_id"] == state["resolved_state_id"]
    return result


def _perspective(near: float = 0.1, far: float = 100.0) -> list[float]:
    a = far / (far - near)
    b = -(far * near) / (far - near)
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, a, b, 0, 0, 1, 0]


def _contracts(profile: str = "training_relationship") -> tuple[dict, dict, dict, dict, dict]:
    state, _pass_policy, raw_plan = _plan(profile)
    plan = _compact(state, raw_plan)
    instance_contract = build_instance_pass_contract(
        state,
        plan,
        _owners(state, 2),
        load_instance_pass_policy(INSTANCE_POLICY),
    )
    geometry_policy = load_geometry_pass_policy(GEOMETRY_POLICY)
    identity = np.eye(4).reshape(-1).tolist()
    coordinate = build_camera_coordinate_sidecar(
        scene_id=plan["scene_id"],
        scene_state_sha256=plan["scene_state_sha256"],
        camera_id="camera_relationship_fixture",
        projection_type="perspective",
        near_clip_m=0.1,
        far_clip_m=100.0,
        subdivision_level=2,
        resolution=[64, 48],
        crop=[0, 0, 64, 48],
        world_to_camera=identity.copy(),
        camera_to_world=identity.copy(),
        projection_matrix=_perspective(),
        policy=geometry_policy,
    )
    geometry_contract = build_geometry_pass_contract(plan, coordinate, policy=geometry_policy)
    relationship_policy = load_relationship_pass_policy(POLICY_PATH)
    relationship_contract = build_relationship_pass_contract(
        instance_contract,
        geometry_contract,
        plan,
        policy=relationship_policy,
    )
    return (
        relationship_policy,
        instance_contract,
        geometry_contract,
        plan,
        relationship_contract,
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
    )


def _paeth(a: int, b: int, c: int) -> int:
    prediction = a + b - c
    distances = [abs(prediction - value) for value in (a, b, c)]
    return (a, b, c)[distances.index(min(distances))]


def _encode_filter(row: bytes, previous: bytes, filter_type: int, bpp: int = 4) -> bytes:
    encoded = bytearray(len(row))
    for index, value in enumerate(row):
        left = row[index - bpp] if index >= bpp else 0
        up = previous[index] if previous else 0
        up_left = previous[index - bpp] if previous and index >= bpp else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        else:
            predictor = _paeth(left, up, up_left)
        encoded[index] = (value - predictor) & 0xFF
    return bytes(encoded)


def _write_pair_png(path: Path, array: np.ndarray, filter_type: int = 0) -> None:
    height, width, channels = array.shape
    assert array.dtype == np.uint16 and channels == 2
    rows = array.astype(">u2").tobytes()
    stride = width * 4
    raw = bytearray()
    previous = b""
    for y in range(height):
        row = rows[y * stride : (y + 1) * stride]
        raw.append(filter_type)
        raw.extend(_encode_filter(row, previous, filter_type))
        previous = row
    ihdr = struct.pack(">IIBBBBB", width, height, 16, 4, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def _arrays() -> dict[str, np.ndarray]:
    instance = np.zeros((48, 64), dtype=np.uint16)
    instance[6:42, 4:32] = 1
    instance[6:42, 32:60] = 2
    depth = np.full((48, 64), np.inf, dtype=np.float32)
    depth[instance == 1] = 1.0
    depth[instance == 2] = 1.5
    boundary = np.zeros((48, 64, 2), dtype=np.uint16)
    boundary[6:42, 31:33] = [1, 2]
    front = np.zeros((48, 64), dtype=np.uint16)
    front[6:42, 31] = 1
    front[6:42, 32] = 2
    contact = np.zeros_like(boundary)
    contact[15:25, 31:33] = [1, 2]
    return {
        "instance": instance,
        "depth": depth,
        "contact_pairs": contact,
        "front_owner": front,
        "boundary_pairs": boundary,
    }


def _write_fixture(root: Path, arrays: dict[str, np.ndarray]) -> dict[str, Path]:
    import cv2

    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "instance": root / "instance.png",
        "depth": root / "depth.exr",
        "contact_pairs": root / "contact_pairs.png",
        "front_owner": root / "front_owner.png",
        "boundary_pairs": root / "boundary_pairs.png",
    }
    Image.fromarray(arrays["instance"]).save(paths["instance"], format="PNG")
    assert cv2.imwrite(str(paths["depth"]), arrays["depth"])
    _write_pair_png(paths["contact_pairs"], arrays["contact_pairs"])
    Image.fromarray(arrays["front_owner"]).save(paths["front_owner"], format="PNG")
    _write_pair_png(paths["boundary_pairs"], arrays["boundary_pairs"])
    return paths


def _observations(*, contact: bool = True) -> list[dict]:
    return [
        {
            "pair": [1, 2],
            "minimum_surface_distance_mm": 0.4 if contact else 12.0,
            "maximum_penetration_mm": 0.2 if contact else 0.0,
            "minimum_normal_dot": 0.8,
            "contact_regions": (
                [{"a_part_id": 26, "b_part_id": 4, "area_mm2": 420.0}] if contact else []
            ),
            "depth_samples": [
                {"x": 31, "y": 10, "a_depth_m": 1.0, "b_depth_m": 2.0, "visible_owner": 1},
                {"x": 32, "y": 10, "a_depth_m": 2.5, "b_depth_m": 1.5, "visible_owner": 2},
            ],
        }
    ]


def _diagnostic_paths(root: Path, contract: dict) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    paths = {}
    for role in set(contract["outputs"]) - {"contact_pairs", "front_owner", "boundary_pairs"}:
        path = root / f"{role}.bin"
        path.write_bytes(f"diagnostic:{role}".encode())
        paths[role] = path
    return paths


def _execution(contract: dict, paths: dict[str, Path], diagnostic_paths: dict[str, Path]) -> dict:
    all_output_paths = {
        "contact_pairs": paths["contact_pairs"],
        "front_owner": paths["front_owner"],
        "boundary_pairs": paths["boundary_pairs"],
        **diagnostic_paths,
    }
    outputs = {}
    repeated = {}
    for role, path in all_output_paths.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        repeated[role] = digest
        output = {
            "role": role,
            "encoding": contract["outputs"][role]["encoding"],
            "resolution": deepcopy(contract["outputs"][role]["resolution"]),
            "crop": deepcopy(contract["outputs"][role]["crop"]),
            "train_eligible": False,
            "effects": [],
            "file_sha256": digest,
            "bytes": path.stat().st_size,
            "completed": True,
            "interrupted": False,
        }
        if role == "amodal_geometry":
            output.update(
                {
                    "logical_path": "13_annotations/amodal_diagnostic",
                    "physically_separate": True,
                    "absent_from_normal_training_exports": True,
                }
            )
        outputs[role] = output
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
        "sidecar_instance_contract_sha256": contract["instance_contract_sha256"],
        "sidecar_geometry_contract_sha256": contract["geometry_contract_sha256"],
        "instance_file_sha256": hashlib.sha256(paths["instance"].read_bytes()).hexdigest(),
        "depth_file_sha256": hashlib.sha256(paths["depth"].read_bytes()).hexdigest(),
        "outputs": outputs,
        "repeated_file_sha256s": repeated,
    }


def _fixture(tmp_path: Path, profile: str = "training_relationship"):
    policy, instance_contract, geometry_contract, _plan_document, contract = _contracts(profile)
    paths = _write_fixture(tmp_path, _arrays())
    diagnostic_paths = _diagnostic_paths(tmp_path, contract)
    execution = _execution(contract, paths, diagnostic_paths)
    return (
        policy,
        instance_contract,
        geometry_contract,
        contract,
        paths,
        diagnostic_paths,
        execution,
    )


def _evaluate(fixture, observations=None):
    policy, instance_contract, geometry_contract, contract, paths, diagnostic_paths, execution = (
        fixture
    )
    return evaluate_relationship_passes(
        contract,
        instance_contract,
        geometry_contract,
        execution,
        observations or _observations(),
        instance_path=paths["instance"],
        depth_path=paths["depth"],
        contact_pairs_path=paths["contact_pairs"],
        front_owner_path=paths["front_owner"],
        boundary_pairs_path=paths["boundary_pairs"],
        diagnostic_paths=diagnostic_paths,
        policy=policy,
        geometry_policy=load_geometry_pass_policy(GEOMETRY_POLICY),
    )


def _codes(report: dict) -> set[str]:
    return set(report["summary"]["failure_codes"])


def test_policy_separates_3d_contact_from_visible_depth_occlusion() -> None:
    policy = load_relationship_pass_policy(POLICY_PATH)
    validate_relationship_pass_policy(policy)
    assert policy["contact"]["geometry_only_no_rgb_inference"] is True
    assert policy["occlusion"]["visible_instance_and_linear_depth_authority"] is True
    assert policy["diagnostic"]["all_train_eligible_false"] is True


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p.__setitem__("policy_version", "2.0.0"), "identity"),
        (lambda p: p["eligible_profiles"].append("training_standard"), "profiles"),
        (lambda p: p["namespace"].__setitem__("maximum_instance_id", 5), "namespace"),
        (lambda p: p["contact"].__setitem__("geometry_only_no_rgb_inference", False), "contact"),
        (lambda p: p["occlusion"].__setitem__("depth_unit", "device"), "occlusion"),
        (lambda p: p["rasters"].__setitem__("boundary_adjacency", "four_connected"), "rasters"),
        (lambda p: p["diagnostic"].__setitem__("all_train_eligible_false", False), "diagnostic"),
        (
            lambda p: p["freeze"].__setitem__("exact_instance_depth_authority_hashes", False),
            "freeze",
        ),
        (lambda p: p["forbidden_effects"].pop(), "effects"),
    ],
)
def test_closed_policy_drift_fails(mutation, reason: str) -> None:
    policy = load_relationship_pass_policy(POLICY_PATH)
    mutation(policy)
    with pytest.raises(
        RelationshipPassContractError, match=f"relationship_policy_{reason}_invalid"
    ):
        validate_relationship_pass_policy(policy)


def test_contract_declares_every_unordered_pair_and_nontrainable_outputs() -> None:
    _policy, _instance, _geometry, _plan_document, contract = _contracts()
    assert contract["owner_ids"] == [1, 2]
    assert contract["pairs"] == [[1, 2]]
    assert all(not output["train_eligible"] for output in contract["outputs"].values())


def test_standard_profile_is_ineligible() -> None:
    with pytest.raises(RelationshipPassContractError, match="relationship_lineage_invalid"):
        _contracts("training_standard")


def test_non_list_observation_pair_fails_closed(tmp_path: Path) -> None:
    observations = _observations()
    observations[0]["pair"] = "1-2"
    with pytest.raises(RelationshipPassContractError, match="relationship_observation_invalid"):
        _evaluate(_fixture(tmp_path), observations)


@pytest.mark.parametrize("profile", ["training_relationship", "diagnostic_full"])
def test_diagnostic_path_set_must_match_contract(tmp_path: Path, profile: str) -> None:
    fixture = list(_fixture(tmp_path, profile))
    if fixture[5]:
        fixture[5].pop(next(iter(fixture[5])))
    else:
        extra = tmp_path / "unexpected.bin"
        extra.write_bytes(b"unexpected")
        fixture[5]["surface"] = extra
    with pytest.raises(
        RelationshipPassContractError, match="relationship_diagnostic_paths_invalid"
    ):
        _evaluate(tuple(fixture))


@pytest.mark.parametrize("filter_type", range(5))
def test_two_channel_uint16_png_all_filters_roundtrip(tmp_path: Path, filter_type: int) -> None:
    array = np.arange(6 * 7 * 2, dtype=np.uint16).reshape(6, 7, 2) * 997
    path = tmp_path / f"pairs_{filter_type}.png"
    _write_pair_png(path, array, filter_type)
    decoded, codec = decode_pair_u16_png(path)
    assert np.array_equal(decoded, array)
    assert codec["bit_depth"] == 16 and codec["color_type"] == 4


@pytest.mark.parametrize("corruption", ["signature", "crc", "bit_depth", "color_type", "interlace"])
def test_invalid_pair_png_fails(tmp_path: Path, corruption: str) -> None:
    path = tmp_path / "pairs.png"
    _write_pair_png(path, np.zeros((3, 4, 2), dtype=np.uint16))
    payload = bytearray(path.read_bytes())
    if corruption == "signature":
        payload[0] = 0
    elif corruption == "crc":
        payload[29] ^= 1
    else:
        ihdr = bytearray(payload[16:29])
        if corruption == "bit_depth":
            ihdr[8] = 8
        elif corruption == "color_type":
            ihdr[9] = 2
        else:
            ihdr[12] = 1
        payload[16:29] = ihdr
        payload[29:33] = struct.pack(">I", binascii.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)
    path.write_bytes(payload)
    with pytest.raises(RelationshipPassContractError, match="relationship_pair_png_"):
        decode_pair_u16_png(path)


def test_known_contact_fixture_emits_reciprocal_contact_and_mixed_occlusion(tmp_path: Path) -> None:
    report = _evaluate(_fixture(tmp_path))
    assert report["summary"]["passed"] is True
    assert report["pair_records"][0]["contact"] is True
    assert report["pair_records"][0]["occlusion_direction"] == "mixed"
    directed = {
        (row["source_instance_id"], row["target_instance_id"], row["type"])
        for row in report["directed_relationships"]
    }
    assert (1, 2, "contact") in directed and (2, 1, "contact") in directed
    assert (1, 2, "occludes") in directed and (2, 1, "occludes") in directed


def test_overlap_without_3d_contact_is_occlusion_not_contact(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    arrays = _arrays()
    arrays["contact_pairs"].fill(0)
    fixture[4].update(_write_fixture(tmp_path, arrays))
    fixture = (*fixture[:6], _execution(fixture[3], fixture[4], fixture[5]))
    report = _evaluate(fixture, _observations(contact=False))
    assert report["summary"]["passed"] is True
    assert report["pair_records"][0]["contact"] is False
    assert not any(row["type"] == "contact" for row in report["directed_relationships"])
    assert any(row["type"] == "occludes" for row in report["directed_relationships"])


def test_contact_raster_without_3d_contact_fails(tmp_path: Path) -> None:
    report = _evaluate(_fixture(tmp_path), _observations(contact=False))
    assert "RELATIONSHIP_CONTACT_RASTER_WITHOUT_3D_CONTACT" in _codes(report)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda a: a["boundary_pairs"].__setitem__((10, 31), [2, 1]),
            "RELATIONSHIP_PAIR_ENCODING_INVALID",
        ),
        (
            lambda a: a["contact_pairs"].__setitem__((0, 0), [1, 2]),
            "RELATIONSHIP_CONTACT_NOT_BOUNDARY_SUBSET",
        ),
        (
            lambda a: a["front_owner"].__setitem__((10, 31), 2),
            "RELATIONSHIP_FRONT_OWNER_INVALID",
        ),
        (
            lambda a: a["boundary_pairs"].__setitem__((0, 0), [1, 2]),
            "RELATIONSHIP_BOUNDARY_ADJACENCY_INVALID",
        ),
    ],
)
def test_seeded_raster_defects_are_detected(tmp_path: Path, mutate, code: str) -> None:
    policy, instance_contract, geometry_contract, _plan_document, contract = _contracts()
    arrays = _arrays()
    mutate(arrays)
    paths = _write_fixture(tmp_path, arrays)
    diagnostics = _diagnostic_paths(tmp_path, contract)
    fixture = (
        policy,
        instance_contract,
        geometry_contract,
        contract,
        paths,
        diagnostics,
        _execution(contract, paths, diagnostics),
    )
    assert code in _codes(_evaluate(fixture))


def test_depth_order_mismatch_is_detected(tmp_path: Path) -> None:
    observations = _observations()
    observations[0]["depth_samples"][0]["visible_owner"] = 2
    report = _evaluate(_fixture(tmp_path), observations)
    assert {
        "RELATIONSHIP_DEPTH_SAMPLE_AUTHORITY_MISMATCH",
        "RELATIONSHIP_DEPTH_ORDER_INVALID",
    } <= _codes(report)


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
    fixture = _fixture(tmp_path)
    fixture[6][field] = "0" * 64
    assert "RELATIONSHIP_SCENE_STATE_MUTATION" in _codes(_evaluate(fixture))


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
    ],
)
def test_every_forbidden_effect_is_detected(tmp_path: Path, effect: str) -> None:
    fixture = _fixture(tmp_path)
    fixture[6]["outputs"]["contact_pairs"]["effects"] = [effect]
    assert "RELATIONSHIP_EFFECT_FORBIDDEN" in _codes(_evaluate(fixture))


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda e: e.__setitem__("sidecar_plan_sha256", "0" * 64),
            "RELATIONSHIP_SIDECAR_PLAN_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_contract_sha256", "0" * 64),
            "RELATIONSHIP_SIDECAR_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_instance_contract_sha256", "0" * 64),
            "RELATIONSHIP_SIDECAR_INSTANCE_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_geometry_contract_sha256", "0" * 64),
            "RELATIONSHIP_SIDECAR_GEOMETRY_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("instance_file_sha256", "0" * 64),
            "RELATIONSHIP_INSTANCE_HASH_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("depth_file_sha256", "0" * 64),
            "RELATIONSHIP_DEPTH_HASH_MISMATCH",
        ),
        (
            lambda e: e["outputs"]["contact_pairs"].__setitem__("encoding", "rgb"),
            "RELATIONSHIP_OUTPUT_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e["outputs"]["contact_pairs"].__setitem__("file_sha256", "0" * 64),
            "RELATIONSHIP_FILE_HASH_MISMATCH",
        ),
        (
            lambda e: e["outputs"]["contact_pairs"].__setitem__("bytes", 1),
            "RELATIONSHIP_BYTE_COUNT_MISMATCH",
        ),
        (
            lambda e: e["outputs"]["contact_pairs"].__setitem__("completed", False),
            "RELATIONSHIP_OUTPUT_INCOMPLETE",
        ),
        (
            lambda e: e["repeated_file_sha256s"].__setitem__("contact_pairs", "0" * 64),
            "RELATIONSHIP_REPLAY_MISMATCH",
        ),
    ],
)
def test_sidecar_authority_output_and_replay_drift(tmp_path: Path, mutation, code: str) -> None:
    fixture = _fixture(tmp_path)
    mutation(fixture[6])
    assert code in _codes(_evaluate(fixture))


def test_diagnostic_full_outputs_are_separate_and_nontrainable(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, "diagnostic_full")
    report = _evaluate(fixture)
    assert report["summary"]["passed"] is True
    outputs = fixture[6]["outputs"]
    assert set(outputs) >= {"surface", "facet", "node", "mapping_confidence", "amodal_geometry"}
    assert outputs["amodal_geometry"]["logical_path"] == "13_annotations/amodal_diagnostic"
    assert all(output["train_eligible"] is False for output in outputs.values())


def test_amodal_training_boundary_drift_is_detected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, "diagnostic_full")
    fixture[6]["outputs"]["amodal_geometry"]["absent_from_normal_training_exports"] = False
    assert "RELATIONSHIP_AMODAL_BOUNDARY_INVALID" in _codes(_evaluate(fixture))


def test_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    _policy, _instance, _geometry, _plan_document, contract = _contracts()
    target, published = publish_relationship_document(contract, tmp_path)
    assert published is True
    assert publish_relationship_document(contract, tmp_path) == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RelationshipPassContractError, match="relationship_publication_conflict"):
        publish_relationship_document(contract, tmp_path)


def test_cli_contract_and_validation_are_idempotent(tmp_path: Path) -> None:
    policy, instance_contract, geometry_contract, plan, relationship_contract = _contracts()
    del policy, relationship_contract
    documents = {
        "instance_contract": instance_contract,
        "geometry_contract": geometry_contract,
        "plan": plan,
    }
    paths = {}
    for name, document in documents.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    contract_output = tmp_path / "contracts"
    plan_arguments = [
        "daz",
        "recipes",
        "plan-relationship-passes",
        "--instance-contract",
        str(paths["instance_contract"]),
        "--geometry-contract",
        str(paths["geometry_contract"]),
        "--pass-plan",
        str(paths["plan"]),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(contract_output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, plan_arguments)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["data"]["publication"]["published"] is True
    replay = runner.invoke(main, plan_arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False

    contract_path = Path(payload["data"]["publication"]["path"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    raster_paths = _write_fixture(tmp_path / "rasters", _arrays())
    diagnostic_paths = _diagnostic_paths(tmp_path / "diagnostics", contract)
    execution_path = tmp_path / "execution.json"
    execution_path.write_text(
        json.dumps(_execution(contract, raster_paths, diagnostic_paths)), encoding="utf-8"
    )
    observations_path = tmp_path / "observations.json"
    observations_path.write_text(json.dumps(_observations()), encoding="utf-8")
    diagnostics_path = tmp_path / "diagnostics.json"
    diagnostics_path.write_text(
        json.dumps({role: str(path) for role, path in diagnostic_paths.items()}),
        encoding="utf-8",
    )
    report_output = tmp_path / "reports"
    validate_arguments = [
        "daz",
        "recipes",
        "validate-relationship-passes",
        "--contract",
        str(contract_path),
        "--instance-contract",
        str(paths["instance_contract"]),
        "--geometry-contract",
        str(paths["geometry_contract"]),
        "--execution",
        str(execution_path),
        "--observations",
        str(observations_path),
        "--instance-image",
        str(raster_paths["instance"]),
        "--depth-exr",
        str(raster_paths["depth"]),
        "--contact-pairs",
        str(raster_paths["contact_pairs"]),
        "--front-owner",
        str(raster_paths["front_owner"]),
        "--boundary-pairs",
        str(raster_paths["boundary_pairs"]),
        "--diagnostics",
        str(diagnostics_path),
        "--policy",
        str(POLICY_PATH),
        "--geometry-policy",
        str(GEOMETRY_POLICY),
        "--output",
        str(report_output),
    ]
    checked = runner.invoke(main, validate_arguments)
    assert checked.exit_code == 0, checked.output
    checked_payload = json.loads(checked.output)
    assert checked_payload["data"]["summary"]["passed"] is True
    checked_replay = runner.invoke(main, validate_arguments)
    assert checked_replay.exit_code == 0, checked_replay.output
    assert json.loads(checked_replay.output)["data"]["publication"]["published"] is False
