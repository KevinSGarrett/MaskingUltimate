"""Campaign-level proof that routine Codex micro-handoffs were suppressed."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from .campaign_telemetry import validate_telemetry_event
from .continuous_contract import canonical_sha256
from .exception_escalation import validate_exception_escalation_replay

AUDIT_SCHEMA = "maskfactory.steward.campaign_handoff_audit.v1"
ZERO_SHA256 = "0" * 64
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_AUDIT_FIELDS = {
    "schema_version",
    "campaign_id",
    "telemetry_event_sha256",
    "typed_exception_result_sha256",
    "terminal_adoption_packet_sha256",
    "codex_interventions",
    "routine_handoffs",
    "exception_escalations",
    "terminal_adoptions",
    "passed",
    "limitations",
    "audit_sha256",
}
_EXCEPTION_RECORD_FIELDS = {"event", "result"}


class HandoffSuppressionError(ValueError):
    """Campaign handoff evidence is missing, duplicated, or contradictory."""


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise HandoffSuppressionError(f"{field} is invalid")
    return value


def _validate_inputs(
    *,
    campaign_id: str,
    telemetry_events: Sequence[Mapping[str, Any]],
    exception_records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    if (
        not isinstance(campaign_id, str)
        or not campaign_id
        or len(campaign_id) > 160
        or any(character in campaign_id for character in "/\\\0")
    ):
        raise HandoffSuppressionError("campaign_id is invalid")
    if not isinstance(telemetry_events, Sequence) or isinstance(telemetry_events, (str, bytes)):
        raise HandoffSuppressionError("telemetry_events must be a sequence")
    normalized_events: list[dict[str, Any]] = []
    event_hashes: set[str] = set()
    for raw in telemetry_events:
        validate_telemetry_event(raw)
        event = dict(raw)
        if event["campaign_id"] != campaign_id:
            raise HandoffSuppressionError("telemetry campaign binding mismatch")
        if event["event_sha256"] in event_hashes:
            raise HandoffSuppressionError("duplicate telemetry event")
        event_hashes.add(event["event_sha256"])
        normalized_events.append(event)
    expected_sequences = list(range(1, len(normalized_events) + 1))
    if [event["sequence"] for event in normalized_events] != expected_sequences:
        raise HandoffSuppressionError("telemetry events must be ordered and contiguous")
    if not isinstance(exception_records, Sequence) or isinstance(exception_records, (str, bytes)):
        raise HandoffSuppressionError("exception_records must be a sequence")
    escalations_by_mission: dict[str, dict[str, Any]] = {}
    result_hashes: set[str] = set()
    for record in exception_records:
        if not isinstance(record, Mapping) or set(record) != _EXCEPTION_RECORD_FIELDS:
            raise HandoffSuppressionError("exception record field set mismatch")
        event = record["event"]
        result = record["result"]
        if not isinstance(event, Mapping) or not isinstance(result, Mapping):
            raise HandoffSuppressionError("exception record must contain objects")
        validate_exception_escalation_replay(result, event=event)
        if event["campaign_id"] != campaign_id or result["campaign_id"] != campaign_id:
            raise HandoffSuppressionError("exception campaign binding mismatch")
        result_hash = result["result_sha256"]
        if result_hash in result_hashes:
            raise HandoffSuppressionError("duplicate exception result")
        result_hashes.add(result_hash)
        if result["disposition"] != "escalate":
            continue
        mission_id = result["mission_id"]
        if mission_id in escalations_by_mission:
            raise HandoffSuppressionError("multiple typed escalations target one mission")
        escalations_by_mission[mission_id] = dict(result)
    return normalized_events, escalations_by_mission, sorted(result_hashes)


def audit_campaign_handoffs(
    *,
    campaign_id: str,
    telemetry_events: Sequence[Mapping[str, Any]],
    exception_records: Sequence[Mapping[str, Any]],
    terminal_adoption_packet_sha256: str,
) -> dict[str, Any]:
    """Prove typed exception-only intervention plus one terminal adoption."""

    terminal_packet = _sha256(
        terminal_adoption_packet_sha256,
        field="terminal_adoption_packet_sha256",
    )
    events, escalations_by_mission, result_hashes = _validate_inputs(
        campaign_id=campaign_id,
        telemetry_events=telemetry_events,
        exception_records=exception_records,
    )
    codex_events = [event for event in events if event["kind"] == "codex_intervention"]
    routine_events = [event for event in codex_events if event["value"] == "routine_handoff"]
    if routine_events:
        raise HandoffSuppressionError("routine Codex handoff violates campaign-local execution")
    terminal_events = [event for event in codex_events if event["value"] == "terminal_adoption"]
    if len(terminal_events) != 1:
        raise HandoffSuppressionError("campaign requires exactly one terminal adoption handoff")
    terminal_event = terminal_events[0]
    if terminal_event["mission_id"] is not None:
        raise HandoffSuppressionError("terminal adoption must be campaign-scoped")
    if terminal_event["sequence"] != len(events):
        raise HandoffSuppressionError("terminal adoption must be the final campaign event")
    exception_events = [event for event in codex_events if event["value"] == "exception_escalation"]
    exception_missions: set[str] = set()
    for event in exception_events:
        mission_id = event["mission_id"]
        if mission_id is None:
            raise HandoffSuppressionError("exception escalation must bind a mission")
        if mission_id in exception_missions:
            raise HandoffSuppressionError("duplicate Codex exception escalation for mission")
        exception_missions.add(mission_id)
        if mission_id not in escalations_by_mission:
            raise HandoffSuppressionError("Codex exception event lacks a typed escalation decision")
    if exception_missions != set(escalations_by_mission):
        raise HandoffSuppressionError("typed escalation decision lacks a Codex exception event")
    audit = {
        "schema_version": AUDIT_SCHEMA,
        "campaign_id": campaign_id,
        "telemetry_event_sha256": [event["event_sha256"] for event in events],
        "typed_exception_result_sha256": result_hashes,
        "terminal_adoption_packet_sha256": terminal_packet,
        "codex_interventions": len(codex_events),
        "routine_handoffs": 0,
        "exception_escalations": len(exception_events),
        "terminal_adoptions": 1,
        "passed": True,
        "limitations": [
            "Audit proves handoff structure only; it does not grant adoption authority.",
            "Terminal packet content and real-campaign provenance require separate validation.",
        ],
        "audit_sha256": ZERO_SHA256,
    }
    audit["audit_sha256"] = canonical_sha256(audit)
    return audit


def validate_campaign_handoff_audit_replay(
    audit: Mapping[str, Any],
    *,
    campaign_id: str,
    telemetry_events: Sequence[Mapping[str, Any]],
    exception_records: Sequence[Mapping[str, Any]],
    terminal_adoption_packet_sha256: str,
) -> None:
    """Reject field, self-hash, source-binding, or deterministic audit drift."""

    if set(audit) != _AUDIT_FIELDS or audit.get("schema_version") != AUDIT_SCHEMA:
        raise HandoffSuppressionError("handoff audit field or schema mismatch")
    declared = _sha256(audit.get("audit_sha256"), field="audit_sha256")
    zeroed = deepcopy(dict(audit))
    zeroed["audit_sha256"] = ZERO_SHA256
    if canonical_sha256(zeroed) != declared:
        raise HandoffSuppressionError("handoff audit self-hash mismatch")
    expected = audit_campaign_handoffs(
        campaign_id=campaign_id,
        telemetry_events=telemetry_events,
        exception_records=exception_records,
        terminal_adoption_packet_sha256=terminal_adoption_packet_sha256,
    )
    if dict(audit) != expected:
        raise HandoffSuppressionError("handoff audit deterministic replay mismatch")


__all__ = [
    "AUDIT_SCHEMA",
    "HandoffSuppressionError",
    "audit_campaign_handoffs",
    "validate_campaign_handoff_audit_replay",
]
