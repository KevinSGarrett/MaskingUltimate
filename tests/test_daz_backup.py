from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.daz.backup import (
    create_tier_a_backup,
    load_tier_a_backup_policy,
    restore_tier_a_test,
    verify_tier_a_backup,
)
from maskfactory.daz.control import DazControlError

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "daz" / "backup.yaml"
SCHEMA = ROOT / "src" / "maskfactory" / "schemas" / "daz_backup.schema.json"
CAPTURED = datetime(2026, 7, 19, 5, 15, tzinfo=UTC)


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    files = {
        "00_control/root_identity.json": b"control",
        "04_runtime/runtime_snapshots/runtime.json": b"runtime",
        "05_registry/snapshots/registry.json": b"registry",
        "07_mappings/genesis9/map.json": b"mapping",
        "09_generation/scene_recipes/recipe.json": b"recipe",
        "14_scene_packages/accepted/package.json": b"package",
        "15_datasets/manifests/lineage.json": b"lineage",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    queue = root / "10_queue" / "queue.sqlite"
    queue.parent.mkdir(parents=True)
    with sqlite3.connect(queue) as connection:
        connection.execute("CREATE TABLE events(id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        connection.execute("INSERT INTO events VALUES ('event_a','immutable')")
    return root


def test_backup_schema_and_closed_tier_a_policy() -> None:
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))
    policy = load_tier_a_backup_policy(POLICY)
    assert policy.document["tier"] == "A"
    assert tuple(policy.required_categories) == (
        "control",
        "registry",
        "mapping",
        "recipe",
        "queue",
        "package_metadata",
        "dataset_model_lineage",
    )


def test_create_verify_and_clean_root_restore_preserve_exact_bytes(tmp_path: Path) -> None:
    source = _source(tmp_path)
    policy = load_tier_a_backup_policy(POLICY)
    manifest = create_tier_a_backup(
        source,
        tmp_path / "backups",
        policy,
        backup_id="backup_fixture_a",
        captured_at=CAPTURED,
    )
    backup = Path(manifest["backup_path"])
    verification = verify_tier_a_backup(backup, policy)
    assert verification["passed"] is True
    assert verification["queue_integrity"] == "ok"
    assert all(verification["category_presence"].values())
    restored = restore_tier_a_test(backup, tmp_path / "restore", policy)
    assert restored["passed"] is True
    assert restored["queue_integrity"] == "ok"
    assert restored["semantic_replay_executed"] is False
    assert restored["lineage_query_executed"] is False
    assert (tmp_path / "restore/07_mappings/genesis9/map.json").read_bytes() == b"mapping"


def test_payload_tamper_fails_hash_verification(tmp_path: Path) -> None:
    source = _source(tmp_path)
    policy = load_tier_a_backup_policy(POLICY)
    manifest = create_tier_a_backup(
        source, tmp_path / "backups", policy, backup_id="backup_fixture_a"
    )
    backup = Path(manifest["backup_path"])
    (backup / "payload/07_mappings/genesis9/map.json").write_bytes(b"tampered")
    with pytest.raises(DazControlError, match="hash mismatch"):
        verify_tier_a_backup(backup, policy)


def test_manifest_tamper_and_nonempty_restore_fail_closed(tmp_path: Path) -> None:
    source = _source(tmp_path)
    policy = load_tier_a_backup_policy(POLICY)
    manifest = create_tier_a_backup(
        source, tmp_path / "backups", policy, backup_id="backup_fixture_a"
    )
    backup = Path(manifest["backup_path"])
    manifest_path = backup / "manifest.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["captured_at"] = "2026-01-01T00:00:00Z"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(DazControlError, match="seal mismatch"):
        verify_tier_a_backup(backup, policy)

    clean_manifest = create_tier_a_backup(
        source, tmp_path / "backups", policy, backup_id="backup_fixture_b"
    )
    target = tmp_path / "restore"
    target.mkdir()
    (target / "existing.txt").write_text("do not overwrite", encoding="utf-8")
    with pytest.raises(DazControlError, match="not empty"):
        restore_tier_a_test(Path(clean_manifest["backup_path"]), target, policy)


def test_backup_destination_inside_source_and_missing_category_are_refused(tmp_path: Path) -> None:
    source = _source(tmp_path)
    policy = load_tier_a_backup_policy(POLICY)
    with pytest.raises(DazControlError, match="inside protected root"):
        create_tier_a_backup(source, source / "21_backups", policy, backup_id="unsafe")
    (source / "07_mappings/genesis9/map.json").unlink()
    with pytest.raises(DazControlError, match="missing required categories: mapping"):
        create_tier_a_backup(source, tmp_path / "backups", policy, backup_id="missing")
