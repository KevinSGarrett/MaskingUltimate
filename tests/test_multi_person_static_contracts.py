from __future__ import annotations

from maskfactory.autonomy.multi_person_static_contracts import (
    AUTHORITY,
    GATE_FAMILIES,
    PROOF_TIER,
    ROUTING_FAMILIES,
    run_multi_person_static_contract_suite,
)
from maskfactory.validation import validate_document


def test_multi_person_static_suite_passes_seeded_gates_and_routing() -> None:
    report = run_multi_person_static_contract_suite()
    assert validate_document(report, "multi_person_static_contracts_report") == ()
    assert report["proof_tier"] == PROOF_TIER
    assert report["authority"] == AUTHORITY
    assert set(report["seeded_gate_blocks"]) == set(GATE_FAMILIES)
    assert all(report["seeded_gate_blocks"].values())
    assert set(report["seeded_routing_checks"]) == set(ROUTING_FAMILIES)
    assert all(report["seeded_routing_checks"].values())
    assert report["mf_p8_11_07_demo_complete"] is False
    assert report["kevin_multi_person_sources_required"] is True
    assert report["real_10_20_image_demo_claimed"] is False
    assert report["doctor_green_claimed"] is False
    assert report["gold_claimed"] is False
    assert report["production_evidence_pass_claimed"] is False
    assert report["report_id"].startswith("mpsc_")
    assert len(report["seal_sha256"]) == 64


def test_schema_rejects_mf_p8_11_07_demo_overclaim() -> None:
    report = run_multi_person_static_contract_suite()
    report["mf_p8_11_07_demo_complete"] = True
    issues = validate_document(report, "multi_person_static_contracts_report")
    assert issues
    assert report["kevin_multi_person_sources_required"] is True
