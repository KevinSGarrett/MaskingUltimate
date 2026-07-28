"""Build and verify byte-exact, resumable corpus-mirror migration manifests."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "maskfactory.corpus_mirror_migration_manifest.v1"
INVENTORY_NAME = "MIGRATION_INVENTORY.sqlite"
MANIFEST_NAME = "MIGRATION_MANIFEST.json"
PROGRESS_NAME = "MIGRATION_PROGRESS.json"
EXCLUDED_ARTIFACTS = frozenset(
    {
        INVENTORY_NAME,
        MANIFEST_NAME,
        PROGRESS_NAME,
        f"{INVENTORY_NAME}-shm",
        f"{INVENTORY_NAME}-wal",
    }
)
EPHEMERAL_SQLITE_SUFFIXES = (
    ".sqlite-shm",
    ".sqlite-wal",
    ".db-shm",
    ".db-wal",
)


class CorpusMirrorManifestError(ValueError):
    """The corpus-mirror manifest or inventory is unsafe or inconsistent."""


@dataclass(frozen=True)
class CorpusMirrorBuildResult:
    manifest_path: Path
    inventory_path: Path
    entry_count: int
    total_bytes: int
    tree_sha256: str
    manifest_sha256: str
    inventory_sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_relative(value: str) -> Path:
    relative = Path(value)
    if (
        not value
        or relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != value
    ):
        raise CorpusMirrorManifestError(f"unsafe inventory path: {value!r}")
    return relative


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _connect_inventory(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            bytes INTEGER NOT NULL CHECK(bytes >= 0),
            mtime_ns INTEGER NOT NULL CHECK(mtime_ns >= 0),
            sha256 TEXT NOT NULL CHECK(length(sha256) = 64)
        );
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    return connection


def _metadata(connection: sqlite3.Connection) -> dict[str, str]:
    return dict(connection.execute("SELECT key, value FROM metadata"))


def _set_metadata(connection: sqlite3.Connection, key: str, value: object) -> None:
    connection.execute(
        """
        INSERT INTO metadata(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, str(value)),
    )


def _inventory_rows(
    connection: sqlite3.Connection,
) -> list[tuple[str, int, str]]:
    return [
        (str(path), int(size), str(digest))
        for path, size, digest in connection.execute(
            "SELECT path, bytes, sha256 FROM files ORDER BY path"
        )
    ]


def _tree_summary(
    rows: list[tuple[str, int, str]],
) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    total_bytes = 0
    for relative, size, file_sha256 in rows:
        _safe_relative(relative)
        if not _is_sha256(file_sha256):
            raise CorpusMirrorManifestError(f"invalid inventory digest for {relative}")
        digest.update(f"{relative}\0{size}\0{file_sha256}\n".encode("utf-8"))
        total_bytes += size
    return len(rows), total_bytes, digest.hexdigest()


def _source_files(source_root: Path, output_dir: Path) -> list[Path]:
    output_paths = {(output_dir / name).resolve(strict=False) for name in EXCLUDED_ARTIFACTS}
    files: list[Path] = []
    casefolded: dict[str, str] = {}
    for path in source_root.rglob("*"):
        if path.resolve(strict=False) in output_paths:
            continue
        if path.is_symlink():
            raise CorpusMirrorManifestError(f"symlink is not allowed in corpus mirror: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(source_root).as_posix()
        if relative in EXCLUDED_ARTIFACTS or relative.lower().endswith(EPHEMERAL_SQLITE_SUFFIXES):
            continue
        _safe_relative(relative)
        folded = relative.casefold()
        if folded in casefolded and casefolded[folded] != relative:
            raise CorpusMirrorManifestError(
                "case-insensitive path collision: " f"{casefolded[folded]!r} and {relative!r}"
            )
        casefolded[folded] = relative
        files.append(path)
    files.sort(key=lambda item: item.relative_to(source_root).as_posix())
    return files


def build_corpus_mirror_manifest(
    *,
    source_root: Path,
    destination_root: Path,
    output_dir: Path,
    asset_id: str,
    batch_size: int = 1000,
) -> CorpusMirrorBuildResult:
    """Hash a source tree into a restart-safe SQLite inventory and sealed JSON."""

    source_root = source_root.resolve(strict=True)
    destination_posix = destination_root.as_posix()
    destination_binding = (
        destination_posix
        if destination_posix.startswith("/")
        else str(destination_root.resolve(strict=False))
    )
    output_dir = output_dir.resolve(strict=False)
    if not source_root.is_dir():
        raise CorpusMirrorManifestError("source_root must be a directory")
    if not asset_id:
        raise CorpusMirrorManifestError("asset_id is required")
    if batch_size < 1:
        raise CorpusMirrorManifestError("batch_size must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = output_dir / INVENTORY_NAME
    manifest_path = output_dir / MANIFEST_NAME
    progress_path = output_dir / PROGRESS_NAME
    if manifest_path.exists():
        raise CorpusMirrorManifestError("sealed manifest already exists; refuse overwrite")

    connection = _connect_inventory(inventory_path)
    try:
        metadata = _metadata(connection)
        bindings = {
            "schema_version": SCHEMA_VERSION,
            "asset_id": asset_id,
            "source_root": str(source_root),
            "destination_root": destination_binding,
        }
        for key, value in bindings.items():
            existing = metadata.get(key)
            if existing is not None and existing != value:
                raise CorpusMirrorManifestError(f"resume binding mismatch for {key}")
            _set_metadata(connection, key, value)
        _set_metadata(connection, "complete", "false")
        connection.commit()

        files = _source_files(source_root, output_dir)
        current_paths: set[str] = set()
        hashed = 0
        reused = 0
        for index, path in enumerate(files, start=1):
            relative = path.relative_to(source_root).as_posix()
            current_paths.add(relative)
            stat = path.stat()
            row = connection.execute(
                "SELECT bytes, mtime_ns, sha256 FROM files WHERE path=?",
                (relative,),
            ).fetchone()
            if (
                row is not None
                and int(row[0]) == stat.st_size
                and int(row[1]) == stat.st_mtime_ns
                and _is_sha256(row[2])
            ):
                reused += 1
            else:
                before_hash = stat
                file_sha256 = sha256_file(path)
                after_hash = path.stat()
                if (
                    before_hash.st_size != after_hash.st_size
                    or before_hash.st_mtime_ns != after_hash.st_mtime_ns
                ):
                    raise CorpusMirrorManifestError(f"source changed while hashing: {relative}")
                connection.execute(
                    """
                    INSERT INTO files(path, bytes, mtime_ns, sha256)
                    VALUES(?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        bytes=excluded.bytes,
                        mtime_ns=excluded.mtime_ns,
                        sha256=excluded.sha256
                    """,
                    (
                        relative,
                        after_hash.st_size,
                        after_hash.st_mtime_ns,
                        file_sha256,
                    ),
                )
                hashed += 1
            if index % batch_size == 0:
                connection.commit()
                progress = {
                    "schema_version": ("maskfactory.corpus_mirror_migration_progress.v1"),
                    "asset_id": asset_id,
                    "source_root": str(source_root),
                    "destination_root": destination_binding,
                    "discovered_file_count": len(files),
                    "processed_file_count": index,
                    "hashed_file_count": hashed,
                    "reused_file_count": reused,
                    "complete": False,
                    "updated_at": _utc_now(),
                }
                progress["self_sha256"] = canonical_sha256(progress)
                _write_json_atomic(progress_path, progress)

        existing_paths = {str(row[0]) for row in connection.execute("SELECT path FROM files")}
        stale = existing_paths - current_paths
        if stale:
            connection.executemany(
                "DELETE FROM files WHERE path=?",
                ((relative,) for relative in sorted(stale)),
            )
        final_files = _source_files(source_root, output_dir)
        final_paths = {path.relative_to(source_root).as_posix() for path in final_files}
        if final_paths != current_paths:
            raise CorpusMirrorManifestError("source file set changed before manifest seal")
        indexed_stats = {
            str(path): (int(size), int(mtime_ns))
            for path, size, mtime_ns in connection.execute(
                "SELECT path, bytes, mtime_ns FROM files"
            )
        }
        for path in final_files:
            relative = path.relative_to(source_root).as_posix()
            stat = path.stat()
            if indexed_stats.get(relative) != (stat.st_size, stat.st_mtime_ns):
                raise CorpusMirrorManifestError(
                    f"source metadata changed before manifest seal: {relative}"
                )
        rows = _inventory_rows(connection)
        entry_count, total_bytes, tree_sha256 = _tree_summary(rows)
        _set_metadata(connection, "entry_count", entry_count)
        _set_metadata(connection, "total_bytes", total_bytes)
        _set_metadata(connection, "tree_sha256", tree_sha256)
        _set_metadata(connection, "complete", "true")
        _set_metadata(connection, "completed_at", _utc_now())
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()

    # VACUUM after closing the WAL-backed build makes the sealed DB self-contained.
    vacuum = sqlite3.connect(inventory_path)
    try:
        vacuum.execute("VACUUM")
    finally:
        vacuum.close()
    inventory_sha256 = sha256_file(inventory_path)
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "asset_id": asset_id,
        "source_root": str(source_root),
        "destination_root": destination_binding,
        "excluded_artifacts": sorted(EXCLUDED_ARTIFACTS),
        "inventory": {
            "path": INVENTORY_NAME,
            "raw_sha256": inventory_sha256,
            "entry_count": entry_count,
            "total_bytes": total_bytes,
            "tree_sha256": tree_sha256,
        },
        "authority_claimed": False,
        "completed_at": _utc_now(),
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    _write_json_atomic(manifest_path, manifest)
    progress = {
        "schema_version": "maskfactory.corpus_mirror_migration_progress.v1",
        "asset_id": asset_id,
        "source_root": str(source_root),
        "destination_root": destination_binding,
        "discovered_file_count": entry_count,
        "processed_file_count": entry_count,
        "hashed_file_count": hashed,
        "reused_file_count": reused,
        "complete": True,
        "updated_at": _utc_now(),
    }
    progress["self_sha256"] = canonical_sha256(progress)
    _write_json_atomic(progress_path, progress)
    return CorpusMirrorBuildResult(
        manifest_path=manifest_path,
        inventory_path=inventory_path,
        entry_count=entry_count,
        total_bytes=total_bytes,
        tree_sha256=tree_sha256,
        manifest_sha256=str(manifest["manifest_sha256"]),
        inventory_sha256=inventory_sha256,
    )


def _load_manifest(
    manifest_path: Path,
    destination_root: Path,
) -> tuple[dict[str, Any], Path]:
    if manifest_path.parent != destination_root:
        raise CorpusMirrorManifestError("manifest must be stored at the destination root")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusMirrorManifestError(f"manifest unreadable: {exc}") from exc
    if not isinstance(manifest, dict):
        raise CorpusMirrorManifestError("manifest must be a JSON object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise CorpusMirrorManifestError("unsupported corpus manifest schema")
    expected_self = manifest.get("manifest_sha256")
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    if not _is_sha256(expected_self) or canonical_sha256(unsigned) != expected_self:
        raise CorpusMirrorManifestError("manifest self-hash mismatch")
    if manifest.get("destination_root") != str(destination_root):
        raise CorpusMirrorManifestError("destination_root binding mismatch")
    if set(manifest.get("excluded_artifacts") or ()) != EXCLUDED_ARTIFACTS:
        raise CorpusMirrorManifestError("excluded_artifacts binding mismatch")
    inventory = manifest.get("inventory")
    if not isinstance(inventory, dict):
        raise CorpusMirrorManifestError("inventory binding is missing")
    relative = _safe_relative(str(inventory.get("path") or ""))
    if relative.as_posix() != INVENTORY_NAME:
        raise CorpusMirrorManifestError("inventory path binding mismatch")
    inventory_path = (manifest_path.parent / relative).resolve(strict=False)
    try:
        inventory_path.relative_to(manifest_path.parent.resolve(strict=True))
    except ValueError as exc:
        raise CorpusMirrorManifestError("inventory path escapes manifest root") from exc
    return manifest, inventory_path


def verify_corpus_mirror_manifest(
    manifest_path: Path,
    destination_root: Path,
) -> dict[str, Any]:
    """Verify every expected and actual destination byte against the inventory."""

    destination_root = destination_root.resolve(strict=True)
    manifest_path = manifest_path.resolve(strict=True)
    manifest, inventory_path = _load_manifest(manifest_path, destination_root)
    inventory_binding = manifest["inventory"]
    checks: dict[str, bool] = {
        "manifest_contract_valid": True,
        "inventory_present": inventory_path.is_file(),
    }
    issues: list[dict[str, str]] = []
    if not checks["inventory_present"]:
        issues.append({"code": "CORPUS_INVENTORY_MISSING", "detail": str(inventory_path)})
        return {"checks": checks, "issues": issues, "detail": {}}
    checks["inventory_raw_hash"] = (
        _is_sha256(inventory_binding.get("raw_sha256"))
        and sha256_file(inventory_path) == inventory_binding["raw_sha256"]
    )
    if not checks["inventory_raw_hash"]:
        issues.append({"code": "CORPUS_INVENTORY_HASH_DRIFT", "detail": str(inventory_path)})
        return {"checks": checks, "issues": issues, "detail": {}}

    try:
        connection = sqlite3.connect(f"file:{inventory_path}?mode=ro", uri=True)
        try:
            metadata = _metadata(connection)
            rows = _inventory_rows(connection)
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise CorpusMirrorManifestError(f"inventory database is invalid: {exc}") from exc
    expected_count, expected_bytes, expected_tree = _tree_summary(rows)
    checks["inventory_complete"] = metadata.get("complete") == "true"
    checks["inventory_metadata_binding"] = (
        metadata.get("schema_version") == SCHEMA_VERSION
        and metadata.get("asset_id") == manifest.get("asset_id")
        and metadata.get("source_root") == manifest.get("source_root")
        and metadata.get("destination_root") == manifest.get("destination_root")
    )
    checks["inventory_summary_binding"] = (
        int(inventory_binding.get("entry_count", -1)) == expected_count
        and int(inventory_binding.get("total_bytes", -1)) == expected_bytes
        and inventory_binding.get("tree_sha256") == expected_tree
        and metadata.get("entry_count") == str(expected_count)
        and metadata.get("total_bytes") == str(expected_bytes)
        and metadata.get("tree_sha256") == expected_tree
    )
    if not checks["inventory_complete"]:
        issues.append({"code": "CORPUS_INVENTORY_INCOMPLETE", "detail": str(inventory_path)})
    if not checks["inventory_metadata_binding"]:
        issues.append(
            {
                "code": "CORPUS_INVENTORY_METADATA_DRIFT",
                "detail": str(inventory_path),
            }
        )
    if not checks["inventory_summary_binding"]:
        issues.append({"code": "CORPUS_INVENTORY_SUMMARY_DRIFT", "detail": str(inventory_path)})

    expected_paths = {relative for relative, _, _ in rows}
    bytes_valid = True
    for relative, size, digest in rows:
        child = (destination_root / _safe_relative(relative)).resolve(strict=False)
        try:
            child.relative_to(destination_root)
        except ValueError:
            bytes_valid = False
            issues.append({"code": "CORPUS_PATH_ESCAPE", "detail": relative})
            continue
        if child.is_symlink() or not child.is_file():
            bytes_valid = False
            issues.append({"code": "CORPUS_FILE_MISSING", "detail": relative})
            continue
        if child.stat().st_size != size or sha256_file(child) != digest:
            bytes_valid = False
            issues.append({"code": "CORPUS_FILE_DRIFT", "detail": relative})
    checks["all_expected_files_hash_bound"] = bytes_valid

    actual_paths: set[str] = set()
    extra_safe = True
    for child in destination_root.rglob("*"):
        if child.is_symlink():
            extra_safe = False
            issues.append(
                {
                    "code": "CORPUS_SYMLINK_UNSUPPORTED",
                    "detail": child.relative_to(destination_root).as_posix(),
                }
            )
            continue
        if not child.is_file():
            continue
        relative = child.relative_to(destination_root).as_posix()
        if relative in EXCLUDED_ARTIFACTS or relative.lower().endswith(EPHEMERAL_SQLITE_SUFFIXES):
            continue
        actual_paths.add(relative)
    extras = sorted(actual_paths - expected_paths)
    missing = sorted(expected_paths - actual_paths)
    checks["no_unmanifested_files"] = not extras and extra_safe
    checks["all_inventory_paths_present"] = not missing
    if extras:
        issues.append(
            {
                "code": "CORPUS_UNMANIFESTED_FILES",
                "detail": json.dumps(extras[:20], separators=(",", ":")),
            }
        )
    if missing:
        issues.append(
            {
                "code": "CORPUS_INVENTORY_PATHS_MISSING",
                "detail": json.dumps(missing[:20], separators=(",", ":")),
            }
        )
    return {
        "checks": checks,
        "issues": issues,
        "detail": {
            "entry_count": expected_count,
            "total_bytes": expected_bytes,
            "tree_sha256": expected_tree,
            "inventory_sha256": inventory_binding["raw_sha256"],
            "manifest_self_sha256": manifest["manifest_sha256"],
            "extra_file_count": len(extras),
            "missing_file_count": len(missing),
            "extra_paths": extras,
            "missing_paths": missing,
        },
    }
