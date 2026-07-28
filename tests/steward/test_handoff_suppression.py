from __future__ import annotations

import copy
import hashlib

import pytest

from maskfactory.steward.campaign_telemetry import build_telemetry_event
from maskfactory.steward.continuous_contract import canonical_sha256
from maskfactory.steward.exception_escalation import (
    evaluate_exception_escalation,
    seal_exception_event,
)
from maskfactory.steward.handoff_suppression import (
    HandoffSuppressionError,
    audit_campaign_handoffs,
    validate_campaign_handoff_audit_replay,
)

CAMPAIGN_ID = "engineering-campaign-025"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _telemetry(
    *,
    intervention: str | None = None,
    mission_id: str | None = None,
) -> list[dict]:
    events = [
        build_telemetry_event(
            campaign_id=CAMPAIGN_ID,
            sequence=1,
            kind="planned",
            mission_id="mission-001",
        ),
        build_telemetry_event(
            campaign_id=CAMPAIGN_ID,
            sequence=2,
            kind="completed",
            mission_id="mission-001",
        ),
    ]
    if intervention is not None:
        events.append(
            build_telemetry_event(
                campaign_id=CAMPAIGN_ID,
                sequence=len(events) + 1,
                kind="codex_intervention",
                mission_id=mission_id,
                value=intervention,
                duration_seconds=30,
                numeric_value=10,
            )
        )
    events.append(
        build_telemetry_event(
            campaign_id=CAMPAIGN_ID,
            sequence=len(events) + 1,
            kind="codex_intervention",
            value="terminal_adoption",
            duration_seconds=60,
            numeric_value=20,
        )
    )
    return events


def _exception_record(*, disposition: str = "escalate") -> dict:
    if disposition == "escalate":
        event = seal_exception_event(
            campaign_id=CAMPAIGN_ID,
            mission_id="mission-001",
            category="contradictory_truth",
            code="truth.conflict",
            detail="Two immutable evidence sources disagree.",
            evidence_sha256=_digest("truth"),
            hard_failure=True,
        )
    else:
        event = seal_exception_event(
            campaign_id=CAMPAIGN_ID,
            mission_id="mission-001",
            category="bookkeeping",
            code="status.compaction",
            detail="Routine campaign-local compaction.",
            evidence_sha256=_digest("bookkeeping"),
        )
    return {
        "event": event,
        "result": evaluate_exception_escalation(event),
    }


def test_ordinary_campaign_has_one_terminal_handoff_only() -> None:
    events = _telemetry()

    audit = audit_campaign_handoffs(
        campaign_id=CAMPAIGN_ID,
        telemetry_events=events,
        exception_records=[],
        terminal_adoption_packet_sha256=_digest("adoption"),
    )

    assert audit["passed"] is True
    assert audit["codex_interventions"] == 1
    assert audit["routine_handoffs"] == 0
    assert audit["exception_escalations"] == 0
    assert audit["terminal_adoptions"] == 1
    validate_campaign_handoff_audit_replay(
        audit,
        campaign_id=CAMPAIGN_ID,
        telemetry_events=events,
        exception_records=[],
        terminal_adoption_packet_sha256=_digest("adoption"),
    )


def test_typed_exception_and_terminal_handoff_are_bound() -> None:
    events = _telemetry(
        intervention="exception_escalation",
        mission_id="mission-001",
    )
    record = _exception_record()

    audit = audit_campaign_handoffs(
        campaign_id=CAMPAIGN_ID,
        telemetry_events=events,
        exception_records=[record],
        terminal_adoption_packet_sha256=_digest("adoption"),
    )

    assert audit["codex_interventions"] == 2
    assert audit["exception_escalations"] == 1
    assert audit["typed_exception_result_sha256"] == [
        record["result"]["result_sha256"]
    ]


def test_campaign_local_non_escalation_is_bound_without_codex_handoff() -> None:
    record = _exception_record(disposition="continue")

    audit = audit_campaign_handoffs(
        campaign_id=CAMPAIGN_ID,
        telemetry_events=_telemetry(),
        exception_records=[record],
        terminal_adoption_packet_sha256=_digest("adoption"),
    )

    assert audit["codex_interventions"] == 1
    assert audit["exception_escalations"] == 0
    assert audit["typed_exception_result_sha256"] == [
        record["result"]["result_sha256"]
    ]


def test_routine_handoff_fails_campaign_audit() -> None:
    with pytest.raises(HandoffSuppressionError, match="routine Codex handoff"):
        audit_campaign_handoffs(
            campaign_id=CAMPAIGN_ID,
            telemetry_events=_telemetry(
                intervention="routine_handoff",
                mission_id="mission-001",
            ),
            exception_records=[],
            terminal_adoption_packet_sha256=_digest("adoption"),
        )


@pytest.mark.parametrize(
    ("events", "records", "message"),
    [
        (
            _telemetry(
                intervention="exception_escalation",
                mission_id="mission-001",
            ),
            [],
            "lacks a typed escalation",
        ),
        (
            _telemetry(),
            [_exception_record()],
            "lacks a Codex exception event",
        ),
        (
            _telemetry(
                intervention="exception_escalation",
                mission_id="mission-001",
            ),
            [_exception_record(disposition="continue")],
            "lacks a typed escalation",
        ),
    ],
)
def test_exception_event_and_typed_decision_must_match_exactly(
    events: list[dict],
    records: list[dict],
    message: str,
) -> None:
    with pytest.raises(HandoffSuppressionError, match=message):
        audit_campaign_handoffs(
            campaign_id=CAMPAIGN_ID,
            telemetry_events=events,
            exception_records=records,
            terminal_adoption_packet_sha256=_digest("adoption"),
        )


def test_terminal_adoption_must_be_unique_campaign_scoped_and_final() -> None:
    missing = _telemetry()[:-1]
    with pytest.raises(HandoffSuppressionError, match="exactly one"):
        audit_campaign_handoffs(
            campaign_id=CAMPAIGN_ID,
            telemetry_events=missing,
            exception_records=[],
            terminal_adoption_packet_sha256=_digest("adoption"),
        )

    mission_scoped = _telemetry()
    mission_scoped[-1] = build_telemetry_event(
        campaign_id=CAMPAIGN_ID,
        sequence=len(mission_scoped),
        kind="codex_intervention",
        mission_id="mission-001",
        value="terminal_adoption",
        duration_seconds=60,
        numeric_value=20,
    )
    with pytest.raises(HandoffSuppressionError, match="campaign-scoped"):
        audit_campaign_handoffs(
            campaign_id=CAMPAIGN_ID,
            telemetry_events=mission_scoped,
            exception_records=[],
            terminal_adoption_packet_sha256=_digest("adoption"),
        )

    not_final = _telemetry()
    terminal = not_final.pop()
    not_final.insert(1, terminal)
    for sequence, event in enumerate(not_final, start=1):
        event["sequence"] = sequence
        event["event_sha256"] = "0" * 64
        event["event_sha256"] = canonical_sha256(event)
    with pytest.raises(HandoffSuppressionError, match="final campaign event"):
        audit_campaign_handoffs(
            campaign_id=CAMPAIGN_ID,
            telemetry_events=not_final,
            exception_records=[],
            terminal_adoption_packet_sha256=_digest("adoption"),
        )


def test_unordered_duplicate_and_cross_campaign_evidence_fail_closed() -> None:
    unordered = _telemetry()
    unordered[0], unordered[1] = unordered[1], unordered[0]
    with pytest.raises(HandoffSuppressionError, match="ordered and contiguous"):
        audit_campaign_handoffs(
            campaign_id=CAMPAIGN_ID,
            telemetry_events=unordered,
            exception_records=[],
            terminal_adoption_packet_sha256=_digest("adoption"),
        )

    duplicated = _telemetry()
    duplicated.insert(1, copy.deepcopy(duplicated[0]))
    with pytest.raises(HandoffSuppressionError, match="duplicate telemetry"):
        audit_campaign_handoffs(
            campaign_id=CAMPAIGN_ID,
            telemetry_events=duplicated,
            exception_records=[],
            terminal_adoption_packet_sha256=_digest("adoption"),
        )

    cross_campaign = _exception_record()
    cross_campaign["event"]["campaign_id"] = "other-campaign"
    cross_campaign["event"]["event_sha256"] = "0" * 64
    cross_campaign["event"]["event_sha256"] = canonical_sha256(
        cross_campaign["event"]
    )
    cross_campaign["result"] = evaluate_exception_escalation(
        cross_campaign["event"]
    )
    with pytest.raises(HandoffSuppressionError, match="campaign binding"):
        audit_campaign_handoffs(
            campaign_id=CAMPAIGN_ID,
            telemetry_events=_telemetry(),
            exception_records=[cross_campaign],
            terminal_adoption_packet_sha256=_digest("adoption"),
        )


def test_rehashed_audit_drift_fails_deterministic_replay() -> None:
    events = _telemetry()
    audit = audit_campaign_handoffs(
        campaign_id=CAMPAIGN_ID,
        telemetry_events=events,
        exception_records=[],
        terminal_adoption_packet_sha256=_digest("adoption"),
    )
    drifted = copy.deepcopy(audit)
    drifted["limitations"][0] = "Invented stronger claim."
    drifted["audit_sha256"] = "0" * 64
    drifted["audit_sha256"] = canonical_sha256(drifted)

    with pytest.raises(HandoffSuppressionError, match="replay mismatch"):
        validate_campaign_handoff_audit_replay(
            drifted,
            campaign_id=CAMPAIGN_ID,
            telemetry_events=events,
            exception_records=[],
            terminal_adoption_packet_sha256=_digest("adoption"),
        )
