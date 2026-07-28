"""Fail-closed assembly for qualified AWS-to-RunPod chunk transfers."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"


class TransferManifestError(ValueError):
    """A transfer manifest or its local chunk set is invalid."""


@dataclass(frozen=True)
class VerifiedTransfer:
    manifest_path: Path
    manifest_sha256: str
    transfer_id: str
    destination: Path
    expected_bytes: int
    expected_sha256: str
    chunk_paths: tuple[Path, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def manifest_payload(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "manifest_sha256"}


def seal_manifest(document: dict[str, Any]) -> dict[str, Any]:
    sealed = json.loads(json.dumps(document))
    sealed["manifest_sha256"] = canonical_sha256(manifest_payload(sealed))
    return sealed


def ordered_chunk_list_sha256(chunks: list[dict[str, Any]]) -> str:
    rows = [
        {
            "index": row.get("index"),
            "path": row.get("path"),
            "size": row.get("size"),
            "sha256": row.get("sha256"),
        }
        for row in chunks
    ]
    return canonical_sha256(rows)


def _require_sha(value: Any, field: str) -> str:
    text = str(value or "").lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise TransferManifestError(f"{field} must be a lowercase SHA-256")
    return text


def _safe_relative(base: Path, raw: Any, field: str) -> Path:
    text = str(raw or "")
    relative = Path(text)
    if not text or relative.is_absolute() or ".." in relative.parts:
        raise TransferManifestError(f"{field} must be a safe relative path")
    resolved = (base / relative).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise TransferManifestError(f"{field} escapes the transfer root") from exc
    return resolved


def _safe_destination(raw: Any, allowed_root: Path) -> Path:
    destination = Path(str(raw or ""))
    if not destination.is_absolute():
        destination = allowed_root / destination
    resolved = destination.resolve()
    try:
        resolved.relative_to(allowed_root.resolve())
    except ValueError as exc:
        raise TransferManifestError("destination escapes the allowed RunPod root") from exc
    return resolved


def verify_transfer_manifest(
    manifest_path: Path,
    *,
    allowed_root: Path = Path("/workspace"),
) -> VerifiedTransfer:
    path = manifest_path.resolve()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransferManifestError(f"cannot read transfer manifest: {exc}") from exc
    if not isinstance(document, dict):
        raise TransferManifestError("transfer manifest must be a JSON object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise TransferManifestError("unsupported transfer manifest schema_version")
    manifest_hash = _require_sha(document.get("manifest_sha256"), "manifest_sha256")
    if manifest_hash != canonical_sha256(manifest_payload(document)):
        raise TransferManifestError("transfer manifest self-hash mismatch")

    transfer_id = str(document.get("transfer_id") or "")
    if not transfer_id or len(transfer_id) > 128:
        raise TransferManifestError("transfer_id is required and bounded")
    source = document.get("source")
    if not isinstance(source, dict) or not str(source.get("uri") or "").startswith("s3://"):
        raise TransferManifestError("source.uri must be an s3:// URI")
    required_source_fields = (
        "role",
        "version",
        "license_allowed_use",
        "qualification_evidence_sha256",
    )
    for field in required_source_fields:
        if not source.get(field):
            raise TransferManifestError(f"source.{field} is required")
    _require_sha(
        source.get("qualification_evidence_sha256"),
        "source.qualification_evidence_sha256",
    )
    expected_bytes = int(source.get("expected_bytes") or -1)
    if expected_bytes < 0:
        raise TransferManifestError("source.expected_bytes must be non-negative")
    expected_sha = _require_sha(source.get("expected_sha256"), "source.expected_sha256")

    destination_doc = document.get("destination")
    if not isinstance(destination_doc, dict):
        raise TransferManifestError("destination object is required")
    destination = _safe_destination(destination_doc.get("path"), allowed_root)
    if destination_doc.get("storage_class") != "runpod_persistent_network_volume":
        raise TransferManifestError("destination must be the RunPod persistent network volume")

    chunks = document.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise TransferManifestError("at least one chunk is required")
    indices = [row.get("index") for row in chunks if isinstance(row, dict)]
    if len(indices) != len(chunks) or indices != list(range(len(chunks))):
        raise TransferManifestError("chunk indices must be contiguous and ordered from zero")

    transfer_root = path.parent
    chunk_paths: list[Path] = []
    observed_bytes = 0
    for index, row in enumerate(chunks):
        chunk_path = _safe_relative(transfer_root, row.get("path"), f"chunks[{index}].path")
        if not chunk_path.is_file():
            raise TransferManifestError(f"chunk {index} is missing")
        expected_chunk_size = int(row.get("size") or -1)
        if expected_chunk_size < 0 or chunk_path.stat().st_size != expected_chunk_size:
            raise TransferManifestError(f"chunk {index} size mismatch")
        expected_chunk_hash = _require_sha(row.get("sha256"), f"chunks[{index}].sha256")
        if sha256_file(chunk_path) != expected_chunk_hash:
            raise TransferManifestError(f"chunk {index} hash mismatch")
        observed_bytes += expected_chunk_size
        chunk_paths.append(chunk_path)
    if observed_bytes != expected_bytes:
        raise TransferManifestError("chunk total does not match source.expected_bytes")

    completion = document.get("completion")
    if not isinstance(completion, dict) or completion.get("complete") is not True:
        raise TransferManifestError("completion record is absent or incomplete")
    if completion.get("expected_chunk_count") != len(chunks):
        raise TransferManifestError("completion chunk count mismatch")
    ordered_hash = _require_sha(
        completion.get("ordered_chunk_list_sha256"),
        "completion.ordered_chunk_list_sha256",
    )
    if ordered_hash != ordered_chunk_list_sha256(chunks):
        raise TransferManifestError("completion ordered chunk hash mismatch")
    marker_path = _safe_relative(
        transfer_root,
        completion.get("marker_path"),
        "completion.marker_path",
    )
    if not marker_path.is_file():
        raise TransferManifestError("completion marker is missing")
    marker_sha = _require_sha(completion.get("marker_sha256"), "completion.marker_sha256")
    if sha256_file(marker_path) != marker_sha:
        raise TransferManifestError("completion marker hash mismatch")

    return VerifiedTransfer(
        manifest_path=path,
        manifest_sha256=manifest_hash,
        transfer_id=transfer_id,
        destination=destination,
        expected_bytes=expected_bytes,
        expected_sha256=expected_sha,
        chunk_paths=tuple(chunk_paths),
    )


def assemble_transfer(verified: VerifiedTransfer) -> dict[str, Any]:
    destination = verified.destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        if (
            destination.stat().st_size == verified.expected_bytes
            and sha256_file(destination) == verified.expected_sha256
        ):
            return _receipt(verified, idempotent=True)
        raise TransferManifestError("destination exists with different bytes")

    temporary = destination.with_name(f".{destination.name}.{verified.transfer_id}.partial")
    digest = hashlib.sha256()
    written = 0
    try:
        with temporary.open("xb") as output:
            for chunk in verified.chunk_paths:
                with chunk.open("rb") as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        output.write(block)
                        digest.update(block)
                        written += len(block)
            output.flush()
            os.fsync(output.fileno())
        if written != verified.expected_bytes:
            raise TransferManifestError("assembled byte count mismatch")
        if digest.hexdigest() != verified.expected_sha256:
            raise TransferManifestError("assembled whole-object hash mismatch")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    if sha256_file(destination) != verified.expected_sha256:
        destination.unlink(missing_ok=True)
        raise TransferManifestError("post-promotion destination hash mismatch")
    return _receipt(verified, idempotent=False)


def _receipt(verified: VerifiedTransfer, *, idempotent: bool) -> dict[str, Any]:
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "transfer_id": verified.transfer_id,
        "manifest_sha256": verified.manifest_sha256,
        "destination": str(verified.destination),
        "bytes": verified.expected_bytes,
        "sha256": verified.expected_sha256,
        "idempotent_existing_destination": idempotent,
        "chunks_preserved_for_resume_or_rollback": True,
        "status": "assembled_and_verified",
    }
    receipt_path = verified.destination.with_suffix(verified.destination.suffix + ".receipt.json")
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt
