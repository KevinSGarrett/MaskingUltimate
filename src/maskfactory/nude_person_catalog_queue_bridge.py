"""Fail-closed bridge from a sealed person-catalog batch to durable stage evidence."""
from __future__ import annotations
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from .nude_batch_queue import NudeBatchQueue
from .nude_corpus_intake import canonical_sha256, sha256_file, validate_shard
from .nude_person_catalog import build_person_catalog_stage_receipt

SCHEMA_VERSION = "maskfactory.nude_person_catalog_queue_bridge.v1"

class NudePersonCatalogQueueBridgeError(ValueError):
    """A catalog batch cannot safely cross the durable queue boundary."""

def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _atomic_write_exact(path: Path, document: Mapping[str, Any]) -> str:
    encoded = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"
    if path.exists():
        if path.read_bytes() != encoded:
            raise NudePersonCatalogQueueBridgeError(f"immutable_output_conflict:{path.name}")
        return _file_sha256(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return _file_sha256(path)

def _load_batch(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise NudePersonCatalogQueueBridgeError("catalog_batch_not_object")
    unsigned = dict(document)
    if unsigned.pop("self_sha256", None) != canonical_sha256(unsigned):
        raise NudePersonCatalogQueueBridgeError("catalog_batch_self_hash_invalid")
    if (
        document.get("schema_version") != "maskfactory.nude_person_catalog_batch.v1"
        or document.get("authority") != "person_catalog_comparison_only"
        or document.get("production_mask_authority") is not False
        or document.get("operational_certificate_issued") is not False
        or not isinstance(document.get("records"), list)
        or document.get("record_count") != len(document["records"])
        or not isinstance(document.get("provider_artifacts"), list)
        or not isinstance(document.get("batch_lane"), str)
        or not document["batch_lane"]
        or not isinstance(document.get("platform"), str)
        or not isinstance(document.get("shard_self_sha256"), str)
    ):
        raise NudePersonCatalogQueueBridgeError("catalog_batch_contract_invalid")
    return document

def bridge_person_catalog_batch_to_queue(*, catalog_batch_path: Path, nude_shard_path: Path, output_path: Path, queue: NudeBatchQueue, platform: str, shard_path: str, lease_token: str) -> dict[str, Any]:
    """Checkpoint exact nonterminal catalog evidence under one pre-owned lease."""
    batch = _load_batch(catalog_batch_path)
    if batch["platform"] != platform:
        raise NudePersonCatalogQueueBridgeError("catalog_batch_platform_mismatch")
    shard = validate_shard(nude_shard_path, expected_lane=batch["batch_lane"], platform=platform)
    if batch["shard_self_sha256"] != shard["self_sha256"]:
        raise NudePersonCatalogQueueBridgeError("catalog_batch_shard_hash_mismatch")
    samples, records = list(shard["samples"]), batch["records"]
    if len(records) != len(samples):
        raise NudePersonCatalogQueueBridgeError("catalog_batch_record_count_mismatch")
    receipts = []
    for index, (sample, report) in enumerate(zip(samples, records, strict=True)):
        if not isinstance(report, Mapping) or report.get("sample_id") != sample.get("sample_id") or report.get("source_sha256") != sample.get("source_sha256"):
            raise NudePersonCatalogQueueBridgeError("catalog_record_shard_alignment_mismatch")
        receipts.append({**build_person_catalog_stage_receipt(report), "sample_index": index})
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        unsigned = dict(existing) if isinstance(existing, dict) else {}
        if unsigned.pop("self_sha256", None) != canonical_sha256(unsigned):
            raise NudePersonCatalogQueueBridgeError("existing_output_self_hash_invalid")
        expected = {
            "schema_version": SCHEMA_VERSION,
            "catalog_batch_self_sha256": batch["self_sha256"],
            "nude_shard_self_sha256": shard["self_sha256"],
            "platform": platform,
            "queue_shard_path": shard_path,
            "record_count": len(receipts),
            "authority": "durable_nonterminal_person_catalog_evidence_only",
            "terminal_progress_advanced": False,
            "production_mask_authority": False,
            "operational_certificate_issued": False,
        }
        if any(existing.get(key) != value for key, value in expected.items()):
            raise NudePersonCatalogQueueBridgeError(f"immutable_output_conflict:{output_path.name}")
        return existing
    checkpoint = queue.checkpoint_person_catalogs(platform=platform, shard_path=shard_path, lease_token=lease_token, receipts=receipts)
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "adult_corpus_person_catalog_queue_bridge",
        "catalog_batch_path": str(catalog_batch_path),
        "catalog_batch_file_sha256": _file_sha256(catalog_batch_path),
        "catalog_batch_self_sha256": batch["self_sha256"],
        "nude_shard_path": str(nude_shard_path),
        "nude_shard_file_sha256": sha256_file(nude_shard_path),
        "nude_shard_self_sha256": shard["self_sha256"],
        "platform": platform,
        "queue_shard_path": shard_path,
        "record_count": len(receipts),
        "checkpoint": checkpoint,
        "authority": "durable_nonterminal_person_catalog_evidence_only",
        "terminal_progress_advanced": False,
        "production_mask_authority": False,
        "operational_certificate_issued": False,
    }
    report = {**body, "self_sha256": canonical_sha256(body)}
    _atomic_write_exact(output_path, report)
    return report

__all__ = ["NudePersonCatalogQueueBridgeError", "SCHEMA_VERSION", "bridge_person_catalog_batch_to_queue"]