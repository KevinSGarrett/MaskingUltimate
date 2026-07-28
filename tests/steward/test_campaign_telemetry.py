from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.steward.campaign_telemetry import (
    CampaignTelemetryError,
    build_telemetry_event,
    reconcile_campaign_telemetry,
    validate_campaign_telemetry_replay,
)

ZERO_SHA256 = "0" * 64
REPO_ROOT = Path(__file__).resolve().parents[2]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _source() -> dict:
    return {
        "schema_version": "maskfactory.campaign-telemetry-source.v1",
        "campaign_id": "engineering-campaign-025",
        "campaign_kind": "engineering",
        "campaign_payload_sha256": _digest("campaign"),
        "source_commit_sha256": _digest("commit"),
        "started_at": "2026-07-26T06:00:00Z",
        "ended_at": "2026-07-26T07:00:00Z",
        "baseline_usage_units_per_accepted_artifact": 100.0,
        "limitations": ["Static reconciliation fixture; no production campaign claim."],
    }


def _events() -> list[dict]:
    raw: list[dict] = []

    def add(kind: str, mission: str | None = None, **kwargs: object) -> None:
        raw.append(
            build_telemetry_event(
                campaign_id="engineering-campaign-025",
                sequence=len(raw) + 1,
                kind=kind,
                mission_id=mission,
                **kwargs,
            )
        )

    for index in range(25):
        mission = f"mission-{index:02d}"
        route = "local_pod" if index < 20 else "cpu_safe"
        add("planned", mission)
        add("eligible", mission)
        add("route_selected", mission, route=route)
        add("autonomously_prepared", mission)
        add("admitted", mission)
        if route == "local_pod":
            cell = f"cell-{index:02d}"
            add("local_gpu_work_cell", mission, subject_id=cell)
            add("model_startup", mission, duration_seconds=2)
            add("inference_submission", mission, subject_id=f"submission-{index:02d}")
            add("inference", mission, duration_seconds=10)
            add("local_gpu_release", mission, subject_id=cell)
        add("patch_attempt", mission)
        add("focused_test_run", mission)
        if index < 3:
            add("repair_attempt", mission)
        add("completed", mission)
        add("artifact_produced", mission, subject_id=f"artifact-{index:02d}")
        if index < 20:
            add("accepted", mission)
            add("artifact_accepted", mission, subject_id=f"artifact-{index:02d}")
        add("terminal_reconciled", mission)
    add(
        "codex_intervention",
        value="terminal_adoption",
        duration_seconds=180,
        numeric_value=400,
    )
    return raw


def _reseal_event(event: dict) -> dict:
    event = copy.deepcopy(event)
    event["event_sha256"] = ZERO_SHA256
    event["event_sha256"] = hashlib.sha256(
        json.dumps(
            event,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    return event


def test_25_mission_telemetry_reconciles_ledger_and_artifact_facts() -> None:
    source = _source()
    events = _events()

    telemetry = reconcile_campaign_telemetry(
        repo_root=REPO_ROOT,
        source=source,
        events=events,
    )

    assert telemetry["counts"] == {
        "planned": 25,
        "eligible": 25,
        "completed": 25,
        "autonomously_prepared": 25,
        "accepted": 20,
    }
    assert telemetry["routes"] == {
        "local_pod": 20,
        "serverless": 0,
        "openrouter_advisory": 0,
        "cpu_safe": 5,
        "fallback_reasons": [],
    }
    assert telemetry["timing"]["local_gpu_work_cells"] == 20
    assert telemetry["timing"]["local_gpu_released_work_cells"] == 20
    assert telemetry["integrity"]["terminally_reconciled_missions"] == 25
    assert telemetry["integrity"]["duplicate_inference_submissions"] == 0
    assert telemetry["engineering"]["repair_attempts"] == 3
    assert telemetry["artifacts"]["produced"] == 25
    assert telemetry["artifacts"]["accepted"] == 20
    assert telemetry["codex"]["observed_usage_units_per_accepted_artifact"] == 20
    validate_campaign_telemetry_replay(
        telemetry,
        repo_root=REPO_ROOT,
        source=source,
        events=events,
    )


def test_duplicate_submissions_and_promotions_are_measured_not_hidden() -> None:
    events = _events()
    duplicate_submission = next(
        event for event in events if event["kind"] == "inference_submission"
    )
    duplicate_promotion = build_telemetry_event(
        campaign_id="engineering-campaign-025",
        sequence=len(events) + 1,
        kind="promotion",
        mission_id="mission-00",
        subject_id="promotion-00",
    )
    events.append(duplicate_promotion)
    events.append(
        build_telemetry_event(
            campaign_id="engineering-campaign-025",
            sequence=len(events) + 1,
            kind="promotion",
            mission_id="mission-01",
            subject_id="promotion-00",
        )
    )
    events.append(
        build_telemetry_event(
            campaign_id="engineering-campaign-025",
            sequence=len(events) + 1,
            kind="inference_submission",
            mission_id="mission-01",
            subject_id=duplicate_submission["subject_id"],
        )
    )

    telemetry = reconcile_campaign_telemetry(
        repo_root=REPO_ROOT,
        source=_source(),
        events=events,
    )

    assert telemetry["integrity"]["duplicate_inference_submissions"] == 1
    assert telemetry["integrity"]["duplicate_promotions"] == 1


def test_route_omission_or_dual_route_fails_closed() -> None:
    events = _events()
    events = [
        event
        for event in events
        if not (event["kind"] == "route_selected" and event["mission_id"] == "mission-00")
    ]
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        events[sequence - 1] = _reseal_event(event)

    with pytest.raises(CampaignTelemetryError, match="exactly one governed route"):
        reconcile_campaign_telemetry(
            repo_root=REPO_ROOT,
            source=_source(),
            events=events,
        )


def test_unmatched_gpu_release_fails_closed() -> None:
    events = _events()
    release = next(event for event in events if event["kind"] == "local_gpu_release")
    release["subject_id"] = "foreign-cell"
    index = events.index(release)
    events[index] = _reseal_event(release)

    with pytest.raises(CampaignTelemetryError, match="matching work cell"):
        reconcile_campaign_telemetry(
            repo_root=REPO_ROOT,
            source=_source(),
            events=events,
        )


def test_accepted_artifact_without_produced_evidence_fails_closed() -> None:
    events = _events()
    events = [
        event
        for event in events
        if not (event["kind"] == "artifact_produced" and event["subject_id"] == "artifact-00")
    ]
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        events[sequence - 1] = _reseal_event(event)

    with pytest.raises(CampaignTelemetryError, match="was not produced"):
        reconcile_campaign_telemetry(
            repo_root=REPO_ROOT,
            source=_source(),
            events=events,
        )


def test_duplicate_artifact_or_release_evidence_fails_closed() -> None:
    events = _events()
    produced = next(event for event in events if event["kind"] == "artifact_produced")
    events.append(
        build_telemetry_event(
            campaign_id="engineering-campaign-025",
            sequence=len(events) + 1,
            kind="artifact_produced",
            mission_id="mission-01",
            subject_id=produced["subject_id"],
        )
    )

    with pytest.raises(CampaignTelemetryError, match="artifact evidence is duplicated"):
        reconcile_campaign_telemetry(
            repo_root=REPO_ROOT,
            source=_source(),
            events=events,
        )


def test_duplicate_release_evidence_fails_closed() -> None:
    events = _events()
    release = next(event for event in events if event["kind"] == "local_gpu_release")
    events.append(
        build_telemetry_event(
            campaign_id="engineering-campaign-025",
            sequence=len(events) + 1,
            kind="local_gpu_release",
            mission_id="mission-01",
            subject_id=release["subject_id"],
        )
    )

    with pytest.raises(CampaignTelemetryError, match="release evidence is duplicated"):
        reconcile_campaign_telemetry(
            repo_root=REPO_ROOT,
            source=_source(),
            events=events,
        )


def test_codex_usage_without_accepted_artifact_fails_closed() -> None:
    events = [
        event for event in _events() if event["kind"] not in {"accepted", "artifact_accepted"}
    ]
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        events[sequence - 1] = _reseal_event(event)

    with pytest.raises(
        CampaignTelemetryError,
        match="undefined with zero accepted artifacts",
    ):
        reconcile_campaign_telemetry(
            repo_root=REPO_ROOT,
            source=_source(),
            events=events,
        )


def test_event_self_hash_drift_fails_closed() -> None:
    events = _events()
    events[0]["mission_id"] = "drifted"

    with pytest.raises(CampaignTelemetryError, match="self-hash mismatch"):
        reconcile_campaign_telemetry(
            repo_root=REPO_ROOT,
            source=_source(),
            events=events,
        )


def test_recovery_mask_and_failure_metrics_are_exact() -> None:
    events = _events()
    for kind, reason, value in (
        ("recovery_required", None, None),
        ("recovery_resolved", None, None),
        ("submitted_unknown", None, None),
        ("repair_exhaustion", None, None),
        ("mask_terminal", "hard_qa_veto", "reject"),
        ("mask_terminal", "critic_disagreement", "abstain"),
    ):
        events.append(
            build_telemetry_event(
                campaign_id="engineering-campaign-025",
                sequence=len(events) + 1,
                kind=kind,
                mission_id="mission-00",
                reason=reason,
                value=value,
            )
        )

    telemetry = reconcile_campaign_telemetry(
        repo_root=REPO_ROOT,
        source=_source(),
        events=events,
    )

    assert telemetry["integrity"]["recovery_required_events"] == 1
    assert telemetry["integrity"]["recovery_resolved_events"] == 1
    assert telemetry["integrity"]["submitted_unknown_events"] == 1
    assert telemetry["engineering"]["repair_exhaustions"] == 1
    assert telemetry["masks"]["reject"] == 1
    assert telemetry["masks"]["abstain"] == 1
    assert telemetry["masks"]["hard_qa_vetoes"] == 1
    assert telemetry["masks"]["critic_disagreements"] == 1


def test_schema_valid_but_rehashed_telemetry_drift_is_rejected() -> None:
    source = _source()
    events = _events()
    telemetry = reconcile_campaign_telemetry(
        repo_root=REPO_ROOT,
        source=source,
        events=events,
    )
    telemetry["engineering"]["repair_attempts"] = 99

    with pytest.raises(CampaignTelemetryError, match="replay mismatch"):
        validate_campaign_telemetry_replay(
            telemetry,
            repo_root=REPO_ROOT,
            source=source,
            events=events,
        )
