"""Exact event-to-telemetry reconciliation for Plan-27 campaigns."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from .continuous_contract import validate_campaign_document

SOURCE_SCHEMA = "maskfactory.campaign-telemetry-source.v1"
EVENT_SCHEMA = "maskfactory.campaign-telemetry-event.v1"
OUTPUT_SCHEMA = "maskfactory_self_hosted_autonomy_campaign_telemetry.v1"
ZERO_SHA256 = "0" * 64
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CAMPAIGN_KINDS = frozenset({"engineering", "mask", "mixed"})
ROUTES = ("local_pod", "serverless", "openrouter_advisory", "cpu_safe")
MASK_OUTCOMES = ("accept", "repair", "abstain", "reject", "quarantine")
CODEX_INTERVENTIONS = frozenset({"routine_handoff", "exception_escalation", "terminal_adoption"})
EVENT_KINDS = frozenset(
    {
        "planned",
        "eligible",
        "completed",
        "autonomously_prepared",
        "accepted",
        "codex_intervention",
        "model_startup",
        "inference",
        "idle_gpu",
        "local_gpu_work_cell",
        "local_gpu_release",
        "route_selected",
        "fallback_reason",
        "inference_submission",
        "promotion",
        "admitted",
        "terminal_reconciled",
        "submitted_unknown",
        "recovery_required",
        "recovery_resolved",
        "authority_bypass",
        "patch_attempt",
        "focused_test_run",
        "repair_attempt",
        "repair_exhaustion",
        "mask_terminal",
        "artifact_produced",
        "artifact_accepted",
    }
)
TIMING_KINDS = frozenset({"model_startup", "inference", "idle_gpu", "codex_intervention"})
SUBJECT_KINDS = frozenset(
    {
        "local_gpu_work_cell",
        "local_gpu_release",
        "inference_submission",
        "promotion",
        "artifact_produced",
        "artifact_accepted",
    }
)


class CampaignTelemetryError(ValueError):
    """Campaign telemetry sources do not reconcile exactly."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    sealed = deepcopy(dict(value))
    sealed[field] = ZERO_SHA256
    sealed[field] = _sha256(sealed)
    return sealed


def _digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise CampaignTelemetryError(f"{field} must be lowercase SHA-256")
    return value


def _identifier(value: object, *, field: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 160
        or any(character in value for character in "/\\\0")
    ):
        raise CampaignTelemetryError(f"{field} is invalid")
    return value


def _number(
    value: object,
    *,
    field: str,
    nullable: bool = False,
) -> float | None:
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise CampaignTelemetryError(f"{field} must be nonnegative")
    return float(value)


def _timestamp(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise CampaignTelemetryError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CampaignTelemetryError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise CampaignTelemetryError(f"{field} must include a timezone")
    return value


def build_telemetry_event(
    *,
    campaign_id: str,
    sequence: int,
    kind: str,
    mission_id: str | None = None,
    route: str | None = None,
    subject_id: str | None = None,
    value: str | None = None,
    duration_seconds: int | float | None = None,
    numeric_value: int | float | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Seal one closed telemetry event."""

    event = {
        "schema_version": EVENT_SCHEMA,
        "campaign_id": campaign_id,
        "sequence": sequence,
        "mission_id": mission_id,
        "kind": kind,
        "route": route,
        "subject_id": subject_id,
        "value": value,
        "duration_seconds": duration_seconds,
        "numeric_value": numeric_value,
        "reason": reason,
        "event_sha256": ZERO_SHA256,
    }
    _validate_event_fields(event, verify_hash=False)
    return _seal(event, "event_sha256")


def _validate_event_fields(
    event: Mapping[str, Any],
    *,
    verify_hash: bool,
) -> None:
    expected_fields = {
        "schema_version",
        "campaign_id",
        "sequence",
        "mission_id",
        "kind",
        "route",
        "subject_id",
        "value",
        "duration_seconds",
        "numeric_value",
        "reason",
        "event_sha256",
    }
    if not isinstance(event, Mapping) or set(event) != expected_fields:
        raise CampaignTelemetryError("telemetry event field set mismatch")
    if event.get("schema_version") != EVENT_SCHEMA:
        raise CampaignTelemetryError("telemetry event schema mismatch")
    _identifier(event.get("campaign_id"), field="campaign_id")
    sequence = event.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
        raise CampaignTelemetryError("event sequence must be positive")
    kind = event.get("kind")
    if kind not in EVENT_KINDS:
        raise CampaignTelemetryError("telemetry event kind is invalid")
    mission_id = _identifier(
        event.get("mission_id"),
        field="mission_id",
        nullable=True,
    )
    if kind != "codex_intervention" and mission_id is None:
        raise CampaignTelemetryError("non-Codex events require mission_id")
    route = event.get("route")
    if kind == "route_selected":
        if route not in ROUTES:
            raise CampaignTelemetryError("route_selected requires a governed route")
    elif route is not None:
        raise CampaignTelemetryError("route is only valid on route_selected")
    subject_id = _identifier(
        event.get("subject_id"),
        field="subject_id",
        nullable=True,
    )
    if kind in SUBJECT_KINDS and subject_id is None:
        raise CampaignTelemetryError(f"{kind} requires subject_id")
    if kind not in SUBJECT_KINDS and subject_id is not None:
        raise CampaignTelemetryError(f"{kind} must not include subject_id")
    value = event.get("value")
    if kind == "mask_terminal":
        if value not in MASK_OUTCOMES:
            raise CampaignTelemetryError("mask_terminal value is invalid")
    elif kind == "codex_intervention":
        if value not in CODEX_INTERVENTIONS:
            raise CampaignTelemetryError("Codex intervention category is invalid")
    elif value is not None:
        raise CampaignTelemetryError(f"{kind} must not include value")
    duration = _number(
        event.get("duration_seconds"),
        field="duration_seconds",
        nullable=True,
    )
    if kind in TIMING_KINDS and duration is None:
        raise CampaignTelemetryError(f"{kind} requires duration_seconds")
    if kind not in TIMING_KINDS and duration is not None:
        raise CampaignTelemetryError(f"{kind} must not include duration_seconds")
    numeric = _number(
        event.get("numeric_value"),
        field="numeric_value",
        nullable=True,
    )
    if kind == "codex_intervention" and numeric is None:
        raise CampaignTelemetryError("Codex intervention requires usage units")
    if kind != "codex_intervention" and numeric is not None:
        raise CampaignTelemetryError(f"{kind} must not include numeric_value")
    reason = event.get("reason")
    if kind in {"fallback_reason", "mask_terminal"}:
        _identifier(reason, field="reason")
    elif reason is not None:
        raise CampaignTelemetryError(f"{kind} must not include reason")
    if verify_hash:
        _digest(event.get("event_sha256"), field="event_sha256")
        zeroed = dict(event)
        zeroed["event_sha256"] = ZERO_SHA256
        if _sha256(zeroed) != event["event_sha256"]:
            raise CampaignTelemetryError("telemetry event self-hash mismatch")


def validate_telemetry_event(event: Mapping[str, Any]) -> None:
    _validate_event_fields(event, verify_hash=True)


def _validate_source(source: Mapping[str, Any]) -> dict[str, Any]:
    expected_fields = {
        "schema_version",
        "campaign_id",
        "campaign_kind",
        "campaign_payload_sha256",
        "source_commit_sha256",
        "started_at",
        "ended_at",
        "baseline_usage_units_per_accepted_artifact",
        "limitations",
    }
    if not isinstance(source, Mapping) or set(source) != expected_fields:
        raise CampaignTelemetryError("telemetry source field set mismatch")
    if source.get("schema_version") != SOURCE_SCHEMA:
        raise CampaignTelemetryError("telemetry source schema mismatch")
    campaign_id = _identifier(source.get("campaign_id"), field="campaign_id")
    campaign_kind = source.get("campaign_kind")
    if campaign_kind not in CAMPAIGN_KINDS:
        raise CampaignTelemetryError("campaign kind is invalid")
    started_at = _timestamp(source.get("started_at"), field="started_at")
    ended_at = _timestamp(source.get("ended_at"), field="ended_at")
    if datetime.fromisoformat(ended_at.replace("Z", "+00:00")) < datetime.fromisoformat(
        started_at.replace("Z", "+00:00")
    ):
        raise CampaignTelemetryError("campaign ended before it started")
    baseline = _number(
        source.get("baseline_usage_units_per_accepted_artifact"),
        field="baseline_usage_units_per_accepted_artifact",
    )
    limitations = source.get("limitations")
    if (
        not isinstance(limitations, Sequence)
        or isinstance(limitations, (str, bytes))
        or not limitations
        or any(
            not isinstance(value, str) or not value or len(value) > 1024 for value in limitations
        )
        or len(set(limitations)) != len(limitations)
    ):
        raise CampaignTelemetryError("limitations must be unique bounded strings")
    return {
        "schema_version": SOURCE_SCHEMA,
        "campaign_id": campaign_id,
        "campaign_kind": campaign_kind,
        "campaign_payload_sha256": _digest(
            source.get("campaign_payload_sha256"),
            field="campaign_payload_sha256",
        ),
        "source_commit_sha256": _digest(
            source.get("source_commit_sha256"),
            field="source_commit_sha256",
        ),
        "started_at": started_at,
        "ended_at": ended_at,
        "baseline_usage_units_per_accepted_artifact": baseline,
        "limitations": list(limitations),
    }


def _mission_sets(events: Sequence[Mapping[str, Any]]) -> dict[str, set[str]]:
    sets: dict[str, set[str]] = defaultdict(set)
    singleton_kinds = {
        "planned",
        "eligible",
        "completed",
        "autonomously_prepared",
        "accepted",
        "admitted",
        "terminal_reconciled",
        "submitted_unknown",
    }
    seen: set[tuple[str, str]] = set()
    for event in events:
        kind = event["kind"]
        mission_id = event["mission_id"]
        if mission_id is None:
            continue
        if kind in singleton_kinds:
            identity = (kind, mission_id)
            if identity in seen:
                raise CampaignTelemetryError(f"mission has duplicate singleton event: {kind}")
            seen.add(identity)
            sets[kind].add(mission_id)
    planned = sets["planned"]
    if not planned:
        raise CampaignTelemetryError("campaign has no planned missions")
    for kind, mission_ids in sets.items():
        if not mission_ids <= planned:
            raise CampaignTelemetryError(f"{kind} references an unplanned mission")
    if not sets["completed"] <= sets["eligible"]:
        raise CampaignTelemetryError("completed missions must be eligible")
    if not sets["autonomously_prepared"] <= sets["eligible"]:
        raise CampaignTelemetryError("autonomous preparation must be eligible")
    if not sets["accepted"] <= sets["completed"]:
        raise CampaignTelemetryError("accepted missions must be completed")
    if not sets["terminal_reconciled"] <= sets["admitted"]:
        raise CampaignTelemetryError("terminal reconciliation requires admission")
    return sets


def reconcile_campaign_telemetry(
    *,
    repo_root: Path,
    source: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive closed telemetry from one exact, hash-chained event collection."""

    normalized_source = _validate_source(source)
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise CampaignTelemetryError("events must be a sequence")
    normalized_events: list[dict[str, Any]] = []
    event_hashes: set[str] = set()
    for raw in events:
        validate_telemetry_event(raw)
        event = dict(raw)
        if event["campaign_id"] != normalized_source["campaign_id"]:
            raise CampaignTelemetryError("event campaign binding mismatch")
        if event["event_sha256"] in event_hashes:
            raise CampaignTelemetryError("duplicate telemetry event hash")
        event_hashes.add(event["event_sha256"])
        normalized_events.append(event)
    normalized_events.sort(key=lambda value: value["sequence"])
    if [event["sequence"] for event in normalized_events] != list(
        range(1, len(normalized_events) + 1)
    ):
        raise CampaignTelemetryError("event sequence must be contiguous and unique")

    sets = _mission_sets(normalized_events)
    route_by_mission: dict[str, str] = {}
    fallback_reasons: set[str] = set()
    for event in normalized_events:
        if event["kind"] == "route_selected":
            mission_id = event["mission_id"]
            if mission_id in route_by_mission:
                raise CampaignTelemetryError("mission selected more than one route")
            route_by_mission[mission_id] = event["route"]
        elif event["kind"] == "fallback_reason":
            fallback_reasons.add(event["reason"])
    if set(route_by_mission) != sets["eligible"]:
        raise CampaignTelemetryError(
            "every eligible mission must select exactly one governed route"
        )

    local_cell_counts = Counter(
        event["subject_id"] for event in normalized_events if event["kind"] == "local_gpu_work_cell"
    )
    local_release_counts = Counter(
        event["subject_id"] for event in normalized_events if event["kind"] == "local_gpu_release"
    )
    if any(count != 1 for count in local_cell_counts.values()):
        raise CampaignTelemetryError("local GPU work cell evidence is duplicated")
    if any(count != 1 for count in local_release_counts.values()):
        raise CampaignTelemetryError("local GPU release evidence is duplicated")
    local_cells = set(local_cell_counts)
    local_releases = set(local_release_counts)
    if not local_releases <= local_cells:
        raise CampaignTelemetryError("local release lacks a matching work cell")

    produced_counts = Counter(
        event["subject_id"] for event in normalized_events if event["kind"] == "artifact_produced"
    )
    accepted_counts = Counter(
        event["subject_id"] for event in normalized_events if event["kind"] == "artifact_accepted"
    )
    if any(count != 1 for count in produced_counts.values()):
        raise CampaignTelemetryError("produced artifact evidence is duplicated")
    if any(count != 1 for count in accepted_counts.values()):
        raise CampaignTelemetryError("accepted artifact evidence is duplicated")
    produced_artifacts = set(produced_counts)
    accepted_artifacts = set(accepted_counts)
    if not accepted_artifacts <= produced_artifacts:
        raise CampaignTelemetryError("accepted artifact was not produced")

    submission_counts = Counter(
        event["subject_id"]
        for event in normalized_events
        if event["kind"] == "inference_submission"
    )
    promotion_counts = Counter(
        event["subject_id"] for event in normalized_events if event["kind"] == "promotion"
    )
    codex_events = [event for event in normalized_events if event["kind"] == "codex_intervention"]
    codex_usage = sum(float(event["numeric_value"]) for event in codex_events)
    if not accepted_artifacts and codex_usage:
        raise CampaignTelemetryError(
            "Codex usage per accepted artifact is undefined with zero accepted artifacts"
        )
    observed_usage = codex_usage / len(accepted_artifacts) if accepted_artifacts else 0.0
    timing = {
        kind: sum(
            float(event["duration_seconds"]) for event in normalized_events if event["kind"] == kind
        )
        for kind in ("model_startup", "inference", "idle_gpu")
    }
    gpu_hours = sum(timing.values()) / 3600.0
    mask_events = [event for event in normalized_events if event["kind"] == "mask_terminal"]
    mask_counts = Counter(event["value"] for event in mask_events)
    telemetry = {
        "schema_version": OUTPUT_SCHEMA,
        "campaign_id": normalized_source["campaign_id"],
        "campaign_kind": normalized_source["campaign_kind"],
        "campaign_payload_sha256": normalized_source["campaign_payload_sha256"],
        "source_commit_sha256": normalized_source["source_commit_sha256"],
        "started_at": normalized_source["started_at"],
        "ended_at": normalized_source["ended_at"],
        "counts": {
            "planned": len(sets["planned"]),
            "eligible": len(sets["eligible"]),
            "completed": len(sets["completed"]),
            "autonomously_prepared": len(sets["autonomously_prepared"]),
            "accepted": len(sets["accepted"]),
        },
        "codex": {
            "interventions": len(codex_events),
            "routine_handoffs": sum(event["value"] == "routine_handoff" for event in codex_events),
            "review_seconds": sum(float(event["duration_seconds"]) for event in codex_events),
            "baseline_usage_units_per_accepted_artifact": normalized_source[
                "baseline_usage_units_per_accepted_artifact"
            ],
            "observed_usage_units_per_accepted_artifact": observed_usage,
        },
        "timing": {
            "model_startup_seconds": timing["model_startup"],
            "inference_seconds": timing["inference"],
            "idle_gpu_seconds": timing["idle_gpu"],
            "local_gpu_work_cells": len(local_cells),
            "local_gpu_released_work_cells": len(local_releases),
        },
        "routes": {
            route: sum(selected == route for selected in route_by_mission.values())
            for route in ROUTES
        }
        | {"fallback_reasons": sorted(fallback_reasons)},
        "integrity": {
            "duplicate_inference_submissions": sum(
                max(0, count - 1) for count in submission_counts.values()
            ),
            "duplicate_promotions": sum(max(0, count - 1) for count in promotion_counts.values()),
            "admitted_missions": len(sets["admitted"]),
            "terminally_reconciled_missions": len(sets["terminal_reconciled"]),
            "submitted_unknown_events": len(sets["submitted_unknown"]),
            "recovery_required_events": sum(
                event["kind"] == "recovery_required" for event in normalized_events
            ),
            "recovery_resolved_events": sum(
                event["kind"] == "recovery_resolved" for event in normalized_events
            ),
            "authority_bypasses": sum(
                event["kind"] == "authority_bypass" for event in normalized_events
            ),
        },
        "engineering": {
            "patch_attempts": sum(event["kind"] == "patch_attempt" for event in normalized_events),
            "focused_test_runs": sum(
                event["kind"] == "focused_test_run" for event in normalized_events
            ),
            "repair_attempts": sum(
                event["kind"] == "repair_attempt" for event in normalized_events
            ),
            "repair_exhaustions": sum(
                event["kind"] == "repair_exhaustion" for event in normalized_events
            ),
        },
        "masks": {outcome: mask_counts.get(outcome, 0) for outcome in MASK_OUTCOMES}
        | {
            "hard_qa_vetoes": sum(event["reason"] == "hard_qa_veto" for event in mask_events),
            "critic_disagreements": sum(
                event["reason"] == "critic_disagreement" for event in mask_events
            ),
        },
        "artifacts": {
            "produced": len(produced_artifacts),
            "accepted": len(accepted_artifacts),
            "gpu_hours": gpu_hours,
            "accepted_per_gpu_hour": (len(accepted_artifacts) / gpu_hours if gpu_hours else 0.0),
        },
        "event_sha256": [event["event_sha256"] for event in normalized_events],
        "limitations": normalized_source["limitations"],
    }
    validate_campaign_document(Path(repo_root), telemetry, kind="telemetry")
    return telemetry


def validate_campaign_telemetry_replay(
    telemetry: Mapping[str, Any],
    *,
    repo_root: Path,
    source: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> None:
    """Reject telemetry whose schema-valid values drifted from the events."""

    validate_campaign_document(Path(repo_root), telemetry, kind="telemetry")
    expected = reconcile_campaign_telemetry(
        repo_root=repo_root,
        source=source,
        events=events,
    )
    if dict(telemetry) != expected:
        raise CampaignTelemetryError("campaign telemetry replay mismatch")


__all__ = [
    "CAMPAIGN_KINDS",
    "CODEX_INTERVENTIONS",
    "CampaignTelemetryError",
    "EVENT_KINDS",
    "EVENT_SCHEMA",
    "MASK_OUTCOMES",
    "OUTPUT_SCHEMA",
    "ROUTES",
    "SOURCE_SCHEMA",
    "build_telemetry_event",
    "reconcile_campaign_telemetry",
    "validate_campaign_telemetry_replay",
    "validate_telemetry_event",
]
