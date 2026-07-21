from __future__ import annotations

from maskfactory.bridge.error_matrix import (
    FAILURE_DOMAINS,
    build_bridge_error_decision,
    validate_bridge_error_decision,
)


def test_closed_matrix_maps_each_failure_domain_deterministically() -> None:
    for domain in FAILURE_DOMAINS:
        decision = build_bridge_error_decision(
            {
                "failure_domain": domain,
                "failure_domains": [domain],
                "failure_code": f"{domain}_failure",
            }
        )
        assert decision["status"] == "accepted"
        assert decision["failure_domain"] == domain
        assert decision["category"] == domain
        assert decision["rejection_reasons"] == []
        assert validate_bridge_error_decision(decision) == ()


def test_unknown_domain_fails_closed_without_fallback() -> None:
    decision = build_bridge_error_decision(
        {"failure_domain": "untyped", "failure_domains": ["untyped"], "failure_code": "unexpected"}
    )
    assert decision["status"] == "rejected"
    assert "unknown_failure_domain" in decision["rejection_reasons"]
    assert decision["permitted_lifecycle_transition"] == "halted_fail_closed"
    assert (
        decision["no_fallback_reason"]
        == "unknown_or_contradictory_failure_signal_has_no_authorized_fallback"
    )
    assert validate_bridge_error_decision(decision) == ()


def test_contradictory_domain_combinations_fail_closed() -> None:
    decision = build_bridge_error_decision(
        {
            "failure_domain": "availability",
            "failure_domains": ["availability", "resource"],
            "failure_code": "mixed",
        }
    )
    assert decision["status"] == "rejected"
    assert "contradictory_failure_domains" in decision["rejection_reasons"]
    assert decision["permitted_lifecycle_transition"] == "halted_fail_closed"
    assert validate_bridge_error_decision(decision) == ()


def test_contradictory_claimed_resolution_fails_closed() -> None:
    decision = build_bridge_error_decision(
        {
            "failure_domain": "resource",
            "failure_domains": ["resource"],
            "claimed_resolution": {"retryable": False},
        }
    )
    assert decision["status"] == "rejected"
    assert "contradictory_failure_claims" in decision["rejection_reasons"]
    assert decision["retryable"] is False
    assert decision["permitted_lifecycle_transition"] == "halted_fail_closed"
    assert validate_bridge_error_decision(decision) == ()


def test_decision_validation_rejects_fail_open_tampering() -> None:
    decision = build_bridge_error_decision(
        {"failure_domain": "identity", "failure_domains": ["identity"]}
    )
    assert decision["status"] == "accepted"
    tampered = dict(decision)
    tampered["retryable"] = True
    tampered["decision_sha256"] = decision["decision_sha256"]
    assert "decision_hash_drift" in validate_bridge_error_decision(tampered)
