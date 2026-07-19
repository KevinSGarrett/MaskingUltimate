"""Focused producer tests for MF-P6-12.05 cross-project qualification matrix."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from maskfactory.bridge.cross_project_qualification import (
    EXTERNAL_MAIN_DEPENDENCIES,
    POLICY_ID,
    POLICY_PATH,
    build_cross_project_qualification_evidence,
    run_cross_project_qualification,
    validate_cross_project_qualification_evidence,
)
from maskfactory.validation import (
    ADOPTION_COMPATIBILITY_CHECKS,
    canonical_document_sha256,
)


def test_policy_self_hash_and_closed_row_set() -> None:
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    assert policy["policy_id"] == POLICY_ID
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    assert policy["policy_sha256"] == expected
    rows = [row["row_id"] for row in policy["required_matrix_rows"]]
    assert len(rows) == len(set(rows))
    assert set(policy["required_frozen_compatibility_checks"]) == ADOPTION_COMPATIBILITY_CHECKS
    dimensions = {row["dimension"] for row in policy["required_matrix_rows"]}
    for required in (
        "compatibility",
        "trust_canonicalization",
        "encoded_pixel_identity",
        "ownership",
        "authority",
        "authority_training_truth",
        "geometry",
        "idempotency",
        "signed_journal",
        "outage",
        "submitted_unknown_restart",
        "cache",
        "invalidation",
        "rollback",
        "no_silent_fallback",
    ):
        assert required in dimensions


def test_producer_partial_when_main_commit_and_adoption_absent() -> None:
    evidence = build_cross_project_qualification_evidence()
    assert validate_cross_project_qualification_evidence(evidence) == ()
    assert evidence["status"] == "producer_partial"
    assert evidence["claim_boundary"]["producer_matrix_executable"] is True
    assert evidence["claim_boundary"]["mf_p6_12_05_complete"] is False
    assert evidence["claim_boundary"]["establishes_production_qualification"] is False
    assert evidence["consumer_binding"]["pinned_main_runtime_git_commit"] is None
    assert evidence["consumer_binding"]["adoption_receipt_present"] is False
    assert evidence["consumer_binding"]["complete"] is False
    assert "main_commit_absent" in evidence["rejection_reasons"]
    assert "adoption_receipt_absent" in evidence["rejection_reasons"]
    assert all(row["result"] == "pass" for row in evidence["matrix_results"])


def test_binds_actual_producer_hashes_and_lineage() -> None:
    evidence = build_cross_project_qualification_evidence()
    producer = evidence["producer_binding"]
    assert isinstance(producer["producer_git_commit"], str)
    assert len(producer["producer_git_commit"]) == 40
    assert producer["preserved_bridge_head"] == "6361df208e01d183083ee6c113e016467a486706"
    assert (
        producer["reconciliation_seal"]
        == "c948da1595f6c29ead2aeda950ac778717c6557f2ed5f6c4b0664e5052f3eb52"
    )
    assert producer["wire_schema_count"] == 12
    assert isinstance(producer["mode_a_vertical_slice_decision_sha256"], str)
    assert isinstance(producer["multi_person_mode_a_vertical_slice_decision_sha256"], str)
    assert isinstance(producer["mode_b_vertical_slice_decision_sha256"], str)
    assert producer["complete"] is True
    assert evidence["consumer_binding"]["main_consumer_planning_head"] == (
        "a54a7ed2bad472f77168e190b9881b4f7e7cc589"
    )


def test_frozen_compatibility_projection_is_closed_16() -> None:
    evidence = build_cross_project_qualification_evidence()
    projection = evidence["frozen_compatibility_projection"]
    assert len(projection) == 16
    assert {row["check"] for row in projection} == ADOPTION_COMPATIBILITY_CHECKS
    assert all(row["status"] in {"pass", "fail", "unbound_external_main"} for row in projection)
    # Producer probes should pass their mapped checks; unbound only when no row maps.
    assert any(row["status"] == "pass" for row in projection)


def test_rejects_fabricated_main_receipt_and_currency_relabel() -> None:
    evidence = build_cross_project_qualification_evidence(
        {
            "fabricated_main_receipt": {
                "main_adapter_execution_receipt_present": True,
                "result_sha256": "a" * 64,
                "history_sha256": "b" * 64,
            },
            "claimed_currency_status": "pass",
            "claim_production_qualification": True,
        }
    )
    assert validate_cross_project_qualification_evidence(evidence) == ()
    assert evidence["status"] == "rejected"
    assert "fabricated_main_receipt" in evidence["rejection_reasons"]
    assert "currency_policy_relabel_forbidden" in evidence["rejection_reasons"]
    assert "fixture_evidence_claimed_as_production" in evidence["rejection_reasons"]
    assert evidence["currency_review_binding"]["relabel_forbidden"] is True
    assert evidence["currency_review_binding"]["reported_status"] == "fail"


def test_planning_head_is_not_accepted_as_runtime_main_pin() -> None:
    evidence = build_cross_project_qualification_evidence(
        {
            "pinned_main_runtime_git_commit": "a54a7ed2bad472f77168e190b9881b4f7e7cc589",
        }
    )
    # A bare planning/runtime commit without adoption/qualification still fails closed.
    assert evidence["status"] == "producer_partial"
    assert evidence["consumer_binding"]["pinned_main_runtime_git_commit"] == (
        "a54a7ed2bad472f77168e190b9881b4f7e7cc589"
    )
    assert "adoption_receipt_absent" in evidence["rejection_reasons"]
    assert evidence["consumer_binding"]["complete"] is False


def test_seeded_negative_rows_pass_when_faults_fail_closed() -> None:
    evidence = build_cross_project_qualification_evidence()
    by_id = {row["row_id"]: row for row in evidence["matrix_results"]}
    for row_id in (
        "mx.compat.unknown_field_neg",
        "mx.trust.signature_substitution_neg",
        "mx.ownership.wrong_person_neg",
        "mx.authority.parent_ceiling_inflation_neg",
        "mx.cache.stale_refuse",
        "mx.nofallback.silent_substitution",
        "mx.fabricate.main_receipt_neg",
    ):
        assert by_id[row_id]["polarity"] == "seeded_negative"
        assert by_id[row_id]["result"] == "pass"


def test_validate_rejects_decision_hash_drift() -> None:
    evidence = build_cross_project_qualification_evidence()
    tampered = dict(evidence)
    tampered["decision_sha256"] = "0" * 64
    issues = validate_cross_project_qualification_evidence(tampered)
    assert "decision_hash_drift" in issues


def test_run_persists_evidence(tmp_path: Path) -> None:
    evidence = run_cross_project_qualification(tmp_path / "mx")
    path = tmp_path / "mx" / "cross_project_qualification_evidence.json"
    assert path.is_file()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["decision_sha256"] == evidence["decision_sha256"]
    assert loaded["status"] == "producer_partial"


def test_external_main_dependencies_are_explicit() -> None:
    assert "pinned_main_runtime_git_commit" in EXTERNAL_MAIN_DEPENDENCIES
    assert "main_adoption_receipt" in EXTERNAL_MAIN_DEPENDENCIES
    assert "main_qualification_bundle_signature" in EXTERNAL_MAIN_DEPENDENCIES
