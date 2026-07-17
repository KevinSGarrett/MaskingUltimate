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
from maskfactory.daz.repair_retry import (  # noqa: E402
    RepairRetryError,
    append_repair_decision,
    build_repair_request,
    load_repair_retry_policy,
    publish_repair_history,
    validate_repair_history,
    validate_repair_retry_policy,
)
from maskfactory.daz.validation_registry import (  # noqa: E402
    build_validation_set_report,
    load_validation_registry,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "daz" / "repair_retry_policy.yaml"
REGISTRY_PATH = ROOT / "configs" / "daz" / "validation_registry.yaml"


def _policy() -> dict:
    return load_repair_retry_policy(POLICY_PATH)


def _registry() -> dict:
    return load_validation_registry(REGISTRY_PATH)


def _sha(document) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _rehash_history(history: dict) -> None:
    previous = None
    for entry in history["entries"]:
        entry["previous_entry_sha256"] = previous
        entry["entry_sha256"] = _sha(
            {key: value for key, value in entry.items() if key != "entry_sha256"}
        )
        previous = entry["entry_sha256"]
    history["summary"]["latest_entry_sha256"] = previous
    content = {
        key: value
        for key, value in history.items()
        if key not in {"schema_version", "history_id", "history_sha256"}
    }
    history["history_sha256"] = _sha(content)
    history["history_id"] = f"drrh_{history['history_sha256'][:24]}"


def _result(validator_id: str, reason_code: str, retryability: str) -> dict:
    validator = next(
        row for row in _registry()["validators"] if row["validator_id"] == validator_id
    )
    return {
        "validator_id": validator_id,
        "validator_version": validator["validator_version"],
        "entity_id": "daz_scene_repair_fixture",
        "status": "fail",
        "reason_code": reason_code,
        "metric": "defect_count",
        "observed": {"defect_count": 1},
        "expected": {"operator": "eq", "value": 0},
        "evidence_paths": ["fixtures/failure.json"],
        "retryability": retryability,
        "affected_asset_ids": [],
        "affected_mapping_ids": [],
    }


def _report(validator_id: str, reason_code: str, retryability: str) -> dict:
    scope = "corpus" if validator_id == "DAZ-V9-001" else "scene"
    return build_validation_set_report(
        [_result(validator_id, reason_code, retryability)],
        entity_id="daz_scene_repair_fixture",
        scope=scope,
        registry=_registry(),
        required_validator_ids=[validator_id],
    )


def _authority() -> dict:
    return {
        "ontology_sha256": "1" * 64,
        "mapping_set_sha256": "2" * 64,
        "label_table_sha256": "3" * 64,
        "truth_tier": "synthetic_exact",
        "training_weight_sha256": "4" * 64,
        "required_validator_set_sha256": "5" * 64,
    }


CASES = {
    "CAMERA_RECENTER": (
        "DAZ-V3-001",
        "ASSEMBLY_FRAMING_INVALID",
        "adjusted_recipe",
        {"camera_target_offset_cm": [1.0, 0.0, 0.0], "distance_delta_cm": 5.0},
    ),
    "CAMERA_CLIP_PLANES": (
        "DAZ-V3-001",
        "ASSEMBLY_FRAMING_INVALID",
        "adjusted_recipe",
        {"near_plane_delta_cm": 1.0, "far_plane_delta_cm": 10.0},
    ),
    "SUPPORT_TRANSLATION": (
        "DAZ-V3-001",
        "ASSEMBLY_FIT_INVALID",
        "adjusted_recipe",
        {"construction_id": "c0", "translation_delta_cm": [0.0, 1.0, 0.0]},
    ),
    "CLOTH_HAIR_SETTLE": (
        "DAZ-V3-001",
        "ASSEMBLY_FIT_INVALID",
        "adjusted_recipe",
        {"node_id": "hair_node", "simulation_seed": 17, "cache_sha256": "6" * 64},
    ),
    "SMOOTHING_FIT_ADJUSTMENT": (
        "DAZ-V4-001",
        "GEOMETRY_PENETRATION_EXCESS",
        "adjusted_recipe",
        {"node_id": "garment_node", "adjustment_profile_id": "bounded_fit_v1"},
    ),
    "PLACEMENT_SEPARATION": (
        "DAZ-V4-001",
        "GEOMETRY_PENETRATION_EXCESS",
        "adjusted_recipe",
        {"construction_id": "c1", "translation_delta_cm": [2.0, 0.0, 0.0]},
    ),
    "CLEAN_WORKER_RERENDER": (
        "DAZ-V5-001",
        "RENDER_PROCESS_FAILED",
        "same_recipe",
        {"worker_restart_nonce": "clean-worker-001"},
    ),
    "COVERAGE_ASSET_POSE_RESAMPLE": (
        "DAZ-V9-001",
        "CORPUS_COVERAGE_DEFICIT",
        "adjusted_recipe",
        {"replacement_stream_seed": 19, "excluded_asset_ids": ["daz_asset_bad"]},
    ),
    "FULL_RECIPE_REGENERATION": (
        "DAZ-V2-001",
        "RECIPE_RANGE_INVALID",
        "adjusted_recipe",
        {"replacement_master_seed": 23},
    ),
}


def _draft(defect_code: str, *, revision: int = 0, suffix: str = "0") -> tuple[dict, dict]:
    validator, reason, retryability, delta = CASES[defect_code]
    if defect_code == "CLEAN_WORKER_RERENDER" and suffix != "0":
        delta = {"worker_restart_nonce": f"clean-worker-{suffix}"}
    report = _report(validator, reason, retryability)
    return (
        {
            "schema_version": "1.0.0",
            "demand_id": "coverage_demand_fixture",
            "entity_id": report["entity_id"],
            "parent_recipe_sha256": suffix.rjust(64, "a")[-64:],
            "parent_recipe_revision": revision,
            "validator_id": validator,
            "defect_code": defect_code,
            "proposed_delta": deepcopy(delta),
            "authority_freeze": _authority(),
        },
        report,
    )


def _request(defect_code: str, *, revision: int = 0, suffix: str = "0") -> tuple[dict, dict]:
    draft, report = _draft(defect_code, revision=revision, suffix=suffix)
    return (
        build_repair_request(draft, report, policy=_policy(), registry=_registry()),
        report,
    )


@pytest.mark.parametrize("defect_code", sorted(CASES))
def test_every_allowed_repair_is_exact_deterministic_and_revalidates(defect_code: str) -> None:
    request, report = _request(defect_code)
    first = append_repair_decision(request, report, None, policy=_policy(), registry=_registry())
    replay = append_repair_decision(request, report, None, policy=_policy(), registry=_registry())
    entry = first["entries"][0]
    assert first == replay
    assert entry["disposition"] == "scheduled"
    assert entry["full_revalidation_required"] is True
    assert entry["next_recipe_revision"] == 1
    assert entry["delta"] == request["proposed_delta"]


def test_policy_closes_all_five_blueprint_budgets_and_authority_fields() -> None:
    policy = _policy()
    validate_repair_retry_policy(policy)
    assert policy["retry_budgets"] == {
        "same_recipe_clean_rerender": 1,
        "camera_support_correction": 2,
        "cloth_hair_settle": 1,
        "asset_combination_replacement": 3,
        "full_recipe_regeneration": 5,
    }
    assert policy["authority_freeze_fields"] == list(_authority())


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p["retry_budgets"].__setitem__("same_recipe_clean_rerender", 2), "budgets"),
        (lambda p: p["authority_freeze_fields"].pop(), "authority"),
        (lambda p: p["repair_rules"]["CAMERA_RECENTER"]["delta_fields"].reverse(), "rules"),
        (lambda p: p["non_repairable_reason_codes"].reverse(), "nonrepairable"),
        (lambda p: p["publication"].__setitem__("hash_chained", False), "publication"),
    ],
)
def test_policy_drift_fails_closed(mutation, reason: str) -> None:
    policy = _policy()
    mutation(policy)
    with pytest.raises(RepairRetryError, match=f"repair_policy_{reason}_invalid"):
        validate_repair_retry_policy(policy)


def test_same_recipe_budget_exhausts_once_into_honest_coverage_deficit() -> None:
    request1, report = _request("CLEAN_WORKER_RERENDER")
    history = append_repair_decision(request1, report, None, policy=_policy(), registry=_registry())
    request2, _report2 = _request("CLEAN_WORKER_RERENDER", revision=1, suffix="2")
    history = append_repair_decision(
        request2, report, history, policy=_policy(), registry=_registry()
    )
    exhausted = history["entries"][-1]
    assert exhausted["disposition"] == "budget_exhausted"
    assert exhausted["attempt"] == 2 and exhausted["maximum_attempts"] == 1
    assert exhausted["coverage_deficit"] is True
    assert exhausted["action"] is None and exhausted["delta"] == {}
    request3, _report3 = _request("CLEAN_WORKER_RERENDER", revision=1, suffix="3")
    with pytest.raises(RepairRetryError, match="repair_budget_already_exhausted"):
        append_repair_decision(request3, report, history, policy=_policy(), registry=_registry())


def test_budgets_are_independent_per_reason_family_with_one_demand() -> None:
    request1, framing_report = _request("CAMERA_RECENTER")
    history = append_repair_decision(
        request1, framing_report, None, policy=_policy(), registry=_registry()
    )
    request2, clip_report = _request("CAMERA_CLIP_PLANES", revision=1, suffix="2")
    history = append_repair_decision(
        request2, clip_report, history, policy=_policy(), registry=_registry()
    )
    assert history["entries"][0]["reason_family"] == "framing"
    assert history["entries"][1]["reason_family"] == "camera_clip"
    assert history["entries"][1]["attempt"] == 1


def test_unknown_id_is_rejected_and_only_repeated_failure_recommends_quarantine() -> None:
    report = _report("DAZ-V6-001", "ID_UNKNOWN_VALUE", "asset_retest")
    draft, _unused = _draft("CAMERA_RECENTER")
    draft.update(
        {
            "entity_id": report["entity_id"],
            "validator_id": "DAZ-V6-001",
            "defect_code": "NON_REPAIRABLE",
            "proposed_delta": {},
        }
    )
    request = build_repair_request(draft, report, policy=_policy(), registry=_registry())
    history = append_repair_decision(request, report, None, policy=_policy(), registry=_registry())
    entry = history["entries"][0]
    assert entry["disposition"] == "rejected_nonrepairable"
    assert entry["attempt"] == 0 and entry["next_recipe_revision"] is None
    assert entry["quarantine_recommended"] is False
    draft["parent_recipe_sha256"] = "7" * 64
    request2 = build_repair_request(draft, report, policy=_policy(), registry=_registry())
    history = append_repair_decision(
        request2, report, history, policy=_policy(), registry=_registry()
    )
    assert history["entries"][-1]["quarantine_recommended"] is True


def test_nonrepairable_failure_cannot_smuggle_a_delta() -> None:
    report = _report("DAZ-V5-001", "RENDER_HASH_MISMATCH", "same_recipe")
    draft, _unused = _draft("CAMERA_RECENTER")
    draft.update(
        {
            "entity_id": report["entity_id"],
            "validator_id": "DAZ-V5-001",
            "defect_code": "NON_REPAIRABLE",
            "proposed_delta": {"worker_restart_nonce": "not-allowed"},
        }
    )
    with pytest.raises(RepairRetryError, match="nonrepairable_delta_invalid"):
        build_repair_request(draft, report, policy=_policy(), registry=_registry())


def test_delta_fields_order_ranges_and_reason_binding_are_closed() -> None:
    draft, report = _draft("CAMERA_RECENTER")
    draft["proposed_delta"] = {
        "distance_delta_cm": 5.0,
        "camera_target_offset_cm": [1.0, 0.0, 0.0],
    }
    with pytest.raises(RepairRetryError, match="repair_delta_fields_invalid"):
        build_repair_request(draft, report, policy=_policy(), registry=_registry())
    draft, report = _draft("CAMERA_RECENTER")
    draft["proposed_delta"]["distance_delta_cm"] = 1000.0
    with pytest.raises(RepairRetryError, match="repair_delta_range_invalid"):
        build_repair_request(draft, report, policy=_policy(), registry=_registry())
    draft, report = _draft("CAMERA_RECENTER")
    draft["defect_code"] = "SUPPORT_TRANSLATION"
    with pytest.raises(RepairRetryError, match="repair_request_rule_mismatch"):
        build_repair_request(draft, report, policy=_policy(), registry=_registry())


def test_authority_freeze_cannot_change_across_history() -> None:
    request1, report = _request("CAMERA_RECENTER")
    history = append_repair_decision(request1, report, None, policy=_policy(), registry=_registry())
    draft2, report2 = _draft("CAMERA_RECENTER", revision=1, suffix="2")
    draft2["authority_freeze"]["truth_tier"] = "downgraded_or_upgraded"
    request2 = build_repair_request(draft2, report2, policy=_policy(), registry=_registry())
    with pytest.raises(RepairRetryError, match="repair_history_request_lineage_invalid"):
        append_repair_decision(request2, report2, history, policy=_policy(), registry=_registry())


def test_history_hash_chain_tampering_and_parent_revision_drift_fail() -> None:
    request, report = _request("CAMERA_RECENTER")
    history = append_repair_decision(request, report, None, policy=_policy(), registry=_registry())
    tampered = deepcopy(history)
    tampered["entries"][0]["delta"]["distance_delta_cm"] = 6.0
    with pytest.raises(RepairRetryError, match="repair_document_hash_invalid"):
        validate_repair_history(tampered, policy=_policy())
    request2, report2 = _request("CAMERA_RECENTER", revision=0, suffix="2")
    with pytest.raises(RepairRetryError, match="repair_history_parent_revision_invalid"):
        append_repair_decision(request2, report2, history, policy=_policy(), registry=_registry())


def test_rehashed_attempt_tampering_still_fails_semantic_replay() -> None:
    request, report = _request("CAMERA_RECENTER")
    history = append_repair_decision(request, report, None, policy=_policy(), registry=_registry())
    tampered = deepcopy(history)
    tampered["entries"][0]["attempt"] = 2
    _rehash_history(tampered)
    with pytest.raises(RepairRetryError, match="repair_history_attempt_invalid"):
        validate_repair_history(tampered, policy=_policy())


def test_duplicate_request_and_immutable_publication_are_idempotent(tmp_path: Path) -> None:
    request, report = _request("CAMERA_RECENTER")
    history = append_repair_decision(request, report, None, policy=_policy(), registry=_registry())
    duplicate = append_repair_decision(
        request, report, history, policy=_policy(), registry=_registry()
    )
    assert duplicate == history
    target, published = publish_repair_history(history, tmp_path)
    replay_target, replay_published = publish_repair_history(history, tmp_path)
    assert target == replay_target and published is True and replay_published is False


def test_cli_seals_request_history_inputs_and_replays_idempotently(tmp_path: Path) -> None:
    draft, report = _draft("CAMERA_RECENTER")
    draft_path = tmp_path / "draft.json"
    report_path = tmp_path / "validation.json"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    output = tmp_path / "repair_history"
    arguments = [
        "daz",
        "recipes",
        "plan-repair",
        "--draft",
        str(draft_path),
        "--validation-set",
        str(report_path),
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
    assert payload["reason"] == "daz_repair_scheduled"
    assert payload["data"]["attempt"] == 1
    assert Path(payload["evidence_paths"][0]).is_file()
    input_root = output / "inputs" / payload["data"]["input_bundle_sha256"][:24]
    assert {path.name for path in input_root.glob("*.json")} == {
        "draft.json",
        "prior_history.json",
        "request.json",
        "validation_set.json",
    }
    replay = CliRunner().invoke(main, arguments)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["data"]["publication"]["published"] is False
