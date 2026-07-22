from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from sync_packages_runpod import build, manifest_sha256  # noqa: E402


def _source(root: Path) -> Path:
    source = root / "packages"
    (source / "p0").mkdir(parents=True)
    (source / "p0" / "manifest.json").write_text('{"revision":1}\n', encoding="utf-8")
    (source / "p0" / "mask.png").write_bytes(b"png-bytes")
    return source


def test_build_is_deterministic_and_hash_bound(tmp_path: Path) -> None:
    source = _source(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    a = build(source, first, chunk_size=7)
    b = build(source, second, chunk_size=7)
    assert a == b
    assert (first / "packages.zip").read_bytes() == (second / "packages.zip").read_bytes()
    assert [row["index"] for row in a["chunks"]] == list(range(len(a["chunks"])))


def test_build_changes_when_package_bytes_change(tmp_path: Path) -> None:
    source = _source(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    a = build(source, first)
    (source / "p0" / "mask.png").write_bytes(b"changed")
    b = build(source, second)
    assert a["manifest_sha256"] != b["manifest_sha256"]
    assert a["archive_sha256"] != b["archive_sha256"]


def test_manifest_self_hash_excludes_no_content(tmp_path: Path) -> None:
    source = _source(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    manifest = build(source, output)
    on_disk = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert manifest_sha256(manifest) == manifest["manifest_sha256"]
    assert manifest["files"] == {
        "p0/manifest.json": manifest["files"]["p0/manifest.json"],
        "p0/mask.png": manifest["files"]["p0/mask.png"],
    }


def test_manifest_self_hash_rejects_manifest_metadata_change(tmp_path: Path) -> None:
    source = _source(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    manifest = build(source, output)
    manifest["chunks"][0]["size"] += 1
    assert manifest_sha256(manifest) != manifest["manifest_sha256"]
