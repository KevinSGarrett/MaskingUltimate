"""Minimal binary owner decisions over fully prepared review evidence."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


class BinaryReviewError(ValueError):
    """A binary review bundle or append-only decision is invalid."""


REVIEW_KINDS = ("human_anchor_seal", "autonomous_audit")
DECISIONS = ("approve", "reject")


def build_binary_review_bundle(document: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize a prepared bundle and bind its evidence with SHA-256."""
    bundle = dict(document)
    if "bundle_sha256" in bundle:
        raise BinaryReviewError("bundle input already has a bundle_sha256")
    _validate_bundle_fields(bundle)
    bundle["bundle_sha256"] = _canonical_sha256(bundle)
    return bundle


def load_binary_review_bundle(path: Path) -> dict[str, Any]:
    try:
        bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BinaryReviewError(f"review bundle is unreadable: {path}") from exc
    if not isinstance(bundle, dict):
        raise BinaryReviewError("review bundle must be an object")
    claimed = bundle.get("bundle_sha256")
    payload = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    _validate_bundle_fields(payload)
    if claimed != _canonical_sha256(payload):
        raise BinaryReviewError("review bundle hash does not match its contents")
    return bundle


def record_binary_review_decision(
    bundle_path: Path,
    *,
    decision: str,
    reviewer: str,
    ledger_path: Path,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Append one approve/reject result to a verified hash-chained ledger."""
    if decision not in DECISIONS:
        raise BinaryReviewError(f"decision must be one of {DECISIONS}")
    reviewer = reviewer.strip()
    if not reviewer:
        raise BinaryReviewError("reviewer is required")
    bundle = load_binary_review_bundle(bundle_path)
    existing = _load_ledger(Path(ledger_path))
    for row in existing:
        if row["bundle_sha256"] != bundle["bundle_sha256"]:
            continue
        if row["decision"] == decision and row["reviewer"] == reviewer:
            return row
        raise BinaryReviewError("a conflicting decision already exists for this evidence bundle")

    if decision == "approve":
        outcome = (
            "seal_human_anchor_gold"
            if bundle["review_kind"] == "human_anchor_seal"
            else "record_autonomous_audit_agreement"
        )
        route = "accepted"
        revoke_certificate = False
    else:
        outcome = "route_bounded_repair"
        route = "residual_repair_queue"
        revoke_certificate = bundle["review_kind"] == "autonomous_audit"
    timestamp = (recorded_at or datetime.now(UTC)).isoformat()
    previous_sha = existing[-1]["record_sha256"] if existing else None
    record = {
        "schema_version": "1.0.0",
        "decision_id": "decision_"
        + hashlib.sha256(f"{bundle['bundle_sha256']}\0{decision}\0{reviewer}".encode()).hexdigest()[
            :24
        ],
        "recorded_at": timestamp,
        "reviewer": reviewer,
        "review_kind": bundle["review_kind"],
        "image_id": bundle["image_id"],
        "package_id": bundle["package_id"],
        "bundle_sha256": bundle["bundle_sha256"],
        "evidence_sha256": bundle["evidence_sha256"],
        "final_mask_set_sha256": bundle["final_mask_set_sha256"],
        "decision": decision,
        "outcome": outcome,
        "route": route,
        "revoke_certificate": revoke_certificate,
        "certificate_ids": bundle["certificate_ids"],
        "previous_record_sha256": previous_sha,
    }
    record["record_sha256"] = _canonical_sha256(record)
    _write_ledger_atomic(Path(ledger_path), existing + [record])
    return record


def _validate_bundle_fields(bundle: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "review_kind",
        "image_id",
        "package_id",
        "truth_tier",
        "truth_partition",
        "source_sha256",
        "final_mask_set_sha256",
        "evidence_sha256",
        "certificate_ids",
        "qa",
    }
    if set(bundle) != required or bundle.get("schema_version") != "1.0.0":
        raise BinaryReviewError("review bundle has the wrong contract")
    if bundle.get("review_kind") not in REVIEW_KINDS:
        raise BinaryReviewError("review kind is invalid")
    for field in ("image_id", "package_id"):
        if not isinstance(bundle.get(field), str) or not bundle[field].strip():
            raise BinaryReviewError(f"review bundle {field} is missing")
    for field in ("source_sha256", "final_mask_set_sha256", "evidence_sha256"):
        value = bundle.get(field)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value.casefold())
        ):
            raise BinaryReviewError(f"review bundle {field} is not SHA-256")
    qa = bundle.get("qa")
    required_qa = {
        "status": "pass",
        "block_qc_ids": [],
        "format_passed": True,
        "identity_passed": True,
        "split_integrity_passed": True,
    }
    if qa != required_qa:
        raise BinaryReviewError("review bundle has unresolved QA or integrity failures")
    certificates = bundle.get("certificate_ids")
    if not isinstance(certificates, list) or not all(
        isinstance(value, str) and value for value in certificates
    ):
        raise BinaryReviewError("review bundle certificate IDs are invalid")
    if bundle["review_kind"] == "human_anchor_seal":
        if bundle.get("truth_tier") != "human_anchor_gold" or certificates:
            raise BinaryReviewError("human-anchor seal has incompatible truth authority")
        if bundle.get("truth_partition") not in {"train", "calibration", "holdout"}:
            raise BinaryReviewError("human-anchor seal has an invalid partition")
    elif (
        bundle.get("truth_tier") != "autonomous_certified_gold"
        or bundle.get("truth_partition") != "train"
        or not certificates
    ):
        raise BinaryReviewError("autonomous audit lacks train-only certificate authority")


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    previous = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BinaryReviewError(f"decision ledger line {line_number} is invalid") from exc
        if not isinstance(row, dict):
            raise BinaryReviewError(f"decision ledger line {line_number} is not an object")
        claimed = row.get("record_sha256")
        payload = {key: value for key, value in row.items() if key != "record_sha256"}
        if claimed != _canonical_sha256(payload) or row.get("previous_record_sha256") != previous:
            raise BinaryReviewError(f"decision ledger chain failed at line {line_number}")
        previous = claimed
        rows.append(row)
    return rows


def _write_ledger_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in records),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "BinaryReviewError",
    "build_binary_review_bundle",
    "load_binary_review_bundle",
    "record_binary_review_decision",
]
