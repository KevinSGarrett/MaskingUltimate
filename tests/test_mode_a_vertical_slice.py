"""Focused producer tests for MF-P6-12.02 Mode A vertical slice."""

from __future__ import annotations

from pathlib import Path

from maskfactory.bridge.mode_a_package_read import evaluate_mode_a_package_read
from maskfactory.bridge.mode_a_vertical_slice import (
    build_fixture_adopted_package,
    build_intended_inpaint_workflow,
    prove_raw_status_escalation_is_rejected,
    reject_fabricated_downstream_receipt,
    run_mode_a_vertical_slice,
    validate_mode_a_vertical_slice_evidence,
)
from maskfactory.validation import schema_validator


def test_schema_registry_loads_mode_a_vertical_slice_evidence() -> None:
    assert schema_validator("mode_a_vertical_slice_evidence")


def test_adopted_package_read_is_production_certified() -> None:
    request, evidence = build_fixture_adopted_package(person_index=0)
    decision = evaluate_mode_a_package_read(request, evidence, decided_at="2026-07-19T14:00:00Z")
    assert decision["status"] == "accepted"
    assert decision["authority_ceiling"] == "certified"
    assert decision["production_eligible"] is True
    assert decision["observed"]["wrapper_status"] == "active"
    assert decision["observed"]["transform_roundtrip_passed"] is True
    assert decision["observed"]["person_index"] == 0


def test_raw_status_escalation_without_wrapper_is_rejected() -> None:
    proof = prove_raw_status_escalation_is_rejected()
    assert proof["status"] == "rejected"
    assert proof["production_eligible"] is False
    assert proof["raw_status_escalation_rejected"] is True
    assert "raw_status_escalation" in proof["rejection_reasons"]
    assert "wrapper_missing" in proof["rejection_reasons"]


def test_fabricated_downstream_receipt_is_rejected() -> None:
    refusal = reject_fabricated_downstream_receipt(
        {
            "main_adapter_execution_receipt_present": True,
            "result_sha256": "a" * 64,
            "history_sha256": "b" * 64,
            "claim_mf_p6_12_02_complete": True,
        }
    )
    assert refusal["attempted"] is True
    assert refusal["rejected"] is True
    assert "downstream_receipt_fabricated" in refusal["reason_codes"]

    honest = reject_fabricated_downstream_receipt(None)
    assert honest["attempted"] is False
    assert honest["rejected"] is False


def test_intended_workflow_hash_is_deterministic() -> None:
    first = build_intended_inpaint_workflow(package_sha256="1" * 64, mask_encoded_sha256="2" * 64)
    second = build_intended_inpaint_workflow(package_sha256="1" * 64, mask_encoded_sha256="2" * 64)
    assert first["workflow_sha256"] == second["workflow_sha256"]
    assert first["operation"] == "comfyui_inpaint_edit"


def test_full_producer_slice_is_partial_with_honest_main_blockers(tmp_path: Path) -> None:
    evidence = run_mode_a_vertical_slice(tmp_path / "slice")
    issues = validate_mode_a_vertical_slice_evidence(evidence)
    assert issues == ()
    assert evidence["status"] == "producer_partial"
    assert evidence["claim_boundary"]["producer_fixture_slice_complete"] is True
    assert evidence["claim_boundary"]["main_adapter_execution_complete"] is False
    assert evidence["claim_boundary"]["comfyui_inpaint_edit_complete"] is False
    assert evidence["claim_boundary"]["mf_p6_12_02_complete"] is False
    assert "main_adapter_execution_absent" in evidence["rejection_reasons"]
    assert "comfyui_result_history_absent" in evidence["rejection_reasons"]
    assert evidence["package_read"]["status"] == "accepted"
    assert evidence["package_read"]["wrapper_status"] == "active"
    assert evidence["adapter_conformance"]["status"] == "accepted"
    assert evidence["use_eligibility"]["eligible"] is True
    assert evidence["identity_chain"]["complete_producer_bindings"] is True
    assert evidence["identity_chain"]["complete_downstream_bindings"] is False
    assert evidence["identity_chain"]["result_sha256"] is None
    assert evidence["identity_chain"]["history_sha256"] is None
    assert evidence["identity_chain"]["person_index"] == 0
    assert evidence["handoff_journal"]["head_state"] == "submit"
    assert evidence["handoff_journal"]["history_valid"] is True
    assert evidence["downstream_envelope"]["binding_status"] == "producer_ready_awaiting_main"
    assert evidence["downstream_envelope"]["main_adapter_execution_receipt_present"] is False
    assert evidence["recovery_probe"]["status"] == "accepted"
    assert evidence["recovery_probe"]["outcome_unknown_reconciled"] is True


def test_fabricated_claim_forces_rejected_slice(tmp_path: Path) -> None:
    evidence = run_mode_a_vertical_slice(
        tmp_path / "fabricated",
        fabricated_downstream_claim={
            "comfyui_inpaint_result_present": True,
            "result_sha256": "f" * 64,
        },
    )
    assert evidence["status"] == "rejected"
    assert "downstream_receipt_fabricated" in evidence["rejection_reasons"]
    assert evidence["downstream_envelope"]["binding_status"] == "rejected_fabricated"
    assert evidence["claim_boundary"]["producer_fixture_slice_complete"] is False
    assert validate_mode_a_vertical_slice_evidence(evidence) == ()
