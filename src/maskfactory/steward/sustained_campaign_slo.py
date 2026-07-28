"""Replay-backed acceptance gate for three consecutive mixed campaigns."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from .campaign_slo import validate_campaign_slo_replay
from .campaign_telemetry import validate_campaign_telemetry_replay
from .continuous_contract import canonical_sha256
from .handoff_suppression import validate_campaign_handoff_audit_replay

SCHEMA_VERSION = "maskfactory.steward.sustained_campaign_slo.v1"
ZERO_SHA256 = "0" * 64
CAMPAIGN_COUNT = 3
_RECORD_FIELDS = {
    "campaign_sequence",
    "source",
    "events",
    "telemetry",
    "exception_records",
    "handoff_audit",
    "slo",
    "terminal_adoption_packet_sha256",
}
_GATE_FIELDS = {
    "exactly_three_campaigns",
    "all_mixed_campaigns",
    "contiguous_campaign_sequence",
    "chronological_nonoverlap",
    "all_campaign_slos_passed",
    "all_handoff_audits_passed",
    "autonomous_preparation_target",
    "handoff_suppression_target",
    "codex_reduction_target",
    "zero_duplicates",
    "full_terminal_reconciliation",
    "full_local_gpu_release",
    "no_authority_bypass",
}
_METRIC_FIELDS = {
    "minimum_autonomously_prepared_fraction",
    "maximum_routine_handoffs_per_campaign_bound",
    "minimum_codex_usage_reduction_fraction",
    "duplicate_inference_submissions",
    "duplicate_promotions",
    "minimum_terminal_reconciliation_fraction",
    "minimum_local_gpu_release_fraction",
    "authority_bypasses",
}
_RESULT_FIELDS = {
    "schema_version",
    "campaign_ids",
    "campaign_sequences",
    "campaign_telemetry_sha256",
    "campaign_slo_sha256",
    "campaign_handoff_audit_sha256",
    "terminal_adoption_packet_sha256",
    "metrics",
    "gates",
    "passed",
    "limitations",
    "result_sha256",
}


class SustainedCampaignSloError(ValueError):
    """Mixed-campaign evidence is missing, unordered, invalid, or drifted."""


def _timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise SustainedCampaignSloError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SustainedCampaignSloError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise SustainedCampaignSloError(f"{field} must include a timezone")
    return parsed


def _validate_record(
    record: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    if not isinstance(record, Mapping) or set(record) != _RECORD_FIELDS:
        raise SustainedCampaignSloError("campaign evidence record field mismatch")
    sequence = record["campaign_sequence"]
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
        raise SustainedCampaignSloError("campaign_sequence must be a positive integer")
    source = record["source"]
    events = record["events"]
    telemetry = record["telemetry"]
    exception_records = record["exception_records"]
    handoff_audit = record["handoff_audit"]
    slo = record["slo"]
    for field, value in (
        ("source", source),
        ("telemetry", telemetry),
        ("handoff_audit", handoff_audit),
        ("slo", slo),
    ):
        if not isinstance(value, Mapping):
            raise SustainedCampaignSloError(f"{field} must be an object")
    validate_campaign_telemetry_replay(
        telemetry,
        repo_root=repo_root,
        source=source,
        events=events,
    )
    validate_campaign_slo_replay(
        slo,
        telemetry=telemetry,
        repo_root=repo_root,
    )
    validate_campaign_handoff_audit_replay(
        handoff_audit,
        campaign_id=telemetry["campaign_id"],
        telemetry_events=events,
        exception_records=exception_records,
        terminal_adoption_packet_sha256=record["terminal_adoption_packet_sha256"],
    )
    if source["campaign_id"] != telemetry["campaign_id"]:
        raise SustainedCampaignSloError("source and telemetry campaign mismatch")
    return {
        "campaign_sequence": sequence,
        "source": dict(source),
        "events": list(events),
        "telemetry": dict(telemetry),
        "exception_records": list(exception_records),
        "handoff_audit": dict(handoff_audit),
        "slo": dict(slo),
        "terminal_adoption_packet_sha256": record["terminal_adoption_packet_sha256"],
    }


def evaluate_sustained_campaign_slo(
    campaign_records: Sequence[Mapping[str, Any]],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Replay and evaluate exactly three contiguous mixed campaigns."""

    if not isinstance(campaign_records, Sequence) or isinstance(campaign_records, (str, bytes)):
        raise SustainedCampaignSloError("campaign_records must be a sequence")
    if len(campaign_records) != CAMPAIGN_COUNT:
        raise SustainedCampaignSloError("exactly three mixed campaign records are required")
    records = [_validate_record(record, repo_root=Path(repo_root)) for record in campaign_records]
    sequences = [record["campaign_sequence"] for record in records]
    if sequences != list(range(sequences[0], sequences[0] + CAMPAIGN_COUNT)):
        raise SustainedCampaignSloError("campaign sequence must be ordered and contiguous")
    campaign_ids = [record["telemetry"]["campaign_id"] for record in records]
    if len(campaign_ids) != len(set(campaign_ids)):
        raise SustainedCampaignSloError("campaign IDs must be unique")
    if any(record["telemetry"]["campaign_kind"] != "mixed" for record in records):
        raise SustainedCampaignSloError("sustained acceptance requires mixed campaigns")
    starts = [
        _timestamp(record["telemetry"]["started_at"], field="started_at") for record in records
    ]
    ends = [_timestamp(record["telemetry"]["ended_at"], field="ended_at") for record in records]
    if any(starts[index] < ends[index - 1] for index in range(1, CAMPAIGN_COUNT)):
        raise SustainedCampaignSloError("campaign times overlap or are not chronological")
    slo_metrics = [record["slo"]["metrics"] for record in records]
    metrics = {
        "minimum_autonomously_prepared_fraction": min(
            value["autonomously_prepared_fraction"] for value in slo_metrics
        ),
        "maximum_routine_handoffs_per_campaign_bound": max(
            value["routine_handoffs_per_campaign_bound"] for value in slo_metrics
        ),
        "minimum_codex_usage_reduction_fraction": min(
            value["codex_usage_reduction_fraction"] for value in slo_metrics
        ),
        "duplicate_inference_submissions": sum(
            value["duplicate_inference_submissions"] for value in slo_metrics
        ),
        "duplicate_promotions": sum(value["duplicate_promotions"] for value in slo_metrics),
        "minimum_terminal_reconciliation_fraction": min(
            value["terminal_reconciliation_fraction"] for value in slo_metrics
        ),
        "minimum_local_gpu_release_fraction": min(
            value["local_gpu_release_fraction"] for value in slo_metrics
        ),
        "authority_bypasses": sum(value["authority_bypasses"] for value in slo_metrics),
    }
    gates = {
        "exactly_three_campaigns": True,
        "all_mixed_campaigns": True,
        "contiguous_campaign_sequence": True,
        "chronological_nonoverlap": True,
        "all_campaign_slos_passed": all(record["slo"]["passed"] for record in records),
        "all_handoff_audits_passed": all(record["handoff_audit"]["passed"] for record in records),
        "autonomous_preparation_target": (metrics["minimum_autonomously_prepared_fraction"] >= 0.8),
        "handoff_suppression_target": (
            metrics["maximum_routine_handoffs_per_campaign_bound"] <= 1.0
        ),
        "codex_reduction_target": (metrics["minimum_codex_usage_reduction_fraction"] >= 0.7),
        "zero_duplicates": (
            metrics["duplicate_inference_submissions"] == 0 and metrics["duplicate_promotions"] == 0
        ),
        "full_terminal_reconciliation": (
            metrics["minimum_terminal_reconciliation_fraction"] == 1.0
        ),
        "full_local_gpu_release": (metrics["minimum_local_gpu_release_fraction"] == 1.0),
        "no_authority_bypass": metrics["authority_bypasses"] == 0,
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "campaign_ids": campaign_ids,
        "campaign_sequences": sequences,
        "campaign_telemetry_sha256": [canonical_sha256(record["telemetry"]) for record in records],
        "campaign_slo_sha256": [record["slo"]["result_sha256"] for record in records],
        "campaign_handoff_audit_sha256": [
            record["handoff_audit"]["audit_sha256"] for record in records
        ],
        "terminal_adoption_packet_sha256": [
            record["terminal_adoption_packet_sha256"] for record in records
        ],
        "metrics": metrics,
        "gates": gates,
        "passed": all(gates.values()),
        "limitations": [
            "This evaluator proves three replayable campaign records; production provenance remains a separate acceptance input.",
            "Global campaign-ledger continuity must independently prove that no mixed campaign was omitted.",
        ],
        "result_sha256": ZERO_SHA256,
    }
    result["result_sha256"] = canonical_sha256(result)
    return result


def validate_sustained_campaign_slo_replay(
    result: Mapping[str, Any],
    *,
    campaign_records: Sequence[Mapping[str, Any]],
    repo_root: Path,
) -> None:
    """Reject self-hash, field, source, aggregate, or gate drift."""

    if set(result) != _RESULT_FIELDS or result.get("schema_version") != SCHEMA_VERSION:
        raise SustainedCampaignSloError("sustained SLO field or schema mismatch")
    if not isinstance(result.get("metrics"), Mapping) or set(result["metrics"]) != _METRIC_FIELDS:
        raise SustainedCampaignSloError("sustained SLO metric field mismatch")
    if not isinstance(result.get("gates"), Mapping) or set(result["gates"]) != _GATE_FIELDS:
        raise SustainedCampaignSloError("sustained SLO gate field mismatch")
    declared = result.get("result_sha256")
    zeroed = deepcopy(dict(result))
    zeroed["result_sha256"] = ZERO_SHA256
    if declared != canonical_sha256(zeroed):
        raise SustainedCampaignSloError("sustained SLO self-hash mismatch")
    expected = evaluate_sustained_campaign_slo(
        campaign_records,
        repo_root=repo_root,
    )
    if dict(result) != expected:
        raise SustainedCampaignSloError("sustained SLO deterministic replay mismatch")


__all__ = [
    "CAMPAIGN_COUNT",
    "SCHEMA_VERSION",
    "SustainedCampaignSloError",
    "evaluate_sustained_campaign_slo",
    "validate_sustained_campaign_slo_replay",
]
