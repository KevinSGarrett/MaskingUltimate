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
    MaterialProtectedContractError,
    build_material_protected_contract,
    build_part_pass_contract,
    evaluate_material_protected_passes,
    load_material_protected_policy,
    load_part_pass_policy,
    publish_material_protected_document,
    validate_material_protected_policy,
)
from test_daz_part_pass import _mapping  # noqa: E402
from test_daz_render_pass_profiles import _plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "material_protected_pass.yaml"
PART_POLICY = ROOT / "configs" / "daz" / "part_pass.yaml"
ONTOLOGY = ROOT / "configs" / "ontology.yaml"


def _contract(
    profile: str = "training_standard", expected_material_ids: list[int] | None = None
) -> tuple[dict, dict, dict]:
    state, _pass_policy, plan = _plan(profile)
    snapshot = build_v1_ontology_snapshot(ONTOLOGY)
    active_part = [row["id"] for row in snapshot["part_labels"] if row["enabled"]]
    mapping = _mapping(state, snapshot, active_part)
    part_contract = build_part_pass_contract(
        state,
        plan,
        snapshot,
        mapping,
        [1, 2, 36, 50, 51, 52, 53],
        load_part_pass_policy(PART_POLICY),
    )
    policy = load_material_protected_policy(POLICY_PATH)
    contract = build_material_protected_contract(
        part_contract,
        plan,
        snapshot,
        target_p_index="p0",
        expected_material_ids=expected_material_ids or [1, 2, 7, 9, 13, 14],
        policy=policy,
    )
    return policy, snapshot, contract


def _valid_arrays(resolution: list[int]) -> dict[str, np.ndarray]:
    width, height = resolution
    shape = (height, width)
    arrays = {
        name: np.zeros(shape, dtype=np.uint16)
        for name in ("material", "protected", "part", "instance")
    }
    flat = {name: value.reshape(-1) for name, value in arrays.items()}
    chunk = max(64, flat["material"].size // 12)
    rows = [
        (1, 0, 2, 1),
        (2, 0, 1, 1),
        (7, 0, 36, 1),
        (9, 53, 53, 1),
        (13, 50, 50, 2),
        (14, 51, 51, 0),
        (14, 52, 52, 0),
        (14, 53, 53, 0),
    ]
    cursor = chunk
    for material_id, protected_id, part_id, instance_id in rows:
        stop = cursor + chunk
        flat["material"][cursor:stop] = material_id
        flat["protected"][cursor:stop] = protected_id
        flat["part"][cursor:stop] = part_id
        flat["instance"][cursor:stop] = instance_id
        cursor = stop
    return arrays


def _all_material_arrays(resolution: list[int]) -> dict[str, np.ndarray]:
    arrays = _valid_arrays(resolution)
    flat = {name: value.reshape(-1) for name, value in arrays.items()}
    chunk = 32
    cursor = 1
    for material_id in range(1, 16):
        stop = cursor + chunk
        if material_id == 13:
            protected_id, part_id, instance_id = 50, 50, 2
        elif material_id == 14:
            protected_id, part_id, instance_id = 51, 51, 0
        elif material_id == 9:
            protected_id, part_id, instance_id = 53, 53, 1
        else:
            protected_id, part_id, instance_id = 0, 2, 1
        flat["material"][cursor:stop] = material_id
        flat["protected"][cursor:stop] = protected_id
        flat["part"][cursor:stop] = part_id
        flat["instance"][cursor:stop] = instance_id
        cursor = stop
    return arrays


def _write_arrays(
    root: Path, arrays: dict[str, np.ndarray], *, protected: bool = True
) -> dict[str, Path]:
    paths = {}
    for name, array in arrays.items():
        if name == "protected" and not protected:
            continue
        path = root / f"{name}.png"
        Image.fromarray(array).save(path, format="PNG")
        paths[name] = path
    return paths


def _execution(contract: dict, paths: dict[str, Path]) -> dict:
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    outputs = {}
    for role in contract["outputs"]:
        payload = paths[role].read_bytes()
        outputs[role] = {
            "role": role,
            "encoding": "uint16_png",
            "resolution": deepcopy(contract["outputs"][role]["resolution"]),
            "crop": deepcopy(contract["outputs"][role]["crop"]),
            "decode_filter": "nearest_neighbor_exact",
            "effects": [],
            "file_sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
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
        "sidecar_ontology_snapshot_sha256": contract["ontology_snapshot_sha256"],
        "sidecar_mapping_sha256": contract["mapping_sha256"],
        "part_file_sha256": hashes["part"],
        "instance_file_sha256": hashes["instance"],
        "repeated_material_file_sha256": hashes["material"],
        "repeated_protected_file_sha256": hashes.get("protected"),
        "outputs": outputs,
    }


def _evaluate(
    contract: dict, policy: dict, paths: dict[str, Path], execution: dict | None = None
) -> dict:
    return evaluate_material_protected_passes(
        contract,
        execution or _execution(contract, paths),
        material_path=paths["material"],
        protected_path=paths.get("protected"),
        part_path=paths["part"],
        instance_path=paths["instance"],
        policy=policy,
    )


def _codes(report: dict) -> set[str]:
    return set(report["summary"]["failure_codes"])


def test_policy_uses_canonical_material_and_protected_namespaces() -> None:
    policy = load_material_protected_policy(POLICY_PATH)
    validate_material_protected_policy(policy)
    assert policy["protected_namespace"] == {
        "other_person": 50,
        "occluding_object": 51,
        "support_surface": 52,
        "accessory_or_prop": 53,
    }
    assert policy["material_relations"]["protected_allowed_material_ids"] == {
        50: [13],
        51: [14],
        52: [14],
        53: [9, 14],
    }


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p.__setitem__("active_ontology_version", "body_parts_v2"), "identity"),
        (lambda p: p["profile_outputs"]["engineering_minimal"].append("protected"), "profiles"),
        (lambda p: p["codec"].__setitem__("encoding", "uint8_png"), "codec"),
        (lambda p: p["protected_namespace"].__setitem__("other_person", 1), "protected"),
        (lambda p: p["material_relations"].__setitem__("other_person_material", 14), "relations"),
        (lambda p: p["orthogonality"].__setitem__("background_all_zero", False), "orthogonality"),
        (
            lambda p: p["freeze"].__setitem__(
                "repeated_material_and_protected_hashes_required", False
            ),
            "freeze",
        ),
    ],
)
def test_closed_policy_drift_fails(mutation, reason: str) -> None:
    policy = load_material_protected_policy(POLICY_PATH)
    mutation(policy)
    with pytest.raises(MaterialProtectedContractError, match=f"material_policy_{reason}_invalid"):
        validate_material_protected_policy(policy)


def test_contract_uses_all_16_canonical_materials_and_four_protected_classes() -> None:
    _policy, snapshot, contract = _contract()
    assert contract["active_material_ids"] == list(range(16))
    assert [row["name"] for row in contract["material_labels"]] == [
        row["name"] for row in snapshot["material_labels"]
    ]
    assert contract["protected_namespace"] == {
        "other_person": 50,
        "occluding_object": 51,
        "support_surface": 52,
        "accessory_or_prop": 53,
    }
    assert set(contract["outputs"]) == {"material", "protected"}


def test_engineering_profile_is_material_only() -> None:
    policy, _snapshot, contract = _contract("engineering_minimal", [1, 2, 7])
    assert policy["profile_outputs"]["engineering_minimal"] == ["material"]
    assert set(contract["outputs"]) == {"material"}


@pytest.mark.parametrize("value", ["x0", "p4", "p-1", ""])
def test_invalid_target_index_fails(value: str) -> None:
    state, _pass_policy, plan = _plan("training_standard")
    snapshot = build_v1_ontology_snapshot(ONTOLOGY)
    active = [row["id"] for row in snapshot["part_labels"] if row["enabled"]]
    part_contract = build_part_pass_contract(
        state,
        plan,
        snapshot,
        _mapping(state, snapshot, active),
        [1],
        load_part_pass_policy(PART_POLICY),
    )
    with pytest.raises(MaterialProtectedContractError, match="material_target_p_index_invalid"):
        build_material_protected_contract(
            part_contract,
            plan,
            snapshot,
            target_p_index=value,
            expected_material_ids=[1],
            policy=load_material_protected_policy(POLICY_PATH),
        )


@pytest.mark.parametrize("ids", [[], [0], [16], [1, 1], [2, 1], [True]])
def test_invalid_expected_material_ids_fail(ids: list[int]) -> None:
    state, _pass_policy, plan = _plan("training_standard")
    snapshot = build_v1_ontology_snapshot(ONTOLOGY)
    active = [row["id"] for row in snapshot["part_labels"] if row["enabled"]]
    part_contract = build_part_pass_contract(
        state,
        plan,
        snapshot,
        _mapping(state, snapshot, active),
        [1],
        load_part_pass_policy(PART_POLICY),
    )
    with pytest.raises(MaterialProtectedContractError, match="material_expected_ids_invalid"):
        build_material_protected_contract(
            part_contract,
            plan,
            snapshot,
            target_p_index="p0",
            expected_material_ids=ids,
            policy=load_material_protected_policy(POLICY_PATH),
        )


def test_valid_orthogonal_maps_pass(tmp_path: Path) -> None:
    policy, _snapshot, contract = _contract()
    paths = _write_arrays(tmp_path, _valid_arrays(contract["outputs"]["material"]["resolution"]))
    report = _evaluate(contract, policy, paths)
    assert report["summary"]["passed"] is True
    assert report["summary"]["orthogonality_exact"] is True
    assert all(value == 0 for value in report["orthogonality"].values())


def test_all_16_material_ids_and_four_protected_classes_pass(tmp_path: Path) -> None:
    policy, _snapshot, contract = _contract(expected_material_ids=list(range(1, 16)))
    paths = _write_arrays(
        tmp_path, _all_material_arrays(contract["outputs"]["material"]["resolution"])
    )
    report = _evaluate(contract, policy, paths)
    assert report["summary"]["passed"] is True
    assert report["observed_material_ids"] == list(range(16))
    assert report["observed_protected_ids"] == [0, 50, 51, 52, 53]


def test_clothing_keeps_body_part_and_clothing_material(tmp_path: Path) -> None:
    policy, _snapshot, contract = _contract(expected_material_ids=[7])
    arrays = {
        name: np.zeros((768, 768), dtype=np.uint16)
        for name in ("material", "protected", "part", "instance")
    }
    arrays["material"][100:400, 100:400] = 7
    arrays["part"][100:400, 100:400] = 36
    arrays["instance"][100:400, 100:400] = 1
    paths = _write_arrays(tmp_path, arrays)
    report = _evaluate(contract, policy, paths)
    assert report["summary"]["passed"] is True
    assert 36 not in report["observed_material_ids"]


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda a: a["material"].__setitem__((100, 100), 0), "MATERIAL_VISIBLE_UNLABELED"),
        (lambda a: a["material"].__setitem__((0, 0), 1), "MATERIAL_ORPHAN_PIXEL"),
        (lambda a: a["part"].__setitem__((500, 500), 2), "MATERIAL_PROTECTED_PART_MISMATCH"),
        (lambda a: a["part"].__setitem__((100, 100), 0), "MATERIAL_PERSON_PART_INVALID"),
        (lambda a: a["protected"].__setitem__((350, 100), 0), "MATERIAL_OTHER_PERSON_MISMATCH"),
        (lambda a: a["protected"].__setitem__((100, 100), 50), "MATERIAL_TARGET_OTHER_PERSON"),
        (lambda a: a["material"].__setitem__((500, 500), 1), "MATERIAL_PROTECTED_RELATION_INVALID"),
        (
            lambda a: a["material"].__setitem__((100, 100), 13),
            "MATERIAL_RELATION_PROTECTED_INVALID",
        ),
    ],
)
def test_each_orthogonality_equation_detects_seeded_defect(
    tmp_path: Path, mutate, code: str
) -> None:
    policy, _snapshot, contract = _contract()
    arrays = _valid_arrays(contract["outputs"]["material"]["resolution"])
    mutate(arrays)
    paths = _write_arrays(tmp_path, arrays)
    assert code in _codes(_evaluate(contract, policy, paths))


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
    paths = _write_arrays(tmp_path, _valid_arrays(contract["outputs"]["material"]["resolution"]))
    execution = _execution(contract, paths)
    execution[field] = "0" * 64
    assert "MATERIAL_SCENE_STATE_MUTATION" in _codes(_evaluate(contract, policy, paths, execution))


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
    paths = _write_arrays(tmp_path, _valid_arrays(contract["outputs"]["material"]["resolution"]))
    execution = _execution(contract, paths)
    execution["outputs"]["material"]["effects"] = [effect]
    assert "MATERIAL_EFFECT_FORBIDDEN" in _codes(_evaluate(contract, policy, paths, execution))


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda e: e.__setitem__("sidecar_plan_sha256", "0" * 64),
            "MATERIAL_SIDECAR_PLAN_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_contract_sha256", "0" * 64),
            "MATERIAL_SIDECAR_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_ontology_snapshot_sha256", "0" * 64),
            "MATERIAL_SIDECAR_ONTOLOGY_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_mapping_sha256", "0" * 64),
            "MATERIAL_SIDECAR_MAPPING_MISMATCH",
        ),
        (lambda e: e.__setitem__("part_file_sha256", "0" * 64), "MATERIAL_AUTHORITY_HASH_MISMATCH"),
        (
            lambda e: e.__setitem__("instance_file_sha256", "0" * 64),
            "MATERIAL_AUTHORITY_HASH_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("repeated_material_file_sha256", "0" * 64),
            "MATERIAL_SEMANTIC_REPLAY_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("repeated_protected_file_sha256", "0" * 64),
            "PROTECTED_SEMANTIC_REPLAY_MISMATCH",
        ),
        (
            lambda e: e["outputs"]["material"].__setitem__("decode_filter", "bilinear"),
            "MATERIAL_OUTPUT_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e["outputs"]["material"].__setitem__("file_sha256", "0" * 64),
            "MATERIAL_FILE_HASH_MISMATCH",
        ),
        (
            lambda e: e["outputs"]["material"].__setitem__("bytes", 1),
            "MATERIAL_BYTE_COUNT_MISMATCH",
        ),
        (
            lambda e: e["outputs"]["material"].__setitem__("completed", False),
            "MATERIAL_OUTPUT_INCOMPLETE",
        ),
    ],
)
def test_sidecar_output_and_replay_drift(tmp_path: Path, mutation, code: str) -> None:
    policy, _snapshot, contract = _contract()
    paths = _write_arrays(tmp_path, _valid_arrays(contract["outputs"]["material"]["resolution"]))
    execution = _execution(contract, paths)
    mutation(execution)
    assert code in _codes(_evaluate(contract, policy, paths, execution))


def test_material_only_engineering_execution_passes(tmp_path: Path) -> None:
    policy, _snapshot, contract = _contract("engineering_minimal", [1, 2, 7])
    arrays = _valid_arrays(contract["outputs"]["material"]["resolution"])
    arrays["protected"].fill(0)
    arrays["material"][arrays["material"] == 9] = 7
    arrays["material"][arrays["material"] == 13] = 1
    arrays["material"][arrays["material"] == 14] = 1
    arrays["part"][np.isin(arrays["part"], [50, 51, 52, 53])] = 2
    arrays["instance"][(arrays["part"] == 2) & (arrays["material"] > 0)] = 1
    paths = _write_arrays(tmp_path, arrays, protected=False)
    report = _evaluate(contract, policy, paths)
    assert report["summary"]["passed"] is True
    assert report["summary"]["protected_required"] is False


def test_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    _policy, _snapshot, contract = _contract()
    target, published = publish_material_protected_document(contract, tmp_path)
    assert published is True
    assert publish_material_protected_document(contract, tmp_path) == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(MaterialProtectedContractError, match="material_publication_conflict"):
        publish_material_protected_document(contract, tmp_path)


def test_cli_contract_and_validation_are_idempotent(tmp_path: Path) -> None:
    state, _pass_policy, plan = _plan("training_standard")
    snapshot = build_v1_ontology_snapshot(ONTOLOGY)
    active_part = [row["id"] for row in snapshot["part_labels"] if row["enabled"]]
    part_contract = build_part_pass_contract(
        state,
        plan,
        snapshot,
        _mapping(state, snapshot, active_part),
        [1, 2, 36, 50, 51, 52, 53],
        load_part_pass_policy(PART_POLICY),
    )
    documents = {
        "part_contract": part_contract,
        "plan": plan,
        "snapshot": snapshot,
        "expected": [1, 2, 7, 9, 13, 14],
    }
    paths: dict[str, Path] = {}
    for name, document in documents.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    contract_output = tmp_path / "contracts"
    arguments = [
        "daz",
        "recipes",
        "plan-material-protected",
        "--part-contract",
        str(paths["part_contract"]),
        "--pass-plan",
        str(paths["plan"]),
        "--ontology-snapshot",
        str(paths["snapshot"]),
        "--target-p-index",
        "p0",
        "--expected-material-ids",
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
    (tmp_path / "maps").mkdir()
    image_paths = _write_arrays(
        tmp_path / "maps", _valid_arrays(contract["outputs"]["material"]["resolution"])
    )
    execution_path = tmp_path / "execution.json"
    execution_path.write_text(json.dumps(_execution(contract, image_paths)), encoding="utf-8")
    report_output = tmp_path / "reports"
    validate = [
        "daz",
        "recipes",
        "validate-material-protected",
        "--contract",
        str(contract_path),
        "--execution",
        str(execution_path),
        "--material-image",
        str(image_paths["material"]),
        "--protected-image",
        str(image_paths["protected"]),
        "--part-image",
        str(image_paths["part"]),
        "--instance-image",
        str(image_paths["instance"]),
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
