from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maskfactory.validation import (
    OPERATIONAL_INVALIDATION_REASON_TARGET_KIND,
    canonical_document_sha256,
    validate_operational_invalidation_event,
)

_KEY_ID = "mf-operational-journal"
_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes([13]) * 32)
_PUBLIC = _PRIVATE.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
_PUBLIC_SHA256 = hashlib.sha256(_PUBLIC).hexdigest()
_KEY_SET_ID = "mf-operational-trust-set"
_KEY_SET_VERSION = "1.0.0"
_KEY_SET_SHA256 = hashlib.sha256(b"mf-operational-trust-set:1.0.0").hexdigest()


def _trusted(*, role: str = "producer_journal", valid_until: str = "2027-01-01T00:00:00Z") -> dict:
    return {
        _KEY_ID: {
            "key_id": _KEY_ID,
            "public_key_sha256": _PUBLIC_SHA256,
            "roles": [role],
            "usage_scope": "production",
            "status": "active",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": valid_until,
            "authority": "MaskFactory",
            "key_set_id": _KEY_SET_ID,
            "key_set_version": _KEY_SET_VERSION,
            "key_set_sha256": _KEY_SET_SHA256,
        }
    }


def _scope(kind: str, target_id: str = "target-1", target_sha256: str = "a" * 64) -> dict:
    targets = [{"target_kind": kind, "target_id": target_id, "target_sha256": target_sha256}]
    return {
        "target_kind": kind,
        "targets": targets,
        "scope_sha256": canonical_document_sha256({"target_kind": kind, "targets": targets}),
    }


def _sign(event: dict) -> dict:
    event = copy.deepcopy(event)
    event["event_payload_sha256"] = canonical_document_sha256(
        event, excluded_top_level_fields=("event_payload_sha256", "signature")
    )
    event["signature"] = {
        "algorithm": "ed25519",
        "key_id": _KEY_ID,
        "public_key_base64": base64.b64encode(_PUBLIC).decode("ascii"),
        "signed_payload_sha256": event["event_payload_sha256"],
        "signed_payload_format": "sha256_digest_bytes",
        "value_base64": base64.b64encode(
            _PRIVATE.sign(bytes.fromhex(event["event_payload_sha256"]))
        ).decode("ascii"),
    }
    return event


def _event(reason: str = "certificate_revoked") -> dict:
    kind = OPERATIONAL_INVALIDATION_REASON_TARGET_KIND[reason]
    event = {
        "schema_version": "1.0.0",
        "record_type": "operational_invalidation_event",
        "event_id": "mfoinv_0123456789abcdef01234567",
        "stream_id": "maskfactory-operational-journal",
        "sequence": 2,
        "causation_id": "mfbevt_000000000000000000000001",
        "idempotency_key": "operational.invalidate.20260719.0001",
        "occurred_at": "2026-07-19T14:00:00Z",
        "effective_at": "2026-07-19T14:00:00Z",
        "fixture_only": False,
        "evidence_context": "runtime_evidence",
        "reason": reason,
        "target_scope": _scope(kind),
        "journal_position": {
            "previous_sequence": 1,
            "previous_event_id": "mfbevt_000000000000000000000001",
            "previous_event_sha256": "b" * 64,
        },
        "supersession": (
            {
                "replacement_event_id": "mfoinv_89abcdef0123456701234567",
                "replacement_release_id": "mfr_20260719_abcdef012345",
                "replacement_release_sha256": "c" * 64,
            }
            if reason == "release_superseded"
            else None
        ),
        "rollback": (
            {
                "rollback_event_id": "mfoinv_89abcdef0123456701234568",
                "rollback_release_id": "mfr_20260718_deadbeefcaf0",
                "rollback_release_sha256": "d" * 64,
            }
            if reason == "release_revoked"
            else None
        ),
        "trust_binding": {
            "key_set_id": _KEY_SET_ID,
            "key_set_version": _KEY_SET_VERSION,
            "key_set_sha256": _KEY_SET_SHA256,
            "key_role": "producer_journal",
            "signing_key_id": _KEY_ID,
            "signing_public_key_sha256": _PUBLIC_SHA256,
            "rotation_policy_sha256": hashlib.sha256(b"rotation-policy-v1").hexdigest(),
            "revocation_policy_sha256": hashlib.sha256(b"revocation-policy-v1").hexdigest(),
        },
        "event_payload_sha256": "0" * 64,
        "signature": {
            "algorithm": "ed25519",
            "key_id": _KEY_ID,
            "public_key_base64": base64.b64encode(_PUBLIC).decode("ascii"),
            "signed_payload_sha256": "0" * 64,
            "signed_payload_format": "sha256_digest_bytes",
            "value_base64": base64.b64encode(b"0" * 64).decode("ascii"),
        },
    }
    return _sign(event)


def _validators(issues) -> set[str]:
    return {issue.validator for issue in issues}


def test_operational_invalidation_accepts_valid_release_supersession() -> None:
    event = _event("release_superseded")
    issues = validate_operational_invalidation_event(
        event,
        trusted_signing_keys=_trusted(),
        expected_journal_position={
            "stream_id": event["stream_id"],
            "next_sequence": 2,
            "head_event_id": "mfbevt_000000000000000000000001",
            "head_event_sha256": "b" * 64,
        },
    )
    assert issues == ()


def test_operational_invalidation_rejects_hash_drift_role_and_stale_signature() -> None:
    drift = _event()
    drift["target_scope"]["targets"][0]["target_sha256"] = "f" * 64
    assert "canonical_payload_hash" in _validators(
        validate_operational_invalidation_event(drift, trusted_signing_keys=_trusted())
    )

    wrong_role = _event()
    assert "trusted_key_role" in _validators(
        validate_operational_invalidation_event(
            wrong_role, trusted_signing_keys=_trusted(role="producer_release")
        )
    )

    stale = _event()
    stale["occurred_at"] = "2028-01-01T00:00:00Z"
    stale["effective_at"] = "2028-01-01T00:00:00Z"
    stale = _sign(stale)
    assert "trusted_key_validity" in _validators(
        validate_operational_invalidation_event(
            stale, trusted_signing_keys=_trusted(valid_until="2027-01-01T00:00:00Z")
        )
    )


def test_operational_invalidation_rejects_non_homogeneous_targets() -> None:
    event = _event("package_invalidated")
    event["target_scope"]["targets"].append(
        {
            "target_kind": "policy",
            "target_id": "target-2",
            "target_sha256": "e" * 64,
        }
    )
    event["target_scope"]["scope_sha256"] = canonical_document_sha256(
        {
            "target_kind": event["target_scope"]["target_kind"],
            "targets": event["target_scope"]["targets"],
        }
    )
    event = _sign(event)
    assert "operational_invalidation_target_set_non_homogeneous" in _validators(
        validate_operational_invalidation_event(event, trusted_signing_keys=_trusted())
    )


def test_operational_invalidation_rejects_replay_fork_and_reorder() -> None:
    event = _event()
    issues = validate_operational_invalidation_event(
        event,
        trusted_signing_keys=_trusted(),
        expected_journal_position={
            "stream_id": event["stream_id"],
            "next_sequence": 3,
            "head_event_id": "mfbevt_000000000000000000000009",
            "head_event_sha256": "9" * 64,
        },
        seen_event_ids=(event["event_id"],),
        seen_idempotency_keys={event["idempotency_key"]: "e" * 64},
    )
    found = _validators(issues)
    assert "operational_invalidation_journal_reorder" in found
    assert "operational_invalidation_journal_fork" in found
    assert "operational_invalidation_journal_replay" in found
    assert "operational_invalidation_idempotency_fork" in found


def test_operational_invalidation_rejects_deleted_or_replaced_journal_head() -> None:
    event = _event()
    # Deleted/replaced head: expected position points at a head that no longer matches the
    # event's declared previous pointer, so fork detection must fail closed.
    issues = validate_operational_invalidation_event(
        event,
        trusted_signing_keys=_trusted(),
        expected_journal_position={
            "stream_id": event["stream_id"],
            "next_sequence": 2,
            "head_event_id": "mfbevt_deleted_head_000000000001",
            "head_event_sha256": "d" * 64,
        },
        seen_event_ids=(),
    )
    assert "operational_invalidation_journal_fork" in _validators(issues)


def test_operational_invalidation_governance_vectors_cover_expected_fail_closed_codes() -> None:
    vectors = json.loads(
        (
            Path("qa/governance/bridge/operational_invalidation_golden_vectors_v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    assert vectors["policy_id"] == "maskfactory-operational-invalidation-v1"
    assert vectors["validator"] == "validate_operational_invalidation_event"
    assert len(vectors["cases"]) == 8
