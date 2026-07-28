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
from maskfactory.daz.mapping import build_v1_ontology_snapshot  # noqa: E402
from maskfactory.daz.render import (  # noqa: E402
    PartPassContractError,
    build_part_pass_contract,
    evaluate_part_pass,
    load_part_pass_policy,
    publish_part_pass_document,
    validate_part_pass_policy,
)
from test_daz_render_pass_profiles import _plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "part_pass.yaml"
ONTOLOGY_PATH = ROOT / "configs" / "ontology.yaml"


def _sha(document) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _mapping(state: dict, snapshot: dict, active_ids: list[int]) -> dict:
    payload = {
        "mapping_set_sha256": state["mapping_set_sha256"],
        "ontology_snapshot_id": snapshot["snapshot_id"],
        "ontology_snapshot_sha256": snapshot["canonical_sha256"],
        "topology_mapping_sha256": "a" * 64,
        "active_part_ids": active_ids,
        "status": "approved",
    }
    digest = _sha(payload)
    return {"mapping_id": f"dpm_{digest[:24]}", "mapping_sha256": digest, **payload}


def _contract(expected: list[int] | None = None) -> tuple[dict, dict, dict]:
    state, _pass_policy, plan = _plan("training_standard")
    snapshot = build_v1_ontology_snapshot(ONTOLOGY_PATH)
    active = [row["id"] for row in snapshot["part_labels"] if row["enabled"]]
    policy = load_part_pass_policy(POLICY_PATH)
    contract = build_part_pass_contract(
        state, plan, snapshot, _mapping(state, snapshot, active), expected or [1], policy
    )
    return policy, snapshot, contract


def _write_maps(
    part_path: Path, instance_path: Path, resolution: list[int], ids: list[int]
) -> None:
    width, height = resolution
    part = np.zeros((height, width), dtype=np.uint16)
    instance = np.zeros_like(part)
    flat_part = part.reshape(-1)
    flat_instance = instance.reshape(-1)
    chunk = max(1, len(flat_part) // (len(ids) + 2))
    cursor = chunk
    for part_id in ids:
        flat_part[cursor : cursor + chunk] = part_id
        flat_instance[cursor : cursor + chunk] = 1
        cursor += chunk
    Image.fromarray(part).save(part_path, format="PNG")
    Image.fromarray(instance).save(instance_path, format="PNG")


def _execution(contract: dict, part_path: Path, instance_path: Path) -> dict:
    part_payload = part_path.read_bytes()
    instance_payload = instance_path.read_bytes()
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
        "sidecar_mapping_sha256": contract["mapping_sha256"],
        "sidecar_ontology_snapshot_sha256": contract["ontology_snapshot_sha256"],
        "instance_file_sha256": hashlib.sha256(instance_payload).hexdigest(),
        "repeated_semantic_file_sha256": hashlib.sha256(part_payload).hexdigest(),
        "output": {
            "role": "part",
            "encoding": "uint16_png",
            "resolution": deepcopy(contract["output"]["resolution"]),
            "crop": deepcopy(contract["output"]["crop"]),
            "decode_filter": "nearest_neighbor_exact",
            "effects": [],
            "file_sha256": hashlib.sha256(part_payload).hexdigest(),
            "bytes": len(part_payload),
            "completed": True,
            "interrupted": False,
        },
    }


def _codes(report: dict) -> set[str]:
    return set(report["summary"]["failure_codes"])


def test_policy_keeps_v1_active_and_v2_inactive() -> None:
    policy = load_part_pass_policy(POLICY_PATH)
    validate_part_pass_policy(policy)
    assert policy["active_ontology_versions"] == ["body_parts_v1"]
    assert policy["inactive_ontology_versions"] == ["body_parts_v2"]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p["active_ontology_versions"].append("body_parts_v2"), "active_ontology"),
        (lambda p: p["inactive_ontology_versions"].clear(), "inactive_ontology"),
        (lambda p: p["eligible_pass_profiles"].pop(), "profiles"),
        (lambda p: p["codec"].__setitem__("encoding", "uint8_png"), "codec"),
        (lambda p: p["mapping"].__setitem__("approved_status", "draft"), "mapping"),
        (lambda p: p["pixel_invariants"].__setitem__("unknown_ids_forbidden", False), "pixels"),
        (lambda p: p["freeze"].__setitem__("repeated_semantic_hash_required", False), "freeze"),
    ],
)
def test_closed_policy_drift_fails(mutation, reason: str) -> None:
    policy = load_part_pass_policy(POLICY_PATH)
    mutation(policy)
    with pytest.raises(PartPassContractError, match=f"part_policy_{reason}_invalid"):
        validate_part_pass_policy(policy)


def test_contract_derives_ids_from_canonical_snapshot_not_local_list() -> None:
    _policy, snapshot, contract = _contract()
    assert contract["ontology_snapshot_sha256"] == snapshot["canonical_sha256"]
    assert contract["active_part_ids"] == list(range(54))
    assert contract["disabled_part_ids"] == [54, 55]
    assert contract["mapping_set_sha256"] == "3" * 64


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.__setitem__("status", "draft"),
        lambda m: m.__setitem__("ontology_snapshot_sha256", "0" * 64),
        lambda m: m.__setitem__("topology_mapping_sha256", "bad"),
        lambda m: m["active_part_ids"].pop(),
        lambda m: m.__setitem__("mapping_sha256", "0" * 64),
    ],
)
def test_mapping_binding_drift_fails(mutation) -> None:
    state, _pass_policy, plan = _plan("training_standard")
    snapshot = build_v1_ontology_snapshot(ONTOLOGY_PATH)
    active = [row["id"] for row in snapshot["part_labels"] if row["enabled"]]
    mapping = _mapping(state, snapshot, active)
    mutation(mapping)
    with pytest.raises(PartPassContractError, match="part_mapping_invalid"):
        build_part_pass_contract(
            state, plan, snapshot, mapping, [1], load_part_pass_policy(POLICY_PATH)
        )


@pytest.mark.parametrize("ids", [[], [0], [54], [1, 1], [2, 1], [1, True]])
def test_invalid_expected_visible_ids_fail(ids: list[int]) -> None:
    state, _pass_policy, plan = _plan("training_standard")
    snapshot = build_v1_ontology_snapshot(ONTOLOGY_PATH)
    active = [row["id"] for row in snapshot["part_labels"] if row["enabled"]]
    with pytest.raises(PartPassContractError, match="part_expected_ids_invalid"):
        build_part_pass_contract(
            state,
            plan,
            snapshot,
            _mapping(state, snapshot, active),
            ids,
            load_part_pass_policy(POLICY_PATH),
        )


def test_all_54_active_v1_ids_are_emitted_and_verified(tmp_path: Path) -> None:
    expected = list(range(1, 54))
    policy, _snapshot, contract = _contract(expected)
    part_path, instance_path = tmp_path / "part.png", tmp_path / "instance.png"
    _write_maps(part_path, instance_path, contract["output"]["resolution"], expected)
    report = evaluate_part_pass(
        contract, _execution(contract, part_path, instance_path), part_path, instance_path, policy
    )
    assert report["summary"]["passed"] is True
    assert report["summary"]["active_id_count"] == 54
    assert report["summary"]["expected_id_count"] == 53
    assert report["observed_ids"] == list(range(54))


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
    policy, _snapshot, contract = _contract()
    part_path, instance_path = tmp_path / "part.png", tmp_path / "instance.png"
    _write_maps(part_path, instance_path, contract["output"]["resolution"], [1])
    execution = _execution(contract, part_path, instance_path)
    execution[field] = "0" * 64
    assert "PART_SCENE_STATE_MUTATION" in _codes(
        evaluate_part_pass(contract, execution, part_path, instance_path, policy)
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
    ],
)
def test_every_forbidden_effect_is_detected(tmp_path: Path, effect: str) -> None:
    policy, _snapshot, contract = _contract()
    part_path, instance_path = tmp_path / "part.png", tmp_path / "instance.png"
    _write_maps(part_path, instance_path, contract["output"]["resolution"], [1])
    execution = _execution(contract, part_path, instance_path)
    execution["output"]["effects"] = [effect]
    assert "PART_EFFECT_FORBIDDEN" in _codes(
        evaluate_part_pass(contract, execution, part_path, instance_path, policy)
    )


def test_disabled_unknown_missing_and_instance_coverage_fail(tmp_path: Path) -> None:
    policy, _snapshot, contract = _contract([1, 2])
    part_path, instance_path = tmp_path / "part.png", tmp_path / "instance.png"
    _write_maps(part_path, instance_path, contract["output"]["resolution"], [1])
    part = np.asarray(Image.open(part_path)).copy()
    instance = np.asarray(Image.open(instance_path)).copy()
    part[0, 0] = 54
    part[0, 1] = 65535
    part[0, 2] = 1
    instance[0, 2] = 0
    instance[0, 3] = 1
    part[0, 3] = 0
    Image.fromarray(part.astype(np.uint16)).save(part_path)
    Image.fromarray(instance.astype(np.uint16)).save(instance_path)
    codes = _codes(
        evaluate_part_pass(
            contract,
            _execution(contract, part_path, instance_path),
            part_path,
            instance_path,
            policy,
        )
    )
    assert {
        "PART_ID_INACTIVE_OR_UNKNOWN",
        "PART_EXPECTED_ID_EMPTY",
        "PART_WITHOUT_INSTANCE",
        "PART_VISIBLE_INSTANCE_UNLABELED",
    } <= codes


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda e: e.__setitem__("sidecar_plan_sha256", "0" * 64), "PART_SIDECAR_PLAN_MISMATCH"),
        (
            lambda e: e.__setitem__("sidecar_contract_sha256", "0" * 64),
            "PART_SIDECAR_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_mapping_sha256", "0" * 64),
            "PART_SIDECAR_MAPPING_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_ontology_snapshot_sha256", "0" * 64),
            "PART_SIDECAR_ONTOLOGY_MISMATCH",
        ),
        (lambda e: e.__setitem__("instance_file_sha256", "0" * 64), "PART_INSTANCE_HASH_MISMATCH"),
        (
            lambda e: e.__setitem__("repeated_semantic_file_sha256", "0" * 64),
            "PART_SEMANTIC_REPLAY_MISMATCH",
        ),
        (
            lambda e: e["output"].__setitem__("decode_filter", "bilinear"),
            "PART_OUTPUT_CONTRACT_MISMATCH",
        ),
        (lambda e: e["output"].__setitem__("file_sha256", "0" * 64), "PART_FILE_HASH_MISMATCH"),
        (lambda e: e["output"].__setitem__("bytes", 1), "PART_BYTE_COUNT_MISMATCH"),
        (lambda e: e["output"].__setitem__("completed", False), "PART_OUTPUT_INCOMPLETE"),
    ],
)
def test_sidecar_output_and_replay_drift(tmp_path: Path, mutation, code: str) -> None:
    policy, _snapshot, contract = _contract()
    part_path, instance_path = tmp_path / "part.png", tmp_path / "instance.png"
    _write_maps(part_path, instance_path, contract["output"]["resolution"], [1])
    execution = _execution(contract, part_path, instance_path)
    mutation(execution)
    assert code in _codes(evaluate_part_pass(contract, execution, part_path, instance_path, policy))


def test_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    _policy, _snapshot, contract = _contract()
    target, published = publish_part_pass_document(contract, tmp_path)
    assert published is True
    assert publish_part_pass_document(contract, tmp_path) == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(PartPassContractError, match="part_publication_conflict"):
        publish_part_pass_document(contract, tmp_path)


def test_cli_contract_and_validation_are_idempotent(tmp_path: Path) -> None:
    state, _pass_policy, plan = _plan("training_standard")
    snapshot = build_v1_ontology_snapshot(ONTOLOGY_PATH)
    active = [row["id"] for row in snapshot["part_labels"] if row["enabled"]]
    mapping = _mapping(state, snapshot, active)
    documents = {
        "state": state,
        "plan": plan,
        "snapshot": snapshot,
        "mapping": mapping,
        "expected": [1],
    }
    paths = {}
    for name, document in documents.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    contract_output = tmp_path / "contracts"
    arguments = [
        "daz",
        "recipes",
        "plan-part-pass",
        "--resolved-state",
        str(paths["state"]),
        "--pass-plan",
        str(paths["plan"]),
        "--ontology-snapshot",
        str(paths["snapshot"]),
        "--mapping-binding",
        str(paths["mapping"]),
        "--expected-ids",
        str(paths["expected"]),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(contract_output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, arguments)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["data"]["publication"]["published"] is True
    replay = runner.invoke(main, arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
    contract_path = Path(payload["data"]["publication"]["path"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    part_path, instance_path = tmp_path / "part.png", tmp_path / "instance.png"
    _write_maps(part_path, instance_path, contract["output"]["resolution"], [1])
    execution_path = tmp_path / "execution.json"
    execution_path.write_text(
        json.dumps(_execution(contract, part_path, instance_path)), encoding="utf-8"
    )
    report_output = tmp_path / "reports"
    validate = [
        "daz",
        "recipes",
        "validate-part-pass",
        "--contract",
        str(contract_path),
        "--execution",
        str(execution_path),
        "--part-image",
        str(part_path),
        "--instance-image",
        str(instance_path),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(report_output),
    ]
    checked = runner.invoke(main, validate)
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.output)["data"]["summary"]["passed"] is True
    checked_replay = runner.invoke(main, validate)
    assert checked_replay.exit_code == 0, checked_replay.output
    assert json.loads(checked_replay.output)["data"]["publication"]["published"] is False
