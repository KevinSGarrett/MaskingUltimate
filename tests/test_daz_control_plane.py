from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from maskfactory.cli import main
from maskfactory.daz import (
    DazControlError,
    DazErrorCode,
    RegisteredRootResolver,
    append_event,
    build_event,
    find_prohibited_source_assets,
    initialize_daz_root,
    initialize_state_database,
    inspect_state_database,
    load_control_configuration,
    load_typed_daz_configuration,
    read_control_state,
    set_control_state,
)
from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "daz"
SCHEMAS = ROOT / "src" / "maskfactory" / "schemas"


def _config_for(tmp_path: Path) -> tuple[Path, Path]:
    config = tmp_path / "configs"
    shutil.copytree(CONFIG, config)
    daz_root = tmp_path / "DAZ Root"
    paths_file = config / "paths.yaml"
    paths = yaml.safe_load(paths_file.read_text(encoding="utf-8"))
    paths.update(
        {
            "root": str(daz_root),
            "root_identity": str(daz_root / "00_control" / "root_identity.json"),
            "acquisition_database": str(daz_root / "00_control" / "acquisition.sqlite3"),
            "state_database": str(daz_root / "10_queue" / "queue.sqlite"),
        }
    )
    paths_file.write_text(yaml.safe_dump(paths, sort_keys=False), encoding="utf-8")
    capacity_file = config / "acquisition_capacity.yaml"
    capacity = yaml.safe_load(capacity_file.read_text(encoding="utf-8"))
    capacity["root"] = str(daz_root)
    capacity_file.write_text(yaml.safe_dump(capacity, sort_keys=False), encoding="utf-8")
    return config, daz_root


def test_closed_schemas_compile_and_typed_loader_rejects_unknown_key(tmp_path: Path):
    configuration = load_typed_daz_configuration(CONFIG)
    assert configuration.paths.state_database == Path(r"F:\DAZ\10_queue\queue.sqlite")
    assert configuration.worker.default_disabled is True
    for name in (
        "paths",
        "operating_profile",
        "worker",
        "training_policy",
        "acquisition_capacity",
    ):
        schema = json.loads((SCHEMAS / f"daz_{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert validate_document(configuration.documents[name], f"daz_{name}") == ()

    config, _ = _config_for(tmp_path)
    worker_path = config / "worker.yaml"
    worker = yaml.safe_load(worker_path.read_text(encoding="utf-8"))
    worker["surprise"] = True
    worker_path.write_text(yaml.safe_dump(worker), encoding="utf-8")
    with pytest.raises(ValueError, match="Additional properties"):
        load_typed_daz_configuration(config)


def test_root_initializer_is_deterministic_and_registered_paths_fail_closed(tmp_path: Path):
    root = tmp_path / "DAZ Root"
    plan = initialize_daz_root(root, apply=False)
    assert plan["data"]["actions"]["create_root_identity"] is True
    assert plan["data"]["actions"]["create_directories"]
    applied = initialize_daz_root(root, apply=True)
    assert applied["code"] == 0
    replay = initialize_daz_root(root, apply=False)
    assert replay["data"]["actions"] == {
        "create_directories": [],
        "create_root_identity": False,
        "create_path_registry": False,
    }

    registry = root / "00_control" / "path_registry.json"
    resolver = RegisteredRootResolver.load(registry)
    assert (
        resolver.resolve("queue", "pending/job_1.json")
        == (root / "10_queue" / "pending" / "job_1.json").resolve()
    )
    for unsafe in (r"..\outside", r"C:\outside", r"\server\share"):
        with pytest.raises(DazControlError) as caught:
            resolver.resolve("queue", unsafe)
        assert caught.value.code == DazErrorCode.PATH_ESCAPE

    document = json.loads(registry.read_text(encoding="utf-8"))
    document["roots"]["escaped_root"] = "../outside"
    registry.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(DazControlError, match="escapes"):
        RegisteredRootResolver.load(registry).resolve("escaped_root", "file.json")


def test_state_migration_wal_integrity_and_append_only_events(tmp_path: Path):
    database = tmp_path / "queue" / "queue.sqlite"
    first = initialize_state_database(database)
    assert first["data"]["applied_migrations"] == [1, 2, 3, 4]
    assert first["data"]["passed"] is True
    second = initialize_state_database(database)
    assert second["data"]["applied_migrations"] == []
    assert inspect_state_database(database)["missing_tables"] == []

    event = build_event(
        "scan.started",
        "registry",
        "registry_fixture",
        {"snapshot": "pending"},
        event_id="evt_fixture",
        timestamp="2026-07-16T00:00:00Z",
    )
    append_event(database, event)
    with pytest.raises(DazControlError, match="event append failed"):
        append_event(database, event)
    invalid = dict(event)
    invalid["unknown"] = True
    with pytest.raises(DazControlError, match="closed event contract"):
        append_event(database, invalid)
    connection = sqlite3.connect(database)
    with pytest.raises(sqlite3.IntegrityError, match="DAZ_EVENTS_APPEND_ONLY"):
        connection.execute("DELETE FROM events WHERE event_id='evt_fixture'")
    connection.close()

    future = tmp_path / "future.sqlite"
    connection = sqlite3.connect(future)
    connection.execute("PRAGMA user_version=99")
    connection.close()
    with pytest.raises(DazControlError, match="newer than supported") as caught:
        initialize_state_database(future)
    assert caught.value.code == DazErrorCode.STATE_MIGRATION_FAILED


def test_control_state_is_atomic_default_disabled_and_storage_gated(tmp_path: Path):
    config_root, root = _config_for(tmp_path)
    initialize_daz_root(root, apply=True)
    configuration = load_control_configuration(config_root)
    assert read_control_state(configuration)["enabled"] is False
    with pytest.raises(DazControlError, match="soft floor") as caught:
        set_control_state(configuration, "enable", reason="fixture", apply=False, free_gib=149)
    assert caught.value.code == DazErrorCode.CONTROL_REFUSED

    enabled = set_control_state(
        configuration, "enable", reason="explicit fixture", apply=True, free_gib=200
    )
    assert enabled["data"]["after"]["enabled"] is True
    stopped = set_control_state(configuration, "stop", reason="fixture stop", apply=True)
    assert stopped["data"]["after"]["stop_requested"] is True
    assert read_control_state(configuration)["revision"] == 2


def test_source_asset_guard_detects_seeded_vendor_files_and_allows_tiny_fixture(tmp_path: Path):
    source = tmp_path / "incoming" / "person.duf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"vendor source")
    fixture = tmp_path / "tests" / "fixtures" / "daz" / "tiny.dsf"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"synthetic unit fixture")
    paths = [source.relative_to(tmp_path), fixture.relative_to(tmp_path), Path("docs/scene.md")]
    assert find_prohibited_source_assets(paths, workspace=tmp_path) == ("incoming/person.duf",)


def test_cli_json_contract_dry_run_migration_integrity_and_stable_error(tmp_path: Path):
    config_root, root = _config_for(tmp_path)
    runner = CliRunner()

    validated = runner.invoke(
        main, ["daz", "config", "validate", "--config-root", str(config_root)]
    )
    assert validated.exit_code == 0
    assert json.loads(validated.output)["reason"] == "configuration_valid"

    planned = runner.invoke(main, ["daz", "roots", "init", "--config-root", str(config_root)])
    assert planned.exit_code == 0
    assert json.loads(planned.output)["data"]["apply"] is False
    applied = runner.invoke(
        main, ["daz", "roots", "init", "--config-root", str(config_root), "--apply"]
    )
    assert applied.exit_code == 0 and root.is_dir()

    migrated = runner.invoke(
        main, ["daz", "state", "init", "--config-root", str(config_root), "--apply"]
    )
    assert migrated.exit_code == 0
    integrity = runner.invoke(
        main, ["daz", "state", "integrity", "--config-root", str(config_root)]
    )
    assert integrity.exit_code == 0
    assert json.loads(integrity.output)["data"]["passed"] is True

    stopped = runner.invoke(
        main,
        [
            "daz",
            "control",
            "stop",
            "--config-root",
            str(config_root),
            "--reason",
            "CLI fixture",
            "--apply",
        ],
    )
    assert stopped.exit_code == 0
    assert json.loads(stopped.output)["data"]["after"]["stop_requested"] is True

    escaped = runner.invoke(
        main,
        [
            "daz",
            "paths",
            "resolve",
            "queue",
            r"..\outside",
            "--config-root",
            str(config_root),
        ],
    )
    assert escaped.exit_code == int(DazErrorCode.PATH_ESCAPE)
    error = json.loads(escaped.output)
    assert error["code"] == int(DazErrorCode.PATH_ESCAPE)
    assert error["retryable"] is False

    worker_path = config_root / "worker.yaml"
    worker = yaml.safe_load(worker_path.read_text(encoding="utf-8"))
    worker["unknown_key"] = True
    worker_path.write_text(yaml.safe_dump(worker), encoding="utf-8")
    invalid_config = runner.invoke(
        main, ["daz", "config", "validate", "--config-root", str(config_root)]
    )
    assert invalid_config.exit_code == int(DazErrorCode.CONFIG_INVALID)
    assert json.loads(invalid_config.output)["code"] == int(DazErrorCode.CONFIG_INVALID)
