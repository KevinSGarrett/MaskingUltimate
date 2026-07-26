from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from maskfactory.steward.campaign_slo import (
    CampaignSloError,
    evaluate_campaign_slo,
    validate_campaign_slo_replay,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _telemetry(*, kind: str = "engineering") -> dict:
    mask_counts = {
        "accept": 100 if kind in {"mask", "mixed"} else 0,
        "repair": 0,
        "abstain": 0,
        "reject": 0,
        "quarantine": 0,
        "hard_qa_vetoes": 0,
        "critic_disagreements": 0,
    }
    eligible = 25 if kind in {"engineering", "mixed"} else 100
    return {
        "schema_version": "maskfactory_self_hosted_autonomy_campaign_telemetry.v1",
        "campaign_id": f"{kind}-campaign-target",
        "campaign_kind": kind,
        "campaign_payload_sha256": _digest(f"{kind}-payload"),
        "source_commit_sha256": _digest("commit"),
        "started_at": "2026-07-26T18:00:00Z",
        "ended_at": "2026-07-26T19:00:00Z",
        "counts": {
            "planned": eligible,
            "eligible": eligible,
            "completed": eligible,
            "autonomously_prepared": int(eligible * 0.8),
            "accepted": int(eligible * 0.8),
        },
        "codex": {
            "interventions": 1,
            "routine_handoffs": 1 if kind != "mixed" else 2,
            "review_seconds": 120,
            "baseline_usage_units_per_accepted_artifact": 100,
            "observed_usage_units_per_accepted_artifact": 30,
        },
        "timing": {
            "model_startup_seconds": 10,
            "inference_seconds": 100,
            "idle_gpu_seconds": 0,
            "local_gpu_work_cells": 2,
            "local_gpu_released_work_cells": 2,
        },
        "routes": {
            "local_pod": 2,
            "serverless": 0,
            "openrouter_advisory": 0,
            "cpu_safe": eligible - 2,
            "fallback_reasons": [],
        },
        "integrity": {
            "duplicate_inference_submissions": 0,
            "duplicate_promotions": 0,
            "admitted_missions": eligible,
            "terminally_reconciled_missions": eligible,
            "submitted_unknown_events": 0,
            "recovery_required_events": 0,
            "recovery_resolved_events": 0,
            "authority_bypasses": 0,
        },
        "engineering": {
            "patch_attempts": 1,
            "focused_test_runs": 1,
            "repair_attempts": 0,
            "repair_exhaustions": 0,
        },
        "masks": mask_counts,
        "artifacts": {
            "produced": eligible,
            "accepted": int(eligible * 0.8),
            "gpu_hours": 1,
            "accepted_per_gpu_hour": int(eligible * 0.8),
        },
        "event_sha256": [],
        "limitations": ["Target evaluator fixture; no real campaign claim."],
    }


@pytest.mark.parametrize("kind", ["engineering", "mask", "mixed"])
def test_target_campaign_passes_exact_slo_evaluation(kind: str) -> None:
    telemetry = _telemetry(kind=kind)
    result = evaluate_campaign_slo(telemetry, repo_root=REPO_ROOT)

    assert result["passed"] is True
    assert all(result["gates"].values())
    assert result["metrics"]["autonomously_prepared_fraction"] == 0.8
    assert result["metrics"]["codex_usage_reduction_fraction"] == 0.7
    assert result["metrics"]["routine_handoffs_per_campaign_bound"] == 1
    validate_campaign_slo_replay(
        result,
        telemetry=telemetry,
        repo_root=REPO_ROOT,
    )


@pytest.mark.parametrize(
    ("path", "value", "failed_gate"),
    [
        (("counts", "autonomously_prepared"), 19, "autonomous_preparation"),
        (("codex", "routine_handoffs"), 2, "handoff_suppression"),
        (
            ("codex", "observed_usage_units_per_accepted_artifact"),
            31,
            "codex_reduction",
        ),
        (
            ("integrity", "duplicate_inference_submissions"),
            1,
            "zero_duplicates",
        ),
        (("integrity", "duplicate_promotions"), 1, "zero_duplicates"),
        (
            ("integrity", "terminally_reconciled_missions"),
            24,
            "full_terminal_reconciliation",
        ),
        (
            ("timing", "local_gpu_released_work_cells"),
            1,
            "full_local_gpu_release",
        ),
        (("integrity", "authority_bypasses"), 1, "no_authority_bypass"),
    ],
)
def test_each_under_target_measure_fails_its_gate(
    path: tuple[str, str],
    value: int,
    failed_gate: str,
) -> None:
    telemetry = _telemetry()
    telemetry[path[0]][path[1]] = value

    result = evaluate_campaign_slo(telemetry, repo_root=REPO_ROOT)

    assert result["passed"] is False
    assert result["gates"][failed_gate] is False


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("counts", "eligible"), 0, "autonomous preparation denominator"),
        (
            ("codex", "baseline_usage_units_per_accepted_artifact"),
            0,
            "baseline must be positive",
        ),
        (
            ("integrity", "admitted_missions"),
            0,
            "terminal reconciliation denominator",
        ),
        (
            ("timing", "local_gpu_released_work_cells"),
            3,
            "released local GPU work cells exceed",
        ),
    ],
)
def test_missing_or_contradictory_denominators_fail_closed(
    path: tuple[str, str],
    value: int,
    message: str,
) -> None:
    telemetry = _telemetry()
    telemetry[path[0]][path[1]] = value

    with pytest.raises(CampaignSloError, match=message):
        evaluate_campaign_slo(telemetry, repo_root=REPO_ROOT)


def test_zero_local_work_cells_is_vacuously_fully_released() -> None:
    telemetry = _telemetry()
    telemetry["timing"]["local_gpu_work_cells"] = 0
    telemetry["timing"]["local_gpu_released_work_cells"] = 0

    result = evaluate_campaign_slo(telemetry, repo_root=REPO_ROOT)

    assert result["metrics"]["local_gpu_release_fraction"] == 1
    assert result["gates"]["full_local_gpu_release"] is True


def test_schema_missing_measure_fails_closed() -> None:
    telemetry = _telemetry()
    del telemetry["codex"]["routine_handoffs"]

    with pytest.raises(CampaignSloError, match="contract failed"):
        evaluate_campaign_slo(telemetry, repo_root=REPO_ROOT)


def test_schema_valid_rehashed_result_drift_fails_replay() -> None:
    telemetry = _telemetry()
    result = evaluate_campaign_slo(telemetry, repo_root=REPO_ROOT)
    drifted = copy.deepcopy(result)
    drifted["metrics"]["routine_handoffs_per_campaign_bound"] = 0
    drifted["result_sha256"] = "0" * 64
    from maskfactory.steward.continuous_contract import canonical_sha256

    drifted["result_sha256"] = canonical_sha256(drifted)

    with pytest.raises(CampaignSloError, match="replay mismatch"):
        validate_campaign_slo_replay(
            drifted,
            telemetry=telemetry,
            repo_root=REPO_ROOT,
        )
