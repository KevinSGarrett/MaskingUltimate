"""Resumable per-record terminal qualification for adult-corpus batches."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .nude_record_qualification import (
    NudeRecordQualificationError,
    qualify_input_terminal_record,
    qualify_nonacceptance_record,
    qualify_terminal_record,
)

SCHEMA_VERSION = "maskfactory.nude_terminal_batch.v1"


class NudeTerminalBatchError(ValueError):
    """A terminal batch violated its closed, immutable processing contract."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise NudeTerminalBatchError(f"{field}_invalid")
    return value


def _atomic_write_exact(path: Path, document: Mapping[str, Any]) -> str:
    encoded = (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    )
    if path.exists():
        if path.read_bytes() != encoded:
            raise NudeTerminalBatchError(f"immutable_output_conflict:{path.name}")
        return hashlib.sha256(encoded).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(encoded).hexdigest()


def _qualify_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    if set(entry) != {"record", "panels"}:
        raise NudeTerminalBatchError("entry_fields_not_closed")
    record = entry.get("record")
    panels = entry.get("panels")
    if not isinstance(record, Mapping):
        raise NudeTerminalBatchError("entry_record_invalid")
    outcome = record.get("outcome")
    if outcome in {"accepted", "repaired"}:
        if not isinstance(panels, Mapping):
            raise NudeTerminalBatchError("terminal_panels_required")
        return qualify_terminal_record(record, panels=panels)
    if outcome in {"abstained", "rejected"}:
        if not isinstance(panels, Mapping):
            raise NudeTerminalBatchError("nonacceptance_panels_required")
        return qualify_nonacceptance_record(record, panels=panels)
    if outcome in {"quarantined", "holdout"}:
        if panels is not None:
            raise NudeTerminalBatchError("input_terminal_panels_must_be_null")
        return qualify_input_terminal_record(record)
    raise NudeTerminalBatchError("entry_outcome_invalid")


def process_terminal_batch(
    entries: Sequence[Mapping[str, Any]],
    *,
    source_manifest_sha256: str,
    output_root: Path,
) -> dict[str, Any]:
    """Qualify every record independently and persist immutable receipts/errors."""

    _sha256(source_manifest_sha256, "source_manifest_sha256")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)) or not entries:
        raise NudeTerminalBatchError("entries_invalid")
    identity = {
        "schema_version": "maskfactory.nude_terminal_batch_identity.v1",
        "source_manifest_sha256": source_manifest_sha256,
        "record_count": len(entries),
    }
    identity["self_sha256"] = _canonical_sha256(identity)
    _atomic_write_exact(output_root / "batch_identity.json", identity)
    results: list[dict[str, Any]] = []
    outcome_counts: dict[str, int] = {}
    for index, entry in enumerate(entries):
        input_sha256 = _canonical_sha256(entry)
        try:
            payload = _qualify_entry(entry)
            outcome = str(payload["outcome"])
            artifact: dict[str, Any] = {
                "schema_version": "maskfactory.nude_terminal_batch_record.v1",
                "ordinal": index,
                "input_sha256": input_sha256,
                "status": "qualified",
                "outcome": outcome,
                "payload": payload,
                "error": None,
            }
        except (NudeRecordQualificationError, NudeTerminalBatchError, OSError, ValueError) as exc:
            outcome = "processing_error"
            artifact = {
                "schema_version": "maskfactory.nude_terminal_batch_record.v1",
                "ordinal": index,
                "input_sha256": input_sha256,
                "status": "error",
                "outcome": outcome,
                "payload": None,
                "error": {"type": type(exc).__name__, "reason": str(exc)},
            }
        artifact["record_sha256"] = _canonical_sha256(artifact)
        filename = f"record_{index:06d}_{outcome}.json"
        artifact_file_sha256 = _atomic_write_exact(output_root / "records" / filename, artifact)
        results.append(
            {
                "ordinal": index,
                "status": artifact["status"],
                "outcome": outcome,
                "record_path": f"records/{filename}",
                "record_file_sha256": artifact_file_sha256,
                "record_sha256": artifact["record_sha256"],
            }
        )
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "adult_corpus_terminal_qualification_batch",
        "authority": "qualification_receipts_only_no_certificate_or_gold_authority",
        "source_manifest_sha256": source_manifest_sha256,
        "record_count": len(entries),
        "qualified_count": sum(row["status"] == "qualified" for row in results),
        "error_count": sum(row["status"] == "error" for row in results),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "records": results,
        "completion_claimed": False,
    }
    summary["self_sha256"] = _canonical_sha256(summary)
    _atomic_write_exact(output_root / "summary.json", summary)
    return summary


__all__ = [
    "NudeTerminalBatchError",
    "SCHEMA_VERSION",
    "process_terminal_batch",
]
