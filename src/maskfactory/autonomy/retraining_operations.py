"""Immutable, fail-closed evidence contract for trigger-driven retraining.

This module does not train or promote a model.  It recomputes whether a real
operations packet proves the complete trigger -> new fingerprint -> scoped
evidence reuse -> recertification/abstention -> promote/reject -> rollback
lifecycle required by the autonomous-gold blueprint.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY = PROJECT_ROOT / "qa/governance/retraining/retraining_compatibility_v1.json"
POLICY_SHA256 = "f02a057c45d76a5e586f1758c94e9df895e20afdaf22edf33d9cc10c13d19107"

EVIDENCE_CATEGORIES = (
    "human_anchor_holdout",
    "human_gold_training",
    "immutable_audit_history",
    "benchmark_observations",
    "autonomy_certificates",
    "serving_promotion_evidence",
    "pseudo_labels",
)
FINGERPRINT_COMPONENTS = {
    "code_tree",
    "dataset_manifest",
    "model_checkpoint",
    "training_config",
}


class RetrainingOperationsError(ValueError):
    """A retraining lifecycle packet or policy is malformed or stale."""


def canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_sha256(value: Any, field: str) -> str:
    if not _is_sha256(value):
        raise RetrainingOperationsError(f"{field} is not a lowercase SHA-256")
    return str(value)


def _require_exact_keys(value: Any, keys: set[str], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise RetrainingOperationsError(f"{field} structure is invalid")
    return value


def _verify_seal(document: Mapping[str, Any], field: str) -> None:
    claimed = _require_sha256(document.get("sha256"), f"{field}.sha256")
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if claimed != canonical_sha256(payload):
        raise RetrainingOperationsError(f"{field} hash mismatch")


def compute_pipeline_fingerprint(gate_fingerprint: str, components: Mapping[str, str]) -> str:
    """Recompute the same canonical identity shape used by autonomy calibration."""
    if not isinstance(gate_fingerprint, str) or not gate_fingerprint.strip():
        raise RetrainingOperationsError("pipeline gate fingerprint is empty")
    if set(components) != FINGERPRINT_COMPONENTS:
        raise RetrainingOperationsError("pipeline fingerprint component coverage is incomplete")
    records = []
    for name, digest in sorted(components.items()):
        records.append({"name": name, "sha256": _require_sha256(digest, name)})
    return canonical_sha256(
        {
            "schema_version": "1.0.0",
            "gate_fingerprint": gate_fingerprint,
            "components": records,
        }
    )


def validate_policy(
    policy: Mapping[str, Any],
    *,
    root: Path = PROJECT_ROOT,
    expected_sha256: str | None = POLICY_SHA256,
) -> None:
    required = {
        "schema_version",
        "policy_id",
        "authority",
        "trigger_thresholds",
        "fingerprint_components",
        "compatibility_rules",
        "role_decision",
        "rollback",
        "governing_source_hashes",
        "sha256",
    }
    _require_exact_keys(policy, required, "retraining compatibility policy")
    if (
        policy["schema_version"] != "1.0.0"
        or policy["policy_id"] != "retraining_compatibility_v1"
        or policy["authority"]
        != "pre_result_contract_only_no_training_promotion_serving_or_gold_authority"
    ):
        raise RetrainingOperationsError("retraining compatibility policy identity is invalid")
    _verify_seal(policy, "retraining compatibility policy")
    if expected_sha256 is not None and policy["sha256"] != expected_sha256:
        raise RetrainingOperationsError("retraining compatibility policy locked hash mismatch")
    thresholds = _require_exact_keys(
        policy["trigger_thresholds"],
        {"minimum_audit_failures", "minimum_new_human_corrections"},
        "trigger thresholds",
    )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in thresholds.values()
    ):
        raise RetrainingOperationsError("retraining trigger thresholds are invalid")
    if set(policy["fingerprint_components"]) != FINGERPRINT_COMPONENTS:
        raise RetrainingOperationsError("policy fingerprint component coverage is incomplete")
    rules = policy["compatibility_rules"]
    if not isinstance(rules, Mapping) or set(rules) != set(EVIDENCE_CATEGORIES):
        raise RetrainingOperationsError("compatibility rule coverage is incomplete")
    for category, rule in rules.items():
        _require_exact_keys(
            rule,
            {"rule_id", "decision", "exact_scope_dimensions", "rationale"},
            f"compatibility rule {category}",
        )
        expected = (
            "reuse"
            if category
            in {
                "human_anchor_holdout",
                "human_gold_training",
                "immutable_audit_history",
                "benchmark_observations",
            }
            else "invalidate"
        )
        if rule["decision"] != expected:
            raise RetrainingOperationsError(f"compatibility rule {category} decision is unsafe")
        if (
            not isinstance(rule["rule_id"], str)
            or not rule["rule_id"].startswith("retraining_compatibility_v1.")
            or not isinstance(rule["exact_scope_dimensions"], list)
            or not rule["exact_scope_dimensions"]
            or len(set(rule["exact_scope_dimensions"])) != len(rule["exact_scope_dimensions"])
            or not all(isinstance(item, str) and item for item in rule["exact_scope_dimensions"])
            or not isinstance(rule["rationale"], str)
            or not rule["rationale"]
        ):
            raise RetrainingOperationsError(f"compatibility rule {category} is invalid")
    _require_exact_keys(
        policy["role_decision"],
        {"require_frozen_holdout_pass", "require_benchmark_pass", "allow_residual_abstention"},
        "role decision policy",
    )
    if any(value is not True for value in policy["role_decision"].values()):
        raise RetrainingOperationsError("role decision policy is not fail closed")
    rollback = _require_exact_keys(
        policy["rollback"],
        {"required_for_promotion", "require_exact_registry_restore", "require_serving_smoke"},
        "rollback policy",
    )
    if any(value is not True for value in rollback.values()):
        raise RetrainingOperationsError("rollback policy is not fail closed")
    source_hashes = policy["governing_source_hashes"]
    if not isinstance(source_hashes, Mapping) or not source_hashes:
        raise RetrainingOperationsError("governing source hashes are absent")
    resolved_root = Path(root).resolve()
    for relative, expected in source_hashes.items():
        _require_sha256(expected, f"governing source {relative}")
        path = (resolved_root / str(relative)).resolve()
        try:
            path.relative_to(resolved_root)
        except ValueError as exc:
            raise RetrainingOperationsError("governing source escaped project root") from exc
        if not path.is_file() or file_sha256(path) != expected:
            raise RetrainingOperationsError(f"governing source hash drift: {relative}")


def load_policy(
    path: Path = DEFAULT_POLICY,
    *,
    root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise RetrainingOperationsError("retraining compatibility policy must be an object")
    validate_policy(policy, root=root)
    return policy


def _validate_fingerprint_record(value: Any, field: str) -> Mapping[str, Any]:
    record = _require_exact_keys(
        value,
        {"gate_fingerprint", "components", "pipeline_fingerprint"},
        field,
    )
    if not isinstance(record["components"], Mapping):
        raise RetrainingOperationsError(f"{field}.components is invalid")
    expected = compute_pipeline_fingerprint(record["gate_fingerprint"], record["components"])
    if record["pipeline_fingerprint"] != expected:
        raise RetrainingOperationsError(f"{field} fingerprint is not reproducible")
    return record


def _validate_input(document: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "operation_id",
        "observed_at",
        "policy_sha256",
        "trigger",
        "fingerprints",
        "training_run",
        "evidence_decisions",
        "affected_strata",
        "role_decision",
        "promotion_transaction",
        "rollback_drill",
        "sha256",
    }
    _require_exact_keys(document, required, "retraining operations input")
    _verify_seal(document, "retraining operations input")
    if (
        document["schema_version"] != "1.0.0"
        or not isinstance(document["operation_id"], str)
        or not document["operation_id"]
        or not isinstance(document["observed_at"], str)
        or not document["observed_at"].endswith("Z")
        or document["policy_sha256"] != policy["sha256"]
    ):
        raise RetrainingOperationsError("retraining operations input identity is invalid")
    trigger = _require_exact_keys(
        document["trigger"],
        {
            "source_queue_sha256",
            "source_outcomes_sha256",
            "retraining_task_sha256",
            "audit_failure_count",
            "new_human_correction_count",
            "requested",
            "status",
            "require_frozen_human_holdout_evaluation",
        },
        "trigger",
    )
    for key in ("source_queue_sha256", "source_outcomes_sha256", "retraining_task_sha256"):
        _require_sha256(trigger[key], f"trigger.{key}")
    for key in ("audit_failure_count", "new_human_correction_count"):
        if isinstance(trigger[key], bool) or not isinstance(trigger[key], int) or trigger[key] < 0:
            raise RetrainingOperationsError(f"trigger.{key} is invalid")
    thresholds = policy["trigger_thresholds"]
    threshold_met = (
        trigger["audit_failure_count"] >= thresholds["minimum_audit_failures"]
        or trigger["new_human_correction_count"] >= thresholds["minimum_new_human_corrections"]
    )
    if (
        not threshold_met
        or trigger["requested"] is not True
        or trigger["status"] != "open"
        or trigger["require_frozen_human_holdout_evaluation"] is not True
    ):
        raise RetrainingOperationsError("retraining trigger is not actionable")
    fingerprints = _require_exact_keys(document["fingerprints"], {"old", "new"}, "fingerprints")
    old = _validate_fingerprint_record(fingerprints["old"], "fingerprints.old")
    new = _validate_fingerprint_record(fingerprints["new"], "fingerprints.new")
    if old["pipeline_fingerprint"] == new["pipeline_fingerprint"]:
        raise RetrainingOperationsError("retraining did not create a new pipeline fingerprint")
    run = _require_exact_keys(
        document["training_run"],
        {
            "status",
            "run_record_sha256",
            "dataset_manifest_sha256",
            "checkpoint_sha256",
            "training_config_sha256",
            "code_tree_sha256",
            "frozen_holdout_results_sha256",
            "benchmark_results_sha256",
        },
        "training run",
    )
    if run["status"] != "succeeded":
        raise RetrainingOperationsError("retraining run did not succeed")
    for key, value in run.items():
        if key != "status":
            _require_sha256(value, f"training_run.{key}")
    binding = {
        "dataset_manifest": "dataset_manifest_sha256",
        "model_checkpoint": "checkpoint_sha256",
        "training_config": "training_config_sha256",
        "code_tree": "code_tree_sha256",
    }
    for component, run_key in binding.items():
        if new["components"][component] != run[run_key]:
            raise RetrainingOperationsError(f"new fingerprint is not bound to {run_key}")
    decisions = document["evidence_decisions"]
    if not isinstance(decisions, list) or len(decisions) != len(EVIDENCE_CATEGORIES):
        raise RetrainingOperationsError("evidence decision coverage is incomplete")
    by_category: dict[str, Mapping[str, Any]] = {}
    for row in decisions:
        decision = _require_exact_keys(
            row,
            {
                "category",
                "rule_id",
                "decision",
                "old_artifact_sha256",
                "new_artifact_sha256",
                "old_scope",
                "new_scope",
                "reason",
            },
            "evidence decision",
        )
        category = decision["category"]
        if category not in EVIDENCE_CATEGORIES or category in by_category:
            raise RetrainingOperationsError("evidence decision category is invalid or duplicated")
        by_category[str(category)] = decision
        rule = policy["compatibility_rules"][category]
        if decision["rule_id"] != rule["rule_id"] or decision["decision"] != rule["decision"]:
            raise RetrainingOperationsError(f"evidence decision {category} violates policy")
        _require_sha256(decision["old_artifact_sha256"], f"{category}.old_artifact_sha256")
        if decision["new_artifact_sha256"] is not None:
            _require_sha256(decision["new_artifact_sha256"], f"{category}.new_artifact_sha256")
        if not isinstance(decision["reason"], str) or not decision["reason"]:
            raise RetrainingOperationsError(f"evidence decision {category} lacks a reason")
        dimensions = rule["exact_scope_dimensions"]
        if (
            not isinstance(decision["old_scope"], Mapping)
            or not isinstance(decision["new_scope"], Mapping)
            or set(decision["old_scope"]) != set(dimensions)
            or set(decision["new_scope"]) != set(dimensions)
        ):
            raise RetrainingOperationsError(f"evidence decision {category} scope is incomplete")
        if rule["decision"] == "reuse":
            if (
                decision["old_artifact_sha256"] != decision["new_artifact_sha256"]
                or decision["old_scope"] != decision["new_scope"]
            ):
                raise RetrainingOperationsError(f"evidence decision {category} is not exact reuse")
        elif decision["new_artifact_sha256"] is not None:
            raise RetrainingOperationsError(f"invalidated evidence {category} cannot be rebound")
    if set(by_category) != set(EVIDENCE_CATEGORIES):
        raise RetrainingOperationsError("evidence decision coverage is incomplete")
    strata = document["affected_strata"]
    if not isinstance(strata, list) or not strata:
        raise RetrainingOperationsError("affected retraining strata are absent")
    seen: set[tuple[str, str]] = set()
    for row in strata:
        stratum = _require_exact_keys(
            row,
            {
                "risk_bucket",
                "instance_context",
                "covered_labels",
                "old_certificate_sha256",
                "outcome",
                "new_certificate_sha256",
                "certificate_pipeline_fingerprint",
                "reason",
            },
            "affected stratum",
        )
        key = (str(stratum["risk_bucket"]), str(stratum["instance_context"]))
        if (
            key in seen
            or not all(key)
            or stratum["instance_context"] not in {"solo", "duo", "small_group"}
            or not isinstance(stratum["covered_labels"], list)
            or not stratum["covered_labels"]
            or len(set(stratum["covered_labels"])) != len(stratum["covered_labels"])
        ):
            raise RetrainingOperationsError("affected stratum identity is invalid")
        seen.add(key)
        if stratum["old_certificate_sha256"] is not None:
            _require_sha256(stratum["old_certificate_sha256"], "old certificate")
        if stratum["outcome"] == "recertified":
            _require_sha256(stratum["new_certificate_sha256"], "new certificate")
            if stratum["certificate_pipeline_fingerprint"] != new["pipeline_fingerprint"]:
                raise RetrainingOperationsError("recertified stratum uses a stale fingerprint")
        elif stratum["outcome"] == "residual_abstain":
            if (
                stratum["new_certificate_sha256"] is not None
                or stratum["certificate_pipeline_fingerprint"] is not None
            ):
                raise RetrainingOperationsError("residual abstention cannot carry a certificate")
        else:
            raise RetrainingOperationsError("affected stratum outcome is invalid")
        if not isinstance(stratum["reason"], str) or not stratum["reason"]:
            raise RetrainingOperationsError("affected stratum reason is absent")
    role = _require_exact_keys(
        document["role_decision"],
        {
            "decision",
            "candidate_key",
            "incumbent_key",
            "frozen_holdout_result",
            "benchmark_result",
            "reason",
        },
        "role decision",
    )
    if (
        role["decision"] not in {"promote", "reject"}
        or not isinstance(role["candidate_key"], str)
        or not role["candidate_key"]
        or not isinstance(role["incumbent_key"], str)
        or not role["incumbent_key"]
        or role["candidate_key"] == role["incumbent_key"]
        or not isinstance(role["reason"], str)
        or not role["reason"]
    ):
        raise RetrainingOperationsError("role decision identity is invalid")
    if role["decision"] == "promote":
        if role["frozen_holdout_result"] != "pass" or role["benchmark_result"] != "pass":
            raise RetrainingOperationsError("promotion lacks frozen holdout and benchmark passes")
        transaction = _require_exact_keys(
            document["promotion_transaction"],
            {
                "candidate_key",
                "incumbent_key",
                "certificate_sha256",
                "registry_before_sha256",
                "registry_after_sha256",
                "serving_smoke_result",
                "serving_smoke_sha256",
                "transaction_sha256",
            },
            "promotion transaction",
        )
        if (
            transaction["candidate_key"] != role["candidate_key"]
            or transaction["incumbent_key"] != role["incumbent_key"]
            or transaction["serving_smoke_result"] != "pass"
        ):
            raise RetrainingOperationsError("promotion transaction does not match role decision")
        for key, value in transaction.items():
            if key not in {"candidate_key", "incumbent_key", "serving_smoke_result"}:
                _require_sha256(value, f"promotion_transaction.{key}")
        rollback = _require_exact_keys(
            document["rollback_drill"],
            {
                "promotion_transaction_sha256",
                "registry_promoted_sha256",
                "registry_restored_sha256",
                "expected_registry_sha256",
                "restored_provider",
                "serving_smoke_result",
                "serving_smoke_sha256",
                "rollback_record_sha256",
            },
            "rollback drill",
        )
        for key, value in rollback.items():
            if key not in {"restored_provider", "serving_smoke_result"}:
                _require_sha256(value, f"rollback_drill.{key}")
        if (
            rollback["promotion_transaction_sha256"] != transaction["transaction_sha256"]
            or rollback["registry_promoted_sha256"] != transaction["registry_after_sha256"]
            or rollback["registry_restored_sha256"] != transaction["registry_before_sha256"]
            or rollback["expected_registry_sha256"] != transaction["registry_before_sha256"]
            or rollback["restored_provider"] != role["incumbent_key"]
            or rollback["serving_smoke_result"] != "pass"
        ):
            raise RetrainingOperationsError("rollback did not exactly restore registry and serving")
    else:
        if document["promotion_transaction"] is not None or document["rollback_drill"] is not None:
            raise RetrainingOperationsError(
                "rejected challenger cannot carry promotion or rollback"
            )
        if role["frozen_holdout_result"] == "pass" and role["benchmark_result"] == "pass":
            raise RetrainingOperationsError(
                "rejection must record at least one failed decision gate"
            )


def build_report(
    document: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    current_policy = dict(policy) if policy is not None else load_policy(root=root)
    validate_policy(current_policy, root=root)
    _validate_input(document, current_policy)
    new_fingerprint = document["fingerprints"]["new"]["pipeline_fingerprint"]
    strata = document["affected_strata"]
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "operation_id": document["operation_id"],
        "policy_sha256": current_policy["sha256"],
        "input_sha256": document["sha256"],
        "old_pipeline_fingerprint": document["fingerprints"]["old"]["pipeline_fingerprint"],
        "new_pipeline_fingerprint": new_fingerprint,
        "reused_evidence_categories": sorted(
            row["category"] for row in document["evidence_decisions"] if row["decision"] == "reuse"
        ),
        "invalidated_evidence_categories": sorted(
            row["category"]
            for row in document["evidence_decisions"]
            if row["decision"] == "invalidate"
        ),
        "recertified_strata_count": sum(row["outcome"] == "recertified" for row in strata),
        "residual_abstention_strata_count": sum(
            row["outcome"] == "residual_abstain" for row in strata
        ),
        "role_decision": document["role_decision"]["decision"],
        "rollback_result": (
            "pass" if document["rollback_drill"] is not None else "not_applicable_rejected"
        ),
        "result": "pass",
        "authority": "verified_evidence_contract_only_no_training_promotion_serving_gold_or_tracker_completion_authority",
    }
    report["sha256"] = canonical_sha256(report)
    return report


def verify_report(
    report: Mapping[str, Any],
    document: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = PROJECT_ROOT,
) -> None:
    current_policy = dict(policy) if policy is not None else load_policy(root=root)
    expected = build_report(document, policy=current_policy, root=root)
    if dict(report) != expected:
        raise RetrainingOperationsError("retraining operations report does not recompute exactly")


__all__ = [
    "DEFAULT_POLICY",
    "EVIDENCE_CATEGORIES",
    "POLICY_SHA256",
    "RetrainingOperationsError",
    "build_report",
    "canonical_sha256",
    "compute_pipeline_fingerprint",
    "file_sha256",
    "load_policy",
    "validate_policy",
    "verify_report",
]
