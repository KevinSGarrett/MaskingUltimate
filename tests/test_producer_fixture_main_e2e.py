"""End-to-end producer + fixture-Main verify for Mode A/B, qualification, handoff."""

from __future__ import annotations

from pathlib import Path

from maskfactory.bridge.cross_project_qualification import (
    build_cross_project_qualification_evidence,
    validate_cross_project_qualification_evidence,
)
from maskfactory.bridge.final_release_handoff import (
    evaluate_final_release_handoff,
    validate_final_release_handoff_evidence,
)
from maskfactory.bridge.fixture_main import (
    AUTHORITY_KIND,
    materialize_fixture_main,
)
from maskfactory.bridge.fixture_main.binding import load_fixture_main_binding
from maskfactory.bridge.mode_a_vertical_slice import (
    run_mode_a_vertical_slice,
    validate_mode_a_vertical_slice_evidence,
)
from maskfactory.bridge.mode_b_vertical_slice import (
    run_mode_b_vertical_slice,
    validate_mode_b_vertical_slice_evidence,
)
from maskfactory.bridge.multi_person_mode_a_vertical_slice import (
    run_multi_person_mode_a_vertical_slice,
    validate_multi_person_mode_a_vertical_slice_evidence,
)


def test_fail_closed_when_fixture_main_absent(tmp_path: Path) -> None:
    binding = load_fixture_main_binding(tmp_path)
    assert binding["present"] is False
    assert binding["binding_status"] == "absent"
    assert binding["claim_boundary"]["independent_real_accuracy_claim"] is False

    mode_a = run_mode_a_vertical_slice(tmp_path / "a", bind_fixture_main=True, repo_root=tmp_path)
    assert validate_mode_a_vertical_slice_evidence(mode_a) == ()
    assert mode_a["status"] == "producer_partial"
    assert mode_a["claim_boundary"]["fixture_main_bound"] is False
    assert "main_adapter_execution_absent" in mode_a["rejection_reasons"]


def test_mode_a_binds_fixture_main_hash_chain(tmp_path: Path) -> None:
    materialize_fixture_main(repo_root=tmp_path)
    evidence = run_mode_a_vertical_slice(
        tmp_path / "mode_a", bind_fixture_main=True, repo_root=tmp_path
    )
    assert validate_mode_a_vertical_slice_evidence(evidence) == ()
    assert evidence["status"] == "accepted"
    assert evidence["downstream_envelope"]["binding_status"] == "fixture_main_bound"
    assert evidence["downstream_envelope"]["authority_kind"] == AUTHORITY_KIND
    assert evidence["identity_chain"]["complete_downstream_bindings"] is True
    assert isinstance(evidence["identity_chain"]["result_sha256"], str)
    assert isinstance(evidence["identity_chain"]["history_sha256"], str)
    assert evidence["claim_boundary"]["fixture_main_bound"] is True
    assert evidence["claim_boundary"]["fixture_main_hash_chain_complete"] is True
    assert evidence["claim_boundary"]["mf_p6_12_02_complete"] is False
    assert evidence["claim_boundary"]["independent_real_accuracy_claim"] is False
    assert evidence["claim_boundary"]["main_adapter_execution_complete"] is False


def test_multi_person_binds_fixture_main_duo_receipts(tmp_path: Path) -> None:
    materialize_fixture_main(repo_root=tmp_path)
    evidence = run_multi_person_mode_a_vertical_slice(
        tmp_path / "duo", bind_fixture_main=True, repo_root=tmp_path
    )
    assert validate_multi_person_mode_a_vertical_slice_evidence(evidence) == ()
    assert evidence["status"] == "accepted"
    assert evidence["external_probe"]["main_adapter_execution"] is True
    assert evidence["external_probe"]["downstream_comfyui_result_history"] is True
    assert evidence["external_probe"]["authority_kind"] == AUTHORITY_KIND
    assert evidence["claim_boundary"]["fixture_main_bound"] is True
    assert evidence["claim_boundary"]["mf_p6_12_03_complete"] is False
    assert evidence["claim_boundary"]["independent_real_accuracy_claim"] is False


def test_mode_b_binds_fixture_main_offer_and_circuit(tmp_path: Path) -> None:
    materialize_fixture_main(repo_root=tmp_path)
    evidence = run_mode_b_vertical_slice(
        tmp_path / "mode_b", bind_fixture_main=True, repo_root=tmp_path
    )
    assert validate_mode_b_vertical_slice_evidence(evidence) == ()
    assert evidence["status"] == "producer_partial"
    assert evidence["live_probe"]["fixture_main_bound"] is True
    assert evidence["claim_boundary"]["fixture_main_bound"] is True
    assert evidence["claim_boundary"]["mf_p6_12_04_complete"] is False
    assert evidence["claim_boundary"]["independent_real_accuracy_claim"] is False
    assert "champion_backed_prediction_absent" in evidence["rejection_reasons"]


def test_qualification_binds_fixture_main_without_production_claim(tmp_path: Path) -> None:
    materialize_fixture_main(repo_root=tmp_path)
    binding = load_fixture_main_binding(tmp_path)
    assert binding["valid"] is True
    evidence = build_cross_project_qualification_evidence(
        repo_root=tmp_path, ensure_slice_evidence=True, bind_fixture_main=True
    )
    assert validate_cross_project_qualification_evidence(evidence) == ()
    assert evidence["status"] == "producer_partial"
    assert evidence["consumer_binding"]["adoption_receipt_present"] is True
    assert evidence["consumer_binding"]["fixture_main_bound"] is True
    assert evidence["consumer_binding"]["complete"] is True
    assert evidence["claim_boundary"]["fixture_main_bound"] is True
    assert evidence["claim_boundary"]["establishes_production_qualification"] is False
    assert evidence["claim_boundary"]["mf_p6_12_05_complete"] is False
    assert evidence["claim_boundary"]["independent_real_accuracy_claim"] is False


def test_handoff_binds_fixture_main_but_refuses_core_close(tmp_path: Path) -> None:
    materialize_fixture_main(repo_root=tmp_path)
    evidence = evaluate_final_release_handoff(
        bind_fixture_main=True,
        repo_root=tmp_path,
        decided_at="2026-07-19T15:00:00Z",
    )
    assert validate_final_release_handoff_evidence(evidence) == ()
    assert evidence["status"] == "incomplete_core"
    assert evidence["core_autonomous_runtime_close_authorized"] is False
    assert evidence["claim_boundary"]["fixture_main_bound"] is True
    assert evidence["claim_boundary"]["independent_real_accuracy_claim"] is False
    assert evidence["claim_boundary"]["core_closed"] is False
    assert "fixture_authority_cannot_close_core" in evidence["rejection_reasons"]
    assert evidence["adoption_validation"]["present"] is True
