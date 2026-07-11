import json
import sqlite3
from pathlib import Path

import pytest

from maskfactory.state import (
    MAIN_STATUS_CHAIN,
    SCHEMA_VERSION,
    InvalidStatusTransition,
    UnknownImageError,
    WriterBusyError,
    WriterGuard,
    initialize_database,
    persist_terminal_image_outcome,
    reader_connection,
    transition_image_status,
    writer_connection,
)

EXPECTED_TABLES = {"images", "stage_runs", "review_tasks", "training_runs"}


def test_initialize_database_creates_four_tables_wal_and_foreign_keys(tmp_path: Path) -> None:
    database = tmp_path / "maskfactory.sqlite"
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables == EXPECTED_TABLES
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_writer_connection_persists_related_rows_and_enforces_foreign_keys(
    tmp_path: Path,
) -> None:
    database = tmp_path / "maskfactory.sqlite"
    initialize_database(database)
    sha = "a" * 64
    with writer_connection(database) as connection:
        connection.execute(
            "INSERT INTO images VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("img_a3f9c2e17b04", sha, "ingested", "S00", 1, "now", "now"),
        )
        connection.execute(
            "INSERT INTO stage_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run_1", "img_a3f9c2e17b04", "S00", "now", None, None, None, sha, 0),
        )
        connection.execute(
            "INSERT INTO review_tasks VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("review_1", "img_a3f9c2e17b04", 10, "kevin", "now", None, None),
        )
        connection.execute(
            "INSERT INTO training_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("train_1", "model", "v1", "now", None, json.dumps({"iou": 0.8}), 0),
        )

    with reader_connection(database) as connection:
        assert connection.execute("SELECT count(*) FROM images").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM images")

    with pytest.raises(sqlite3.IntegrityError):
        with writer_connection(database) as connection:
            connection.execute(
                "INSERT INTO stage_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("run_bad", "img_missing", "S00", "now", None, None, None, sha, 0),
            )


def test_terminal_outcome_transition_is_idempotent_and_governed(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite"
    initialize_database(database)
    with writer_connection(database) as connection:
        connection.execute(
            "INSERT INTO images VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("img_a3f9c2e17b04", "a" * 64, "ingested", "S00", 1, "t0", "t0"),
        )
    assert persist_terminal_image_outcome(
        database,
        "img_a3f9c2e17b04",
        "rejected",
        reason="no_person",
        current_stage="S01",
        updated_at="t1",
    )
    assert not persist_terminal_image_outcome(
        database,
        "img_a3f9c2e17b04",
        "rejected",
        reason="no_person",
        current_stage="S01",
        updated_at="t2",
    )
    with pytest.raises(InvalidStatusTransition, match="invalid terminal"):
        persist_terminal_image_outcome(
            database,
            "img_a3f9c2e17b04",
            "drafted",
            reason="bad",
            current_stage="S01",
        )


def test_writer_guard_refuses_concurrent_orchestrator_and_releases_cleanly(
    tmp_path: Path,
) -> None:
    database = tmp_path / "maskfactory.sqlite"
    first = WriterGuard(database)
    second = WriterGuard(database)
    with first:
        metadata = json.loads(first.lock_path.read_text(encoding="utf-8"))
        assert metadata["pid"] > 0
        assert metadata["database"] == str(database.resolve())
        with pytest.raises(WriterBusyError, match="writer already active"):
            second.acquire()
    assert not first.lock_path.exists()
    with second:
        assert second.lock_path.is_file()


def test_writer_connection_rolls_back_on_error_and_removes_guard(tmp_path: Path) -> None:
    database = tmp_path / "maskfactory.sqlite"
    initialize_database(database)
    guard_path = database.with_suffix(".sqlite.writer.lock")
    with pytest.raises(RuntimeError, match="abort"):
        with writer_connection(database) as connection:
            connection.execute(
                "INSERT INTO images VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("img_a3f9c2e17b04", "a" * 64, "ingested", None, 1, "now", "now"),
            )
            raise RuntimeError("abort")
    assert not guard_path.exists()
    with reader_connection(database) as connection:
        assert connection.execute("SELECT count(*) FROM images").fetchone()[0] == 0


def _insert_ingested(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO images VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("img_a3f9c2e17b04", "a" * 64, "ingested", "S00", 1, "t0", "t0"),
    )


def test_status_machine_enforces_the_complete_main_chain(tmp_path: Path) -> None:
    database = tmp_path / "maskfactory.sqlite"
    initialize_database(database)
    with writer_connection(database) as connection:
        _insert_ingested(connection)
        for index, status in enumerate(MAIN_STATUS_CHAIN[1:], start=1):
            transition_image_status(
                connection,
                "img_a3f9c2e17b04",
                status,
                current_stage=f"S{index:02d}",
                updated_at=f"t{index}",
            )
        row = connection.execute(
            "SELECT status, current_stage, updated_at FROM images WHERE image_id = ?",
            ("img_a3f9c2e17b04",),
        ).fetchone()
        assert tuple(row) == ("exported", "S07", "t7")


def test_status_machine_allows_governed_branch_and_reentry(tmp_path: Path) -> None:
    database = tmp_path / "maskfactory.sqlite"
    initialize_database(database)
    with writer_connection(database) as connection:
        _insert_ingested(connection)
        transition_image_status(connection, "img_a3f9c2e17b04", "quarantined", updated_at="t1")
        transition_image_status(connection, "img_a3f9c2e17b04", "ingested", updated_at="t2")
        transition_image_status(connection, "img_a3f9c2e17b04", "rejected", updated_at="t3")
        transition_image_status(connection, "img_a3f9c2e17b04", "deprecated", updated_at="t4")


def test_status_machine_refuses_skips_unknown_status_and_unknown_image(tmp_path: Path) -> None:
    database = tmp_path / "maskfactory.sqlite"
    initialize_database(database)
    with writer_connection(database) as connection:
        _insert_ingested(connection)
        with pytest.raises(InvalidStatusTransition, match="ingested -> approved_gold"):
            transition_image_status(
                connection, "img_a3f9c2e17b04", "approved_gold", updated_at="t1"
            )
        with pytest.raises(InvalidStatusTransition, match="unknown image status"):
            transition_image_status(connection, "img_a3f9c2e17b04", "invented", updated_at="t1")
        with pytest.raises(UnknownImageError):
            transition_image_status(connection, "img_missing", "drafted", updated_at="t1")


def test_sql_constraint_rejects_status_bypass(tmp_path: Path) -> None:
    database = tmp_path / "maskfactory.sqlite"
    initialize_database(database)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
        with writer_connection(database) as connection:
            connection.execute(
                "INSERT INTO images VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("img_a3f9c2e17b04", "a" * 64, "invented", None, 1, "t0", "t0"),
            )
