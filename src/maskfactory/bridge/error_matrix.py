"""Closed bridge-error decision matrix for deterministic fail-closed handling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from maskfactory.validation import canonical_document_sha256

SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "bridge_error_decision.schema.json"
MATRIX_ID = "maskfactory-bridge-error-decision-matrix-v1"
FAILURE_DOMAINS = (
    "availability",
    "compatibility",
    "capability",
    "identity",
    "transform",
    "authority",
    "trust",
    "integrity",
    "resource",
    "invariant",
)
MATRIX_FIELDS = (
    "category",
    "retryable",
    "affected_scope",
    "completion_profile_impact",
    "remediation",
    "permitted_lifecycle_transition",
    "no_fallback_reason",
)
_MATRIX: dict[str, dict[str, Any]] = {
    "availability": {
        "category": "availability",
        "retryable": True,
        "affected_scope": "request",
        "completion_profile_impact": "attempt_deferred",
        "remediation": "retry_with_backoff",
        "permitted_lifecycle_transition": "retry_pending",
        "no_fallback_reason": "fallback_route_would_bypass_declared_availability_guards",
    },
    "compatibility": {
        "category": "compatibility",
        "retryable": False,
        "affected_scope": "release",
        "completion_profile_impact": "profile_blocked",
        "remediation": "align_contract_versions",
        "permitted_lifecycle_transition": "blocked_pending_contract_alignment",
        "no_fallback_reason": "fallback_contract_version_is_not_authorized",
    },
    "capability": {
        "category": "capability",
        "retryable": False,
        "affected_scope": "consumer_adoption",
        "completion_profile_impact": "profile_ineligible",
        "remediation": "publish_required_capability_set",
        "permitted_lifecycle_transition": "blocked_pending_capability_publication",
        "no_fallback_reason": "fallback_capability_set_would_violate_declared_requirements",
    },
    "identity": {
        "category": "identity",
        "retryable": False,
        "affected_scope": "run",
        "completion_profile_impact": "profile_blocked",
        "remediation": "rebind_canonical_identity_inputs",
        "permitted_lifecycle_transition": "quarantined_pending_identity_rebind",
        "no_fallback_reason": "fallback_identity_binding_cannot_be_proven",
    },
    "transform": {
        "category": "transform",
        "retryable": False,
        "affected_scope": "request",
        "completion_profile_impact": "attempt_rejected",
        "remediation": "recompute_declared_transform_chain",
        "permitted_lifecycle_transition": "rejected_unrecoverable_request",
        "no_fallback_reason": "fallback_transform_would_break_lineage_provenance",
    },
    "authority": {
        "category": "authority",
        "retryable": False,
        "affected_scope": "release",
        "completion_profile_impact": "profile_blocked",
        "remediation": "refresh_authority_material",
        "permitted_lifecycle_transition": "invalidated_authority_state",
        "no_fallback_reason": "fallback_authority_state_is_not_permitted",
    },
    "trust": {
        "category": "trust",
        "retryable": False,
        "affected_scope": "release",
        "completion_profile_impact": "profile_blocked",
        "remediation": "rotate_and_rebind_trust_anchors",
        "permitted_lifecycle_transition": "invalidated_trust_state",
        "no_fallback_reason": "fallback_trust_anchor_is_untrusted",
    },
    "integrity": {
        "category": "integrity",
        "retryable": False,
        "affected_scope": "run",
        "completion_profile_impact": "attempt_rejected",
        "remediation": "recompute_integrity_evidence",
        "permitted_lifecycle_transition": "quarantined_pending_integrity_rebuild",
        "no_fallback_reason": "fallback_integrity_path_would_accept_unverified_bytes",
    },
    "resource": {
        "category": "resource",
        "retryable": True,
        "affected_scope": "pass",
        "completion_profile_impact": "attempt_deferred",
        "remediation": "reduce_resource_envelope_then_retry",
        "permitted_lifecycle_transition": "retry_pending_with_reduced_envelope",
        "no_fallback_reason": "fallback_resource_profile_is_not_declared_or_benchmarked",
    },
    "invariant": {
        "category": "invariant",
        "retryable": False,
        "affected_scope": "run",
        "completion_profile_impact": "profile_blocked",
        "remediation": "repair_invariant_inputs_before_resume",
        "permitted_lifecycle_transition": "quarantined_pending_invariant_repair",
        "no_fallback_reason": "fallback_would_violate_nonnegotiable_bridge_invariants",
    },
}
_FAIL_CLOSED_DECISION = {
    "category": "invariant",
    "retryable": False,
    "affected_scope": "run",
    "completion_profile_impact": "profile_blocked",
    "remediation": "halt_and_raise_operator_review",
    "permitted_lifecycle_transition": "halted_fail_closed",
    "no_fallback_reason": "unknown_or_contradictory_failure_signal_has_no_authorized_fallback",
}


def _matrix_sha256() -> str:
    payload = {
        "matrix_id": MATRIX_ID,
        "failure_domains": FAILURE_DOMAINS,
        "matrix": _MATRIX,
        "fail_closed": _FAIL_CLOSED_DECISION,
    }
    return canonical_document_sha256(payload)


def _reasons_for_contradiction(
    failure: Mapping[str, Any], expected: Mapping[str, Any]
) -> list[str]:
    claimed = failure.get("claimed_resolution")
    if claimed is None:
        return []
    if not isinstance(claimed, Mapping):
        return ["contradictory_failure_claims"]
    mismatches = [
        name
        for name in MATRIX_FIELDS
        if name in claimed and claimed.get(name) != expected.get(name)
    ]
    return ["contradictory_failure_claims"] if mismatches else []


def _normalize_failure_domains(primary: object, declared: object) -> tuple[str | None, list[str]]:
    reasons: list[str] = []
    if not isinstance(primary, str) or primary not in FAILURE_DOMAINS:
        reasons.append("unknown_failure_domain")
    if declared is None:
        return primary if isinstance(primary, str) else None, reasons
    if (
        not isinstance(declared, list)
        or not declared
        or not all(isinstance(item, str) for item in declared)
    ):
        reasons.append("contradictory_failure_domains")
        return primary if isinstance(primary, str) else None, reasons
    unknown = [item for item in declared if item not in FAILURE_DOMAINS]
    if unknown or len(set(declared)) != 1 or (isinstance(primary, str) and declared[0] != primary):
        reasons.append("contradictory_failure_domains")
    return primary if isinstance(primary, str) else None, reasons


def build_bridge_error_decision(failure: Mapping[str, Any]) -> dict[str, Any]:
    """Map bridge failures to a closed decision profile; unknowns fail closed."""
    domain, reasons = _normalize_failure_domains(
        failure.get("failure_domain"), failure.get("failure_domains")
    )
    mapped = _MATRIX.get(domain or "")
    if mapped is not None:
        reasons.extend(_reasons_for_contradiction(failure, mapped))
    decision_profile = mapped if not reasons and mapped is not None else _FAIL_CLOSED_DECISION
    reasons = sorted(set(reasons))
    resolved_domain = (
        domain if isinstance(domain, str) and domain in FAILURE_DOMAINS else "invariant"
    )
    decision = {
        "schema_version": "1.0.0",
        "record_type": "bridge_error_decision",
        "matrix_id": MATRIX_ID,
        "matrix_sha256": _matrix_sha256(),
        "failure_domain": resolved_domain,
        "status": "accepted" if not reasons else "rejected",
        "failure_code": failure.get("failure_code"),
        **decision_profile,
        "rejection_reasons": reasons,
        "decision_sha256": "",
    }
    decision["decision_sha256"] = canonical_document_sha256(
        decision, excluded_top_level_fields=("decision_sha256",)
    )
    return decision


def validate_bridge_error_decision(decision: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate decision schema, matrix bindings, and fail-closed semantics."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues = [
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(decision))
    ]
    if decision.get("matrix_id") != MATRIX_ID or decision.get("matrix_sha256") != _matrix_sha256():
        issues.append("matrix_binding_drift")
    expected = canonical_document_sha256(decision, excluded_top_level_fields=("decision_sha256",))
    if decision.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    status = decision.get("status")
    reasons = decision.get("rejection_reasons")
    if status == "accepted":
        if reasons:
            issues.append("accepted_decision_has_reasons")
        domain = decision.get("failure_domain")
        expected_profile = _MATRIX.get(domain)
        if expected_profile is None:
            issues.append("accepted_unknown_domain")
        else:
            for name in MATRIX_FIELDS:
                if decision.get(name) != expected_profile.get(name):
                    issues.append("accepted_profile_mismatch")
                    break
    elif status == "rejected":
        if not isinstance(reasons, list) or not reasons:
            issues.append("rejected_decision_requires_reasons")
        for name in MATRIX_FIELDS:
            if decision.get(name) != _FAIL_CLOSED_DECISION[name]:
                issues.append("rejected_not_fail_closed")
                break
    return tuple(sorted(set(issues)))


__all__ = [
    "FAILURE_DOMAINS",
    "MATRIX_ID",
    "build_bridge_error_decision",
    "validate_bridge_error_decision",
]
