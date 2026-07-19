"""Trusted, checkpointed append-only producer bridge journal contracts.

This module is producer-side durable contract plumbing for MF-P6-11.06.
It signs journal entries and checkpoints, enforces closed state transitions,
validates replay/idempotency and append-only integrity, and reconstructs exact
in-memory durable state after interruption.

External Main dependencies (explicit):
- Main must persist successful appends atomically with surrounding business side effects.
- Main must durably retain the append-only entry stream and checkpoint stream.
- Main must provide a stable idempotency-key namespace and deduplicated retry surface.
- Main must supply trusted producer journal signing keys and rotation/revocation policy.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from jsonschema import Draft202012Validator

from maskfactory.validation import canonical_document_sha256

POLICY_PATH = Path(__file__).parents[3] / "configs" / "bridge_durable_journal_policy.yaml"
SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "bridge_journal_reconstruction_evidence.schema.json"
)
POLICY_ID = "maskfactory-bridge-durable-journal-v1"

# Closed durable state machine vocabulary for MF-P6-11.06.
# ``submit`` is retained as the generic/legacy submit alias beside submit_known/unknown.
JOURNAL_STATES = (
    "admit",
    "route",
    "lease",
    "submit",
    "submit_known",
    "submit_unknown",
    "reconcile",
    "result",
    "validate",
    "cache",
    "decision",
    "feedback",
    "adoption",
    "invalidation",
    "retry",
    "repair",
    "recovery",
    "rollback",
)
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "admit": frozenset({"route", "rollback"}),
    # Legacy path may skip lease and go directly to submit*.
    "route": frozenset(
        {"lease", "submit", "submit_known", "submit_unknown", "recovery", "rollback"}
    ),
    "lease": frozenset({"submit", "submit_known", "submit_unknown", "recovery", "rollback"}),
    "submit": frozenset({"reconcile", "retry", "repair", "recovery", "rollback"}),
    "submit_known": frozenset({"reconcile", "retry", "repair", "recovery", "rollback"}),
    # Unknown submissions must reconcile before retry.
    "submit_unknown": frozenset({"reconcile", "recovery", "rollback"}),
    "reconcile": frozenset({"result", "retry", "repair", "recovery", "rollback"}),
    # Short path may skip validate/cache into decision (feedback intake).
    "result": frozenset({"validate", "decision", "retry", "repair", "recovery", "rollback"}),
    "validate": frozenset({"cache", "decision", "retry", "repair", "recovery", "rollback"}),
    "cache": frozenset({"decision", "feedback", "recovery", "rollback"}),
    "decision": frozenset(
        {"feedback", "adoption", "invalidation", "retry", "repair", "recovery", "rollback"}
    ),
    "feedback": frozenset({"adoption", "invalidation", "retry", "repair", "recovery", "rollback"}),
    "adoption": frozenset({"invalidation", "recovery", "rollback"}),
    "invalidation": frozenset({"recovery", "rollback"}),
    "retry": frozenset({"route", "lease", "submit", "submit_known", "recovery", "rollback"}),
    "repair": frozenset({"route", "lease", "submit", "submit_known", "recovery", "rollback"}),
    "recovery": frozenset({"route", "lease", "reconcile", "rollback"}),
    "rollback": frozenset(),
}
EXTERNAL_MAIN_DEPENDENCIES = (
    "main_atomic_append_side_effect_commit",
    "main_durable_append_only_retention",
    "main_idempotency_key_namespace",
    "main_trusted_journal_key_lifecycle",
)
_SIGNATURE_FIELDS = (
    "algorithm",
    "key_id",
    "public_key_base64",
    "signed_payload_sha256",
    "signed_payload_format",
    "value_base64",
)


class BridgeJournalError(ValueError):
    """Raised when append/update requests violate durable journal contracts."""

    def __init__(self, *codes: str):
        self.codes = tuple(sorted(set(codes))) or ("journal_rejected",)
        super().__init__("bridge journal rejected: " + ", ".join(self.codes))


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        return None


def _public_key(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _entry_payload(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in entry.items()
        if key not in {"entry_sha256", "entry_payload_sha256", "signature"}
    }


def _checkpoint_payload(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in checkpoint.items()
        if key not in {"checkpoint_sha256", "checkpoint_payload_sha256", "signature"}
    }


def _signed_envelope(
    *,
    payload: Mapping[str, Any],
    private_key: Ed25519PrivateKey,
    signing_key_id: str,
) -> tuple[str, dict[str, Any]]:
    payload_sha256 = canonical_document_sha256(payload)
    public = _public_key(private_key)
    signature = base64.b64encode(private_key.sign(bytes.fromhex(payload_sha256))).decode("ascii")
    return payload_sha256, {
        "algorithm": "ed25519",
        "key_id": signing_key_id,
        "public_key_base64": base64.b64encode(public).decode("ascii"),
        "signed_payload_sha256": payload_sha256,
        "signed_payload_format": "sha256_digest_bytes",
        "value_base64": signature,
    }


def _journal_chain_sha(entries: Sequence[Mapping[str, Any]], *, head_sequence: int) -> str:
    rows: list[str] = []
    for entry in entries:
        sequence = entry.get("sequence")
        if isinstance(sequence, int) and 0 <= sequence <= head_sequence:
            rows.append(str(entry.get("entry_sha256", "")))
    return canonical_document_sha256({"head_sequence": head_sequence, "entry_sha256s": rows})


def append_bridge_journal_event(
    entries: Sequence[Mapping[str, Any]],
    *,
    journal_id: str,
    state: str,
    idempotency_key: str,
    event_body: Mapping[str, Any],
    occurred_at: str,
    private_key: Ed25519PrivateKey,
    signing_key_id: str,
    checkpoints: Sequence[Mapping[str, Any]] = (),
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any], bool]:
    """Append one signed event or replay an existing idempotent event."""
    if state not in JOURNAL_STATES:
        raise BridgeJournalError("unknown_state")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise BridgeJournalError("idempotency_key_invalid")
    if _utc(occurred_at) is None:
        raise BridgeJournalError("occurred_at_invalid")

    body_sha = canonical_document_sha256(event_body)
    normalized = tuple(dict(row) for row in entries)
    by_key: MutableMapping[str, Mapping[str, Any]] = {}
    for entry in normalized:
        key = entry.get("idempotency_key")
        if not isinstance(key, str):
            continue
        prior = by_key.get(key)
        if prior is None:
            by_key[key] = entry
            continue
        if prior.get("event_body_sha256") != entry.get("event_body_sha256"):
            raise BridgeJournalError("same_key_different_body")

    prior = by_key.get(idempotency_key)
    if prior is not None:
        if prior.get("event_body_sha256") != body_sha:
            raise BridgeJournalError("same_key_different_body")
        return normalized, dict(prior), True

    last = normalized[-1] if normalized else None
    if last is not None:
        prior_state = last.get("state")
        if not isinstance(prior_state, str) or state not in ALLOWED_TRANSITIONS.get(
            prior_state, frozenset()
        ):
            raise BridgeJournalError("illegal_transition")
        previous_entry_sha256 = last.get("entry_sha256")
        if not isinstance(previous_entry_sha256, str):
            raise BridgeJournalError("journal_corrupt")
        sequence = int(last.get("sequence", -1)) + 1
    else:
        if state != "admit":
            raise BridgeJournalError("illegal_transition")
        previous_entry_sha256 = None
        sequence = 0

    latest_checkpoint_sha = None
    latest_checkpoint_seq = -1
    for checkpoint in checkpoints:
        sequence_value = checkpoint.get("head_sequence")
        sha = checkpoint.get("checkpoint_sha256")
        if (
            isinstance(sequence_value, int)
            and isinstance(sha, str)
            and sequence_value >= latest_checkpoint_seq
        ):
            latest_checkpoint_seq = sequence_value
            latest_checkpoint_sha = sha

    payload = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_bridge_journal_entry",
        "journal_id": journal_id,
        "sequence": sequence,
        "state": state,
        "occurred_at": occurred_at,
        "idempotency_key": idempotency_key,
        "event_body_sha256": body_sha,
        "event_body": dict(event_body),
        "previous_entry_sha256": previous_entry_sha256,
        "checkpoint_sha256": latest_checkpoint_sha,
    }
    payload_sha, signature = _signed_envelope(
        payload=payload, private_key=private_key, signing_key_id=signing_key_id
    )
    entry = {
        **payload,
        "entry_payload_sha256": payload_sha,
        "signature": signature,
        "entry_sha256": "",
    }
    entry["entry_sha256"] = canonical_document_sha256(
        entry, excluded_top_level_fields=("entry_sha256",)
    )
    return (*normalized, entry), entry, False


def checkpoint_bridge_journal(
    entries: Sequence[Mapping[str, Any]],
    *,
    journal_id: str,
    checkpoint_id: str,
    created_at: str,
    private_key: Ed25519PrivateKey,
    signing_key_id: str,
    previous_checkpoint_sha256: str | None = None,
) -> dict[str, Any]:
    """Create one signed checkpoint over the current append-only journal head."""
    if _utc(created_at) is None:
        raise BridgeJournalError("checkpoint_created_at_invalid")
    head_sequence = max((int(entry.get("sequence", -1)) for entry in entries), default=-1)
    head_entry_sha256 = ""
    for entry in entries:
        if entry.get("sequence") == head_sequence:
            head_entry_sha256 = str(entry.get("entry_sha256", ""))
    payload = {
        "schema_version": "1.0.0",
        "record_type": "maskfactory_bridge_journal_checkpoint",
        "journal_id": journal_id,
        "checkpoint_id": checkpoint_id,
        "created_at": created_at,
        "head_sequence": head_sequence,
        "head_entry_sha256": head_entry_sha256,
        "entry_count": head_sequence + 1 if head_sequence >= 0 else 0,
        "journal_chain_sha256": _journal_chain_sha(entries, head_sequence=head_sequence),
        "previous_checkpoint_sha256": previous_checkpoint_sha256,
    }
    payload_sha, signature = _signed_envelope(
        payload=payload, private_key=private_key, signing_key_id=signing_key_id
    )
    checkpoint = {
        **payload,
        "checkpoint_payload_sha256": payload_sha,
        "signature": signature,
        "checkpoint_sha256": "",
    }
    checkpoint["checkpoint_sha256"] = canonical_document_sha256(
        checkpoint, excluded_top_level_fields=("checkpoint_sha256",)
    )
    return checkpoint


def _validate_signature(
    *,
    signature: Mapping[str, Any],
    signed_payload_sha256: str,
    trusted_signing_keys: Mapping[str, Mapping[str, Any]],
    at_time: str | None,
) -> list[str]:
    issues: list[str] = []
    if set(signature) != set(_SIGNATURE_FIELDS):
        return ["signature_shape"]
    key_id = signature.get("key_id")
    trusted = trusted_signing_keys.get(key_id) if isinstance(key_id, str) else None
    if not isinstance(trusted, Mapping):
        return ["signing_key_untrusted"]
    try:
        public = base64.b64decode(str(signature.get("public_key_base64")), validate=True)
        value = base64.b64decode(str(signature.get("value_base64")), validate=True)
    except (ValueError, TypeError, binascii.Error):
        return ["signature_encoding"]
    if trusted.get("public_key_sha256") != hashlib.sha256(public).hexdigest():
        issues.append("signing_key_substituted")
    if trusted.get("status") != "active":
        issues.append("signing_key_inactive")
    if "producer_journal" not in set(trusted.get("roles") or ()):
        issues.append("signing_key_wrong_role")
    if signature.get("signed_payload_sha256") != signed_payload_sha256:
        issues.append("signature_binding")
    if at_time is not None:
        observed = _utc(at_time)
        valid_from = _utc(trusted.get("valid_from"))
        valid_until = _utc(trusted.get("valid_until"))
        if (
            observed is None
            or valid_from is None
            or valid_until is None
            or not (valid_from <= observed < valid_until)
        ):
            issues.append("signing_key_validity")
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(
            value, bytes.fromhex(signed_payload_sha256)
        )
    except (ValueError, TypeError, InvalidSignature):
        issues.append("signature_verification")
    return issues


def validate_bridge_journal_history(
    entries: Sequence[Mapping[str, Any]],
    *,
    checkpoints: Sequence[Mapping[str, Any]] = (),
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[str, ...]:
    """Validate append-only order, signatures, idempotency, transitions, and checkpoints."""
    issues: list[str] = []
    trusted = trusted_signing_keys if isinstance(trusted_signing_keys, Mapping) else {}
    ordered = [dict(row) for row in entries if isinstance(row, Mapping)]
    if len(ordered) != len(entries):
        issues.append("entry_shape")

    sequence_rows: dict[int, dict[str, Any]] = {}
    seen_sequence: set[int] = set()
    provided_sequences: list[int] = []
    previous_state: str | None = None
    previous_sha: str | None = None
    idempotency_fingerprints: dict[str, str] = {}
    idempotency_first_sha: dict[str, str] = {}
    for index, entry in enumerate(ordered):
        sequence = entry.get("sequence")
        if not isinstance(sequence, int) or sequence < 0:
            issues.append("sequence_invalid")
            continue
        provided_sequences.append(sequence)
        if sequence in seen_sequence:
            prior = sequence_rows[sequence]
            if prior.get("entry_sha256") != entry.get("entry_sha256"):
                issues.append("journal_fork_detected")
            continue
        seen_sequence.add(sequence)
        sequence_rows[sequence] = entry
        if sequence != index:
            issues.append("journal_reorder_detected")

        payload = _entry_payload(entry)
        payload_sha = canonical_document_sha256(payload)
        if entry.get("entry_payload_sha256") != payload_sha:
            issues.append("entry_payload_hash_drift")
        expected_entry_sha = canonical_document_sha256(
            entry, excluded_top_level_fields=("entry_sha256",)
        )
        if entry.get("entry_sha256") != expected_entry_sha:
            issues.append("entry_hash_drift")

        signature = entry.get("signature")
        if not isinstance(signature, Mapping):
            issues.append("signature_missing")
        else:
            issues.extend(
                _validate_signature(
                    signature=signature,
                    signed_payload_sha256=payload_sha,
                    trusted_signing_keys=trusted,
                    at_time=(
                        entry.get("occurred_at")
                        if isinstance(entry.get("occurred_at"), str)
                        else None
                    ),
                )
            )

        state = entry.get("state")
        if state not in JOURNAL_STATES:
            issues.append("state_unknown")
        if previous_state is not None:
            if not isinstance(state, str) or state not in ALLOWED_TRANSITIONS.get(
                previous_state, frozenset()
            ):
                issues.append("illegal_transition")
        elif state != "admit":
            issues.append("illegal_transition")
        previous_state = state if isinstance(state, str) else previous_state

        if entry.get("previous_entry_sha256") != previous_sha:
            issues.append("journal_fork_detected")
        current_sha = entry.get("entry_sha256")
        previous_sha = current_sha if isinstance(current_sha, str) else previous_sha

        key = entry.get("idempotency_key")
        body_sha = entry.get("event_body_sha256")
        if isinstance(key, str) and isinstance(body_sha, str):
            prior = idempotency_fingerprints.get(key)
            if prior is None:
                idempotency_fingerprints[key] = body_sha
                if isinstance(current_sha, str):
                    idempotency_first_sha[key] = current_sha
            elif prior != body_sha:
                issues.append("same_key_different_body")
            elif isinstance(current_sha, str) and idempotency_first_sha.get(key) != current_sha:
                issues.append("idempotency_replay_appended")
        else:
            issues.append("idempotency_shape")

    if provided_sequences:
        expected = list(range(max(provided_sequences) + 1))
        if sorted(set(provided_sequences)) != expected:
            issues.append("journal_delete_detected")

    ordered_checkpoints = [dict(row) for row in checkpoints if isinstance(row, Mapping)]
    previous_checkpoint_sha = None
    for index, checkpoint in enumerate(ordered_checkpoints):
        head_sequence = checkpoint.get("head_sequence")
        if not isinstance(head_sequence, int) or head_sequence < -1:
            issues.append("checkpoint_head_invalid")
            continue
        if index > 0 and (
            not isinstance(ordered_checkpoints[index - 1].get("head_sequence"), int)
            or head_sequence <= ordered_checkpoints[index - 1]["head_sequence"]
        ):
            issues.append("checkpoint_reorder_detected")
        if checkpoint.get("previous_checkpoint_sha256") != previous_checkpoint_sha:
            issues.append("checkpoint_fork_detected")
        payload = _checkpoint_payload(checkpoint)
        payload_sha = canonical_document_sha256(payload)
        if checkpoint.get("checkpoint_payload_sha256") != payload_sha:
            issues.append("checkpoint_payload_hash_drift")
        expected_checkpoint_sha = canonical_document_sha256(
            checkpoint, excluded_top_level_fields=("checkpoint_sha256",)
        )
        if checkpoint.get("checkpoint_sha256") != expected_checkpoint_sha:
            issues.append("checkpoint_hash_drift")
        signature = checkpoint.get("signature")
        if not isinstance(signature, Mapping):
            issues.append("checkpoint_signature_missing")
        else:
            issues.extend(
                _validate_signature(
                    signature=signature,
                    signed_payload_sha256=payload_sha,
                    trusted_signing_keys=trusted,
                    at_time=(
                        checkpoint.get("created_at")
                        if isinstance(checkpoint.get("created_at"), str)
                        else None
                    ),
                )
            )
        if head_sequence >= 0:
            head = sequence_rows.get(head_sequence)
            if head is None:
                issues.append("checkpoint_head_missing")
            elif head.get("entry_sha256") != checkpoint.get("head_entry_sha256"):
                issues.append("checkpoint_head_drift")
        if checkpoint.get("entry_count") != (head_sequence + 1 if head_sequence >= 0 else 0):
            issues.append("checkpoint_entry_count_drift")
        if checkpoint.get("journal_chain_sha256") != _journal_chain_sha(
            ordered, head_sequence=head_sequence
        ):
            issues.append("checkpoint_chain_drift")
        previous_checkpoint_sha = checkpoint.get("checkpoint_sha256")

    return tuple(sorted(set(issues)))


def _policy() -> dict[str, Any]:
    try:
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BridgeJournalError("journal_policy_unavailable") from exc
    if not isinstance(policy, Mapping) or policy.get("policy_id") != POLICY_ID:
        raise BridgeJournalError("journal_policy_unexpected")
    expected = canonical_document_sha256(policy, excluded_top_level_fields=("policy_sha256",))
    if policy.get("policy_sha256") != expected:
        raise BridgeJournalError("journal_policy_hash_mismatch")
    return dict(policy)


def _ordered_reasons(policy: Mapping[str, Any], reasons: set[str]) -> list[str]:
    codes = policy.get("rejection_reason_codes")
    catalog = [code for code in codes if isinstance(code, str)] if isinstance(codes, list) else []
    ordered = [code for code in catalog if code in reasons]
    leftovers = sorted(reason for reason in reasons if reason not in set(ordered))
    return [*ordered, *leftovers]


def reconstruct_bridge_journal_state(
    entries: Sequence[Mapping[str, Any]],
    *,
    checkpoints: Sequence[Mapping[str, Any]] = (),
    trusted_signing_keys: Mapping[str, Mapping[str, Any]] | None = None,
    decided_at: str,
    main_prerequisites_satisfied: Sequence[str] = (),
) -> dict[str, Any]:
    """Reconstruct exact durable head state from validated history after interruption.

    Producer-only: reconstructs in-memory closed state from signed entries/checkpoints.
    Does not persist Main retention, atomic side-effect commits, or key lifecycle.
    """
    policy = _policy()
    if _utc(decided_at) is None:
        raise BridgeJournalError("occurred_at_invalid")

    history_issues = validate_bridge_journal_history(
        entries,
        checkpoints=checkpoints,
        trusted_signing_keys=trusted_signing_keys,
    )
    required = list(policy.get("external_main_prerequisites") or EXTERNAL_MAIN_DEPENDENCIES)
    satisfied = [item for item in required if item in set(main_prerequisites_satisfied)]
    unmet = [item for item in required if item not in set(satisfied)]

    ordered = [dict(row) for row in entries if isinstance(row, Mapping)]
    ordered.sort(key=lambda row: int(row.get("sequence", -1)))
    head = ordered[-1] if ordered else None
    journal_id = ""
    if head is not None and isinstance(head.get("journal_id"), str):
        journal_id = head["journal_id"]
    elif ordered and isinstance(ordered[0].get("journal_id"), str):
        journal_id = ordered[0]["journal_id"]

    head_sequence = int(head["sequence"]) if head is not None else -1
    head_state = head.get("state") if head is not None else None
    head_entry_sha256 = head.get("entry_sha256") if head is not None else None
    journal_chain = _journal_chain_sha(ordered, head_sequence=head_sequence) if ordered else None

    latest_checkpoint_sha256 = None
    latest_checkpoint_head_sequence = None
    latest_seq = -2
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, Mapping):
            continue
        sequence_value = checkpoint.get("head_sequence")
        sha = checkpoint.get("checkpoint_sha256")
        if (
            isinstance(sequence_value, int)
            and isinstance(sha, str)
            and sequence_value >= latest_seq
        ):
            latest_seq = sequence_value
            latest_checkpoint_sha256 = sha
            latest_checkpoint_head_sequence = sequence_value

    idempotency_index: dict[str, str] = {}
    for entry in ordered:
        key = entry.get("idempotency_key")
        body_sha = entry.get("event_body_sha256")
        if isinstance(key, str) and isinstance(body_sha, str) and key not in idempotency_index:
            idempotency_index[key] = body_sha

    covered_states = []
    seen_states: set[str] = set()
    for entry in ordered:
        state = entry.get("state")
        if isinstance(state, str) and state not in seen_states:
            seen_states.add(state)
            covered_states.append(state)

    current_state = head_state if isinstance(head_state, str) else None
    allowed_next = sorted(ALLOWED_TRANSITIONS.get(current_state or "", frozenset()))
    reasons: set[str] = set()
    if history_issues:
        reasons.add("reconstruction_history_invalid")
        reasons.update(history_issues)
    if unmet:
        reasons.add("external_main_prerequisite_unmet")

    # Producer in-memory reconstruction can succeed while Main retention /
    # atomic-commit prerequisites remain unmet; those stay explicit on the evidence.
    status = "rejected" if history_issues else "reconstructed"
    rejection_reasons = _ordered_reasons(policy, reasons) if history_issues else []

    evidence = {
        "schema_version": "1.0.0",
        "record_type": "bridge_journal_reconstruction_evidence",
        "decided_at": decided_at,
        "policy_id": POLICY_ID,
        "policy_sha256": policy["policy_sha256"],
        "journal_id": journal_id or "unspecified",
        "status": status,
        "rejection_reasons": rejection_reasons,
        "head_state": current_state,
        "head_sequence": head_sequence,
        "head_entry_sha256": head_entry_sha256 if isinstance(head_entry_sha256, str) else None,
        "entry_count": len(ordered),
        "journal_chain_sha256": journal_chain,
        "latest_checkpoint_sha256": latest_checkpoint_sha256,
        "latest_checkpoint_head_sequence": latest_checkpoint_head_sequence,
        "idempotency_index": idempotency_index,
        "closed_state_machine": {
            "current_state": current_state,
            "terminal": current_state == "rollback",
            "allowed_next_states": allowed_next,
            "covered_states": covered_states,
        },
        "external_main_prerequisites": {
            "required": required,
            "satisfied": satisfied,
            "unmet": unmet,
        },
        "decision_sha256": "",
    }
    evidence["decision_sha256"] = canonical_document_sha256(
        evidence, excluded_top_level_fields=("decision_sha256",)
    )
    return evidence


def validate_bridge_journal_reconstruction_evidence(
    evidence: Mapping[str, Any],
) -> tuple[str, ...]:
    """Validate reconstruction evidence against the closed schema and policy seal."""
    issues: list[str] = []
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(dict(evidence))
    except Exception:
        issues.append("schema_invalid")
        return tuple(sorted(set(issues)))

    try:
        policy = _policy()
    except BridgeJournalError as exc:
        return tuple(sorted(set(exc.codes)))

    if evidence.get("policy_id") != POLICY_ID:
        issues.append("policy_id_mismatch")
    if evidence.get("policy_sha256") != policy.get("policy_sha256"):
        issues.append("policy_hash_mismatch")

    expected = canonical_document_sha256(evidence, excluded_top_level_fields=("decision_sha256",))
    if evidence.get("decision_sha256") != expected:
        issues.append("decision_hash_drift")

    machine = evidence.get("closed_state_machine")
    if isinstance(machine, Mapping):
        covered = machine.get("covered_states")
        if isinstance(covered, list):
            unknown = [state for state in covered if state not in JOURNAL_STATES]
            if unknown:
                issues.append("state_unknown")

    if evidence.get("status") == "reconstructed" and evidence.get("rejection_reasons"):
        issues.append("reconstructed_with_rejection_reasons")
    if evidence.get("status") == "rejected" and not evidence.get("rejection_reasons"):
        issues.append("rejected_without_reasons")

    return tuple(sorted(set(issues)))


__all__ = [
    "ALLOWED_TRANSITIONS",
    "BridgeJournalError",
    "EXTERNAL_MAIN_DEPENDENCIES",
    "JOURNAL_STATES",
    "POLICY_ID",
    "POLICY_PATH",
    "append_bridge_journal_event",
    "checkpoint_bridge_journal",
    "reconstruct_bridge_journal_state",
    "validate_bridge_journal_history",
    "validate_bridge_journal_reconstruction_evidence",
]
