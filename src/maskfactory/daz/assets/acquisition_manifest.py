"""Deterministic index of manifests emitted by the autonomous acquisition workers."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .filesystem_inventory import FilesystemInventoryError, canonicalize_relative_path, utcnow

MAX_MANIFEST_BYTES = 32 * 1024 * 1024
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-f]{16,64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ROOT_ALIASES = {
    "mf_daz_library": "content_primary",
    "maskfactory_daz_library": "content_primary",
    "mf_user_library": "content_user",
    "maskfactory_user_library": "content_user",
    "mf_scene_packages": "scene_packages",
}
ROOT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
SAFE_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class AcquisitionManifestError(ValueError):
    """One stable refusal to index an unsafe autonomous-acquisition manifest."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


@dataclass(frozen=True)
class AcquisitionManifestSummary:
    source_fingerprint: str
    manifest_count: int
    product_count: int
    package_count: int
    file_occurrence_count: int
    unique_logical_path_count: int
    conflicting_logical_path_count: int
    unregistered_source_root_count: int
    total_declared_bytes: int
    index_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_fingerprint": self.source_fingerprint,
            "manifest_count": self.manifest_count,
            "product_count": self.product_count,
            "package_count": self.package_count,
            "file_occurrence_count": self.file_occurrence_count,
            "unique_logical_path_count": self.unique_logical_path_count,
            "conflicting_logical_path_count": self.conflicting_logical_path_count,
            "unregistered_source_root_count": self.unregistered_source_root_count,
            "total_declared_bytes": self.total_declared_bytes,
            "index_path": str(self.index_path),
        }


@dataclass(frozen=True)
class AcquisitionManifestProgress:
    discovered_manifest_count: int
    indexed_manifest_count: int
    pending_manifest_count: int
    failed_manifest_count: int
    indexed_this_chunk: int
    complete: bool
    source_fingerprint: str | None
    index_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "discovered_manifest_count": self.discovered_manifest_count,
            "indexed_manifest_count": self.indexed_manifest_count,
            "pending_manifest_count": self.pending_manifest_count,
            "failed_manifest_count": self.failed_manifest_count,
            "indexed_this_chunk": self.indexed_this_chunk,
            "complete": self.complete,
            "source_fingerprint": self.source_fingerprint,
            "index_path": str(self.index_path),
        }


def resume_acquisition_manifest_index(
    manifest_directory: Path,
    index_path: Path,
    *,
    max_manifests: int = 25,
    reset: bool = False,
    root_aliases: Mapping[str, str] = ROOT_ALIASES,
) -> AcquisitionManifestProgress:
    """Index a bounded manifest chunk while preserving an auditable resume queue."""

    if max_manifests <= 0:
        raise AcquisitionManifestError("manifest_budget_invalid", "max_manifests must be positive")
    manifest_directory = Path(manifest_directory).resolve(strict=True)
    if not manifest_directory.is_dir():
        raise AcquisitionManifestError("manifest_root_invalid", "manifest root is not a directory")
    index_path = Path(index_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if reset and index_path.exists():
        index_path.unlink()
    connection = sqlite3.connect(index_path, timeout=30)
    indexed = 0
    try:
        _configure(connection)
        _create_schema(connection)
        _initialize_metadata(connection)
        _refresh_source_queue(connection, manifest_directory)
        pending = connection.execute(
            "SELECT manifest_name FROM source_queue WHERE state='pending' "
            "ORDER BY manifest_name LIMIT ?",
            (max_manifests,),
        ).fetchall()
        for (manifest_name,) in pending:
            path = manifest_directory / str(manifest_name)
            raw = _read_manifest(path)
            current = path.stat()
            expected = connection.execute(
                "SELECT size_bytes,mtime_ns FROM source_queue WHERE manifest_name=?",
                (manifest_name,),
            ).fetchone()
            if expected != (int(current.st_size), int(current.st_mtime_ns)):
                raise AcquisitionManifestError(
                    "manifest_changed_during_scan", f"source changed: {manifest_name}"
                )
            connection.execute("BEGIN IMMEDIATE")
            try:
                _index_one_manifest(
                    connection,
                    path=path,
                    raw=raw,
                    root_aliases=root_aliases,
                )
                connection.execute(
                    "UPDATE source_queue SET state='complete',manifest_sha256=?,error_code=NULL "
                    "WHERE manifest_name=?",
                    (hashlib.sha256(raw).hexdigest(), manifest_name),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                connection.execute(
                    "UPDATE source_queue SET state='failed',error_code='parse_or_index_failure' "
                    "WHERE manifest_name=?",
                    (manifest_name,),
                )
                connection.commit()
                raise
            indexed += 1
        return _progress(connection, index_path, indexed)
    except (AcquisitionManifestError, FilesystemInventoryError):
        raise
    except (OSError, sqlite3.Error) as exc:
        raise AcquisitionManifestError("index_resume_failed", type(exc).__name__) from exc
    finally:
        connection.close()


def build_acquisition_manifest_index(
    manifest_directory: Path,
    index_path: Path,
    *,
    root_aliases: Mapping[str, str] = ROOT_ALIASES,
) -> AcquisitionManifestSummary:
    """Parse one immutable listing and atomically publish its SQLite index."""

    manifest_directory = Path(manifest_directory).resolve(strict=True)
    if not manifest_directory.is_dir():
        raise AcquisitionManifestError("manifest_root_invalid", "manifest root is not a directory")
    paths = sorted(manifest_directory.glob("*.yaml"), key=lambda path: path.name.casefold())
    index_path = Path(index_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{index_path.stem}.", suffix=".sqlite", dir=index_path.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    connection = sqlite3.connect(temporary, timeout=30)
    source_digest = hashlib.sha256()
    try:
        _configure(connection)
        _create_schema(connection)
        _initialize_metadata(connection)
        seen_manifest_ids: set[str] = set()
        for path in paths:
            raw = _read_manifest(path)
            manifest_sha = hashlib.sha256(raw).hexdigest()
            source_digest.update(path.name.encode("utf-8"))
            source_digest.update(bytes.fromhex(manifest_sha))
            document = _parse_document(raw, path.name)
            manifest_id = _required_id(document, "manifest_id", path.name)
            if manifest_id in seen_manifest_ids:
                raise AcquisitionManifestError(
                    "manifest_id_duplicate", f"duplicate manifest identity: {manifest_id}"
                )
            seen_manifest_ids.add(manifest_id)
            _index_one_manifest(
                connection,
                path=path,
                raw=raw,
                root_aliases=root_aliases,
                parsed_document=document,
            )
        fingerprint = source_digest.hexdigest()
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key,value) VALUES ('source_fingerprint',?)",
            (fingerprint,),
        )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise AcquisitionManifestError(
                "index_integrity_failed", "SQLite integrity check failed"
            )
        summary = _summary(connection, fingerprint, index_path)
        connection.close()
        os.replace(temporary, index_path)
        return summary
    except (AcquisitionManifestError, FilesystemInventoryError):
        connection.close()
        raise
    except (OSError, sqlite3.Error) as exc:
        connection.close()
        raise AcquisitionManifestError("index_build_failed", type(exc).__name__) from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def reconcile_acquisition_with_inventory(
    acquisition_index: Path, inventory_state: Path
) -> dict[str, int | bool]:
    """Compare manifest occurrences to filesystem paths without hashing or mutation."""

    acquisition_index = Path(acquisition_index).resolve(strict=True)
    inventory_state = Path(inventory_state).resolve(strict=True)
    connection = sqlite3.connect(acquisition_index, timeout=30)
    try:
        _configure(connection)
        connection.execute("ATTACH DATABASE ? AS inventory", (str(inventory_state),))
        inventory_roots = {
            str(row[0])
            for row in connection.execute("SELECT DISTINCT root_id FROM inventory.directories")
        }
        inventory_states = dict(
            connection.execute("SELECT state,count(*) FROM inventory.directories GROUP BY state")
        )
        inventory_complete = (
            int(inventory_states.get("pending", 0)) == 0
            and int(inventory_states.get("failed", 0)) == 0
        )
        placeholders = ",".join("?" for _ in inventory_roots)
        if inventory_roots:
            present_occurrences = connection.execute(
                "SELECT count(*) FROM file_occurrences a JOIN inventory.files f "
                "ON f.root_id=a.root_id AND f.canonical_path=a.canonical_path "
                f"WHERE a.root_id IN ({placeholders})",
                tuple(sorted(inventory_roots)),
            ).fetchone()[0]
            missing_occurrences = connection.execute(
                "SELECT count(*) FROM file_occurrences a LEFT JOIN inventory.files f "
                "ON f.root_id=a.root_id AND f.canonical_path=a.canonical_path "
                f"WHERE a.root_id IN ({placeholders}) AND f.root_id IS NULL",
                tuple(sorted(inventory_roots)),
            ).fetchone()[0]
        else:
            present_occurrences = missing_occurrences = 0
        out_of_scope = connection.execute(
            "SELECT count(*) FROM file_occurrences WHERE root_id NOT IN "
            "(SELECT DISTINCT root_id FROM inventory.directories)"
        ).fetchone()[0]
        unmanifested_files = connection.execute(
            "SELECT count(*) FROM inventory.files f LEFT JOIN file_occurrences a "
            "ON f.root_id=a.root_id AND f.canonical_path=a.canonical_path "
            "WHERE a.root_id IS NULL"
        ).fetchone()[0]
        size_mismatches = connection.execute(
            "SELECT count(*) FROM file_occurrences a JOIN inventory.files f "
            "ON f.root_id=a.root_id AND f.canonical_path=a.canonical_path "
            "WHERE f.size_bytes<>a.size_bytes"
        ).fetchone()[0]
        return {
            "inventory_complete": inventory_complete,
            "present_manifest_occurrences": int(present_occurrences),
            "missing_manifest_occurrences": int(missing_occurrences),
            "unmanifested_files": int(unmanifested_files),
            "size_mismatches": int(size_mismatches),
            "out_of_scope_manifest_occurrences": int(out_of_scope),
        }
    except sqlite3.Error as exc:
        raise AcquisitionManifestError("reconciliation_failed", type(exc).__name__) from exc
    finally:
        connection.close()


def _read_manifest(path: Path) -> bytes:
    if path.is_symlink():
        raise AcquisitionManifestError(
            "manifest_symlink", f"symlink manifest prohibited: {path.name}"
        )
    size = path.stat().st_size
    if size <= 0 or size > MAX_MANIFEST_BYTES:
        raise AcquisitionManifestError(
            "manifest_size_invalid", f"{path.name}: bytes must be 1..{MAX_MANIFEST_BYTES}"
        )
    return path.read_bytes()


def _parse_document(raw: bytes, name: str) -> dict[str, Any]:
    try:
        document = yaml.load(raw, Loader=SAFE_YAML_LOADER)
    except yaml.YAMLError as exc:
        raise AcquisitionManifestError(
            "manifest_yaml_invalid", f"{name}: {type(exc).__name__}"
        ) from exc
    if not isinstance(document, dict):
        raise AcquisitionManifestError("manifest_shape_invalid", f"{name}: root must be an object")
    return document


def _index_one_manifest(
    connection: sqlite3.Connection,
    *,
    path: Path,
    raw: bytes,
    root_aliases: Mapping[str, str],
    parsed_document: dict[str, Any] | None = None,
) -> None:
    document = parsed_document or _parse_document(raw, path.name)
    manifest_id = _required_id(document, "manifest_id", path.name)
    product = _required_mapping(document, "product", path.name)
    product_id = _required_id(product, "product_id", path.name)
    packages = document.get("packages")
    if not isinstance(packages, list) or not packages:
        raise AcquisitionManifestError(
            "packages_invalid", f"{path.name}: packages must be a nonempty list"
        )
    package_ids = tuple(
        _required_id(package, "package_id", path.name)
        for package in packages
        if isinstance(package, dict)
    )
    if len(package_ids) != len(packages) or len(set(package_ids)) != len(package_ids):
        raise AcquisitionManifestError(
            "packages_invalid", f"{path.name}: package records are malformed or duplicated"
        )
    manifest_sha = hashlib.sha256(raw).hexdigest()
    connection.execute(
        "INSERT INTO manifests(manifest_id,manifest_name,manifest_sha256,product_id) VALUES (?,?,?,?)",
        (manifest_id, path.name, manifest_sha, product_id),
    )
    connection.executemany(
        "INSERT INTO packages(package_id,manifest_id,product_id) VALUES (?,?,?)",
        ((package_id, manifest_id, product_id) for package_id in package_ids),
    )
    files = document.get("files")
    if not isinstance(files, list):
        raise AcquisitionManifestError("files_invalid", f"{path.name}: files must be a list")
    _insert_files(
        connection,
        manifest_id=manifest_id,
        package_ids=set(package_ids),
        files=files,
        manifest_name=path.name,
        root_aliases=root_aliases,
    )


def _required_mapping(document: Mapping[str, Any], key: str, name: str) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise AcquisitionManifestError("manifest_shape_invalid", f"{name}: {key} must be an object")
    return value


def _required_id(document: Mapping[str, Any], key: str, name: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise AcquisitionManifestError("identity_invalid", f"{name}: {key} is invalid")
    return value


def _insert_files(
    connection: sqlite3.Connection,
    *,
    manifest_id: str,
    package_ids: set[str],
    files: list[Any],
    manifest_name: str,
    root_aliases: Mapping[str, str],
) -> None:
    seen: set[tuple[str, str]] = set()
    for position, item in enumerate(files):
        if not isinstance(item, dict):
            raise AcquisitionManifestError(
                "file_record_invalid", f"{manifest_name}: file {position} must be an object"
            )
        file_id = _required_id(item, "file_id", manifest_name)
        package_id = _required_id(item, "package_id", manifest_name)
        if package_id not in package_ids:
            raise AcquisitionManifestError(
                "file_package_unresolved", f"{manifest_name}: {file_id} package is not declared"
            )
        raw_root = item.get("content_root_id")
        if not isinstance(raw_root, str) or ROOT_ID_PATTERN.fullmatch(raw_root) is None:
            raise AcquisitionManifestError(
                "content_root_invalid", f"{manifest_name}: {file_id} content root is invalid"
            )
        mapped_root = root_aliases.get(raw_root)
        root_state = "registered" if mapped_root is not None else "unregistered"
        if mapped_root is None:
            mapped_root = (
                "unregistered_" + hashlib.sha256(raw_root.encode("utf-8")).hexdigest()[:16]
            )
        raw_relative = item.get("installed_relative_path")
        if not isinstance(raw_relative, str):
            raise AcquisitionManifestError(
                "installed_path_invalid", f"{manifest_name}: {file_id} path is missing"
            )
        display, canonical, logical_uri = canonicalize_relative_path(raw_relative)
        key = (mapped_root, canonical)
        if key in seen:
            raise AcquisitionManifestError(
                "manifest_path_duplicate", f"{manifest_name}: duplicate logical path {canonical}"
            )
        seen.add(key)
        sha256 = item.get("sha256")
        size = item.get("size_bytes")
        if not isinstance(sha256, str) or SHA256_PATTERN.fullmatch(sha256) is None:
            raise AcquisitionManifestError(
                "file_hash_invalid", f"{manifest_name}: {file_id} SHA-256 is invalid"
            )
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise AcquisitionManifestError(
                "file_size_invalid", f"{manifest_name}: {file_id} size is invalid"
            )
        connection.execute(
            "INSERT INTO file_occurrences(manifest_id,file_id,package_id,source_root_id,root_id,root_state,"
            "relative_path,canonical_path,logical_uri,sha256,size_bytes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                manifest_id,
                file_id,
                package_id,
                raw_root,
                key[0],
                root_state,
                display,
                canonical,
                logical_uri,
                sha256,
                size,
            ),
        )


def _configure(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_queue(
          manifest_name TEXT PRIMARY KEY,
          size_bytes INTEGER NOT NULL,
          mtime_ns INTEGER NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('pending','complete','failed')),
          manifest_sha256 TEXT,
          error_code TEXT
        );
        CREATE TABLE IF NOT EXISTS manifests(
          manifest_id TEXT PRIMARY KEY,
          manifest_name TEXT NOT NULL UNIQUE,
          manifest_sha256 TEXT NOT NULL,
          product_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS packages(
          package_id TEXT PRIMARY KEY,
          manifest_id TEXT NOT NULL REFERENCES manifests(manifest_id),
          product_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS file_occurrences(
          manifest_id TEXT NOT NULL REFERENCES manifests(manifest_id),
          file_id TEXT NOT NULL,
          package_id TEXT NOT NULL REFERENCES packages(package_id),
          source_root_id TEXT NOT NULL,
          root_id TEXT NOT NULL,
          root_state TEXT NOT NULL CHECK(root_state IN ('registered','unregistered')),
          relative_path TEXT NOT NULL,
          canonical_path TEXT NOT NULL,
          logical_uri TEXT NOT NULL,
          sha256 TEXT NOT NULL,
          size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
          PRIMARY KEY(manifest_id,file_id),
          UNIQUE(manifest_id,root_id,canonical_path)
        );
        CREATE INDEX IF NOT EXISTS file_occurrences_path ON file_occurrences(root_id,canonical_path);
        CREATE INDEX IF NOT EXISTS file_occurrences_hash ON file_occurrences(sha256);
        """
    )


def _initialize_metadata(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "INSERT OR IGNORE INTO metadata(key,value) VALUES (?,?)",
        (
            ("schema_version", "1"),
            ("captured_at", utcnow()),
            ("source_scope", "autonomous_acquisition_manifests_only"),
        ),
    )
    connection.commit()


def _refresh_source_queue(connection: sqlite3.Connection, directory: Path) -> None:
    observed_names: set[str] = set()
    for path in sorted(directory.glob("*.yaml"), key=lambda item: item.name.casefold()):
        observed = path.stat()
        observed_names.add(path.name)
        existing = connection.execute(
            "SELECT size_bytes,mtime_ns,state FROM source_queue WHERE manifest_name=?",
            (path.name,),
        ).fetchone()
        identity = (int(observed.st_size), int(observed.st_mtime_ns))
        if existing is None:
            connection.execute(
                "INSERT INTO source_queue(manifest_name,size_bytes,mtime_ns,state) "
                "VALUES (?,?,?,'pending')",
                (path.name, *identity),
            )
        elif existing[:2] != identity:
            raise AcquisitionManifestError(
                "published_manifest_changed", f"published source changed: {path.name}"
            )
    missing = [
        row[0]
        for row in connection.execute("SELECT manifest_name FROM source_queue")
        if row[0] not in observed_names
    ]
    if missing:
        raise AcquisitionManifestError(
            "published_manifest_removed", f"published source disappeared: {missing[0]}"
        )
    connection.commit()


def _progress(
    connection: sqlite3.Connection, index_path: Path, indexed_this_chunk: int
) -> AcquisitionManifestProgress:
    states = dict(connection.execute("SELECT state,count(*) FROM source_queue GROUP BY state"))
    pending = int(states.get("pending", 0))
    failed = int(states.get("failed", 0))
    complete = pending == 0 and failed == 0
    fingerprint = None
    if complete:
        digest = hashlib.sha256()
        for name, sha256 in connection.execute(
            "SELECT manifest_name,manifest_sha256 FROM source_queue ORDER BY manifest_name"
        ):
            digest.update(str(name).encode("utf-8"))
            digest.update(bytes.fromhex(str(sha256)))
        fingerprint = digest.hexdigest()
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key,value) VALUES ('source_fingerprint',?)",
            (fingerprint,),
        )
        connection.commit()
    return AcquisitionManifestProgress(
        discovered_manifest_count=sum(int(value) for value in states.values()),
        indexed_manifest_count=int(states.get("complete", 0)),
        pending_manifest_count=pending,
        failed_manifest_count=failed,
        indexed_this_chunk=indexed_this_chunk,
        complete=complete,
        source_fingerprint=fingerprint,
        index_path=index_path,
    )


def _summary(
    connection: sqlite3.Connection, fingerprint: str, index_path: Path
) -> AcquisitionManifestSummary:
    manifest_count = connection.execute("SELECT count(*) FROM manifests").fetchone()[0]
    product_count = connection.execute(
        "SELECT count(DISTINCT product_id) FROM manifests"
    ).fetchone()[0]
    package_count = connection.execute("SELECT count(*) FROM packages").fetchone()[0]
    occurrence_count, unique_paths, total_bytes = connection.execute(
        "SELECT count(*),count(DISTINCT root_id || char(0) || canonical_path),"
        "coalesce(sum(size_bytes),0) FROM file_occurrences"
    ).fetchone()
    conflicts = connection.execute(
        "SELECT count(*) FROM (SELECT root_id,canonical_path FROM file_occurrences "
        "GROUP BY root_id,canonical_path HAVING count(DISTINCT sha256)>1)"
    ).fetchone()[0]
    unregistered_roots = connection.execute(
        "SELECT count(DISTINCT source_root_id) FROM file_occurrences WHERE root_state='unregistered'"
    ).fetchone()[0]
    return AcquisitionManifestSummary(
        source_fingerprint=fingerprint,
        manifest_count=int(manifest_count),
        product_count=int(product_count),
        package_count=int(package_count),
        file_occurrence_count=int(occurrence_count),
        unique_logical_path_count=int(unique_paths),
        conflicting_logical_path_count=int(conflicts),
        unregistered_source_root_count=int(unregistered_roots),
        total_declared_bytes=int(total_bytes),
        index_path=index_path,
    )
