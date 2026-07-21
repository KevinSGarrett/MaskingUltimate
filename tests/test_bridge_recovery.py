"""Receipt-last recovery, reconciliation, and kill-boundary drills for MF-P6-11.08."""

from __future__ import annotations

import pytest

from maskfactory.bridge.recovery import (
    EXTERNAL_MAIN_DEPENDENCIES,
    RecoveryError,
    build_recovery_evidence,
    simulate_kill_at_boundary,
    validate_recovery_evidence,
)
from maskfactory.validation import canonical_document_sha256


def _snapshot(**overrides: object) -> dict:
    body = {
        "health": {"status": "ok", "health_sha256": "a" * 64},
        "capability": {"capability_sha256": "b" * 64},
        "adopted_release": {"release_sha256": "c" * 64},
        "revocation": {"revocation_head_sha256": "d" * 64, "fresh": True},
        "service_openapi": {"service_sha256": "e" * 64},
        "node_pack": {
            "node_pack_sha256": "f" * 64,
            "closed_manifest": True,
            "stale_unmanifested_files": False,
        },
        "policy": {"policy_sha256": "1" * 64},
        "route": {"route_sha256": "2" * 64},
        "gpu_lease": {"lease_sha256": "3" * 64},
    }
    body.update(overrides)
    body["snapshot_sha256"] = canonical_document_sha256(
        body, excluded_top_level_fields=("snapshot_sha256",)
    )
    return body


def _lease(*, state: str = "held", cleanup: bool = False) -> dict:
    return {
        "state": state,
        "token": "lease-token-test" if state == "held" else None,
        "request_id": "mfareq_recovery_00000001",
        "device_id": "cuda:0",
        "cleanup_deleted_foreign_token": cleanup,
    }


def _cache(*, request_id: str = "mfareq_recovery_00000001") -> dict:
    return {
        "request_id": request_id,
        "receipt_sha256": "11" * 32,
        "artifact_sha256": "22" * 32,
        "release_sha256": "c" * 64,
        "capability_sha256": "b" * 64,
        "revocation_head_sha256": "d" * 64,
        "node_pack_sha256": "f" * 64,
        "authority_sha256": "33" * 32,
        "captured_at": "2026-07-19T12:00:00Z",
        "decided_at": "2026-07-19T12:01:00Z",
        "tombstoned": False,
        "main_tombstone_evidence": {},
    }


def _complete_transaction() -> dict:
    phases = [
        "reservation",
        "admission",
        "lease_acquired",
        "submitted",
        "provider_result",
        "artifacts_staged",
        "artifacts_published",
        "receipt_signed",
        "receipt_written",
        "receipt_committed_event",
        "checkpoint_advanced",
        "cache_published",
    ]
    return {
        "request_id": "mfareq_recovery_00000001",
        "current_phase": "cache_published",
        "completed_phases": phases,
        "submission_state": "reconciled",
        "outcome_unknown": False,
        "retry_requested": False,
        "duplicate_submission_attempted": False,
        "orphan_promotion_attempted": False,
        "authority_granted": True,
        "authority_granted_without_checkpoint": False,
        "commit_claimed": True,
        "decided_at": "2026-07-19T12:01:00Z",
        "artifacts": [{"artifact_sha256": "22" * 32}],
        "receipt": {
            "receipt_sha256": "11" * 32,
            "artifact_sha256s": ["22" * 32],
            "resolved": True,
        },
    }


def _healthy_observation() -> dict:
    snapshot = _snapshot()
    return {
        "request_id": "mfareq_recovery_00000001",
        "transaction": _complete_transaction(),
        "reconciliation": {},
        "decision_snapshot": snapshot,
        "current_context": {
            "capability": snapshot["capability"],
            "revocation": snapshot["revocation"],
            "adopted_release": snapshot["adopted_release"],
            "service_openapi": snapshot["service_openapi"],
            "node_pack": snapshot["node_pack"],
        },
        "cache": _cache(),
        "gpu_lease": _lease(state="held"),
        "rollback": {},
        "journal_entries": [],
        "checkpoints": [],
    }


def test_external_main_dependencies_are_documented() -> None:
    assert "main_remote_execution_history_provider" in EXTERNAL_MAIN_DEPENDENCIES
    assert "main_node_pack_atomic_install_rollback" in EXTERNAL_MAIN_DEPENDENCIES
    assert "main_cache_tombstone_and_rebuild" in EXTERNAL_MAIN_DEPENDENCIES


def test_receipt_last_commit_ready_when_chain_complete() -> None:
    evidence = build_recovery_evidence(_healthy_observation(), decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "accepted"
    assert evidence["transaction"]["receipt_last_order_ok"] is True
    assert evidence["transaction"]["commit_complete"] is True
    assert evidence["transaction"]["commit_ready"] is True
    assert evidence["integrity"]["no_duplicate_execution"] is True
    assert evidence["integrity"]["no_orphan_promotion"] is True
    assert evidence["integrity"]["no_authority_drift"] is True
    assert validate_recovery_evidence(evidence) == ()


def test_receipt_before_artifacts_is_rejected() -> None:
    observation = _healthy_observation()
    observation["transaction"]["completed_phases"] = [
        "reservation",
        "admission",
        "lease_acquired",
        "submitted",
        "provider_result",
        "artifacts_staged",
        "receipt_signed",
        "receipt_written",
        "receipt_committed_event",
        "checkpoint_advanced",
    ]
    observation["transaction"]["current_phase"] = "checkpoint_advanced"
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "rejected"
    assert "receipt_before_artifacts" in evidence["rejection_reasons"]
    assert evidence["transaction"]["commit_ready"] is False


def test_unresolved_receipt_digest_fails_closed() -> None:
    observation = _healthy_observation()
    observation["transaction"]["receipt"] = {
        "receipt_sha256": "deadbeef",
        "resolved": False,
        "artifact_sha256s": [],
    }
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "rejected"
    assert "unresolved_receipt_digest" in evidence["rejection_reasons"]


def test_outcome_unknown_requires_reconciliation_before_retry() -> None:
    observation = _healthy_observation()
    observation["transaction"] = {
        "request_id": "mfareq_recovery_00000001",
        "current_phase": "submitted",
        "completed_phases": ["reservation", "admission", "lease_acquired", "submitted"],
        "submission_state": "outcome_unknown",
        "outcome_unknown": True,
        "retry_requested": True,
        "duplicate_submission_attempted": False,
        "orphan_promotion_attempted": False,
        "authority_granted": False,
        "commit_claimed": False,
        "receipt": {},
        "artifacts": [],
    }
    observation["reconciliation"] = {}
    observation["cache"] = {}
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "rejected"
    assert "outcome_unknown_unreconciled" in evidence["rejection_reasons"]
    assert "resubmit_without_not_found" in evidence["rejection_reasons"]
    assert evidence["reconciliation"]["resubmission_authorized"] is False


@pytest.mark.parametrize(
    ("outcome", "remote_status", "remote", "result", "not_found", "resubmit"),
    [
        ("found_running", "running", True, False, False, False),
        ("found_completed_pending_receipt", "completed", True, True, False, False),
        ("found_failed", "failed", True, False, False, False),
        ("not_found", "not_found", False, False, True, True),
    ],
)
def test_reconciliation_outcomes_are_exact(
    outcome: str,
    remote_status: str,
    remote: bool,
    result: bool,
    not_found: bool,
    resubmit: bool,
) -> None:
    observation = _healthy_observation()
    observation["transaction"] = {
        "request_id": "mfareq_recovery_00000001",
        "current_phase": "submitted",
        "completed_phases": ["reservation", "admission", "lease_acquired", "submitted"],
        "submission_state": "outcome_unknown",
        "outcome_unknown": True,
        "retry_requested": resubmit,
        "duplicate_submission_attempted": False,
        "orphan_promotion_attempted": False,
        "authority_granted": False,
        "commit_claimed": False,
        "receipt": {},
        "artifacts": [],
    }
    observation["cache"] = {}
    observation["reconciliation"] = {
        "outcome": outcome,
        "remote_status": remote_status,
        "remote_execution_id": "remote-1" if remote else None,
        "remote_execution_sha256": "a" * 64 if remote else None,
        "remote_result_sha256": "b" * 64 if result else None,
        "not_found_evidence_sha256": "c" * 64 if not_found else None,
        "checked_at": "2026-07-19T12:01:00Z",
        "resubmission_authorized": resubmit,
    }
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "accepted"
    assert evidence["reconciliation"]["outcome"] == outcome
    assert evidence["reconciliation"]["evidence_valid"] is True
    assert evidence["reconciliation"]["resubmission_authorized"] is resubmit
    assert evidence["integrity"]["no_duplicate_execution"] is True
    assert validate_recovery_evidence(evidence) == ()


def test_duplicate_resubmit_after_found_running_is_rejected() -> None:
    observation = _healthy_observation()
    observation["transaction"] = {
        "request_id": "mfareq_recovery_00000001",
        "current_phase": "submitted",
        "completed_phases": ["reservation", "admission", "lease_acquired", "submitted"],
        "submission_state": "outcome_unknown",
        "outcome_unknown": True,
        "retry_requested": True,
        "duplicate_submission_attempted": True,
        "orphan_promotion_attempted": False,
        "authority_granted": False,
        "commit_claimed": False,
        "receipt": {},
        "artifacts": [],
    }
    observation["cache"] = {}
    observation["reconciliation"] = {
        "outcome": "found_running",
        "remote_status": "running",
        "remote_execution_id": "remote-1",
        "remote_execution_sha256": "a" * 64,
        "remote_result_sha256": None,
        "not_found_evidence_sha256": None,
        "checked_at": "2026-07-19T12:01:00Z",
        "resubmission_authorized": False,
    }
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "rejected"
    assert "duplicate_execution" in evidence["rejection_reasons"]
    assert "resubmit_without_not_found" in evidence["rejection_reasons"]


def test_capability_and_node_pack_drift_refuse_commit() -> None:
    observation = _healthy_observation()
    observation["current_context"]["capability"] = {"capability_sha256": "9" * 64}
    observation["current_context"]["node_pack"] = {
        "node_pack_sha256": "8" * 64,
        "closed_manifest": True,
        "stale_unmanifested_files": False,
    }
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "accepted"
    assert "capability_changed" in evidence["refusal_reasons"]
    assert "node_pack_drift" in evidence["refusal_reasons"]
    assert evidence["transaction"]["commit_ready"] is False
    assert evidence["decision_snapshot"]["capability_unchanged"] is False
    assert evidence["decision_snapshot"]["node_pack_exact"] is False


def test_stale_node_pack_without_closed_manifest_refuses() -> None:
    snapshot = _snapshot(
        node_pack={
            "node_pack_sha256": "f" * 64,
            "closed_manifest": False,
            "stale_unmanifested_files": True,
        }
    )
    observation = _healthy_observation()
    observation["decision_snapshot"] = snapshot
    observation["current_context"]["node_pack"] = snapshot["node_pack"]
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "accepted"
    assert "node_pack_drift" in evidence["refusal_reasons"]
    assert evidence["transaction"]["commit_ready"] is False


def test_gpu_lock_contention_and_foreign_cleanup() -> None:
    observation = _healthy_observation()
    observation["gpu_lease"] = _lease(state="contended")
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "accepted"
    assert "gpu_lease_contention" in evidence["refusal_reasons"]
    assert evidence["gpu_lease"]["held"] is False
    assert evidence["transaction"]["commit_ready"] is False

    observation["gpu_lease"] = _lease(state="held", cleanup=True)
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "rejected"
    assert "gpu_lease_unowned_cleanup" in evidence["rejection_reasons"]
    assert evidence["gpu_lease"]["foreign_token_cleanup_refused"] is False


def test_stale_cache_refuses_freshness() -> None:
    observation = _healthy_observation()
    observation["cache"]["captured_at"] = "2026-07-19T10:00:00Z"
    observation["cache"]["decided_at"] = "2026-07-19T12:01:00Z"
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "accepted"
    assert "cache_stale_or_unbound" in evidence["refusal_reasons"]
    assert evidence["cache"]["fresh"] is False
    assert evidence["transaction"]["commit_ready"] is False


def test_orphan_promotion_and_authority_drift_rejected() -> None:
    observation = _healthy_observation()
    observation["transaction"]["completed_phases"] = [
        "reservation",
        "admission",
        "lease_acquired",
        "submitted",
        "provider_result",
        "artifacts_staged",
        "artifacts_published",
    ]
    observation["transaction"]["current_phase"] = "artifacts_published"
    observation["transaction"]["commit_claimed"] = False
    observation["transaction"]["authority_granted"] = True
    observation["transaction"]["authority_granted_without_checkpoint"] = True
    observation["transaction"]["orphan_promotion_attempted"] = True
    observation["cache"] = {}
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "rejected"
    assert "orphan_artifact_promotion" in evidence["rejection_reasons"]
    assert "authority_drift" in evidence["rejection_reasons"]


@pytest.mark.parametrize(
    "boundary",
    [
        "reservation",
        "admission",
        "lease_acquired",
        "submitted_known",
        "submitted_unknown",
        "provider_result",
        "artifacts_staged",
        "artifacts_published",
        "receipt_signed",
        "receipt_written",
        "receipt_committed_event",
        "checkpoint_advanced",
        "cache_published",
        "install_switch",
        "rollback",
    ],
)
def test_kill_at_every_durable_boundary_recovers_without_drift(boundary: str) -> None:
    evidence = simulate_kill_at_boundary(
        kill_boundary=boundary,
        request_id="mfareq_recovery_kill_0001",
        decided_at="2026-07-19T12:05:00Z",
        recovered_cleanly=True,
    )
    assert evidence["status"] == "accepted"
    assert evidence["kill_boundary"] == boundary
    assert evidence["integrity"]["no_duplicate_execution"] is True
    assert evidence["integrity"]["no_orphan_promotion"] is True
    assert evidence["integrity"]["no_authority_drift"] is True
    assert evidence["integrity"]["kill_boundary_fail_closed"] is True
    assert evidence["transaction"]["commit_ready"] is False
    if boundary == "submitted_unknown":
        assert evidence["reconciliation"]["required"] is True
        assert evidence["reconciliation"]["resubmission_authorized"] is True
        assert evidence["reconciliation"]["outcome"] == "not_found"
    if boundary == "rollback":
        assert evidence["integrity"]["rollback_clean"] is True
    assert validate_recovery_evidence(evidence) == ()


def test_kill_with_authority_grant_fails_closed() -> None:
    evidence = simulate_kill_at_boundary(
        kill_boundary="artifacts_published",
        request_id="mfareq_recovery_kill_bad",
        decided_at="2026-07-19T12:05:00Z",
    )
    # Mutate via direct observation to claim authority after kill.
    observation = {
        "request_id": "mfareq_recovery_kill_bad",
        "kill_boundary": "artifacts_published",
        "recovered_cleanly": False,
        "transaction": {
            "request_id": "mfareq_recovery_kill_bad",
            "current_phase": "artifacts_published",
            "completed_phases": [
                "reservation",
                "admission",
                "lease_acquired",
                "submitted",
                "provider_result",
                "artifacts_staged",
                "artifacts_published",
            ],
            "submission_state": "submitted",
            "authority_granted": True,
            "orphan_promotion_attempted": True,
            "duplicate_submission_attempted": True,
            "commit_claimed": False,
            "receipt": {},
            "artifacts": [{"artifact_sha256": "22" * 32}],
        },
        "reconciliation": {},
        "decision_snapshot": _snapshot(),
        "current_context": {},
        "cache": {},
        "gpu_lease": _lease(state="held"),
        "rollback": {},
    }
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:05:00Z")
    assert evidence["status"] == "rejected"
    assert "kill_boundary_fail_closed" in evidence["rejection_reasons"]
    assert "orphan_artifact_promotion" in evidence["rejection_reasons"]
    assert "duplicate_execution" in evidence["rejection_reasons"]


def test_rollback_drill_without_duplicate_or_drift() -> None:
    observation = _healthy_observation()
    observation["transaction"]["commit_claimed"] = False
    observation["transaction"]["authority_granted"] = False
    observation["cache"] = {}
    observation["rollback"] = {
        "started": True,
        "completed": True,
        "duplicate_execution": False,
        "orphan_promotion": False,
        "authority_drift": False,
        "from_release_sha256": "d" * 64,
        "to_release_sha256": "e" * 64,
        "evidence_sha256": "f" * 64,
    }
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "accepted"
    assert evidence["integrity"]["rollback_clean"] is True
    assert evidence["integrity"]["no_duplicate_execution"] is True

    observation["rollback"]["completed"] = False
    observation["rollback"]["authority_drift"] = True
    evidence = build_recovery_evidence(observation, decided_at="2026-07-19T12:01:00Z")
    assert evidence["status"] == "rejected"
    assert "rollback_incomplete" in evidence["rejection_reasons"]
    assert "authority_drift" in evidence["rejection_reasons"]


def test_unsupported_kill_boundary_raises() -> None:
    with pytest.raises(RecoveryError):
        simulate_kill_at_boundary(
            kill_boundary="not_a_boundary",
            request_id="x",
            decided_at="2026-07-19T12:05:00Z",
        )
