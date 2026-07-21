from __future__ import annotations

import pytest

from maskfactory.selective_autonomy_targets_static import (
    EXPECTED_LABOR_TARGETS,
    EXPECTED_QUALITY_TARGETS,
    HARD_ANATOMY_SCOPES,
    REQUIRED_ANTI_COLLAPSE_BUCKETS,
    SelectiveAutonomyTargetsStaticError,
    bind_labor_targets_from_config,
    bind_quality_targets_from_config,
    evaluate_anti_bucket_collapse,
    evaluate_review_time_proxy_refusal,
    refuse_labor_overclaim,
    refuse_quality_overclaim,
    run_selective_autonomy_targets_static_suite,
)
from maskfactory.validation import validate_document


def test_config_binds_frozen_quality_and_labor_targets() -> None:
    quality = bind_quality_targets_from_config()
    labor = bind_labor_targets_from_config()
    assert quality == EXPECTED_QUALITY_TARGETS
    assert labor == EXPECTED_LABOR_TARGETS


def test_anti_bucket_collapse_blocks_aggregate_hide() -> None:
    ok = evaluate_anti_bucket_collapse(
        {
            "aggregate_pass": True,
            "bucket_passes": {name: True for name in REQUIRED_ANTI_COLLAPSE_BUCKETS},
            "hard_anatomy_scope_passes": {name: True for name in HARD_ANATOMY_SCOPES},
        }
    )
    assert ok["aggregate_cannot_hide_failing_bucket"] is True

    with pytest.raises(SelectiveAutonomyTargetsStaticError, match="bucket_collapse_hidden"):
        evaluate_anti_bucket_collapse(
            {
                "aggregate_pass": True,
                "bucket_passes": {
                    **{name: True for name in REQUIRED_ANTI_COLLAPSE_BUCKETS},
                    "hard_bucket": False,
                },
                "hard_anatomy_scope_passes": {name: True for name in HARD_ANATOMY_SCOPES},
            }
        )


def test_review_time_proxy_refused() -> None:
    ok = evaluate_review_time_proxy_refusal({"labor_authority": "measured_production_report"})
    assert ok["requires_measured_production_denominators"] is True

    with pytest.raises(SelectiveAutonomyTargetsStaticError, match="review_time_proxy"):
        evaluate_review_time_proxy_refusal(
            {
                "labor_authority": "review_time_proxy",
                "review_minutes_per_image": 8.0,
            }
        )


def test_overclaim_flags_fail_closed() -> None:
    with pytest.raises(SelectiveAutonomyTargetsStaticError, match="quality_overclaim"):
        refuse_quality_overclaim({"mf_p9_15_01_complete": True})
    with pytest.raises(SelectiveAutonomyTargetsStaticError, match="labor_overclaim"):
        refuse_labor_overclaim({"production_labor_measured": True})


def test_suite_seals_schema_valid_static_report() -> None:
    report = run_selective_autonomy_targets_static_suite()
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["mf_p9_15_01_complete"] is False
    assert report["mf_p9_15_03_complete"] is False
    assert report["blinded_human_anchor_holdout_measured"] is False
    assert report["production_labor_measured"] is False
    assert report["anti_collapse_negative_fixture_blocked"] is True
    assert report["labor_proxy_negative_fixture_blocked"] is True
    assert report["report_id"].startswith("sats_")
    assert validate_document(report, "selective_autonomy_targets_static_report") == ()
