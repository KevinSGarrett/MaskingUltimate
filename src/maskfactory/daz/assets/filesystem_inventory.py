"""Bounded, resumable DAZ content inventory without junction traversal."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping
from urllib.parse import quote

from ...validation import require_valid_document

STATE_SCHEMA_VERSION = 2
SNAPSHOT_SCHEMA_VERSION = "1.0.0"
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
USER_FACING_EXTENSIONS = frozenset(
    {
        ".cm2",
        ".cr2",
        ".dsa",
        ".dsb",
        ".dse",
        ".dsf",
        ".duf",
        ".fc2",
        ".hd2",
        ".hr2",
        ".lt2",
        ".mc6",
        ".pz2",
        ".pp2",
    }
)


class FilesystemInventoryError(ValueError):
    """A stable refusal to inventory an unsafe or ambiguous filesystem state."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


@dataclass(frozen=True)
class ContentRoot:
    root_id: str
    path: Path
    priority: int
    source_kind: str


@dataclass(frozen=True)
class InventoryChunkResult:
    scanned_directories: int
    observed_entries: int
    file_count: int
    skipped_reparse_points: int
    pending_directories: int
    failed_directories: int
    complete: bool


def utcnow() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonicalize_relative_path(value: str | Path) -> tuple[str, str, str]:
    """Return display path, case-folded comparison path, and unambiguous DAZ URI."""

    raw = unicodedata.normalize("NFC", str(value)).replace("\\", "/")
    if not raw or "\x00" in raw or raw.startswith("/"):
        raise FilesystemInventoryError(
            "relative_path_invalid", "path must be nonempty and relative"
        )
    if len(raw) >= 2 and raw[1] == ":":
        raise FilesystemInventoryError(
            "relative_path_invalid", "drive-qualified paths are prohibited"
        )
    parts = PurePosixPath(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise FilesystemInventoryError(
            "relative_path_invalid", "dot/traversal segments are prohibited"
        )
    display = "/".join(parts)
    comparison = display.casefold()
    logical_uri = "/" + quote(display, safe="/-._~!$&'()*+,;=:@")
    return display, comparison, logical_uri


def initialize_inventory_state(
    state_path: Path,
    roots: Iterable[ContentRoot],
    *,
    reset: bool = False,
) -> tuple[ContentRoot, ...]:
    """Initialize or validate one resumable SQLite filesystem scan."""

    normalized = _normalize_roots(roots)
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if reset and state_path.exists():
        state_path.unlink()
    connection = sqlite3.connect(state_path, timeout=30)
    try:
        _configure_connection(connection)
        _create_schema(connection)
        expected = _roots_document(normalized)
        fingerprint = _canonical_sha(expected)
        row = connection.execute(
            "SELECT value FROM metadata WHERE key='root_fingerprint'"
        ).fetchone()
        if row is None:
            connection.executemany(
                "INSERT INTO metadata(key,value) VALUES (?,?)",
                (
                    ("schema_version", str(STATE_SCHEMA_VERSION)),
                    ("root_fingerprint", fingerprint),
                    ("roots_json", json.dumps(expected, sort_keys=True, separators=(",", ":"))),
                    ("created_at", utcnow()),
                ),
            )
            connection.executemany(
                "INSERT INTO directories(root_id,relative_path,canonical_path,parent_canonical_path,state) "
                "VALUES (?,?,?,NULL,'pending')",
                ((root.root_id, "", "") for root in normalized),
            )
            connection.commit()
        elif row[0] != fingerprint:
            raise FilesystemInventoryError(
                "inventory_roots_changed", "resume state was created for a different root set"
            )
        _verify_integrity(connection)
    finally:
        connection.close()
    return normalized


def scan_inventory_chunk(
    state_path: Path,
    roots: Iterable[ContentRoot],
    *,
    max_entries: int = 50_000,
    max_seconds: float = 30.0,
) -> InventoryChunkResult:
    """Scan whole directories until a deterministic chunk budget is reached."""

    if max_entries <= 0 or max_seconds <= 0:
        raise FilesystemInventoryError("scan_budget_invalid", "chunk budgets must be positive")
    normalized = initialize_inventory_state(state_path, roots)
    root_map = {root.root_id: root for root in normalized}
    connection = sqlite3.connect(Path(state_path), timeout=30)
    started = time.monotonic()
    directories = entries = files = reparse = 0
    try:
        _configure_connection(connection)
        while entries < max_entries and time.monotonic() - started < max_seconds:
            row = connection.execute(
                "SELECT root_id,relative_path FROM directories WHERE state='pending' "
                "ORDER BY root_id,canonical_path LIMIT 1"
            ).fetchone()
            if row is None:
                break
            root_id, relative = str(row[0]), str(row[1])
            root = root_map[root_id]
            directory = root.path if not relative else root.path / Path(relative)
            try:
                observed = _scan_one_directory(connection, root, relative, directory)
            except OSError as exc:
                connection.execute(
                    "UPDATE directories SET state='failed',error_code=?,scanned_at=? "
                    "WHERE root_id=? AND relative_path=?",
                    (type(exc).__name__, utcnow(), root_id, relative),
                )
                connection.commit()
                continue
            directories += 1
            entries += observed[0]
            files += observed[1]
            reparse += observed[2]
        counts = dict(
            connection.execute("SELECT state,count(*) FROM directories GROUP BY state").fetchall()
        )
        pending = int(counts.get("pending", 0))
        failed = int(counts.get("failed", 0))
        if pending == 0 and failed == 0:
            _requeue_drifted_directories(connection, root_map)
            counts = dict(
                connection.execute(
                    "SELECT state,count(*) FROM directories GROUP BY state"
                ).fetchall()
            )
            pending = int(counts.get("pending", 0))
            failed = int(counts.get("failed", 0))
        return InventoryChunkResult(
            scanned_directories=directories,
            observed_entries=entries,
            file_count=files,
            skipped_reparse_points=reparse,
            pending_directories=pending,
            failed_directories=failed,
            complete=pending == 0 and failed == 0,
        )
    finally:
        connection.close()


def inventory_state_summary(state_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(Path(state_path), timeout=30)
    try:
        _configure_connection(connection)
        _verify_integrity(connection)
        states = dict(
            connection.execute("SELECT state,count(*) FROM directories GROUP BY state").fetchall()
        )
        file_count, byte_count, user_facing = connection.execute(
            "SELECT count(*),coalesce(sum(size_bytes),0),coalesce(sum(user_facing),0) FROM files"
        ).fetchone()
        reparse = connection.execute("SELECT count(*) FROM skipped_reparse_points").fetchone()[0]
        return {
            "directory_states": {key: int(value) for key, value in sorted(states.items())},
            "file_count": int(file_count),
            "byte_count": int(byte_count),
            "user_facing_file_count": int(user_facing),
            "skipped_reparse_point_count": int(reparse),
            "complete": int(states.get("pending", 0)) == 0 and int(states.get("failed", 0)) == 0,
        }
    finally:
        connection.close()


def build_inventory_snapshot(
    state_path: Path,
    *,
    roots: Iterable[ContentRoot] | None = None,
    include_files: bool = True,
) -> dict[str, Any]:
    """Build canonical portable authority only after the resumable scan is complete."""

    normalized_roots = initialize_inventory_state(state_path, roots) if roots is not None else None
    if normalized_roots is not None:
        drift_connection = sqlite3.connect(Path(state_path), timeout=30)
        try:
            _configure_connection(drift_connection)
            _requeue_drifted_directories(
                drift_connection, {root.root_id: root for root in normalized_roots}
            )
        finally:
            drift_connection.close()
    summary = inventory_state_summary(state_path)
    if not summary["complete"]:
        raise FilesystemInventoryError(
            "inventory_incomplete", "pending or failed directories remain"
        )
    connection = sqlite3.connect(Path(state_path), timeout=30)
    try:
        _configure_connection(connection)
        roots = json.loads(
            connection.execute("SELECT value FROM metadata WHERE key='roots_json'").fetchone()[0]
        )
        rows: list[dict[str, Any]] = []
        digest = hashlib.sha256()
        query = (
            "SELECT root_id,relative_path,canonical_path,logical_uri,size_bytes,mtime_ns,file_id,"
            "extension,user_facing FROM files ORDER BY root_id,canonical_path,relative_path"
        )
        for row in connection.execute(query):
            record = {
                "root_id": row[0],
                "relative_path": row[1],
                "canonical_path": row[2],
                "logical_uri": row[3],
                "size_bytes": row[4],
                "mtime_ns": row[5],
                "file_id": row[6],
                "extension": row[7],
                "user_facing": bool(row[8]),
            }
            encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            if include_files:
                rows.append(record)
        inventory_sha = digest.hexdigest()
        document: dict[str, Any] = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": f"fs_{inventory_sha[:24]}",
            "inventory_sha256": inventory_sha,
            "roots": roots,
            "summary": summary,
            "reparse_points_followed": False,
            "files": rows if include_files else None,
        }
        if normalized_roots is not None:
            _requeue_drifted_directories(
                connection, {root.root_id: root for root in normalized_roots}
            )
            if not inventory_state_summary(state_path)["complete"]:
                raise FilesystemInventoryError(
                    "inventory_drifted", "content roots changed while finalizing the snapshot"
                )
        require_valid_document(document, "daz_filesystem_inventory_snapshot")
        return document
    finally:
        connection.close()


def publish_inventory_snapshot(snapshot: Mapping[str, Any], output_root: Path) -> tuple[Path, bool]:
    snapshot_id = snapshot.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id.startswith("fs_"):
        raise FilesystemInventoryError(
            "snapshot_identity_invalid", "snapshot_id is missing or invalid"
        )
    payload = (json.dumps(snapshot, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{snapshot_id}.json"
    if target.exists():
        if target.read_bytes() != payload:
            raise FilesystemInventoryError(
                "snapshot_immutable_conflict", "existing snapshot bytes do not match"
            )
        return target, False
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{snapshot_id}.", suffix=".tmp", dir=output_root
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return target, True


def _normalize_roots(roots: Iterable[ContentRoot]) -> tuple[ContentRoot, ...]:
    normalized: list[ContentRoot] = []
    seen: set[str] = set()
    seen_paths: set[str] = set()
    for root in roots:
        if not root.root_id or root.root_id in seen:
            raise FilesystemInventoryError(
                "root_identity_invalid", "root IDs must be unique and nonempty"
            )
        path = Path(root.path).resolve(strict=True)
        if not path.is_dir():
            raise FilesystemInventoryError(
                "root_path_invalid", f"root is not a directory: {root.root_id}"
            )
        path_key = os.path.normcase(str(path))
        if path_key in seen_paths:
            raise FilesystemInventoryError(
                "root_path_duplicate", "two root IDs resolve to one path"
            )
        root_stat = path.stat(follow_symlinks=False)
        if _is_reparse(root_stat) or path.is_symlink():
            raise FilesystemInventoryError(
                "root_reparse_prohibited", f"root is a reparse point: {root.root_id}"
            )
        seen.add(root.root_id)
        seen_paths.add(path_key)
        normalized.append(ContentRoot(root.root_id, path, int(root.priority), root.source_kind))
    if not normalized:
        raise FilesystemInventoryError("roots_missing", "at least one content root is required")
    return tuple(sorted(normalized, key=lambda item: (item.priority, item.root_id)))


def _roots_document(roots: Iterable[ContentRoot]) -> list[dict[str, Any]]:
    return [
        {
            "root_id": root.root_id,
            "priority": root.priority,
            "source_kind": root.source_kind,
            "path_fingerprint": hashlib.sha256(
                os.path.normcase(str(root.path)).encode("utf-8")
            ).hexdigest(),
        }
        for root in roots
    ]


def _canonical_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS directories(
          root_id TEXT NOT NULL,
          relative_path TEXT NOT NULL,
          canonical_path TEXT NOT NULL,
          parent_canonical_path TEXT,
          state TEXT NOT NULL CHECK(state IN ('pending','complete','failed')),
          entry_count INTEGER,
          mtime_ns INTEGER,
          scanned_at TEXT,
          error_code TEXT,
          PRIMARY KEY(root_id,canonical_path)
        );
        CREATE TABLE IF NOT EXISTS files(
          root_id TEXT NOT NULL,
          relative_path TEXT NOT NULL,
          canonical_path TEXT NOT NULL,
          parent_canonical_path TEXT NOT NULL,
          logical_uri TEXT NOT NULL,
          size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
          mtime_ns INTEGER NOT NULL,
          file_id TEXT,
          extension TEXT NOT NULL,
          user_facing INTEGER NOT NULL CHECK(user_facing IN (0,1)),
          PRIMARY KEY(root_id,canonical_path)
        );
        CREATE TABLE IF NOT EXISTS skipped_reparse_points(
          root_id TEXT NOT NULL,
          relative_path TEXT NOT NULL,
          canonical_path TEXT NOT NULL,
          parent_canonical_path TEXT NOT NULL,
          kind TEXT NOT NULL,
          PRIMARY KEY(root_id,canonical_path)
        );
        """
    )


def _verify_integrity(connection: sqlite3.Connection) -> None:
    row = connection.execute("PRAGMA integrity_check").fetchone()
    if row is None or row[0] != "ok":
        raise FilesystemInventoryError("inventory_state_corrupt", "SQLite integrity check failed")
    version = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
    if version is not None and version[0] != str(STATE_SCHEMA_VERSION):
        raise FilesystemInventoryError(
            "inventory_state_version", "unsupported inventory state version"
        )


def _scan_one_directory(
    connection: sqlite3.Connection,
    root: ContentRoot,
    relative: str,
    directory: Path,
) -> tuple[int, int, int]:
    entries = sorted(os.scandir(directory), key=lambda item: (item.name.casefold(), item.name))
    file_count = reparse_count = 0
    parent_canonical = canonicalize_relative_path(relative)[1] if relative else ""
    observed_children: set[str] = set()
    connection.execute("BEGIN IMMEDIATE")
    try:
        for entry in entries:
            child_relative = entry.name if not relative else f"{relative}/{entry.name}"
            display, canonical, logical_uri = canonicalize_relative_path(child_relative)
            observed_children.add(canonical)
            observed = entry.stat(follow_symlinks=False)
            if entry.is_symlink() or _is_reparse(observed):
                connection.execute(
                    "INSERT OR REPLACE INTO skipped_reparse_points(root_id,relative_path,canonical_path,"
                    "parent_canonical_path,kind) VALUES (?,?,?,?,?)",
                    (
                        root.root_id,
                        display,
                        canonical,
                        parent_canonical,
                        "symlink" if entry.is_symlink() else "reparse",
                    ),
                )
                reparse_count += 1
                continue
            if stat.S_ISDIR(observed.st_mode):
                _insert_unique_path(
                    connection,
                    "directories",
                    root.root_id,
                    display,
                    canonical,
                    "INSERT INTO directories(root_id,relative_path,canonical_path,parent_canonical_path,state) "
                    "VALUES (?,?,?,?,'pending') ON CONFLICT(root_id,canonical_path) DO NOTHING",
                    parent_canonical,
                )
                continue
            if not stat.S_ISREG(observed.st_mode):
                continue
            extension = Path(entry.name).suffix.casefold()
            file_id = (
                f"{int(observed.st_dev):x}:{int(observed.st_ino):x}" if observed.st_ino else None
            )
            existing = connection.execute(
                "SELECT relative_path FROM files WHERE root_id=? AND canonical_path=?",
                (root.root_id, canonical),
            ).fetchone()
            if existing is not None and existing[0] != display:
                raise FilesystemInventoryError(
                    "case_collision",
                    f"case-folded path collision under {root.root_id}: {canonical}",
                )
            connection.execute(
                "INSERT OR REPLACE INTO files(root_id,relative_path,canonical_path,parent_canonical_path,"
                "logical_uri,size_bytes,mtime_ns,file_id,extension,user_facing) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    root.root_id,
                    display,
                    canonical,
                    parent_canonical,
                    logical_uri,
                    int(observed.st_size),
                    int(observed.st_mtime_ns),
                    file_id,
                    extension,
                    int(extension in USER_FACING_EXTENSIONS),
                ),
            )
            file_count += 1
        _remove_disappeared_children(connection, root.root_id, parent_canonical, observed_children)
        directory_stat = directory.stat(follow_symlinks=False)
        connection.execute(
            "UPDATE directories SET state='complete',entry_count=?,mtime_ns=?,scanned_at=?,error_code=NULL "
            "WHERE root_id=? AND relative_path=?",
            (len(entries), int(directory_stat.st_mtime_ns), utcnow(), root.root_id, relative),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return len(entries), file_count, reparse_count


def _insert_unique_path(
    connection: sqlite3.Connection,
    table: str,
    root_id: str,
    display: str,
    canonical: str,
    statement: str,
    parent_canonical: str,
) -> None:
    existing = connection.execute(
        f"SELECT relative_path FROM {table} WHERE root_id=? AND canonical_path=?",  # noqa: S608
        (root_id, canonical),
    ).fetchone()
    if existing is not None and existing[0] != display:
        raise FilesystemInventoryError(
            "case_collision", f"case-folded path collision under {root_id}: {canonical}"
        )
    connection.execute(statement, (root_id, display, canonical, parent_canonical))


def _remove_disappeared_children(
    connection: sqlite3.Connection,
    root_id: str,
    parent_canonical: str,
    observed_children: set[str],
) -> None:
    for table in ("files", "skipped_reparse_points"):
        existing = {
            str(row[0])
            for row in connection.execute(
                f"SELECT canonical_path FROM {table} "  # noqa: S608
                "WHERE root_id=? AND parent_canonical_path=?",
                (root_id, parent_canonical),
            )
        }
        for canonical in existing - observed_children:
            connection.execute(
                f"DELETE FROM {table} WHERE root_id=? AND canonical_path=?",  # noqa: S608
                (root_id, canonical),
            )
    child_directories = {
        str(row[0])
        for row in connection.execute(
            "SELECT canonical_path FROM directories " "WHERE root_id=? AND parent_canonical_path=?",
            (root_id, parent_canonical),
        )
    }
    for canonical in child_directories - observed_children:
        prefix = canonical + "/%"
        connection.execute(
            "DELETE FROM files WHERE root_id=? AND (canonical_path=? OR canonical_path LIKE ?)",
            (root_id, canonical, prefix),
        )
        connection.execute(
            "DELETE FROM skipped_reparse_points WHERE root_id=? "
            "AND (canonical_path=? OR canonical_path LIKE ?)",
            (root_id, canonical, prefix),
        )
        connection.execute(
            "DELETE FROM directories WHERE root_id=? AND (canonical_path=? OR canonical_path LIKE ?)",
            (root_id, canonical, prefix),
        )


def _requeue_drifted_directories(
    connection: sqlite3.Connection, roots: Mapping[str, ContentRoot]
) -> None:
    changed: list[tuple[str, str]] = []
    for root_id, relative, recorded_mtime in connection.execute(
        "SELECT root_id,relative_path,mtime_ns FROM directories WHERE state='complete'"
    ):
        root = roots[str(root_id)]
        directory = root.path if not relative else root.path / Path(str(relative))
        try:
            observed = directory.stat(follow_symlinks=False)
        except OSError:
            changed.append((str(root_id), str(relative)))
            continue
        if _is_reparse(observed) or int(observed.st_mtime_ns) != int(recorded_mtime):
            changed.append((str(root_id), str(relative)))
    if changed:
        connection.executemany(
            "UPDATE directories SET state='pending',error_code=NULL "
            "WHERE root_id=? AND relative_path=?",
            changed,
        )
        connection.commit()


def _is_reparse(observed: os.stat_result) -> bool:
    attributes = int(getattr(observed, "st_file_attributes", 0))
    return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)
