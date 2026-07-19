"""Producer failure-control admission and Main evidence conformance.

Additive MF-P6-11.07 controls:
- absolute deadline admission against trusted current time
- declared resource-envelope feasibility before provider invocation
- bounded retries only for typed transient ``error_matrix`` decisions
- validation of Main-signed circuit and scoped DAG-block evidence
- explicit no-silent-fallback (never admit empty/wrong/weaker/unqualified masks)

This module does not implement or impersonate Main's DAG controller or circuit
state machine; it only admits/refuses producer work and validates Main evidence.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from maskfactory.bridge.error_matrix import (
    build_bridge_error_decision,
    validate_bridge_error_decision,
)
from maskfactory.validation import canonical_document_sha256

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_failure_control_policy.yaml"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "bridge_failure_control_evidence.schema.json"
POLICY_ID = "maskfactory-bridge-failure-control-v1"
EXTERNAL_MAIN_DEPENDENCIES = (
    "main_circuit_breaker_execution",
    "main_scoped_dag_blocking",
    "main_retry_attempt_accounting",
    "main_signed_failure_evidence",
)


class FailureControlError(ValueError):
    """Raised when failure-control policy or inputs are unusable."""


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FailureControlError("failure control policy is unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise FailureControlError("unexpected failure control policy")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise FailureControlError("failure control policy hash mismatch")
    return dict(policy)


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        return None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, str) and item]


def _ordered_reasons(policy: Mapping[str, Any], reasons: set[str]) -> list[str]:
    return [code for code in policy["rejection_reason_codes"] if code in reasons]


def _deadline_met(request: Mapping[str, Any], at_time: str) -> bool:
    current = _utc(at_time)
    deadline = _utc(request.get("deadline_at"))
    created = _utc(request.get("created_at"))
    if current is None or deadline is None or created is None:
        return False
    return created <= current < deadline


def _resource_feasible(request: Mapping[str, Any], route: Mapping[str, Any]) -> bool:
    envelope = _mapping(request.get("resource_envelope"))
    required = (
        ("maximum_vram_mb", "required_vram_mb"),
        ("maximum_ram_mb", "required_ram_mb"),
        ("maximum_runtime_ms", "required_runtime_ms"),
        ("maximum_queue_ms", "observed_queue_ms"),
        ("maximum_output_bytes", "required_output_bytes"),
    )
    for envelope_key, route_key in required:
        limit = envelope.get(envelope_key)
        need = route.get(route_key)
        if not isinstance(limit, int) or not isinstance(need, int) or need > limit:
            return False
    if envelope.get("allow_cpu_fallback") is True and route.get("selected_device") == "cpu":
        # CPU may only be used when an explicit signed compatible route permits it.
        if route.get("signed_cpu_route_permitted") is not True:
            return False
    return True


def _dependent_pass_ids(failed_pass_id: str, dag_passes: list[Mapping[str, Any]]) -> set[str]:
    deps: dict[str, set[str]] = {}
    for row in dag_passes:
        pass_id = row.get("pass_id")
        if not isinstance(pass_id, str) or not pass_id:
            continue
        depends_on = {item for item in _strings(row.get("depends_on")) if isinstance(item, str)}
        deps[pass_id] = depends_on
    blocked = {failed_pass_id}
    changed = True
    while changed:
        changed = False
        for pass_id, depends_on in deps.items():
            if pass_id in blocked:
                continue
            if depends_on & blocked:
                blocked.add(pass_id)
                changed = True
    return blocked


def _validate_circuit(
    policy: Mapping[str, Any], circuit: Mapping[str, Any]
) -> tuple[str, bool, bool, str, set[str]]:
    if not circuit:
        return "absent", False, False, "main circuit evidence absent", {"circuit_evidence_invalid"}
    reasons: set[str] = set()
    required = set(policy["circuit_required_fields"])
    missing = [name for name in required if name not in circuit]
    state = circuit.get("state")
    if missing or state not in set(policy["circuit_states"]):
        reasons.add("circuit_evidence_invalid")
    threshold = circuit.get("failure_threshold")
    window = circuit.get("observation_window_ms")
    cooldown = circuit.get("cooldown_ms")
    if not isinstance(threshold, int) or threshold < 1:
        reasons.add("circuit_evidence_invalid")
    if not isinstance(window, int) or window < 1:
        reasons.add("circuit_evidence_invalid")
    if not isinstance(cooldown, int) or cooldown < 0:
        reasons.add("circuit_evidence_invalid")
    evidence_hash = circuit.get("evidence_sha256")
    if not isinstance(evidence_hash, str) or len(evidence_hash) != 64:
        reasons.add("circuit_evidence_invalid")
    else:
        recomputed = canonical_document_sha256(
            circuit, excluded_top_level_fields=("evidence_sha256",)
        )
        if evidence_hash != recomputed:
            reasons.add("circuit_evidence_invalid")
    blocks = state == "open" or (
        state == "half_open" and circuit.get("half_open_probe_allowed") is not True
    )
    if blocks:
        reasons.add("circuit_open_blocks_route")
    valid = "circuit_evidence_invalid" not in reasons
    detail = "circuit evidence accepted" if valid and not blocks else "circuit blocks or invalid"
    resolved_state = state if state in set(policy["circuit_states"]) else "absent"
    return str(resolved_state), bool(blocks), valid, detail, reasons


def _validate_main_retry(
    policy: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    retry_evidence: Mapping[str, Any],
    matrix: Mapping[str, Any],
) -> tuple[bool, str, set[str]]:
    if not retry_evidence:
        return False, "main retry evidence absent", {"main_retry_evidence_invalid"}
    reasons: set[str] = set()
    attempt = request.get("attempt_number")
    maximum = _mapping(request.get("retry_policy")).get("maximum_attempts")
    bounds = _mapping(policy.get("maximum_attempts_bounds"))
    if not isinstance(attempt, int) or not isinstance(maximum, int):
        reasons.add("main_retry_evidence_invalid")
    elif not (bounds.get("minimum", 1) <= attempt <= maximum <= bounds.get("maximum", 10)):
        reasons.add("main_retry_evidence_invalid")
    if retry_evidence.get("attempt_number") != attempt:
        reasons.add("main_retry_evidence_invalid")
    if retry_evidence.get("maximum_attempts") != maximum:
        reasons.add("main_retry_evidence_invalid")
    if retry_evidence.get("retry_only_typed_transient_errors") is not True:
        reasons.add("main_retry_evidence_invalid")
    if retry_evidence.get("allow_silent_fallback") is not False:
        reasons.add("silent_fallback_forbidden")
    claimed_retry = retry_evidence.get("retry_permitted")
    matrix_retryable = matrix.get("retryable") is True and matrix.get("status") == "accepted"
    budget_remaining = isinstance(attempt, int) and isinstance(maximum, int) and attempt < maximum
    expected = bool(matrix_retryable and budget_remaining)
    if claimed_retry is not expected:
        reasons.add("main_retry_evidence_invalid")
    if claimed_retry is True and not matrix_retryable:
        reasons.add("non_transient_retry_forbidden")
    if isinstance(attempt, int) and isinstance(maximum, int) and attempt >= maximum:
        if claimed_retry is True:
            reasons.add("retry_budget_exhausted")
    detail = "main retry evidence coherent" if not reasons else "main retry evidence rejected"
    return not reasons, detail, reasons


def _validate_scoped_dag(
    *,
    failed_pass_id: str,
    dag_passes: list[Mapping[str, Any]],
    scoped_evidence: Mapping[str, Any],
    matrix: Mapping[str, Any],
) -> tuple[list[str], list[str], bool, str, set[str]]:
    reasons: set[str] = set()
    if not scoped_evidence:
        return (
            [],
            [],
            False,
            "main scoped block evidence absent",
            {"main_scoped_block_evidence_invalid"},
        )
    expected_blocked = _dependent_pass_ids(failed_pass_id, dag_passes)
    claimed_blocked = set(_strings(scoped_evidence.get("blocked_pass_ids")))
    all_passes = {
        str(row.get("pass_id"))
        for row in dag_passes
        if isinstance(row.get("pass_id"), str) and row.get("pass_id")
    }
    expected_continuing = sorted(all_passes - expected_blocked)
    claimed_continuing = set(_strings(scoped_evidence.get("continuing_pass_ids")))
    if claimed_blocked - expected_blocked:
        reasons.add("scoped_block_overreach")
    if expected_blocked - claimed_blocked:
        reasons.add("scoped_block_underreach")
    if claimed_continuing != set(expected_continuing):
        reasons.add("main_scoped_block_evidence_invalid")
    if scoped_evidence.get("affected_scope") != matrix.get("affected_scope"):
        reasons.add("main_scoped_block_evidence_invalid")
    if scoped_evidence.get("contains_fallback_artifact") is True:
        reasons.add("fallback_artifact_present")
    scope_exact = not reasons
    detail = "scoped DAG block exact" if scope_exact else "scoped DAG block rejected"
    return (
        sorted(claimed_blocked),
        sorted(claimed_continuing),
        scope_exact,
        detail,
        reasons,
    )


def _fallback_kinds(policy: Mapping[str, Any], fallback: Mapping[str, Any]) -> list[str]:
    if not fallback:
        return []
    forbidden = set(policy["forbidden_fallback_kinds"])
    observed = set(_strings(fallback.get("kinds")))
    kind = fallback.get("kind")
    if isinstance(kind, str):
        observed.add(kind)
    return sorted(observed & forbidden)


def build_failure_control_evidence(
    observation: Mapping[str, Any], *, decided_at: str
) -> dict[str, Any]:
    """Build fail-closed failure-control evidence from an admission observation."""
    policy = _policy()
    reasons: set[str] = set()
    request = _mapping(observation.get("request"))
    route = _mapping(observation.get("route_requirements"))
    failure = _mapping(observation.get("failure"))
    circuit = _mapping(observation.get("main_circuit_evidence"))
    retry_evidence = _mapping(observation.get("main_retry_evidence"))
    scoped_evidence = _mapping(observation.get("main_scoped_block_evidence"))
    fallback = _mapping(observation.get("fallback_attempt"))
    dag_passes = [row for row in observation.get("dag_passes") or () if isinstance(row, Mapping)]
    at_time = observation.get("at_time")
    if not isinstance(at_time, str):
        at_time = decided_at

    fault_kind = failure.get("fault_kind")
    fault_map = _mapping(policy.get("fault_domain_map"))
    if fault_kind in fault_map:
        domain = fault_map[fault_kind]
    else:
        domain = failure.get("failure_domain")
    failure_signal_present = isinstance(domain, str) or fault_kind in fault_map
    if failure_signal_present:
        matrix = build_bridge_error_decision(
            {
                "failure_domain": domain,
                "failure_domains": (
                    [domain] if isinstance(domain, str) else failure.get("failure_domains")
                ),
                "failure_code": failure.get("failure_code"),
                "claimed_resolution": failure.get("claimed_resolution"),
            }
        )
        matrix_issues = validate_bridge_error_decision(matrix)
        if matrix.get("status") != "accepted" or matrix_issues:
            reasons.add("error_matrix_rejected")
    else:
        # Healthy admission path: no typed failure signal to classify.
        matrix = {
            "status": "accepted",
            "failure_domain": "availability",
            "retryable": False,
            "affected_scope": "request",
            "no_fallback_reason": "healthy_admission_has_no_fallback_route",
            "decision_sha256": canonical_document_sha256(
                {
                    "status": "accepted",
                    "failure_domain": "availability",
                    "retryable": False,
                    "affected_scope": "request",
                    "no_fallback_reason": "healthy_admission_has_no_fallback_route",
                }
            ),
        }

    deadline_met = _deadline_met(request, at_time)
    if not deadline_met:
        reasons.add("deadline_expired")

    resource_ok = _resource_feasible(request, route)
    if not resource_ok:
        reasons.add("resource_envelope_infeasible")

    retry_policy = _mapping(request.get("retry_policy"))
    if retry_policy.get("allow_silent_fallback") is not False:
        reasons.add("silent_fallback_forbidden")
    if retry_policy.get("retry_only_typed_transient_errors") is not True:
        reasons.add("non_transient_retry_forbidden")

    forbidden_kinds = _fallback_kinds(policy, fallback)
    fallback_present = bool(fallback) and (
        fallback.get("artifact_present") is True or bool(forbidden_kinds)
    )
    if fallback_present or forbidden_kinds:
        reasons.add("fallback_artifact_present")
        reasons.add("silent_fallback_forbidden")

    circuit_state, circuit_blocks, circuit_valid, circuit_detail, circuit_reasons = (
        _validate_circuit(policy, circuit)
    )
    reasons.update(circuit_reasons)

    if failure_signal_present or retry_evidence:
        retry_ok, retry_detail, retry_reasons = _validate_main_retry(
            policy,
            request=request,
            retry_evidence=retry_evidence,
            matrix=matrix,
        )
        reasons.update(retry_reasons)
    else:
        retry_ok, retry_detail = True, "no retry decision required for healthy admission"

    failed_pass_id = request.get("pass_id")
    if not isinstance(failed_pass_id, str) or not failed_pass_id:
        failed_pass_id = "unknown_pass"
        reasons.add("main_scoped_block_evidence_invalid")
    if failure_signal_present:
        blocked, continuing, scope_exact, scoped_detail, scoped_reasons = _validate_scoped_dag(
            failed_pass_id=failed_pass_id,
            dag_passes=dag_passes,
            scoped_evidence=scoped_evidence,
            matrix=matrix,
        )
        reasons.update(scoped_reasons)
    elif scoped_evidence:
        # Healthy path may omit scoped-block evidence; if present it must claim no blocks.
        blocked = sorted(set(_strings(scoped_evidence.get("blocked_pass_ids"))))
        continuing = sorted(set(_strings(scoped_evidence.get("continuing_pass_ids"))))
        if blocked or scoped_evidence.get("contains_fallback_artifact") is True:
            scope_exact = False
            scoped_detail = "healthy admission cannot claim blocked passes"
            scoped_reasons = {"main_scoped_block_evidence_invalid"}
            reasons.update(scoped_reasons)
        else:
            scope_exact = True
            scoped_detail = "healthy admission has no scoped DAG block"
    else:
        all_passes = sorted(
            {
                str(row.get("pass_id"))
                for row in dag_passes
                if isinstance(row.get("pass_id"), str) and row.get("pass_id")
            }
        )
        blocked, continuing, scope_exact, scoped_detail = (
            [],
            all_passes,
            True,
            ("healthy admission has no scoped DAG block"),
        )

    fault_observed = fault_kind in fault_map
    provider_permitted = (
        deadline_met
        and resource_ok
        and not circuit_blocks
        and not fallback_present
        and not fault_observed
        and matrix.get("status") == "accepted"
        and not forbidden_kinds
    )
    if not provider_permitted:
        reasons.add("provider_invocation_forbidden")

    prerequisites: list[dict[str, Any]] = []
    for name in policy["external_main_prerequisites"]:
        if name == "main_circuit_breaker_execution":
            status = "met" if circuit_valid and circuit else "missing_external_main_evidence"
            detail = circuit_detail
            if circuit and not circuit_valid:
                status = "failed"
        elif name == "main_scoped_dag_blocking":
            status = (
                "met"
                if scope_exact
                else ("missing_external_main_evidence" if not scoped_evidence else "failed")
            )
            detail = scoped_detail
        elif name == "main_retry_attempt_accounting":
            status = (
                "met"
                if retry_ok
                else ("missing_external_main_evidence" if not retry_evidence else "failed")
            )
            detail = retry_detail
        else:
            status = "met" if matrix.get("status") == "accepted" else "failed"
            detail = "error matrix decision bound"
        if status != "met":
            reasons.add("external_main_prerequisite_unmet")
        prerequisites.append({"prerequisite": name, "status": status, "detail": detail})

    attempt = request.get("attempt_number") if isinstance(request.get("attempt_number"), int) else 1
    maximum = (
        retry_policy.get("maximum_attempts")
        if isinstance(retry_policy.get("maximum_attempts"), int)
        else 1
    )
    retry_permitted = bool(
        retry_evidence.get("retry_permitted") is True
        and matrix.get("retryable") is True
        and matrix.get("status") == "accepted"
        and attempt < maximum
        and not circuit_blocks
        and deadline_met
    )

    ordered = _ordered_reasons(policy, reasons)
    integrity_failures = {
        "silent_fallback_forbidden",
        "fallback_artifact_present",
        "scoped_block_overreach",
        "scoped_block_underreach",
        "main_retry_evidence_invalid",
        "main_scoped_block_evidence_invalid",
        "circuit_evidence_invalid",
        "error_matrix_rejected",
        "non_transient_retry_forbidden",
    }
    main_evidence_complete = circuit_valid and retry_ok and scope_exact
    accepted = (
        matrix.get("status") == "accepted"
        and not fallback_present
        and not (integrity_failures & set(ordered))
        and main_evidence_complete
    )
    status = "accepted" if accepted else "rejected"
    rejection_reasons = [] if accepted else ordered

    evidence = {
        "schema_version": "1.0.0",
        "record_type": "bridge_failure_control_evidence",
        "decided_at": decided_at,
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "request_id": str(request.get("request_id") or "unknown_request"),
        "pass_id": failed_pass_id,
        "fault_kind": fault_kind if fault_kind in fault_map or fault_kind is None else None,
        "error_matrix_decision": {
            "status": matrix["status"],
            "failure_domain": matrix["failure_domain"],
            "retryable": matrix["retryable"],
            "affected_scope": matrix["affected_scope"],
            "no_fallback_reason": matrix["no_fallback_reason"],
            "decision_sha256": matrix["decision_sha256"],
        },
        "admission": {
            "deadline_met": deadline_met,
            "resource_feasible": resource_ok,
            "provider_invocation_permitted": provider_permitted,
            "detail": (
                "provider admission granted" if provider_permitted else "provider admission refused"
            ),
        },
        "retry": {
            "attempt_number": attempt,
            "maximum_attempts": maximum,
            "retry_permitted": retry_permitted,
            "retry_only_typed_transient_errors": True,
            "detail": retry_detail,
        },
        "circuit": {
            "state": circuit_state,
            "blocks_route": circuit_blocks,
            "evidence_valid": circuit_valid,
            "detail": circuit_detail,
        },
        "scoped_dag": {
            "blocked_pass_ids": blocked,
            "continuing_pass_ids": continuing,
            "scope_exact": scope_exact,
            "detail": scoped_detail,
        },
        "no_silent_fallback": {
            "allow_silent_fallback": False,
            "fallback_artifact_present": fallback_present,
            "enforced": True,
            "forbidden_kinds_observed": forbidden_kinds,
            "detail": (
                "no silent fallback artifact admitted"
                if not fallback_present
                else "silent fallback artifact refused"
            ),
        },
        "external_main_prerequisites": prerequisites,
        "status": status,
        "rejection_reasons": rejection_reasons,
        "decision_sha256": "",
    }
    evidence["decision_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("decision_sha256",)
    )
    return evidence


def validate_failure_control_evidence(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate schema, policy binding, hash, and fail-closed coherence."""
    issues: list[str] = []
    try:
        policy = _policy()
    except FailureControlError as exc:
        return (str(exc),)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    issues.extend(
        f"schema:{error.validator}"
        for error in Draft202012Validator(schema).iter_errors(dict(evidence))
    )
    if (
        evidence.get("policy_id") != policy["policy_id"]
        or evidence.get("policy_sha256") != policy["policy_sha256"]
    ):
        issues.append("policy_drift")
    expected = canonical_document_sha256(evidence, excluded_top_level_fields=("decision_sha256",))
    if evidence.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")
    allowed = set(policy["rejection_reason_codes"])
    reasons = set(_strings(evidence.get("rejection_reasons")))
    if not reasons.issubset(allowed):
        issues.append("decision_reason_code")
    if evidence.get("status") == "rejected" and not reasons:
        issues.append("decision_status_reasons")
    no_fallback = _mapping(evidence.get("no_silent_fallback"))
    if (
        no_fallback.get("allow_silent_fallback") is not False
        or no_fallback.get("enforced") is not True
    ):
        issues.append("silent_fallback_not_enforced")
    if (
        no_fallback.get("fallback_artifact_present") is True
        and evidence.get("status") == "accepted"
    ):
        issues.append("accepted_with_fallback_artifact")
    if evidence.get("admission", {}).get("provider_invocation_permitted") is True:
        if no_fallback.get("fallback_artifact_present") is True:
            issues.append("provider_permitted_with_fallback")
        if evidence.get("circuit", {}).get("blocks_route") is True:
            issues.append("provider_permitted_while_circuit_open")
        if evidence.get("admission", {}).get("deadline_met") is not True:
            issues.append("provider_permitted_after_deadline")
        if evidence.get("admission", {}).get("resource_feasible") is not True:
            issues.append("provider_permitted_with_infeasible_resources")
    matrix = _mapping(evidence.get("error_matrix_decision"))
    fault_kind = evidence.get("fault_kind")
    if matrix and fault_kind is not None:
        rebuilt = build_bridge_error_decision(
            {
                "failure_domain": matrix.get("failure_domain"),
                "failure_domains": [matrix.get("failure_domain")],
                "failure_code": "embedded",
            }
        )
        if (
            matrix.get("status") == "accepted"
            and rebuilt.get("status") == "accepted"
            and (
                matrix.get("retryable") != rebuilt.get("retryable")
                or matrix.get("affected_scope") != rebuilt.get("affected_scope")
                or matrix.get("no_fallback_reason") != rebuilt.get("no_fallback_reason")
            )
        ):
            issues.append("error_matrix_profile_drift")
    return tuple(sorted(set(issues)))


def simulate_fault_injection(
    *,
    fault_kind: str,
    request: Mapping[str, Any],
    route_requirements: Mapping[str, Any],
    dag_passes: list[Mapping[str, Any]],
    main_circuit_evidence: Mapping[str, Any] | None = None,
    decided_at: str,
    at_time: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic fault-injection observation and evaluate it."""
    policy = _policy()
    domain = _mapping(policy.get("fault_domain_map")).get(fault_kind)
    if domain is None:
        raise FailureControlError(f"unsupported fault kind: {fault_kind}")
    failed_pass_id = str(request.get("pass_id"))
    expected_blocked = sorted(_dependent_pass_ids(failed_pass_id, dag_passes))
    all_passes = sorted(
        {
            str(row.get("pass_id"))
            for row in dag_passes
            if isinstance(row.get("pass_id"), str) and row.get("pass_id")
        }
    )
    continuing = sorted(set(all_passes) - set(expected_blocked))
    matrix = build_bridge_error_decision(
        {
            "failure_domain": domain,
            "failure_domains": [domain],
            "failure_code": f"fault_{fault_kind}",
        }
    )
    attempt = int(request.get("attempt_number") or 1)
    maximum = int(_mapping(request.get("retry_policy")).get("maximum_attempts") or 1)
    retry_permitted = bool(matrix["retryable"] and attempt < maximum)
    circuit = dict(main_circuit_evidence or {})
    if not circuit:
        circuit_body = {
            "route_key": "mode-b/predict",
            "release_id": "mfrel_test",
            "state": "closed",
            "failure_threshold": 3,
            "observation_window_ms": 60000,
            "cooldown_ms": 5000,
            "opened_at": None,
            "half_open_probe_allowed": False,
        }
        circuit_body["evidence_sha256"] = canonical_document_sha256(
            circuit_body, excluded_top_level_fields=("evidence_sha256",)
        )
        circuit = circuit_body
    observation = {
        "at_time": at_time or decided_at,
        "request": dict(request),
        "route_requirements": dict(route_requirements),
        "failure": {
            "fault_kind": fault_kind,
            "failure_domain": domain,
            "failure_code": f"fault_{fault_kind}",
        },
        "main_circuit_evidence": circuit,
        "main_retry_evidence": {
            "attempt_number": attempt,
            "maximum_attempts": maximum,
            "retry_only_typed_transient_errors": True,
            "allow_silent_fallback": False,
            "retry_permitted": retry_permitted,
        },
        "main_scoped_block_evidence": {
            "blocked_pass_ids": expected_blocked,
            "continuing_pass_ids": continuing,
            "affected_scope": matrix["affected_scope"],
            "contains_fallback_artifact": False,
        },
        "fallback_attempt": {},
        "dag_passes": list(dag_passes),
    }
    return build_failure_control_evidence(observation, decided_at=decided_at)


__all__ = [
    "EXTERNAL_MAIN_DEPENDENCIES",
    "FailureControlError",
    "POLICY_ID",
    "build_failure_control_evidence",
    "simulate_fault_injection",
    "validate_failure_control_evidence",
]
