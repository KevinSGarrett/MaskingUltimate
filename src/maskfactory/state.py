"""SQLite workflow state and the orchestrator's explicit single-writer guard."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / "data" / "maskfactory.sqlite"
SCHEMA_VERSION = 1
IMAGE_STATUSES = frozenset(
    {
        "ingested",
        "drafted",
        "auto_qa",
        "vlm_qa",
        "in_review",
        "corrected",
        "approved_gold",
        "exported",
        "rejected",
        "quarantined",
        "deprecated",
    }
)
MAIN_STATUS_CHAIN = (
    "ingested",
    "drafted",
    "auto_qa",
    "vlm_qa",
    "in_review",
    "corrected",
    "approved_gold",
    "exported",
)
PIPELINE_PROGRESS_STAGE = {
    "ingested": "S00",
    "drafted": "S09",
    "auto_qa": "S10",
    "vlm_qa": "S11",
    "in_review": "S12",
    "corrected": "S12",
    "approved_gold": "S13",
    "exported": "S14",
}
ALLOWED_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    status: frozenset({MAIN_STATUS_CHAIN[index + 1], "rejected", "quarantined"})
    for index, status in enumerate(MAIN_STATUS_CHAIN[:-1])
}
ALLOWED_STATUS_TRANSITIONS["corrected"] = frozenset(
    {"approved_gold", "in_review", "rejected", "quarantined"}
)
ALLOWED_STATUS_TRANSITIONS["approved_gold"] = frozenset({"exported", "corrected", "deprecated"})
ALLOWED_STATUS_TRANSITIONS["exported"] = frozenset({"corrected", "deprecated"})
ALLOWED_STATUS_TRANSITIONS["rejected"] = frozenset({"ingested", "deprecated"})
ALLOWED_STATUS_TRANSITIONS["quarantined"] = frozenset({"ingested", "rejected", "deprecated"})
ALLOWED_STATUS_TRANSITIONS["deprecated"] = frozenset()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS images (
    image_id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL UNIQUE CHECK(length(source_sha256) = 64),
    status TEXT NOT NULL CHECK(status IN (
        'ingested', 'drafted', 'auto_qa', 'vlm_qa', 'in_review', 'corrected',
        'approved_gold', 'exported', 'rejected', 'quarantined', 'deprecated'
    )),
    current_stage TEXT,
    package_version INTEGER NOT NULL DEFAULT 1 CHECK(package_version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_runs (
    run_id TEXT PRIMARY KEY,
    image_id TEXT NOT NULL REFERENCES images(image_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    started TEXT NOT NULL,
    ended TEXT,
    ok INTEGER CHECK(ok IN (0, 1) OR ok IS NULL),
    error TEXT,
    config_hash TEXT NOT NULL CHECK(length(config_hash) = 64),
    gpu_seconds REAL NOT NULL DEFAULT 0 CHECK(gpu_seconds >= 0)
);
CREATE INDEX IF NOT EXISTS idx_stage_runs_image_stage ON stage_runs(image_id, stage);

CREATE TABLE IF NOT EXISTS review_tasks (
    task_id TEXT PRIMARY KEY,
    image_id TEXT NOT NULL REFERENCES images(image_id) ON DELETE CASCADE,
    cvat_task_id INTEGER NOT NULL,
    assignee TEXT,
    opened TEXT NOT NULL,
    closed TEXT,
    minutes REAL CHECK(minutes >= 0 OR minutes IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_review_tasks_image ON review_tasks(image_id);

CREATE TABLE IF NOT EXISTS training_runs (
    run_id TEXT PRIMARY KEY,
    model_key TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    started TEXT NOT NULL,
    ended TEXT,
    metrics_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metrics_json)),
    promoted INTEGER NOT NULL DEFAULT 0 CHECK(promoted IN (0, 1))
);
"""


class WriterBusyError(RuntimeError):
    """Raised when another orchestrator owns the database writer lease."""


class UnknownImageError(KeyError):
    """Raised when a workflow update targets an unknown image."""


class InvalidStatusTransition(ValueError):
    """Raised when code attempts to skip or reverse a governed workflow state."""


@dataclass
class WriterGuard:
    """Atomic process-level lease enforcing the one-orchestrator writer rule."""

    database: Path = DEFAULT_DB_PATH
    _acquired: bool = False

    @property
    def lock_path(self) -> Path:
        return self.database.with_suffix(self.database.suffix + ".writer.lock")

    def acquire(self) -> None:
        if self._acquired:
            raise WriterBusyError(f"writer guard is already held by this object: {self.lock_path}")
        self.database.parent.mkdir(parents=True, exist_ok=True)
        owner = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "acquired_at": datetime.now(UTC).isoformat(),
            "database": str(self.database.resolve()),
        }
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            try:
                existing = self.lock_path.read_text(encoding="utf-8").strip()
            except OSError:
                existing = "owner metadata unavailable"
            raise WriterBusyError(f"database writer already active: {existing}") from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(owner, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            self.lock_path.unlink(missing_ok=True)
            raise
        self._acquired = True

    def release(self) -> None:
        if self._acquired:
            self.lock_path.unlink(missing_ok=True)
            self._acquired = False

    def __enter__(self) -> WriterGuard:
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()


def _connect(path: Path, *, read_only: bool) -> sqlite3.Connection:
    if read_only:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=30)
    else:
        connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    if read_only:
        connection.execute("PRAGMA query_only=ON")
    return connection


def initialize_database(path: Path = DEFAULT_DB_PATH) -> None:
    """Create/upgrade the authoritative workflow index in WAL mode."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with WriterGuard(path):
        connection = _connect(path, read_only=False)
        try:
            journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(journal_mode).lower() != "wal":
                raise RuntimeError(f"failed to enable SQLite WAL mode: {journal_mode}")
            connection.executescript(SCHEMA_SQL)
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()
        finally:
            connection.close()


def transition_image_status(
    connection: sqlite3.Connection,
    image_id: str,
    new_status: str,
    *,
    updated_at: str,
    current_stage: str | None = None,
) -> None:
    """Apply one legal image state transition inside the caller's transaction."""
    if new_status not in IMAGE_STATUSES:
        raise InvalidStatusTransition(f"unknown image status: {new_status}")
    row = connection.execute("SELECT status FROM images WHERE image_id = ?", (image_id,)).fetchone()
    if row is None:
        raise UnknownImageError(image_id)
    old_status = str(row[0])
    allowed = ALLOWED_STATUS_TRANSITIONS[old_status]
    if new_status not in allowed:
        choices = ", ".join(sorted(allowed)) or "none (terminal state)"
        raise InvalidStatusTransition(
            f"illegal image status transition {old_status} -> {new_status}; allowed: {choices}"
        )
    connection.execute(
        "UPDATE images SET status = ?, current_stage = ?, updated_at = ? WHERE image_id = ?",
        (new_status, current_stage, updated_at, image_id),
    )


def persist_terminal_image_outcome(
    database: Path,
    image_id: str,
    outcome: str,
    *,
    reason: str,
    current_stage: str,
    updated_at: str | None = None,
) -> bool:
    """Persist a cacheable terminal stage outcome exactly once."""
    if outcome not in {"rejected", "quarantined"}:
        raise InvalidStatusTransition(f"invalid terminal outcome: {outcome}")
    if not reason.strip():
        raise ValueError("terminal outcome reason cannot be empty")
    timestamp = updated_at or datetime.now(UTC).isoformat()
    with writer_connection(database) as connection:
        row = connection.execute(
            "SELECT status, current_stage FROM images WHERE image_id = ?", (image_id,)
        ).fetchone()
        if row is None:
            raise UnknownImageError(image_id)
        if str(row[0]) == outcome and str(row[1]) == current_stage:
            return False
        transition_image_status(
            connection,
            image_id,
            outcome,
            updated_at=timestamp,
            current_stage=current_stage,
        )
    return True


def persist_recovered_image_outcome(
    database: Path,
    image_id: str,
    *,
    current_stage: str,
    updated_at: str | None = None,
) -> bool:
    """Return a previously terminal image to the main chain after a verified rerun."""
    timestamp = updated_at or datetime.now(UTC).isoformat()
    with writer_connection(database) as connection:
        row = connection.execute(
            "SELECT status FROM images WHERE image_id = ?", (image_id,)
        ).fetchone()
        if row is None:
            raise UnknownImageError(image_id)
        if str(row[0]) not in {"rejected", "quarantined"}:
            return False
        transition_image_status(
            connection,
            image_id,
            "ingested",
            updated_at=timestamp,
            current_stage=current_stage,
        )
    return True


def persist_image_progress(
    database: Path,
    image_id: str,
    target_status: str,
    *,
    updated_at: str | None = None,
) -> bool:
    """Advance durable pipeline progress without skipping states or regressing reruns."""
    if target_status not in PIPELINE_PROGRESS_STAGE or target_status == "ingested":
        raise InvalidStatusTransition(f"invalid pipeline progress target: {target_status}")
    target_index = MAIN_STATUS_CHAIN.index(target_status)
    timestamp = updated_at or datetime.now(UTC).isoformat()
    with writer_connection(database) as connection:
        row = connection.execute(
            "SELECT status FROM images WHERE image_id = ?", (image_id,)
        ).fetchone()
        if row is None:
            raise UnknownImageError(image_id)
        current_status = str(row[0])
        if current_status not in MAIN_STATUS_CHAIN:
            raise InvalidStatusTransition(
                f"cannot advance terminal image status {current_status}; rerun S01 recovery first"
            )
        current_index = MAIN_STATUS_CHAIN.index(current_status)
        if current_index >= target_index:
            return False
        for next_status in MAIN_STATUS_CHAIN[current_index + 1 : target_index + 1]:
            if next_status not in PIPELINE_PROGRESS_STAGE:
                raise InvalidStatusTransition(
                    f"pipeline progress cannot infer stage for {next_status}"
                )
            transition_image_status(
                connection,
                image_id,
                next_status,
                updated_at=timestamp,
                current_stage=PIPELINE_PROGRESS_STAGE[next_status],
            )
    return True


@contextmanager
def writer_connection(path: Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Yield the sole mutable connection while holding the orchestrator lease."""
    path = Path(path)
    with WriterGuard(path):
        connection = _connect(path, read_only=False)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


@contextmanager
def reader_connection(path: Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Yield a query-only dashboard connection without claiming the writer lease."""
    connection = _connect(Path(path), read_only=True)
    try:
        yield connection
    finally:
        connection.close()
