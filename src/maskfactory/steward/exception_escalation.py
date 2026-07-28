"""Closed, fail-closed exception escalation for autonomous campaigns."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .continuous_contract import canonical_sha256

EVENT_SCHEMA = "maskfactory.steward.exception_escalation_event.v1"
RESULT_SCHEMA = "maskfactory.steward.exception_escalation_result.v1"
ZERO_SHA256 = "0" * 64

ESCALATION_CATEGORIES = frozenset(
    {
        "security_or_credentials",
        "destructive_or_external_authority",
        "authority_conflict",
        "contradictory_truth",
        "policy_or_schema_change",
        "unreconciled_ambiguity",
        "repair_exhaustion",
        "terminal_adoption",
    }
)
ROUTINE_CATEGORIES = frozenset(
    {
        "convenience",
        "bookkeeping",
        "routine_success",
        "intermediate_validation",
        "status_request",
    }
)
CATEGORIES = ESCALATION_CATEGORIES | ROUTINE_CATEGORIES
DISPOSITIONS = frozenset({"escalate", "continue_campaign", "continue_recovery"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_EVENT_FIELDS = {
    "schema_version",
    "campaign_id",
    "mission_id",
    "category",
    "code",
    "detail",
    "evidence_sha256",
    "hard_failure",
    "internal_repair_exhausted",
    "external_authority_required",
    "terminal_decision_required",
    "event_sha256",
}
_RESULT_FIELDS = {
    "schema_version",
    "campaign_id",
    "mission_id",
    "event_sha256",
    "category",
    "disposition",
    "reason_code",
    "routine_handoff_allowed",
    "result_sha256",
}


class ExceptionEscalationError(ValueError):
    """An escalation event is malformed, contradictory, or hides a hard failure."""


def _identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ExceptionEscalationError(f"{field} is invalid")
    return value


def _text(value: object, *, field: str, maximum_bytes: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise ExceptionEscalationError(f"{field} is invalid")
    return value.strip()


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ExceptionEscalationError(f"{field} is invalid")
    return value


def _boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ExceptionEscalationError(f"{field} must be boolean")
    return value


def _verify_self_hash(
    value: Mapping[str, Any],
    *,
    field: str,
    error_label: str,
) -> None:
    declared = _sha256(value.get(field), field=field)
    zeroed = deepcopy(dict(value))
    zeroed[field] = ZERO_SHA256
    if canonical_sha256(zeroed) != declared:
        raise ExceptionEscalationError(f"{error_label} self-hash mismatch")


def seal_exception_event(
    *,
    campaign_id: str,
    mission_id: str,
    category: str,
    code: str,
    detail: str,
    evidence_sha256: str,
    hard_failure: bool = False,
    internal_repair_exhausted: bool = False,
    external_authority_required: bool = False,
    terminal_decision_required: bool = False,
) -> dict[str, Any]:
    """Seal one strict event without deciding whether Codex must be invoked."""

    event = {
        "schema_version": EVENT_SCHEMA,
        "campaign_id": campaign_id,
        "mission_id": mission_id,
        "category": category,
        "code": code,
        "detail": detail,
        "evidence_sha256": evidence_sha256,
        "hard_failure": hard_failure,
        "internal_repair_exhausted": internal_repair_exhausted,
        "external_authority_required": external_authority_required,
        "terminal_decision_required": terminal_decision_required,
        "event_sha256": ZERO_SHA256,
    }
    event["event_sha256"] = canonical_sha256(event)
    validate_exception_event(event)
    return event


def validate_exception_event(event: Mapping[str, Any]) -> None:
    """Reject unknown fields, invalid facts, drift, and category/fact contradictions."""

    if set(event) != _EVENT_FIELDS or event.get("schema_version") != EVENT_SCHEMA:
        raise ExceptionEscalationError("exception event field or schema mismatch")
    _identifier(event.get("campaign_id"), field="campaign_id")
    _identifier(event.get("mission_id"), field="mission_id")
    _identifier(event.get("code"), field="code")
    detail = _text(event.get("detail"), field="detail")
    if event.get("detail") != detail:
        raise ExceptionEscalationError("detail is not canonical")
    _sha256(event.get("evidence_sha256"), field="evidence_sha256")
    category = event.get("category")
    if category not in CATEGORIES:
        raise ExceptionEscalationError("exception category is unsupported")
    hard_failure = _boolean(event.get("hard_failure"), field="hard_failure")
    repair_exhausted = _boolean(
        event.get("internal_repair_exhausted"),
        field="internal_repair_exhausted",
    )
    external_authority = _boolean(
        event.get("external_authority_required"),
        field="external_authority_required",
    )
    terminal_decision = _boolean(
        event.get("terminal_decision_required"),
        field="terminal_decision_required",
    )
    if repair_exhausted and not hard_failure:
        raise ExceptionEscalationError(
            "internal repair exhaustion requires a hard failure"
        )
    if category in ROUTINE_CATEGORIES and (
        hard_failure or repair_exhausted or external_authority or terminal_decision
    ):
        raise ExceptionEscalationError(
            "routine category cannot hide a hard failure or authority requirement"
        )
    if category in {
        "security_or_credentials",
        "destructive_or_external_authority",
        "authority_conflict",
    } and not external_authority:
        raise ExceptionEscalationError(
            f"{category} requires external_authority_required"
        )
    if external_authority and category not in {
        "security_or_credentials",
        "destructive_or_external_authority",
        "authority_conflict",
    }:
        raise ExceptionEscalationError(
            "external authority fact contradicts the exception category"
        )
    if category == "repair_exhaustion" and not (
        hard_failure and repair_exhausted
    ):
        raise ExceptionEscalationError(
            "repair_exhaustion requires hard_failure and internal_repair_exhausted"
        )
    if category == "terminal_adoption" and not terminal_decision:
        raise ExceptionEscalationError(
            "terminal_adoption requires terminal_decision_required"
        )
    if terminal_decision and category != "terminal_adoption":
        raise ExceptionEscalationError(
            "terminal decision fact contradicts the exception category"
        )
    _verify_self_hash(
        event,
        field="event_sha256",
        error_label="exception event",
    )


def evaluate_exception_escalation(event: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the sole permitted campaign escalation disposition."""

    validate_exception_event(event)
    category = event["category"]
    if category in ROUTINE_CATEGORIES:
        disposition = "continue_campaign"
        reason_code = "routine_handoff_suppressed"
    elif category == "unreconciled_ambiguity" and not (
        event["hard_failure"] and event["internal_repair_exhausted"]
    ):
        disposition = "continue_recovery"
        reason_code = "ambiguity_requires_internal_reconciliation"
    else:
        disposition = "escalate"
        reason_code = f"typed_exception_{category}"
    result = {
        "schema_version": RESULT_SCHEMA,
        "campaign_id": event["campaign_id"],
        "mission_id": event["mission_id"],
        "event_sha256": event["event_sha256"],
        "category": category,
        "disposition": disposition,
        "reason_code": reason_code,
        "routine_handoff_allowed": False,
        "result_sha256": ZERO_SHA256,
    }
    result["result_sha256"] = canonical_sha256(result)
    return result


def validate_exception_escalation_replay(
    result: Mapping[str, Any],
    *,
    event: Mapping[str, Any],
) -> None:
    """Reject self-hash, source-binding, field, or deterministic decision drift."""

    if set(result) != _RESULT_FIELDS or result.get("schema_version") != RESULT_SCHEMA:
        raise ExceptionEscalationError("exception result field or schema mismatch")
    if result.get("disposition") not in DISPOSITIONS:
        raise ExceptionEscalationError("exception result disposition is unsupported")
    if result.get("routine_handoff_allowed") is not False:
        raise ExceptionEscalationError("routine handoff authority escalation")
    _verify_self_hash(
        result,
        field="result_sha256",
        error_label="exception result",
    )
    expected = evaluate_exception_escalation(event)
    if dict(result) != expected:
        raise ExceptionEscalationError(
            "exception escalation deterministic replay mismatch"
        )


__all__ = [
    "CATEGORIES",
    "DISPOSITIONS",
    "ESCALATION_CATEGORIES",
    "EVENT_SCHEMA",
    "ExceptionEscalationError",
    "RESULT_SCHEMA",
    "ROUTINE_CATEGORIES",
    "evaluate_exception_escalation",
    "seal_exception_event",
    "validate_exception_escalation_replay",
    "validate_exception_event",
]
