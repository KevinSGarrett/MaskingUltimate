from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path

from maskfactory.bridge.consumer_invalidation import (
    build_consumer_invalidation_decision,
    validate_consumer_invalidation_decision,
)
from maskfactory.validation import canonical_document_sha256

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/mask_bridge_contracts/positive_contract_set_v1.json"
BUILDER = runpy.run_path(
    str(ROOT / "tests/fixtures/mask_bridge_contracts/build_contract_fixtures.py")
)
CHAIN_HELPERS = runpy.run_path(str(ROOT / "tests/test_mask_bridge_contracts_v1.py"))
TRUSTED_KEYS = BUILDER["TRUSTED_KEYS"]


def _fixtures() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def _invalidation_event(reason: str = "certificate_revoked") -> dict:
    event = copy.deepcopy(_fixtures()["mask_authority_invalidation_event"])
    if reason == "release_revoked":
        transition = event["target_transitions"][0]
        transition["target_kind"] = "release"
        transition["target_id"] = "mfr_rollback_source"
        transition["target_sha256"] = "d" * 64
        transition["scope_sha256"] = canonical_document_sha256(
            {
                "target_kind": transition["target_kind"],
                "target_id": transition["target_id"],
                "target_sha256": transition["target_sha256"],
                "previous_authority_state": transition["previous_authority_state"],
                "new_authority_state": transition["new_authority_state"],
                "previous_certificate_status": transition["previous_certificate_status"],
                "new_certificate_status": transition["new_certificate_status"],
                "reason_code": transition["reason_code"],
            }
        )
        event["reason"] = "release_revoked"
        event["required_actions"] = [
            {
                "action_id": "action-rollback-release",
                "transition_ids": [transition["transition_id"]],
                "action": "rollback_release",
                "deadline_at": "2026-07-17T00:10:00Z",
                "verification_evidence_required": True,
                "verification_policy_sha256": "b" * 64,
            },
            {
                "action_id": "action-revalidate-adoption",
                "transition_ids": [transition["transition_id"]],
                "action": "revalidate_adoption",
                "deadline_at": "2026-07-17T00:10:00Z",
                "verification_evidence_required": True,
                "verification_policy_sha256": "c" * 64,
            },
        ]
    BUILDER["sign"](
        event, "event_payload_sha256", "producer_journal", ("event_payload_sha256", "signature")
    )
    return event


def _journal_chain(invalidation_event: dict) -> list[dict]:
    make_event = CHAIN_HELPERS["_journal_event"]
    published = make_event("release_published", 1, "MaskFactory", "release", "none", "published")
    adopted = make_event(
        "release_adopted",
        2,
        "Comfy_UI_Main",
        "release",
        "published",
        "adopted",
        previous=published,
    )
    revalidation = make_event(
        "adoption_revalidation_required",
        3,
        "Comfy_UI_Main",
        "release",
        "adopted",
        "revalidation_required",
        previous=adopted,
        invalidation=invalidation_event,
    )
    return [published, adopted, revalidation]


def _action_evidence(event: dict) -> dict[str, dict[str, str]]:
    return {
        row["action_id"]: {
            "status": "performed",
            "evidence_sha256": canonical_document_sha256(
                {"action_id": row["action_id"], "action": row["action"], "evidence": "performed"}
            ),
        }
        for row in event.get("required_actions", [])
    }


def _base_inputs(reason: str = "certificate_revoked") -> dict:
    event = _invalidation_event(reason)
    journal = _journal_chain(event)
    return {
        "event": event,
        "trusted_signing_keys": TRUSTED_KEYS,
        "bridge_journal_events": journal,
        "expected_journal_head_sha256": journal[-1]["event_payload_sha256"],
        "consumer_action_evidence": _action_evidence(event),
        "cache_snapshot": {
            "snapshot_sha256": "1" * 64,
            "captured_at": "2026-07-17T00:05:01Z",
            "invalidated_scope_sha256": event["target_transitions"][0]["scope_sha256"],
        },
        "revocation_head": {
            "expected_head_sha256": "2" * 64,
            "observed_head_sha256": "2" * 64,
            "observed_at": "2026-07-17T00:05:01Z",
        },
        "recovery_markers": [
            {"marker": "recovery_started", "journal_head_sha256": "3" * 64},
            {"marker": "recovery_completed", "journal_head_sha256": "3" * 64},
        ],
        "rollback_proof": {
            "target_release_id": "mfr_prev_compatible",
            "target_release_sha256": "4" * 64,
            "compatibility_checks_passed": True,
            "compatibility_proof_sha256": "5" * 64,
            "proof_artifacts": [
                {"kind": "compatibility_proof", "sha256": "5" * 64},
                {"kind": "route_table_snapshot", "sha256": "6" * 64},
                {"kind": "cache_tombstone_manifest", "sha256": "7" * 64},
            ],
        },
        "compatible_release_history": [
            {
                "release_id": "mfr_prev_compatible",
                "release_payload_sha256": "4" * 64,
                "compatible": True,
                "revoked": False,
            },
            {
                "release_id": "mfr_older_compatible",
                "release_payload_sha256": "9" * 64,
                "compatible": True,
                "revoked": False,
            },
        ],
    }


def test_rejects_stale_cache_snapshot_fail_closed() -> None:
    inputs = _base_inputs()
    inputs["cache_snapshot"]["captured_at"] = "2026-07-16T00:00:00Z"
    decision = build_consumer_invalidation_decision(**inputs)
    assert decision["status"] == "rejected"
    assert "stale_cache_snapshot" in decision["rejection_reasons"]
    assert validate_consumer_invalidation_decision(decision) == ()


def test_rejects_revocation_head_drift_fail_closed() -> None:
    inputs = _base_inputs()
    inputs["revocation_head"]["observed_head_sha256"] = "f" * 64
    decision = build_consumer_invalidation_decision(**inputs)
    assert decision["status"] == "rejected"
    assert "revocation_head_drift" in decision["rejection_reasons"]


def test_rejects_missing_restart_recovery_markers_fail_closed() -> None:
    inputs = _base_inputs()
    inputs["recovery_markers"] = [{"marker": "recovery_started", "journal_head_sha256": "3" * 64}]
    decision = build_consumer_invalidation_decision(**inputs)
    assert decision["status"] == "rejected"
    assert "restart_recovery_marker_missing" in decision["rejection_reasons"]


def test_rejects_rollback_target_without_compatibility_proof_artifacts() -> None:
    inputs = _base_inputs("release_revoked")
    inputs["rollback_proof"]["proof_artifacts"] = [
        {"kind": "route_table_snapshot", "sha256": "6" * 64}
    ]
    inputs["compatible_release_history"][0]["release_id"] = "mfr_newer_expected"
    decision = build_consumer_invalidation_decision(**inputs)
    assert decision["status"] == "rejected"
    assert "compatibility_proof_artifact_missing" in decision["rejection_reasons"]
    assert "rollback_target_not_last_compatible" in decision["rejection_reasons"]


def test_governance_vectors_cover_consumer_invalidation_fail_closed_cases() -> None:
    vectors = json.loads(
        (
            Path("qa/governance/bridge/consumer_invalidation_golden_vectors_v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    assert vectors["policy_id"] == "maskfactory-bridge-consumer-invalidation-v1"
    assert vectors["validator"] == "build_consumer_invalidation_decision"
    assert len(vectors["cases"]) == 4
