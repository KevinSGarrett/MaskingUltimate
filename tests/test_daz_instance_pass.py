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
from maskfactory.daz.render import (  # noqa: E402
    InstancePassContractError,
    build_instance_pass_contract,
    decode_u16_png_exact,
    evaluate_instance_pass,
    load_instance_pass_policy,
    publish_instance_pass_document,
    validate_instance_pass_policy,
)
from test_daz_render_pass_profiles import _plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "instance_pass.yaml"


def _owners(state: dict, count: int = 1) -> list[dict]:
    nodes = [asset["node_id"] for asset in state["state"]["assets"]]
    return [
        {
            "p_index": f"p{index}",
            "instance_id": index + 1,
            "construction_id": f"c{index}",
            "node_ids": [nodes[index]],
        }
        for index in range(count)
    ]


def _contract(owner_count: int = 1) -> tuple[dict, dict, dict]:
    state, _pass_policy, plan = _plan("training_standard")
    policy = load_instance_pass_policy(POLICY_PATH)
    contract = build_instance_pass_contract(state, plan, _owners(state, owner_count), policy)
    return state, policy, contract


def _write_map(path: Path, resolution: list[int], owner_fractions: list[float]) -> None:
    width, height = resolution
    array = np.zeros((height, width), dtype=np.uint16)
    cursor = 0
    total = width * height
    flat = array.reshape(-1)
    for instance_id, fraction in enumerate(owner_fractions, start=1):
        count = int(total * fraction)
        flat[cursor : cursor + count] = instance_id
        cursor += count
    Image.fromarray(array).save(path, format="PNG")


def _execution(contract: dict, image_path: Path) -> dict:
    payload = image_path.read_bytes()
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
        "repeated_semantic_file_sha256": hashlib.sha256(payload).hexdigest(),
        "output": {
            "role": "instance",
            "encoding": "uint16_png",
            "resolution": deepcopy(contract["output"]["resolution"]),
            "crop": deepcopy(contract["output"]["crop"]),
            "decode_filter": "nearest_neighbor_exact",
            "effects": [],
            "file_sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "completed": True,
            "interrupted": False,
        },
    }


def _codes(report: dict) -> set[str]:
    return set(report["summary"]["failure_codes"])


def test_policy_closes_codec_namespace_ownership_and_freeze() -> None:
    policy = load_instance_pass_policy(POLICY_PATH)
    validate_instance_pass_policy(policy)
    assert policy["namespace"]["ordered_mapping"] == [
        {"p_index": "p0", "instance_id": 1},
        {"p_index": "p1", "instance_id": 2},
        {"p_index": "p2", "instance_id": 3},
        {"p_index": "p3", "instance_id": 4},
    ]
    assert policy["codec"]["background_value"] == 0
    assert policy["codec"]["decode_filter"] == "nearest_neighbor_exact"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p["eligible_pass_profiles"].pop(), "profiles"),
        (lambda p: p["codec"].__setitem__("integer_bits", 8), "codec"),
        (lambda p: p["namespace"].__setitem__("maximum_people", 5), "namespace"),
        (lambda p: p["ownership"].__setitem__("node_ids_required", False), "ownership"),
        (lambda p: p["freeze"].__setitem__("repeated_semantic_hash_required", False), "freeze"),
    ],
)
def test_policy_drift_fails_closed(mutation, reason: str) -> None:
    policy = load_instance_pass_policy(POLICY_PATH)
    mutation(policy)
    with pytest.raises(InstancePassContractError, match=f"instance_policy_{reason}_invalid"):
        validate_instance_pass_policy(policy)


def test_contract_binds_exact_p_index_ids_nodes_and_state() -> None:
    state, _policy, contract = _contract(2)
    assert [owner["p_index"] for owner in contract["owners"]] == ["p0", "p1"]
    assert [owner["instance_id"] for owner in contract["owners"]] == [1, 2]
    assert contract["scene_state_sha256"] == state["scene_state_sha256"]
    assert contract["output"]["encoding"] == "uint16_png"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda owners: owners.clear(),
        lambda owners: owners.extend(deepcopy(owners) * 4),
        lambda owners: owners[0].__setitem__("p_index", "p1"),
        lambda owners: owners[0].__setitem__("instance_id", 2),
        lambda owners: owners[0].__setitem__("construction_id", ""),
        lambda owners: owners[0].__setitem__("node_ids", []),
        lambda owners: owners[0]["node_ids"].append("node_unknown"),
        lambda owners: owners.append({**deepcopy(owners[0]), "p_index": "p1", "instance_id": 2}),
    ],
)
def test_invalid_owner_contract_fails(mutation) -> None:
    state, _pass_policy, plan = _plan("training_standard")
    owners = _owners(state)
    mutation(owners)
    with pytest.raises(InstancePassContractError, match="instance_owner|instance_owners"):
        build_instance_pass_contract(state, plan, owners, load_instance_pass_policy(POLICY_PATH))


def test_u16_png_codec_exhaustively_round_trips_all_65536_values(tmp_path: Path) -> None:
    expected = np.arange(65536, dtype=np.uint16).reshape(256, 256)
    path = tmp_path / "all_u16_values.png"
    Image.fromarray(expected).save(path, format="PNG")
    decoded, metadata = decode_u16_png_exact(path)
    assert decoded.dtype == np.uint16
    assert np.array_equal(decoded, expected)
    assert metadata["minimum"] == 0
    assert metadata["maximum"] == 65535
    assert metadata["resolution"] == [256, 256]


@pytest.mark.parametrize("mode", ["RGB", "P", "L"])
def test_non_u16_or_palette_png_is_rejected(tmp_path: Path, mode: str) -> None:
    path = tmp_path / f"bad_{mode}.png"
    Image.new(mode, (8, 8)).save(path, format="PNG")
    with pytest.raises(InstancePassContractError, match="instance_codec_format_invalid"):
        decode_u16_png_exact(path)


def test_valid_instance_map_passes_with_exact_semantic_replay(tmp_path: Path) -> None:
    _state_document, policy, contract = _contract()
    path = tmp_path / "instance.png"
    _write_map(path, contract["output"]["resolution"], [0.25])
    report = evaluate_instance_pass(contract, _execution(contract, path), path, policy)
    assert report["summary"] == {
        "passed": True,
        "finding_count": 0,
        "failure_codes": [],
        "owner_count": 1,
        "scene_state_unchanged": True,
        "semantic_replay_identical": True,
    }
    assert report["observed_ids"] == [0, 1]
    assert report["owner_measurements"][0]["visible_area_fraction"] >= 0.249


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
def test_any_scene_mutation_invalidates_instance_pass(tmp_path: Path, field: str) -> None:
    _state_document, policy, contract = _contract()
    path = tmp_path / "instance.png"
    _write_map(path, contract["output"]["resolution"], [0.25])
    execution = _execution(contract, path)
    execution[field] = "0" * 64
    report = evaluate_instance_pass(contract, execution, path, policy)
    assert "INSTANCE_SCENE_STATE_MUTATION" in _codes(report)
    assert report["summary"]["scene_state_unchanged"] is False


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
    _state_document, policy, contract = _contract()
    path = tmp_path / "instance.png"
    _write_map(path, contract["output"]["resolution"], [0.25])
    execution = _execution(contract, path)
    execution["output"]["effects"] = [effect]
    assert "INSTANCE_EFFECT_FORBIDDEN" in _codes(
        evaluate_instance_pass(contract, execution, path, policy)
    )


def test_unknown_empty_small_and_misranked_instances_fail(tmp_path: Path) -> None:
    _state_document, policy, solo = _contract()
    path = tmp_path / "unknown.png"
    _write_map(path, solo["output"]["resolution"], [0.01])
    pixels, _ = decode_u16_png_exact(path)
    pixels = pixels.copy()
    pixels[0, 0] = 9
    Image.fromarray(pixels).save(path, format="PNG")
    execution = _execution(solo, path)
    codes = _codes(evaluate_instance_pass(solo, execution, path, policy))
    assert {"INSTANCE_ID_UNDECLARED", "INSTANCE_PROMINENCE_BELOW_FLOOR"} <= codes

    _state_document, policy, duo = _contract(2)
    duo_path = tmp_path / "misranked.png"
    _write_map(duo_path, duo["output"]["resolution"], [0.10, 0.20])
    codes = _codes(evaluate_instance_pass(duo, _execution(duo, duo_path), duo_path, policy))
    assert "INSTANCE_PROMINENCE_RANK_MISMATCH" in codes

    empty_path = tmp_path / "empty_owner.png"
    _write_map(empty_path, duo["output"]["resolution"], [0.20, 0.0])
    codes = _codes(evaluate_instance_pass(duo, _execution(duo, empty_path), empty_path, policy))
    assert "INSTANCE_DECLARED_OWNER_EMPTY" in codes


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda e: e.__setitem__("sidecar_plan_sha256", "0" * 64),
            "INSTANCE_SIDECAR_PLAN_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_contract_sha256", "0" * 64),
            "INSTANCE_SIDECAR_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("repeated_semantic_file_sha256", "0" * 64),
            "INSTANCE_SEMANTIC_REPLAY_MISMATCH",
        ),
        (
            lambda e: e["output"].__setitem__("decode_filter", "bilinear"),
            "INSTANCE_OUTPUT_CONTRACT_MISMATCH",
        ),
        (lambda e: e["output"].__setitem__("file_sha256", "0" * 64), "INSTANCE_FILE_HASH_MISMATCH"),
        (lambda e: e["output"].__setitem__("bytes", 1), "INSTANCE_BYTE_COUNT_MISMATCH"),
        (lambda e: e["output"].__setitem__("completed", False), "INSTANCE_OUTPUT_INCOMPLETE"),
    ],
)
def test_sidecar_output_and_replay_drift_is_detected(tmp_path: Path, mutation, code: str) -> None:
    _state_document, policy, contract = _contract()
    path = tmp_path / "instance.png"
    _write_map(path, contract["output"]["resolution"], [0.25])
    execution = _execution(contract, path)
    mutation(execution)
    assert code in _codes(evaluate_instance_pass(contract, execution, path, policy))


def test_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    _state_document, _policy, contract = _contract()
    target, published = publish_instance_pass_document(contract, tmp_path)
    assert published is True
    assert publish_instance_pass_document(contract, tmp_path) == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(InstancePassContractError, match="instance_publication_conflict"):
        publish_instance_pass_document(contract, tmp_path)


def test_cli_contract_and_validation_are_idempotent(tmp_path: Path) -> None:
    state, _pass_policy, plan = _plan("training_standard")
    owners = _owners(state)
    paths = {}
    for name, document in (("state", state), ("plan", plan), ("owners", owners)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    contract_output = tmp_path / "contracts"
    contract_args = [
        "daz",
        "recipes",
        "plan-instance-pass",
        "--resolved-state",
        str(paths["state"]),
        "--pass-plan",
        str(paths["plan"]),
        "--owners",
        str(paths["owners"]),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(contract_output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, contract_args)
    assert first.exit_code == 0, first.output
    first_payload = json.loads(first.output)
    assert first_payload["data"]["publication"]["published"] is True
    replay = runner.invoke(main, contract_args)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
    contract_path = Path(first_payload["data"]["publication"]["path"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    image_path = tmp_path / "instance.png"
    _write_map(image_path, contract["output"]["resolution"], [0.25])
    execution_path = tmp_path / "execution.json"
    execution_path.write_text(json.dumps(_execution(contract, image_path)), encoding="utf-8")
    report_output = tmp_path / "reports"
    report_args = [
        "daz",
        "recipes",
        "validate-instance-pass",
        "--contract",
        str(contract_path),
        "--execution",
        str(execution_path),
        "--image",
        str(image_path),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(report_output),
    ]
    validated = runner.invoke(main, report_args)
    assert validated.exit_code == 0, validated.output
    assert json.loads(validated.output)["data"]["summary"]["passed"] is True
    validated_replay = runner.invoke(main, report_args)
    assert validated_replay.exit_code == 0, validated_replay.output
    assert json.loads(validated_replay.output)["data"]["publication"]["published"] is False
