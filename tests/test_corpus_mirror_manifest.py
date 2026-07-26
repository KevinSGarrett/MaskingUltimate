from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from maskfactory.corpus_mirror_manifest import (
    CorpusMirrorManifestError,
    build_corpus_mirror_manifest,
    canonical_sha256,
    sha256_file,
    verify_corpus_mirror_manifest,
)


def _source(root: Path) -> Path:
    source = root / "source"
    (source / "nested").mkdir(parents=True)
    (source / "a.bin").write_bytes(b"a")
    (source / "nested" / "b.bin").write_bytes(b"bb")
    return source


def _build(root: Path, source: Path | None = None):
    source = source or _source(root)
    destination = root / "destination"
    destination.mkdir()
    (destination / "nested").mkdir()
    (destination / "a.bin").write_bytes(b"a")
    (destination / "nested" / "b.bin").write_bytes(b"bb")
    output = root / "output"
    result = build_corpus_mirror_manifest(
        source_root=source,
        destination_root=destination,
        output_dir=output,
        asset_id="fixture",
        batch_size=1,
    )
    (destination / "MIGRATION_MANIFEST.json").write_bytes(
        result.manifest_path.read_bytes()
    )
    (destination / "MIGRATION_INVENTORY.sqlite").write_bytes(
        result.inventory_path.read_bytes()
    )
    return result, destination


def test_byte_exact_corpus_mirror_passes(tmp_path: Path) -> None:
    result, destination = _build(tmp_path)
    verification = verify_corpus_mirror_manifest(
        destination / "MIGRATION_MANIFEST.json",
        destination,
    )
    assert verification["issues"] == []
    assert all(verification["checks"].values())
    assert verification["detail"]["entry_count"] == 2
    assert verification["detail"]["total_bytes"] == 3
    assert verification["detail"]["tree_sha256"] == result.tree_sha256


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing", "CORPUS_FILE_MISSING"),
        ("drift", "CORPUS_FILE_DRIFT"),
        ("extra", "CORPUS_UNMANIFESTED_FILES"),
    ],
)
def test_missing_drifted_or_extra_file_fails(
    tmp_path: Path,
    mutation: str,
    code: str,
) -> None:
    _, destination = _build(tmp_path)
    if mutation == "missing":
        (destination / "a.bin").unlink()
    elif mutation == "drift":
        (destination / "a.bin").write_bytes(b"x")
    else:
        (destination / "extra.bin").write_bytes(b"x")
    verification = verify_corpus_mirror_manifest(
        destination / "MIGRATION_MANIFEST.json",
        destination,
    )
    assert code in {issue["code"] for issue in verification["issues"]}


def test_inventory_hash_drift_fails_before_trusting_rows(tmp_path: Path) -> None:
    _, destination = _build(tmp_path)
    inventory = destination / "MIGRATION_INVENTORY.sqlite"
    with inventory.open("ab") as stream:
        stream.write(b"drift")
    verification = verify_corpus_mirror_manifest(
        destination / "MIGRATION_MANIFEST.json",
        destination,
    )
    assert verification["checks"]["inventory_raw_hash"] is False
    assert verification["issues"][0]["code"] == "CORPUS_INVENTORY_HASH_DRIFT"


def test_resume_reuses_unchanged_rows_and_rehashes_changed_rows(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    output = tmp_path / "output"
    destination = tmp_path / "destination"
    first = build_corpus_mirror_manifest(
        source_root=source,
        destination_root=destination,
        output_dir=output,
        asset_id="fixture",
        batch_size=1,
    )
    first.manifest_path.unlink()
    (source / "a.bin").write_bytes(b"changed")
    second = build_corpus_mirror_manifest(
        source_root=source,
        destination_root=destination,
        output_dir=output,
        asset_id="fixture",
        batch_size=1,
    )
    progress = json.loads(
        (output / "MIGRATION_PROGRESS.json").read_text(encoding="utf-8")
    )
    assert progress["hashed_file_count"] == 1
    assert progress["reused_file_count"] == 1
    assert second.tree_sha256 != first.tree_sha256


def test_resume_binding_mismatch_and_sealed_overwrite_fail(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    output = tmp_path / "output"
    first = build_corpus_mirror_manifest(
        source_root=source,
        destination_root=tmp_path / "destination",
        output_dir=output,
        asset_id="fixture",
    )
    with pytest.raises(CorpusMirrorManifestError, match="refuse overwrite"):
        build_corpus_mirror_manifest(
            source_root=source,
            destination_root=tmp_path / "destination",
            output_dir=output,
            asset_id="fixture",
        )
    first.manifest_path.unlink()
    with pytest.raises(CorpusMirrorManifestError, match="binding mismatch"):
        build_corpus_mirror_manifest(
            source_root=source,
            destination_root=tmp_path / "different",
            output_dir=output,
            asset_id="fixture",
        )


def test_manifest_self_hash_and_inventory_summary_fail_closed(
    tmp_path: Path,
) -> None:
    _, destination = _build(tmp_path)
    manifest_path = destination / "MIGRATION_MANIFEST.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["destination_root"] = str(tmp_path / "elsewhere")
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CorpusMirrorManifestError, match="self-hash mismatch"):
        verify_corpus_mirror_manifest(manifest_path, destination)

    _, destination_two = _build(tmp_path / "second")
    inventory = destination_two / "MIGRATION_INVENTORY.sqlite"
    manifest = json.loads(
        (destination_two / "MIGRATION_MANIFEST.json").read_text(encoding="utf-8")
    )
    with sqlite3.connect(inventory) as connection:
        connection.execute("UPDATE metadata SET value='999' WHERE key='entry_count'")
    manifest["inventory"]["raw_sha256"] = sha256_file(inventory)
    manifest["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    (destination_two / "MIGRATION_MANIFEST.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    verification = verify_corpus_mirror_manifest(
        destination_two / "MIGRATION_MANIFEST.json",
        destination_two,
    )
    assert verification["checks"]["inventory_summary_binding"] is False


def test_manifest_must_be_at_destination_root(tmp_path: Path) -> None:
    result, destination = _build(tmp_path)
    with pytest.raises(CorpusMirrorManifestError, match="destination root"):
        verify_corpus_mirror_manifest(
            result.manifest_path,
            destination,
        )


def test_inventory_metadata_drift_fails_closed(tmp_path: Path) -> None:
    _, destination = _build(tmp_path)
    inventory = destination / "MIGRATION_INVENTORY.sqlite"
    manifest_path = destination / "MIGRATION_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with sqlite3.connect(inventory) as connection:
        connection.execute("UPDATE metadata SET value='foreign' WHERE key='asset_id'")
    manifest["inventory"]["raw_sha256"] = sha256_file(inventory)
    manifest["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    verification = verify_corpus_mirror_manifest(
        manifest_path,
        destination,
    )
    assert verification["checks"]["inventory_metadata_binding"] is False
    assert "CORPUS_INVENTORY_METADATA_DRIFT" in {
        issue["code"] for issue in verification["issues"]
    }


def test_cli_imports_from_repository_checkout(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            str(repository_root / "tools" / "build_corpus_mirror_manifest.py"),
            "--help",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "{build,verify}" in completed.stdout
