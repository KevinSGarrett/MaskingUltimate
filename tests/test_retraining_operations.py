from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.autonomy.retraining_operations import (
    DEFAULT_POLICY,
    EVIDENCE_CATEGORIES,
    POLICY_SHA256,
    RetrainingOperationsError,
    build_report,
    canonical_sha256,
    compute_pipeline_fingerprint,
    load_policy,
    validate_policy,
    verify_report,
)
from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]


def _digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def _seal(document: dict) -> dict:
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    return document


def _fingerprint(prefix: str, checkpoint: str) -> dict:
    components = {
        "code_tree": _digest(f"{prefix}-code"),
        "dataset_manifest": _digest(f"{prefix}-dataset"),
        "model_checkpoint": checkpoint,
        "training_config": _digest(f"{prefix}-config"),
    }
    gate = f"{prefix}-gate-v1"
    return {
        "gate_fingerprint": gate,
        "components": components,
        "pipeline_fingerprint": compute_pipeline_fingerprint(gate, components),
    }


def _input(*, decision: str = "promote") -> tuple[dict, dict]:
    policy = load_policy()
    old = _fingerprint("old", _digest("incumbent-checkpoint"))
    new = _fingerprint("new", _digest("challenger-checkpoint"))
    evidence = []
    for category in EVIDENCE_CATEGORIES:
        rule = policy["compatibility_rules"][category]
        scope = {
            dimension: f"{category}-{dimension}-v1" for dimension in rule["exact_scope_dimensions"]
        }
        artifact = _digest(f"{category}-artifact")
        evidence.append(
            {
                "category": category,
                "rule_id": rule["rule_id"],
                "decision": rule["decision"],
                "old_artifact_sha256": artifact,
                "new_artifact_sha256": artifact if rule["decision"] == "reuse" else None,
                "old_scope": copy.deepcopy(scope),
                "new_scope": copy.deepcopy(scope),
                "reason": "fixture exercises the frozen compatibility rule",
            }
        )
    document = {
        "schema_version": "1.0.0",
        "operation_id": "retraining-fixture-20260715",
        "observed_at": "2026-07-15T12:00:00Z",
        "policy_sha256": policy["sha256"],
        "trigger": {
            "source_queue_sha256": _digest("queue"),
            "source_outcomes_sha256": _digest("outcomes"),
            "retraining_task_sha256": _digest("task"),
            "audit_failure_count": 1,
            "new_human_correction_count": 1,
            "requested": True,
            "status": "open",
            "require_frozen_human_holdout_evaluation": True,
        },
        "fingerprints": {"old": old, "new": new},
        "training_run": {
            "status": "succeeded",
            "run_record_sha256": _digest("run"),
            "dataset_manifest_sha256": new["components"]["dataset_manifest"],
            "checkpoint_sha256": new["components"]["model_checkpoint"],
            "training_config_sha256": new["components"]["training_config"],
            "code_tree_sha256": new["components"]["code_tree"],
            "frozen_holdout_results_sha256": _digest("holdout-results"),
            "benchmark_results_sha256": _digest("benchmark-results"),
        },
        "evidence_decisions": evidence,
        "affected_strata": [
            {
                "risk_bucket": "solo_standard",
                "instance_context": "solo",
                "covered_labels": ["hair", "skin"],
                "old_certificate_sha256": _digest("old-cert-solo"),
                "outcome": "recertified",
                "new_certificate_sha256": _digest("new-cert-solo"),
                "certificate_pipeline_fingerprint": new["pipeline_fingerprint"],
                "reason": "new human-anchor certificate passed",
            },
            {
                "risk_bucket": "duo_occlusion",
                "instance_context": "duo",
                "covered_labels": ["left_hand_base", "right_hand_base"],
                "old_certificate_sha256": _digest("old-cert-duo"),
                "outcome": "residual_abstain",
                "new_certificate_sha256": None,
                "certificate_pipeline_fingerprint": None,
                "reason": "new evidence floor was not met; retain human review",
            },
        ],
        "role_decision": {
            "decision": decision,
            "candidate_key": "eomt_retrained_fixture",
            "incumbent_key": "eomt_incumbent_fixture",
            "frozen_holdout_result": "pass" if decision == "promote" else "fail",
            "benchmark_result": "pass",
            "reason": "all promotion gates passed" if decision == "promote" else "holdout failed",
        },
        "promotion_transaction": None,
        "rollback_drill": None,
    }
    if decision == "promote":
        transaction = {
            "candidate_key": "eomt_retrained_fixture",
            "incumbent_key": "eomt_incumbent_fixture",
            "certificate_sha256": _digest("promotion-certificate"),
            "registry_before_sha256": _digest("registry-before"),
            "registry_after_sha256": _digest("registry-after"),
            "serving_smoke_result": "pass",
            "serving_smoke_sha256": _digest("candidate-serving-smoke"),
            "transaction_sha256": _digest("promotion-transaction"),
        }
        document["promotion_transaction"] = transaction
        document["rollback_drill"] = {
            "promotion_transaction_sha256": transaction["transaction_sha256"],
            "registry_promoted_sha256": transaction["registry_after_sha256"],
            "registry_restored_sha256": transaction["registry_before_sha256"],
            "expected_registry_sha256": transaction["registry_before_sha256"],
            "restored_provider": "eomt_incumbent_fixture",
            "serving_smoke_result": "pass",
            "serving_smoke_sha256": _digest("incumbent-serving-smoke"),
            "rollback_record_sha256": _digest("rollback-record"),
        }
    return _seal(document), policy


def _decision(document: dict, category: str) -> dict:
    return next(row for row in document["evidence_decisions"] if row["category"] == category)


def test_frozen_policy_and_schemas_are_hash_locked_and_current() -> None:
    policy = load_policy()
    assert DEFAULT_POLICY == ROOT / "qa/governance/retraining/retraining_compatibility_v1.json"
    assert policy["sha256"] == POLICY_SHA256
    assert set(policy["compatibility_rules"]) == set(EVIDENCE_CATEGORIES)
    assert policy["authority"].startswith("pre_result_contract_only")
    for name in (
        "retraining_operations_policy",
        "retraining_operations_input",
        "retraining_operations_report",
    ):
        schema = json.loads((ROOT / f"src/maskfactory/schemas/{name}.schema.json").read_text())
        Draft202012Validator.check_schema(schema)


def test_report_proves_new_identity_scoped_reuse_abstention_promotion_and_rollback() -> None:
    document, policy = _input()
    report = build_report(document, policy=policy)
    assert validate_document(document, "retraining_operations_input") == ()
    assert validate_document(report, "retraining_operations_report") == ()
    assert report["result"] == "pass"
    assert report["old_pipeline_fingerprint"] != report["new_pipeline_fingerprint"]
    assert report["recertified_strata_count"] == 1
    assert report["residual_abstention_strata_count"] == 1
    assert report["role_decision"] == "promote" and report["rollback_result"] == "pass"
    assert (
        "no_training_promotion_serving_gold_or_tracker_completion_authority" in report["authority"]
    )


def test_rejected_challenger_retains_incumbent_without_fake_rollback() -> None:
    document, policy = _input(decision="reject")
    report = build_report(document, policy=policy)
    assert report["role_decision"] == "reject"
    assert report["rollback_result"] == "not_applicable_rejected"


def test_report_and_input_tamper_are_detected() -> None:
    document, policy = _input()
    report = build_report(document, policy=policy)
    report["role_decision"] = "reject"
    with pytest.raises(RetrainingOperationsError, match="does not recompute exactly"):
        verify_report(report, document, policy=policy)
    document["trigger"]["audit_failure_count"] = 50
    with pytest.raises(RetrainingOperationsError, match="input hash mismatch"):
        build_report(document, policy=policy)


def test_same_or_unreproducible_fingerprint_is_rejected() -> None:
    document, policy = _input()
    document["fingerprints"]["new"] = copy.deepcopy(document["fingerprints"]["old"])
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="did not create a new"):
        build_report(document, policy=policy)
    document, policy = _input()
    document["fingerprints"]["new"]["pipeline_fingerprint"] = _digest("lie")
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="not reproducible"):
        build_report(document, policy=policy)


def test_new_fingerprint_must_bind_exact_training_outputs() -> None:
    document, policy = _input()
    document["training_run"]["checkpoint_sha256"] = _digest("other-checkpoint")
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="checkpoint_sha256"):
        build_report(document, policy=policy)


def test_below_threshold_or_non_open_trigger_is_rejected() -> None:
    document, policy = _input()
    document["trigger"]["audit_failure_count"] = 0
    document["trigger"]["new_human_correction_count"] = 0
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="not actionable"):
        build_report(document, policy=policy)
    document, policy = _input()
    document["trigger"]["status"] = "closed"
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="not actionable"):
        build_report(document, policy=policy)


@pytest.mark.parametrize(
    "category",
    [
        "human_anchor_holdout",
        "human_gold_training",
        "immutable_audit_history",
        "benchmark_observations",
    ],
)
def test_reusable_evidence_requires_exact_artifact_and_scope_identity(category: str) -> None:
    document, policy = _input()
    _decision(document, category)["new_artifact_sha256"] = _digest("changed")
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="not exact reuse"):
        build_report(document, policy=policy)
    document, policy = _input()
    row = _decision(document, category)
    dimension = next(iter(row["new_scope"]))
    row["new_scope"][dimension] = "drifted"
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="not exact reuse"):
        build_report(document, policy=policy)


@pytest.mark.parametrize(
    "category", ["autonomy_certificates", "serving_promotion_evidence", "pseudo_labels"]
)
def test_fingerprint_scoped_authority_cannot_be_rebound(category: str) -> None:
    document, policy = _input()
    _decision(document, category)["new_artifact_sha256"] = _digest("stale-rebind")
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="cannot be rebound"):
        build_report(document, policy=policy)


def test_recertification_must_use_new_fingerprint_and_abstention_has_no_certificate() -> None:
    document, policy = _input()
    document["affected_strata"][0]["certificate_pipeline_fingerprint"] = document["fingerprints"][
        "old"
    ]["pipeline_fingerprint"]
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="stale fingerprint"):
        build_report(document, policy=policy)
    document, policy = _input()
    document["affected_strata"][1]["new_certificate_sha256"] = _digest("unsafe-cert")
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="cannot carry a certificate"):
        build_report(document, policy=policy)


def test_promotion_requires_both_gates_and_exact_candidate_transaction() -> None:
    document, policy = _input()
    document["role_decision"]["benchmark_result"] = "fail"
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="lacks frozen holdout"):
        build_report(document, policy=policy)
    document, policy = _input()
    document["promotion_transaction"]["candidate_key"] = "wrong-candidate"
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="does not match role decision"):
        build_report(document, policy=policy)


@pytest.mark.parametrize(
    "field",
    [
        "promotion_transaction_sha256",
        "registry_promoted_sha256",
        "registry_restored_sha256",
        "expected_registry_sha256",
        "restored_provider",
        "serving_smoke_result",
    ],
)
def test_rollback_requires_exact_transaction_registry_provider_and_smoke(field: str) -> None:
    document, policy = _input()
    document["rollback_drill"][field] = (
        "fail"
        if field == "serving_smoke_result"
        else ("wrong-provider" if field == "restored_provider" else _digest(f"wrong-{field}"))
    )
    _seal(document)
    with pytest.raises(RetrainingOperationsError, match="rollback did not exactly restore"):
        build_report(document, policy=policy)


def test_policy_self_hash_locked_hash_and_governing_source_drift_fail(tmp_path: Path) -> None:
    policy = load_policy()
    tampered = copy.deepcopy(policy)
    tampered["trigger_thresholds"]["minimum_audit_failures"] = 9
    with pytest.raises(RetrainingOperationsError, match="policy hash mismatch"):
        validate_policy(tampered)
    _seal(tampered)
    with pytest.raises(RetrainingOperationsError, match="locked hash mismatch"):
        validate_policy(tampered)
    drift_root = tmp_path / "root"
    for relative in policy["governing_source_hashes"]:
        source = ROOT / relative
        target = drift_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    (drift_root / "configs/autonomous_masks.yaml").write_text("drift\n", encoding="utf-8")
    with pytest.raises(RetrainingOperationsError, match="governing source hash drift"):
        validate_policy(policy, root=drift_root, expected_sha256=None)


def test_cli_build_and_verify_round_trip(tmp_path: Path) -> None:
    document, _ = _input()
    input_path = tmp_path / "input.json"
    report_path = tmp_path / "report.json"
    input_path.write_text(json.dumps(document), encoding="utf-8")
    command = [
        sys.executable,
        str(ROOT / "tools/retraining_operations_report.py"),
        str(input_path),
        "--output",
        str(report_path),
        "--root",
        str(ROOT),
    ]
    built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert built.returncode == 0, built.stderr
    verified = subprocess.run(
        command + ["--verify"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert verified.returncode == 0, verified.stderr
    assert json.loads(report_path.read_text())["result"] == "pass"
