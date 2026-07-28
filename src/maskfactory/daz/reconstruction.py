"""Clean-root reconstruction from a verified DAZ restore and append-only events."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .control import STATE_SCHEMA_VERSION, DazControlError, DazErrorCode, initialize_state_database

SUPPORTED_JOB_EVENTS = {
    "scheduler.job_leased",
    "scheduler.job_complete",
    "scheduler.job_failed",
    "scheduler.job_retry",
}


def build_reconstruction_manifest_set(
    source_database: Path,
    path_registry: Path,
    *,
    manifest_set_id: str,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Seal the exact scene/job/package state needed for deterministic replay."""
    source = Path(source_database).resolve(strict=True)
    registry = Path(path_registry).resolve(strict=True)
    _validate_source_database(source)
    _validate_path_registry(registry)
    with _open_read_only(source) as connection:
        scenes = [
            _scene_row(row)
            for row in connection.execute(
                "SELECT scene_id,family_id,state,payload_json FROM scene_recipes ORDER BY scene_id"
            )
        ]
        jobs = [
            {
                "job_id": str(row[0]),
                "scene_id": str(row[1]),
                "initial_state": "pending",
                "initial_attempt": 0,
                "expected_state": str(row[2]),
                "expected_attempt": int(row[3]),
            }
            for row in connection.execute(
                "SELECT job_id,scene_id,state,attempt FROM jobs ORDER BY job_id"
            )
        ]
        packages = [
            _package_row(row)
            for row in connection.execute(
                "SELECT package_id,scene_id,state,payload_json FROM package_exports ORDER BY package_id"
            )
        ]
    body = {
        "schema_version": "1.0.0",
        "manifest_set_id": manifest_set_id,
        "captured_at": _timestamp(captured_at),
        "source_database_sha256": _sha256(source),
        "path_registry_sha256": _sha256(registry),
        "scene_recipes": scenes,
        "jobs": jobs,
        "packages": packages,
    }
    document = {**body, "manifest_set_sha256": _canonical_sha256(body)}
    validate_reconstruction_manifest_set(document)
    return document


def publish_reconstruction_manifest_set(
    manifest_set: Mapping[str, Any], output_path: Path
) -> dict[str, Any]:
    """Publish a sealed manifest set immutably and idempotently."""
    validate_reconstruction_manifest_set(manifest_set)
    destination = Path(output_path).resolve()
    payload = json.dumps(dict(manifest_set), indent=2, sort_keys=True) + "\n"
    if destination.exists():
        try:
            existing = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DazControlError(
                DazErrorCode.STATE_DATABASE_INVALID,
                "reconstruction manifest output already exists but is unreadable",
                evidence_paths=(str(destination),),
            ) from exc
        if existing != dict(manifest_set):
            raise DazControlError(
                DazErrorCode.STATE_DATABASE_INVALID,
                "reconstruction manifest output already exists with drift",
                evidence_paths=(str(destination),),
            )
        return {
            "published": False,
            "path": str(destination),
            "manifest_set_sha256": manifest_set["manifest_set_sha256"],
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, destination)
    return {
        "published": True,
        "path": str(destination),
        "manifest_set_sha256": manifest_set["manifest_set_sha256"],
    }


def plan_history_reconstruction(
    source_database: Path,
    path_registry: Path,
    target_database: Path,
    manifest_set: Mapping[str, Any],
) -> dict[str, Any]:
    source = Path(source_database).resolve(strict=True)
    registry = Path(path_registry).resolve(strict=True)
    target = Path(target_database).resolve()
    _validate_bound_inputs(source, registry, target, manifest_set)
    events = _read_events(source)
    replay = _replay_job_history(manifest_set, events)
    return {
        "schema_version": "1.0.0",
        "apply": False,
        "source_database": str(source),
        "target_database": str(target),
        "manifest_set_sha256": manifest_set["manifest_set_sha256"],
        "path_registry_sha256": manifest_set["path_registry_sha256"],
        "scene_count": len(manifest_set["scene_recipes"]),
        "job_count": len(manifest_set["jobs"]),
        "package_count": len(manifest_set["packages"]),
        "event_count": len(events),
        "replay_job_states": replay,
        "source_mutated": False,
    }


def reconstruct_history_to_clean_database(
    source_database: Path,
    path_registry: Path,
    target_database: Path,
    manifest_set: Mapping[str, Any],
    *,
    registry_view_path: Path,
) -> dict[str, Any]:
    """Build a new v4 DB, replay queue events, and publish a sealed registry view."""
    plan = plan_history_reconstruction(
        source_database, path_registry, target_database, manifest_set
    )
    source = Path(source_database).resolve(strict=True)
    target = Path(target_database).resolve()
    view_path = Path(registry_view_path).resolve()
    if target.exists() or view_path.exists():
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "reconstruction target database and registry view must not exist",
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    initialize_state_database(target)
    events = _read_events(source)
    try:
        with sqlite3.connect(target) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            for row in manifest_set["scene_recipes"]:
                connection.execute(
                    "INSERT INTO scene_recipes VALUES (?,?,?,?)",
                    (
                        row["scene_id"],
                        row["family_id"],
                        row["state"],
                        _canonical_text(row["payload"]),
                    ),
                )
            for row in manifest_set["jobs"]:
                connection.execute(
                    "INSERT INTO jobs VALUES (?,?,?,?)",
                    (row["job_id"], row["scene_id"], "pending", 0),
                )
            for row in manifest_set["packages"]:
                connection.execute(
                    "INSERT INTO package_exports VALUES (?,?,?,?)",
                    (
                        row["package_id"],
                        row["scene_id"],
                        row["state"],
                        _canonical_text(row["payload"]),
                    ),
                )
            _apply_job_events(connection, manifest_set, events)
            for event in events:
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
                        _canonical_text(event["data"]),
                    ),
                )
            connection.commit()
    except Exception:
        for candidate in (target, Path(f"{target}-wal"), Path(f"{target}-shm")):
            candidate.unlink(missing_ok=True)
        raise
    comparison = _compare_reconstruction(source, target)
    if not comparison["passed"]:
        raise DazControlError(
            DazErrorCode.STATE_DATABASE_INVALID,
            "reconstructed state does not match the verified restore",
            evidence_paths=(str(source), str(target)),
        )
    view_body = {
        "schema_version": "1.0.0",
        "manifest_set_sha256": manifest_set["manifest_set_sha256"],
        "path_registry_sha256": manifest_set["path_registry_sha256"],
        "source_database_sha256": manifest_set["source_database_sha256"],
        "target_database_sha256": _stable_sqlite_sha256(target),
        "scene_ids": sorted(row["scene_id"] for row in manifest_set["scene_recipes"]),
        "job_states": comparison["job_states"],
        "package_ids": sorted(row["package_id"] for row in manifest_set["packages"]),
        "event_chain_sha256": _canonical_sha256(events),
    }
    view = {**view_body, "registry_view_sha256": _canonical_sha256(view_body)}
    view_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = view_path.with_suffix(view_path.suffix + ".tmp")
    temporary.write_text(json.dumps(view, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, view_path)
    return {
        **plan,
        "apply": True,
        "passed": True,
        "target_database_sha256": view["target_database_sha256"],
        "registry_view_sha256": view["registry_view_sha256"],
        "registry_view_path": str(view_path),
        "queue_integrity": comparison["queue_integrity"],
        "foreign_key_errors": comparison["foreign_key_errors"],
        "duplicate_acceptance": False,
    }


def validate_reconstruction_manifest_set(document: Mapping[str, Any]) -> None:
    schema = json.loads(
        (
            Path(__file__).parents[1] / "schemas/daz_reconstruction_manifest_set.schema.json"
        ).read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.path)
    )
    if errors:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"reconstruction manifest set violates its closed schema: {errors[0].message}",
        )
    body = {key: value for key, value in document.items() if key != "manifest_set_sha256"}
    if document["manifest_set_sha256"] != _canonical_sha256(body):
        raise DazControlError(DazErrorCode.CONFIG_INVALID, "reconstruction manifest seal mismatch")
    for group, identity in (
        ("scene_recipes", "scene_id"),
        ("jobs", "job_id"),
        ("packages", "package_id"),
    ):
        values = [str(row[identity]) for row in document[group]]
        if len(values) != len(set(values)):
            raise DazControlError(DazErrorCode.CONFIG_INVALID, f"duplicate {group} identity")
    for group in ("scene_recipes", "packages"):
        for row in document[group]:
            if row["payload_sha256"] != _canonical_sha256(row["payload"]):
                raise DazControlError(DazErrorCode.CONFIG_INVALID, f"{group} payload seal mismatch")


def _validate_bound_inputs(
    source: Path, registry: Path, target: Path, manifest_set: Mapping[str, Any]
) -> None:
    validate_reconstruction_manifest_set(manifest_set)
    _validate_source_database(source)
    _validate_path_registry(registry)
    if target == source:
        raise DazControlError(DazErrorCode.SCHEDULER_REFUSED, "target must be a new database")
    if manifest_set["source_database_sha256"] != _sha256(source):
        raise DazControlError(DazErrorCode.STATE_DATABASE_INVALID, "restored database hash drift")
    if manifest_set["path_registry_sha256"] != _sha256(registry):
        raise DazControlError(DazErrorCode.STATE_DATABASE_INVALID, "path registry hash drift")


def _validate_source_database(path: Path) -> None:
    with _open_read_only(path) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        leases = int(connection.execute("SELECT count(*) FROM leases").fetchone()[0])
    if version != STATE_SCHEMA_VERSION or integrity != "ok" or foreign_keys or leases:
        raise DazControlError(
            DazErrorCode.STATE_DATABASE_INVALID,
            "reconstruction source must be a healthy drained current-schema restore",
            evidence_paths=(str(path),),
        )


def _validate_path_registry(path: Path) -> None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DazControlError(
            DazErrorCode.ROOT_IDENTITY_INVALID,
            "reconstruction path registry is unreadable",
            evidence_paths=(str(path),),
        ) from exc
    if not isinstance(document, dict):
        raise DazControlError(
            DazErrorCode.ROOT_IDENTITY_INVALID,
            "reconstruction path registry must be a JSON object",
            evidence_paths=(str(path),),
        )


def _read_events(path: Path) -> list[dict[str, Any]]:
    with _open_read_only(path) as connection:
        rows = connection.execute(
            "SELECT event_id,timestamp,event_type,entity_type,entity_id,job_id,attempt,data_json "
            "FROM events ORDER BY rowid"
        ).fetchall()
    events = []
    for row in rows:
        try:
            data = json.loads(row[7])
        except json.JSONDecodeError as exc:
            raise DazControlError(
                DazErrorCode.STATE_DATABASE_INVALID, "event JSON is invalid"
            ) from exc
        if not isinstance(data, dict):
            raise DazControlError(
                DazErrorCode.STATE_DATABASE_INVALID, "event data must be an object"
            )
        events.append(
            {
                "event_id": str(row[0]),
                "timestamp": str(row[1]),
                "event_type": str(row[2]),
                "entity_type": str(row[3]),
                "entity_id": str(row[4]),
                "job_id": str(row[5]) if row[5] is not None else None,
                "attempt": int(row[6]) if row[6] is not None else None,
                "data": data,
            }
        )
    return events


def _replay_job_history(
    manifest_set: Mapping[str, Any], events: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    states = {
        str(row["job_id"]): {"state": "pending", "attempt": 0} for row in manifest_set["jobs"]
    }
    for event in events:
        if event["event_type"] not in SUPPORTED_JOB_EVENTS:
            continue
        job_id = event["job_id"]
        if job_id not in states or event["attempt"] is None:
            raise DazControlError(
                DazErrorCode.STATE_DATABASE_INVALID, "job event identity is invalid"
            )
        state = states[job_id]
        if event["event_type"] == "scheduler.job_leased":
            if (
                state["state"] not in {"pending", "retry"}
                or event["attempt"] != state["attempt"] + 1
            ):
                raise DazControlError(
                    DazErrorCode.STATE_DATABASE_INVALID, "lease event order is invalid"
                )
            state.update(state="leased", attempt=event["attempt"])
        else:
            terminal = event["event_type"].removeprefix("scheduler.job_")
            if state["state"] != "leased" or event["attempt"] != state["attempt"]:
                raise DazControlError(
                    DazErrorCode.STATE_DATABASE_INVALID, "terminal event order is invalid"
                )
            state["state"] = terminal
    expected = {
        str(row["job_id"]): {
            "state": str(row["expected_state"]),
            "attempt": int(row["expected_attempt"]),
        }
        for row in manifest_set["jobs"]
    }
    if states != expected:
        raise DazControlError(DazErrorCode.STATE_DATABASE_INVALID, "event replay is incomplete")
    return {key: states[key] for key in sorted(states)}


def _apply_job_events(
    connection: sqlite3.Connection,
    manifest_set: Mapping[str, Any],
    events: list[dict[str, Any]],
) -> None:
    states = _replay_job_history(manifest_set, events)
    for job_id, state in states.items():
        connection.execute(
            "UPDATE jobs SET state=?,attempt=? WHERE job_id=?",
            (state["state"], state["attempt"], job_id),
        )


def _compare_reconstruction(source: Path, target: Path) -> dict[str, Any]:
    queries = {
        "scenes": "SELECT scene_id,family_id,state,payload_json FROM scene_recipes ORDER BY scene_id",
        "jobs": "SELECT job_id,scene_id,state,attempt FROM jobs ORDER BY job_id",
        "packages": "SELECT package_id,scene_id,state,payload_json FROM package_exports ORDER BY package_id",
        "events": "SELECT event_id,timestamp,event_type,entity_type,entity_id,job_id,attempt,data_json FROM events ORDER BY rowid",
    }
    with _open_read_only(source) as source_db, _open_read_only(target) as target_db:
        matches = {}
        for name, query in queries.items():
            source_rows = source_db.execute(query).fetchall()
            target_rows = target_db.execute(query).fetchall()
            if name in {"scenes", "packages"}:
                source_rows = [(*row[:3], _payload(row[3])) for row in source_rows]
                target_rows = [(*row[:3], _payload(row[3])) for row in target_rows]
            elif name == "events":
                source_rows = [(*row[:7], _payload(row[7])) for row in source_rows]
                target_rows = [(*row[:7], _payload(row[7])) for row in target_rows]
            matches[name] = source_rows == target_rows
        integrity = str(target_db.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = len(list(target_db.execute("PRAGMA foreign_key_check")))
        job_states = {
            str(row[0]): {"state": str(row[1]), "attempt": int(row[2])}
            for row in target_db.execute("SELECT job_id,state,attempt FROM jobs ORDER BY job_id")
        }
    return {
        "passed": all(matches.values()) and integrity == "ok" and foreign_keys == 0,
        "table_matches": matches,
        "queue_integrity": integrity,
        "foreign_key_errors": foreign_keys,
        "job_states": job_states,
    }


def _scene_row(row: tuple[Any, ...]) -> dict[str, Any]:
    payload = _payload(row[3])
    return {
        "scene_id": str(row[0]),
        "family_id": str(row[1]),
        "state": str(row[2]),
        "payload": payload,
        "payload_sha256": _canonical_sha256(payload),
    }


def _package_row(row: tuple[Any, ...]) -> dict[str, Any]:
    payload = _payload(row[3])
    return {
        "package_id": str(row[0]),
        "scene_id": str(row[1]),
        "state": str(row[2]),
        "payload": payload,
        "payload_sha256": _canonical_sha256(payload),
    }


def _payload(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise DazControlError(
            DazErrorCode.STATE_DATABASE_INVALID, "stored payload JSON is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise DazControlError(
            DazErrorCode.STATE_DATABASE_INVALID, "stored payload must be an object"
        )
    return payload


def _open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _stable_sqlite_sha256(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    if journal_mode != "wal":
        raise DazControlError(
            DazErrorCode.STATE_DATABASE_INVALID,
            "reconstructed database must remain in WAL journal mode",
            evidence_paths=(str(path),),
        )
    return _sha256(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_text(value).encode()).hexdigest()


def _timestamp(value: datetime | None) -> str:
    captured = value or datetime.now(UTC)
    if captured.tzinfo is None:
        raise DazControlError(DazErrorCode.CONFIG_INVALID, "reconstruction timestamp must be aware")
    return captured.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "build_reconstruction_manifest_set",
    "plan_history_reconstruction",
    "publish_reconstruction_manifest_set",
    "reconstruct_history_to_clean_database",
    "validate_reconstruction_manifest_set",
]
