"""Additive receipt decision matrix for Main adoption outcomes.

This boundary does not replace the frozen adoption receipt contract. It
independently recomputes whether an adoption decision is admissible by binding
release/capability/requirements/compatibility evidence, decision-time
freshness, and executed test hashes. Unknown or missing evidence fails closed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from maskfactory.validation import canonical_document_sha256

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_adoption_decision_matrix_policy.yaml"
SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "bridge_adoption_receipt_matrix_decision.schema.json"
)
POLICY_ID = "maskfactory-bridge-adoption-receipt-matrix-v1"


class AdoptionReceiptMatrixError(ValueError):
    """Decision matrix inputs or policy are unavailable or malformed."""


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AdoptionReceiptMatrixError("adoption matrix policy is unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise AdoptionReceiptMatrixError("unexpected adoption matrix policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise AdoptionReceiptMatrixError("adoption matrix policy hash mismatch")
    checks = policy.get("required_compatibility_checks")
    codes = policy.get("reason_codes")
    if (
        not isinstance(checks, list)
        or not checks
        or len(checks) != len(set(checks))
        or not isinstance(codes, list)
        or len(codes) != len(set(codes))
    ):
        raise AdoptionReceiptMatrixError("adoption matrix policy is not closed")
    return dict(policy)


def _ordered(policy: Mapping[str, Any], reasons: list[str]) -> list[str]:
    return [code for code in policy["reason_codes"] if code in set(reasons)] or ["eligible"]


def _decision_time_valid(receipt: Mapping[str, Any], at_time: str | None) -> bool:
    if not isinstance(at_time, str):
        return False
    decided_at = receipt.get("decided_at")
    valid_until = receipt.get("valid_until")
    return (
        isinstance(decided_at, str)
        and isinstance(valid_until, str)
        and decided_at < at_time < valid_until
    )


def _prerequisite(
    name: str,
    *,
    present: bool,
    passed: bool,
    detail: str,
) -> dict[str, Any]:
    status = (
        "met"
        if present and passed
        else ("missing_external_main_evidence" if not present else "failed")
    )
    return {
        "prerequisite": name,
        "status": status,
        "detail": detail,
    }


def _check_map(receipt: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], bool]:
    rows = [row for row in receipt.get("compatibility_checks") or () if isinstance(row, Mapping)]
    names = [row.get("check") for row in rows]
    unique = len(names) == len(set(names))
    return {str(row.get("check")): row for row in rows}, unique


def _qualification_hashes(
    qualification_bundle: Mapping[str, Any] | None,
) -> tuple[dict[str, str], list[str]]:
    if not isinstance(qualification_bundle, Mapping):
        return {}, ["external_main_qualification_bundle_required"]
    hashes: dict[str, str] = {}
    reasons: list[str] = []
    rows = [
        row
        for row in qualification_bundle.get("compatibility_checks") or ()
        if isinstance(row, Mapping)
    ]
    for row in rows:
        check = row.get("check")
        execution = row.get("execution") if isinstance(row.get("execution"), Mapping) else {}
        test_ids = row.get("test_ids")
        if (
            not isinstance(check, str)
            or not isinstance(test_ids, list)
            or not test_ids
            or len(test_ids) != len(set(test_ids))
        ):
            reasons.append("required_executed_test_hashes_missing")
            continue
        if not all(
            isinstance(execution.get(field), str)
            for field in ("command_sha256", "stdout_sha256", "stderr_sha256")
        ):
            reasons.append("file_presence_only_claim")
            continue
        if not isinstance(row.get("result_sha256"), str):
            reasons.append("required_executed_test_hashes_missing")
            continue
        evidence_hash = canonical_document_sha256(
            {
                "check": check,
                "test_ids": sorted(set(test_ids)),
                "result_sha256": row.get("result_sha256"),
                "execution": {
                    "command_sha256": execution.get("command_sha256"),
                    "stdout_sha256": execution.get("stdout_sha256"),
                    "stderr_sha256": execution.get("stderr_sha256"),
                    "status": execution.get("status"),
                    "exit_code": execution.get("exit_code"),
                },
            }
        )
        if check in hashes:
            reasons.append("required_executed_test_hashes_duplicate")
            continue
        hashes[check] = evidence_hash
    return hashes, reasons


def build_adoption_receipt_matrix_decision(
    receipt: Mapping[str, Any],
    *,
    at_time: str,
    qualification_bundle: Mapping[str, Any] | None = None,
    release_publication_issues: tuple[Any, ...] | list[Any] | None = None,
    capability_decision: Mapping[str, Any] | None = None,
    consumer_requirements_admission: Mapping[str, Any] | None = None,
    compatibility_decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate Main adoption receipt against closed additive matrix rules."""
    policy = _policy()
    reasons: list[str] = []
    required_checks = set(policy["required_compatibility_checks"])
    check_by_name, checks_unique = _check_map(receipt)
    names = set(check_by_name)
    if names != required_checks:
        reasons.append("compatibility_checks_missing_or_unknown")
    if not checks_unique:
        reasons.append("compatibility_checks_duplicate")

    qualified_hashes, qualification_reasons = _qualification_hashes(qualification_bundle)
    reasons.extend(qualification_reasons)
    required_hash_rows: list[dict[str, str]] = []
    for check in sorted(required_checks):
        row = check_by_name.get(check)
        observed = row.get("evidence_sha256") if isinstance(row, Mapping) else None
        expected = qualified_hashes.get(check)
        if expected is None or observed != expected:
            reasons.append("required_executed_test_hashes_missing")
        else:
            required_hash_rows.append({"check": check, "executed_test_hash_sha256": expected})

    compatibility_failures = sorted(
        check
        for check, row in check_by_name.items()
        if isinstance(row, Mapping) and row.get("result") == "fail"
    )
    if compatibility_failures:
        reasons.append("compatibility_check_failed")

    decisions = [
        row for row in receipt.get("capability_decisions") or () if isinstance(row, Mapping)
    ]
    decision_ids = [row.get("capability_id") for row in decisions]
    if len(decision_ids) != len(set(decision_ids)):
        reasons.append("capability_decisions_duplicate")
    required_rows = [row for row in decisions if row.get("requirement_class") == "required"]
    optional_rows = [row for row in decisions if row.get("requirement_class") == "optional"]
    required_rejected = [row for row in required_rows if row.get("decision") != "accepted"]
    optional_rejected = [row for row in optional_rows if row.get("decision") != "accepted"]
    if required_rejected and receipt.get("decision") in {"adopted", "partially_adopted"}:
        reasons.append("required_capability_coverage_partial")
    if optional_rejected and receipt.get("decision") == "adopted":
        reasons.append("optional_only_blocker")

    if not _decision_time_valid(receipt, at_time):
        reasons.append("decision_time_validity_failed")

    signature = receipt.get("signature")
    if not isinstance(signature, Mapping) or not all(
        isinstance(signature.get(field), str)
        for field in ("key_id", "public_key_base64", "signed_payload_sha256", "value_base64")
    ):
        reasons.append("receipt_authentication_missing_or_malformed")

    external_prerequisites = [
        _prerequisite(
            "main_release_publication_10_01",
            present=release_publication_issues is not None,
            passed=isinstance(release_publication_issues, (list, tuple))
            and len(release_publication_issues) == 0,
            detail="requires Main executed release-publication validation output",
        ),
        _prerequisite(
            "main_capability_qualification_10_02",
            present=isinstance(capability_decision, Mapping),
            passed=isinstance(capability_decision, Mapping)
            and capability_decision.get("status") == "accepted",
            detail="requires Main route capability qualification decision",
        ),
        _prerequisite(
            "main_consumer_requirements_10_03",
            present=isinstance(consumer_requirements_admission, Mapping),
            passed=isinstance(consumer_requirements_admission, Mapping)
            and consumer_requirements_admission.get("status") == "accepted",
            detail="requires Main signed consumer requirements admission result",
        ),
        _prerequisite(
            "main_compatibility_10_04",
            present=isinstance(compatibility_decision, Mapping),
            passed=isinstance(compatibility_decision, Mapping)
            and compatibility_decision.get("compatible") is True,
            detail="requires Main compatibility decision output when produced",
        ),
        _prerequisite(
            "main_qualification_executed_test_hashes",
            present=isinstance(qualification_bundle, Mapping),
            passed=isinstance(qualification_bundle, Mapping) and not qualification_reasons,
            detail="requires Main executed compatibility test artifacts (not file-presence-only claims)",
        ),
    ]
    if any(row["status"] != "met" for row in external_prerequisites):
        reasons.append("external_main_prerequisite_unmet")

    expected = (
        "rejected"
        if compatibility_failures or required_rejected
        else ("partially_adopted" if optional_rejected else "adopted")
    )
    if receipt.get("decision") != expected:
        reasons.append("receipt_decision_matrix_disagrees")

    decision = {
        "schema_version": "1.0.0",
        "record_type": "bridge_adoption_receipt_matrix_decision",
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "receipt_adoption_id": receipt.get("adoption_id"),
        "receipt_payload_sha256": receipt.get("adoption_payload_sha256"),
        "receipt_decision": receipt.get("decision"),
        "expected_decision": expected,
        "decision_time_valid": "decision_time_validity_failed" not in reasons,
        "compatibility_failures": compatibility_failures,
        "required_executed_test_hashes": required_hash_rows,
        "external_main_adoption_prerequisites": external_prerequisites,
        "status": "accepted" if not reasons else "rejected",
        "rejection_reasons": _ordered(policy, reasons),
        "decision_sha256": "",
    }
    decision["decision_sha256"] = canonical_document_sha256(
        decision, excluded_top_level_fields=("decision_sha256",)
    )
    return decision


def validate_adoption_receipt_matrix_decision(decision: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate matrix decision shape, policy binding, and canonical hash."""
    try:
        policy = _policy()
    except AdoptionReceiptMatrixError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues = [
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(decision))
    ]
    if (
        decision.get("policy_id") != policy["policy_id"]
        or decision.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    if not set(decision.get("rejection_reasons") or ()).issubset(set(policy["reason_codes"])):
        issues.append("reason_code_drift")
    expected = canonical_document_sha256(decision, excluded_top_level_fields=("decision_sha256",))
    if decision.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    if (decision.get("status") == "accepted") != (
        decision.get("rejection_reasons") == ["eligible"]
    ):
        issues.append("decision_status_reasons")
    return tuple(sorted(set(issues)))
