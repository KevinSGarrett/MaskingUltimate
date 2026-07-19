from __future__ import annotations

import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maskfactory.bridge.journal import (
    JOURNAL_STATES,
    BridgeJournalError,
    append_bridge_journal_event,
    checkpoint_bridge_journal,
    reconstruct_bridge_journal_state,
    validate_bridge_journal_history,
    validate_bridge_journal_reconstruction_evidence,
)


def _trusted(private_key: Ed25519PrivateKey) -> tuple[str, dict[str, dict[str, object]]]:
    key_id = "mf-producer-journal-test"
    public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return key_id, {
        key_id: {
            "public_key_sha256": hashlib.sha256(public).hexdigest(),
            "roles": ["producer_journal"],
            "status": "active",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
        }
    }


def _journal(private_key: Ed25519PrivateKey, key_id: str) -> tuple[dict[str, object], ...]:
    entries: tuple[dict[str, object], ...] = ()
    entries, _, _ = append_bridge_journal_event(
        entries,
        journal_id="bridge-journal-v1",
        state="admit",
        idempotency_key="idem-admit-001",
        event_body={"phase": "admit"},
        occurred_at="2026-07-19T12:00:00Z",
        private_key=private_key,
        signing_key_id=key_id,
    )
    entries, _, _ = append_bridge_journal_event(
        entries,
        journal_id="bridge-journal-v1",
        state="route",
        idempotency_key="idem-route-001",
        event_body={"phase": "route"},
        occurred_at="2026-07-19T12:00:01Z",
        private_key=private_key,
        signing_key_id=key_id,
    )
    entries, _, _ = append_bridge_journal_event(
        entries,
        journal_id="bridge-journal-v1",
        state="submit",
        idempotency_key="idem-submit-001",
        event_body={"phase": "submit"},
        occurred_at="2026-07-19T12:00:02Z",
        private_key=private_key,
        signing_key_id=key_id,
    )
    return entries


def test_replay_is_idempotent_and_same_key_different_body_is_rejected() -> None:
    private_key = Ed25519PrivateKey.generate()
    key_id, _trusted_keys = _trusted(private_key)
    entries: tuple[dict[str, object], ...] = ()
    entries, original, replay = append_bridge_journal_event(
        entries,
        journal_id="bridge-journal-v1",
        state="admit",
        idempotency_key="idem-admit-001",
        event_body={"phase": "admit", "request": "same"},
        occurred_at="2026-07-19T12:00:00Z",
        private_key=private_key,
        signing_key_id=key_id,
    )
    assert replay is False
    entries_after, replayed, replay = append_bridge_journal_event(
        entries,
        journal_id="bridge-journal-v1",
        state="admit",
        idempotency_key="idem-admit-001",
        event_body={"phase": "admit", "request": "same"},
        occurred_at="2026-07-19T12:00:00Z",
        private_key=private_key,
        signing_key_id=key_id,
    )
    assert replay is True
    assert entries_after == entries
    assert replayed["entry_sha256"] == original["entry_sha256"]

    with pytest.raises(BridgeJournalError) as caught:
        append_bridge_journal_event(
            entries,
            journal_id="bridge-journal-v1",
            state="admit",
            idempotency_key="idem-admit-001",
            event_body={"phase": "admit", "request": "different"},
            occurred_at="2026-07-19T12:00:03Z",
            private_key=private_key,
            signing_key_id=key_id,
        )
    assert "same_key_different_body" in caught.value.codes


def test_illegal_transition_is_rejected() -> None:
    private_key = Ed25519PrivateKey.generate()
    key_id, _trusted_keys = _trusted(private_key)
    entries: tuple[dict[str, object], ...] = ()
    entries, _, _ = append_bridge_journal_event(
        entries,
        journal_id="bridge-journal-v1",
        state="admit",
        idempotency_key="idem-admit-001",
        event_body={"phase": "admit"},
        occurred_at="2026-07-19T12:00:00Z",
        private_key=private_key,
        signing_key_id=key_id,
    )
    with pytest.raises(BridgeJournalError) as caught:
        append_bridge_journal_event(
            entries,
            journal_id="bridge-journal-v1",
            state="result",
            idempotency_key="idem-result-001",
            event_body={"phase": "result"},
            occurred_at="2026-07-19T12:00:04Z",
            private_key=private_key,
            signing_key_id=key_id,
        )
    assert "illegal_transition" in caught.value.codes


def test_signed_checkpointed_history_is_valid() -> None:
    private_key = Ed25519PrivateKey.generate()
    key_id, trusted_keys = _trusted(private_key)
    entries = _journal(private_key, key_id)
    checkpoint = checkpoint_bridge_journal(
        entries,
        journal_id="bridge-journal-v1",
        checkpoint_id="ckpt-001",
        created_at="2026-07-19T12:01:00Z",
        private_key=private_key,
        signing_key_id=key_id,
    )
    assert (
        validate_bridge_journal_history(
            entries, checkpoints=(checkpoint,), trusted_signing_keys=trusted_keys
        )
        == ()
    )


def test_fork_delete_and_reorder_are_detected() -> None:
    private_key = Ed25519PrivateKey.generate()
    key_id, trusted_keys = _trusted(private_key)
    entries = _journal(private_key, key_id)
    checkpoint = checkpoint_bridge_journal(
        entries,
        journal_id="bridge-journal-v1",
        checkpoint_id="ckpt-001",
        created_at="2026-07-19T12:01:00Z",
        private_key=private_key,
        signing_key_id=key_id,
    )

    deleted = (entries[0], entries[2])
    delete_codes = set(
        validate_bridge_journal_history(
            deleted, checkpoints=(checkpoint,), trusted_signing_keys=trusted_keys
        )
    )
    assert "journal_delete_detected" in delete_codes

    reordered = (entries[1], entries[0], entries[2])
    reorder_codes = set(
        validate_bridge_journal_history(
            reordered, checkpoints=(checkpoint,), trusted_signing_keys=trusted_keys
        )
    )
    assert "journal_reorder_detected" in reorder_codes

    forked_entry = dict(entries[2])
    forked_entry["previous_entry_sha256"] = entries[0]["entry_sha256"]
    fork_codes = set(
        validate_bridge_journal_history(
            (entries[0], entries[1], forked_entry),
            checkpoints=(checkpoint,),
            trusted_signing_keys=trusted_keys,
        )
    )
    assert "journal_fork_detected" in fork_codes


def _append(
    entries: tuple[dict[str, object], ...],
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    state: str,
    key: str,
    seconds: int,
    checkpoints: tuple[dict[str, object], ...] = (),
) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    updated, entry, _ = append_bridge_journal_event(
        entries,
        journal_id="bridge-journal-v1",
        state=state,
        idempotency_key=key,
        event_body={"phase": state},
        occurred_at=f"2026-07-19T12:00:{seconds:02d}Z",
        private_key=private_key,
        signing_key_id=key_id,
        checkpoints=checkpoints,
    )
    return updated, entry


def test_closed_state_machine_covers_full_verify_vocabulary() -> None:
    required = {
        "admit",
        "route",
        "lease",
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
    }
    assert required.issubset(set(JOURNAL_STATES))
    assert "submit" in JOURNAL_STATES  # legacy/generic submit retained

    private_key = Ed25519PrivateKey.generate()
    key_id, trusted_keys = _trusted(private_key)
    entries: tuple[dict[str, object], ...] = ()
    path = (
        "admit",
        "route",
        "lease",
        "submit_known",
        "reconcile",
        "result",
        "validate",
        "cache",
        "decision",
        "feedback",
        "adoption",
        "invalidation",
        "recovery",
        "rollback",
    )
    for index, state in enumerate(path):
        entries, _ = _append(
            entries,
            private_key=private_key,
            key_id=key_id,
            state=state,
            key=f"idem-{state}-001",
            seconds=index,
        )
    assert validate_bridge_journal_history(entries, trusted_signing_keys=trusted_keys) == ()

    # submit_unknown must reconcile before retry; direct retry is illegal.
    unknown_path: tuple[dict[str, object], ...] = ()
    for index, state in enumerate(("admit", "route", "submit_unknown")):
        unknown_path, _ = _append(
            unknown_path,
            private_key=private_key,
            key_id=key_id,
            state=state,
            key=f"idem-unknown-{state}-001",
            seconds=index,
        )
    with pytest.raises(BridgeJournalError) as caught:
        _append(
            unknown_path,
            private_key=private_key,
            key_id=key_id,
            state="retry",
            key="idem-unknown-retry-001",
            seconds=3,
        )
    assert "illegal_transition" in caught.value.codes

    # repair is a first-class retry sibling after result.
    repair_path: tuple[dict[str, object], ...] = ()
    for index, state in enumerate(("admit", "route", "submit", "reconcile", "result", "repair")):
        repair_path, _ = _append(
            repair_path,
            private_key=private_key,
            key_id=key_id,
            state=state,
            key=f"idem-repair-{state}-001",
            seconds=index,
        )
    assert validate_bridge_journal_history(repair_path, trusted_signing_keys=trusted_keys) == ()


def test_interruption_reconstructs_exact_state() -> None:
    private_key = Ed25519PrivateKey.generate()
    key_id, trusted_keys = _trusted(private_key)
    entries = _journal(private_key, key_id)
    checkpoint = checkpoint_bridge_journal(
        entries,
        journal_id="bridge-journal-v1",
        checkpoint_id="ckpt-001",
        created_at="2026-07-19T12:01:00Z",
        private_key=private_key,
        signing_key_id=key_id,
    )
    # Continue after checkpoint through decision, then interrupt.
    for index, state in enumerate(("reconcile", "result", "decision"), start=3):
        entries, head = _append(
            entries,
            private_key=private_key,
            key_id=key_id,
            state=state,
            key=f"idem-{state}-001",
            seconds=index,
            checkpoints=(checkpoint,),
        )

    evidence = reconstruct_bridge_journal_state(
        entries,
        checkpoints=(checkpoint,),
        trusted_signing_keys=trusted_keys,
        decided_at="2026-07-19T12:02:00Z",
    )
    assert evidence["status"] == "reconstructed"
    assert evidence["head_state"] == "decision"
    assert evidence["head_sequence"] == head["sequence"]
    assert evidence["head_entry_sha256"] == head["entry_sha256"]
    assert evidence["entry_count"] == len(entries)
    assert evidence["latest_checkpoint_sha256"] == checkpoint["checkpoint_sha256"]
    assert evidence["idempotency_index"]["idem-admit-001"]
    assert evidence["closed_state_machine"]["current_state"] == "decision"
    assert "feedback" in evidence["closed_state_machine"]["allowed_next_states"]
    assert evidence["external_main_prerequisites"]["unmet"]
    assert validate_bridge_journal_reconstruction_evidence(evidence) == ()

    # Corrupted history cannot reconstruct.
    deleted = (entries[0], entries[2])
    rejected = reconstruct_bridge_journal_state(
        deleted,
        checkpoints=(checkpoint,),
        trusted_signing_keys=trusted_keys,
        decided_at="2026-07-19T12:02:00Z",
    )
    assert rejected["status"] == "rejected"
    assert "reconstruction_history_invalid" in rejected["rejection_reasons"]
    assert validate_bridge_journal_reconstruction_evidence(rejected) == ()
