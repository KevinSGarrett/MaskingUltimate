"""Fail-closed durable state for bounded self-hosted engineering missions.

The steward is intentionally narrower than a model launcher.  It binds one
advisory engineering mission, suppresses duplicate work, records deterministic
model runs, reconciles interruption without blindly resubmitting ambiguous
requests, and requires durable release evidence before GPU handoff is complete.

It never grants source, Git, tracker, infrastructure, or final-acceptance
authority to model output.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

BINDING_SCHEMA = "maskfactory_self_hosted_steward_binding.v1"
TERMINAL_RECEIPT_SCHEMA = "maskfactory_self_hosted_steward_terminal.v1"
SHA256_HEX_LENGTH = 64
TERMINAL_STATES = frozenset({"completed", "failed"})
NONTERMINAL_STATES = frozenset({"admitted", "running", "recovery_required"})
ALL_STATES = TERMINAL_STATES | NONTERMINAL_STATES
RELEASE_KINDS = frozenset({"lease_release", "direct_process_exit"})
AUTHORITY_KEYS = frozenset(
    {
        "repository_mutation",
        "git",
        "tracker",
        "infrastructure",
        "runpod_control",
        "secret_access",
        "tool_invocation",
        "final_acceptance",
    }
)


class MissionBindingError(ValueError):
    """An immutable mission binding is malformed or exceeds its authority."""


class MissionConflictError(RuntimeError):
    """Durable state conflicts with the requested immutable mission."""


class DeterminismError(MissionConflictError):
    """Repeated deterministic work produced a different canonical proposal."""


class AmbiguousMissionError(MissionConflictError):
    """A request may have executed and cannot be submitted again safely."""


class AuthorityCeilingError(MissionConflictError):
    """Model output attempted to claim reserved Codex authority."""


def canonical_sha256(value: object) -> str:
    """Return the stable SHA-256 of a JSON-compatible object."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != SHA256_HEX_LENGTH:
        raise MissionBindingError(f"{field} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise MissionBindingError(f"{field} must be a SHA-256 hex digest") from exc
    return value.lower()


def _identity(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise MissionBindingError(f"{field} must be a bounded non-empty string")
    if any(character in value for character in ("/", "\\", "\0")):
        raise MissionBindingError(f"{field} contains a path separator")
    return value


def _output_namespace(value: Any, session_id: str, job_id: str) -> str:
    if not isinstance(value, str) or "\\" in value:
        raise MissionBindingError("output_namespace must be a POSIX relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.parts != (session_id, job_id)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise MissionBindingError("output_namespace must equal <session_id>/<job_id>")
    return path.as_posix()


def seal_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with a canonical self-hash in ``binding_sha256``."""
    sealed = dict(binding)
    sealed["binding_sha256"] = "0" * SHA256_HEX_LENGTH
    sealed["binding_sha256"] = canonical_sha256(sealed)
    return sealed


def _validate_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "session_id",
        "job_id",
        "payload_sha256",
        "binding_sha256",
        "model_tree_sha256",
        "runtime_sha256",
        "input_sha256",
        "output_namespace",
        "requires_replay",
        "authority",
    }
    if set(binding) != required:
        raise MissionBindingError("binding keys do not match the closed schema")
    if binding["schema_version"] != BINDING_SCHEMA:
        raise MissionBindingError("binding schema version mismatch")
    session_id = _identity(binding["session_id"], "session_id")
    job_id = _identity(binding["job_id"], "job_id")
    normalized = {
        "schema_version": BINDING_SCHEMA,
        "session_id": session_id,
        "job_id": job_id,
        "payload_sha256": _sha256(binding["payload_sha256"], "payload_sha256"),
        "binding_sha256": _sha256(binding["binding_sha256"], "binding_sha256"),
        "model_tree_sha256": _sha256(binding["model_tree_sha256"], "model_tree_sha256"),
        "runtime_sha256": _sha256(binding["runtime_sha256"], "runtime_sha256"),
        "output_namespace": _output_namespace(
            binding["output_namespace"], session_id, job_id
        ),
    }
    inputs = binding["input_sha256"]
    if not isinstance(inputs, Mapping) or not inputs:
        raise MissionBindingError("input_sha256 must be a non-empty object")
    normalized_inputs: dict[str, str] = {}
    for name, digest in inputs.items():
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            raise MissionBindingError("input_sha256 keys must be plain file names")
        normalized_inputs[name] = _sha256(digest, f"input_sha256.{name}")
    normalized["input_sha256"] = normalized_inputs
    if not isinstance(binding["requires_replay"], bool):
        raise MissionBindingError("requires_replay must be boolean")
    normalized["requires_replay"] = binding["requires_replay"]
    authority = binding["authority"]
    if (
        not isinstance(authority, Mapping)
        or set(authority) != AUTHORITY_KEYS
        or any(value is not False for value in authority.values())
    ):
        raise MissionBindingError("binding authority ceiling must explicitly deny all powers")
    normalized["authority"] = {key: False for key in sorted(AUTHORITY_KEYS)}
    zeroed = dict(normalized)
    declared = normalized["binding_sha256"]
    zeroed["binding_sha256"] = "0" * SHA256_HEX_LENGTH
    if canonical_sha256(zeroed) != declared:
        raise MissionBindingError("binding canonical self-hash mismatch")
    return normalized


class StewardLedger:
    """SQLite-backed mission admission and recovery state."""

    def __init__(self, database: Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS steward_missions (
                    session_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    binding_sha256 TEXT NOT NULL,
                    output_namespace TEXT NOT NULL,
                    requires_replay INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    request_sha256 TEXT,
                    request_started_at REAL,
                    owner_pid INTEGER,
                    owner_start_token TEXT,
                    terminal_reason TEXT,
                    release_kind TEXT,
                    release_sha256 TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (session_id, job_id),
                    UNIQUE (session_id, payload_sha256)
                );
                CREATE TABLE IF NOT EXISTS steward_runs (
                    session_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    run_number INTEGER NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    response_sha256 TEXT NOT NULL,
                    proposal_sha256 TEXT NOT NULL,
                    proposal_canonical_sha256 TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (session_id, job_id, run_number),
                    FOREIGN KEY (session_id, job_id)
                        REFERENCES steward_missions(session_id, job_id)
                        ON DELETE RESTRICT
                );
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def get(self, session_id: str, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM steward_missions
                WHERE session_id = ? AND job_id = ?
                """,
                (session_id, job_id),
            ).fetchone()
        return self._row(row)

    def runs(self, session_id: str, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM steward_runs
                WHERE session_id = ? AND job_id = ?
                ORDER BY run_number
                """,
                (session_id, job_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def admit(self, binding: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _validate_binding(binding)
        now = time.time()
        session_id = normalized["session_id"]
        job_id = normalized["job_id"]
        payload_sha256 = normalized["payload_sha256"]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM steward_missions
                WHERE session_id = ? AND job_id = ?
                """,
                (session_id, job_id),
            ).fetchone()
            if existing is not None:
                record = dict(existing)
                if (
                    record["payload_sha256"] != payload_sha256
                    or record["binding_sha256"] != normalized["binding_sha256"]
                ):
                    raise MissionConflictError(
                        "job identity is already bound to different immutable work"
                    )
                return {
                    "outcome": (
                        "reconciled_terminal"
                        if record["state"] in TERMINAL_STATES
                        else "duplicate_nonterminal"
                    ),
                    "mission": record,
                }
            duplicate = connection.execute(
                """
                SELECT * FROM steward_missions
                WHERE session_id = ? AND payload_sha256 = ?
                """,
                (session_id, payload_sha256),
            ).fetchone()
            if duplicate is not None:
                return {
                    "outcome": "duplicate_payload",
                    "mission": dict(duplicate),
                }
            connection.execute(
                """
                INSERT INTO steward_missions (
                    session_id, job_id, payload_sha256, binding_sha256,
                    output_namespace, requires_replay, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'admitted', ?, ?)
                """,
                (
                    session_id,
                    job_id,
                    payload_sha256,
                    normalized["binding_sha256"],
                    normalized["output_namespace"],
                    int(normalized["requires_replay"]),
                    now,
                    now,
                ),
            )
        return {
            "outcome": "admitted",
            "mission": self.get(session_id, job_id),
        }

    def mark_running(
        self,
        session_id: str,
        job_id: str,
        *,
        owner_pid: int,
        owner_start_token: str,
    ) -> dict[str, Any]:
        if not isinstance(owner_pid, int) or isinstance(owner_pid, bool) or owner_pid <= 0:
            raise MissionConflictError("owner_pid must be a positive integer")
        if not isinstance(owner_start_token, str) or not owner_start_token:
            raise MissionConflictError("owner_start_token is required")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM steward_missions
                WHERE session_id = ? AND job_id = ?
                """,
                (session_id, job_id),
            ).fetchone()
            if row is None:
                raise MissionConflictError("mission is not admitted")
            record = dict(row)
            if record["state"] == "running":
                if (
                    record["owner_pid"] == owner_pid
                    and record["owner_start_token"] == owner_start_token
                ):
                    return record
                raise MissionConflictError("mission is owned by a different process")
            if record["state"] != "admitted":
                raise MissionConflictError(f"mission cannot start from {record['state']}")
            connection.execute(
                """
                UPDATE steward_missions
                SET state = 'running', owner_pid = ?, owner_start_token = ?, updated_at = ?
                WHERE session_id = ? AND job_id = ?
                """,
                (owner_pid, owner_start_token, time.time(), session_id, job_id),
            )
        return self.get(session_id, job_id) or {}

    def record_request_intent(
        self,
        session_id: str,
        job_id: str,
        *,
        request_sha256: str,
    ) -> dict[str, Any]:
        """Durably grant one request submission and reject every reissue.

        A previously recorded digest is ambiguous: the corresponding model
        request may already have executed even when no response is durable.
        Returning ordinary success for that case would let a restarted caller
        mistake idempotent state reconciliation for a second send permission.
        """
        digest = _sha256(request_sha256, "request_sha256")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            mission = connection.execute(
                """
                SELECT * FROM steward_missions
                WHERE session_id = ? AND job_id = ?
                """,
                (session_id, job_id),
            ).fetchone()
            if mission is None or mission["state"] != "running":
                raise MissionConflictError("request intent requires a running mission")
            if mission["request_sha256"] is not None:
                if mission["request_sha256"] == digest:
                    raise AmbiguousMissionError(
                        "request intent already exists; do not reissue model request"
                    )
                raise MissionConflictError("different request intent already exists")
            connection.execute(
                """
                UPDATE steward_missions
                SET request_sha256 = ?, request_started_at = ?, updated_at = ?
                WHERE session_id = ? AND job_id = ?
                """,
                (digest, time.time(), time.time(), session_id, job_id),
            )
        return self.get(session_id, job_id) or {}

    def record_run(
        self,
        session_id: str,
        job_id: str,
        *,
        run_number: int,
        request_sha256: str,
        response_sha256: str,
        proposal_sha256: str,
        proposal_canonical_sha256: str,
    ) -> dict[str, Any]:
        if run_number not in {1, 2}:
            raise MissionConflictError("run_number must be 1 or 2")
        digests = {
            "request_sha256": _sha256(request_sha256, "request_sha256"),
            "response_sha256": _sha256(response_sha256, "response_sha256"),
            "proposal_sha256": _sha256(proposal_sha256, "proposal_sha256"),
            "proposal_canonical_sha256": _sha256(
                proposal_canonical_sha256, "proposal_canonical_sha256"
            ),
        }
        determinism_error: str | None = None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            mission = connection.execute(
                """
                SELECT * FROM steward_missions
                WHERE session_id = ? AND job_id = ?
                """,
                (session_id, job_id),
            ).fetchone()
            if mission is None or mission["state"] != "running":
                raise MissionConflictError("run evidence requires a running mission")
            if mission["request_sha256"] is None:
                raise MissionConflictError("request intent must be durable before run evidence")
            if mission["request_sha256"] != digests["request_sha256"]:
                raise MissionConflictError("run request does not match durable request intent")
            existing = connection.execute(
                """
                SELECT * FROM steward_runs
                WHERE session_id = ? AND job_id = ? AND run_number = ?
                """,
                (session_id, job_id, run_number),
            ).fetchone()
            if existing is not None:
                record = dict(existing)
                if all(record[key] == value for key, value in digests.items()):
                    return record
                raise MissionConflictError("run number already has different evidence")
            prior = connection.execute(
                """
                SELECT * FROM steward_runs
                WHERE session_id = ? AND job_id = ?
                ORDER BY run_number
                """,
                (session_id, job_id),
            ).fetchall()
            if prior and (
                any(row["request_sha256"] != digests["request_sha256"] for row in prior)
                or any(
                    row["proposal_canonical_sha256"]
                    != digests["proposal_canonical_sha256"]
                    for row in prior
                )
            ):
                determinism_error = "deterministic replay drift"
                connection.execute(
                    """
                    UPDATE steward_missions
                    SET state = 'failed', terminal_reason = ?, updated_at = ?
                    WHERE session_id = ? AND job_id = ?
                    """,
                    (determinism_error, time.time(), session_id, job_id),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO steward_runs (
                        session_id, job_id, run_number, request_sha256,
                        response_sha256, proposal_sha256,
                        proposal_canonical_sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        job_id,
                        run_number,
                        digests["request_sha256"],
                        digests["response_sha256"],
                        digests["proposal_sha256"],
                        digests["proposal_canonical_sha256"],
                        time.time(),
                    ),
                )
        if determinism_error is not None:
            raise DeterminismError(determinism_error)
        recorded = self.runs(session_id, job_id)
        return next(row for row in recorded if row["run_number"] == run_number)

    def complete(
        self,
        session_id: str,
        job_id: str,
        *,
        proposal_canonical_sha256: str,
        authority_claimed: bool,
        _from_reconciliation: bool = False,
    ) -> dict[str, Any]:
        proposal_digest = _sha256(
            proposal_canonical_sha256, "proposal_canonical_sha256"
        )
        if authority_claimed is not False:
            self.fail(session_id, job_id, "model output exceeded authority ceiling")
            raise AuthorityCeilingError("model output exceeded authority ceiling")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            mission = connection.execute(
                """
                SELECT * FROM steward_missions
                WHERE session_id = ? AND job_id = ?
                """,
                (session_id, job_id),
            ).fetchone()
            if mission is None:
                raise MissionConflictError("mission does not exist")
            if mission["state"] == "completed":
                return dict(mission)
            allowed_states = (
                {"running", "recovery_required"}
                if _from_reconciliation
                else {"running"}
            )
            if mission["state"] not in allowed_states:
                raise MissionConflictError(f"mission cannot complete from {mission['state']}")
            runs = connection.execute(
                """
                SELECT * FROM steward_runs
                WHERE session_id = ? AND job_id = ?
                ORDER BY run_number
                """,
                (session_id, job_id),
            ).fetchall()
            expected_count = 2 if mission["requires_replay"] else 1
            if len(runs) != expected_count:
                raise MissionConflictError("required deterministic run evidence is incomplete")
            if any(row["proposal_canonical_sha256"] != proposal_digest for row in runs):
                raise MissionConflictError("terminal proposal does not match run evidence")
            connection.execute(
                """
                UPDATE steward_missions
                SET state = 'completed', terminal_reason = 'accepted_advisory_output',
                    owner_pid = NULL, owner_start_token = NULL, updated_at = ?
                WHERE session_id = ? AND job_id = ?
                """,
                (time.time(), session_id, job_id),
            )
        return self.get(session_id, job_id) or {}

    def fail(self, session_id: str, job_id: str, reason: str) -> dict[str, Any]:
        if not isinstance(reason, str) or not reason:
            raise MissionConflictError("terminal failure reason is required")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT state FROM steward_missions
                WHERE session_id = ? AND job_id = ?
                """,
                (session_id, job_id),
            ).fetchone()
            if row is None:
                raise MissionConflictError("mission does not exist")
            if row["state"] == "completed":
                raise MissionConflictError("completed mission cannot be failed")
            connection.execute(
                """
                UPDATE steward_missions
                SET state = 'failed', terminal_reason = ?,
                    owner_pid = NULL, owner_start_token = NULL, updated_at = ?
                WHERE session_id = ? AND job_id = ?
                """,
                (reason, time.time(), session_id, job_id),
            )
        return self.get(session_id, job_id) or {}

    def reconcile(
        self,
        session_id: str,
        job_id: str,
        *,
        owner_alive: bool,
        terminal_receipt: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        mission = self.get(session_id, job_id)
        if mission is None:
            raise MissionConflictError("mission does not exist")
        if mission["state"] in TERMINAL_STATES:
            return {"outcome": "terminal", "mission": mission}
        if terminal_receipt is not None:
            required = {
                "schema_version",
                "session_id",
                "job_id",
                "payload_sha256",
                "binding_sha256",
                "state",
                "proposal_canonical_sha256",
                "authority_claimed",
            }
            if set(terminal_receipt) != required:
                raise MissionConflictError("terminal receipt keys do not match schema")
            if (
                terminal_receipt["schema_version"] != TERMINAL_RECEIPT_SCHEMA
                or terminal_receipt["session_id"] != session_id
                or terminal_receipt["job_id"] != job_id
                or terminal_receipt["payload_sha256"] != mission["payload_sha256"]
                or terminal_receipt["binding_sha256"] != mission["binding_sha256"]
                or terminal_receipt["state"] not in TERMINAL_STATES
                or terminal_receipt["authority_claimed"] is not False
            ):
                raise MissionConflictError("terminal receipt does not match mission")
            if terminal_receipt["state"] == "completed":
                completed = self.complete(
                    session_id,
                    job_id,
                    proposal_canonical_sha256=terminal_receipt[
                        "proposal_canonical_sha256"
                    ],
                    authority_claimed=False,
                    _from_reconciliation=True,
                )
                return {"outcome": "reconciled_terminal_receipt", "mission": completed}
            failed = self.fail(session_id, job_id, "reconciled_external_failure")
            return {"outcome": "reconciled_terminal_receipt", "mission": failed}
        if mission["state"] == "running" and owner_alive:
            return {"outcome": "owner_still_running", "mission": mission}
        if mission["state"] == "running":
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE steward_missions
                    SET state = 'recovery_required',
                        terminal_reason = 'owner_dead_without_terminal_receipt',
                        owner_pid = NULL, owner_start_token = NULL, updated_at = ?
                    WHERE session_id = ? AND job_id = ?
                    """,
                    (time.time(), session_id, job_id),
                )
            return {
                "outcome": "recovery_required",
                "mission": self.get(session_id, job_id),
            }
        return {"outcome": "safe_before_request", "mission": mission}

    def resume_before_request(self, session_id: str, job_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            mission = connection.execute(
                """
                SELECT * FROM steward_missions
                WHERE session_id = ? AND job_id = ?
                """,
                (session_id, job_id),
            ).fetchone()
            if mission is None or mission["state"] != "recovery_required":
                raise MissionConflictError("mission is not awaiting recovery")
            run_count = connection.execute(
                """
                SELECT COUNT(*) FROM steward_runs
                WHERE session_id = ? AND job_id = ?
                """,
                (session_id, job_id),
            ).fetchone()[0]
            if run_count or mission["request_sha256"] is not None:
                raise AmbiguousMissionError(
                    "model request evidence exists; terminal reconciliation is required"
                )
            connection.execute(
                """
                UPDATE steward_missions
                SET state = 'admitted', terminal_reason = NULL, updated_at = ?
                WHERE session_id = ? AND job_id = ?
                """,
                (time.time(), session_id, job_id),
            )
        return self.get(session_id, job_id) or {}

    @staticmethod
    def owner_process_alive(
        owner_pid: int,
        owner_start_token: str,
        *,
        proc_root: Path = Path("/proc"),
    ) -> bool:
        """Check Linux PID identity without trusting a potentially reused PID."""
        if owner_pid <= 0 or not owner_start_token:
            return False
        try:
            stat = (Path(proc_root) / str(owner_pid) / "stat").read_text(
                encoding="utf-8"
            )
        except (FileNotFoundError, OSError, UnicodeError):
            return False
        closing_parenthesis = stat.rfind(")")
        if closing_parenthesis < 0:
            return False
        fields_after_command = stat[closing_parenthesis + 1 :].split()
        if len(fields_after_command) <= 19:
            return False
        if fields_after_command[0] == "Z":
            return False
        process_start_token = fields_after_command[19]
        return process_start_token == owner_start_token

    def reconcile_recorded_owner(
        self,
        session_id: str,
        job_id: str,
        *,
        terminal_receipt: Mapping[str, Any] | None = None,
        proc_root: Path = Path("/proc"),
    ) -> dict[str, Any]:
        """Reconcile using the recorded PID plus Linux process start token."""
        mission = self.get(session_id, job_id)
        if mission is None:
            raise MissionConflictError("mission does not exist")
        owner_alive = bool(
            mission["state"] == "running"
            and mission["owner_pid"]
            and mission["owner_start_token"]
            and self.owner_process_alive(
                int(mission["owner_pid"]),
                str(mission["owner_start_token"]),
                proc_root=proc_root,
            )
        )
        return self.reconcile(
            session_id,
            job_id,
            owner_alive=owner_alive,
            terminal_receipt=terminal_receipt,
        )

    def record_release(
        self,
        session_id: str,
        job_id: str,
        *,
        release_kind: str,
        release_sha256: str,
    ) -> dict[str, Any]:
        if release_kind not in RELEASE_KINDS:
            raise MissionConflictError("release_kind is invalid")
        digest = _sha256(release_sha256, "release_sha256")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            mission = connection.execute(
                """
                SELECT * FROM steward_missions
                WHERE session_id = ? AND job_id = ?
                """,
                (session_id, job_id),
            ).fetchone()
            if mission is None or mission["state"] not in TERMINAL_STATES:
                raise MissionConflictError("release evidence requires a terminal mission")
            if mission["release_sha256"] is not None:
                if (
                    mission["release_kind"] == release_kind
                    and mission["release_sha256"] == digest
                ):
                    return dict(mission)
                raise MissionConflictError("different release evidence already exists")
            connection.execute(
                """
                UPDATE steward_missions
                SET release_kind = ?, release_sha256 = ?, updated_at = ?
                WHERE session_id = ? AND job_id = ?
                """,
                (release_kind, digest, time.time(), session_id, job_id),
            )
        return self.get(session_id, job_id) or {}

    def handoff_ready(self, session_id: str, job_id: str) -> bool:
        mission = self.get(session_id, job_id)
        return bool(
            mission
            and mission["state"] in TERMINAL_STATES
            and mission["release_kind"] in RELEASE_KINDS
            and mission["release_sha256"]
        )


__all__ = [
    "AmbiguousMissionError",
    "AuthorityCeilingError",
    "BINDING_SCHEMA",
    "DeterminismError",
    "MissionBindingError",
    "MissionConflictError",
    "StewardLedger",
    "TERMINAL_RECEIPT_SCHEMA",
    "canonical_sha256",
    "seal_binding",
]
