#!/usr/bin/env python3
"""Coordinate fair, non-preemptive atomic jobs on one shared Pod GPU."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_DATABASE = Path(
    "/workspace/.maskfactory/shared_pod_coordination/shared_gpu_leases_v1.sqlite"
)
TERMINAL_STATES = frozenset({"completed", "failed", "released", "expired"})
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class SharedGpuLeaseError(RuntimeError):
    """Raised when shared-GPU coordination cannot proceed safely."""


def _token_sha256(owner_token: str) -> str:
    if not owner_token:
        raise SharedGpuLeaseError("owner token is required")
    return hashlib.sha256(owner_token.encode("utf-8")).hexdigest()


def ensure_owner_token_file(path: Path) -> str:
    """Create or reuse one protected restart token without printing it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        pass
    else:
        token = secrets.token_hex(32)
        try:
            os.write(descriptor, token.encode("ascii"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    try:
        if path.stat().st_size > 4096:
            raise SharedGpuLeaseError("owner token file is too large")
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise SharedGpuLeaseError("owner token file permissions are not private")
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SharedGpuLeaseError("owner token file is unreadable") from exc
    if not token:
        raise SharedGpuLeaseError("owner token file is empty")
    return token


def _request_id(session_id: str, job_id: str, payload_sha256: str) -> str:
    canonical = json.dumps(
        [session_id, job_id, payload_sha256],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"gpu-{hashlib.sha256(canonical).hexdigest()[:32]}"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    return connection


def initialize(path: Path = DEFAULT_DATABASE) -> None:
    with _connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS lease_requests(
                request_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                job_id TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                work_kind TEXT NOT NULL,
                requested_at REAL NOT NULL,
                max_runtime_seconds INTEGER NOT NULL
                    CHECK(max_runtime_seconds > 0),
                state TEXT NOT NULL
                    CHECK(state IN (
                        'queued','active','completed','failed',
                        'released','expired'
                    )),
                owner_token_sha256 TEXT,
                acquired_at REAL,
                heartbeat_at REAL,
                released_at REAL,
                terminal_reason TEXT,
                UNIQUE(session_id,job_id,payload_sha256)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_shared_gpu_lease
                ON lease_requests((1)) WHERE state='active';
            CREATE INDEX IF NOT EXISTS lease_fifo
                ON lease_requests(state,requested_at,request_id);
            CREATE TABLE IF NOT EXISTS lease_events(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                event TEXT NOT NULL,
                observed_at REAL NOT NULL,
                detail_json TEXT NOT NULL
            );
            """
        )


def _event(
    connection: sqlite3.Connection,
    *,
    request_id: str,
    event: str,
    now: float,
    detail: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO lease_events(request_id,event,observed_at,detail_json)
        VALUES(?,?,?,?)
        """,
        (
            request_id,
            event,
            now,
            json.dumps(detail, sort_keys=True, separators=(",", ":")),
        ),
    )


def _row(connection: sqlite3.Connection, request_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM lease_requests WHERE request_id=?",
        (request_id,),
    ).fetchone()
    if row is None:
        raise SharedGpuLeaseError("lease request does not exist")
    return row


def _public(row: sqlite3.Row) -> dict[str, Any]:
    result = {key: row[key] for key in row.keys() if key != "owner_token_sha256"}
    acquired = row["acquired_at"]
    if acquired is not None:
        result["expires_at"] = acquired + row["max_runtime_seconds"]
    else:
        result["expires_at"] = None
    result["owner_token_retained"] = False
    return result


def enqueue(
    *,
    database: Path,
    session_id: str,
    job_id: str,
    payload_sha256: str,
    work_kind: str,
    max_runtime_seconds: int,
    now: float | None = None,
) -> dict[str, Any]:
    if (
        not session_id
        or not job_id
        or not work_kind
        or not SHA256_RE.fullmatch(payload_sha256)
        or isinstance(max_runtime_seconds, bool)
        or max_runtime_seconds <= 0
    ):
        raise SharedGpuLeaseError("lease request fields are invalid")
    initialize(database)
    observed_at = time.time() if now is None else now
    request_id = _request_id(session_id, job_id, payload_sha256)
    with _connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            """
            SELECT * FROM lease_requests
            WHERE session_id=? AND job_id=? AND payload_sha256=?
            """,
            (session_id, job_id, payload_sha256),
        ).fetchone()
        if existing is not None:
            connection.commit()
            return _public(existing)
        connection.execute(
            """
            INSERT INTO lease_requests(
                request_id,session_id,job_id,payload_sha256,work_kind,
                requested_at,max_runtime_seconds,state
            ) VALUES(?,?,?,?,?,?,?,'queued')
            """,
            (
                request_id,
                session_id,
                job_id,
                payload_sha256,
                work_kind,
                observed_at,
                max_runtime_seconds,
            ),
        )
        _event(
            connection,
            request_id=request_id,
            event="queued",
            now=observed_at,
            detail={"max_runtime_seconds": max_runtime_seconds},
        )
        row = _row(connection, request_id)
        connection.commit()
    return _public(row)


def acquire(
    *,
    database: Path,
    request_id: str,
    owner_token: str,
    now: float | None = None,
) -> dict[str, Any]:
    initialize(database)
    observed_at = time.time() if now is None else now
    token_sha256 = _token_sha256(owner_token)
    with _connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        requested = _row(connection, request_id)
        if requested["state"] == "active":
            if requested["owner_token_sha256"] != token_sha256:
                raise SharedGpuLeaseError("active lease is owned by a different token")
            if (
                requested["acquired_at"] is None
                or observed_at >= requested["acquired_at"] + requested["max_runtime_seconds"]
            ):
                raise SharedGpuLeaseError(
                    "active lease deadline expired; prove and reclaim it "
                    "before a new acquisition"
                )
            connection.commit()
            return {"acquired": True, "reason": "ALREADY_OWNED", **_public(requested)}
        if requested["state"] != "queued":
            raise SharedGpuLeaseError("only a queued request can acquire the GPU")
        active = connection.execute(
            """
            SELECT request_id FROM lease_requests
            WHERE state='active' LIMIT 1
            """
        ).fetchone()
        if active is not None:
            connection.commit()
            return {
                "acquired": False,
                "reason": "ACTIVE_LEASE_EXISTS",
                "active_request_id": active["request_id"],
                **_public(requested),
            }
        oldest = connection.execute(
            """
            SELECT request_id FROM lease_requests
            WHERE state='queued'
            ORDER BY requested_at,request_id LIMIT 1
            """
        ).fetchone()
        if oldest is None or oldest["request_id"] != request_id:
            connection.commit()
            return {
                "acquired": False,
                "reason": "WAITING_FOR_FIFO_TURN",
                "oldest_request_id": (oldest["request_id"] if oldest is not None else None),
                **_public(requested),
            }
        connection.execute(
            """
            UPDATE lease_requests
            SET state='active',owner_token_sha256=?,acquired_at=?,heartbeat_at=?
            WHERE request_id=? AND state='queued'
            """,
            (token_sha256, observed_at, observed_at, request_id),
        )
        _event(
            connection,
            request_id=request_id,
            event="acquired",
            now=observed_at,
            detail={"non_preemptive": True},
        )
        row = _row(connection, request_id)
        connection.commit()
    return {"acquired": True, "reason": "ACQUIRED", **_public(row)}


def heartbeat(
    *,
    database: Path,
    request_id: str,
    owner_token: str,
    now: float | None = None,
) -> dict[str, Any]:
    observed_at = time.time() if now is None else now
    token_sha256 = _token_sha256(owner_token)
    with _connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = _row(connection, request_id)
        if row["state"] != "active" or row["owner_token_sha256"] != token_sha256:
            raise SharedGpuLeaseError("heartbeat is not authorized for this lease")
        if observed_at >= row["acquired_at"] + row["max_runtime_seconds"]:
            raise SharedGpuLeaseError(
                "lease runtime expired; heartbeat cannot extend the atomic job"
            )
        connection.execute(
            "UPDATE lease_requests SET heartbeat_at=? WHERE request_id=?",
            (observed_at, request_id),
        )
        _event(
            connection,
            request_id=request_id,
            event="heartbeat",
            now=observed_at,
            detail={"lease_extended": False},
        )
        row = _row(connection, request_id)
        connection.commit()
    return _public(row)


def release(
    *,
    database: Path,
    request_id: str,
    owner_token: str,
    terminal_state: str,
    terminal_reason: str,
    now: float | None = None,
) -> dict[str, Any]:
    if terminal_state not in TERMINAL_STATES - {"expired"}:
        raise SharedGpuLeaseError("release terminal state is invalid")
    if not terminal_reason:
        raise SharedGpuLeaseError("terminal reason is required")
    observed_at = time.time() if now is None else now
    token_sha256 = _token_sha256(owner_token)
    with _connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = _row(connection, request_id)
        if row["state"] != "active" or row["owner_token_sha256"] != token_sha256:
            raise SharedGpuLeaseError("release is not authorized for this lease")
        connection.execute(
            """
            UPDATE lease_requests
            SET state=?,released_at=?,terminal_reason=?
            WHERE request_id=?
            """,
            (terminal_state, observed_at, terminal_reason, request_id),
        )
        _event(
            connection,
            request_id=request_id,
            event=terminal_state,
            now=observed_at,
            detail={"terminal_reason": terminal_reason},
        )
        row = _row(connection, request_id)
        connection.commit()
    return _public(row)


def withdraw_queued(
    *,
    database: Path,
    request_id: str,
    session_id: str,
    job_id: str,
    payload_sha256: str,
    terminal_reason: str,
    now: float | None = None,
) -> dict[str, Any]:
    """Release an unacquired request before routing the job to Serverless."""
    if not terminal_reason:
        raise SharedGpuLeaseError("terminal reason is required")
    observed_at = time.time() if now is None else now
    with _connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = _row(connection, request_id)
        if (
            row["state"] != "queued"
            or row["session_id"] != session_id
            or row["job_id"] != job_id
            or row["payload_sha256"] != payload_sha256
        ):
            raise SharedGpuLeaseError("queued withdrawal identity or state does not match")
        connection.execute(
            """
            UPDATE lease_requests
            SET state='released',released_at=?,terminal_reason=?
            WHERE request_id=? AND state='queued'
            """,
            (observed_at, terminal_reason, request_id),
        )
        _event(
            connection,
            request_id=request_id,
            event="released",
            now=observed_at,
            detail={
                "terminal_reason": terminal_reason,
                "lease_was_never_acquired": True,
            },
        )
        row = _row(connection, request_id)
        connection.commit()
    return _public(row)


def reclaim_expired(
    *,
    database: Path,
    request_id: str,
    owner_process_dead: bool,
    zero_matching_gpu_process: bool,
    evidence: str,
    now: float | None = None,
) -> dict[str, Any]:
    if not owner_process_dead or not zero_matching_gpu_process or not evidence:
        raise SharedGpuLeaseError("reclaim requires dead-owner and zero-matching-GPU-process proof")
    observed_at = time.time() if now is None else now
    with _connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = _row(connection, request_id)
        if row["state"] != "active":
            raise SharedGpuLeaseError("only an active lease can be reclaimed")
        expires_at = row["acquired_at"] + row["max_runtime_seconds"]
        if observed_at < expires_at:
            raise SharedGpuLeaseError("active lease has not expired")
        connection.execute(
            """
            UPDATE lease_requests
            SET state='expired',released_at=?,terminal_reason=?
            WHERE request_id=?
            """,
            (observed_at, evidence, request_id),
        )
        _event(
            connection,
            request_id=request_id,
            event="expired",
            now=observed_at,
            detail={
                "owner_process_dead": True,
                "zero_matching_gpu_process": True,
                "evidence": evidence,
            },
        )
        row = _row(connection, request_id)
        connection.commit()
    return _public(row)


def status(*, database: Path) -> dict[str, Any]:
    initialize(database)
    with _connect(database) as connection:
        active = connection.execute(
            """
            SELECT * FROM lease_requests
            WHERE state='active' LIMIT 1
            """
        ).fetchone()
        queued = connection.execute(
            """
            SELECT * FROM lease_requests
            WHERE state='queued' ORDER BY requested_at,request_id
            """
        ).fetchall()
    return {
        "schema_version": "shared_pod_gpu_lease_status.v1",
        "active": _public(active) if active is not None else None,
        "queued": [_public(row) for row in queued],
    }


def _owner_token(args: argparse.Namespace) -> str:
    if args.owner_token_file is None:
        raise SharedGpuLeaseError("--owner-token-file is required")
    try:
        token = args.owner_token_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SharedGpuLeaseError("owner token file is unreadable") from exc
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    subparsers = parser.add_subparsers(dest="verb", required=True)

    enqueue_parser = subparsers.add_parser("enqueue")
    enqueue_parser.add_argument("--session-id", required=True)
    enqueue_parser.add_argument("--job-id", required=True)
    enqueue_parser.add_argument("--payload-sha256", required=True)
    enqueue_parser.add_argument("--work-kind", required=True)
    enqueue_parser.add_argument("--max-runtime-seconds", type=int, required=True)

    for verb in ("acquire", "heartbeat"):
        child = subparsers.add_parser(verb)
        child.add_argument("--request-id", required=True)
        child.add_argument("--owner-token-file", type=Path, required=True)

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("--request-id", required=True)
    release_parser.add_argument("--owner-token-file", type=Path, required=True)
    release_parser.add_argument(
        "--terminal-state",
        choices=sorted(TERMINAL_STATES - {"expired"}),
        required=True,
    )
    release_parser.add_argument("--terminal-reason", required=True)

    withdraw_parser = subparsers.add_parser("withdraw-queued")
    withdraw_parser.add_argument("--request-id", required=True)
    withdraw_parser.add_argument("--session-id", required=True)
    withdraw_parser.add_argument("--job-id", required=True)
    withdraw_parser.add_argument("--payload-sha256", required=True)
    withdraw_parser.add_argument("--terminal-reason", required=True)

    reclaim_parser = subparsers.add_parser("reclaim-expired")
    reclaim_parser.add_argument("--request-id", required=True)
    reclaim_parser.add_argument("--owner-process-dead", action="store_true")
    reclaim_parser.add_argument("--zero-matching-gpu-process", action="store_true")
    reclaim_parser.add_argument("--evidence", required=True)

    subparsers.add_parser("status")
    token_parser = subparsers.add_parser("ensure-token-file")
    token_parser.add_argument("--owner-token-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.verb == "enqueue":
            result = enqueue(
                database=args.database,
                session_id=args.session_id,
                job_id=args.job_id,
                payload_sha256=args.payload_sha256,
                work_kind=args.work_kind,
                max_runtime_seconds=args.max_runtime_seconds,
            )
        elif args.verb == "acquire":
            result = acquire(
                database=args.database,
                request_id=args.request_id,
                owner_token=_owner_token(args),
            )
        elif args.verb == "heartbeat":
            result = heartbeat(
                database=args.database,
                request_id=args.request_id,
                owner_token=_owner_token(args),
            )
        elif args.verb == "release":
            result = release(
                database=args.database,
                request_id=args.request_id,
                owner_token=_owner_token(args),
                terminal_state=args.terminal_state,
                terminal_reason=args.terminal_reason,
            )
        elif args.verb == "withdraw-queued":
            result = withdraw_queued(
                database=args.database,
                request_id=args.request_id,
                session_id=args.session_id,
                job_id=args.job_id,
                payload_sha256=args.payload_sha256,
                terminal_reason=args.terminal_reason,
            )
        elif args.verb == "reclaim-expired":
            result = reclaim_expired(
                database=args.database,
                request_id=args.request_id,
                owner_process_dead=args.owner_process_dead,
                zero_matching_gpu_process=args.zero_matching_gpu_process,
                evidence=args.evidence,
            )
        elif args.verb == "status":
            result = status(database=args.database)
        else:
            ensure_owner_token_file(args.owner_token_file)
            result = {
                "owner_token_file": str(args.owner_token_file),
                "owner_token_retained": False,
                "status": "READY",
            }
    except SharedGpuLeaseError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
