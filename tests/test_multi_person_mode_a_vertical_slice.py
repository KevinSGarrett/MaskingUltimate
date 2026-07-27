"""Focused producer tests for MF-P6-12.03 multi-person Mode A vertical slice."""

from __future__ import annotations

from pathlib import Path

from maskfactory.bridge.multi_person_mode_a_vertical_slice import (
    assess_zero_ownership_ambiguity,
    build_overlapping_contact_duo_fixture,
    evaluate_duo_mode_a_reads,
    evaluate_duo_multi_person_gate,
    run_multi_person_mode_a_vertical_slice,
    seed_cross_instance_rejection,
    seed_wrong_person_rejection,
    validate_multi_person_mode_a_vertical_slice_evidence,
)
from maskfactory.validation import schema_validator

DECIDED_AT = "2026-07-19T14:00:00Z"


def test_schema_registry_loads_multi_person_mode_a_vertical_slice_evidence() -> None:
    assert schema_validator("multi_person_mode_a_vertical_slice_evidence")


def test_overlapping_contact_duo_fixture_has_distinct_instances(tmp_path: Path) -> None:
    fixture = build_overlapping_contact_duo_fixture(tmp_path / "fixture")
    assert fixture["instance_context"] == "duo"
    assert fixture["relationship_kind"] == "contact"
    assert fixture["distinct_character_instances"] is True
    assert len(fixture["persons"]) == 2
    assert (
        fixture["persons"][0]["character_revision"] != fixture["persons"][1]["character_revision"]
    )
    assert (
        fixture["persons"][0]["character_instance_id"]
        != fixture["persons"][1]["character_instance_id"]
    )
    assert fixture["persons"][0]["scene_instance_id"] != fixture["persons"][1]["scene_instance_id"]
    assert fixture["ownership_mask_sha256s"]["p0"] != fixture["ownership_mask_sha256s"]["p1"]
    assert fixture["skeleton_sha256s"]["p0"] != fixture["skeleton_sha256s"]["p1"]
    assert fixture["transform_chain_sha256s"]["p0"] != fixture["transform_chain_sha256s"]["p1"]
    assert fixture["protected_region_count"] == 2


def test_duo_mode_a_reads_accept_with_transform_roundtrip(tmp_path: Path) -> None:
    fixture = build_overlapping_contact_duo_fixture(tmp_path / "fixture")
    reads = evaluate_duo_mode_a_reads(fixture, decided_at=DECIDED_AT)
    assert reads["both_accepted"] is True
    assert reads["distinct_package_ids"] is True
    assert reads["p0"]["transform_roundtrip_passed"] is True
    assert reads["p1"]["transform_roundtrip_passed"] is True
    assert reads["p0"]["owner_id"] == "person-0"
    assert reads["p1"]["owner_id"] == "person-1"


def test_multi_person_gate_passes_clean_contact_duo(tmp_path: Path) -> None:
    fixture = build_overlapping_contact_duo_fixture(tmp_path / "fixture")
    gate = evaluate_duo_multi_person_gate(fixture)
    assert gate["passed"] is True
    assert gate["blockers"] == []
    assert gate["promoted_instances"] == ["p0", "p1"]


def test_seeded_wrong_person_and_cross_instance_faults_reject(tmp_path: Path) -> None:
    fixture = build_overlapping_contact_duo_fixture(tmp_path / "fixture")
    wrong = seed_wrong_person_rejection(fixture, decided_at=DECIDED_AT)
    assert wrong["injected"] is True
    assert wrong["rejected"] is True
    assert "wrong_owner" in wrong["blocking_reason_codes"]

    cross = seed_cross_instance_rejection(fixture, decided_at=DECIDED_AT)
    assert cross["injected"] is True
    assert cross["rejected"] is True
    assert "instance_mismatch" in cross["blocking_reason_codes"]


def test_zero_ownership_ambiguity_on_accepted_duo(tmp_path: Path) -> None:
    fixture = build_overlapping_contact_duo_fixture(tmp_path / "fixture")
    gate = evaluate_duo_multi_person_gate(fixture)
    verdict = assess_zero_ownership_ambiguity(fixture, gate)
    assert verdict["zero_ownership_ambiguity"] is True
    assert verdict["cross_instance_bleed_absent"] is True
    assert verdict["reciprocal_contact_present"] is True
    assert verdict["protected_region_violation_absent"] is True


def test_full_producer_slice_is_partial_with_honest_blockers(tmp_path: Path) -> None:
    evidence = run_multi_person_mode_a_vertical_slice(tmp_path / "slice")
    issues = validate_multi_person_mode_a_vertical_slice_evidence(evidence)
    assert issues == ()
    assert evidence["status"] == "producer_partial"
    assert evidence["claim_boundary"]["producer_fixture_slice_complete"] is True
    assert evidence["claim_boundary"]["mf_p6_12_02_prerequisite_complete"] is False
    assert evidence["claim_boundary"]["main_adapter_execution_complete"] is False
    assert evidence["claim_boundary"]["mf_p6_12_03_complete"] is False
    assert evidence["person_reads"]["both_accepted"] is True
    assert evidence["multi_person_gate"]["passed"] is True
    assert evidence["seeded_faults"]["wrong_person"]["rejected"] is True
    assert evidence["seeded_faults"]["cross_instance"]["rejected"] is True
    assert evidence["ambiguity_verdict"]["zero_ownership_ambiguity"] is True
    assert "adopted_package_transaction_absent" in evidence["rejection_reasons"]
    assert "main_adapter_execution_absent" in evidence["rejection_reasons"]
    assert evidence["external_probe"]["main_adapter_execution"] is False


def test_completion_overclaim_is_rejected_by_validator(tmp_path: Path) -> None:
    evidence = run_multi_person_mode_a_vertical_slice(tmp_path / "slice")
    evidence["claim_boundary"]["mf_p6_12_03_complete"] = True
    evidence["decision_sha256"] = "0" * 64
    issues = validate_multi_person_mode_a_vertical_slice_evidence(evidence)
    assert "completion_overclaim" in issues
