"""Incremental hashing and explicit DAZ duplicate/shadow resolution."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ...validation import require_valid_document
from .filesystem_inventory import (
    FILE_ATTRIBUTE_REPARSE_POINT,
    ContentRoot,
    build_inventory_snapshot,
    utcnow,
)

IDENTITY_STATE_SCHEMA_VERSION = 1
IDENTITY_SNAPSHOT_SCHEMA_VERSION = "1.0.0"


class AssetIdentityError(ValueError):
    """A stable refusal to hash or resolve an ambiguous DAZ asset estate."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


@dataclass(frozen=True)
class IdentityChunkResult:
    hashed_this_chunk: int
    hashed_bytes_this_chunk: int
    reused_hashes: int
    pending_files: int
    failed_files: int
    complete: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resume_asset_identity_index(
    inventory_state: Path,
    identity_state: Path,
    roots: Iterable[ContentRoot],
    *,
    max_files: int = 100,
    max_bytes: int = 2 * 1024**3,
    max_seconds: float = 30.0,
    reset: bool = False,
) -> IdentityChunkResult:
    """Hash a bounded set of new/changed inventory files without following reparses."""

    if max_files <= 0 or max_bytes <= 0 or max_seconds <= 0:
        raise AssetIdentityError("identity_budget_invalid", "all hash budgets must be positive")
    normalized = _normalize_roots(roots)
    inventory_state = Path(inventory_state).resolve(strict=True)
    identity_state = Path(identity_state)
    identity_state.parent.mkdir(parents=True, exist_ok=True)
    if reset:
        for candidate in (
            identity_state,
            Path(str(identity_state) + "-wal"),
            Path(str(identity_state) + "-shm"),
        ):
            candidate.unlink(missing_ok=True)
    reused = _synchronize_identity_state(inventory_state, identity_state, normalized)
    root_map = {root.root_id: root for root in normalized}
    connection = sqlite3.connect(identity_state, timeout=30)
    _configure_identity_connection(connection)
    started = time.monotonic()
    hashed = hashed_bytes = 0
    try:
        rows = connection.execute(
            "SELECT root_id,relative_path,canonical_path,size_bytes,mtime_ns,file_id "
            "FROM files WHERE state='pending' ORDER BY root_priority,root_id,canonical_path"
        ).fetchall()
        for root_id, relative_path, canonical_path, size_bytes, mtime_ns, file_id in rows:
            if hashed >= max_files or hashed_bytes >= max_bytes:
                break
            if time.monotonic() - started >= max_seconds:
                break
            root = root_map[str(root_id)]
            try:
                path = _path_under_root(root.path, str(relative_path))
                before = path.stat(follow_symlinks=False)
                _verify_hash_target(path, before)
                if not _stat_matches(before, int(size_bytes), int(mtime_ns), file_id):
                    _leave_pending(
                        connection,
                        str(root_id),
                        str(canonical_path),
                        "inventory_metadata_drift",
                    )
                    continue
                sha256 = _sha256_file(path)
                after = path.stat(follow_symlinks=False)
                if not _stat_matches(after, int(size_bytes), int(mtime_ns), file_id):
                    _leave_pending(
                        connection,
                        str(root_id),
                        str(canonical_path),
                        "file_changed_during_hash",
                    )
                    continue
            except (OSError, AssetIdentityError) as exc:
                reason = (
                    exc.reason_code if isinstance(exc, AssetIdentityError) else type(exc).__name__
                )
                connection.execute(
                    "UPDATE files SET state='failed',sha256=NULL,error_code=?,hashed_at=? "
                    "WHERE root_id=? AND canonical_path=?",
                    (reason, utcnow(), root_id, canonical_path),
                )
                connection.commit()
                continue
            connection.execute(
                "UPDATE files SET state='complete',sha256=?,error_code=NULL,hashed_at=? "
                "WHERE root_id=? AND canonical_path=?",
                (sha256, utcnow(), root_id, canonical_path),
            )
            connection.commit()
            hashed += 1
            hashed_bytes += int(size_bytes)
        counts = dict(connection.execute("SELECT state,count(*) FROM files GROUP BY state"))
        pending = int(counts.get("pending", 0))
        failed = int(counts.get("failed", 0))
        return IdentityChunkResult(
            hashed_this_chunk=hashed,
            hashed_bytes_this_chunk=hashed_bytes,
            reused_hashes=reused,
            pending_files=pending,
            failed_files=failed,
            complete=pending == 0 and failed == 0,
        )
    finally:
        connection.close()


def asset_identity_state_summary(identity_state: Path) -> dict[str, Any]:
    connection = sqlite3.connect(Path(identity_state), timeout=30)
    try:
        _configure_identity_connection(connection)
        _verify_identity_integrity(connection)
        states = dict(connection.execute("SELECT state,count(*) FROM files GROUP BY state"))
        file_count, byte_count = connection.execute(
            "SELECT count(*),coalesce(sum(size_bytes),0) FROM files"
        ).fetchone()
        return {
            "file_states": {key: int(value) for key, value in sorted(states.items())},
            "file_count": int(file_count),
            "byte_count": int(byte_count),
            "complete": int(states.get("pending", 0)) == 0 and int(states.get("failed", 0)) == 0,
        }
    finally:
        connection.close()


def build_asset_identity_snapshot(
    inventory_state: Path,
    identity_state: Path,
    roots: Iterable[ContentRoot],
) -> dict[str, Any]:
    """Freeze exact hashes and explicit logical-path/content duplicate decisions."""

    normalized = _normalize_roots(roots)
    fast_before = build_inventory_snapshot(
        Path(inventory_state), roots=normalized, include_files=False
    )
    _synchronize_identity_state(Path(inventory_state), Path(identity_state), normalized)
    summary = asset_identity_state_summary(identity_state)
    if not summary["complete"]:
        raise AssetIdentityError(
            "identity_index_incomplete", "pending or failed file hashes remain"
        )
    connection = sqlite3.connect(Path(identity_state), timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        _configure_identity_connection(connection)
        rows = connection.execute(
            "SELECT root_id,relative_path,canonical_path,logical_uri,size_bytes,mtime_ns,file_id,"
            "root_priority,source_kind,sha256 FROM files ORDER BY root_priority,root_id,canonical_path"
        ).fetchall()
    finally:
        connection.close()
    files, conflicts, duplicate_groups = _resolve_identity_rows(rows)
    fast_after = build_inventory_snapshot(
        Path(inventory_state), roots=normalized, include_files=False
    )
    if fast_before["inventory_sha256"] != fast_after["inventory_sha256"]:
        raise AssetIdentityError(
            "inventory_drifted_during_identity_freeze",
            "filesystem inventory changed while identity snapshot was built",
        )
    fingerprint = _canonical_sha(
        {
            "inventory_sha256": fast_after["inventory_sha256"],
            "files": files,
            "logical_conflicts": conflicts,
            "content_duplicate_groups": duplicate_groups,
        }
    )
    document = {
        "schema_version": IDENTITY_SNAPSHOT_SCHEMA_VERSION,
        "snapshot_id": f"aid_{fingerprint[:24]}",
        "identity_sha256": fingerprint,
        "inventory_snapshot_id": fast_after["snapshot_id"],
        "inventory_sha256": fast_after["inventory_sha256"],
        "summary": {
            "file_count": len(files),
            "byte_count": sum(int(row["size_bytes"]) for row in files),
            "unique_logical_assets": sum(
                row["logical_status"] in {"unique", "duplicate_winner"} for row in files
            ),
            "duplicate_copies": sum(row["logical_status"] == "duplicate_copy" for row in files),
            "shadow_conflict_files": sum(
                row["logical_status"] == "shadow_conflict" for row in files
            ),
            "logical_conflict_count": len(conflicts),
            "content_duplicate_group_count": len(duplicate_groups),
            "complete": True,
        },
        "files": files,
        "logical_conflicts": conflicts,
        "content_duplicate_groups": duplicate_groups,
    }
    require_valid_document(document, "daz_asset_identity_snapshot")
    return document


def diff_asset_identity_snapshots(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a deterministic asset add/remove/change/move/conflict diff."""

    require_valid_document(previous, "daz_asset_identity_snapshot")
    require_valid_document(current, "daz_asset_identity_snapshot")
    old = {(str(row["root_id"]), str(row["canonical_path"])): row for row in previous["files"]}
    new = {(str(row["root_id"]), str(row["canonical_path"])): row for row in current["files"]}
    removed_keys = sorted(set(old) - set(new))
    added_keys = sorted(set(new) - set(old))
    changed = []
    metadata_only = []
    for key in sorted(set(old) & set(new)):
        if old[key]["sha256"] != new[key]["sha256"]:
            changed.append(_key_record(key, old[key]["sha256"], new[key]["sha256"]))
        elif (
            old[key]["size_bytes"] != new[key]["size_bytes"]
            or old[key]["mtime_ns"] != new[key]["mtime_ns"]
            or old[key]["file_id"] != new[key]["file_id"]
        ):
            metadata_only.append(_key_record(key, old[key]["sha256"], new[key]["sha256"]))
    added_by_sha = _keys_by_sha(added_keys, new)
    removed_by_sha = _keys_by_sha(removed_keys, old)
    moves = []
    consumed_added: set[tuple[str, str]] = set()
    consumed_removed: set[tuple[str, str]] = set()
    for sha256 in sorted(set(added_by_sha) & set(removed_by_sha)):
        if len(added_by_sha[sha256]) == 1 and len(removed_by_sha[sha256]) == 1:
            source = removed_by_sha[sha256][0]
            destination = added_by_sha[sha256][0]
            moves.append(
                {
                    "sha256": sha256,
                    "from": _key_record(source),
                    "to": _key_record(destination),
                }
            )
            consumed_removed.add(source)
            consumed_added.add(destination)
    old_conflicts = {str(row["logical_key"]): row for row in previous["logical_conflicts"]}
    new_conflicts = {str(row["logical_key"]): row for row in current["logical_conflicts"]}
    document = {
        "schema_version": "1.0.0",
        "previous_snapshot_id": previous["snapshot_id"],
        "current_snapshot_id": current["snapshot_id"],
        "added": [
            _key_record(key, new[key]["sha256"]) for key in added_keys if key not in consumed_added
        ],
        "removed": [
            _key_record(key, old[key]["sha256"])
            for key in removed_keys
            if key not in consumed_removed
        ],
        "content_changed": changed,
        "metadata_changed": metadata_only,
        "moves": moves,
        "new_shadow_conflicts": sorted(set(new_conflicts) - set(old_conflicts)),
        "resolved_shadow_conflicts": sorted(set(old_conflicts) - set(new_conflicts)),
        "changed_shadow_conflicts": sorted(
            key
            for key in set(old_conflicts) & set(new_conflicts)
            if old_conflicts[key] != new_conflicts[key]
        ),
    }
    document["diff_sha256"] = _canonical_sha(document)
    return document


def publish_asset_identity_snapshot(
    snapshot: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    require_valid_document(snapshot, "daz_asset_identity_snapshot")
    snapshot_id = str(snapshot["snapshot_id"])
    payload = (json.dumps(snapshot, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{snapshot_id}.json"
    if target.exists():
        if target.read_bytes() != payload:
            raise AssetIdentityError(
                "identity_snapshot_immutable_conflict", "existing snapshot bytes differ"
            )
        return target, False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{snapshot_id}.", suffix=".tmp", dir=output_root
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_name, target)
        except FileExistsError:
            if target.read_bytes() != payload:
                raise AssetIdentityError(
                    "identity_snapshot_immutable_conflict", "concurrent snapshot bytes differ"
                )
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return target, True


def _synchronize_identity_state(
    inventory_state: Path,
    identity_state: Path,
    roots: tuple[ContentRoot, ...],
) -> int:
    inventory = sqlite3.connect(f"file:{inventory_state}?mode=ro", uri=True, timeout=30)
    try:
        inventory.execute("PRAGMA query_only=ON")
        quick = inventory.execute("PRAGMA quick_check").fetchone()
        if quick is None or quick[0] != "ok":
            raise AssetIdentityError("inventory_state_corrupt", "inventory quick_check failed")
        stored_roots = json.loads(
            inventory.execute("SELECT value FROM metadata WHERE key='roots_json'").fetchone()[0]
        )
        _verify_roots_match(stored_roots, roots)
        inventory_fingerprint = inventory.execute(
            "SELECT value FROM metadata WHERE key='root_fingerprint'"
        ).fetchone()[0]
        rows = inventory.execute(
            "SELECT root_id,relative_path,canonical_path,logical_uri,size_bytes,mtime_ns,file_id "
            "FROM files ORDER BY root_id,canonical_path"
        ).fetchall()
    finally:
        inventory.close()
    root_map = {root.root_id: root for root in roots}
    identity_state.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(identity_state, timeout=30)
    try:
        _configure_identity_connection(connection)
        _create_identity_schema(connection)
        row = connection.execute(
            "SELECT value FROM metadata WHERE key='root_fingerprint'"
        ).fetchone()
        if row is None:
            connection.executemany(
                "INSERT INTO metadata(key,value) VALUES (?,?)",
                (
                    ("schema_version", str(IDENTITY_STATE_SCHEMA_VERSION)),
                    ("root_fingerprint", str(inventory_fingerprint)),
                    ("created_at", utcnow()),
                ),
            )
        elif row[0] != inventory_fingerprint:
            raise AssetIdentityError(
                "identity_roots_changed", "identity state belongs to another root set"
            )
        before_complete = int(
            connection.execute("SELECT count(*) FROM files WHERE state='complete'").fetchone()[0]
        )
        connection.execute("DROP TABLE IF EXISTS temp.current_keys")
        connection.execute(
            "CREATE TEMP TABLE current_keys(root_id TEXT,canonical_path TEXT,PRIMARY KEY(root_id,canonical_path))"
        )
        upsert = (
            "INSERT INTO files(root_id,relative_path,canonical_path,logical_uri,size_bytes,mtime_ns,"
            "file_id,root_priority,source_kind,sha256,state,error_code,hashed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,NULL,'pending',NULL,NULL) "
            "ON CONFLICT(root_id,canonical_path) DO UPDATE SET "
            "relative_path=excluded.relative_path,logical_uri=excluded.logical_uri,"
            "root_priority=excluded.root_priority,source_kind=excluded.source_kind,"
            "sha256=CASE WHEN files.size_bytes=excluded.size_bytes AND files.mtime_ns=excluded.mtime_ns "
            "AND files.file_id IS excluded.file_id THEN files.sha256 ELSE NULL END,"
            "state=CASE WHEN files.size_bytes=excluded.size_bytes AND files.mtime_ns=excluded.mtime_ns "
            "AND files.file_id IS excluded.file_id AND files.sha256 IS NOT NULL THEN 'complete' ELSE 'pending' END,"
            "error_code=CASE WHEN files.size_bytes=excluded.size_bytes AND files.mtime_ns=excluded.mtime_ns "
            "AND files.file_id IS excluded.file_id THEN files.error_code ELSE NULL END,"
            "hashed_at=CASE WHEN files.size_bytes=excluded.size_bytes AND files.mtime_ns=excluded.mtime_ns "
            "AND files.file_id IS excluded.file_id THEN files.hashed_at ELSE NULL END,"
            "size_bytes=excluded.size_bytes,mtime_ns=excluded.mtime_ns,file_id=excluded.file_id"
        )
        payloads = []
        keys = []
        for (
            root_id,
            relative_path,
            canonical_path,
            logical_uri,
            size_bytes,
            mtime_ns,
            file_id,
        ) in rows:
            root = root_map[str(root_id)]
            payloads.append(
                (
                    root_id,
                    relative_path,
                    canonical_path,
                    logical_uri,
                    size_bytes,
                    mtime_ns,
                    file_id,
                    root.priority,
                    root.source_kind,
                )
            )
            keys.append((root_id, canonical_path))
        connection.executemany(upsert, payloads)
        connection.executemany(
            "INSERT INTO current_keys(root_id,canonical_path) VALUES (?,?)", keys
        )
        connection.execute(
            "DELETE FROM files WHERE NOT EXISTS (SELECT 1 FROM current_keys k "
            "WHERE k.root_id=files.root_id AND k.canonical_path=files.canonical_path)"
        )
        connection.commit()
        _verify_identity_integrity(connection)
        after_complete = int(
            connection.execute("SELECT count(*) FROM files WHERE state='complete'").fetchone()[0]
        )
        return min(before_complete, after_complete)
    finally:
        connection.close()


def _resolve_identity_rows(
    rows: Iterable[sqlite3.Row],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    source = [dict(row) for row in rows]
    by_logical: dict[str, list[dict[str, Any]]] = {}
    for row in source:
        by_logical.setdefault(str(row["canonical_path"]), []).append(row)
    output: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for logical_key in sorted(by_logical):
        candidates = sorted(
            by_logical[logical_key],
            key=lambda row: (int(row["root_priority"]), str(row["root_id"])),
        )
        hashes = {str(row["sha256"]) for row in candidates}
        if len(candidates) == 1:
            statuses = ("unique",)
        elif len(hashes) == 1:
            statuses = ("duplicate_winner",) + ("duplicate_copy",) * (len(candidates) - 1)
        else:
            statuses = ("shadow_conflict",) * len(candidates)
            conflicts.append(
                {
                    "logical_key": logical_key,
                    "logical_uri": str(candidates[0]["logical_uri"]),
                    "resolution": "explicit_technical_resolution_required",
                    "candidates": [
                        {
                            "root_id": str(row["root_id"]),
                            "sha256": str(row["sha256"]),
                            "size_bytes": int(row["size_bytes"]),
                        }
                        for row in candidates
                    ],
                }
            )
        for rank, (row, status_name) in enumerate(zip(candidates, statuses, strict=True), 1):
            sha256 = str(row["sha256"])
            asset_id = (
                "ast_"
                + hashlib.sha256((logical_key + "\0" + sha256).encode("utf-8")).hexdigest()[:24]
            )
            output.append(
                {
                    "asset_id": asset_id,
                    "root_id": str(row["root_id"]),
                    "relative_path": str(row["relative_path"]),
                    "canonical_path": logical_key,
                    "logical_uri": str(row["logical_uri"]),
                    "sha256": sha256,
                    "size_bytes": int(row["size_bytes"]),
                    "mtime_ns": int(row["mtime_ns"]),
                    "file_id": row["file_id"],
                    "root_priority": int(row["root_priority"]),
                    "source_kind": str(row["source_kind"]),
                    "logical_status": status_name,
                    "precedence_rank": rank,
                    "eligible": status_name in {"unique", "duplicate_winner"},
                }
            )
    output.sort(key=lambda row: (row["root_priority"], row["root_id"], row["canonical_path"]))
    by_hash: dict[str, set[str]] = {}
    for row in output:
        by_hash.setdefault(str(row["sha256"]), set()).add(str(row["asset_id"]))
    duplicate_groups = [
        {
            "group_id": f"dup_{sha256[:24]}",
            "sha256": sha256,
            "asset_ids": sorted(asset_ids),
        }
        for sha256, asset_ids in sorted(by_hash.items())
        if len(asset_ids) > 1
    ]
    return output, conflicts, duplicate_groups


def _normalize_roots(roots: Iterable[ContentRoot]) -> tuple[ContentRoot, ...]:
    normalized = []
    seen_ids: set[str] = set()
    for root in roots:
        if not root.root_id or root.root_id in seen_ids:
            raise AssetIdentityError("identity_root_invalid", "root IDs must be unique")
        raw_path = Path(root.path)
        observed = raw_path.stat(follow_symlinks=False)
        if (
            raw_path.is_symlink()
            or int(getattr(observed, "st_file_attributes", 0)) & FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise AssetIdentityError(
                "identity_root_reparse_prohibited", f"root is a reparse point: {root.root_id}"
            )
        path = raw_path.resolve(strict=True)
        if not path.is_dir():
            raise AssetIdentityError("identity_root_invalid", f"not a directory: {root.root_id}")
        seen_ids.add(root.root_id)
        normalized.append(ContentRoot(root.root_id, path, int(root.priority), root.source_kind))
    if not normalized:
        raise AssetIdentityError("identity_roots_missing", "at least one root is required")
    return tuple(sorted(normalized, key=lambda root: (root.priority, root.root_id)))


def _verify_roots_match(stored: list[dict[str, Any]], roots: tuple[ContentRoot, ...]) -> None:
    expected = [
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
    if stored != expected:
        raise AssetIdentityError(
            "identity_inventory_root_mismatch", "inventory and hashing roots differ"
        )


def _configure_identity_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=30000")


def _create_identity_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS files(
          root_id TEXT NOT NULL,
          relative_path TEXT NOT NULL,
          canonical_path TEXT NOT NULL,
          logical_uri TEXT NOT NULL,
          size_bytes INTEGER NOT NULL CHECK(size_bytes>=0),
          mtime_ns INTEGER NOT NULL,
          file_id TEXT,
          root_priority INTEGER NOT NULL,
          source_kind TEXT NOT NULL,
          sha256 TEXT,
          state TEXT NOT NULL CHECK(state IN ('pending','complete','failed')),
          error_code TEXT,
          hashed_at TEXT,
          PRIMARY KEY(root_id,canonical_path),
          CHECK((state='complete' AND length(sha256)=64) OR (state!='complete' AND sha256 IS NULL))
        );
        """
    )


def _verify_identity_integrity(connection: sqlite3.Connection) -> None:
    quick = connection.execute("PRAGMA quick_check").fetchone()
    if quick is None or quick[0] != "ok":
        raise AssetIdentityError("identity_state_corrupt", "identity quick_check failed")
    version = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
    if version is not None and version[0] != str(IDENTITY_STATE_SCHEMA_VERSION):
        raise AssetIdentityError("identity_state_version", "unsupported identity state version")


def _path_under_root(root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise AssetIdentityError("identity_path_escape", "inventory path escapes root")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AssetIdentityError("identity_path_escape", "resolved path escapes root") from exc
    return path


def _verify_hash_target(path: Path, observed: os.stat_result) -> None:
    attributes = int(getattr(observed, "st_file_attributes", 0))
    if path.is_symlink() or attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        raise AssetIdentityError("identity_reparse_prohibited", "hash target is a reparse point")
    if not stat.S_ISREG(observed.st_mode):
        raise AssetIdentityError("identity_target_not_file", "hash target is not a regular file")


def _stat_matches(
    observed: os.stat_result, size_bytes: int, mtime_ns: int, file_id: object
) -> bool:
    if int(observed.st_size) != size_bytes or int(observed.st_mtime_ns) != mtime_ns:
        return False
    if file_id is None:
        return True
    observed_id = f"{int(observed.st_dev):x}:{int(observed.st_ino):x}"
    return observed_id == str(file_id)


def _leave_pending(
    connection: sqlite3.Connection, root_id: str, canonical_path: str, error_code: str
) -> None:
    connection.execute(
        "UPDATE files SET state='pending',sha256=NULL,error_code=?,hashed_at=? "
        "WHERE root_id=? AND canonical_path=?",
        (error_code, utcnow(), root_id, canonical_path),
    )
    connection.commit()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _key_record(
    key: tuple[str, str], old_sha256: str | None = None, new_sha256: str | None = None
) -> dict[str, Any]:
    record: dict[str, Any] = {"root_id": key[0], "canonical_path": key[1]}
    if old_sha256 is not None:
        record["old_sha256"] = old_sha256
    if new_sha256 is not None:
        record["new_sha256"] = new_sha256
    return record


def _keys_by_sha(
    keys: Iterable[tuple[str, str]], rows: Mapping[tuple[str, str], Mapping[str, Any]]
) -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {}
    for key in keys:
        result.setdefault(str(rows[key]["sha256"]), []).append(key)
    return result


__all__ = [
    "AssetIdentityError",
    "IdentityChunkResult",
    "asset_identity_state_summary",
    "build_asset_identity_snapshot",
    "diff_asset_identity_snapshots",
    "publish_asset_identity_snapshot",
    "resume_asset_identity_index",
]
