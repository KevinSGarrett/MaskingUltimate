from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maskfactory.cli import main  # noqa: E402
from maskfactory.daz import (  # noqa: E402
    DazControlError,
    ingest_adapted_scene,
    initialize_state_database,
    query_descendants,
    register_downstream_artifact,
    revoke_lineage,
)
from maskfactory.daz.control import MIGRATION_1, MIGRATION_2  # noqa: E402
from maskfactory.daz.package_qc import (  # noqa: E402
    load_adapted_package_qc_policy,
    run_adapted_package_qc,
)
from maskfactory.daz.s00_adapter import adapt_accepted_scene  # noqa: E402
from test_daz_s00_adapter import _fixture as _adapter_fixture  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
QC_POLICY = ROOT / "configs" / "daz" / "adapted_package_qc.yaml"
ONTOLOGY = ROOT / "configs" / "ontology.yaml"
TS = "2026-07-17T04:00:00Z"


def _fixture(tmp_path: Path, owner_count: int = 2):
    adapter_inputs = _adapter_fixture(tmp_path / "adapter", owner_count)
    adapter_report, adapted_root, _published = adapt_accepted_scene(**adapter_inputs)
    qa_report, _qa_path, _qa_published = run_adapted_package_qc(
        adapted_root,
        adapter_report,
        adapter_inputs["package_contract"],
        policy=load_adapted_package_qc_policy(QC_POLICY),
        ontology_source=ONTOLOGY,
        output_root=tmp_path / "qa",
    )
    database = tmp_path / "queue.sqlite"
    initialize_state_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO scene_recipes VALUES (?,?,?,?)",
            (
                adapter_report["scene_id"],
                adapter_report["scene_family_id"],
                "accepted",
                "{}",
            ),
        )
        connection.execute(
            "INSERT INTO scene_certificates VALUES (?,?,?,?)",
            (
                adapter_report["certificate_id"],
                adapter_report["scene_id"],
                "accepted",
                "{}",
            ),
        )
    return database, adapted_root, adapter_report, qa_report, adapter_inputs["package_contract"]


def _ingest(fixture):
    database, adapted_root, adapter_report, qa_report, _contract = fixture
    return ingest_adapted_scene(database, adapted_root, adapter_report, qa_report, timestamp=TS)


def test_v2_database_migrates_to_v3_without_losing_existing_rows(tmp_path: Path) -> None:
    database = tmp_path / "legacy_v2.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(MIGRATION_1)
        connection.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (1, "initial", TS))
        connection.execute(
            "INSERT INTO scene_recipes VALUES (?,?,?,?)",
            ("daz_scene_preserved", "daz_family_preserved", "accepted", "{}"),
        )
        connection.commit()
        connection.executescript(MIGRATION_2)
        connection.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (2, "events", TS))
        connection.execute("PRAGMA user_version=2")
        connection.commit()
    report = initialize_state_database(database)
    assert report["data"]["source_version"] == 2
    assert report["data"]["applied_migrations"] == [3]
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert connection.execute("SELECT scene_id FROM scene_recipes").fetchone()[0] == (
            "daz_scene_preserved"
        )


@pytest.mark.parametrize("owner_count", [1, 2, 3, 4])
def test_ingest_registers_exact_scene_packages_and_authorities_transactionally(
    tmp_path: Path, owner_count: int
) -> None:
    fixture = _fixture(tmp_path, owner_count)
    record = _ingest(fixture)
    replay = _ingest(fixture)
    assert replay == record
    assert len(record["package_ids"]) == owner_count
    database = fixture[0]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ingest_records").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM package_exports").fetchone()[0] == owner_count
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM package_exports WHERE state='ingested'"
            ).fetchone()[0]
            == owner_count
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM events WHERE event_type='package.ingested'"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_ingest_rejects_failed_qa_post_qa_tamper_and_missing_control_authority(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "failed")
    package = fixture[1] / "packages" / "p0" / "qa_report.json"
    package.write_bytes(package.read_bytes() + b" ")
    failed_qa, _path, _published = run_adapted_package_qc(
        fixture[1],
        fixture[2],
        fixture[4],
        policy=load_adapted_package_qc_policy(QC_POLICY),
        ontology_source=ONTOLOGY,
        output_root=tmp_path / "failed_qa",
    )
    with pytest.raises(DazControlError, match="passing adapted-package QA"):
        ingest_adapted_scene(fixture[0], fixture[1], fixture[2], failed_qa, timestamp=TS)

    fixture = _fixture(tmp_path / "post_qa")
    package = fixture[1] / "packages" / "p0" / "source_manifest.json"
    package.write_bytes(package.read_bytes() + b" ")
    with pytest.raises(DazControlError, match="changed after QA"):
        _ingest(fixture)

    fixture = _fixture(tmp_path / "missing_file")
    (fixture[1] / "packages" / "p0" / "full_body.png").unlink()
    with pytest.raises(DazControlError, match="changed after QA"):
        _ingest(fixture)

    fixture = _fixture(tmp_path / "authority")
    with sqlite3.connect(fixture[0]) as connection:
        connection.execute("UPDATE scene_certificates SET status='revoked'")
    with pytest.raises(DazControlError, match="lacks accepted scene/certificate"):
        _ingest(fixture)
    with sqlite3.connect(fixture[0]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ingest_records").fetchone()[0] == 0


def test_descendant_query_and_mapping_revocation_reach_datasets_runs_and_models(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    record = _ingest(fixture)
    database = fixture[0]
    packages = [("package", package_id) for package_id in record["package_ids"]]
    register_downstream_artifact(
        database,
        "dataset_snapshot",
        "dataset_fixture",
        "d" * 64,
        packages,
        {"split": "train"},
        timestamp=TS,
    )
    register_downstream_artifact(
        database,
        "training_run",
        "run_fixture",
        "e" * 64,
        [("dataset_snapshot", "dataset_fixture")],
        {"status": "complete"},
        timestamp=TS,
    )
    register_downstream_artifact(
        database,
        "model",
        "model_fixture",
        "f" * 64,
        [("training_run", "run_fixture")],
        {"role": "challenger"},
        timestamp=TS,
    )
    manifest = json.loads(
        (fixture[1] / "packages" / "p0" / "manifest.json").read_text(encoding="utf-8")
    )
    mapping_sha = manifest["synthetic_lineage"]["mapping_set_sha256"]
    mapping_id = f"mapping_{mapping_sha[:24]}"
    descendants = query_descendants(database, "mapping", mapping_id)
    assert {row["entity_type"] for row in descendants} == {
        "certificate",
        "scene",
        "package",
        "dataset_snapshot",
        "training_run",
        "model",
    }
    assert max(row["depth"] for row in descendants) == 6
    revoked = revoke_lineage(
        database,
        "mapping",
        mapping_id,
        mapping_sha,
        "SEMANTIC_MAPPING_DEFECT",
        "9" * 64,
        timestamp=TS,
    )
    assert (
        revoke_lineage(
            database,
            "mapping",
            mapping_id,
            mapping_sha,
            "SEMANTIC_MAPPING_DEFECT",
            "9" * 64,
            timestamp=TS,
        )
        == revoked
    )
    states = {(row["entity_type"], row["new_state"]) for row in revoked["impacts"]}
    assert ("dataset_snapshot", "excluded") in states
    assert ("training_run", "affected") in states
    assert ("model", "affected") in states
    assert ("package", "revoked") in states
    assert ("certificate", "revoked") in states
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM package_exports WHERE state='revoked'"
            ).fetchone()[0]
            == 2
        )
        assert connection.execute("SELECT COUNT(*) FROM dataset_membership").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM revocation_impacts").fetchone()[0] == len(
            revoked["impacts"]
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM events WHERE event_type='lineage.revoked'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM scene_certificates WHERE status='revoked'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM scene_recipes WHERE state='revoked'"
            ).fetchone()[0]
            == 1
        )
    with pytest.raises(DazControlError, match="lacks accepted scene/certificate"):
        _ingest(fixture)
    with pytest.raises(DazControlError, match="parent is missing or revoked"):
        register_downstream_artifact(
            database,
            "dataset_snapshot",
            "dataset_after_revocation",
            "a" * 64,
            [("package", record["package_ids"][0])],
            {},
            timestamp=TS,
        )
    with pytest.raises(DazControlError, match="invalid lineage edge"):
        register_downstream_artifact(
            database,
            "model",
            "model_with_package_parent",
            "2" * 64,
            [("package", record["package_ids"][0])],
            {},
            timestamp=TS,
        )


def test_revocation_is_exact_scoped_append_only_and_transactional(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _ingest(fixture)
    database = fixture[0]
    manifest = json.loads(
        (fixture[1] / "packages" / "p0" / "manifest.json").read_text(encoding="utf-8")
    )
    mapping_sha = manifest["synthetic_lineage"]["mapping_set_sha256"]
    mapping_id = f"mapping_{mapping_sha[:24]}"
    with pytest.raises(DazControlError, match="hash-rebound"):
        revoke_lineage(database, "mapping", mapping_id, "0" * 64, "DEFECT", "1" * 64, timestamp=TS)
    register_downstream_artifact(
        database,
        "dataset_snapshot",
        "unrelated_dataset",
        "b" * 64,
        [("package", manifest["package_id"])],
        {},
        timestamp=TS,
    )
    with pytest.raises(DazControlError, match="lineage entity conflict"):
        register_downstream_artifact(
            database,
            "dataset_snapshot",
            "unrelated_dataset",
            "b" * 64,
            [("package", _ingest(fixture)["package_ids"][1])],
            {},
            timestamp=TS,
        )
    with pytest.raises(DazControlError, match="duplicate parents"):
        register_downstream_artifact(
            database,
            "dataset_snapshot",
            "duplicate_parent_dataset",
            "d" * 64,
            [("package", manifest["package_id"]), ("package", manifest["package_id"])],
            {},
            timestamp=TS,
        )
    with pytest.raises(DazControlError, match="parent is missing or revoked"):
        register_downstream_artifact(
            database,
            "model",
            "rolled_back_model",
            "c" * 64,
            [("training_run", "missing")],
            {},
            timestamp=TS,
        )
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM lineage_entities WHERE entity_id='rolled_back_model'"
            ).fetchone()[0]
            == 0
        )
        with pytest.raises(sqlite3.IntegrityError, match="DAZ_LINEAGE_APPEND_ONLY"):
            connection.execute("DELETE FROM lineage_edges")
        with pytest.raises(sqlite3.IntegrityError, match="DAZ_INGEST_APPEND_ONLY"):
            connection.execute("UPDATE ingest_records SET scene_id='tampered'")
        with pytest.raises(sqlite3.IntegrityError, match="DAZ_LINEAGE_IDENTITY_IMMUTABLE"):
            connection.execute("UPDATE lineage_entities SET content_sha256=?", ("0" * 64,))
        with pytest.raises(sqlite3.IntegrityError, match="DAZ_DATASET_MEMBERSHIP_APPEND_ONLY"):
            connection.execute("DELETE FROM dataset_membership")


def test_cli_ingest_verify_and_revoke_use_the_same_authoritative_lineage(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    database, adapted_root, adapter_report, qa_report, _contract = fixture
    adapter_path = tmp_path / "adapter_report.json"
    qa_path = tmp_path / "qa_report.json"
    adapter_path.write_text(json.dumps(adapter_report), encoding="utf-8")
    qa_path.write_text(json.dumps(qa_report), encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "daz",
            "ingest",
            adapter_report["scene_id"],
            "--adapted-root",
            str(adapted_root),
            "--adapter-report",
            str(adapter_path),
            "--qa-report",
            str(qa_path),
            "--database",
            str(database),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    ingest_result = json.loads(result.output)
    assert ingest_result["reason"] == "daz_scene_ingest_planned"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ingest_records").fetchone()[0] == 0

    result = runner.invoke(
        main,
        [
            "daz",
            "ingest",
            adapter_report["scene_id"],
            "--adapted-root",
            str(adapted_root),
            "--adapter-report",
            str(adapter_path),
            "--qa-report",
            str(qa_path),
            "--database",
            str(database),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["reason"] == "daz_scene_ingested"

    manifest = json.loads(
        (adapted_root / "packages" / "p0" / "manifest.json").read_text(encoding="utf-8")
    )
    mapping_sha = manifest["synthetic_lineage"]["mapping_set_sha256"]
    mapping_id = f"mapping_{mapping_sha[:24]}"
    result = runner.invoke(
        main,
        [
            "daz",
            "lineage",
            "verify",
            "mapping",
            mapping_id,
            "--database",
            str(database),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["descendant_count"] == 4

    result = runner.invoke(
        main,
        [
            "daz",
            "lineage",
            "revoke",
            "mapping",
            mapping_id,
            "--root-sha256",
            mapping_sha,
            "--reason-code",
            "CLI_TEST_DEFECT",
            "--evidence-sha256",
            "9" * 64,
            "--database",
            str(database),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["reason"] == "daz_lineage_revocation_planned"
    assert query_descendants(database, "mapping", mapping_id)[0]["state"] == "active"

    result = runner.invoke(
        main,
        [
            "daz",
            "lineage",
            "revoke",
            "mapping",
            mapping_id,
            "--root-sha256",
            mapping_sha,
            "--reason-code",
            "CLI_TEST_DEFECT",
            "--evidence-sha256",
            "9" * 64,
            "--database",
            str(database),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["reason"] == "daz_lineage_revoked"

    result = runner.invoke(
        main,
        [
            "daz",
            "lineage",
            "verify",
            "mapping",
            "missing_mapping",
            "--database",
            str(database),
        ],
    )
    assert result.exit_code == 73
    assert "lineage root is missing" in json.loads(result.output)["reason"]
