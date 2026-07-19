from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from maskfactory.cli import main
from maskfactory.daz.control import (
    DazControlError,
    initialize_daz_root,
    initialize_state_database,
    load_control_configuration,
)
from maskfactory.daz.recovery import (
    build_recovery_records_from_state,
    evaluate_recovery_matrix,
    load_recovery_policy,
    publish_recovery_matrix,
)
from maskfactory.daz.storage import register_retention_artifact

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs/daz/recovery.yaml"
SCHEMA = ROOT / "src/maskfactory/schemas/daz_recovery.schema.json"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
CONFIG = ROOT / "configs/daz"


def _fixture_configuration(tmp_path: Path):
    config = tmp_path / "configs"
    shutil.copytree(CONFIG, config)
    daz_root = tmp_path / "DAZ Root"
    paths_file = config / "paths.yaml"
    paths = yaml.safe_load(paths_file.read_text(encoding="utf-8"))
    paths.update(
        {
            "root": str(daz_root),
            "root_identity": str(daz_root / "00_control/root_identity.json"),
            "acquisition_database": str(daz_root / "00_control/acquisition.sqlite3"),
            "state_database": str(daz_root / "10_queue/queue.sqlite"),
        }
    )
    paths_file.write_text(yaml.safe_dump(paths, sort_keys=False), encoding="utf-8")
    capacity_file = config / "acquisition_capacity.yaml"
    capacity = yaml.safe_load(capacity_file.read_text(encoding="utf-8"))
    capacity["root"] = str(daz_root)
    capacity_file.write_text(yaml.safe_dump(capacity, sort_keys=False), encoding="utf-8")
    initialize_daz_root(daz_root, apply=True)
    configuration = load_control_configuration(config)
    initialize_state_database(configuration.paths.state_database)
    return config, configuration


def _record(artifact_id: str, tier: str, strategy: str, **extra):
    return {
        "artifact_id": artifact_id,
        "artifact_type": "generic",
        "tier": tier,
        "strategy": strategy,
        "referenced": False,
        "bytes": 10,
        "content_sha256": HASH_A,
        **extra,
    }


def test_recovery_policy_schema_is_closed() -> None:
    Draft202012Validator.check_schema(json.loads(SCHEMA.read_text(encoding="utf-8")))
    policy = load_recovery_policy(POLICY)
    assert tuple(policy.document["tiers"]) == ("A", "B", "C")


def test_complete_recovery_matrix_is_deterministic_and_accounts_bulk_bytes() -> None:
    policy = load_recovery_policy(POLICY)
    records = [
        _record("control", "A", "backup"),
        _record("accepted_map", "B", "backup", referenced=True),
        _record(
            "diagnostic",
            "C",
            "omit",
            source_sha256=HASH_B,
            rebuild_recipe_id="recipe_a",
            toolchain_sha256=HASH_C,
            bytes=30,
        ),
    ]
    first = evaluate_recovery_matrix(policy, records)
    second = evaluate_recovery_matrix(policy, list(reversed(records)))
    assert first == second
    assert first["recoverable"] is True
    assert first["backup_bytes"] == 20
    assert first["optional_bulk_bytes"] == 30


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        (_record("unknown", "D", "backup"), "unknown_tier"),
        (_record("tier_a_omit", "A", "omit"), "strategy_not_allowed_for_tier"),
        (
            _record("accepted", "B", "rebuild", referenced=True),
            "referenced_authority_requires_backup",
        ),
        (
            _record("package", "B", "backup", artifact_type="package_metadata"),
            "package_metadata_not_tier_a",
        ),
        (_record("bulk", "C", "omit"), "missing_source_sha256"),
    ],
)
def test_recovery_matrix_blocks_unrecoverable_or_misclassified_rows(record, reason: str) -> None:
    report = evaluate_recovery_matrix(load_recovery_policy(POLICY), [record])
    assert report["recoverable"] is False
    assert report["blockers"] == [{"artifact_id": record["artifact_id"], "reason": reason}]


def test_rebuild_requires_all_hash_bound_inputs() -> None:
    report = evaluate_recovery_matrix(
        load_recovery_policy(POLICY),
        [
            _record(
                "bulk",
                "C",
                "rebuild",
                source_sha256=HASH_B,
                rebuild_recipe_id="recipe_a",
                toolchain_sha256="short",
            )
        ],
    )
    assert report["blockers"][0]["reason"] == "missing_toolchain_sha256"


def test_duplicate_ids_and_invalid_bytes_fail_closed() -> None:
    policy = load_recovery_policy(POLICY)
    with pytest.raises(DazControlError, match="unique"):
        evaluate_recovery_matrix(policy, [_record("a", "A", "backup")] * 2)
    with pytest.raises(DazControlError, match="bytes invalid"):
        evaluate_recovery_matrix(policy, [_record("a", "A", "backup", bytes=-1)])


def test_state_builder_binds_file_bytes_package_metadata_and_dataset_reference(
    tmp_path: Path,
) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    permanent = configuration.paths.root / "00_control/permanent.json"
    permanent.write_bytes(b"permanent")
    register_retention_artifact(
        configuration,
        artifact_id="permanent",
        path=permanent,
        retention_class="R0",
        created_at=datetime(2026, 7, 19, tzinfo=UTC),
    )
    bulk = configuration.paths.root / "20_tmp/bulk.bin"
    bulk.write_bytes(b"bulk")
    register_retention_artifact(
        configuration,
        artifact_id="bulk",
        path=bulk,
        retention_class="R5",
        created_at=datetime(2026, 7, 19, tzinfo=UTC),
        payload={
            "recovery_strategy": "omit",
            "source_sha256": HASH_A,
            "rebuild_recipe_id": "rebuild_a",
            "toolchain_sha256": HASH_B,
        },
    )
    with sqlite3.connect(configuration.paths.state_database) as connection:
        connection.execute("INSERT INTO scene_recipes VALUES ('scene_a','family','ready','{}')")
        connection.execute(
            "INSERT INTO package_exports VALUES ('package_a','scene_a','accepted',?)",
            (json.dumps({"manifest_sha256": HASH_C}),),
        )
        connection.execute(
            "INSERT INTO dataset_membership VALUES ('dataset_a','package_a','train')"
        )
    records = build_recovery_records_from_state(configuration)
    assert [row["artifact_id"] for row in records] == [
        "package:package_a",
        "retention:bulk",
        "retention:permanent",
    ]
    package = records[0]
    assert package["artifact_type"] == "package_metadata"
    assert package["tier"] == "A" and package["strategy"] == "backup"
    assert package["referenced"] is True
    report = evaluate_recovery_matrix(load_recovery_policy(POLICY), records)
    assert report["recoverable"] is True


def test_state_builder_fails_when_registered_file_bytes_drift(tmp_path: Path) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    artifact = configuration.paths.root / "20_tmp/cache.bin"
    artifact.write_bytes(b"first")
    register_retention_artifact(
        configuration,
        artifact_id="cache",
        path=artifact,
        retention_class="R5",
        created_at=datetime(2026, 7, 19, tzinfo=UTC),
    )
    artifact.write_bytes(b"drift")
    with pytest.raises(DazControlError, match="bytes drifted"):
        build_recovery_records_from_state(configuration)


def test_state_builder_blocks_unregistered_package_directory_bytes(tmp_path: Path) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    package_file = configuration.paths.root / "14_scene_packages/legacy/package.duf"
    package_file.parent.mkdir(parents=True, exist_ok=True)
    package_file.write_bytes(b"legacy")
    records = build_recovery_records_from_state(configuration)
    assert len(records) == 1
    assert records[0]["artifact_type"] == "unregistered_package_file"
    report = evaluate_recovery_matrix(load_recovery_policy(POLICY), records)
    assert report["recoverable"] is False
    assert report["blockers"][0]["reason"] == "unknown_tier"


def test_state_builder_reports_required_schema_migration_without_writing(tmp_path: Path) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    with sqlite3.connect(configuration.paths.state_database) as connection:
        connection.execute("PRAGMA user_version=2")
    before = configuration.paths.state_database.read_bytes()
    with pytest.raises(DazControlError, match="schema 2 requires migration to 4"):
        build_recovery_records_from_state(configuration)
    assert configuration.paths.state_database.read_bytes() == before


def test_recovery_matrix_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    matrix = evaluate_recovery_matrix(
        load_recovery_policy(POLICY), [_record("control", "A", "backup")]
    )
    output = tmp_path / "matrix.json"
    first = publish_recovery_matrix(matrix, output)
    second = publish_recovery_matrix(matrix, output)
    assert first["published"] is True and second["published"] is False
    assert first["matrix_sha256"] == second["matrix_sha256"]
    output.write_text("{}\n", encoding="utf-8")
    with pytest.raises(DazControlError, match="already exists with drift"):
        publish_recovery_matrix(matrix, output)


def test_recovery_cli_is_dry_run_default_and_publishes_only_with_apply(tmp_path: Path) -> None:
    records = tmp_path / "records.json"
    records.write_text(json.dumps([_record("control", "A", "backup")]), encoding="utf-8")
    output = tmp_path / "matrix.json"
    base = [
        "daz",
        "recovery",
        "matrix",
        "--policy",
        str(POLICY),
        "--records",
        str(records),
        "--output",
        str(output),
    ]
    runner = CliRunner()
    planned = runner.invoke(main, base)
    assert planned.exit_code == 0, planned.output
    assert json.loads(planned.output)["reason"] == "recovery_matrix_passed"
    assert not output.exists()
    published = runner.invoke(main, [*base, "--apply"])
    assert published.exit_code == 0, published.output
    document = json.loads(published.output)
    assert document["data"]["publication"]["published"] is True
    assert output.is_file()
    repeated = runner.invoke(main, [*base, "--apply"])
    assert repeated.exit_code == 0, repeated.output
    assert json.loads(repeated.output)["data"]["publication"]["published"] is False


def test_recovery_cli_returns_stable_blocked_exit_for_incomplete_bulk(tmp_path: Path) -> None:
    records = tmp_path / "records.json"
    records.write_text(json.dumps([_record("bulk", "C", "omit")]), encoding="utf-8")
    result = CliRunner().invoke(
        main,
        [
            "daz",
            "recovery",
            "matrix",
            "--policy",
            str(POLICY),
            "--records",
            str(records),
        ],
    )
    assert result.exit_code == 77
    document = json.loads(result.output)
    assert document["reason"] == "recovery_matrix_blocked"
    assert document["data"]["matrix"]["blockers"][0]["reason"] == "missing_source_sha256"
