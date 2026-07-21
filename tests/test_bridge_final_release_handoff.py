from __future__ import annotations

import runpy
from pathlib import Path

from maskfactory.bridge.final_release_handoff import (
    EXTERNAL_MAIN_DEPENDENCIES,
    evaluate_final_release_handoff,
    load_tracker_data,
    regenerate_profile_status_inputs,
    validate_final_release_handoff_evidence,
)
from maskfactory.validation import canonical_document_sha256, schema_validator

ROOT = Path(__file__).resolve().parents[1]
TRACKER_SOURCE = ROOT / "Plan" / "Tracker" / "tracker.py"
PRODUCER = "a" * 40
CONSUMER = "b" * 40
RELEASE_ID = "mfr_20260719_abcdef012345"
RELEASE_HASH = "1" * 64
ADOPTION_ID = "mfadopt_0123456789abcdef01234567"
ADOPTION_HASH = "2" * 64
QUAL_ID = "mfqual_0123456789abcdef01234567"
QUAL_HASH = "3" * 64


def _tracker_module() -> dict:
    return runpy.run_path(str(TRACKER_SOURCE))


def _complete_core_tracker() -> dict:
    module = _tracker_module()
    data = load_tracker_data()
    closure = module["completion_profile_dependency_closure"](data, "core_autonomous_runtime")
    for item_id in closure:
        row = data["items"][item_id]
        row["status"] = "complete"
        row["orphaned"] = False
        row["percent_complete"] = 100
        row["blocked_reason"] = None
    # Keep optional profiles incomplete to prove independence.
    for profile_id in ("independent_real_accuracy", "scale_daz_maturity"):
        for item_id in module["COMPLETION_PROFILES"][profile_id]["driven_by"]:
            if item_id in closure:
                continue
            if item_id in data["items"]:
                data["items"][item_id]["status"] = "blocked"
                data["items"][item_id]["percent_complete"] = 0
    return data


def _release(*, published: bool = True, fixture_only: bool = False) -> dict:
    return {
        "release_id": RELEASE_ID,
        "release_payload_sha256": RELEASE_HASH,
        "release_status": "published" if published else "draft",
        "fixture_only": fixture_only,
        "producer": {"git_commit": PRODUCER},
    }


def _adoption(*, decision: str = "adopted", scope: str = "production_authority") -> dict:
    return {
        "adoption_id": ADOPTION_ID,
        "adoption_payload_sha256": ADOPTION_HASH,
        "adoption_scope": scope,
        "decision": decision,
        "production_use_authorized": decision in {"adopted", "partially_adopted"},
        "fixture_only": scope != "production_authority",
        "release_id": RELEASE_ID,
        "release_payload_sha256": RELEASE_HASH,
        "qualification_bundle_id": QUAL_ID,
        "qualification_bundle_sha256": QUAL_HASH,
        "consumer": {
            "project": "Comfy_UI_Main",
            "controller_version": "1.0.0",
            "git_commit": CONSUMER,
        },
        "decided_at": "2026-07-19T00:00:00Z",
        "valid_until": "2026-07-20T00:00:00Z",
        "compatibility_checks": [],
        "capability_decisions": [],
        "signature": {
            "key_id": "comfy-main-adoption-prod",
            "public_key_base64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "signed_payload_sha256": "4" * 64,
            "value_base64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        },
    }


def _qualification() -> dict:
    return {
        "qualification_id": QUAL_ID,
        "qualification_payload_sha256": QUAL_HASH,
        "fixture_only": False,
    }


def _ack() -> dict:
    return {
        "acknowledgement_id": "mfack_0123456789abcdef01234567",
        "adoption_id": ADOPTION_ID,
        "adoption_payload_sha256": ADOPTION_HASH,
        "invalidation_head_sha256": "5" * 64,
        "rollback_target_sha256": "6" * 64,
        "producer_git_commit": PRODUCER,
        "consumer_git_commit": CONSUMER,
    }


def test_schema_registered() -> None:
    assert schema_validator("bridge_final_release_handoff_evidence") is not None


def test_missing_main_adoption_proves_incomplete_core_and_refuses_close() -> None:
    evidence = evaluate_final_release_handoff(
        release_snapshot=_release(),
        release_publication_issues=[],
        adoption_receipt=None,
        tracker_data=load_tracker_data(),
        producer_git_commit=PRODUCER,
        decided_at="2026-07-19T15:00:00Z",
        # Isolate true Main-absence from auto-bind of repo fixture_main artifacts.
        bind_fixture_main=False,
    )
    assert evidence["status"] == "incomplete_core"
    assert evidence["core_autonomous_runtime_close_authorized"] is False
    assert "main_adoption_receipt_missing" in evidence["rejection_reasons"]
    assert "core_close_refused_without_exact_gates" in evidence["rejection_reasons"]
    assert evidence["claim_boundary"]["core_closed"] is False
    assert evidence["adoption_validation"]["present"] is False
    core = evidence["profile_status_inputs"]["profiles"]["core_autonomous_runtime"]
    assert core["status"] != "complete"
    assert core["close_authorized"] is False
    assert core["open_driving_item_count"] > 0
    assert evidence["profile_status_inputs"]["core_close_refused"] is True
    assert validate_final_release_handoff_evidence(evidence) == ()
    assert set(EXTERNAL_MAIN_DEPENDENCIES) == {
        "main_production_adoption_receipt",
        "main_installed_runtime_identities",
        "main_compatibility_vertical_slice_evidence",
        "main_qualification_bundle_runtime_evidence",
    }


def test_regenerates_claim_safe_profile_inputs_from_live_tracker() -> None:
    data = load_tracker_data()
    inputs = regenerate_profile_status_inputs(data, core_close_authorized=False)
    assert set(inputs["profiles"]) == {
        "core_autonomous_runtime",
        "independent_real_accuracy",
        "scale_daz_maturity",
    }
    assert inputs["independence_proof"]["optional_failure_cannot_revoke_core"] is True
    assert inputs["independence_proof"]["core_close_requires_exact_gates"] is True
    assert inputs["profiles"]["core_autonomous_runtime"]["close_authorized"] is False
    # Live tracker currently has incomplete core; inputs must not invent completeness.
    assert inputs["profiles"]["core_autonomous_runtime"]["status"] != "complete"
    assert inputs["tracker_items_sha256"] == canonical_document_sha256(
        {
            item_id: {
                "status": row.get("status"),
                "orphaned": bool(row.get("orphaned")),
                "conditional": bool(row.get("conditional")),
            }
            for item_id, row in data["items"].items()
        }
    )


def test_refuses_fabricated_core_complete_claim() -> None:
    evidence = evaluate_final_release_handoff(
        release_snapshot=_release(),
        release_publication_issues=[],
        adoption_receipt=_adoption(),
        reciprocal_acknowledgement=_ack(),
        qualification_bundle=_qualification(),
        tracker_data=_complete_core_tracker(),
        producer_git_commit=PRODUCER,
        consumer_git_commit=CONSUMER,
        at_time="2026-07-19T12:00:00Z",
        adoption_matrix_decision={"status": "accepted", "rejection_reasons": ["eligible"]},
        fabricated_core_complete_claim=True,
        decided_at="2026-07-19T15:00:00Z",
    )
    assert evidence["status"] == "rejected"
    assert evidence["core_autonomous_runtime_close_authorized"] is False
    assert "fabricated_core_complete_claim" in evidence["rejection_reasons"]
    assert "core_close_refused_without_exact_gates" in evidence["rejection_reasons"]
    assert validate_final_release_handoff_evidence(evidence) == ()


def test_fixture_only_release_cannot_authorize_core_close() -> None:
    evidence = evaluate_final_release_handoff(
        release_snapshot=_release(fixture_only=True),
        release_publication_issues=[],
        adoption_receipt=_adoption(),
        reciprocal_acknowledgement=_ack(),
        qualification_bundle=_qualification(),
        tracker_data=_complete_core_tracker(),
        producer_git_commit=PRODUCER,
        consumer_git_commit=CONSUMER,
        at_time="2026-07-19T12:00:00Z",
        adoption_matrix_decision={"status": "accepted", "rejection_reasons": ["eligible"]},
        decided_at="2026-07-19T15:00:00Z",
    )
    assert evidence["status"] == "incomplete_core"
    assert evidence["core_autonomous_runtime_close_authorized"] is False
    assert "final_producer_release_fixture_only" in evidence["rejection_reasons"]
    gate = next(
        row
        for row in evidence["exact_core_close_gates"]
        if row["gate_id"] == "final_producer_release_published"
    )
    assert gate["status"] == "failed"
    assert validate_final_release_handoff_evidence(evidence) == ()


def test_authorizes_close_only_when_every_exact_gate_passes() -> None:
    evidence = evaluate_final_release_handoff(
        release_snapshot=_release(),
        release_publication_issues=[],
        adoption_receipt=_adoption(),
        reciprocal_acknowledgement=_ack(),
        qualification_bundle=_qualification(),
        tracker_data=_complete_core_tracker(),
        producer_git_commit=PRODUCER,
        consumer_git_commit=CONSUMER,
        at_time="2026-07-19T12:00:00Z",
        adoption_matrix_decision={"status": "accepted", "rejection_reasons": ["eligible"]},
        decided_at="2026-07-19T15:00:00Z",
    )
    assert evidence["status"] == "accepted"
    assert evidence["rejection_reasons"] == ["eligible"]
    assert evidence["core_autonomous_runtime_close_authorized"] is True
    assert evidence["claim_boundary"]["core_closed"] is False
    assert all(row["status"] == "met" for row in evidence["exact_core_close_gates"])
    core = evidence["profile_status_inputs"]["profiles"]["core_autonomous_runtime"]
    assert core["status"] == "complete"
    assert core["close_authorized"] is True
    # Optional profiles remain independent and may stay incomplete.
    assert (
        evidence["profile_status_inputs"]["profiles"]["independent_real_accuracy"]["status"]
        != "complete"
    )
    assert validate_final_release_handoff_evidence(evidence) == ()


def test_conformance_only_adoption_is_incomplete_core() -> None:
    evidence = evaluate_final_release_handoff(
        release_snapshot=_release(),
        release_publication_issues=[],
        adoption_receipt=_adoption(decision="conformance_only", scope="conformance_validation"),
        reciprocal_acknowledgement=_ack(),
        qualification_bundle=_qualification(),
        tracker_data=_complete_core_tracker(),
        producer_git_commit=PRODUCER,
        consumer_git_commit=CONSUMER,
        decided_at="2026-07-19T15:00:00Z",
    )
    assert evidence["status"] == "incomplete_core"
    assert evidence["core_autonomous_runtime_close_authorized"] is False
    assert "main_adoption_not_production_authority" in evidence["rejection_reasons"]
    assert validate_final_release_handoff_evidence(evidence) == ()
