from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.assets import (
    AssetIdentityError,
    ContentRoot,
    build_asset_identity_snapshot,
    diff_asset_identity_snapshots,
    publish_asset_identity_snapshot,
    resume_asset_identity_index,
    scan_inventory_chunk,
)


def _roots(tmp_path: Path) -> tuple[ContentRoot, ...]:
    primary = tmp_path / "primary"
    user = tmp_path / "user"
    primary.mkdir()
    user.mkdir()
    return (
        ContentRoot("content_primary", primary, 10, "governed"),
        ContentRoot("content_user", user, 20, "governed"),
    )


def _finish_inventory(state: Path, roots: tuple[ContentRoot, ...]) -> None:
    for _ in range(50):
        result = scan_inventory_chunk(state, roots, max_entries=10_000, max_seconds=10)
        if result.complete:
            return
    raise AssertionError("inventory did not complete")


def _finish_identity(inventory: Path, identity: Path, roots: tuple[ContentRoot, ...]) -> None:
    for _ in range(50):
        result = resume_asset_identity_index(
            inventory,
            identity,
            roots,
            max_files=1,
            max_bytes=1024**2,
            max_seconds=10,
        )
        if result.complete:
            return
    raise AssertionError("identity hashing did not complete")


def test_identity_hashing_is_bounded_and_resolves_duplicates_and_shadows(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    (roots[0].path / "same.duf").write_bytes(b"identical")
    (roots[1].path / "same.duf").write_bytes(b"identical")
    (roots[0].path / "shadow.duf").write_bytes(b"primary")
    (roots[1].path / "shadow.duf").write_bytes(b"different")
    (roots[0].path / "moved-a.duf").write_bytes(b"content-duplicate")
    (roots[1].path / "moved-b.duf").write_bytes(b"content-duplicate")
    inventory = tmp_path / "inventory.sqlite"
    identity = tmp_path / "identity.sqlite"
    _finish_inventory(inventory, roots)

    first = resume_asset_identity_index(
        inventory,
        identity,
        roots,
        max_files=1,
        max_bytes=1024**2,
        max_seconds=10,
    )
    assert first.hashed_this_chunk == 1
    assert first.pending_files == 5
    assert first.complete is False
    _finish_identity(inventory, identity, roots)
    snapshot = build_asset_identity_snapshot(inventory, identity, roots)
    assert snapshot["summary"] == {
        "file_count": 6,
        "byte_count": sum(
            path.stat().st_size for root in roots for path in root.path.glob("*.duf")
        ),
        "unique_logical_assets": 3,
        "duplicate_copies": 1,
        "shadow_conflict_files": 2,
        "logical_conflict_count": 1,
        "content_duplicate_group_count": 1,
        "complete": True,
    }
    by_path = {}
    for row in snapshot["files"]:
        by_path[(row["root_id"], row["canonical_path"])] = row
    assert by_path[("content_primary", "same.duf")]["logical_status"] == "duplicate_winner"
    assert by_path[("content_primary", "same.duf")]["eligible"] is True
    assert by_path[("content_user", "same.duf")]["logical_status"] == "duplicate_copy"
    assert by_path[("content_user", "same.duf")]["eligible"] is False
    assert {
        row["logical_status"] for row in snapshot["files"] if row["canonical_path"] == "shadow.duf"
    } == {"shadow_conflict"}
    assert snapshot["logical_conflicts"][0]["resolution"] == (
        "explicit_technical_resolution_required"
    )
    assert len(snapshot["content_duplicate_groups"][0]["asset_ids"]) == 2

    target, created = publish_asset_identity_snapshot(snapshot, tmp_path / "snapshots")
    assert created is True
    assert publish_asset_identity_snapshot(snapshot, tmp_path / "snapshots") == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(AssetIdentityError, match="immutable_conflict"):
        publish_asset_identity_snapshot(snapshot, tmp_path / "snapshots")


def test_changed_hash_is_invalidated_and_snapshot_diff_detects_change_and_move(
    tmp_path: Path,
) -> None:
    roots = _roots(tmp_path)
    changing = roots[0].path / "changing.duf"
    moving = roots[0].path / "old-name.duf"
    changing.write_bytes(b"before")
    moving.write_bytes(b"move-me")
    inventory = tmp_path / "inventory.sqlite"
    identity = tmp_path / "identity.sqlite"
    _finish_inventory(inventory, roots)
    _finish_identity(inventory, identity, roots)
    previous = build_asset_identity_snapshot(inventory, identity, roots)

    changing.write_bytes(b"after-with-new-size")
    moving.rename(roots[0].path / "new-name.duf")
    drift = scan_inventory_chunk(inventory, roots, max_entries=10_000, max_seconds=10)
    assert drift.complete is False
    _finish_inventory(inventory, roots)
    _finish_identity(inventory, identity, roots)
    current = build_asset_identity_snapshot(inventory, identity, roots)
    difference = diff_asset_identity_snapshots(previous, current)
    assert len(difference["content_changed"]) == 1
    assert difference["content_changed"][0]["canonical_path"] == "changing.duf"
    assert difference["moves"] == [
        {
            "sha256": next(
                row["sha256"] for row in current["files"] if row["canonical_path"] == "new-name.duf"
            ),
            "from": {"root_id": "content_primary", "canonical_path": "old-name.duf"},
            "to": {"root_id": "content_primary", "canonical_path": "new-name.duf"},
        }
    ]
    assert difference["added"] == []
    assert difference["removed"] == []
    assert len(difference["diff_sha256"]) == 64


def test_identity_snapshot_refuses_pending_hashes_and_cli_resumes(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    (roots[0].path / "one.duf").write_bytes(b"one")
    (roots[0].path / "two.duf").write_bytes(b"two")
    inventory = tmp_path / "inventory.sqlite"
    identity = tmp_path / "identity.sqlite"
    _finish_inventory(inventory, roots)
    resume_asset_identity_index(
        inventory,
        identity,
        roots,
        max_files=1,
        max_bytes=1024**2,
        max_seconds=10,
    )
    with pytest.raises(AssetIdentityError, match="identity_index_incomplete"):
        build_asset_identity_snapshot(inventory, identity, roots)

    runner = CliRunner()
    invocation = runner.invoke(
        main,
        [
            "daz",
            "assets",
            "identity-index",
            "--root",
            f"content_primary={roots[0].path}",
            "--root",
            f"content_user={roots[1].path}",
            "--inventory-state",
            str(inventory),
            "--state",
            str(identity),
            "--max-files",
            "10",
            "--max-bytes",
            str(1024**2),
            "--max-seconds",
            "10",
            "--finalize",
            "--output",
            str(tmp_path / "published"),
        ],
    )
    assert invocation.exit_code == 0, invocation.output
    report = json.loads(invocation.output)
    assert report["reason"] == "asset_identity_index_complete"
    assert report["data"]["summary"]["complete"] is True
    assert report["data"]["publication"]["summary"]["file_count"] == 2
