from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.assets.acquisition_manifest import (
    AcquisitionManifestError,
    build_acquisition_manifest_index,
    reconcile_acquisition_with_inventory,
    resume_acquisition_manifest_index,
)
from maskfactory.daz.assets.filesystem_inventory import (
    ContentRoot,
    FilesystemInventoryError,
    build_inventory_snapshot,
    canonicalize_relative_path,
    initialize_inventory_state,
    inventory_state_summary,
    publish_inventory_snapshot,
    scan_inventory_chunk,
)


def _roots(tmp_path: Path) -> tuple[ContentRoot, ...]:
    primary = tmp_path / "primary"
    user = tmp_path / "user"
    primary.mkdir()
    user.mkdir()
    return (
        ContentRoot("content_primary", primary, 10, "governed"),
        ContentRoot("content_user", user, 20, "governed_user"),
    )


def _finish(state: Path, roots: tuple[ContentRoot, ...]) -> None:
    for _ in range(20):
        result = scan_inventory_chunk(state, roots, max_entries=1, max_seconds=10)
        if result.complete:
            return
    raise AssertionError("scan did not complete")


def test_canonical_logical_uri_is_unambiguous_and_traversal_fails() -> None:
    display, canonical, uri = canonicalize_relative_path(r"People\Genesis 9\A #1.duf")
    assert display == "People/Genesis 9/A #1.duf"
    assert canonical == "people/genesis 9/a #1.duf"
    assert uri == "/People/Genesis%209/A%20%231.duf"
    for unsafe in ("", "../escape.duf", "/absolute.duf", r"C:\escape.duf"):
        with pytest.raises(FilesystemInventoryError):
            canonicalize_relative_path(unsafe)


def test_resumable_scan_is_deterministic_and_never_hashes_content(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    (roots[0].path / "People" / "Genesis 9").mkdir(parents=True)
    (roots[0].path / "People" / "Genesis 9" / "Pose One.duf").write_bytes(b"not-hashed")
    (roots[0].path / "Runtime").mkdir()
    (roots[0].path / "Runtime" / "texture.jpg").write_bytes(b"pixels")
    state_a = tmp_path / "a.sqlite"
    _finish(state_a, roots)
    summary = inventory_state_summary(state_a)
    assert summary["complete"] is True
    assert summary["file_count"] == 2
    assert summary["user_facing_file_count"] == 1
    first = build_inventory_snapshot(state_a, roots=roots)

    state_b = tmp_path / "b.sqlite"
    _finish(state_b, roots)
    second = build_inventory_snapshot(state_b, roots=roots)
    assert first == second
    assert set(first["files"][0]) == {
        "root_id",
        "relative_path",
        "canonical_path",
        "logical_uri",
        "size_bytes",
        "mtime_ns",
        "file_id",
        "extension",
        "user_facing",
    }
    assert "sha256" not in first["files"][0]


def test_incomplete_inventory_cannot_publish_and_root_drift_fails(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    state = tmp_path / "state.sqlite"
    initialize_inventory_state(state, roots)
    with pytest.raises(FilesystemInventoryError, match="inventory_incomplete"):
        build_inventory_snapshot(state, roots=roots)
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    changed = (ContentRoot("content_primary", replacement, 10, "governed"), roots[1])
    with pytest.raises(FilesystemInventoryError, match="inventory_roots_changed"):
        initialize_inventory_state(state, changed)


def test_completed_scan_requeues_directory_drift_and_reconciles_deletes(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    directory = roots[0].path / "People"
    directory.mkdir()
    first = directory / "first.duf"
    first.write_text("{}", encoding="utf-8")
    state = tmp_path / "state.sqlite"
    _finish(state, roots)
    first.unlink()
    second = directory / "second.duf"
    second.write_text("{}", encoding="utf-8")
    drift = scan_inventory_chunk(state, roots, max_entries=100, max_seconds=10)
    assert drift.complete is False
    _finish(state, roots)
    snapshot = build_inventory_snapshot(state, roots=roots)
    paths = {item["relative_path"] for item in snapshot["files"]}
    assert "People/first.duf" not in paths
    assert "People/second.duf" in paths


def test_snapshot_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    (roots[0].path / "asset.duf").write_text("{}", encoding="utf-8")
    state = tmp_path / "state.sqlite"
    _finish(state, roots)
    snapshot = build_inventory_snapshot(state, roots=roots)
    target, published = publish_inventory_snapshot(snapshot, tmp_path / "snapshots")
    assert published is True
    assert json.loads(target.read_text(encoding="utf-8"))["snapshot_id"] == snapshot["snapshot_id"]
    assert publish_inventory_snapshot(snapshot, tmp_path / "snapshots") == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(FilesystemInventoryError, match="snapshot_immutable_conflict"):
        publish_inventory_snapshot(snapshot, tmp_path / "snapshots")


def _manifest(manifest_id: str, file_id: str, sha256: str, relative: str) -> dict[str, object]:
    product_id = "prd_" + "1" * 24
    package_id = "pkg_" + manifest_id.removeprefix("mfst_")
    return {
        "schema_version": "1.0.0",
        "manifest_id": manifest_id,
        "product": {"product_id": product_id},
        "packages": [{"package_id": package_id}],
        "files": [
            {
                "file_id": file_id,
                "package_id": package_id,
                "content_root_id": "mf_daz_library",
                "installed_relative_path": relative,
                "sha256": sha256,
                "size_bytes": 7,
            }
        ],
    }


def test_autonomous_manifest_index_is_separate_and_reconciles_paths(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    relative = "People/Genesis 9/asset.duf"
    installed = roots[0].path / Path(relative)
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"1234567")
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    record = _manifest("mfst_" + "a" * 24, "fil_" + "b" * 24, "c" * 64, relative)
    (manifests / "one.yaml").write_text(yaml.safe_dump(record), encoding="utf-8")
    index = tmp_path / "acquisition.sqlite"
    first = build_acquisition_manifest_index(manifests, index)
    second = build_acquisition_manifest_index(manifests, index)
    assert first.source_fingerprint == second.source_fingerprint
    assert first.manifest_count == 1
    assert first.file_occurrence_count == 1

    state = tmp_path / "inventory.sqlite"
    _finish(state, roots)
    comparison = reconcile_acquisition_with_inventory(index, state)
    assert comparison == {
        "inventory_complete": True,
        "present_manifest_occurrences": 1,
        "missing_manifest_occurrences": 0,
        "unmanifested_files": 0,
        "size_mismatches": 0,
        "out_of_scope_manifest_occurrences": 0,
    }


def test_autonomous_manifest_index_resumes_in_bounded_chunks(tmp_path: Path) -> None:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    for index, token in enumerate(("a", "d")):
        record = _manifest(
            "mfst_" + token * 24,
            "fil_" + chr(ord(token) + 1) * 24,
            chr(ord(token) + 2) * 64,
            f"asset_{index}.duf",
        )
        (manifests / f"{index}.yaml").write_text(yaml.safe_dump(record), encoding="utf-8")
    output = tmp_path / "resume.sqlite"
    first = resume_acquisition_manifest_index(manifests, output, max_manifests=1)
    assert first.indexed_this_chunk == 1
    assert first.pending_manifest_count == 1
    assert first.complete is False
    second = resume_acquisition_manifest_index(manifests, output, max_manifests=1)
    assert second.indexed_manifest_count == 2
    assert second.pending_manifest_count == 0
    assert second.complete is True
    assert second.source_fingerprint is not None


def test_autonomous_manifest_refuses_traversal_and_preserves_unknown_roots(tmp_path: Path) -> None:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    record = _manifest("mfst_" + "a" * 24, "fil_" + "b" * 24, "c" * 64, "../escape.duf")
    (manifests / "bad.yaml").write_text(yaml.safe_dump(record), encoding="utf-8")
    with pytest.raises((AcquisitionManifestError, FilesystemInventoryError)):
        build_acquisition_manifest_index(manifests, tmp_path / "index.sqlite")
    record = _manifest("mfst_" + "d" * 24, "fil_" + "e" * 24, "f" * 64, "asset.duf")
    record["files"][0]["content_root_id"] = "other_original_library"
    (manifests / "bad.yaml").write_text(yaml.safe_dump(record), encoding="utf-8")
    summary = build_acquisition_manifest_index(manifests, tmp_path / "index.sqlite")
    assert summary.unregistered_source_root_count == 1


def test_filesystem_and_acquisition_cli_round_trip(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    (roots[0].path / "asset.duf").write_bytes(b"1234567")
    state = tmp_path / "inventory.sqlite"
    runner = CliRunner()
    invocation = runner.invoke(
        main,
        [
            "daz",
            "assets",
            "filesystem-scan",
            "--root",
            f"content_primary={roots[0].path}",
            "--root",
            f"content_user={roots[1].path}",
            "--state",
            str(state),
            "--max-entries",
            "100",
            "--max-seconds",
            "10",
        ],
    )
    assert invocation.exit_code == 0, invocation.output
    assert json.loads(invocation.output)["data"]["summary"]["complete"] is True

    manifests = tmp_path / "manifests"
    manifests.mkdir()
    record = _manifest("mfst_" + "a" * 24, "fil_" + "b" * 24, "c" * 64, "asset.duf")
    (manifests / "one.yaml").write_text(yaml.safe_dump(record), encoding="utf-8")
    index = tmp_path / "acquisition.sqlite"
    indexed = runner.invoke(
        main,
        [
            "daz",
            "assets",
            "acquisition-index",
            "--source",
            str(manifests),
            "--output",
            str(index),
            "--inventory-state",
            str(state),
        ],
    )
    assert indexed.exit_code == 0, indexed.output
    payload = json.loads(indexed.output)
    assert payload["data"]["progress"]["indexed_manifest_count"] == 1
    assert payload["data"]["filesystem_comparison"]["present_manifest_occurrences"] == 1
