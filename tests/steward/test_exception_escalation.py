from __future__ import annotations

import copy
import hashlib

import pytest

from maskfactory.steward.continuous_contract import canonical_sha256
from maskfactory.steward.exception_escalation import (
    ESCALATION_CATEGORIES,
    ROUTINE_CATEGORIES,
    ExceptionEscalationError,
    evaluate_exception_escalation,
    seal_exception_event,
    validate_exception_escalation_replay,
    validate_exception_event,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _event(category: str, **overrides: bool) -> dict:
    facts = {
        "hard_failure": False,
        "internal_repair_exhausted": False,
        "external_authority_required": False,
        "terminal_decision_required": False,
    }
    if category in {
        "security_or_credentials",
        "destructive_or_external_authority",
        "authority_conflict",
    }:
        facts["external_authority_required"] = True
    if category == "repair_exhaustion":
        facts["hard_failure"] = True
        facts["internal_repair_exhausted"] = True
    if category == "terminal_adoption":
        facts["terminal_decision_required"] = True
    facts.update(overrides)
    return seal_exception_event(
        campaign_id="campaign-001",
        mission_id="mission-001",
        category=category,
        code=f"{category}.detected",
        detail=f"Evidence-backed {category} event.",
        evidence_sha256=_digest(category),
        **facts,
    )


@pytest.mark.parametrize("category", sorted(ESCALATION_CATEGORIES))
def test_each_closed_exception_category_escalates(category: str) -> None:
    event = _event(category)
    if category == "unreconciled_ambiguity":
        event = _event(
            category,
            hard_failure=True,
            internal_repair_exhausted=True,
        )

    result = evaluate_exception_escalation(event)

    assert result["disposition"] == "escalate"
    assert result["reason_code"] == f"typed_exception_{category}"
    assert result["routine_handoff_allowed"] is False
    validate_exception_escalation_replay(result, event=event)


@pytest.mark.parametrize("category", sorted(ROUTINE_CATEGORIES))
def test_convenience_and_bookkeeping_categories_continue_without_handoff(
    category: str,
) -> None:
    result = evaluate_exception_escalation(_event(category))

    assert result["disposition"] == "continue_campaign"
    assert result["reason_code"] == "routine_handoff_suppressed"
    assert result["routine_handoff_allowed"] is False


def test_ambiguity_continues_internal_recovery_until_exhausted() -> None:
    result = evaluate_exception_escalation(_event("unreconciled_ambiguity", hard_failure=True))

    assert result["disposition"] == "continue_recovery"
    assert result["reason_code"] == "ambiguity_requires_internal_reconciliation"


@pytest.mark.parametrize("category", sorted(ROUTINE_CATEGORIES))
def test_routine_label_cannot_hide_a_hard_failure(category: str) -> None:
    with pytest.raises(ExceptionEscalationError, match="cannot hide"):
        _event(category, hard_failure=True)


@pytest.mark.parametrize(
    ("category", "facts", "message"),
    [
        (
            "security_or_credentials",
            {"external_authority_required": False},
            "requires external_authority_required",
        ),
        (
            "destructive_or_external_authority",
            {"external_authority_required": False},
            "requires external_authority_required",
        ),
        (
            "authority_conflict",
            {"external_authority_required": False},
            "requires external_authority_required",
        ),
        (
            "repair_exhaustion",
            {"hard_failure": True, "internal_repair_exhausted": False},
            "requires hard_failure",
        ),
        (
            "terminal_adoption",
            {"terminal_decision_required": False},
            "requires terminal_decision_required",
        ),
    ],
)
def test_required_exception_facts_fail_closed(
    category: str,
    facts: dict[str, bool],
    message: str,
) -> None:
    with pytest.raises(ExceptionEscalationError, match=message):
        _event(category, **facts)


def test_internal_repair_exhaustion_without_hard_failure_fails_closed() -> None:
    with pytest.raises(ExceptionEscalationError, match="requires a hard failure"):
        _event(
            "unreconciled_ambiguity",
            hard_failure=False,
            internal_repair_exhausted=True,
        )


def test_unknown_fields_and_unsupported_categories_fail_closed() -> None:
    event = _event("contradictory_truth")
    with_extra = dict(event, unexpected=True)
    with pytest.raises(ExceptionEscalationError, match="field or schema"):
        validate_exception_event(with_extra)

    unsupported = copy.deepcopy(event)
    unsupported["category"] = "please_review"
    unsupported["event_sha256"] = "0" * 64
    unsupported["event_sha256"] = canonical_sha256(unsupported)
    with pytest.raises(ExceptionEscalationError, match="unsupported"):
        validate_exception_event(unsupported)


def test_event_hash_drift_and_rehashed_result_drift_fail_replay() -> None:
    event = _event("contradictory_truth")
    drifted_event = copy.deepcopy(event)
    drifted_event["detail"] = "Changed after sealing."
    with pytest.raises(ExceptionEscalationError, match="event self-hash mismatch"):
        validate_exception_event(drifted_event)

    result = evaluate_exception_escalation(event)
    drifted_result = copy.deepcopy(result)
    drifted_result["reason_code"] = "invented_reason"
    drifted_result["result_sha256"] = "0" * 64
    drifted_result["result_sha256"] = canonical_sha256(drifted_result)
    with pytest.raises(ExceptionEscalationError, match="replay mismatch"):
        validate_exception_escalation_replay(drifted_result, event=event)


def test_invalid_boolean_is_rejected_instead_of_coerced() -> None:
    event = _event("contradictory_truth")
    event["hard_failure"] = 1
    event["event_sha256"] = "0" * 64
    event["event_sha256"] = canonical_sha256(event)

    with pytest.raises(ExceptionEscalationError, match="must be boolean"):
        validate_exception_event(event)


@pytest.mark.parametrize(
    ("category", "facts", "message"),
    [
        (
            "contradictory_truth",
            {"external_authority_required": True},
            "external authority fact contradicts",
        ),
        (
            "policy_or_schema_change",
            {"terminal_decision_required": True},
            "terminal decision fact contradicts",
        ),
    ],
)
def test_cross_category_authority_facts_fail_closed(
    category: str,
    facts: dict[str, bool],
    message: str,
) -> None:
    with pytest.raises(ExceptionEscalationError, match=message):
        _event(category, **facts)


def test_noncanonical_detail_fails_closed() -> None:
    event = _event("contradictory_truth")
    event["detail"] = f" {event['detail']} "
    event["event_sha256"] = "0" * 64
    event["event_sha256"] = canonical_sha256(event)

    with pytest.raises(ExceptionEscalationError, match="detail is not canonical"):
        validate_exception_event(event)
