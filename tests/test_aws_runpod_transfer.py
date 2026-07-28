from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.aws_runpod_transfer import (
    TransferManifestError,
    assemble_transfer,
    ordered_chunk_list_sha256,
    seal_manifest,
    sha256_file,
    verify_transfer_manifest,
)


def _write_fixture(root: Path) -> Path:
    chunks_dir = root / "chunks"
    chunks_dir.mkdir(parents=True)
    payloads = [b"MaskFactory-", b"persistent-", b"artifact"]
    chunks = []
    for index, payload in enumerate(payloads):
        path = chunks_dir / f"part-{index:04d}"
        path.write_bytes(payload)
        chunks.append(
            {
                "index": index,
                "path": path.relative_to(root).as_posix(),
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    marker = root / "COMPLETE.json"
    marker.write_text('{"complete":true}\n', encoding="utf-8")
    combined = b"".join(payloads)
    manifest = seal_manifest(
        {
            "schema_version": "1.0.0",
            "transfer_id": "fixture-transfer-1",
            "source": {
                "uri": "s3://fixture-bucket/qualified/model.bin",
                "role": "fixture_model",
                "version": "1.0.0",
                "license_allowed_use": "fixture-test-only",
                "qualification_evidence_sha256": "1" * 64,
                "expected_bytes": len(combined),
                "expected_sha256": hashlib.sha256(combined).hexdigest(),
            },
            "destination": {
                "path": "assembled/model.bin",
                "storage_class": "runpod_persistent_network_volume",
            },
            "chunks": chunks,
            "completion": {
                "complete": True,
                "expected_chunk_count": len(chunks),
                "ordered_chunk_list_sha256": ordered_chunk_list_sha256(chunks),
                "marker_path": marker.relative_to(root).as_posix(),
                "marker_sha256": sha256_file(marker),
            },
        }
    )
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def _mutate_manifest(path: Path, mutation) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    mutation(document)
    path.write_text(json.dumps(seal_manifest(document), indent=2) + "\n", encoding="utf-8")


def test_complete_fixture_assembles_byte_identically_and_is_idempotent(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    allowed_root = tmp_path / "destination"
    verified = verify_transfer_manifest(manifest, allowed_root=allowed_root)

    receipt = assemble_transfer(verified)

    destination = allowed_root / "assembled" / "model.bin"
    assert destination.read_bytes() == b"MaskFactory-persistent-artifact"
    assert receipt["sha256"] == sha256_file(destination)
    assert receipt["idempotent_existing_destination"] is False
    assert assemble_transfer(verified)["idempotent_existing_destination"] is True


def test_missing_chunk_fails(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    (tmp_path / "chunks" / "part-0001").unlink()

    with pytest.raises(TransferManifestError, match="chunk 1 is missing"):
        verify_transfer_manifest(manifest, allowed_root=tmp_path / "destination")


def test_reordered_chunks_fail(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    _mutate_manifest(manifest, lambda document: document["chunks"].reverse())

    with pytest.raises(TransferManifestError, match="contiguous and ordered"):
        verify_transfer_manifest(manifest, allowed_root=tmp_path / "destination")


def test_corrupt_chunk_fails(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    (tmp_path / "chunks" / "part-0000").write_bytes(b"maskfactory-")

    with pytest.raises(TransferManifestError, match="chunk 0 hash mismatch"):
        verify_transfer_manifest(manifest, allowed_root=tmp_path / "destination")


def test_incomplete_marker_and_count_fail(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    _mutate_manifest(
        manifest,
        lambda document: document["completion"].update({"complete": False}),
    )

    with pytest.raises(TransferManifestError, match="absent or incomplete"):
        verify_transfer_manifest(manifest, allowed_root=tmp_path / "destination")


def test_destination_escape_fails(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    _mutate_manifest(
        manifest,
        lambda document: document["destination"].update({"path": "../escape.bin"}),
    )

    with pytest.raises(TransferManifestError, match="destination escapes"):
        verify_transfer_manifest(manifest, allowed_root=tmp_path / "destination")


def test_manifest_tamper_fails_before_chunk_use(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["source"]["version"] = "tampered"
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(TransferManifestError, match="self-hash mismatch"):
        verify_transfer_manifest(manifest, allowed_root=tmp_path / "destination")


def test_wrong_whole_object_hash_fails_and_removes_partial(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    _mutate_manifest(
        manifest,
        lambda document: document["source"].update({"expected_sha256": "f" * 64}),
    )
    allowed_root = tmp_path / "destination"
    verified = verify_transfer_manifest(manifest, allowed_root=allowed_root)

    with pytest.raises(TransferManifestError, match="whole-object hash mismatch"):
        assemble_transfer(verified)

    assert not verified.destination.exists()
    assert not list(verified.destination.parent.glob("*.partial"))
