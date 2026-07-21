from __future__ import annotations

from maskfactory.lanes.specialist_static_contracts import (
    AUTHORITY,
    LANE_FAMILIES,
    PANEL_FAMILIES,
    PROOF_TIER,
    ROUTING_FAMILIES,
    SPECIALIST_LABELS,
    run_specialist_static_contract_suite,
)
from maskfactory.validation import validate_document


def test_specialist_static_suite_passes_lanes_panels_and_routing() -> None:
    report = run_specialist_static_contract_suite()
    assert validate_document(report, "specialist_static_contracts_report") == ()
    assert report["proof_tier"] == PROOF_TIER
    assert report["authority"] == AUTHORITY
    assert set(report["specialist_labels"]) == set(SPECIALIST_LABELS)
    assert set(report["seeded_lane_checks"]) == set(LANE_FAMILIES)
    assert all(report["seeded_lane_checks"].values())
    assert set(report["seeded_panel_checks"]) == set(PANEL_FAMILIES)
    assert all(report["seeded_panel_checks"].values())
    assert set(report["seeded_routing_checks"]) == set(ROUTING_FAMILIES)
    assert all(report["seeded_routing_checks"].values())
    assert report["mf_p3_07_01_sop_cadence_complete"] is False
    assert report["mf_p3_07_02_100_certified_complete"] is False
    assert report["mf_p3_07_03_labor_metrics_complete"] is False
    assert report["mf_p3_07_04_second_look_complete"] is False
    assert report["mf_p3_exit_complete"] is False
    assert report["kevin_sop_cadence_required"] is True
    assert report["certified_package_count"] == 0
    assert report["doctor_green_claimed"] is False
    assert report["gold_claimed"] is False
    assert report["production_evidence_pass_claimed"] is False
    assert report["report_id"].startswith("ssc_")
    assert len(report["seal_sha256"]) == 64


def test_schema_rejects_p3_07_and_exit_overclaims() -> None:
    report = run_specialist_static_contract_suite()
    report["mf_p3_07_02_100_certified_complete"] = True
    report["mf_p3_exit_complete"] = True
    report["certified_package_count"] = 100
    issues = validate_document(report, "specialist_static_contracts_report")
    assert issues
    assert report["kevin_sop_cadence_required"] is True
