from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maskfactory.cli import main  # noqa: E402
from maskfactory.daz.pass_semantic_validators import (  # noqa: E402
    PassSemanticValidationError,
    load_pass_semantic_policy,
    validate_pass_semantic_policy,
    validate_render_layer,
    validate_semantic_layer,
)
from maskfactory.daz.passes import (  # noqa: E402
    evaluate_render_pass_execution,
    load_render_pass_policy,
)
from maskfactory.daz.render import (  # noqa: E402
    evaluate_same_state_replay,
    load_same_state_replay_policy,
)
from maskfactory.daz.validation_registry import load_validation_registry  # noqa: E402
from test_daz_render_pass_profiles import _plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "strict_pass_semantic_validators.yaml"
REGISTRY_PATH = ROOT / "configs" / "daz" / "validation_registry.yaml"
PASS_POLICY_PATH = ROOT / "configs" / "daz" / "render_pass_profiles.yaml"
REPLAY_POLICY_PATH = ROOT / "configs" / "daz" / "same_state_replay.yaml"


def _policy() -> dict:
    return load_pass_semantic_policy(POLICY_PATH)


def _registry() -> dict:
    return load_validation_registry(REGISTRY_PATH)


def _digest(path: Path) -> tuple[str, int]:
    payload = path.read_bytes()
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _write_u16(path: Path, array: np.ndarray) -> None:
    Image.fromarray(array.astype(np.uint16)).save(path)


def _render_paths(root: Path, plan: dict) -> dict[str, Path]:
    root.mkdir(parents=True)
    width, height = plan["outputs"][0]["resolution"]
    yy, xx = np.indices((height, width))
    rgb = np.stack(
        [
            (xx % 251).astype(np.uint8),
            (yy % 241).astype(np.uint8),
            ((xx + yy) % 239).astype(np.uint8),
        ],
        axis=2,
    )
    paths = {}
    for output in plan["outputs"]:
        role = output["role"]
        path = root / f"{role}.png"
        if output["encoding"] == "lossless_rgb_png":
            Image.fromarray(rgb, mode="RGB").save(path)
        else:
            values = np.zeros((height, width), dtype=np.uint16)
            values[height // 4 : 3 * height // 4, width // 4 : 3 * width // 4] = 1
            _write_u16(path, values)
        paths[role] = path
    return paths


def _execution(plan: dict, paths: dict[str, Path]) -> dict:
    passes = []
    for output in plan["outputs"]:
        digest, byte_count = _digest(paths[output["role"]])
        passes.append(
            {
                "sequence": output["sequence"],
                "role": output["role"],
                "encoding": output["encoding"],
                "resolution": deepcopy(output["resolution"]),
                "crop": deepcopy(output["crop"]),
                "file_sha256": digest,
                "bytes": byte_count,
                "scene_state_before_sha256": plan["scene_state_sha256"],
                "sidecar_scene_state_sha256": plan["scene_state_sha256"],
                "scene_state_after_sha256": plan["scene_state_sha256"],
                "annotation_restore_scene_state_sha256": plan["scene_state_sha256"],
                "sidecar_plan_sha256": plan["plan_sha256"],
                "effects": [],
                "decode_filter": (
                    "nearest_neighbor_exact"
                    if output["integer_map_rules_required"]
                    else "native_lossless"
                ),
            }
        )
    return {
        "schema_version": "1.0.0",
        "scene_id": plan["scene_id"],
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "passes": passes,
        "semantic_passes_rendered": sum(row["semantic"] for row in plan["outputs"]),
        "parent_semantic_set_sha256": None,
        "terminal_scene_state_sha256": plan["scene_state_sha256"],
    }


def _run(run_id: str, process_id: int) -> dict:
    policy = load_same_state_replay_policy(REPLAY_POLICY_PATH)
    return {
        "run_id": run_id,
        "process_id": process_id,
        **{
            field: hashlib.sha256(f"authority:{field}".encode()).hexdigest()
            for field in policy["authority_fields"]
        },
    }


def _render_fixture(tmp_path: Path):
    _state, pass_policy, plan = _plan("engineering_minimal")
    original_paths = _render_paths(tmp_path / "original", plan)
    replay_paths = _render_paths(tmp_path / "replay", plan)
    execution = _execution(plan, original_paths)
    replay_execution = _execution(plan, replay_paths)
    execution_report = evaluate_render_pass_execution(plan, execution, pass_policy)
    replay_report = evaluate_same_state_replay(
        plan,
        execution,
        replay_execution,
        _run("v5_original", 101),
        _run("v5_replay", 202),
        original_paths=original_paths,
        replay_paths=replay_paths,
        pass_policy=pass_policy,
        policy=load_same_state_replay_policy(REPLAY_POLICY_PATH),
    )
    return plan, execution, execution_report, replay_report, original_paths


def _v5(fixture) -> dict:
    plan, execution, execution_report, replay_report, paths = fixture
    return validate_render_layer(
        plan,
        execution,
        execution_report,
        replay_report,
        paths,
        policy=_policy(),
        registry=_registry(),
        evidence_paths=["fixtures/plan.json", "fixtures/render_outputs.json"],
    )


def _semantic_fixture(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    shape = (64, 64)
    instance = np.zeros(shape, dtype=np.uint16)
    instance[8:56, 8:40] = 1
    instance[16:48, 46:60] = 2
    part = np.zeros(shape, dtype=np.uint16)
    part[instance == 1] = 4
    part[instance == 2] = 50
    material = np.zeros(shape, dtype=np.uint16)
    material[instance == 1] = 1
    material[instance == 2] = 13
    protected = np.zeros(shape, dtype=np.uint16)
    protected[instance == 2] = 50
    alpha = np.zeros(shape, dtype=np.uint16)
    alpha[instance > 0] = 65535
    skeleton = np.zeros(shape, dtype=np.uint16)
    surface = np.zeros(shape, dtype=np.uint16)
    surface[part == 4] = 1
    target = instance == 1
    depth_boundary = np.zeros(shape, dtype=np.uint16)
    depth_boundary[8:56, 8] = 1
    depth_boundary[8:56, 39] = 1
    depth_boundary[8, 8:40] = 1
    depth_boundary[55, 8:40] = 1
    rgb = np.full((*shape, 3), [20, 20, 20], dtype=np.uint8)
    rgb[target] = [150, 90, 55]
    rgb[instance == 2] = [30, 160, 80]
    arrays = {
        "instance": instance,
        "part": part,
        "material": material,
        "protected": protected,
        "coverage_alpha": alpha,
        "skeleton_owner": skeleton,
        "surface_orientation": surface,
        "depth_discontinuity": depth_boundary,
    }
    paths: dict[str, Path] = {}
    rgb_path = tmp_path / "rgb.png"
    Image.fromarray(rgb, mode="RGB").save(rgb_path)
    paths["rgb"] = rgb_path
    for role, array in arrays.items():
        path = tmp_path / f"{role}.png"
        _write_u16(path, array)
        paths[role] = path
    authority = {
        "schema_version": "1.0.0",
        "scene_id": "daz_scene_v6_fixture",
        "provider_id": "daz_exact_geometry",
        "authority_tier": "synthetic_exact",
        "ontology_version": "body_parts_v1",
        "ontology_sha256": "a" * 64,
        "owner": "maskfactory",
        "package_revision": "fixture-r1",
        "certificate_id": "cert_fixture_v6",
        "certificate_sha256": "b" * 64,
        "certificate_scope": "fixture_only",
        "transform_chain_sha256": "c" * 64,
        "target_instance_id": 1,
        "other_instance_ids": [2],
        "expected_visible_part_ids": [4],
        "absent_part_ids": [],
        "area_check_part_ids": [],
    }
    return paths, authority


def _v6(paths: dict[str, Path], authority: dict) -> dict:
    return validate_semantic_layer(
        authority["scene_id"],
        paths,
        authority,
        policy=_policy(),
        registry=_registry(),
        evidence_paths=["fixtures/authority.json", "fixtures/rasters.json"],
    )


def test_policy_and_positive_v5_v6_are_closed_and_normalized(tmp_path: Path) -> None:
    validate_pass_semantic_policy(_policy())
    v5 = _v5(_render_fixture(tmp_path / "render"))
    paths, authority = _semantic_fixture(tmp_path / "semantic")
    v6 = _v6(paths, authority)
    assert (v5["status"], v5["reason_code"]) == ("pass", "RENDER_VALID")
    assert (v6["status"], v6["reason_code"]) == ("pass", "SEMANTIC_VALID")
    assert v6["observed"]["defect_count"] == 0


@pytest.mark.parametrize("field", ["require_same_state_replay", "require_independent_file_hashes"])
def test_render_policy_cannot_weaken_required_evidence(field: str) -> None:
    policy = _policy()
    policy["render"][field] = False
    with pytest.raises(PassSemanticValidationError, match="render_policy"):
        validate_pass_semantic_policy(policy)


def test_v5_rehashes_actual_files_instead_of_trusting_execution(tmp_path: Path) -> None:
    fixture = list(_render_fixture(tmp_path))
    pixels = np.asarray(Image.open(fixture[4]["part"])).copy()
    pixels[0, 0] = 7
    _write_u16(fixture[4]["part"], pixels)
    result = _v5(tuple(fixture))
    assert result["status"] == "fail"
    assert result["reason_code"] == "RENDER_HASH_MISMATCH"


def test_v5_rejects_actual_dimension_drift(tmp_path: Path) -> None:
    fixture = list(_render_fixture(tmp_path))
    _write_u16(fixture[4]["part"], np.ones((8, 8), dtype=np.uint16))
    digest, byte_count = _digest(fixture[4]["part"])
    record = next(row for row in fixture[1]["passes"] if row["role"] == "part")
    record["file_sha256"], record["bytes"] = digest, byte_count
    fixture[2] = evaluate_render_pass_execution(
        fixture[0], fixture[1], load_render_pass_policy(PASS_POLICY_PATH)
    )
    result = _v5(tuple(fixture))
    assert result["reason_code"] == "RENDER_DIMENSION_MISMATCH"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda a: a["part"].__setitem__((10, 10), 99), "ID_UNKNOWN_VALUE"),
        (lambda a: a["part"].__setitem__((10, 10), 0), "ID_OWNERSHIP_INVALID"),
        (lambda a: a["protected"].__setitem__((20, 50), 0), "ID_OWNERSHIP_INVALID"),
        (lambda a: a["material"].__setitem__((20, 50), 1), "SEMANTIC_MAPPING_INVALID"),
        (lambda a: a["surface_orientation"].__setitem__((10, 10), 2), "SEMANTIC_MAPPING_INVALID"),
        (
            lambda a: a["depth_discontinuity"].__setitem__(slice(None), 0),
            "SEMANTIC_BOUNDARY_INVALID",
        ),
    ],
)
def test_v6_scans_every_pixel_and_normalizes_defects(tmp_path: Path, mutation, reason: str) -> None:
    paths, authority = _semantic_fixture(tmp_path)
    arrays = {
        role: np.asarray(Image.open(path)).copy() for role, path in paths.items() if role != "rgb"
    }
    mutation(arrays)
    for role, array in arrays.items():
        _write_u16(paths[role], array)
    result = _v6(paths, authority)
    assert result["status"] == "fail"
    assert result["reason_code"] == reason


def test_v6_authority_cannot_relabel_maskfactory_gold(tmp_path: Path) -> None:
    paths, authority = _semantic_fixture(tmp_path)
    authority["owner"] = "bundle_selector"
    with pytest.raises(PassSemanticValidationError, match="semantic_authority_invalid"):
        _v6(paths, authority)


def test_v6_area_plausibility_is_explicitly_scoped_and_full_image(tmp_path: Path) -> None:
    paths, authority = _semantic_fixture(tmp_path)
    authority["area_check_part_ids"] = [4]
    result = _v6(paths, authority)
    assert result["reason_code"] == "SEMANTIC_MAPPING_INVALID"
    assert any(row["path"] == "/part/4/area" for row in result["observed"]["findings"])


def test_v6_checks_present_anatomical_chain_adjacency(tmp_path: Path) -> None:
    paths, authority = _semantic_fixture(tmp_path)
    part = np.asarray(Image.open(paths["part"])).copy()
    skeleton = np.asarray(Image.open(paths["skeleton_owner"])).copy()
    part[10:14, 10:14] = 14
    part[30:34, 20:24] = 16
    part[46:50, 30:34] = 18
    skeleton[np.isin(part, [14, 16, 18])] = 1
    _write_u16(paths["part"], part)
    _write_u16(paths["skeleton_owner"], skeleton)
    result = _v6(paths, authority)
    assert result["reason_code"] == "SEMANTIC_MAPPING_INVALID"
    assert any("/adjacency/" in row["path"] for row in result["observed"]["findings"])


def test_v6_requires_exact_raster_role_order(tmp_path: Path) -> None:
    paths, authority = _semantic_fixture(tmp_path)
    reordered = {key: paths[key] for key in reversed(paths)}
    with pytest.raises(PassSemanticValidationError, match="semantic_raster_role_order_invalid"):
        _v6(reordered, authority)


def test_cli_publishes_idempotent_v5_v6_set_with_hashed_input_evidence(tmp_path: Path) -> None:
    plan, execution, execution_report, replay_report, render_paths = _render_fixture(
        tmp_path / "render"
    )
    semantic_paths, authority = _semantic_fixture(tmp_path / "semantic")
    authority["scene_id"] = plan["scene_id"]
    documents = {
        "plan": plan,
        "execution": execution,
        "execution_report": execution_report,
        "replay_report": replay_report,
        "semantic_authority": authority,
        "render_files": {key: str(value) for key, value in render_paths.items()},
        "semantic_files": {key: str(value) for key, value in semantic_paths.items()},
    }
    paths = {}
    for name, document in documents.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "reports"
    arguments = [
        "daz",
        "recipes",
        "validate-pass-semantics",
        "--plan",
        str(paths["plan"]),
        "--execution",
        str(paths["execution"]),
        "--execution-report",
        str(paths["execution_report"]),
        "--replay-report",
        str(paths["replay_report"]),
        "--render-files",
        str(paths["render_files"]),
        "--semantic-authority",
        str(paths["semantic_authority"]),
        "--semantic-files",
        str(paths["semantic_files"]),
        "--policy",
        str(POLICY_PATH),
        "--registry",
        str(REGISTRY_PATH),
        "--output",
        str(output),
    ]
    first = CliRunner().invoke(main, arguments)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["reason"] == "daz_pass_semantics_valid"
    assert payload["data"]["summary"]["required_count"] == 2
    assert [row["validator_id"] for row in payload["data"]["results"]] == [
        "DAZ-V5-001",
        "DAZ-V6-001",
    ]
    for row in payload["data"]["results"]:
        assert all((output / relative).is_file() for relative in row["evidence_paths"])
    replay = CliRunner().invoke(main, arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
