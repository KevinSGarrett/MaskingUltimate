"""Deterministic, default-disabled DAZ queue scheduling primitives."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .control import (
    DazControlError,
    DazErrorCode,
    build_event,
    read_control_state,
    result_envelope,
)
from .policy import DazConfiguration

LEASEABLE_JOB_STATES = ("pending", "retry")
TERMINAL_JOB_STATES = ("complete", "failed", "retry")


def scheduler_status(configuration: DazConfiguration) -> dict[str, Any]:
    """Return a read-only queue/control snapshot without recovering or leasing work."""
    state = read_control_state(configuration)
    path = configuration.paths.state_database
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            connection.execute("PRAGMA query_only=ON")
            states = {
                str(name): int(count)
                for name, count in connection.execute(
                    "SELECT state,count(*) FROM jobs GROUP BY state ORDER BY state"
                )
            }
            active_leases = int(connection.execute("SELECT count(*) FROM leases").fetchone()[0])
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"scheduler status read failed: {exc}",
            retryable=True,
            evidence_paths=(str(path),),
        ) from exc
    leasing_allowed = (
        _leasing_allowed(state) and active_leases < configuration.worker.maximum_workers
    )
    drained = bool(state["drain"]) and active_leases == 0
    return result_envelope(
        reason="scheduler_status",
        evidence_paths=(str(path),),
        data={
            "control": state,
            "job_state_counts": states,
            "active_lease_count": active_leases,
            "maximum_workers": configuration.worker.maximum_workers,
            "leasing_allowed": leasing_allowed,
            "drained": drained,
        },
    )


def lease_next_job(
    configuration: DazConfiguration,
    *,
    owner_pid: int,
    lease_seconds: int,
    now: datetime | None = None,
    lease_id: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Atomically lease the next deterministic job when control permits new work."""
    if owner_pid <= 0 or not 1 <= lease_seconds <= 86_400:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "scheduler owner PID or lease duration is invalid",
        )
    captured = _as_utc(now)
    path = configuration.paths.state_database
    connection = _open_scheduler_database(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        state = read_control_state(configuration)
        if not _leasing_allowed(state):
            connection.rollback()
            return result_envelope(
                reason="scheduler_controlled_no_lease",
                evidence_paths=(str(path),),
                data={"leased": False, "control": state},
            )
        active = int(connection.execute("SELECT count(*) FROM leases").fetchone()[0])
        if active >= configuration.worker.maximum_workers:
            connection.rollback()
            return result_envelope(
                reason="scheduler_capacity_no_lease",
                evidence_paths=(str(path),),
                data={"leased": False, "active_lease_count": active},
            )
        row = connection.execute(
            "SELECT job_id,state,attempt FROM jobs "
            "WHERE state IN ('pending','retry') ORDER BY attempt,job_id LIMIT 1"
        ).fetchone()
        if row is None:
            connection.rollback()
            return result_envelope(
                reason="scheduler_idle",
                evidence_paths=(str(path),),
                data={"leased": False},
            )
        job_id, prior_state, prior_attempt = str(row[0]), str(row[1]), int(row[2])
        next_attempt = prior_attempt + 1
        identity = lease_id or f"lease_{uuid.uuid4().hex}"
        expires = captured + timedelta(seconds=lease_seconds)
        connection.execute(
            "UPDATE jobs SET state='leased',attempt=? WHERE job_id=? AND state=? AND attempt=?",
            (next_attempt, job_id, prior_state, prior_attempt),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != 1:
            raise DazControlError(
                DazErrorCode.SCHEDULER_REFUSED,
                "scheduler job changed during lease transaction",
                entity_ids=(job_id,),
                retryable=True,
            )
        connection.execute(
            "INSERT INTO leases(lease_id,job_id,owner_pid,expires_at) VALUES (?,?,?,?)",
            (identity, job_id, owner_pid, _timestamp(expires)),
        )
        event = build_event(
            "scheduler.job_leased",
            "job",
            job_id,
            {
                "lease_id": identity,
                "owner_pid": owner_pid,
                "prior_state": prior_state,
                "control_revision": int(state["revision"]),
            },
            job_id=job_id,
            attempt=next_attempt,
            timestamp=_timestamp(captured),
            event_id=event_id,
        )
        _append_event_in_transaction(connection, event)
        connection.commit()
    except DazControlError:
        connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"scheduler lease transaction failed: {exc}",
            retryable=True,
            evidence_paths=(str(path),),
        ) from exc
    finally:
        connection.close()
    return result_envelope(
        reason="scheduler_job_leased",
        entity_ids=(job_id, identity),
        evidence_paths=(str(path),),
        data={
            "leased": True,
            "job_id": job_id,
            "lease_id": identity,
            "attempt": next_attempt,
            "owner_pid": owner_pid,
            "expires_at": _timestamp(expires),
            "control_revision": int(state["revision"]),
        },
    )


def finish_lease(
    configuration: DazConfiguration,
    *,
    lease_id: str,
    terminal_state: str,
    reason: str,
    now: datetime | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Finish an active job without promoting any partial scene artifact."""
    if terminal_state not in TERMINAL_JOB_STATES or not lease_id or not reason.strip():
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "scheduler lease completion is invalid",
        )
    captured = _as_utc(now)
    path = configuration.paths.state_database
    connection = _open_scheduler_database(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT l.job_id,j.attempt FROM leases l JOIN jobs j ON j.job_id=l.job_id "
            "WHERE l.lease_id=?",
            (lease_id,),
        ).fetchone()
        if row is None:
            raise DazControlError(
                DazErrorCode.SCHEDULER_REFUSED,
                "scheduler lease does not exist",
                entity_ids=(lease_id,),
            )
        job_id, attempt = str(row[0]), int(row[1])
        connection.execute("DELETE FROM leases WHERE lease_id=?", (lease_id,))
        connection.execute("UPDATE jobs SET state=? WHERE job_id=?", (terminal_state, job_id))
        event = build_event(
            f"scheduler.job_{terminal_state}",
            "job",
            job_id,
            {"lease_id": lease_id, "reason": reason.strip(), "artifact_promoted": False},
            job_id=job_id,
            attempt=attempt,
            timestamp=_timestamp(captured),
            event_id=event_id,
        )
        _append_event_in_transaction(connection, event)
        connection.commit()
    except DazControlError:
        connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"scheduler completion transaction failed: {exc}",
            retryable=True,
            evidence_paths=(str(path),),
        ) from exc
    finally:
        connection.close()
    return result_envelope(
        reason="scheduler_lease_finished",
        entity_ids=(job_id, lease_id),
        evidence_paths=(str(path),),
        data={
            "job_id": job_id,
            "lease_id": lease_id,
            "job_state": terminal_state,
            "artifact_promoted": False,
        },
    )


def _leasing_allowed(state: dict[str, Any]) -> bool:
    return all(
        (
            state["enabled"] is True,
            state["paused"] is False,
            state["drain"] is False,
            state["stop_requested"] is False,
        )
    )


def _open_scheduler_database(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(path, timeout=10)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
    except sqlite3.Error as exc:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"scheduler database open failed: {exc}",
            retryable=True,
            evidence_paths=(str(path),),
        ) from exc


def _append_event_in_transaction(connection: sqlite3.Connection, event: dict[str, Any]) -> None:
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


def _as_utc(value: datetime | None) -> datetime:
    captured = value or datetime.now(UTC)
    if captured.tzinfo is None:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "scheduler timestamps must be timezone-aware",
        )
    return captured.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "LEASEABLE_JOB_STATES",
    "TERMINAL_JOB_STATES",
    "finish_lease",
    "lease_next_job",
    "scheduler_status",
]
