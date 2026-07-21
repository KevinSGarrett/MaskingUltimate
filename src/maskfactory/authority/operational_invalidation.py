"""Evaluate immutable operational certificates against signed current state.

Certificates are historical evidence.  This module never changes their bytes:
it produces a separate, hash-bound at-use decision from a fresh signed state
snapshot.  A snapshot may revoke only its exact certificate payload; dependency
drift applies only to the certificate whose recorded bindings no longer match.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from maskfactory.validation import (
    ValidationIssue,
    canonical_document_sha256,
    canonical_json_bytes,
    validate_operational_autonomy_certificate,
    validate_operational_invalidation_event,
)

_MAX_STATE_AGE_SECONDS = 300
_REQUIRED_CURRENT_BINDINGS = (
    "pipeline_sha256",
    "policy_sha256",
    "ontology_sha256",
    "execution_fingerprint_sha256",
    "provider_stack_sha256",
    "provider_lifecycle",
)


class OperationalInvalidationError(ValueError):
    """Raised when a current-state snapshot cannot be trusted."""


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _state_payload(snapshot: Mapping[str, Any]) -> bytes:
    unsigned = {key: value for key, value in snapshot.items() if key != "signature"}
    return canonical_json_bytes(unsigned)


def _verify_snapshot(
    snapshot: Mapping[str, Any],
    *,
    trusted_state_keys: Mapping[str, Mapping[str, Any]],
    use_time: datetime,
) -> list[str]:
    reasons: list[str] = []
    if snapshot.get("record_type") != "operational_authority_current_state":
        reasons.append("current_state_type_invalid")
    observed = _parse_timestamp(snapshot.get("observed_at"))
    if (
        observed is None
        or observed > use_time
        or (use_time - observed).total_seconds() > _MAX_STATE_AGE_SECONDS
    ):
        reasons.append("current_state_stale")
    signature = snapshot.get("signature")
    if not isinstance(signature, Mapping):
        return [*reasons, "current_state_signature_missing"]
    key_id = signature.get("key_id")
    record = trusted_state_keys.get(key_id) if isinstance(key_id, str) else None
    if not isinstance(record, Mapping) or record.get("status") != "active":
        return [*reasons, "current_state_signer_untrusted"]
    try:
        public = base64.b64decode(record["public_key_base64"], validate=True)
        value = base64.b64decode(signature["value_base64"], validate=True)
        Ed25519PublicKey.from_public_bytes(public).verify(value, _state_payload(snapshot))
    except (KeyError, TypeError, ValueError, InvalidSignature):
        reasons.append("current_state_signature_invalid")
    return reasons


def _certificate_bindings(certificate: Mapping[str, Any]) -> dict[str, Any]:
    pipeline = certificate.get("pipeline_policy_binding", {})
    ontology = certificate.get("ontology_binding", {})
    execution = certificate.get("execution_binding", {})
    return {
        "pipeline_sha256": pipeline.get("pipeline_sha256"),
        "policy_sha256": pipeline.get("policy_sha256"),
        "ontology_sha256": ontology.get("sha256"),
        "execution_fingerprint_sha256": execution.get("execution_fingerprint_sha256"),
        "provider_stack_sha256": execution.get("provider_stack_sha256"),
        "provider_lifecycle": "promoted",
    }


def _exact_revocation_matches(
    revocation: Mapping[str, Any], certificate: Mapping[str, Any]
) -> bool:
    return revocation.get("certificate_id") == certificate.get("certificate_id") and revocation.get(
        "certificate_payload_sha256"
    ) == certificate.get("certificate_payload_sha256")


def evaluate_operational_certificate_at_use(
    certificate: Mapping[str, Any],
    *,
    current_state: Mapping[str, Any],
    trusted_state_keys: Mapping[str, Mapping[str, Any]],
    use_time: str,
    trusted_certificate_keys: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Return an immutable, exact-scope authorization decision at ``use_time``."""

    parsed_use_time = _parse_timestamp(use_time)
    if parsed_use_time is None:
        raise OperationalInvalidationError("use_time_invalid")
    reasons = _verify_snapshot(
        current_state, trusted_state_keys=trusted_state_keys, use_time=parsed_use_time
    )
    certificate_issues = validate_operational_autonomy_certificate(
        certificate,
        trusted_signing_keys=trusted_certificate_keys,
        at_time=use_time,
        production_required=True,
    )
    reasons.extend(f"certificate_{issue.validator}" for issue in certificate_issues)

    bindings = current_state.get("current_bindings")
    if not isinstance(bindings, Mapping) or set(bindings) != set(_REQUIRED_CURRENT_BINDINGS):
        reasons.append("current_bindings_invalid")
    else:
        expected = _certificate_bindings(certificate)
        for field, value in expected.items():
            if bindings.get(field) != value:
                reasons.append(f"{field}_drift")

    for item in current_state.get("revocations", ()):
        if not isinstance(item, Mapping):
            reasons.append("revocation_record_invalid")
        elif _exact_revocation_matches(item, certificate):
            status = item.get("status")
            if status not in {"revoked", "superseded", "expired"}:
                reasons.append("revocation_record_invalid")
            else:
                reasons.append(f"certificate_{status}")

    unique_reasons = tuple(sorted(set(reasons)))
    core = {
        "schema_version": "1.0.0",
        "record_type": "operational_certificate_at_use_decision",
        "certificate_id": certificate.get("certificate_id"),
        "certificate_payload_sha256": certificate.get("certificate_payload_sha256"),
        "use_time": use_time,
        "current_state_sha256": hashlib.sha256(_state_payload(current_state)).hexdigest(),
        "status": "allow" if not unique_reasons else "reject",
        "reasons": list(unique_reasons),
    }
    return {**core, "decision_sha256": canonical_document_sha256(core)}


def verify_operational_invalidation_event(
    event: Mapping[str, Any],
    *,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
    expected_journal_position: Mapping[str, Any] | None = None,
    seen_event_ids: tuple[str, ...] = (),
    seen_idempotency_keys: Mapping[str, str] | None = None,
) -> tuple[ValidationIssue, ...]:
    """Return strict validation findings for operational invalidation events."""
    return validate_operational_invalidation_event(
        event,
        trusted_signing_keys=trusted_signing_keys,
        expected_journal_position=expected_journal_position,
        seen_event_ids=seen_event_ids,
        seen_idempotency_keys=seen_idempotency_keys,
    )


__all__ = [
    "OperationalInvalidationError",
    "evaluate_operational_certificate_at_use",
    "verify_operational_invalidation_event",
]
