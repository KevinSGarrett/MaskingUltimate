"""Fail-closed durability audit for active assets transferred onto RunPod."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from maskfactory.aws_runpod_transfer import (
    TransferManifestError,
    verify_transfer_manifest,
)
from maskfactory.corpus_mirror_manifest import (
    CorpusMirrorManifestError,
    verify_corpus_mirror_manifest,
)

REGISTRY_SCHEMA_VERSION = "maskfactory.transferred_asset_registry.v1"
AUDIT_SCHEMA_VERSION = "maskfactory.transferred_asset_durability_audit.v1"


class DurabilityRegistryError(ValueError):
    """The transferred-asset registry itself is invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def seal_registry(document: dict[str, Any]) -> dict[str, Any]:
    sealed = json.loads(json.dumps(document))
    sealed.pop("registry_sha256", None)
    sealed["registry_sha256"] = canonical_sha256(sealed)
    return sealed


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _safe_absolute(path_value: object, allowed_root: Path, field: str) -> Path:
    path = Path(str(path_value or ""))
    if not path.is_absolute():
        raise DurabilityRegistryError(f"{field} must be absolute")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(allowed_root.resolve(strict=True))
    except ValueError as exc:
        raise DurabilityRegistryError(f"{field} escapes allowed_root") from exc
    return resolved


def _safe_child(root: Path, value: object, field: str) -> Path:
    relative = Path(str(value or ""))
    if not str(value or "") or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{field} must be a safe relative path")
    path = (root / relative).resolve(strict=False)
    try:
        path.relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise ValueError(f"{field} escapes manifest root") from exc
    return path


def _load_registry(path: Path, allowed_root: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DurabilityRegistryError(f"cannot read registry: {exc}") from exc
    if not isinstance(document, dict):
        raise DurabilityRegistryError("registry must be a JSON object")
    if document.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise DurabilityRegistryError("unsupported registry schema_version")
    expected = document.get("registry_sha256")
    unsigned = dict(document)
    unsigned.pop("registry_sha256", None)
    if not _is_sha256(expected) or canonical_sha256(unsigned) != expected:
        raise DurabilityRegistryError("registry self-hash mismatch")
    if document.get("allowed_root") != str(allowed_root):
        raise DurabilityRegistryError("registry allowed_root mismatch")
    assets = document.get("assets")
    if not isinstance(assets, list) or not assets:
        raise DurabilityRegistryError("registry assets must be a non-empty list")
    identifiers = [
        str(row.get("asset_id") or "") for row in assets if isinstance(row, dict)
    ]
    if len(identifiers) != len(assets) or any(not item for item in identifiers):
        raise DurabilityRegistryError("every asset requires asset_id")
    if len(set(identifiers)) != len(identifiers):
        raise DurabilityRegistryError("asset_id values must be unique")
    if not any(row.get("lifecycle") == "active" for row in assets):
        raise DurabilityRegistryError("registry has no active assets")
    return assets


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _audit_package_sync(
    manifest_path: Path,
    destination: Path,
    row: dict[str, Any],
) -> tuple[dict[str, bool], list[dict[str, str]], dict[str, Any]]:
    checks: dict[str, bool] = {}
    issues: list[dict[str, str]] = []
    detail: dict[str, Any] = {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return checks, [_issue("MANIFEST_UNREADABLE", str(exc))], detail

    self_hash = manifest.get("manifest_sha256")
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    checks["manifest_self_hash"] = (
        _is_sha256(self_hash) and canonical_sha256(unsigned) == self_hash
    )
    if not checks["manifest_self_hash"]:
        issues.append(_issue("MANIFEST_SELF_HASH_DRIFT", str(manifest_path)))
    checks["manifest_self_hash_binding"] = row.get("manifest_self_sha256") == self_hash
    if not checks["manifest_self_hash_binding"]:
        issues.append(_issue("MANIFEST_BINDING_DRIFT", str(manifest_path)))

    chunks = manifest.get("chunks")
    chunks_valid = isinstance(chunks, list) and bool(chunks)
    if chunks_valid:
        indices = [
            item.get("index") if isinstance(item, dict) else None for item in chunks
        ]
        chunks_valid = indices == list(range(len(chunks)))
    checks["chunk_order_contiguous"] = chunks_valid
    if not chunks_valid:
        issues.append(_issue("CHUNK_ORDER_INVALID", str(manifest_path)))

    manifest_root = manifest_path.parent
    combined = hashlib.sha256()
    combined_bytes = 0
    if chunks_valid:
        for index, chunk in enumerate(chunks):
            try:
                chunk_path = _safe_child(
                    manifest_root,
                    chunk.get("name"),
                    f"chunks[{index}].name",
                )
            except ValueError as exc:
                issues.append(_issue("CHUNK_PATH_INVALID", str(exc)))
                chunks_valid = False
                break
            if not chunk_path.is_file():
                issues.append(_issue("CHUNK_MISSING", str(chunk_path)))
                chunks_valid = False
                continue
            expected_size = chunk.get("size")
            expected_hash = chunk.get("sha256")
            if chunk_path.stat().st_size != expected_size:
                issues.append(_issue("CHUNK_SIZE_DRIFT", str(chunk_path)))
                chunks_valid = False
                continue
            if (
                not _is_sha256(expected_hash)
                or sha256_file(chunk_path) != expected_hash
            ):
                issues.append(_issue("CHUNK_HASH_DRIFT", str(chunk_path)))
                chunks_valid = False
                continue
            with chunk_path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    combined.update(block)
                    combined_bytes += len(block)
    checks["all_chunks_present_and_hash_bound"] = chunks_valid

    archive_hash = manifest.get("archive_sha256")
    archive_bytes = manifest.get("archive_bytes")
    checks["destination_is_manifest_archive"] = destination == (
        manifest_root / "packages.zip"
    ).resolve(strict=False)
    if not checks["destination_is_manifest_archive"]:
        issues.append(_issue("DESTINATION_BINDING_MISMATCH", str(destination)))
    checks["archive_present"] = destination.is_file()
    if not checks["archive_present"]:
        issues.append(_issue("UNASSEMBLED_DESTINATION", str(destination)))
    archive_matches = (
        destination.is_file()
        and destination.stat().st_size == archive_bytes
        and _is_sha256(archive_hash)
        and sha256_file(destination) == archive_hash
        and combined_bytes == archive_bytes
        and combined.hexdigest() == archive_hash
    )
    checks["archive_matches_chunks"] = archive_matches
    if destination.is_file() and not archive_matches:
        issues.append(_issue("ASSEMBLED_ARCHIVE_DRIFT", str(destination)))

    files = manifest.get("files")
    payload_matches = isinstance(files, dict) and bool(files) and archive_matches
    if payload_matches:
        file_names = list(files)
        payload_matches = all(
            name and not Path(name).is_absolute() and ".." not in Path(name).parts
            for name in file_names
        )
    if payload_matches:
        try:
            with zipfile.ZipFile(destination, "r") as archive:
                names = [name for name in archive.namelist() if not name.endswith("/")]
                if (
                    len(names) != len(set(names))
                    or len(names) != len(files)
                    or set(names) != set(files)
                ):
                    payload_matches = False
                else:
                    for name, expected_hash in files.items():
                        if (
                            not _is_sha256(expected_hash)
                            or hashlib.sha256(archive.read(name)).hexdigest()
                            != expected_hash
                        ):
                            payload_matches = False
                            break
        except (OSError, zipfile.BadZipFile, KeyError):
            payload_matches = False
    checks["archive_payload_manifest"] = payload_matches
    if archive_matches and not payload_matches:
        issues.append(_issue("ARCHIVE_PAYLOAD_DRIFT", str(destination)))
    detail.update(
        {
            "chunk_count": len(chunks) if isinstance(chunks, list) else None,
            "archive_sha256": archive_hash,
            "archive_bytes": archive_bytes,
            "payload_file_count": len(files) if isinstance(files, dict) else None,
        }
    )
    return checks, issues, detail


def _audit_aws_chunk_transfer(
    manifest_path: Path,
    destination: Path,
    allowed_root: Path,
) -> tuple[dict[str, bool], list[dict[str, str]], dict[str, Any]]:
    checks: dict[str, bool] = {}
    issues: list[dict[str, str]] = []
    detail: dict[str, Any] = {}
    try:
        verified = verify_transfer_manifest(
            manifest_path,
            allowed_root=allowed_root,
        )
    except TransferManifestError as exc:
        return checks, [_issue("MANIFEST_CONTRACT_INVALID", str(exc))], detail
    checks["manifest_contract_valid"] = True
    checks["destination_binding"] = verified.destination == destination
    if not checks["destination_binding"]:
        issues.append(_issue("DESTINATION_BINDING_MISMATCH", str(destination)))
    assembled = (
        destination.is_file()
        and destination.stat().st_size == verified.expected_bytes
        and sha256_file(destination) == verified.expected_sha256
    )
    checks["assembled_destination_hash"] = assembled
    if not assembled:
        issues.append(_issue("UNASSEMBLED_OR_DRIFTED_DESTINATION", str(destination)))
    detail.update(
        {
            "transfer_id": verified.transfer_id,
            "chunk_count": len(verified.chunk_paths),
            "expected_bytes": verified.expected_bytes,
            "expected_sha256": verified.expected_sha256,
        }
    )
    return checks, issues, detail


def _audit_corpus_mirror(
    manifest_path: Path,
    destination: Path,
    row: dict[str, Any],
) -> tuple[dict[str, bool], list[dict[str, str]], dict[str, Any]]:
    checks: dict[str, bool] = {}
    issues: list[dict[str, str]] = []
    detail: dict[str, Any] = {}
    try:
        verified = verify_corpus_mirror_manifest(
            manifest_path,
            destination,
        )
    except (CorpusMirrorManifestError, OSError) as exc:
        return (
            checks,
            [_issue("CORPUS_MIRROR_MANIFEST_INVALID", str(exc))],
            detail,
        )
    checks.update(verified["checks"])
    issues.extend(verified["issues"])
    detail.update(verified["detail"])
    checks["manifest_self_hash_binding"] = row.get("manifest_self_sha256") == verified[
        "detail"
    ].get("manifest_self_sha256")
    if not checks["manifest_self_hash_binding"]:
        issues.append(_issue("MANIFEST_BINDING_DRIFT", str(manifest_path)))
    return checks, issues, detail


def audit_registry(
    registry_path: Path,
    *,
    allowed_root: Path = Path("/workspace"),
    container_root: Path = Path("/"),
    device_of: Callable[[Path], int] | None = None,
) -> dict[str, Any]:
    assets = _load_registry(registry_path, allowed_root)
    get_device = device_of or (lambda path: os.stat(path).st_dev)
    container_device = get_device(container_root)
    results: list[dict[str, Any]] = []
    for row in assets:
        if row.get("lifecycle") != "active":
            continue
        asset_id = str(row["asset_id"])
        kind = str(row.get("manifest_kind") or "")
        manifest = _safe_absolute(
            row.get("manifest_path"),
            allowed_root,
            f"{asset_id}.manifest_path",
        )
        destination = _safe_absolute(
            row.get("destination_path"),
            allowed_root,
            f"{asset_id}.destination_path",
        )
        checks: dict[str, bool] = {
            "manifest_present": manifest.is_file(),
            "destination_present": destination.exists(),
        }
        issues: list[dict[str, str]] = []
        detail: dict[str, Any] = {}
        if not checks["manifest_present"]:
            issues.append(_issue("MISSING_MIGRATION_MANIFEST", str(manifest)))
        if not checks["destination_present"]:
            issues.append(_issue("MISSING_DESTINATION", str(destination)))
        checks["persistent_device_not_root_overlay"] = (
            destination.exists() and get_device(destination) != container_device
        )
        if destination.exists() and not checks["persistent_device_not_root_overlay"]:
            issues.append(_issue("ROOT_OVERLAY_ONLY", str(destination)))

        expected_raw = row.get("manifest_raw_sha256")
        checks["manifest_raw_hash"] = (
            manifest.is_file()
            and _is_sha256(expected_raw)
            and sha256_file(manifest) == expected_raw
        )
        if manifest.is_file() and not checks["manifest_raw_hash"]:
            issues.append(_issue("MANIFEST_RAW_HASH_DRIFT", str(manifest)))

        if manifest.is_file() and kind == "package_sync_v1":
            child_checks, child_issues, detail = _audit_package_sync(
                manifest,
                destination,
                row,
            )
            checks.update(child_checks)
            issues.extend(child_issues)
        elif manifest.is_file() and kind == "aws_chunk_transfer_v1":
            child_checks, child_issues, detail = _audit_aws_chunk_transfer(
                manifest,
                destination,
                allowed_root,
            )
            checks.update(child_checks)
            issues.extend(child_issues)
        elif manifest.is_file() and kind == "corpus_mirror_v1":
            child_checks, child_issues, detail = _audit_corpus_mirror(
                manifest,
                destination,
                row,
            )
            checks.update(child_checks)
            issues.extend(child_issues)
        elif manifest.is_file():
            checks["manifest_kind_supported"] = False
            issues.append(_issue("UNSUPPORTED_MANIFEST_KIND", kind))

        results.append(
            {
                "asset_id": asset_id,
                "manifest_kind": kind,
                "manifest_path": str(manifest),
                "destination_path": str(destination),
                "status": "PASS" if all(checks.values()) and not issues else "FAIL",
                "checks": checks,
                "issues": issues,
                "detail": detail,
            }
        )

    result: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "scope": "active_transferred_assets_only",
        "authority_claimed": False,
        "registry_path": str(registry_path.resolve()),
        "registry_raw_sha256": sha256_file(registry_path),
        "registry_self_sha256": json.loads(registry_path.read_text(encoding="utf-8"))[
            "registry_sha256"
        ],
        "active_asset_count": len(results),
        "pass_count": sum(row["status"] == "PASS" for row in results),
        "fail_count": sum(row["status"] == "FAIL" for row in results),
        "assets": results,
    }
    result["status"] = (
        "RUNTIME_PASS_DURABILITY"
        if results and result["fail_count"] == 0
        else "RUNTIME_BLOCKED_DURABILITY"
    )
    result["self_sha256"] = canonical_sha256(result)
    return result
