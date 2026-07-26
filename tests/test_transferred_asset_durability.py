from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from maskfactory.aws_runpod_transfer import (
    ordered_chunk_list_sha256,
    seal_manifest,
)
from maskfactory.transferred_asset_durability import (
    DurabilityRegistryError,
    audit_registry,
    canonical_sha256,
    seal_registry,
    sha256_file,
)


def _write_package(root: Path) -> tuple[Path, Path]:
    transfer = root / "transfer"
    transfer.mkdir(parents=True)
    payloads = {
        "a/source.png": b"source",
        "a/mask.png": b"mask",
    }
    archive_path = transfer / "packages.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    archive_bytes = archive_path.read_bytes()
    chunks = []
    for index, start in enumerate(range(0, len(archive_bytes), 13)):
        payload = archive_bytes[start : start + 13]
        name = f"part-{index:06d}"
        (transfer / name).write_bytes(payload)
        chunks.append(
            {
                "index": index,
                "name": name,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest = {
        "schema_version": "1.0.0",
        "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "archive_bytes": len(archive_bytes),
        "files": {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in payloads.items()
        },
        "chunks": chunks,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    manifest_path = transfer / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path, archive_path


def _write_registry(
    root: Path,
    manifest: Path,
    destination: Path,
    *,
    kind: str = "package_sync_v1",
) -> Path:
    manifest_doc = (
        json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
    )
    registry = seal_registry(
        {
            "schema_version": "maskfactory.transferred_asset_registry.v1",
            "allowed_root": str(root),
            "assets": [
                {
                    "asset_id": "asset-1",
                    "lifecycle": "active",
                    "manifest_kind": kind,
                    "manifest_path": str(manifest),
                    "manifest_raw_sha256": (
                        sha256_file(manifest) if manifest.is_file() else None
                    ),
                    "manifest_self_sha256": manifest_doc.get("manifest_sha256"),
                    "destination_path": str(destination),
                }
            ],
        }
    )
    path = root / "registry.json"
    path.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_aws_transfer(root: Path) -> tuple[Path, Path]:
    transfer = root / "aws-transfer"
    transfer.mkdir(parents=True)
    payloads = [b"persistent-", b"runtime"]
    chunks = []
    for index, payload in enumerate(payloads):
        path = transfer / f"part-{index:06d}"
        path.write_bytes(payload)
        chunks.append(
            {
                "index": index,
                "path": path.name,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    marker = transfer / "COMPLETE.json"
    marker.write_text('{"complete":true}\n', encoding="utf-8")
    combined = b"".join(payloads)
    destination = root / "assembled" / "model.bin"
    destination.parent.mkdir()
    destination.write_bytes(combined)
    manifest = seal_manifest(
        {
            "schema_version": "1.0.0",
            "transfer_id": "aws-transfer-fixture",
            "source": {
                "uri": "s3://fixture/qualified/model.bin",
                "role": "fixture",
                "version": "1.0.0",
                "license_allowed_use": "test",
                "qualification_evidence_sha256": "1" * 64,
                "expected_bytes": len(combined),
                "expected_sha256": hashlib.sha256(combined).hexdigest(),
            },
            "destination": {
                "path": str(destination.relative_to(root)),
                "storage_class": "runpod_persistent_network_volume",
            },
            "chunks": chunks,
            "completion": {
                "complete": True,
                "expected_chunk_count": len(chunks),
                "ordered_chunk_list_sha256": ordered_chunk_list_sha256(chunks),
                "marker_path": marker.name,
                "marker_sha256": sha256_file(marker),
            },
        }
    )
    manifest_path = transfer / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path, destination


def _audit(
    registry: Path,
    root: Path,
    *,
    destination_device: int = 2,
) -> dict:
    return audit_registry(
        registry,
        allowed_root=root,
        container_root=root,
        device_of=lambda path: (destination_device if path != root else 1),
    )


def test_complete_package_transfer_passes(tmp_path: Path) -> None:
    manifest, archive = _write_package(tmp_path)
    registry = _write_registry(tmp_path, manifest, archive)
    result = _audit(registry, tmp_path)
    assert result["status"] == "RUNTIME_PASS_DURABILITY"
    assert result["pass_count"] == 1
    assert result["assets"][0]["checks"]["archive_payload_manifest"] is True


def test_complete_aws_chunk_transfer_passes(tmp_path: Path) -> None:
    manifest, destination = _write_aws_transfer(tmp_path)
    registry = _write_registry(
        tmp_path,
        manifest,
        destination,
        kind="aws_chunk_transfer_v1",
    )
    result = _audit(registry, tmp_path)
    assert result["status"] == "RUNTIME_PASS_DURABILITY"
    assert result["assets"][0]["checks"]["manifest_contract_valid"] is True
    assert result["assets"][0]["checks"]["assembled_destination_hash"] is True


def test_missing_manifest_fails_closed(tmp_path: Path) -> None:
    destination = tmp_path / "mirror"
    destination.mkdir()
    registry = _write_registry(
        tmp_path,
        tmp_path / "MIGRATION_MANIFEST.json",
        destination,
    )
    result = _audit(registry, tmp_path)
    assert result["status"] == "RUNTIME_BLOCKED_DURABILITY"
    assert result["assets"][0]["issues"][0]["code"] == "MISSING_MIGRATION_MANIFEST"


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing", "CHUNK_MISSING"),
        ("corrupt", "CHUNK_HASH_DRIFT"),
        ("reordered", "CHUNK_ORDER_INVALID"),
    ],
)
def test_partial_corrupt_or_reordered_chunks_fail(
    tmp_path: Path,
    mutation: str,
    code: str,
) -> None:
    manifest, archive = _write_package(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if mutation == "missing":
        (manifest.parent / document["chunks"][0]["name"]).unlink()
    elif mutation == "corrupt":
        chunk = manifest.parent / document["chunks"][0]["name"]
        chunk.write_bytes(b"x" * chunk.stat().st_size)
    else:
        document["chunks"].reverse()
        document["manifest_sha256"] = canonical_sha256(
            {key: value for key, value in document.items() if key != "manifest_sha256"}
        )
        manifest.write_text(json.dumps(document), encoding="utf-8")
    registry = _write_registry(tmp_path, manifest, archive)
    result = _audit(registry, tmp_path)
    assert result["status"] == "RUNTIME_BLOCKED_DURABILITY"
    assert code in {item["code"] for item in result["assets"][0]["issues"]}


def test_root_overlay_only_fails(tmp_path: Path) -> None:
    manifest, archive = _write_package(tmp_path)
    registry = _write_registry(tmp_path, manifest, archive)
    result = _audit(registry, tmp_path, destination_device=1)
    assert result["status"] == "RUNTIME_BLOCKED_DURABILITY"
    assert "ROOT_OVERLAY_ONLY" in {
        item["code"] for item in result["assets"][0]["issues"]
    }


def test_unassembled_destination_fails(tmp_path: Path) -> None:
    manifest, archive = _write_package(tmp_path)
    registry = _write_registry(tmp_path, manifest, archive)
    archive.unlink()
    result = _audit(registry, tmp_path)
    assert result["status"] == "RUNTIME_BLOCKED_DURABILITY"
    assert "UNASSEMBLED_DESTINATION" in {
        item["code"] for item in result["assets"][0]["issues"]
    }


def test_registry_tamper_and_duplicate_ids_fail(tmp_path: Path) -> None:
    manifest, archive = _write_package(tmp_path)
    registry = _write_registry(tmp_path, manifest, archive)
    document = json.loads(registry.read_text(encoding="utf-8"))
    document["assets"][0]["destination_path"] = str(tmp_path / "drift")
    registry.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(DurabilityRegistryError, match="self-hash mismatch"):
        _audit(registry, tmp_path)

    registry = _write_registry(tmp_path, manifest, archive)
    document = json.loads(registry.read_text(encoding="utf-8"))
    document["assets"].append(dict(document["assets"][0]))
    document = seal_registry(document)
    registry.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(DurabilityRegistryError, match="must be unique"):
        _audit(registry, tmp_path)


def test_unsupported_manifest_kind_fails(tmp_path: Path) -> None:
    manifest, archive = _write_package(tmp_path)
    registry = _write_registry(
        tmp_path,
        manifest,
        archive,
        kind="unknown_v1",
    )
    result = _audit(registry, tmp_path)
    assert "UNSUPPORTED_MANIFEST_KIND" in {
        item["code"] for item in result["assets"][0]["issues"]
    }
