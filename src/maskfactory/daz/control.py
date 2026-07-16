"""Fail-closed DAZ roots, state database, events, and local control state."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path, PurePath
from typing import Any, Mapping

from .policy import DazConfiguration, load_typed_daz_configuration

STATE_SCHEMA_VERSION = 2
ROOT_SCHEMA_VERSION = "1.0.0"
EVENT_SCHEMA = "daz_event_1.0.0"


class DazErrorCode(IntEnum):
    CONFIG_INVALID = 70
    PATH_ESCAPE = 71
    ROOT_IDENTITY_INVALID = 72
    STATE_DATABASE_INVALID = 73
    STATE_MIGRATION_FAILED = 74
    CONTROL_REFUSED = 75
    ASSET_SOURCE_IN_GIT = 80
    DIM_MANIFEST_INVALID = 81
    DIM_CONFIGURATION_INVALID = 82


class DazControlError(ValueError):
    """One stable DAZ control-plane failure with machine-readable details."""

    def __init__(
        self,
        code: DazErrorCode,
        reason: str,
        *,
        entity_ids: tuple[str, ...] = (),
        retryable: bool = False,
        evidence_paths: tuple[str, ...] = (),
    ) -> None:
        self.code = code
        self.reason = reason
        self.entity_ids = entity_ids
        self.retryable = retryable
        self.evidence_paths = evidence_paths
        super().__init__(reason)

    def as_result(self) -> dict[str, Any]:
        return result_envelope(
            code=int(self.code),
            reason=self.reason,
            entity_ids=self.entity_ids,
            retryable=self.retryable,
            evidence_paths=self.evidence_paths,
        )


def result_envelope(
    *,
    code: int = 0,
    reason: str = "ok",
    entity_ids: tuple[str, ...] = (),
    retryable: bool = False,
    evidence_paths: tuple[str, ...] = (),
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "code": code,
        "reason": reason,
        "entity_ids": list(entity_ids),
        "retryable": retryable,
        "evidence_paths": list(evidence_paths),
    }
    if data is not None:
        result["data"] = dict(data)
    return result


@dataclass(frozen=True)
class RegisteredRootResolver:
    canonical_root: Path
    root_uuid: str
    roots: Mapping[str, str]

    @classmethod
    def load(cls, registry_path: Path) -> "RegisteredRootResolver":
        try:
            document = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DazControlError(
                DazErrorCode.ROOT_IDENTITY_INVALID,
                f"registered root file is unreadable: {exc}",
                evidence_paths=(str(registry_path),),
            ) from exc
        if set(document) != {"schema_version", "canonical_root", "root_uuid", "roots"}:
            raise DazControlError(
                DazErrorCode.ROOT_IDENTITY_INVALID,
                "registered root file has unknown or missing fields",
                evidence_paths=(str(registry_path),),
            )
        roots = document["roots"]
        if (
            document["schema_version"] != ROOT_SCHEMA_VERSION
            or not isinstance(document["root_uuid"], str)
            or not isinstance(roots, dict)
            or not roots
            or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in roots.items()
            )
        ):
            raise DazControlError(
                DazErrorCode.ROOT_IDENTITY_INVALID,
                "registered root file violates its closed contract",
                evidence_paths=(str(registry_path),),
            )
        return cls(
            canonical_root=Path(document["canonical_root"]),
            root_uuid=document["root_uuid"],
            roots=roots,
        )

    def resolve(self, root_id: str, relative_path: str | Path = ".") -> Path:
        if root_id not in self.roots:
            raise DazControlError(
                DazErrorCode.PATH_ESCAPE,
                f"unknown registered root: {root_id}",
                entity_ids=(root_id,),
            )
        relative = Path(relative_path)
        if _is_unsafe_relative(relative):
            raise DazControlError(
                DazErrorCode.PATH_ESCAPE,
                f"absolute or traversal path is prohibited: {relative_path}",
                entity_ids=(root_id,),
            )
        canonical = self.canonical_root.resolve(strict=True)
        registered = (canonical / self.roots[root_id]).resolve(strict=False)
        candidate = (registered / relative).resolve(strict=False)
        if not _is_relative_to(registered, canonical) or not _is_relative_to(candidate, registered):
            raise DazControlError(
                DazErrorCode.PATH_ESCAPE,
                f"registered path escapes F:\\DAZ authority: {relative_path}",
                entity_ids=(root_id,),
            )
        return candidate


def _is_unsafe_relative(path: PurePath) -> bool:
    raw = str(path)
    return (
        path.is_absolute()
        or path.drive != ""
        or raw.startswith(("\\", "/"))
        or any(part == ".." for part in path.parts)
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


DIRECTORY_TREE = {
    "00_control": (),
    "01_source_records": (
        "products",
        "install_manifests",
        "file_inventories",
        "dependency_snapshots",
    ),
    "02_installers": (
        "dim_downloads",
        "manual_packages",
        "manual_packages/_incoming_unsorted",
        "manual_packages/_needs_classification",
        "manual_packages/_ready_for_install",
        "manual_packages/_installed_archives",
        "manual_packages/_failed_install",
        "manual_packages/asset_dropzone/genesis_9",
        "manual_packages/asset_dropzone/genesis_8_1",
        "manual_packages/asset_dropzone/genesis_8",
        "manual_packages/asset_dropzone/generation_neutral",
        "manual_packages/asset_dropzone/other_or_unknown",
        "application_installers",
        "plugin_installers",
        "checksums",
    ),
    "03_content": (
        "libraries/MaskFactory_DAZ_Library",
        "libraries/MaskFactory_User_Library",
        "cloud_cache_disabled",
        "content_overrides",
    ),
    "04_runtime": (
        "scripts/active",
        "scripts/versions",
        "app_profiles/MaskFactoryDAZ",
        "render_profiles",
        "plugin_inventory",
        "runtime_snapshots",
    ),
    "05_registry": ("live", "snapshots", "diffs", "overrides", "rebuild_evidence"),
    "06_asset_staging": (
        "discovered",
        "inspect_pending",
        "smoke_pending",
        "mapping_pending",
        "eligible",
        "retired",
    ),
    "07_mappings": (
        "genesis9/body_parts_v1",
        "genesis9/body_parts_v2",
        "genesis8_1/body_parts_v1",
        "genesis8_1/body_parts_v2",
        "genesis8/body_parts_v1",
        "genesis8/body_parts_v2",
        "geografts",
        "wardrobe_transfer",
        "hair",
        "golden_fixtures",
        "revoked",
    ),
    "08_asset_tests": ("jobs", "previews", "certificates", "failures", "quarantine", "retest"),
    "09_generation": (
        "policies",
        "coverage_demands",
        "sampling_plans",
        "recipe_templates",
        "scene_recipes",
        "family_manifests",
    ),
    "10_queue": (
        "pending",
        "leased",
        "running",
        "retry",
        "failed",
        "complete",
        "leases",
        "heartbeats",
    ),
    "11_scene_state": ("partial", "assembled", "snapshots", "debug_duf", "rejected"),
    "12_renders": ("pristine", "derived", "thumbnails", "rejected"),
    "13_annotations": (
        "instance_id",
        "part_id",
        "material_id",
        "protected_id",
        "depth",
        "normals",
        "alpha",
        "relationships",
        "amodal_diagnostic",
        "body_part_levels/01_major",
        "body_part_levels/02_sub",
        "body_part_levels/03_micro",
        "body_part_levels/04_nano",
    ),
    "14_scene_packages": ("draft", "validating", "accepted", "rejected", "revoked"),
    "15_datasets": ("builds", "cards", "manifests", "sample_weights", "synthetic_diagnostics"),
    "16_maskfactory_exports": ("intake_ready", "ingested", "rejected", "pointers"),
    "17_logs": ("worker", "daz_studio", "render", "validation", "scheduler", "audit", "incidents"),
    "18_reports": ("daily", "weekly", "coverage", "assets", "mappings", "storage", "training"),
    "19_cache": (
        "compiled_shaders",
        "textures",
        "simulations",
        "geometry",
        "thumbnails",
        "decoder",
    ),
    "20_tmp": ("worker", "decode", "package", "downloads"),
    "21_backups": (
        "control",
        "registries",
        "mappings",
        "recipes",
        "package_metadata",
        "restore_tests",
    ),
    "22_dvc": ("cache", "local_remote", "locks"),
    "23_exports": ("reports_redacted", "support_bundles_redacted"),
    "99_archive": ("runtime_versions", "registry_snapshots", "mappings", "corpus_versions"),
}

REGISTERED_ROOTS = {
    "daz_root": ".",
    "control": "00_control",
    "content_primary": "03_content/libraries/MaskFactory_DAZ_Library",
    "content_user": "03_content/libraries/MaskFactory_User_Library",
    "registry": "05_registry",
    "mappings": "07_mappings",
    "generation": "09_generation",
    "queue": "10_queue",
    "renders": "12_renders",
    "annotations": "13_annotations",
    "packages": "14_scene_packages",
    "datasets": "15_datasets",
    "exports": "16_maskfactory_exports",
    "logs": "17_logs",
    "temporary": "20_tmp",
    "backups": "21_backups",
}


def initialize_daz_root(root: Path, *, apply: bool) -> dict[str, Any]:
    root = Path(root)
    expected = tuple(
        sorted(
            {top for top in DIRECTORY_TREE}
            | {f"{top}/{child}" for top, children in DIRECTORY_TREE.items() for child in children}
        )
    )
    missing = [relative for relative in expected if not (root / relative).is_dir()]
    identity_path = root / "00_control" / "root_identity.json"
    identity: dict[str, Any] | None = None
    if identity_path.is_file():
        try:
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DazControlError(
                DazErrorCode.ROOT_IDENTITY_INVALID,
                f"root identity is unreadable: {exc}",
                evidence_paths=(str(identity_path),),
            ) from exc
        if identity.get("canonical_path", "").casefold() != str(root).casefold():
            raise DazControlError(
                DazErrorCode.ROOT_IDENTITY_INVALID,
                "root identity canonical path mismatch",
                evidence_paths=(str(identity_path),),
            )
    registry_path = root / "00_control" / "path_registry.json"
    actions = {
        "create_directories": missing,
        "create_root_identity": identity is None,
        "create_path_registry": not registry_path.is_file(),
    }
    if apply:
        for relative in expected:
            (root / relative).mkdir(parents=True, exist_ok=True)
        if identity is None:
            identity = {
                "schema_version": ROOT_SCHEMA_VERSION,
                "root_uuid": str(uuid.uuid4()),
                "created_at_utc": _utc_now(),
                "canonical_path": str(root),
                "filesystem": "NTFS" if os.name == "nt" else "fixture",
            }
            _atomic_write_json(identity_path, identity)
        registry = {
            "schema_version": ROOT_SCHEMA_VERSION,
            "canonical_root": str(root),
            "root_uuid": identity["root_uuid"],
            "roots": REGISTERED_ROOTS,
        }
        if registry_path.is_file():
            existing = RegisteredRootResolver.load(registry_path)
            if (
                existing.canonical_root != root
                or existing.root_uuid != identity["root_uuid"]
                or dict(existing.roots) != REGISTERED_ROOTS
            ):
                raise DazControlError(
                    DazErrorCode.ROOT_IDENTITY_INVALID,
                    "existing path registry differs from the frozen root contract",
                    evidence_paths=(str(registry_path),),
                )
        else:
            _atomic_write_json(registry_path, registry)
    return result_envelope(
        reason="daz_root_initialization_plan" if not apply else "daz_root_initialized",
        evidence_paths=(str(identity_path), str(registry_path)),
        data={"root": str(root), "apply": apply, "actions": actions},
    )


TABLE_NAMES = (
    "registry_snapshots",
    "assets",
    "asset_certificates",
    "mapping_bundles",
    "coverage_demands",
    "scene_recipes",
    "jobs",
    "leases",
    "scene_outputs",
    "validation_results",
    "scene_certificates",
    "package_exports",
    "dataset_membership",
    "events",
)

MIGRATION_1 = """
BEGIN IMMEDIATE;
CREATE TABLE registry_snapshots (snapshot_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE assets (asset_id TEXT PRIMARY KEY, state TEXT NOT NULL, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE asset_certificates (certificate_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(asset_id), status TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE mapping_bundles (mapping_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE coverage_demands (demand_id TEXT PRIMARY KEY, state TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE scene_recipes (scene_id TEXT PRIMARY KEY, family_id TEXT NOT NULL, state TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE jobs (job_id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES scene_recipes(scene_id), state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0);
CREATE TABLE leases (lease_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id), owner_pid INTEGER NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE scene_outputs (output_id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES scene_recipes(scene_id), role TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE validation_results (result_id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES scene_recipes(scene_id), status TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE scene_certificates (certificate_id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES scene_recipes(scene_id), status TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE package_exports (package_id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES scene_recipes(scene_id), state TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE dataset_membership (dataset_id TEXT NOT NULL, package_id TEXT NOT NULL REFERENCES package_exports(package_id), split TEXT NOT NULL, PRIMARY KEY(dataset_id, package_id));
CREATE TABLE events (event_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, event_type TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, job_id TEXT, attempt INTEGER, data_json TEXT NOT NULL);
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT NOT NULL);
"""

MIGRATION_2 = """
BEGIN IMMEDIATE;
CREATE TRIGGER events_no_update
BEFORE UPDATE ON events
BEGIN
  SELECT RAISE(ABORT, 'DAZ_EVENTS_APPEND_ONLY');
END;
CREATE TRIGGER events_no_delete
BEFORE DELETE ON events
BEGIN
  SELECT RAISE(ABORT, 'DAZ_EVENTS_APPEND_ONLY');
END;
"""


def initialize_state_database(path: Path) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        connection = sqlite3.connect(path, timeout=10)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            journal_mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
            source_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            applied: list[int] = []
            if source_version > STATE_SCHEMA_VERSION:
                raise DazControlError(
                    DazErrorCode.STATE_MIGRATION_FAILED,
                    f"state database version {source_version} is newer than supported {STATE_SCHEMA_VERSION}",
                    evidence_paths=(str(path),),
                )
            if source_version < 1:
                connection.executescript(MIGRATION_1)
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?,?,?)",
                    (1, "initial DAZ control-plane schema", _utc_now()),
                )
                connection.execute("PRAGMA user_version=1")
                connection.commit()
                applied.append(1)
            if source_version < 2:
                connection.executescript(MIGRATION_2)
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?,?,?)",
                    (2, "make operational events append-only", _utc_now()),
                )
                connection.execute("PRAGMA user_version=2")
                connection.commit()
                applied.append(2)
        finally:
            connection.close()
    except DazControlError:
        raise
    except sqlite3.Error as exc:
        raise DazControlError(
            DazErrorCode.STATE_MIGRATION_FAILED,
            f"state database migration failed: {exc}",
            retryable=True,
            evidence_paths=(str(path),),
        ) from exc
    report = inspect_state_database(path)
    report["source_version"] = source_version
    report["applied_migrations"] = applied
    report["journal_mode"] = journal_mode
    return result_envelope(
        reason="state_database_initialized",
        evidence_paths=(str(path),),
        data=report,
    )


def inspect_state_database(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise DazControlError(
            DazErrorCode.STATE_DATABASE_INVALID,
            "state database does not exist",
            evidence_paths=(str(path),),
        )
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            connection.execute("PRAGMA query_only=ON")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            journal = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            foreign_key_errors = len(connection.execute("PRAGMA foreign_key_check").fetchall())
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise DazControlError(
            DazErrorCode.STATE_DATABASE_INVALID,
            f"state database integrity read failed: {exc}",
            retryable=True,
            evidence_paths=(str(path),),
        ) from exc
    missing = sorted(set(TABLE_NAMES + ("schema_migrations",)) - tables)
    passed = (
        version == STATE_SCHEMA_VERSION
        and journal == "wal"
        and quick_check == "ok"
        and not foreign_key_errors
        and not missing
    )
    return {
        "path": str(path),
        "schema_version": version,
        "journal_mode": journal,
        "quick_check": quick_check,
        "foreign_key_error_count": foreign_key_errors,
        "missing_tables": missing,
        "passed": passed,
    }


def build_event(
    event_type: str,
    entity_type: str,
    entity_id: str,
    data: Mapping[str, Any],
    *,
    job_id: str | None = None,
    attempt: int | None = None,
    timestamp: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    if not event_type or "." not in event_type or not entity_type or not entity_id:
        raise DazControlError(DazErrorCode.STATE_DATABASE_INVALID, "event identity is invalid")
    return {
        "event_schema": EVENT_SCHEMA,
        "event_id": event_id or f"evt_{uuid.uuid4().hex}",
        "timestamp": timestamp or _utc_now(),
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "job_id": job_id,
        "attempt": attempt,
        "data": dict(data),
    }


def append_event(path: Path, event: Mapping[str, Any]) -> None:
    expected = {
        "event_schema",
        "event_id",
        "timestamp",
        "event_type",
        "entity_type",
        "entity_id",
        "job_id",
        "attempt",
        "data",
    }
    if (
        set(event) != expected
        or event.get("event_schema") != EVENT_SCHEMA
        or not isinstance(event.get("data"), Mapping)
    ):
        raise DazControlError(
            DazErrorCode.STATE_DATABASE_INVALID, "event violates the closed event contract"
        )
    connection = sqlite3.connect(path, timeout=10)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
            (
                event["event_id"],
                event["timestamp"],
                event["event_type"],
                event["entity_type"],
                event["entity_id"],
                event["job_id"],
                event["attempt"],
                json.dumps(event["data"], sort_keys=True, separators=(",", ":")),
            ),
        )
        connection.commit()
    except sqlite3.Error as exc:
        raise DazControlError(
            DazErrorCode.STATE_DATABASE_INVALID,
            f"event append failed: {exc}",
            evidence_paths=(str(path),),
        ) from exc
    finally:
        connection.close()


def read_control_state(configuration: DazConfiguration) -> dict[str, Any]:
    path = configuration.paths.root / "00_control" / "runtime_state.json"
    if not path.is_file():
        return {
            "schema_version": "1.0.0",
            "revision": 0,
            "enabled": False,
            "paused": True,
            "drain": True,
            "stop_requested": False,
            "reason": "checked_in_default_disabled",
            "updated_at": None,
            "previous_sha256": None,
        }
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DazControlError(
            DazErrorCode.CONTROL_REFUSED,
            f"runtime control state is unreadable: {exc}",
            evidence_paths=(str(path),),
        ) from exc
    if set(state) != {
        "schema_version",
        "revision",
        "enabled",
        "paused",
        "drain",
        "stop_requested",
        "reason",
        "updated_at",
        "previous_sha256",
    }:
        raise DazControlError(
            DazErrorCode.CONTROL_REFUSED, "runtime control state has contract drift"
        )
    return state


def set_control_state(
    configuration: DazConfiguration,
    action: str,
    *,
    reason: str,
    apply: bool,
    free_gib: float | None = None,
) -> dict[str, Any]:
    if action not in {"enable", "disable", "stop"} or not reason.strip():
        raise DazControlError(DazErrorCode.CONTROL_REFUSED, "control action or reason is invalid")
    current = read_control_state(configuration)
    if action == "enable":
        available = free_gib
        if available is None:
            available = _disk_free_gib(configuration.paths.root)
        if available < configuration.paths.storage_thresholds_gib.soft:
            raise DazControlError(
                DazErrorCode.CONTROL_REFUSED,
                f"enable refused below storage soft floor: {available:.3f} GiB",
                retryable=True,
            )
        values = {"enabled": True, "paused": False, "drain": False, "stop_requested": False}
    elif action == "disable":
        values = {"enabled": False, "paused": True, "drain": True, "stop_requested": False}
    else:
        values = {"enabled": False, "paused": True, "drain": True, "stop_requested": True}
    next_state = {
        "schema_version": "1.0.0",
        "revision": int(current["revision"]) + 1,
        **values,
        "reason": reason.strip(),
        "updated_at": _utc_now(),
        "previous_sha256": _canonical_sha256(current),
    }
    path = configuration.paths.root / "00_control" / "runtime_state.json"
    if apply:
        _atomic_write_json(path, next_state)
    return result_envelope(
        reason=f"control_{action}_{'applied' if apply else 'planned'}",
        evidence_paths=(str(path),),
        data={"apply": apply, "before": current, "after": next_state},
    )


def load_control_configuration(config_root: Path) -> DazConfiguration:
    try:
        return load_typed_daz_configuration(config_root)
    except ValueError as exc:
        raise DazControlError(DazErrorCode.CONFIG_INVALID, str(exc)) from exc


def _disk_free_gib(root: Path) -> float:
    return (
        os.statvfs(root).f_bavail * os.statvfs(root).f_frsize / (1024**3)
        if os.name != "nt"
        else __import__("shutil").disk_usage(root).free / (1024**3)
    )


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "DazControlError",
    "DazErrorCode",
    "RegisteredRootResolver",
    "append_event",
    "build_event",
    "initialize_daz_root",
    "initialize_state_database",
    "inspect_state_database",
    "load_control_configuration",
    "read_control_state",
    "result_envelope",
    "set_control_state",
]
