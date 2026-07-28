"""Fail-closed Plan-27 sustained-target evaluation for campaign telemetry."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from .continuous_contract import (
    ContinuousContractError,
    canonical_sha256,
    validate_campaign_document,
)

SLO_SCHEMA = "maskfactory.steward.campaign_slo_evaluation.v1"
ZERO_SHA256 = "0" * 64
AUTONOMOUS_PREPARATION_TARGET = 0.8
CODEX_REDUCTION_TARGET = 0.7
ENGINEERING_CAMPAIGN_BOUND = 25
MASK_CAMPAIGN_BOUND = 100
GATE_FIELDS = {
    "autonomous_preparation",
    "handoff_suppression",
    "codex_reduction",
    "zero_duplicates",
    "full_terminal_reconciliation",
    "full_local_gpu_release",
    "no_authority_bypass",
}
METRIC_FIELDS = {
    "autonomously_prepared_fraction",
    "routine_handoffs_per_campaign_bound",
    "codex_usage_reduction_fraction",
    "duplicate_inference_submissions",
    "duplicate_promotions",
    "terminal_reconciliation_fraction",
    "local_gpu_release_fraction",
    "authority_bypasses",
}


class CampaignSloError(ValueError):
    """Campaign telemetry is insufficient or invalid for SLO evaluation."""


def _ratio(numerator: int | float, denominator: int | float, *, field: str) -> float:
    if denominator <= 0:
        raise CampaignSloError(f"{field} denominator must be positive")
    return float(numerator) / float(denominator)


def _bound_equivalents(telemetry: Mapping[str, Any]) -> float:
    kind = telemetry["campaign_kind"]
    eligible = telemetry["counts"]["eligible"]
    mask_records = sum(
        telemetry["masks"][outcome]
        for outcome in ("accept", "repair", "abstain", "reject", "quarantine")
    )
    if kind == "engineering":
        return _ratio(
            eligible,
            ENGINEERING_CAMPAIGN_BOUND,
            field="engineering campaign bound",
        )
    if kind == "mask":
        return _ratio(
            mask_records,
            MASK_CAMPAIGN_BOUND,
            field="mask campaign bound",
        )
    engineering_bounds = _ratio(
        eligible,
        ENGINEERING_CAMPAIGN_BOUND,
        field="mixed engineering campaign bound",
    )
    mask_bounds = _ratio(
        mask_records,
        MASK_CAMPAIGN_BOUND,
        field="mixed mask campaign bound",
    )
    return engineering_bounds + mask_bounds


def evaluate_campaign_slo(
    telemetry: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Derive exact Plan-27 target metrics from one closed telemetry record."""

    try:
        validate_campaign_document(Path(repo_root), telemetry, kind="telemetry")
    except ContinuousContractError as exc:
        raise CampaignSloError(f"campaign telemetry contract failed: {exc}") from exc
    counts = telemetry["counts"]
    codex = telemetry["codex"]
    integrity = telemetry["integrity"]
    timing = telemetry["timing"]
    autonomous_fraction = _ratio(
        counts["autonomously_prepared"],
        counts["eligible"],
        field="autonomous preparation",
    )
    campaign_bounds = _bound_equivalents(telemetry)
    handoffs_per_bound = _ratio(
        codex["routine_handoffs"],
        campaign_bounds,
        field="routine handoffs per campaign bound",
    )
    baseline = codex["baseline_usage_units_per_accepted_artifact"]
    if baseline <= 0:
        raise CampaignSloError("Codex usage baseline must be positive")
    observed = codex["observed_usage_units_per_accepted_artifact"]
    codex_reduction = max(0.0, 1.0 - (float(observed) / float(baseline)))
    reconciliation_fraction = _ratio(
        integrity["terminally_reconciled_missions"],
        integrity["admitted_missions"],
        field="terminal reconciliation",
    )
    local_cells = timing["local_gpu_work_cells"]
    released_cells = timing["local_gpu_released_work_cells"]
    if released_cells > local_cells:
        raise CampaignSloError("released local GPU work cells exceed admitted cells")
    release_fraction = (
        _ratio(released_cells, local_cells, field="local GPU release") if local_cells else 1.0
    )
    metrics = {
        "autonomously_prepared_fraction": autonomous_fraction,
        "routine_handoffs_per_campaign_bound": handoffs_per_bound,
        "codex_usage_reduction_fraction": codex_reduction,
        "duplicate_inference_submissions": integrity["duplicate_inference_submissions"],
        "duplicate_promotions": integrity["duplicate_promotions"],
        "terminal_reconciliation_fraction": reconciliation_fraction,
        "local_gpu_release_fraction": release_fraction,
        "authority_bypasses": integrity["authority_bypasses"],
    }
    gates = {
        "autonomous_preparation": (autonomous_fraction >= AUTONOMOUS_PREPARATION_TARGET),
        "handoff_suppression": handoffs_per_bound <= 1.0,
        "codex_reduction": codex_reduction >= CODEX_REDUCTION_TARGET,
        "zero_duplicates": (
            metrics["duplicate_inference_submissions"] == 0 and metrics["duplicate_promotions"] == 0
        ),
        "full_terminal_reconciliation": reconciliation_fraction == 1.0,
        "full_local_gpu_release": release_fraction == 1.0,
        "no_authority_bypass": metrics["authority_bypasses"] == 0,
    }
    result = {
        "schema_version": SLO_SCHEMA,
        "campaign_id": telemetry["campaign_id"],
        "campaign_kind": telemetry["campaign_kind"],
        "campaign_telemetry_sha256": canonical_sha256(telemetry),
        "campaign_bound_equivalents": campaign_bounds,
        "metrics": metrics,
        "gates": gates,
        "passed": all(gates.values()),
        "limitations": [
            "Single-campaign target evaluation; it does not prove three consecutive mixed campaigns.",
            "Evaluation does not claim real-campaign provenance beyond the supplied validated telemetry.",
        ],
        "result_sha256": ZERO_SHA256,
    }
    result["result_sha256"] = canonical_sha256(result)
    return result


def validate_campaign_slo_replay(
    result: Mapping[str, Any],
    *,
    telemetry: Mapping[str, Any],
    repo_root: Path,
) -> None:
    """Reject self-hash, field, metric, gate, or source-telemetry drift."""

    expected_fields = {
        "schema_version",
        "campaign_id",
        "campaign_kind",
        "campaign_telemetry_sha256",
        "campaign_bound_equivalents",
        "metrics",
        "gates",
        "passed",
        "limitations",
        "result_sha256",
    }
    if set(result) != expected_fields or result.get("schema_version") != SLO_SCHEMA:
        raise CampaignSloError("campaign SLO result field or schema mismatch")
    declared = result.get("result_sha256")
    zeroed = deepcopy(dict(result))
    zeroed["result_sha256"] = ZERO_SHA256
    if declared != canonical_sha256(zeroed):
        raise CampaignSloError("campaign SLO result self-hash mismatch")
    if not isinstance(result.get("metrics"), dict) or set(result["metrics"]) != METRIC_FIELDS:
        raise CampaignSloError("campaign SLO metric field set mismatch")
    if not isinstance(result.get("gates"), dict) or set(result["gates"]) != GATE_FIELDS:
        raise CampaignSloError("campaign SLO gate field set mismatch")
    expected = evaluate_campaign_slo(telemetry, repo_root=repo_root)
    if dict(result) != expected:
        raise CampaignSloError("campaign SLO deterministic replay mismatch")


__all__ = [
    "AUTONOMOUS_PREPARATION_TARGET",
    "CODEX_REDUCTION_TARGET",
    "CampaignSloError",
    "SLO_SCHEMA",
    "evaluate_campaign_slo",
    "validate_campaign_slo_replay",
]
