"""Fault-injection and admission tests for additive bridge failure control."""

from __future__ import annotations

import pytest

from maskfactory.bridge.error_matrix import build_bridge_error_decision
from maskfactory.bridge.failure_control import (
    FailureControlError,
    build_failure_control_evidence,
    simulate_fault_injection,
    validate_failure_control_evidence,
)
from maskfactory.validation import canonical_document_sha256


def _circuit(*, state: str = "closed", half_open_probe_allowed: bool = False) -> dict:
    body = {
        "route_key": "mode-b/predict",
        "release_id": "mfrel_failure_control_test",
        "state": state,
        "failure_threshold": 3,
        "observation_window_ms": 60000,
        "cooldown_ms": 5000,
        "opened_at": "2026-07-19T12:00:00Z" if state != "closed" else None,
        "half_open_probe_allowed": half_open_probe_allowed,
    }
    body["evidence_sha256"] = canonical_document_sha256(
        body, excluded_top_level_fields=("evidence_sha256",)
    )
    return body


def _request(
    *,
    attempt_number: int = 1,
    maximum_attempts: int = 3,
    deadline_at: str = "2026-07-19T13:00:00Z",
    created_at: str = "2026-07-19T12:00:00Z",
    allow_cpu_fallback: bool = False,
    vram_mb: int = 8192,
) -> dict:
    return {
        "request_id": "mfareq_failure_control_00000001",
        "pass_id": "pass_predict",
        "attempt_number": attempt_number,
        "created_at": created_at,
        "deadline_at": deadline_at,
        "resource_envelope": {
            "maximum_runtime_ms": 120000,
            "maximum_queue_ms": 30000,
            "maximum_vram_mb": vram_mb,
            "maximum_ram_mb": 16384,
            "maximum_output_bytes": 50_000_000,
            "priority": "normal",
            "allow_cpu_fallback": allow_cpu_fallback,
        },
        "retry_policy": {
            "maximum_attempts": maximum_attempts,
            "retry_only_typed_transient_errors": True,
            "allow_silent_fallback": False,
        },
    }


def _route(*, vram_mb: int = 4096, device: str = "cuda") -> dict:
    return {
        "required_vram_mb": vram_mb,
        "required_ram_mb": 8192,
        "required_runtime_ms": 5000,
        "observed_queue_ms": 100,
        "required_output_bytes": 1_000_000,
        "selected_device": device,
        "signed_cpu_route_permitted": False,
    }


def _dag() -> list[dict]:
    return [
        {"pass_id": "pass_predict", "depends_on": []},
        {"pass_id": "pass_refine", "depends_on": ["pass_predict"]},
        {"pass_id": "pass_unrelated", "depends_on": []},
    ]


def _healthy_observation() -> dict:
    return {
        "at_time": "2026-07-19T12:05:00Z",
        "request": _request(),
        "route_requirements": _route(),
        "failure": {},
        "main_circuit_evidence": _circuit(state="closed"),
        "main_retry_evidence": {},
        "main_scoped_block_evidence": {},
        "fallback_attempt": {},
        "dag_passes": _dag(),
    }


def test_healthy_admission_permits_provider_without_fallback() -> None:
    evidence = build_failure_control_evidence(
        _healthy_observation(), decided_at="2026-07-19T12:05:00Z"
    )
    assert evidence["status"] == "accepted"
    assert evidence["admission"]["provider_invocation_permitted"] is True
    assert evidence["admission"]["deadline_met"] is True
    assert evidence["admission"]["resource_feasible"] is True
    assert evidence["no_silent_fallback"]["enforced"] is True
    assert evidence["no_silent_fallback"]["fallback_artifact_present"] is False
    assert evidence["retry"]["retry_permitted"] is False
    assert validate_failure_control_evidence(evidence) == ()


def test_vram_fields_are_telemetry_and_cannot_refuse_provider() -> None:
    observation = _healthy_observation()
    observation["request"] = _request(vram_mb=1)
    observation["route_requirements"] = _route(vram_mb=999_999_999)

    evidence = build_failure_control_evidence(observation, decided_at="2026-07-19T12:05:00Z")

    assert evidence["status"] == "accepted"
    assert evidence["admission"]["resource_feasible"] is True
    assert evidence["admission"]["provider_invocation_permitted"] is True
    assert validate_failure_control_evidence(evidence) == ()


@pytest.mark.parametrize(
    ("fault_kind", "domain", "retryable"),
    [
        ("outage", "availability", True),
        ("timeout", "availability", True),
        ("oom", "resource", True),
        ("incompatible_authority", "authority", False),
    ],
)
def test_fault_injection_blocks_dependents_and_forbids_fallback(
    fault_kind: str, domain: str, retryable: bool
) -> None:
    evidence = simulate_fault_injection(
        fault_kind=fault_kind,
        request=_request(attempt_number=1, maximum_attempts=3),
        route_requirements=_route(),
        dag_passes=_dag(),
        decided_at="2026-07-19T12:05:00Z",
        at_time="2026-07-19T12:05:00Z",
    )
    assert evidence["status"] == "accepted"
    assert evidence["fault_kind"] == fault_kind
    assert evidence["error_matrix_decision"]["failure_domain"] == domain
    assert evidence["error_matrix_decision"]["retryable"] is retryable
    assert evidence["admission"]["provider_invocation_permitted"] is False
    assert evidence["scoped_dag"]["scope_exact"] is True
    assert set(evidence["scoped_dag"]["blocked_pass_ids"]) == {
        "pass_predict",
        "pass_refine",
    }
    assert evidence["scoped_dag"]["continuing_pass_ids"] == ["pass_unrelated"]
    assert evidence["no_silent_fallback"]["fallback_artifact_present"] is False
    assert evidence["no_silent_fallback"]["forbidden_kinds_observed"] == []
    assert evidence["retry"]["retry_permitted"] is retryable
    assert validate_failure_control_evidence(evidence) == ()


def test_silent_fallback_artifact_is_rejected() -> None:
    observation = _healthy_observation()
    observation["failure"] = {
        "fault_kind": "outage",
        "failure_domain": "availability",
        "failure_code": "SERVICE_UNAVAILABLE",
    }
    matrix = build_bridge_error_decision(
        {
            "failure_domain": "availability",
            "failure_domains": ["availability"],
            "failure_code": "SERVICE_UNAVAILABLE",
        }
    )
    observation["main_retry_evidence"] = {
        "attempt_number": 1,
        "maximum_attempts": 3,
        "retry_only_typed_transient_errors": True,
        "allow_silent_fallback": False,
        "retry_permitted": True,
    }
    observation["main_scoped_block_evidence"] = {
        "blocked_pass_ids": ["pass_predict", "pass_refine"],
        "continuing_pass_ids": ["pass_unrelated"],
        "affected_scope": matrix["affected_scope"],
        "contains_fallback_artifact": False,
    }
    observation["fallback_attempt"] = {
        "kind": "empty_mask",
        "artifact_present": True,
        "kinds": ["empty_mask", "weaker_authority"],
    }
    evidence = build_failure_control_evidence(observation, decided_at="2026-07-19T12:05:00Z")
    assert evidence["status"] == "rejected"
    assert "silent_fallback_forbidden" in evidence["rejection_reasons"]
    assert "fallback_artifact_present" in evidence["rejection_reasons"]
    assert evidence["admission"]["provider_invocation_permitted"] is False
    assert set(evidence["no_silent_fallback"]["forbidden_kinds_observed"]) == {
        "empty_mask",
        "weaker_authority",
    }


def test_deadline_and_resource_envelope_refuse_provider() -> None:
    observation = _healthy_observation()
    observation["at_time"] = "2026-07-19T14:00:00Z"  # after deadline
    observation["route_requirements"] = _route()
    observation["route_requirements"]["required_ram_mb"] = 99999
    evidence = build_failure_control_evidence(observation, decided_at="2026-07-19T14:00:00Z")
    assert evidence["status"] == "accepted"
    assert evidence["admission"]["deadline_met"] is False
    assert evidence["admission"]["resource_feasible"] is False
    assert evidence["admission"]["provider_invocation_permitted"] is False
    assert validate_failure_control_evidence(evidence) == ()


def test_open_circuit_blocks_route_without_mask_substitution() -> None:
    observation = _healthy_observation()
    observation["main_circuit_evidence"] = _circuit(state="open")
    evidence = build_failure_control_evidence(observation, decided_at="2026-07-19T12:05:00Z")
    assert evidence["status"] == "accepted"
    assert evidence["circuit"]["state"] == "open"
    assert evidence["circuit"]["blocks_route"] is True
    assert evidence["admission"]["provider_invocation_permitted"] is False
    assert evidence["no_silent_fallback"]["fallback_artifact_present"] is False
    assert validate_failure_control_evidence(evidence) == ()


def test_scoped_block_overreach_is_rejected() -> None:
    observation = _healthy_observation()
    observation["failure"] = {
        "fault_kind": "timeout",
        "failure_domain": "availability",
        "failure_code": "TIMEOUT",
    }
    matrix = build_bridge_error_decision(
        {
            "failure_domain": "availability",
            "failure_domains": ["availability"],
            "failure_code": "TIMEOUT",
        }
    )
    observation["main_retry_evidence"] = {
        "attempt_number": 1,
        "maximum_attempts": 3,
        "retry_only_typed_transient_errors": True,
        "allow_silent_fallback": False,
        "retry_permitted": True,
    }
    observation["main_scoped_block_evidence"] = {
        "blocked_pass_ids": ["pass_predict", "pass_refine", "pass_unrelated"],
        "continuing_pass_ids": [],
        "affected_scope": matrix["affected_scope"],
        "contains_fallback_artifact": False,
    }
    evidence = build_failure_control_evidence(observation, decided_at="2026-07-19T12:05:00Z")
    assert evidence["status"] == "rejected"
    assert "scoped_block_overreach" in evidence["rejection_reasons"]
    assert evidence["admission"]["provider_invocation_permitted"] is False


def test_authority_failure_is_not_retried() -> None:
    evidence = simulate_fault_injection(
        fault_kind="incompatible_authority",
        request=_request(attempt_number=1, maximum_attempts=5),
        route_requirements=_route(),
        dag_passes=_dag(),
        decided_at="2026-07-19T12:05:00Z",
    )
    assert evidence["error_matrix_decision"]["retryable"] is False
    assert evidence["retry"]["retry_permitted"] is False
    assert evidence["admission"]["provider_invocation_permitted"] is False
    assert "pass_unrelated" in evidence["scoped_dag"]["continuing_pass_ids"]


def test_retry_budget_exhausted_disallows_further_retry() -> None:
    evidence = simulate_fault_injection(
        fault_kind="outage",
        request=_request(attempt_number=3, maximum_attempts=3),
        route_requirements=_route(),
        dag_passes=_dag(),
        decided_at="2026-07-19T12:05:00Z",
    )
    assert evidence["retry"]["retry_permitted"] is False
    assert evidence["admission"]["provider_invocation_permitted"] is False


def test_cpu_fallback_without_signed_route_is_infeasible() -> None:
    observation = _healthy_observation()
    observation["request"] = _request(allow_cpu_fallback=True)
    observation["route_requirements"] = _route(device="cpu")
    evidence = build_failure_control_evidence(observation, decided_at="2026-07-19T12:05:00Z")
    assert evidence["admission"]["resource_feasible"] is False
    assert evidence["admission"]["provider_invocation_permitted"] is False


def test_unsupported_fault_kind_raises() -> None:
    with pytest.raises(FailureControlError):
        simulate_fault_injection(
            fault_kind="mystery",
            request=_request(),
            route_requirements=_route(),
            dag_passes=_dag(),
            decided_at="2026-07-19T12:05:00Z",
        )


def test_validation_rejects_accepted_evidence_with_fallback_artifact() -> None:
    evidence = build_failure_control_evidence(
        _healthy_observation(), decided_at="2026-07-19T12:05:00Z"
    )
    tampered = dict(evidence)
    tampered["no_silent_fallback"] = {
        **evidence["no_silent_fallback"],
        "fallback_artifact_present": True,
    }
    tampered["decision_sha256"] = canonical_document_sha256(
        tampered, excluded_top_level_fields=("decision_sha256",)
    )
    issues = validate_failure_control_evidence(tampered)
    assert "accepted_with_fallback_artifact" in issues
