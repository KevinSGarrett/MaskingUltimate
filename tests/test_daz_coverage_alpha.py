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
    CoverageAlphaContractError,
    build_coverage_alpha_contract,
    build_hair_alpha_certificate,
    build_material_protected_contract,
    build_part_pass_contract,
    evaluate_coverage_alpha,
    load_coverage_alpha_policy,
    load_material_protected_policy,
    load_part_pass_policy,
    publish_coverage_alpha_document,
    resolve_visible_coverage_owner,
    validate_coverage_alpha_policy,
)
from test_daz_part_pass import _mapping  # noqa: E402
from test_daz_render_pass_profiles import _plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "coverage_alpha.yaml"
MATERIAL_POLICY = ROOT / "configs" / "daz" / "material_protected_pass.yaml"
PART_POLICY = ROOT / "configs" / "daz" / "part_pass.yaml"
ONTOLOGY = ROOT / "configs" / "ontology.yaml"


def _certificate(
    policy: dict,
    construction: str = "transmapped_cards",
    mapping_sha256: str = "2" * 64,
) -> dict:
    return build_hair_alpha_certificate(
        asset_id="hair_fixture",
        asset_sha256="1" * 64,
        mapping_sha256=mapping_sha256,
        construction=construction,
        renderer_id="iray",
        renderer_version="fixture-1",
        pass_route=policy["hair"]["constructions"][construction],
        policy=policy,
    )


def _material_lineage(profile: str) -> tuple[dict, dict]:
    state, _pass_policy, plan = _plan(profile)
    snapshot = build_v1_ontology_snapshot(ONTOLOGY)
    active = [row["id"] for row in snapshot["part_labels"] if row["enabled"]]
    part_contract = build_part_pass_contract(
        state,
        plan,
        snapshot,
        _mapping(state, snapshot, active),
        [1, 2, 50, 51, 52, 53],
        load_part_pass_policy(PART_POLICY),
    )
    material_contract = build_material_protected_contract(
        part_contract,
        plan,
        snapshot,
        target_p_index="p0",
        expected_material_ids=[1, 2, 13, 14],
        policy=load_material_protected_policy(MATERIAL_POLICY),
    )
    return plan, material_contract


def _contract(
    profile: str = "training_standard",
    *,
    hair: bool = True,
    mixed: bool = True,
) -> tuple[dict, dict, dict]:
    plan, material_contract = _material_lineage(profile)
    policy = load_coverage_alpha_policy(POLICY_PATH)
    certificates = (
        [_certificate(policy, mapping_sha256=material_contract["mapping_sha256"])] if hair else []
    )
    contract = build_coverage_alpha_contract(
        material_contract,
        plan,
        certificates,
        expected_hair_material_present=hair,
        expected_mixed_coverage=mixed,
        policy=policy,
    )
    return policy, plan, contract


def _valid_arrays(resolution: list[int]) -> dict[str, np.ndarray]:
    width, height = resolution
    arrays = {
        name: np.zeros((height, width), dtype=np.uint16)
        for name in ("coverage_alpha", "material", "part", "instance")
    }
    arrays["coverage_alpha"][20:120, 20:120] = 65535
    arrays["material"][20:120, 20:120] = 1
    arrays["part"][20:120, 20:120] = 2
    arrays["instance"][20:120, 20:120] = 1
    arrays["coverage_alpha"][150:250, 150:250] = 32768
    arrays["material"][150:250, 150:250] = 2
    arrays["part"][150:250, 150:250] = 1
    arrays["instance"][150:250, 150:250] = 1
    arrays["coverage_alpha"][300:330, 300:330] = 257
    arrays["coverage_alpha"][360:390, 360:390] = 50000
    arrays["material"][360:390, 360:390] = 1
    arrays["part"][360:390, 360:390] = 2
    arrays["instance"][360:390, 360:390] = 1
    return arrays


def _write_arrays(root: Path, arrays: dict[str, np.ndarray]) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, array in arrays.items():
        path = root / f"{name}.png"
        Image.fromarray(array).save(path, format="PNG")
        paths[name] = path
    return paths


def _execution(contract: dict, paths: dict[str, Path]) -> dict:
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    alpha_bytes = paths["coverage_alpha"].stat().st_size
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
        "material_file_sha256": hashes["material"],
        "part_file_sha256": hashes["part"],
        "instance_file_sha256": hashes["instance"],
        "repeated_coverage_alpha_file_sha256": hashes["coverage_alpha"],
        "output": {
            "role": "coverage_alpha",
            "encoding": "uint16_linear_png",
            "resolution": deepcopy(contract["output"]["resolution"]),
            "crop": deepcopy(contract["output"]["crop"]),
            "color_space": "linear",
            "downsample_filter": "box_linear",
            "effects": [],
            "file_sha256": hashes["coverage_alpha"],
            "bytes": alpha_bytes,
            "completed": True,
            "interrupted": False,
        },
    }


def _evaluate(
    contract: dict,
    policy: dict,
    paths: dict[str, Path],
    execution: dict | None = None,
) -> dict:
    return evaluate_coverage_alpha(
        contract,
        execution or _execution(contract, paths),
        alpha_path=paths["coverage_alpha"],
        material_path=paths["material"],
        part_path=paths["part"],
        instance_path=paths["instance"],
        policy=policy,
    )


def _codes(report: dict) -> set[str]:
    return set(report["summary"]["failure_codes"])


def _candidate(owner: int, coverage: float, depth: float, node: str) -> dict:
    return {
        "owner_id": owner,
        "visible_opacity_samples": [coverage] * 16,
        "frontmost_depth": depth,
        "stable_node_id": node,
    }


def test_policy_separates_visibility_and_binary_thresholds() -> None:
    policy = load_coverage_alpha_policy(POLICY_PATH)
    validate_coverage_alpha_policy(policy)
    assert policy["boundary"]["visibility_threshold"] == 1 / 255
    assert policy["boundary"]["minimum_nonzero_code"] == 257
    assert policy["boundary"]["binary_ownership_threshold"] == 0.5
    assert policy["boundary"]["hard_owner_minimum_code"] == 32768


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p.__setitem__("policy_version", "2.0.0"), "identity"),
        (lambda p: p["eligible_profiles"].append("engineering_minimal"), "profiles"),
        (lambda p: p["codec"].__setitem__("color_space", "srgb"), "codec"),
        (lambda p: p["boundary"].__setitem__("binary_ownership_threshold", 0.49), "boundary"),
        (lambda p: p["hair"].__setitem__("canonical_material_id", 1), "hair"),
        (
            lambda p: p["freeze"].__setitem__("repeated_coverage_alpha_hash_required", False),
            "freeze",
        ),
    ],
)
def test_closed_policy_drift_fails(mutation, reason: str) -> None:
    policy = load_coverage_alpha_policy(POLICY_PATH)
    mutation(policy)
    with pytest.raises(CoverageAlphaContractError, match=f"alpha_policy_{reason}_invalid"):
        validate_coverage_alpha_policy(policy)


@pytest.mark.parametrize(
    "construction",
    ["polygonal", "transmapped_cards", "strand_based", "fibermesh", "mixed"],
)
def test_each_hair_construction_seals_exact_route(construction: str) -> None:
    policy = load_coverage_alpha_policy(POLICY_PATH)
    certificate = _certificate(policy, construction)
    assert certificate["pass_route"] == policy["hair"]["constructions"][construction]
    assert certificate["binary_ownership_threshold"] == 0.5
    assert certificate["shadow_ownership_forbidden"] is True


def test_wrong_hair_route_fails() -> None:
    policy = load_coverage_alpha_policy(POLICY_PATH)
    with pytest.raises(CoverageAlphaContractError, match="alpha_certificate_route_invalid"):
        build_hair_alpha_certificate(
            asset_id="hair",
            asset_sha256="1" * 64,
            mapping_sha256="2" * 64,
            construction="transmapped_cards",
            renderer_id="iray",
            renderer_version="fixture",
            pass_route="ordinary_depth_visibility",
            policy=policy,
        )


@pytest.mark.parametrize(
    ("coverage", "owner", "code"),
    [
        (0.0, 0, 0),
        (1 / 65535, 0, 0),
        (1 / 255, 0, 257),
        (0.49999, 0, 32767),
        (0.5, 7, 32768),
        (1.0, 7, 65535),
    ],
)
def test_owner_resolution_exact_thresholds(coverage: float, owner: int, code: int) -> None:
    policy = load_coverage_alpha_policy(POLICY_PATH)
    result = resolve_visible_coverage_owner([_candidate(7, coverage, 1.0, "node")], policy)
    assert result["hard_owner_id"] == owner
    assert result["coverage_u16"] == code


def test_owner_resolution_uses_coverage_then_depth_then_node() -> None:
    policy = load_coverage_alpha_policy(POLICY_PATH)
    assert (
        resolve_visible_coverage_owner(
            [_candidate(1, 0.4, 1, "a"), _candidate(2, 0.6, 2, "b")], policy
        )["hard_owner_id"]
        == 2
    )
    assert (
        resolve_visible_coverage_owner(
            [_candidate(1, 0.5, 2, "a"), _candidate(2, 0.5, 1, "b")], policy
        )["hard_owner_id"]
        == 2
    )
    assert (
        resolve_visible_coverage_owner(
            [_candidate(1, 0.5, 1, "b"), _candidate(2, 0.5, 1, "a")], policy
        )["hard_owner_id"]
        == 2
    )


def test_owner_resolution_rejects_impossible_visibility_sum() -> None:
    policy = load_coverage_alpha_policy(POLICY_PATH)
    with pytest.raises(CoverageAlphaContractError, match="alpha_candidate_visibility_overflow"):
        resolve_visible_coverage_owner(
            [_candidate(1, 0.6, 1, "a"), _candidate(2, 0.5, 2, "b")], policy
        )


def test_contract_binds_hair_certificate_and_alpha_output() -> None:
    _policy, _plan_document, contract = _contract()
    assert contract["hair_part_id"] == 1
    assert contract["hair_material_id"] == 2
    assert len(contract["hair_certificates"]) == 1
    assert contract["output"]["encoding"] == "uint16_linear_png"


def test_engineering_profile_is_ineligible() -> None:
    with pytest.raises(CoverageAlphaContractError, match="alpha_plan_lineage_invalid"):
        _contract("engineering_minimal")


def test_visible_hair_requires_certificate() -> None:
    policy = load_coverage_alpha_policy(POLICY_PATH)
    plan, material_contract = _material_lineage("training_standard")
    with pytest.raises(CoverageAlphaContractError, match="alpha_visible_hair_certificate_missing"):
        build_coverage_alpha_contract(
            material_contract,
            plan,
            [],
            expected_hair_material_present=True,
            expected_mixed_coverage=True,
            policy=policy,
        )


def test_hair_certificate_must_match_scene_mapping() -> None:
    policy = load_coverage_alpha_policy(POLICY_PATH)
    plan, material_contract = _material_lineage("training_standard")
    with pytest.raises(CoverageAlphaContractError, match="alpha_certificate_mapping_mismatch"):
        build_coverage_alpha_contract(
            material_contract,
            plan,
            [_certificate(policy, mapping_sha256="f" * 64)],
            expected_hair_material_present=True,
            expected_mixed_coverage=True,
            policy=policy,
        )


def test_valid_edge_fixture_passes(tmp_path: Path) -> None:
    policy, _plan_document, contract = _contract()
    paths = _write_arrays(tmp_path, _valid_arrays(contract["output"]["resolution"]))
    report = _evaluate(contract, policy, paths)
    assert report["summary"]["passed"] is True
    assert report["metrics"]["subthreshold_support_pixels"] > 0
    assert report["metrics"]["hair_hard_pixels"] > 0


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda a: a["coverage_alpha"].__setitem__((0, 0), 1), "ALPHA_SUBVISIBILITY_NONZERO"),
        (
            lambda a: a["coverage_alpha"].__setitem__((20, 20), 32767),
            "ALPHA_HARD_OWNER_BELOW_THRESHOLD",
        ),
        (
            lambda a: a["coverage_alpha"].__setitem__((0, 0), 32768),
            "ALPHA_HARD_OWNER_MISSING",
        ),
        (lambda a: a["part"].__setitem__((150, 150), 2), "ALPHA_HAIR_SEMANTIC_MISMATCH"),
        (
            lambda a: a["coverage_alpha"].__setitem__((150, 150), 32767),
            "ALPHA_HAIR_BELOW_THRESHOLD",
        ),
    ],
)
def test_seeded_alpha_and_hair_defects_are_detected(tmp_path: Path, mutate, code: str) -> None:
    policy, _plan_document, contract = _contract()
    arrays = _valid_arrays(contract["output"]["resolution"])
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
    policy, _plan_document, contract = _contract()
    paths = _write_arrays(tmp_path, _valid_arrays(contract["output"]["resolution"]))
    execution = _execution(contract, paths)
    execution[field] = "0" * 64
    assert "ALPHA_SCENE_STATE_MUTATION" in _codes(_evaluate(contract, policy, paths, execution))


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
    policy, _plan_document, contract = _contract()
    paths = _write_arrays(tmp_path, _valid_arrays(contract["output"]["resolution"]))
    execution = _execution(contract, paths)
    execution["output"]["effects"] = [effect]
    assert "ALPHA_EFFECT_FORBIDDEN" in _codes(_evaluate(contract, policy, paths, execution))


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda e: e.__setitem__("sidecar_plan_sha256", "0" * 64), "ALPHA_SIDECAR_PLAN_MISMATCH"),
        (
            lambda e: e.__setitem__("sidecar_contract_sha256", "0" * 64),
            "ALPHA_SIDECAR_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_ontology_snapshot_sha256", "0" * 64),
            "ALPHA_SIDECAR_ONTOLOGY_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("sidecar_mapping_sha256", "0" * 64),
            "ALPHA_SIDECAR_MAPPING_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("material_file_sha256", "0" * 64),
            "ALPHA_AUTHORITY_HASH_MISMATCH",
        ),
        (
            lambda e: e.__setitem__("repeated_coverage_alpha_file_sha256", "0" * 64),
            "ALPHA_SEMANTIC_REPLAY_MISMATCH",
        ),
        (
            lambda e: e["output"].__setitem__("color_space", "srgb"),
            "ALPHA_OUTPUT_CONTRACT_MISMATCH",
        ),
        (
            lambda e: e["output"].__setitem__("file_sha256", "0" * 64),
            "ALPHA_FILE_HASH_MISMATCH",
        ),
        (lambda e: e["output"].__setitem__("bytes", 1), "ALPHA_BYTE_COUNT_MISMATCH"),
        (lambda e: e["output"].__setitem__("completed", False), "ALPHA_OUTPUT_INCOMPLETE"),
    ],
)
def test_sidecar_output_and_replay_drift(tmp_path: Path, mutation, code: str) -> None:
    policy, _plan_document, contract = _contract()
    paths = _write_arrays(tmp_path, _valid_arrays(contract["output"]["resolution"]))
    execution = _execution(contract, paths)
    mutation(execution)
    assert code in _codes(_evaluate(contract, policy, paths, execution))


def test_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    _policy, _plan_document, contract = _contract()
    target, published = publish_coverage_alpha_document(contract, tmp_path)
    assert published is True
    assert publish_coverage_alpha_document(contract, tmp_path) == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(CoverageAlphaContractError, match="alpha_publication_conflict"):
        publish_coverage_alpha_document(contract, tmp_path)


def test_cli_contract_and_validation_are_idempotent(tmp_path: Path) -> None:
    policy = load_coverage_alpha_policy(POLICY_PATH)
    plan, material_contract = _material_lineage("training_standard")
    documents = {
        "material_contract": material_contract,
        "plan": plan,
        "certificates": [_certificate(policy, mapping_sha256=material_contract["mapping_sha256"])],
    }
    paths: dict[str, Path] = {}
    for name, document in documents.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[name] = path
    contract_output = tmp_path / "contracts"
    plan_arguments = [
        "daz",
        "recipes",
        "plan-coverage-alpha",
        "--material-contract",
        str(paths["material_contract"]),
        "--pass-plan",
        str(paths["plan"]),
        "--hair-certificates",
        str(paths["certificates"]),
        "--expect-hair",
        "--expect-mixed-coverage",
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
    image_paths = _write_arrays(tmp_path / "maps", _valid_arrays(contract["output"]["resolution"]))
    execution_path = tmp_path / "execution.json"
    execution_path.write_text(json.dumps(_execution(contract, image_paths)), encoding="utf-8")
    report_output = tmp_path / "reports"
    validate_arguments = [
        "daz",
        "recipes",
        "validate-coverage-alpha",
        "--contract",
        str(contract_path),
        "--execution",
        str(execution_path),
        "--alpha-image",
        str(image_paths["coverage_alpha"]),
        "--material-image",
        str(image_paths["material"]),
        "--part-image",
        str(image_paths["part"]),
        "--instance-image",
        str(image_paths["instance"]),
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
