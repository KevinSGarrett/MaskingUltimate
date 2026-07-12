import copy
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.reindex import (
    ReindexError,
    expected_image_rows,
    reindex_packages,
    run_reindex_incident_drill,
)
from maskfactory.state import initialize_database, reader_connection, writer_connection
from test_manifest_schema import valid_manifest


def _write_manifest(packages: Path, manifest: dict, instance: str = "p0") -> Path:
    path = packages / manifest["image_id"] / "instances" / instance / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def test_reindex_dry_run_reports_drift_rebuilds_and_then_is_clean(tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    database = tmp_path / "state.sqlite"
    manifest = valid_manifest()
    _write_manifest(packages, manifest)
    initialize_database(database)

    before = reindex_packages(packages_root=packages, database=database, dry_run=True)
    assert before.missing_in_db == (manifest["image_id"],)
    with reader_connection(database) as connection:
        assert connection.execute("SELECT count(*) FROM images").fetchone()[0] == 0

    applied = reindex_packages(packages_root=packages, database=database, dry_run=False)
    assert applied == before
    after = reindex_packages(packages_root=packages, database=database, dry_run=True)
    assert after.clean
    with reader_connection(database) as connection:
        row = connection.execute(
            "SELECT source_sha256, status, current_stage FROM images"
        ).fetchone()
    assert tuple(row) == ("a" * 64, "approved_gold", "S13")


def test_reindex_dry_run_treats_pre_schema_sqlite_as_empty_index(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite"
    sqlite3.connect(database).close()
    assert reindex_packages(
        packages_root=tmp_path / "missing-packages", database=database, dry_run=True
    ).clean


def test_reindex_reports_stale_and_extra_rows_then_rebuild_removes_them(tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    database = tmp_path / "state.sqlite"
    manifest = valid_manifest()
    _write_manifest(packages, manifest)
    initialize_database(database)
    with writer_connection(database) as connection:
        connection.execute(
            "INSERT INTO images VALUES (?, ?, ?, ?, ?, ?, ?)",
            (manifest["image_id"], "a" * 64, "ingested", "S00", 1, "old", "old"),
        )
        connection.execute(
            "INSERT INTO images VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("img_b3f9c2e17b04", "b" * 64, "ingested", "S00", 1, "old", "old"),
        )
    difference = reindex_packages(packages_root=packages, database=database, dry_run=True)
    assert difference.extra_in_db == ("img_b3f9c2e17b04",)
    assert set(difference.stale_rows[manifest["image_id"]]) == {
        "status",
        "current_stage",
        "created_at",
        "updated_at",
    }
    reindex_packages(packages_root=packages, database=database, dry_run=False)
    with reader_connection(database) as connection:
        ids = [row[0] for row in connection.execute("SELECT image_id FROM images")]
    assert ids == [manifest["image_id"]]


def test_reindex_collapses_distinct_instance_crops_by_parent_source_identity(
    tmp_path: Path,
) -> None:
    packages = tmp_path / "packages"
    first = valid_manifest()
    second = copy.deepcopy(first)
    _write_manifest(packages, first, "p0")
    _write_manifest(packages, second, "p1")
    assert list(expected_image_rows(packages)) == [first["image_id"]]

    second["source"]["source_sha256"] = "b" * 64
    _write_manifest(packages, second, "p1")
    rows = expected_image_rows(packages)
    assert rows[first["image_id"]].source_sha256 == "a" * 64

    second["source"]["parent_source_sha256"] = "b" * 64
    _write_manifest(packages, second, "p1")
    with pytest.raises(ReindexError, match="disagree on parent_source_sha256"):
        expected_image_rows(packages)


def test_reindex_cli_dry_run_emits_machine_readable_diff(tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    database = tmp_path / "state.sqlite"
    _write_manifest(packages, valid_manifest())
    initialize_database(database)
    result = CliRunner().invoke(
        main,
        [
            "reindex",
            "--dry-run",
            "--packages-root",
            str(packages),
            "--database",
            str(database),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["clean"] is False
    assert payload["missing_in_db"] == ["img_a3f9c2e17b04"]


def test_ip3_reindex_drill_rebuilds_copy_and_never_mutates_source(tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    database = tmp_path / "state.sqlite"
    _write_manifest(packages, valid_manifest())
    initialize_database(database)
    source_before = database.read_bytes()
    report_path = run_reindex_incident_drill(
        source_database=database,
        packages_root=packages,
        output_dir=tmp_path / "drill",
        now=datetime(2026, 7, 12, tzinfo=UTC),
    )
    report = json.loads(report_path.read_text())
    assert report["source_untouched"] is True
    assert report["source_sha256_before"] == report["source_sha256_after"]
    assert report["before_rebuild"]["missing_in_db"] == ["img_a3f9c2e17b04"]
    assert report["after_rebuild"] == {
        "clean": True,
        "missing_in_db": [],
        "stale_rows": {},
        "extra_in_db": [],
    }
    assert database.read_bytes() == source_before
    assert Path(report["copy_database"]).is_file()


def test_ip3_cli_writes_report_from_copy(tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    database = tmp_path / "state.sqlite"
    _write_manifest(packages, valid_manifest())
    initialize_database(database)
    result = CliRunner().invoke(
        main,
        [
            "incident",
            "reindex-drill",
            "--database",
            str(database),
            "--packages-root",
            str(packages),
            "--output-dir",
            str(tmp_path / "evidence"),
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(Path(result.output.strip()).read_text())
    assert report["after_rebuild"]["clean"] is True
