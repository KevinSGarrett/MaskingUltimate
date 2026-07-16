from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maskfactory.cli import main  # noqa: E402
from maskfactory.daz.render import (  # noqa: E402
    SameStateReplayError,
    evaluate_same_state_replay,
    load_same_state_replay_policy,
    publish_same_state_replay_report,
    validate_same_state_replay_policy,
)
from test_daz_render_pass_profiles import _plan  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "same_state_replay.yaml"
PASS_POLICY_PATH = ROOT / "configs" / "daz" / "render_pass_profiles.yaml"


def _sha(document) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _digest(path: Path) -> tuple[str, int]:
    if path.is_file():
        payload = path.read_bytes()
        return hashlib.sha256(payload).hexdigest(), len(payload)
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
    return _sha(records), total


def _paths(root: Path, plan: dict, *, rgb_variant: str = "same") -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    result = {}
    for output in plan["outputs"]:
        role = output["role"]
        if role == "amodal_geometry":
            path = root / role
            path.mkdir()
            (path / "mesh.bin").write_bytes(b"amodal:mesh")
            (path / "facets.bin").write_bytes(b"amodal:facets")
        else:
            path = root / f"{role}.bin"
            suffix = rgb_variant if not output["semantic"] else "same"
            path.write_bytes(f"role:{role}:{suffix}".encode())
        result[role] = path
    return result


def _execution(plan: dict, paths: dict[str, Path]) -> dict:
    integer_roles = {
        output["role"] for output in plan["outputs"] if output["integer_map_rules_required"]
    }
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
                    if output["role"] in integer_roles
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
        "semantic_passes_rendered": sum(output["semantic"] for output in plan["outputs"]),
        "parent_semantic_set_sha256": None,
        "terminal_scene_state_sha256": plan["scene_state_sha256"],
    }


def _run(run_id: str, process_id: int) -> dict:
    policy = load_same_state_replay_policy(POLICY_PATH)
    return {
        "run_id": run_id,
        "process_id": process_id,
        **{
            field: hashlib.sha256(f"authority:{field}".encode()).hexdigest()
            for field in policy["authority_fields"]
        },
    }


def _fixture(tmp_path: Path, profile: str = "training_relationship"):
    _state, pass_policy, plan = _plan(profile)
    original_paths = _paths(tmp_path / "original", plan)
    replay_paths = _paths(tmp_path / "replay", plan)
    return (
        load_same_state_replay_policy(POLICY_PATH),
        pass_policy,
        plan,
        original_paths,
        replay_paths,
        _execution(plan, original_paths),
        _execution(plan, replay_paths),
        _run("run_original", 101),
        _run("run_replay", 202),
    )


def _evaluate(fixture):
    (
        policy,
        pass_policy,
        plan,
        original_paths,
        replay_paths,
        original_execution,
        replay_execution,
        original_run,
        replay_run,
    ) = fixture
    return evaluate_same_state_replay(
        plan,
        original_execution,
        replay_execution,
        original_run,
        replay_run,
        original_paths=original_paths,
        replay_paths=replay_paths,
        pass_policy=pass_policy,
        policy=policy,
    )


def _codes(report: dict) -> set[str]:
    return set(report["summary"]["failure_codes"])


def test_policy_closes_authority_independence_semantics_and_freeze() -> None:
    policy = load_same_state_replay_policy(POLICY_PATH)
    validate_same_state_replay_policy(policy)
    assert len(policy["authority_fields"]) == 8
    assert policy["semantic_replay"]["actual_files_independently_hashed"] is True
    assert policy["semantic_replay"]["rgb_outside_semantic_exactness_claim"] is True


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p.__setitem__("policy_version", "2.0.0"), "identity"),
        (lambda p: p["eligible_profiles"].pop(), "profiles"),
        (lambda p: p["authority_fields"].pop(), "authorities"),
        (
            lambda p: p["independence"].__setitem__("distinct_run_ids_required", False),
            "independence",
        ),
        (lambda p: p["semantic_replay"].__setitem__("exact_sha256_required", False), "semantics"),
        (lambda p: p["scene_freeze"].__setitem__("exact_plan_lineage_required", False), "freeze"),
        (lambda p: p["publication"].__setitem__("immutable", False), "publication"),
    ],
)
def test_closed_policy_drift_fails(mutation, reason: str) -> None:
    policy = load_same_state_replay_policy(POLICY_PATH)
    mutation(policy)
    with pytest.raises(SameStateReplayError, match=f"replay_policy_{reason}_invalid"):
        validate_same_state_replay_policy(policy)


@pytest.mark.parametrize(
    "profile",
    ["engineering_minimal", "training_standard", "training_relationship", "diagnostic_full"],
)
def test_every_semantic_profile_replays_exactly(tmp_path: Path, profile: str) -> None:
    report = _evaluate(_fixture(tmp_path, profile))
    assert report["summary"]["passed"] is True
    assert report["summary"]["semantic_hashes_byte_identical"] is True
    assert report["semantic_roles"] == [record["role"] for record in report["semantic_records"]]
    assert all(record["hash_identical"] for record in report["semantic_records"])


def test_rgb_drift_is_recorded_but_outside_semantic_exactness_claim(tmp_path: Path) -> None:
    fixture = list(_fixture(tmp_path, "training_standard"))
    replay_paths = _paths(tmp_path / "rgb_drift", fixture[2], rgb_variant="different")
    fixture[4] = replay_paths
    fixture[6] = _execution(fixture[2], replay_paths)
    report = _evaluate(tuple(fixture))
    assert report["summary"]["passed"] is True
    assert report["summary"]["semantic_hashes_byte_identical"] is True
    assert report["rgb_records"][0]["hash_identical"] is False


SEMANTIC_ROLES = [
    "instance",
    "part",
    "material",
    "protected",
    "depth",
    "normals",
    "coverage_alpha",
    "contact_pairs",
    "front_owner",
    "boundary_pairs",
    "surface",
    "facet",
    "node",
    "mapping_confidence",
    "amodal_geometry",
]


@pytest.mark.parametrize("role", SEMANTIC_ROLES)
def test_each_semantic_role_drift_is_detected(tmp_path: Path, role: str) -> None:
    fixture = _fixture(tmp_path, "diagnostic_full")
    path = fixture[4][role]
    target = path / "mesh.bin" if path.is_dir() else path
    target.write_bytes(target.read_bytes() + b":drift")
    report = _evaluate(fixture)
    assert "REPLAY_SEMANTIC_HASH_DRIFT" in _codes(report)
    assert "REPLAY_HASH_UNTRUSTED" in _codes(report)
    assert report["summary"]["semantic_hashes_byte_identical"] is False


@pytest.mark.parametrize(
    "field",
    [
        "resolved_recipe_sha256",
        "asset_snapshot_sha256",
        "runtime_snapshot_sha256",
        "script_sha256",
        "mapping_set_sha256",
        "render_profile_sha256",
        "renderer_sha256",
        "driver_fingerprint_sha256",
    ],
)
def test_each_replay_authority_drift_is_detected(tmp_path: Path, field: str) -> None:
    fixture = list(_fixture(tmp_path))
    fixture[8][field] = "0" * 64
    report = _evaluate(tuple(fixture))
    assert "REPLAY_AUTHORITY_MISMATCH" in _codes(report)
    assert report["summary"]["authorities_identical"] is False


@pytest.mark.parametrize("field", ["run_id", "process_id"])
def test_replay_run_must_be_independent(tmp_path: Path, field: str) -> None:
    fixture = list(_fixture(tmp_path))
    fixture[8][field] = fixture[7][field]
    report = _evaluate(tuple(fixture))
    assert report["summary"]["runs_independent"] is False
    assert any(code.endswith("NOT_DISTINCT") for code in _codes(report))


@pytest.mark.parametrize(
    "field",
    [
        "scene_state_before_sha256",
        "sidecar_scene_state_sha256",
        "scene_state_after_sha256",
        "annotation_restore_scene_state_sha256",
    ],
)
def test_each_pass_state_mutation_invalidates_replay(tmp_path: Path, field: str) -> None:
    fixture = list(_fixture(tmp_path))
    fixture[6]["passes"][0][field] = "0" * 64
    report = _evaluate(tuple(fixture))
    assert "REPLAY_EXECUTION_INVALID" in _codes(report)
    assert report["summary"]["scene_state_unchanged"] is False


def test_terminal_state_mutation_invalidates_replay(tmp_path: Path) -> None:
    fixture = list(_fixture(tmp_path))
    fixture[6]["terminal_scene_state_sha256"] = "0" * 64
    report = _evaluate(tuple(fixture))
    assert "REPLAY_EXECUTION_INVALID" in _codes(report)
    assert report["summary"]["scene_state_unchanged"] is False


@pytest.mark.parametrize("field", ["file_sha256", "bytes"])
def test_execution_claim_must_match_independently_hashed_file(tmp_path: Path, field: str) -> None:
    fixture = list(_fixture(tmp_path))
    fixture[6]["passes"][1][field] = "0" * 64 if field == "file_sha256" else 1
    report = _evaluate(tuple(fixture))
    assert any(
        code in _codes(report) for code in {"REPLAY_HASH_UNTRUSTED", "REPLAY_BYTES_UNTRUSTED"}
    )


def test_path_role_set_fails_closed(tmp_path: Path) -> None:
    fixture = list(_fixture(tmp_path))
    fixture[4].pop("part")
    with pytest.raises(SameStateReplayError, match="replay_path_role_set_invalid"):
        _evaluate(tuple(fixture))


def test_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    report = _evaluate(_fixture(tmp_path))
    target, published = publish_same_state_replay_report(report, tmp_path / "reports")
    assert published is True
    assert publish_same_state_replay_report(report, tmp_path / "reports") == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(SameStateReplayError, match="replay_publication_conflict"):
        publish_same_state_replay_report(report, tmp_path / "reports")


def test_cli_replay_proof_is_idempotent(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    (
        _policy,
        _pass_policy,
        plan,
        original_paths,
        replay_paths,
        original_execution,
        replay_execution,
        original_run,
        replay_run,
    ) = fixture
    documents = {
        "plan": plan,
        "original_execution": original_execution,
        "replay_execution": replay_execution,
        "original_run": original_run,
        "replay_run": replay_run,
        "original_paths": {role: str(path) for role, path in original_paths.items()},
        "replay_paths": {role: str(path) for role, path in replay_paths.items()},
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
        "prove-same-state-replay",
        "--pass-plan",
        str(paths["plan"]),
        "--original-execution",
        str(paths["original_execution"]),
        "--replay-execution",
        str(paths["replay_execution"]),
        "--original-run",
        str(paths["original_run"]),
        "--replay-run",
        str(paths["replay_run"]),
        "--original-paths",
        str(paths["original_paths"]),
        "--replay-paths",
        str(paths["replay_paths"]),
        "--pass-policy",
        str(PASS_POLICY_PATH),
        "--policy",
        str(POLICY_PATH),
        "--output",
        str(output),
    ]
    runner = CliRunner()
    first = runner.invoke(main, arguments)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["data"]["summary"]["semantic_hashes_byte_identical"] is True
    assert payload["data"]["publication"]["published"] is True
    replay = runner.invoke(main, arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
