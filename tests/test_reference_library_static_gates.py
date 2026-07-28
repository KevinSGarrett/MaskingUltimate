"""STATIC leakage/authority/index contracts for MF-P9-14 (no 83k corpus copy)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maskfactory.reference_library_static_gates import (
    EXPECTED_BENCHMARK_COUNT,
    EXPECTED_RETRIEVAL_COUNT,
    FROZEN_BENCHMARK_ISOLATION_FINGERPRINT,
    FROZEN_INVENTORY,
    PROOF_TIER,
    ReferenceLibraryStaticGateError,
    build_static_gate_evidence,
    evaluate_authority_surface,
    evaluate_capacity_held_portfolio_status,
    evaluate_index_progress_contract,
    evaluate_inventory_claim_contract,
    evaluate_isolation_receipt,
    evaluate_materialization_honesty,
    require_isolation_receipt,
    write_static_gate_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "qa" / "fixtures" / "reference_library_static"
EVIDENCE = ROOT / "qa" / "live_verification" / "reference_library_static_gates_20260719.json"


def test_index_progress_contract_fails_closed_on_disagreement() -> None:
    ok = evaluate_index_progress_contract(
        {"classified": 10, "remaining": 0, "percent": 100.0, "complete": True},
        exact_representatives=10,
    )
    assert ok["passed"] is True
    assert ok["proof_tier"] == PROOF_TIER
    bad = evaluate_index_progress_contract(
        {"classified": 7, "remaining": 0, "percent": 100.0, "complete": True},
        exact_representatives=10,
    )
    assert bad["passed"] is False
    assert "remaining:0!=3" in bad["issues"]
    assert "complete_disagrees_with_classified_vs_representatives" in bad["issues"]


def test_inventory_claim_refuses_corpus_walk_and_binds_frozen_counts() -> None:
    claim = dict(FROZEN_INVENTORY)
    claim["complete"] = True
    ok = evaluate_inventory_claim_contract(claim, require_frozen_live_counts=True)
    assert ok["passed"] is True
    walked = dict(claim)
    walked["full_corpus_walk_performed"] = True
    refused = evaluate_inventory_claim_contract(walked, require_frozen_live_counts=True)
    assert refused["passed"] is False
    assert "full_corpus_walk_performed_forbidden_under_static_gates" in refused["issues"]


def test_authority_surface_blocks_truth_and_training_promotion() -> None:
    ok = evaluate_authority_surface(
        {
            "source_role": "unlabeled_reference_corpus",
            "truth_authority": "none",
            "training_eligible": False,
            "candidates": [{"truth_authority": "none", "training_eligible": False}],
        }
    )
    assert ok["passed"] is True
    bad = evaluate_authority_surface(
        {
            "truth_authority": "human_anchor_gold",
            "training_eligible": True,
            "selection_or_retrieval_creates_truth": True,
        }
    )
    assert bad["passed"] is False
    assert "truth_authority:human_anchor_gold" in bad["issues"]
    assert "training_eligible" in bad["issues"]


def test_isolation_receipt_and_require_helper() -> None:
    receipt = {
        "schema_version": "1.0.0",
        "passed": True,
        "benchmark_count": EXPECTED_BENCHMARK_COUNT,
        "benchmark_fingerprint": "a" * 64,
        "record_count": 12,
        "issues": [],
        "dhash_hamming_threshold": 3,
    }
    assert evaluate_isolation_receipt(receipt)["passed"] is True
    assert require_isolation_receipt(receipt)["passed"] is True
    live = dict(receipt)
    live["benchmark_fingerprint"] = FROZEN_BENCHMARK_ISOLATION_FINGERPRINT
    assert evaluate_isolation_receipt(live, require_frozen_live_fingerprint=True)["passed"] is True
    with pytest.raises(ReferenceLibraryStaticGateError, match="reference-benchmark isolation"):
        require_isolation_receipt({"passed": False, "issues": ["exact_overlap:0:x"]})


def test_materialization_honesty_and_capacity_held_portfolio() -> None:
    hold = evaluate_materialization_honesty(
        {
            "complete": False,
            "processed_this_chunk": 0,
            "capacity_hold": {
                "reason": "storage_below_soft_floor",
                "soft_floor_gib": 150,
            },
        }
    )
    assert hold["passed"] is True
    assert hold["honest_status"] == "capacity_held_incomplete"
    lying = evaluate_materialization_honesty(
        {
            "complete": True,
            "processed_this_chunk": 0,
            "capacity_hold": {"reason": "storage_below_soft_floor", "soft_floor_gib": 150},
        }
    )
    assert lying["passed"] is False
    assert "complete_true_under_capacity_hold" in lying["issues"]

    portfolio = evaluate_capacity_held_portfolio_status(
        benchmark_materialized_count=EXPECTED_BENCHMARK_COUNT,
        retrieval_materialized_count=0,
        contact_sheets_complete=True,
    )
    assert portfolio["passed"] is True
    assert portfolio["capacity_held"] is True
    assert portfolio["mf_p9_14_06_complete_claim_allowed"] is False
    assert portfolio["expected_retrieval_count"] == EXPECTED_RETRIEVAL_COUNT

    partial = evaluate_capacity_held_portfolio_status(
        benchmark_materialized_count=EXPECTED_BENCHMARK_COUNT,
        retrieval_materialized_count=100,
        contact_sheets_complete=True,
    )
    assert partial["passed"] is False
    assert any("partial_retrieval_copy" in issue for issue in partial["issues"])


def test_fixture_claims_and_sealed_evidence_round_trip(tmp_path: Path) -> None:
    inventory = json.loads((FIXTURES / "inventory_claim.json").read_text(encoding="utf-8"))
    authority = json.loads((FIXTURES / "authority_surface.json").read_text(encoding="utf-8"))
    isolation = json.loads((FIXTURES / "isolation_receipt.json").read_text(encoding="utf-8"))
    materialization = json.loads(
        (FIXTURES / "materialization_capacity_hold.json").read_text(encoding="utf-8")
    )

    index_report = evaluate_index_progress_contract(
        {
            "classified": inventory["classified"],
            "remaining": inventory["remaining"],
            "percent": 100.0,
            "complete": True,
        },
        exact_representatives=inventory["exact_representatives"],
    )
    inventory_report = evaluate_inventory_claim_contract(inventory, require_frozen_live_counts=True)
    authority_report = evaluate_authority_surface(authority)
    isolation_report = evaluate_isolation_receipt(isolation, require_frozen_live_fingerprint=True)
    materialization_report = evaluate_materialization_honesty(materialization)
    portfolio_report = evaluate_capacity_held_portfolio_status(
        benchmark_materialized_count=EXPECTED_BENCHMARK_COUNT,
        retrieval_materialized_count=0,
        contact_sheets_complete=True,
    )
    evidence = build_static_gate_evidence(
        index_report=index_report,
        inventory_report=inventory_report,
        authority_report=authority_report,
        isolation_report=isolation_report,
        materialization_report=materialization_report,
        portfolio_report=portfolio_report,
    )
    assert evidence["result"] == "pass_reference_library_static_gates"
    assert evidence["proof_tier"] == PROOF_TIER
    assert len(evidence["sha256"]) == 64
    written = write_static_gate_evidence(evidence, tmp_path / "gates.json")
    assert json.loads(written.read_text(encoding="utf-8"))["sha256"] == evidence["sha256"]

    # Repository evidence must remain sealed and passing.
    published = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert published["result"] == "pass_reference_library_static_gates"
    assert published["sha256"] == evidence["sha256"]
