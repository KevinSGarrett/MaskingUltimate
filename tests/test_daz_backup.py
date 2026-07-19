from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from maskfactory.cli import main
from maskfactory.daz.backup import (
    create_tier_a_backup,
    load_tier_a_backup_policy,
    plan_tier_a_backup,
    restore_tier_a_test,
    verify_tier_a_backup,
)
from maskfactory.daz.control import DazControlError
from maskfactory.daz.recovery import (
    evaluate_recovery_matrix,
    load_recovery_policy,
    publish_recovery_matrix,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "daz" / "backup.yaml"
SCHEMA = ROOT / "src" / "maskfactory" / "schemas" / "daz_backup.schema.json"
CONFIG = ROOT / "configs" / "daz"
RECOVERY_POLICY = CONFIG / "recovery.yaml"
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
        connection.execute("PRAGMA journal_mode=WAL")
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
        "queue",
    )
    assert tuple(policy.conditional_categories) == (
        "recipe",
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
    assert not (backup / "payload/10_queue/queue.sqlite-wal").exists()
    assert not (backup / "payload/10_queue/queue.sqlite-shm").exists()
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


def test_preactivation_backup_records_missing_conditional_categories_without_claiming_activation(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    policy = load_tier_a_backup_policy(POLICY)
    for relative in (
        "09_generation/scene_recipes/recipe.json",
        "14_scene_packages/accepted/package.json",
        "15_datasets/manifests/lineage.json",
    ):
        (source / relative).unlink()
    plan = plan_tier_a_backup(source, tmp_path / "backups", policy, backup_id="preactivation")
    assert plan["activation_complete"] is False
    assert plan["category_presence"]["control"] is True
    assert plan["category_presence"]["recipe"] is False
    manifest = create_tier_a_backup(source, tmp_path / "backups", policy, backup_id="preactivation")
    verification = verify_tier_a_backup(Path(manifest["backup_path"]), policy)
    assert verification["passed"] is True
    assert verification["activation_complete"] is False


def test_backup_cli_is_dry_run_default_then_create_verify_and_restore(tmp_path: Path) -> None:
    source = _source(tmp_path)
    destination = tmp_path / "backups"
    recovery_matrix = tmp_path / "recovery_matrix.json"
    matrix = evaluate_recovery_matrix(
        load_recovery_policy(RECOVERY_POLICY),
        [
            {
                "artifact_id": "control",
                "artifact_type": "package_metadata",
                "tier": "A",
                "strategy": "backup",
                "referenced": True,
                "bytes": 10,
                "content_sha256": "a" * 64,
            }
        ],
    )
    publish_recovery_matrix(matrix, recovery_matrix)
    runner = CliRunner()
    base = [
        "daz",
        "backup",
        "create",
        "--config-root",
        str(CONFIG),
        "--policy",
        str(POLICY),
        "--source-root",
        str(source),
        "--destination-root",
        str(destination),
        "--backup-id",
        "backup_cli_a",
        "--recovery-matrix",
        str(recovery_matrix),
    ]
    planned = runner.invoke(main, base)
    assert planned.exit_code == 0, planned.output
    assert json.loads(planned.output)["reason"] == "tier_a_backup_plan"
    assert not destination.exists()

    created = runner.invoke(main, [*base, "--apply"])
    assert created.exit_code == 0, created.output
    backup = destination / "backup_cli_a"
    assert backup.is_dir()
    verified = runner.invoke(
        main,
        [
            "daz",
            "backup",
            "verify",
            str(backup),
            "--policy",
            str(POLICY),
            "--recovery-matrix",
            str(recovery_matrix),
        ],
    )
    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.output)["data"]["passed"] is True

    target = tmp_path / "restore"
    restore_base = [
        "daz",
        "backup",
        "restore-test",
        str(backup),
        "--target",
        str(target),
        "--policy",
        str(POLICY),
        "--recovery-matrix",
        str(recovery_matrix),
    ]
    restore_plan = runner.invoke(main, restore_base)
    assert restore_plan.exit_code == 0, restore_plan.output
    assert json.loads(restore_plan.output)["reason"] == "tier_a_restore_test_plan"
    assert not target.exists()
    restored = runner.invoke(main, [*restore_base, "--apply"])
    assert restored.exit_code == 0, restored.output
    document = json.loads(restored.output)
    assert document["reason"] == "tier_a_restore_test_passed"
    assert document["data"]["restore"]["passed"] is True
    assert document["data"]["restore"]["recovery_matrix_sha256"] == matrix["matrix_sha256"]


def test_backup_verification_rejects_wrong_recovery_matrix_binding(tmp_path: Path) -> None:
    source = _source(tmp_path)
    policy = load_tier_a_backup_policy(POLICY)
    manifest = create_tier_a_backup(
        source,
        tmp_path / "backups",
        policy,
        backup_id="backup_fixture_a",
        recovery_matrix_sha256="a" * 64,
    )
    with pytest.raises(DazControlError, match="binding mismatch"):
        verify_tier_a_backup(
            Path(manifest["backup_path"]),
            policy,
            expected_recovery_matrix_sha256="b" * 64,
        )


def test_backup_cli_rejects_nonempty_restore_without_overwriting(tmp_path: Path) -> None:
    source = _source(tmp_path)
    policy = load_tier_a_backup_policy(POLICY)
    manifest = create_tier_a_backup(
        source, tmp_path / "backups", policy, backup_id="backup_fixture_a"
    )
    target = tmp_path / "restore"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("preserve", encoding="utf-8")
    result = CliRunner().invoke(
        main,
        [
            "daz",
            "backup",
            "restore-test",
            manifest["backup_path"],
            "--target",
            str(target),
            "--policy",
            str(POLICY),
            "--apply",
        ],
    )
    assert result.exit_code == 77
    assert json.loads(result.output)["reason"] == "restore target is not empty"
    assert marker.read_text(encoding="utf-8") == "preserve"
