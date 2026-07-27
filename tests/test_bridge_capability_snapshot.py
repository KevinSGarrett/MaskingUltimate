from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from maskfactory.bridge.capability_snapshot import (
    CapabilityQualificationError,
    _canonical_stack,
    build_capability_decision,
    restore_route_champion_from_rollback,
    validate_capability_decision,
)
from maskfactory.validation import canonical_document_sha256


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _certificate(stack: dict, now: datetime, revocation_index: dict) -> bytes:
    certificate = {
        "certificate_id": "cert-route-one",
        "signer_id": "benchmark-ca-1",
        "signer_role": "capability_qualification",
        "issuer_kind": "independent_benchmark",
        "status": "active",
        "route_id": "route-one",
        "stack_sha256": stack["stack_sha256"],
        "qualification_scope_sha256": stack["qualification_scope"]["scope_sha256"],
        "valid_from": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "valid_until": (now + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "revocation_head_sha256": canonical_document_sha256(revocation_index),
        "payload_sha256": "",
        "signed_payload_sha256": "",
    }
    certificate["payload_sha256"] = canonical_document_sha256(
        certificate, excluded_top_level_fields=("payload_sha256", "signed_payload_sha256")
    )
    certificate["signed_payload_sha256"] = certificate["payload_sha256"]
    return json.dumps(certificate).encode()


def _inputs() -> tuple[dict, dict, str]:
    now = datetime(2026, 7, 19, 12, tzinfo=UTC)
    decision_time = now.isoformat().replace("+00:00", "Z")
    blobs = {
        "model-one": b"model-one",
        "workflow": b"workflow",
        "runtime_lock": b"runtime-lock",
        "hardware_profile": b"hardware-profile",
        "route_key": b"route-key",
    }
    stack = {
        "stack_id": "stack.one",
        "capability_ids": ["segment"],
        "roles": ["primary"],
        "labels": ["body"],
        "access_modes": ["mode_b_live_predict"],
        "media_scopes": ["still_image"],
        "model_artifacts": [{"model_id": "model-one", "sha256": _sha(blobs["model-one"])}],
        "workflow": {"workflow_id": "workflow-one", "sha256": _sha(blobs["workflow"])},
        "runtime": {"environment_lock_sha256": _sha(blobs["runtime_lock"])},
        "hardware": {"hardware_profile_sha256": _sha(blobs["hardware_profile"])},
        "route_key": {"route_key_id": "route-one", "sha256": _sha(blobs["route_key"])},
        "performance_profile": {"profile_id": "profile-one", "sha256": "1" * 64},
        "champion_binding": {
            "champion_id": "champion-one",
            "champion_sha256": "2" * 64,
            "status": "current",
        },
        "qualification_scope": {"scope_sha256": "3" * 64},
        "lifecycle": "promoted",
        "certificate_ids": ["cert-route-one"],
    }
    stack["stack_sha256"] = _canonical_stack(stack)
    snapshot = {
        "snapshot_id": "mfcap_0123456789abcdef01234567",
        "provider_stacks": [stack],
        "snapshot_sha256": "",
    }
    snapshot["snapshot_sha256"] = canonical_document_sha256(
        snapshot, excluded_top_level_fields=("snapshot_sha256",)
    )
    entry_base = {
        "route_id": "route-one",
        "stack_sha256": stack["stack_sha256"],
        "self_reported": False,
        "independence": "independent",
        "observed_at": decision_time,
    }
    ledger = []
    previous = ""
    for source, correlation in (("lab-a", "family-a"), ("lab-b", "family-b")):
        entry = {
            **entry_base,
            "evidence_source_id": source,
            "correlation_group": correlation,
            "previous_entry_sha256": previous,
            "entry_sha256": "",
        }
        entry["entry_sha256"] = canonical_document_sha256(
            entry, excluded_top_level_fields=("entry_sha256",)
        )
        previous = entry["entry_sha256"]
        ledger.append(entry)
    release_bytes = b'{"release":"trusted"}'
    revocation_index = {"revoked_certificate_ids": []}
    evidence = {
        "artifact_bytes": blobs,
        "certificate_bytes": {"cert-route-one": _certificate(stack, now, revocation_index)},
        "certificate_authority_bytes": b"",
        "release_publication": {
            "id": "pub-one",
            "bytes": release_bytes,
            "sha256": _sha(release_bytes),
        },
        "revocation_index": revocation_index,
        "performance_ledger": ledger,
        "previous_decision": {"qualified_routes": [{"stack_sha256": stack["stack_sha256"]}]},
        "rollback_state": {
            "route-one": {
                "current_stack_sha256": stack["stack_sha256"],
                "rollback_stack_sha256": "4" * 64,
                "tested_ledger_entry_sha256": ledger[-1]["entry_sha256"],
            }
        },
    }
    authority = {
        "authority_id": "benchmark-ca",
        "status": "active",
        "trusted_signer_ids": ["benchmark-ca-1"],
        "authority_sha256": "",
    }
    authority["authority_sha256"] = canonical_document_sha256(
        authority, excluded_top_level_fields=("authority_sha256",)
    )
    evidence["certificate_authority_bytes"] = json.dumps(authority).encode()
    return snapshot, evidence, decision_time


def test_resolves_only_actual_independently_qualified_routes() -> None:
    snapshot, evidence, time = _inputs()
    decision = build_capability_decision(snapshot, evidence, decided_at=time)
    assert decision["status"] == "accepted"
    assert [route["route_id"] for route in decision["qualified_routes"]] == ["route-one"]
    assert validate_capability_decision(decision) == ()


def test_changed_bytes_stale_certificate_and_correlated_evidence_fail_closed() -> None:
    snapshot, evidence, time = _inputs()
    evidence["artifact_bytes"]["model-one"] = b"changed-model"
    evidence["certificate_bytes"]["cert-route-one"] = b"{}"
    for entry in evidence["performance_ledger"]:
        entry["correlation_group"] = "shared"
        entry["entry_sha256"] = "0" * 64
    decision = build_capability_decision(snapshot, evidence, decided_at=time)
    assert decision["status"] == "rejected"
    assert decision["qualified_routes"] == []
    assert "model_artifact_bytes_drift" in decision["rejection_reasons"]
    assert "qualification_certificate_unresolved" in decision["rejection_reasons"]
    assert "performance_evidence_not_independent_or_fresh" in decision["rejection_reasons"]


def test_newly_installed_or_unqualified_stack_stays_challenger() -> None:
    snapshot, evidence, time = _inputs()
    evidence["previous_decision"] = {"qualified_routes": []}
    decision = build_capability_decision(snapshot, evidence, decided_at=time)
    assert decision["status"] == "rejected"
    assert decision["qualified_routes"] == []
    assert decision["challenger_routes"][0]["stack_id"] == "stack.one"
    assert "newcomer_direct_promotion" in decision["rejection_reasons"]


def test_stale_self_reported_evidence_and_rollback_drift_cannot_promote() -> None:
    snapshot, evidence, time = _inputs()
    for entry in evidence["performance_ledger"]:
        entry["self_reported"] = True
        entry["observed_at"] = "2000-01-01T00:00:00Z"
        entry["entry_sha256"] = "0" * 64
    evidence["rollback_state"]["route-one"]["rollback_stack_sha256"] = snapshot["provider_stacks"][
        0
    ]["stack_sha256"]
    decision = build_capability_decision(snapshot, evidence, decided_at=time)
    assert decision["status"] == "rejected"
    assert decision["qualified_routes"] == []
    assert "performance_evidence_not_independent_or_fresh" in decision["rejection_reasons"]
    assert "rollback_binding_unverified" in decision["rejection_reasons"]


def test_honest_partial_library_is_valid_when_no_route_is_claimed() -> None:
    snapshot, evidence, time = _inputs()
    snapshot["provider_stacks"] = []
    snapshot["snapshot_sha256"] = canonical_document_sha256(
        snapshot, excluded_top_level_fields=("snapshot_sha256",)
    )
    decision = build_capability_decision(snapshot, evidence, decided_at=time)
    assert decision["status"] == "accepted"
    assert decision["qualified_routes"] == []
    assert decision["challenger_routes"] == []


def test_release_publication_editable_install_rejects_decision() -> None:
    snapshot, evidence, time = _inputs()
    publication = {
        "record_type": "maskfactory_release_publication_evidence",
        "repository_observation": {"clean": True},
        "installation": {"argv": ["python", "-m", "pip", "install", "-e", "."]},
        "rollback": {"argv": ["python", "rollback.py"]},
    }
    publication_bytes = json.dumps(publication, sort_keys=True).encode()
    evidence["release_publication"] = {
        "id": "pub-one",
        "bytes": publication_bytes,
        "sha256": _sha(publication_bytes),
    }
    decision = build_capability_decision(snapshot, evidence, decided_at=time)
    assert decision["status"] == "rejected"
    assert "release_publication_editable_install_forbidden" in decision["rejection_reasons"]


def test_close_route_branch_budget_and_rollback_restore_prior_champion() -> None:
    snapshot, evidence, time = _inputs()
    evidence["close_route_branches"] = [
        {
            "route_id": "route-one",
            "score_a": 0.91,
            "score_b": 0.90,
            "branch_attempts": 3,
        }
    ]
    over_budget = build_capability_decision(snapshot, evidence, decided_at=time)
    assert over_budget["status"] == "rejected"
    assert "close_route_branch_budget_exceeded" in over_budget["rejection_reasons"]

    evidence["close_route_branches"] = [
        {
            "route_id": "route-one",
            "score_a": 0.91,
            "score_b": 0.90,
            "branch_attempts": 2,
        }
    ]
    decision = build_capability_decision(snapshot, evidence, decided_at=time)
    assert decision["status"] == "accepted"
    restored = restore_route_champion_from_rollback(decision, route_id="route-one")
    assert restored["restored_champion_stack_sha256"] == "4" * 64
    assert (
        restored["previous_champion_stack_sha256"]
        == decision["qualified_routes"][0]["stack_sha256"]
    )
    with pytest.raises(CapabilityQualificationError):
        restore_route_champion_from_rollback(over_budget, route_id="route-one")
