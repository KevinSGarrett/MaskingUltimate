"""Read-only DAZ CMS observation with an explicit filesystem-only fallback."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from ...validation import require_valid_document
from .filesystem_inventory import (
    ContentRoot,
    FilesystemInventoryError,
    canonicalize_relative_path,
    inventory_state_summary,
)

DEFAULT_CONFIG = Path(r"C:\Users\kevin\AppData\Roaming\DAZ 3D\cms\cmscfg.json")
DEFAULT_PSQL = Path(r"C:\Program Files\DAZ 3D\PostgreSQL CMS\bin\psql.exe")
Runner = Callable[[Sequence[str], str, Mapping[str, str]], subprocess.CompletedProcess[str]]


class CmsObservationError(ValueError):
    """A stable CMS query/configuration failure."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


@dataclass(frozen=True)
class CmsConnection:
    port: int
    cluster_path_fingerprint: str


def load_cms_connection(config_path: Path = DEFAULT_CONFIG) -> CmsConnection:
    try:
        document = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CmsObservationError("cms_config_unreadable", type(exc).__name__) from exc
    if set(document) != {"DatabaseClusterPath", "Port"}:
        raise CmsObservationError("cms_config_shape", "CMS config has unknown or missing fields")
    cluster = document["DatabaseClusterPath"]
    port = document["Port"]
    if not isinstance(cluster, str) or not isinstance(port, int) or isinstance(port, bool):
        raise CmsObservationError("cms_config_type", "CMS path/port types are invalid")
    if not 1 <= port <= 65535:
        raise CmsObservationError("cms_config_port", "CMS port is outside 1..65535")
    return CmsConnection(
        port=port,
        cluster_path_fingerprint=hashlib.sha256(
            os.path.normcase(cluster).encode("utf-8")
        ).hexdigest(),
    )


def query_cms_snapshot(
    *,
    registered_roots: Iterable[ContentRoot],
    config_path: Path = DEFAULT_CONFIG,
    psql_path: Path = DEFAULT_PSQL,
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Query only local CMS views in a forced read-only transaction."""

    connection = load_cms_connection(config_path)
    psql_path = Path(psql_path)
    if not psql_path.is_file():
        raise CmsObservationError("psql_missing", "local DAZ CMS psql executable is missing")
    roots = tuple(registered_roots)
    if not roots:
        raise CmsObservationError(
            "registered_roots_missing", "at least one content root is required"
        )
    execute = runner or _run_psql
    sql = _cms_sql()
    command = (
        str(psql_path),
        "-X",
        "-h",
        "127.0.0.1",
        "-p",
        str(connection.port),
        "-U",
        "dzcms",
        "-d",
        "Content",
        "-Atq",
        "-v",
        "ON_ERROR_STOP=1",
        "-f",
        "-",
    )
    environment = {
        "PGOPTIONS": "-c default_transaction_read_only=on -c statement_timeout=15000",
        "PGCONNECT_TIMEOUT": "5",
    }
    completed = execute(command, sql, environment)
    if completed.returncode != 0:
        detail = _safe_failure(completed.stderr)
        raise CmsObservationError("cms_query_failed", detail)
    records = _parse_tagged_rows(completed.stdout)
    root_rows = records.get("root", [])
    product_rows = records.get("product", [])
    content_rows = records.get("content", [])
    mapped_roots = [_map_cms_root(row, roots) for row in root_rows]
    resolved_root_ids = sorted(
        {
            row["registered_root_id"]
            for row in mapped_roots
            if isinstance(row.get("registered_root_id"), str)
        }
    )
    contents = [_normalize_content(row, resolved_root_ids) for row in content_rows]
    canonical = {
        "schema_version": "1.0.0",
        "source_kind": "online_local_cms_read_only",
        "cms_available": True,
        "connection": {
            "host": "127.0.0.1",
            "port": connection.port,
            "database": "Content",
            "cluster_path_fingerprint": connection.cluster_path_fingerprint,
            "credentials_stored": False,
        },
        "content_roots": mapped_roots,
        "products": sorted(product_rows, key=lambda row: int(row["cms_product_id"])),
        "contents": sorted(contents, key=lambda row: int(row["cms_content_id"])),
        "metadata_gaps": [],
    }
    fingerprint = _canonical_sha(canonical)
    canonical["snapshot_id"] = f"cms_{fingerprint[:24]}"
    canonical["canonical_sha256"] = fingerprint
    require_valid_document(canonical, "daz_cms_snapshot")
    return canonical


def build_offline_cms_fallback(
    *,
    registered_roots: Iterable[ContentRoot],
    inventory_state: Path,
    failure_reason_code: str = "cms_unavailable",
) -> dict[str, Any]:
    """Represent filesystem authority honestly when CMS cannot be queried."""

    roots = sorted(tuple(registered_roots), key=lambda root: (root.priority, root.root_id))
    summary = inventory_state_summary(inventory_state)
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "source_kind": "offline_filesystem_fallback",
        "cms_available": False,
        "failure_reason_code": failure_reason_code,
        "registered_roots": [
            {
                "root_id": root.root_id,
                "priority": root.priority,
                "source_kind": root.source_kind,
                "path_fingerprint": hashlib.sha256(
                    os.path.normcase(str(Path(root.path).resolve(strict=True))).encode("utf-8")
                ).hexdigest(),
            }
            for root in roots
        ],
        "filesystem_inventory": summary,
        "metadata_gaps": [
            "CMS product identity unavailable",
            "CMS content categories unavailable",
            "CMS compatibility bases unavailable",
            "CMS file-to-product membership unavailable except through other manifests",
        ],
    }
    fingerprint = _canonical_sha(document)
    document["snapshot_id"] = f"cms_offline_{fingerprint[:24]}"
    document["canonical_sha256"] = fingerprint
    require_valid_document(document, "daz_cms_snapshot")
    return document


def compare_cms_with_inventory(
    cms_snapshot: Mapping[str, Any], inventory_state: Path
) -> dict[str, int]:
    """Compare CMS logical paths to the independently observed filesystem state."""

    import sqlite3

    contents = cms_snapshot.get("contents")
    if not isinstance(contents, list):
        raise CmsObservationError("cms_snapshot_invalid", "online CMS contents are missing")
    connection = sqlite3.connect(Path(inventory_state), timeout=30)
    matched = missing = unresolved = 0
    try:
        for item in contents:
            if not isinstance(item, dict):
                raise CmsObservationError("cms_snapshot_invalid", "CMS content row is malformed")
            root_id = item.get("registered_root_id")
            canonical = item.get("canonical_path")
            if not isinstance(root_id, str) or not isinstance(canonical, str):
                unresolved += 1
                continue
            found = connection.execute(
                "SELECT 1 FROM files WHERE root_id=? AND canonical_path=? LIMIT 1",
                (root_id, canonical),
            ).fetchone()
            if found is None:
                missing += 1
            else:
                matched += 1
        return {
            "cms_content_rows": len(contents),
            "matched_filesystem_paths": matched,
            "missing_filesystem_paths": missing,
            "unresolved_cms_roots": unresolved,
        }
    except (sqlite3.Error, FilesystemInventoryError) as exc:
        raise CmsObservationError("cms_inventory_comparison_failed", type(exc).__name__) from exc
    finally:
        connection.close()


def publish_cms_snapshot(snapshot: Mapping[str, Any], output_root: Path) -> tuple[Path, bool]:
    snapshot_id = snapshot.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id.startswith("cms_"):
        raise CmsObservationError("cms_snapshot_identity", "snapshot identity is invalid")
    payload = (json.dumps(snapshot, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{snapshot_id}.json"
    if target.exists():
        if target.read_bytes() != payload:
            raise CmsObservationError("cms_snapshot_conflict", "immutable snapshot bytes differ")
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


def _run_psql(
    command: Sequence[str], sql: str, environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in tuple(env):
        if key.upper() in {"PGPASSWORD", "PGPASSFILE", "PGSERVICE"}:
            env.pop(key, None)
    env.update(environment)
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.run(
        list(command),
        input=sql,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=25,
        env=env,
        creationflags=creationflags,
    )


def _cms_sql() -> str:
    return r"""
BEGIN TRANSACTION READ ONLY;
SELECT 'root' || chr(9) || row_to_json(x)::text FROM (
  SELECT "RecID"::bigint AS cms_root_id, "fldBasePath"::text AS base_path
  FROM dzcontent."tblBasePath" ORDER BY "RecID"
) x;
SELECT 'product' || chr(9) || row_to_json(x)::text FROM (
  SELECT id::bigint AS cms_product_id, guid::text AS guid, name::text AS name,
         artists::text AS artists, date_installed::text AS date_installed
  FROM dzcontent.product WHERE is_installed ORDER BY id
) x;
SELECT 'content' || chr(9) || row_to_json(x)::text FROM (
  SELECT id::bigint AS cms_content_id, product_id::bigint AS cms_product_id,
         file_and_path::text AS relative_path, content_type_id::bigint AS content_type_id,
         compatibility_base_id::bigint AS compatibility_base_id,
         user_facing::boolean AS user_facing
  FROM dzcontent.content WHERE is_installed ORDER BY id
) x;
COMMIT;
""".strip()


def _parse_tagged_rows(output: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"root": [], "product": [], "content": []}
    for line in output.splitlines():
        if not line.strip() or line.strip() in {"BEGIN", "COMMIT"}:
            continue
        tag, separator, payload = line.partition("\t")
        if separator != "\t" or tag not in result:
            raise CmsObservationError("cms_output_invalid", "unexpected untagged CMS output")
        try:
            row = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise CmsObservationError("cms_output_invalid", "CMS row is not valid JSON") from exc
        if not isinstance(row, dict):
            raise CmsObservationError("cms_output_invalid", "CMS row must be an object")
        result[tag].append(row)
    return result


def _map_cms_root(row: Mapping[str, Any], roots: Iterable[ContentRoot]) -> dict[str, Any]:
    root_id = row.get("cms_root_id")
    path = row.get("base_path")
    if not isinstance(root_id, int) or not isinstance(path, str):
        raise CmsObservationError("cms_root_invalid", "CMS root row is malformed")
    observed = os.path.normcase(os.path.normpath(path))
    registered = None
    for root in roots:
        candidate = os.path.normcase(os.path.normpath(str(Path(root.path).resolve(strict=True))))
        if candidate == observed:
            registered = root.root_id
            break
    return {
        "cms_root_id": root_id,
        "registered_root_id": registered,
        "path_state": "registered" if registered else "unregistered",
        "path_fingerprint": hashlib.sha256(observed.encode("utf-8")).hexdigest(),
    }


def _normalize_content(row: Mapping[str, Any], resolved_roots: list[str]) -> dict[str, Any]:
    content_id = row.get("cms_content_id")
    product_id = row.get("cms_product_id")
    relative = row.get("relative_path")
    if not isinstance(content_id, int) or not isinstance(relative, str):
        raise CmsObservationError("cms_content_invalid", "CMS content row is malformed")
    try:
        display, canonical, logical_uri = canonicalize_relative_path(relative)
    except FilesystemInventoryError as exc:
        raise CmsObservationError("cms_content_path_invalid", exc.reason_code) from exc
    registered_root_id = resolved_roots[0] if len(resolved_roots) == 1 else None
    return {
        "cms_content_id": content_id,
        "cms_product_id": product_id if isinstance(product_id, int) else None,
        "registered_root_id": registered_root_id,
        "relative_path": display,
        "canonical_path": canonical,
        "logical_uri": logical_uri,
        "content_type_id": row.get("content_type_id"),
        "compatibility_base_id": row.get("compatibility_base_id"),
        "user_facing": bool(row.get("user_facing")),
    }


def _safe_failure(stderr: str) -> str:
    folded = stderr.casefold()
    if "timeout" in folded:
        return "timeout"
    if "connection" in folded:
        return "connection_failed"
    if "does not exist" in folded:
        return "schema_missing"
    return "psql_failed"


def _canonical_sha(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
