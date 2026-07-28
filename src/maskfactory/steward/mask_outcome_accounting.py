"""Immutable terminal accounting for governed mask campaign records."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "maskfactory.mask-outcome-accounting.v1"
ZERO_SHA256 = "0" * 64
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TERMINAL_OUTCOMES = ("accept", "repair", "abstain", "reject", "quarantine")
PASSING_HARD_QA = frozenset({"PASS", "PASS_AFTER_REPAIR"})
AUTHORITY_LIMITATIONS = (
    "codex_final_adoption_required",
    "codex_tracker_authority_retained",
    "no_gold_authority",
    "no_training_truth_authority",
    "no_automatic_promotion",
)


class MaskOutcomeAccountingError(ValueError):
    """A terminal mask record or campaign failed closed."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    sealed = dict(value)
    sealed[field] = ZERO_SHA256
    sealed[field] = _sha256(sealed)
    return sealed


def _verify_self_hash(
    value: Mapping[str, Any],
    *,
    field: str,
    subject: str,
) -> None:
    actual = value.get(field)
    if not isinstance(actual, str) or SHA256_RE.fullmatch(actual) is None:
        raise MaskOutcomeAccountingError(f"{subject} has invalid {field}")
    candidate = dict(value)
    candidate[field] = ZERO_SHA256
    if _sha256(candidate) != actual:
        raise MaskOutcomeAccountingError(f"{subject} self-hash mismatch")


def _digest(value: object, *, field: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise MaskOutcomeAccountingError(f"{field} must be lowercase SHA-256")
    return value


def _identifier(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 160
        or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
            for character in value
        )
    ):
        raise MaskOutcomeAccountingError(f"{field} is invalid")
    return value


def _validate_terminal_fields(
    record: Mapping[str, Any],
    *,
    verify_hash: bool,
) -> None:
    expected_fields = {
        "schema_version",
        "record_id",
        "input_sha256",
        "parent_mask_sha256",
        "final_mask_sha256",
        "hard_qa_result_sha256",
        "hard_qa_outcome",
        "visual_quorum_sha256",
        "visual_outcome",
        "repair_result_sha256s",
        "terminal_outcome",
        "reason_code",
        "authority_claimed",
        "promotion_claimed",
        "terminal_record_sha256",
    }
    if not isinstance(record, Mapping) or set(record) != expected_fields:
        raise MaskOutcomeAccountingError("terminal record field set mismatch")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise MaskOutcomeAccountingError("terminal record schema mismatch")
    _identifier(record.get("record_id"), field="record_id")
    for field in ("input_sha256", "parent_mask_sha256", "hard_qa_result_sha256"):
        _digest(record.get(field), field=field)
    final_mask_sha256 = _digest(
        record.get("final_mask_sha256"),
        field="final_mask_sha256",
        nullable=True,
    )
    visual_quorum_sha256 = _digest(
        record.get("visual_quorum_sha256"),
        field="visual_quorum_sha256",
        nullable=True,
    )
    visual_outcome = record.get("visual_outcome")
    if (visual_quorum_sha256 is None) != (visual_outcome is None):
        raise MaskOutcomeAccountingError(
            "visual outcome and quorum digest must be jointly present or absent"
        )
    if visual_outcome is not None:
        _identifier(visual_outcome, field="visual_outcome")
    repairs = record.get("repair_result_sha256s")
    if (
        not isinstance(repairs, Sequence)
        or isinstance(repairs, (str, bytes))
        or any(_digest(value, field="repair_result_sha256") is None for value in repairs)
        or len(set(repairs)) != len(repairs)
    ):
        raise MaskOutcomeAccountingError("repair result digests must be unique SHA-256s")
    hard_qa_outcome = _identifier(
        record.get("hard_qa_outcome"),
        field="hard_qa_outcome",
    )
    terminal_outcome = record.get("terminal_outcome")
    if terminal_outcome not in TERMINAL_OUTCOMES:
        raise MaskOutcomeAccountingError("terminal outcome is invalid")
    _identifier(record.get("reason_code"), field="reason_code")
    if record.get("authority_claimed") is not False:
        raise MaskOutcomeAccountingError("terminal record may not claim authority")
    if record.get("promotion_claimed") is not False:
        raise MaskOutcomeAccountingError("terminal record may not claim promotion")

    if terminal_outcome == "accept":
        if (
            final_mask_sha256 is None
            or hard_qa_outcome not in PASSING_HARD_QA
            or visual_outcome != "VISUAL_QA_PASS_BOUNDED"
        ):
            raise MaskOutcomeAccountingError(
                "accept requires passing hard QA, visual quorum, and final candidate"
            )
    elif terminal_outcome == "repair":
        if (
            final_mask_sha256 is None
            or not repairs
            or final_mask_sha256 == record["parent_mask_sha256"]
        ):
            raise MaskOutcomeAccountingError(
                "repair requires distinct parent/final masks and repair evidence"
            )
    elif terminal_outcome == "reject":
        if (
            hard_qa_outcome in PASSING_HARD_QA
            and visual_outcome != "REJECT_VISUAL"
        ):
            raise MaskOutcomeAccountingError(
                "reject requires deterministic or visual rejection evidence"
            )
    if verify_hash:
        _verify_self_hash(
            record,
            field="terminal_record_sha256",
            subject="terminal mask record",
        )


def build_terminal_mask_record(
    *,
    record_id: str,
    input_sha256: str,
    parent_mask_sha256: str,
    final_mask_sha256: str | None,
    hard_qa_result_sha256: str,
    hard_qa_outcome: str,
    visual_quorum_sha256: str | None,
    visual_outcome: str | None,
    repair_result_sha256s: Sequence[str],
    terminal_outcome: str,
    reason_code: str,
    authority_claimed: bool = False,
    promotion_claimed: bool = False,
) -> dict[str, Any]:
    """Seal one terminal record after validating its evidence relationships."""

    record = {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id,
        "input_sha256": input_sha256,
        "parent_mask_sha256": parent_mask_sha256,
        "final_mask_sha256": final_mask_sha256,
        "hard_qa_result_sha256": hard_qa_result_sha256,
        "hard_qa_outcome": hard_qa_outcome,
        "visual_quorum_sha256": visual_quorum_sha256,
        "visual_outcome": visual_outcome,
        "repair_result_sha256s": list(repair_result_sha256s),
        "terminal_outcome": terminal_outcome,
        "reason_code": reason_code,
        "authority_claimed": authority_claimed,
        "promotion_claimed": promotion_claimed,
        "terminal_record_sha256": ZERO_SHA256,
    }
    _validate_terminal_fields(record, verify_hash=False)
    return _seal(record, "terminal_record_sha256")


def validate_terminal_mask_record(record: Mapping[str, Any]) -> None:
    _validate_terminal_fields(record, verify_hash=True)


def _normalize_inputs(
    inputs: Sequence[Mapping[str, Any]],
    *,
    expected_record_count: int,
) -> list[dict[str, str]]:
    if (
        not isinstance(expected_record_count, int)
        or isinstance(expected_record_count, bool)
        or expected_record_count <= 0
    ):
        raise MaskOutcomeAccountingError("expected_record_count must be positive")
    if not isinstance(inputs, Sequence) or isinstance(inputs, (str, bytes)):
        raise MaskOutcomeAccountingError("campaign inputs must be a sequence")
    if len(inputs) != expected_record_count:
        raise MaskOutcomeAccountingError("campaign input count mismatch")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in inputs:
        if not isinstance(value, Mapping) or set(value) != {
            "record_id",
            "input_sha256",
        }:
            raise MaskOutcomeAccountingError("campaign input field set mismatch")
        record_id = _identifier(value.get("record_id"), field="record_id")
        if record_id in seen:
            raise MaskOutcomeAccountingError("campaign input record IDs must be unique")
        seen.add(record_id)
        normalized.append(
            {
                "record_id": record_id,
                "input_sha256": _digest(
                    value.get("input_sha256"),
                    field="input_sha256",
                ),
            }
        )
    return normalized


def reconcile_mask_outcome_campaign(
    *,
    campaign_id: str,
    inputs: Sequence[Mapping[str, Any]],
    terminal_records: Sequence[Mapping[str, Any]],
    expected_record_count: int = 100,
) -> dict[str, Any]:
    """Prove exactly one terminal, non-promoting outcome for every input."""

    campaign = _identifier(campaign_id, field="campaign_id")
    normalized_inputs = _normalize_inputs(
        inputs,
        expected_record_count=expected_record_count,
    )
    if (
        not isinstance(terminal_records, Sequence)
        or isinstance(terminal_records, (str, bytes))
        or len(terminal_records) != expected_record_count
    ):
        raise MaskOutcomeAccountingError("terminal record count mismatch")
    by_id: dict[str, dict[str, Any]] = {}
    terminal_hashes: set[str] = set()
    for raw in terminal_records:
        validate_terminal_mask_record(raw)
        record = dict(raw)
        record_id = record["record_id"]
        if record_id in by_id:
            raise MaskOutcomeAccountingError("duplicate terminal record")
        if record["terminal_record_sha256"] in terminal_hashes:
            raise MaskOutcomeAccountingError("duplicate terminal evidence")
        by_id[record_id] = record
        terminal_hashes.add(record["terminal_record_sha256"])

    ordered_records: list[dict[str, Any]] = []
    for item in normalized_inputs:
        record = by_id.pop(item["record_id"], None)
        if record is None:
            raise MaskOutcomeAccountingError("campaign input lacks terminal outcome")
        if record["input_sha256"] != item["input_sha256"]:
            raise MaskOutcomeAccountingError("terminal record input binding mismatch")
        ordered_records.append(record)
    if by_id:
        raise MaskOutcomeAccountingError("terminal record has no campaign input")

    counts = Counter(record["terminal_outcome"] for record in ordered_records)
    outcome_counts = {
        outcome: counts.get(outcome, 0) for outcome in TERMINAL_OUTCOMES
    }
    return _seal(
        {
            "schema_version": SCHEMA_VERSION,
            "campaign_id": campaign,
            "expected_record_count": expected_record_count,
            "input_count": len(normalized_inputs),
            "terminal_record_count": len(ordered_records),
            "inputs": normalized_inputs,
            "terminal_record_sha256s": [
                record["terminal_record_sha256"] for record in ordered_records
            ],
            "outcome_counts": outcome_counts,
            "zero_loss": len(ordered_records) == len(normalized_inputs),
            "zero_duplicate_promotion": all(
                record["promotion_claimed"] is False for record in ordered_records
            ),
            "complete_accounting": len(ordered_records) == expected_record_count,
            "authority_granted": False,
            "authority_limitations": list(AUTHORITY_LIMITATIONS),
            "campaign_sha256": ZERO_SHA256,
        },
        "campaign_sha256",
    )


def validate_mask_outcome_campaign(
    result: Mapping[str, Any],
    *,
    inputs: Sequence[Mapping[str, Any]],
    terminal_records: Sequence[Mapping[str, Any]],
) -> None:
    """Reject rehashed campaign drift by deterministic reconciliation."""

    if not isinstance(result, Mapping):
        raise MaskOutcomeAccountingError("campaign result must be an object")
    _verify_self_hash(result, field="campaign_sha256", subject="mask outcome campaign")
    expected = reconcile_mask_outcome_campaign(
        campaign_id=result.get("campaign_id"),
        inputs=inputs,
        terminal_records=terminal_records,
        expected_record_count=result.get("expected_record_count"),
    )
    if dict(result) != expected:
        raise MaskOutcomeAccountingError("mask outcome campaign replay mismatch")


__all__ = [
    "AUTHORITY_LIMITATIONS",
    "MaskOutcomeAccountingError",
    "SCHEMA_VERSION",
    "TERMINAL_OUTCOMES",
    "build_terminal_mask_record",
    "reconcile_mask_outcome_campaign",
    "validate_mask_outcome_campaign",
    "validate_terminal_mask_record",
]
