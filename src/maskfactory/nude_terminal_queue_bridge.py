"""Atomically bridge prepared terminal batches into the durable shard queue."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .nude_batch_queue import NudeBatchQueue
from .nude_dataset_coverage import build_nude_dataset_coverage
from .nude_terminal_batch import process_terminal_batch

SCHEMA_VERSION = "maskfactory.nude_terminal_queue_bridge.v1"


class NudeTerminalQueueBridgeError(ValueError):
    """Prepared terminal results could not cross the queue boundary safely."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write_exact(path: Path, document: Mapping[str, Any]) -> str:
    encoded = (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    )
    if path.exists():
        if path.read_bytes() != encoded:
            raise NudeTerminalQueueBridgeError(f"immutable_output_conflict:{path.name}")
        return hashlib.sha256(encoded).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(encoded).hexdigest()


def _normalize_entries(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[list[int], list[dict[str, Any]]]:
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)) or not entries:
        raise NudeTerminalQueueBridgeError("entries_invalid")
    indices: list[int] = []
    terminal_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {"sample_index", "terminal_entry"}:
            raise NudeTerminalQueueBridgeError("bridge_entry_fields_not_closed")
        sample_index = entry["sample_index"]
        if not isinstance(sample_index, int) or isinstance(sample_index, bool) or sample_index < 0:
            raise NudeTerminalQueueBridgeError("sample_index_invalid")
        terminal_entry = entry["terminal_entry"]
        if not isinstance(terminal_entry, Mapping):
            raise NudeTerminalQueueBridgeError("terminal_entry_invalid")
        indices.append(sample_index)
        terminal_entries.append(dict(terminal_entry))
    expected = list(range(indices[0], indices[0] + len(indices)))
    if indices != expected:
        raise NudeTerminalQueueBridgeError("sample_indices_must_be_contiguous_and_ordered")
    return indices, terminal_entries


def _load_record_artifact(
    *,
    output_root: Path,
    record: Mapping[str, Any],
    expected_ordinal: int,
    expected_input_sha256: str,
) -> dict[str, Any]:
    if record.get("ordinal") != expected_ordinal:
        raise NudeTerminalQueueBridgeError("terminal_summary_ordinal_mismatch")
    relative = record.get("record_path")
    if (
        not isinstance(relative, str)
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
    ):
        raise NudeTerminalQueueBridgeError("terminal_record_path_invalid")
    path = output_root / relative
    if not path.is_file() or _file_sha256(path) != record.get("record_file_sha256"):
        raise NudeTerminalQueueBridgeError("terminal_record_file_hash_mismatch")
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(artifact, dict):
        raise NudeTerminalQueueBridgeError("terminal_record_artifact_invalid")
    expected_record_sha = artifact.get("record_sha256")
    unsigned = {key: value for key, value in artifact.items() if key != "record_sha256"}
    if expected_record_sha != _canonical_sha256(unsigned):
        raise NudeTerminalQueueBridgeError("terminal_record_self_hash_mismatch")
    if artifact.get("record_sha256") != record.get("record_sha256"):
        raise NudeTerminalQueueBridgeError("terminal_summary_record_hash_mismatch")
    if artifact.get("status") != record.get("status") or artifact.get("outcome") != record.get(
        "outcome"
    ):
        raise NudeTerminalQueueBridgeError("terminal_summary_record_state_mismatch")
    if artifact.get("ordinal") != expected_ordinal:
        raise NudeTerminalQueueBridgeError("terminal_record_ordinal_mismatch")
    if artifact.get("input_sha256") != expected_input_sha256:
        raise NudeTerminalQueueBridgeError("terminal_record_input_hash_mismatch")
    return artifact


def bridge_terminal_batch_to_queue(
    entries: Sequence[Mapping[str, Any]],
    *,
    source_manifest_sha256: str,
    output_root: Path,
    queue: NudeBatchQueue,
    platform: str,
    shard_path: str,
    lease_token: str,
    registry_records: Path | None = None,
    ontology_crosswalk: Path | None = None,
) -> dict[str, Any]:
    """Process all records, checkpoint the valid contiguous prefix, and reconcile reports."""

    if (registry_records is None) != (ontology_crosswalk is None):
        raise NudeTerminalQueueBridgeError("coverage_inputs_must_be_supplied_together")
    indices, terminal_entries = _normalize_entries(entries)
    terminal_root = output_root / "terminal"
    terminal_summary = process_terminal_batch(
        terminal_entries,
        source_manifest_sha256=source_manifest_sha256,
        output_root=terminal_root,
    )
    ready: list[dict[str, Any]] = []
    first_error_ordinal: int | None = None
    for ordinal, record in enumerate(terminal_summary["records"]):
        artifact = _load_record_artifact(
            output_root=terminal_root,
            record=record,
            expected_ordinal=ordinal,
            expected_input_sha256=_canonical_sha256(terminal_entries[ordinal]),
        )
        if artifact.get("status") != "qualified":
            first_error_ordinal = ordinal
            break
        payload = artifact.get("payload")
        if not isinstance(payload, Mapping):
            raise NudeTerminalQueueBridgeError("qualified_terminal_payload_missing")
        ready.append({**dict(payload), "sample_index": indices[ordinal]})

    checkpoint_result: dict[str, Any] | None = None
    if ready:
        checkpoint_result = queue.checkpoint(
            platform=platform,
            shard_path=shard_path,
            lease_token=lease_token,
            outcomes=ready,
        )
    milestone = queue.milestone_report(platform=platform)
    milestone_path = output_root / "queue_milestone.json"
    milestone_file_sha256 = _atomic_write_exact(milestone_path, milestone)

    coverage: dict[str, Any] | None = None
    coverage_file_sha256: str | None = None
    if registry_records is not None and ontology_crosswalk is not None:
        coverage = build_nude_dataset_coverage(
            registry_records=registry_records,
            ontology_crosswalk=ontology_crosswalk,
            queue_path=queue.path,
            platform=platform,
        )
        coverage_file_sha256 = _atomic_write_exact(output_root / "dataset_coverage.json", coverage)

    durable_checkpoint = None
    if checkpoint_result is not None:
        durable_checkpoint = {
            "next_sample_index": checkpoint_result["next_sample_index"],
            "complete": checkpoint_result["complete"],
        }
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "adult_corpus_terminal_queue_bridge",
        "authority": "durable_queue_outcomes_only_no_certificate_or_gold_authority",
        "source_manifest_sha256": source_manifest_sha256,
        "platform": platform,
        "shard_path": shard_path,
        "input_record_count": len(entries),
        "qualified_artifact_count": terminal_summary["qualified_count"],
        "processing_error_count": terminal_summary["error_count"],
        "checkpoint_ready_prefix_count": len(ready),
        "first_error_ordinal": first_error_ordinal,
        "noncheckpointed_record_count": len(entries) - len(ready),
        "deferred_after_error_count": (
            len(entries) - first_error_ordinal - 1 if first_error_ordinal is not None else 0
        ),
        "durable_checkpoint": durable_checkpoint,
        "terminal_summary_path": "terminal/summary.json",
        "terminal_summary_file_sha256": _file_sha256(terminal_root / "summary.json"),
        "terminal_summary_self_sha256": terminal_summary["self_sha256"],
        "queue_milestone_path": "queue_milestone.json",
        "queue_milestone_file_sha256": milestone_file_sha256,
        "queue_milestone_self_sha256": milestone["self_sha256"],
        "queue_milestone_status": milestone["status"],
        "coverage_path": "dataset_coverage.json" if coverage is not None else None,
        "coverage_file_sha256": coverage_file_sha256,
        "coverage_self_sha256": coverage["self_sha256"] if coverage is not None else None,
        "coverage_status": coverage["status"] if coverage is not None else None,
        "completion_claimed": False,
    }
    report["self_sha256"] = _canonical_sha256(report)
    _atomic_write_exact(output_root / "bridge_receipt.json", report)
    return report


__all__ = [
    "NudeTerminalQueueBridgeError",
    "SCHEMA_VERSION",
    "bridge_terminal_batch_to_queue",
]
