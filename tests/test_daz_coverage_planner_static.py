from __future__ import annotations

import pytest

from maskfactory.datasets.coverage import ATTRIBUTES, CONTEXTS, POSES, VIEWS
from maskfactory.daz.coverage_planner_static import (
    ABLATION_CHECKS,
    ABLATION_SCENE_COUNT,
    CALIBRATION_CHECKS,
    MINIMA_CHECKS,
    OFFLINE_CHAIN_CHECKS,
    PILOT_CHECKS,
    PILOT_SCENE_COUNT,
    DazCoveragePlannerStaticError,
    build_planned_scene_stream,
    refuse_coverage_planner_overclaim,
    run_daz_coverage_planner_static_suite,
)
from maskfactory.validation import validate_document


def test_coverage_planner_overclaim_fail_closed() -> None:
    with pytest.raises(DazCoveragePlannerStaticError, match="mf_p9_10_07_pilot_complete"):
        refuse_coverage_planner_overclaim({"mf_p9_10_07_pilot_complete": True})
    with pytest.raises(
        DazCoveragePlannerStaticError, match="mf_p9_10_09_ablation_corpus_complete"
    ):
        refuse_coverage_planner_overclaim({"mf_p9_10_09_ablation_corpus_complete": True})
    with pytest.raises(DazCoveragePlannerStaticError, match="live_daz_render_executed"):
        refuse_coverage_planner_overclaim({"live_daz_render_executed": True})
    with pytest.raises(DazCoveragePlannerStaticError, match="accepted_scene_count"):
        refuse_coverage_planner_overclaim({"accepted_scene_count": 1})


def test_planned_streams_are_deterministic_and_full_marginal() -> None:
    a = build_planned_scene_stream("pilot", PILOT_SCENE_COUNT)
    b = build_planned_scene_stream("pilot", PILOT_SCENE_COUNT)
    assert a == b
    assert a["planned_scene_count"] == 1000
    assert a["accepted_scene_count"] == 0
    assert a["rendered_scene_count"] == 0
    assert a["cell_count"] == len(VIEWS) * len(POSES) * len(CONTEXTS)
    assert a["attribute_count"] == len(ATTRIBUTES)
    ablation = build_planned_scene_stream("ablation", ABLATION_SCENE_COUNT)
    assert ablation["planned_scene_count"] == 10000
    assert ablation["stream_sha256"] != a["stream_sha256"]


def test_suite_seals_schema_valid_static_report() -> None:
    report = run_daz_coverage_planner_static_suite()
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["mf_p9_10_07_pilot_complete"] is False
    assert report["mf_p9_10_08_live_calibration_complete"] is False
    assert report["mf_p9_10_09_ablation_corpus_complete"] is False
    assert report["mf_p9_10_10_accepted_coverage_complete"] is False
    assert report["live_daz_render_executed"] is False
    assert report["live_daz_accept_executed"] is False
    assert report["accepted_scene_count"] == 0
    assert report["rendered_scene_count"] == 0
    assert report["measured_from_live_pilot"] is False
    assert report["corpus_materialized_on_disk"] is False
    assert report["doctor_green_claimed"] is False
    assert report["gold_claimed"] is False
    assert report["main_complete_claimed"] is False
    assert report["production_evidence_pass_claimed"] is False
    assert set(report["offline_chain_checks"]) == set(OFFLINE_CHAIN_CHECKS)
    assert set(report["pilot_checks"]) == set(PILOT_CHECKS)
    assert set(report["calibration_checks"]) == set(CALIBRATION_CHECKS)
    assert set(report["ablation_checks"]) == set(ABLATION_CHECKS)
    assert set(report["minima_checks"]) == set(MINIMA_CHECKS)
    assert all(report["offline_chain_checks"].values())
    assert all(report["pilot_checks"].values())
    assert all(report["calibration_checks"].values())
    assert all(report["ablation_checks"].values())
    assert all(report["minima_checks"].values())
    assert report["bindings"]["planned_pilot_scenes"] == 1000
    assert report["bindings"]["planned_ablation_scenes"] == 10000
    assert report["bindings"]["reservation_bytes"] > 0
    assert report["bindings"]["accepted_coverage_complete"] is False
    assert validate_document(report, "daz_coverage_planner_static_report") == ()
