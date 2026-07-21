from __future__ import annotations

import pytest

from maskfactory.selective_autonomy_e2e_static import (
    REQUIRED_PIPELINE_STAGES,
    SelectiveAutonomyE2EStaticError,
    bind_stage_module_contracts,
    evaluate_headline_channel_separation,
    evaluate_stage_order,
    refuse_e2e_overclaim,
    run_selective_autonomy_e2e_static_suite,
)
from maskfactory.validation import validate_document


def test_stage_modules_importable() -> None:
    bindings = bind_stage_module_contracts()
    assert set(bindings) == set(REQUIRED_PIPELINE_STAGES)
    assert all(row["import_ok"] for row in bindings.values())


def test_stage_order_fail_closed() -> None:
    ok = evaluate_stage_order(REQUIRED_PIPELINE_STAGES)
    assert ok["order_matches_required"] is True
    with pytest.raises(SelectiveAutonomyE2EStaticError, match="stage_order_invalid"):
        evaluate_stage_order(("generate", "audit"))


def test_headline_conflation_refused() -> None:
    ok = evaluate_headline_channel_separation(
        {
            "quality": {"ordinary_part_mean_iou_reported": False},
            "labor": {"zero_touch_fraction_reported": False},
            "measured_production_authority": False,
            "blinded_holdout_authority": False,
        }
    )
    assert ok["channels_separate"] is True
    with pytest.raises(SelectiveAutonomyE2EStaticError, match="headline_conflation"):
        evaluate_headline_channel_separation(
            {
                "quality": {"a": 1},
                "labor": {"b": 2},
                "quality_labor_score": 0.9,
            }
        )


def test_overclaim_fail_closed() -> None:
    with pytest.raises(SelectiveAutonomyE2EStaticError, match="mf_p9_15_08_complete"):
        refuse_e2e_overclaim({"mf_p9_15_08_complete": True})


def test_suite_seals_schema_valid_static_report() -> None:
    report = run_selective_autonomy_e2e_static_suite()
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["mf_p9_15_08_complete"] is False
    assert report["live_generate_critic_repair_certify_audit_demo"] is False
    assert report["required_pipeline_stages"] == list(REQUIRED_PIPELINE_STAGES)
    assert report["stage_order_negative_fixture_blocked"] is True
    assert report["headline_conflation_negative_fixture_blocked"] is True
    assert report["completion_overclaim_negative_fixture_blocked"] is True
    assert report["report_id"].startswith("sae2e_")
    assert validate_document(report, "selective_autonomy_e2e_static_report") == ()
