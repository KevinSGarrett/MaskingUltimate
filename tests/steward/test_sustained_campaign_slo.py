from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from maskfactory.steward.campaign_slo import evaluate_campaign_slo
from maskfactory.steward.campaign_telemetry import (
    CampaignTelemetryError,
    build_telemetry_event,
    reconcile_campaign_telemetry,
)
from maskfactory.steward.continuous_contract import canonical_sha256
from maskfactory.steward.handoff_suppression import audit_campaign_handoffs
from maskfactory.steward.sustained_campaign_slo import (
    SustainedCampaignSloError,
    evaluate_sustained_campaign_slo,
    validate_sustained_campaign_slo_replay,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _record(index: int, *, sequence: int | None = None) -> dict:
    campaign_id = f"mixed-campaign-{index:03d}"
    started = datetime(2026, 7, 26, 10 + index, tzinfo=UTC)
    ended = started + timedelta(minutes=30)
    source = {
        "schema_version": "maskfactory.campaign-telemetry-source.v1",
        "campaign_id": campaign_id,
        "campaign_kind": "mixed",
        "campaign_payload_sha256": _digest(f"payload-{index}"),
        "source_commit_sha256": _digest("source-commit"),
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "ended_at": ended.isoformat().replace("+00:00", "Z"),
        "baseline_usage_units_per_accepted_artifact": 100,
        "limitations": ["Replay fixture; not real production campaign evidence."],
    }
    events: list[dict] = []

    def add(kind: str, mission_id: str | None = None, **kwargs: object) -> None:
        events.append(
            build_telemetry_event(
                campaign_id=campaign_id,
                sequence=len(events) + 1,
                kind=kind,
                mission_id=mission_id,
                **kwargs,
            )
        )

    for mission_index in range(25):
        mission_id = f"mission-{mission_index:02d}"
        add("planned", mission_id)
        add("eligible", mission_id)
        add("route_selected", mission_id, route="cpu_safe")
        if mission_index < 20:
            add("autonomously_prepared", mission_id)
        add("admitted", mission_id)
        add("completed", mission_id)
        artifact_id = f"artifact-{mission_index:02d}"
        add("artifact_produced", mission_id, subject_id=artifact_id)
        if mission_index < 20:
            add("accepted", mission_id)
            add("artifact_accepted", mission_id, subject_id=artifact_id)
        add("terminal_reconciled", mission_id)
    for mask_index in range(100):
        add(
            "mask_terminal",
            f"mission-{mask_index % 25:02d}",
            value="accept",
            reason="accepted",
        )
    add(
        "codex_intervention",
        value="terminal_adoption",
        duration_seconds=60,
        numeric_value=400,
    )
    telemetry = reconcile_campaign_telemetry(
        repo_root=REPO_ROOT,
        source=source,
        events=events,
    )
    slo = evaluate_campaign_slo(telemetry, repo_root=REPO_ROOT)
    terminal_packet = _digest(f"terminal-packet-{index}")
    handoff = audit_campaign_handoffs(
        campaign_id=campaign_id,
        telemetry_events=events,
        exception_records=[],
        terminal_adoption_packet_sha256=terminal_packet,
    )
    return {
        "campaign_sequence": index if sequence is None else sequence,
        "source": source,
        "events": events,
        "telemetry": telemetry,
        "exception_records": [],
        "handoff_audit": handoff,
        "slo": slo,
        "terminal_adoption_packet_sha256": terminal_packet,
    }


def _records() -> list[dict]:
    return [_record(1), _record(2), _record(3)]


def test_three_replayed_mixed_campaigns_pass_sustained_gate() -> None:
    records = _records()

    result = evaluate_sustained_campaign_slo(records, repo_root=REPO_ROOT)

    assert result["passed"] is True
    assert all(result["gates"].values())
    assert result["campaign_sequences"] == [1, 2, 3]
    assert result["metrics"] == {
        "minimum_autonomously_prepared_fraction": 0.8,
        "maximum_routine_handoffs_per_campaign_bound": 0.0,
        "minimum_codex_usage_reduction_fraction": 0.8,
        "duplicate_inference_submissions": 0,
        "duplicate_promotions": 0,
        "minimum_terminal_reconciliation_fraction": 1.0,
        "minimum_local_gpu_release_fraction": 1.0,
        "authority_bypasses": 0,
    }
    validate_sustained_campaign_slo_replay(
        result,
        campaign_records=records,
        repo_root=REPO_ROOT,
    )


@pytest.mark.parametrize("count", [0, 1, 2, 4])
def test_exactly_three_campaigns_are_required(count: int) -> None:
    with pytest.raises(SustainedCampaignSloError, match="exactly three"):
        evaluate_sustained_campaign_slo(
            [_record(index + 1) for index in range(count)],
            repo_root=REPO_ROOT,
        )


def test_noncontiguous_duplicate_nonmixed_and_overlapping_records_fail_closed() -> None:
    noncontiguous = [_record(1), _record(2, sequence=4), _record(3, sequence=5)]
    with pytest.raises(SustainedCampaignSloError, match="ordered and contiguous"):
        evaluate_sustained_campaign_slo(noncontiguous, repo_root=REPO_ROOT)

    duplicate = _records()
    duplicate[1]["source"]["campaign_id"] = duplicate[0]["source"]["campaign_id"]
    duplicate[1]["telemetry"]["campaign_id"] = duplicate[0]["telemetry"]["campaign_id"]
    with pytest.raises(CampaignTelemetryError, match="binding mismatch"):
        evaluate_sustained_campaign_slo(duplicate, repo_root=REPO_ROOT)

    nonmixed = _records()
    nonmixed[1]["source"]["campaign_kind"] = "engineering"
    with pytest.raises(CampaignTelemetryError, match="replay mismatch"):
        evaluate_sustained_campaign_slo(nonmixed, repo_root=REPO_ROOT)

    overlapping = _records()
    overlapping[1]["source"]["started_at"] = overlapping[0]["source"]["started_at"]
    overlapping[1]["source"]["ended_at"] = overlapping[0]["source"]["ended_at"]
    overlapping[1]["telemetry"] = reconcile_campaign_telemetry(
        repo_root=REPO_ROOT,
        source=overlapping[1]["source"],
        events=overlapping[1]["events"],
    )
    overlapping[1]["slo"] = evaluate_campaign_slo(
        overlapping[1]["telemetry"],
        repo_root=REPO_ROOT,
    )
    with pytest.raises(SustainedCampaignSloError, match="overlap"):
        evaluate_sustained_campaign_slo(overlapping, repo_root=REPO_ROOT)


def test_under_target_campaign_keeps_sustained_claim_false() -> None:
    records = _records()
    source = records[1]["source"]
    events = [
        event
        for event in records[1]["events"]
        if not (
            event["kind"] == "autonomously_prepared"
            and event["mission_id"] == "mission-19"
        )
    ]
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        event["event_sha256"] = "0" * 64
        event["event_sha256"] = canonical_sha256(event)
    telemetry = reconcile_campaign_telemetry(
        repo_root=REPO_ROOT,
        source=source,
        events=events,
    )
    records[1]["events"] = events
    records[1]["telemetry"] = telemetry
    records[1]["slo"] = evaluate_campaign_slo(telemetry, repo_root=REPO_ROOT)
    records[1]["handoff_audit"] = audit_campaign_handoffs(
        campaign_id=telemetry["campaign_id"],
        telemetry_events=events,
        exception_records=[],
        terminal_adoption_packet_sha256=records[1][
            "terminal_adoption_packet_sha256"
        ],
    )

    result = evaluate_sustained_campaign_slo(records, repo_root=REPO_ROOT)

    assert result["passed"] is False
    assert result["gates"]["all_campaign_slos_passed"] is False
    assert result["gates"]["autonomous_preparation_target"] is False


def test_rehashed_sustained_result_drift_fails_replay() -> None:
    records = _records()
    result = evaluate_sustained_campaign_slo(records, repo_root=REPO_ROOT)
    drifted = copy.deepcopy(result)
    drifted["limitations"][0] = "Invented production provenance."
    drifted["result_sha256"] = "0" * 64
    drifted["result_sha256"] = canonical_sha256(drifted)

    with pytest.raises(SustainedCampaignSloError, match="replay mismatch"):
        validate_sustained_campaign_slo_replay(
            drifted,
            campaign_records=records,
            repo_root=REPO_ROOT,
        )
