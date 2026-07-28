"""Immutable campaign/mission identity and durable continuous state machine."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

CONTINUOUS_BINDING_SCHEMA = "maskfactory_continuous_work_binding.v1"
WORK_KINDS = frozenset({"campaign", "mission"})
STATES = (
    "planned",
    "intent_persisted",
    "queued",
    "admitted",
    "running",
    "submitted_unknown",
    "response_persisted",
    "validated",
    "accepted",
    "rejected",
    "recovery_required",
    "released",
    "terminal",
)
TRANSITIONS = {
    "planned": frozenset({"intent_persisted"}),
    "intent_persisted": frozenset({"queued", "admitted", "recovery_required"}),
    "queued": frozenset({"admitted", "recovery_required"}),
    "admitted": frozenset({"running", "recovery_required"}),
    "running": frozenset({"submitted_unknown", "response_persisted", "recovery_required"}),
    "submitted_unknown": frozenset({"response_persisted", "recovery_required"}),
    "response_persisted": frozenset({"validated", "rejected", "recovery_required"}),
    "validated": frozenset({"accepted", "rejected"}),
    "accepted": frozenset({"released"}),
    "rejected": frozenset({"released"}),
    "recovery_required": frozenset({"response_persisted", "rejected"}),
    "released": frozenset({"terminal"}),
    "terminal": frozenset(),
}
SHA256_LENGTH = 64


class ContinuousLedgerError(RuntimeError):
    """Continuous ledger state is malformed or conflicts with durable truth."""


class ContinuousBindingError(ValueError):
    """A continuous work binding violates the closed identity contract."""


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _sha256(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ContinuousBindingError(f"{field} must be lowercase SHA-256")
    return value


def _identity(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 200
        or any(character in value for character in "/\\\0")
    ):
        raise ContinuousBindingError(f"{field} must be a plain bounded identity")
    return value


def seal_continuous_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    sealed = deepcopy(dict(binding))
    sealed["binding_sha256"] = "0" * SHA256_LENGTH
    sealed["binding_sha256"] = canonical_sha256(sealed)
    return sealed


def validate_continuous_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "work_kind",
        "session_id",
        "work_id",
        "campaign_id",
        "payload_sha256",
        "policy_sha256",
        "tool_sha256",
        "runtime_sha256",
        "dependency_ids",
        "supersedes_ids",
        "allowed_outputs",
        "authority_ceiling",
        "binding_sha256",
    }
    if set(binding) != required:
        raise ContinuousBindingError("binding keys do not match the closed schema")
    if binding["schema_version"] != CONTINUOUS_BINDING_SCHEMA:
        raise ContinuousBindingError("binding schema version mismatch")
    kind = binding["work_kind"]
    if kind not in WORK_KINDS:
        raise ContinuousBindingError("work_kind is invalid")
    session_id = _identity(binding["session_id"], "session_id")
    work_id = _identity(binding["work_id"], "work_id")
    campaign_id = binding["campaign_id"]
    if kind == "campaign" and campaign_id is not None:
        raise ContinuousBindingError("campaign binding cannot have campaign_id")
    if kind == "mission":
        campaign_id = _identity(campaign_id, "campaign_id")
    normalized = {
        "schema_version": CONTINUOUS_BINDING_SCHEMA,
        "work_kind": kind,
        "session_id": session_id,
        "work_id": work_id,
        "campaign_id": campaign_id,
        "payload_sha256": _sha256(binding["payload_sha256"], "payload_sha256"),
        "policy_sha256": _sha256(binding["policy_sha256"], "policy_sha256"),
        "tool_sha256": _sha256(binding["tool_sha256"], "tool_sha256"),
        "runtime_sha256": _sha256(binding["runtime_sha256"], "runtime_sha256"),
    }
    for field in ("dependency_ids", "supersedes_ids", "allowed_outputs"):
        values = binding[field]
        if (
            not isinstance(values, list)
            or len(values) != len(set(values))
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise ContinuousBindingError(f"{field} must be an array of unique non-empty strings")
        normalized[field] = list(values)
    authority = binding["authority_ceiling"]
    if not isinstance(authority, Mapping) or not authority:
        raise ContinuousBindingError("authority_ceiling must be a non-empty object")
    if any(not isinstance(key, str) or value is not False for key, value in authority.items()):
        raise ContinuousBindingError("authority_ceiling must explicitly deny every power")
    normalized["authority_ceiling"] = dict(sorted(authority.items()))
    normalized["binding_sha256"] = _sha256(binding["binding_sha256"], "binding_sha256")
    zeroed = deepcopy(normalized)
    zeroed["binding_sha256"] = "0" * SHA256_LENGTH
    if canonical_sha256(zeroed) != normalized["binding_sha256"]:
        raise ContinuousBindingError("binding canonical self-hash mismatch")
    return normalized


class ContinuousWorkLedger:
    """SQLite-backed state machine for continuous campaigns and missions."""

    def __init__(self, database: Path, *, clock: Callable[[], float] = time.time):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
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
                CREATE TABLE IF NOT EXISTS continuous_work (
                    session_id TEXT NOT NULL,
                    work_kind TEXT NOT NULL,
                    work_id TEXT NOT NULL,
                    campaign_id TEXT,
                    payload_sha256 TEXT NOT NULL,
                    binding_sha256 TEXT NOT NULL,
                    binding_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    owner_pid INTEGER,
                    owner_start_token TEXT,
                    selected_route TEXT,
                    terminal_outcome TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (session_id, work_kind, work_id),
                    UNIQUE (session_id, work_kind, payload_sha256)
                );
                CREATE TABLE IF NOT EXISTS continuous_transitions (
                    session_id TEXT NOT NULL,
                    work_kind TEXT NOT NULL,
                    work_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    previous_event_sha256 TEXT NOT NULL,
                    event_sha256 TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (session_id, work_kind, work_id, sequence),
                    UNIQUE (event_sha256),
                    FOREIGN KEY (session_id, work_kind, work_id)
                        REFERENCES continuous_work(session_id, work_kind, work_id)
                        ON DELETE RESTRICT
                );
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def get(self, session_id: str, work_kind: str, work_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM continuous_work
                WHERE session_id = ? AND work_kind = ? AND work_id = ?
                """,
                (session_id, work_kind, work_id),
            ).fetchone()
        return self._row(row)

    def transitions(self, session_id: str, work_kind: str, work_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM continuous_transitions
                WHERE session_id = ? AND work_kind = ? AND work_id = ?
                ORDER BY sequence
                """,
                (session_id, work_kind, work_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def _append_transition(
        self,
        connection: sqlite3.Connection,
        *,
        binding: Mapping[str, Any],
        from_state: str | None,
        to_state: str,
        evidence_sha256: str,
    ) -> None:
        prior = connection.execute(
            """
            SELECT sequence, event_sha256 FROM continuous_transitions
            WHERE session_id = ? AND work_kind = ? AND work_id = ?
            ORDER BY sequence DESC LIMIT 1
            """,
            (binding["session_id"], binding["work_kind"], binding["work_id"]),
        ).fetchone()
        sequence = int(prior["sequence"]) + 1 if prior else 1
        previous = prior["event_sha256"] if prior else "0" * SHA256_LENGTH
        created_at = self.clock()
        event = {
            "session_id": binding["session_id"],
            "work_kind": binding["work_kind"],
            "work_id": binding["work_id"],
            "sequence": sequence,
            "from_state": from_state,
            "to_state": to_state,
            "evidence_sha256": evidence_sha256,
            "previous_event_sha256": previous,
            "created_at": created_at,
            "event_sha256": "0" * SHA256_LENGTH,
        }
        event["event_sha256"] = canonical_sha256(event)
        connection.execute(
            """
            INSERT INTO continuous_transitions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["session_id"],
                event["work_kind"],
                event["work_id"],
                event["sequence"],
                event["from_state"],
                event["to_state"],
                event["evidence_sha256"],
                event["previous_event_sha256"],
                event["event_sha256"],
                event["created_at"],
            ),
        )

    def register(self, binding: Mapping[str, Any]) -> dict[str, Any]:
        normalized = validate_continuous_binding(binding)
        key = (
            normalized["session_id"],
            normalized["work_kind"],
            normalized["work_id"],
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM continuous_work
                WHERE session_id = ? AND work_kind = ? AND work_id = ?
                """,
                key,
            ).fetchone()
            if existing:
                record = dict(existing)
                if record["binding_sha256"] != normalized["binding_sha256"]:
                    raise ContinuousLedgerError(
                        "work identity is bound to different immutable bytes"
                    )
                return {"outcome": "replayed", "work": record}
            duplicate = connection.execute(
                """
                SELECT * FROM continuous_work
                WHERE session_id = ? AND work_kind = ? AND payload_sha256 = ?
                """,
                (
                    normalized["session_id"],
                    normalized["work_kind"],
                    normalized["payload_sha256"],
                ),
            ).fetchone()
            if duplicate:
                return {"outcome": "duplicate_payload", "work": dict(duplicate)}
            if normalized["work_kind"] == "mission":
                parent = connection.execute(
                    """
                    SELECT state FROM continuous_work
                    WHERE session_id = ? AND work_kind = 'campaign' AND work_id = ?
                    """,
                    (normalized["session_id"], normalized["campaign_id"]),
                ).fetchone()
                if parent is None or parent["state"] == "terminal":
                    raise ContinuousLedgerError(
                        "mission requires a registered nonterminal campaign"
                    )
            now = self.clock()
            connection.execute(
                """
                INSERT INTO continuous_work (
                    session_id, work_kind, work_id, campaign_id,
                    payload_sha256, binding_sha256, binding_json, state,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?)
                """,
                (
                    *key,
                    normalized["campaign_id"],
                    normalized["payload_sha256"],
                    normalized["binding_sha256"],
                    json.dumps(normalized, sort_keys=True, separators=(",", ":")),
                    now,
                    now,
                ),
            )
            self._append_transition(
                connection,
                binding=normalized,
                from_state=None,
                to_state="planned",
                evidence_sha256=normalized["binding_sha256"],
            )
        return {"outcome": "registered", "work": self.get(*key)}

    def transition(
        self,
        session_id: str,
        work_kind: str,
        work_id: str,
        *,
        to_state: str,
        evidence_sha256: str,
        owner_pid: int | None = None,
        owner_start_token: str | None = None,
        selected_route: str | None = None,
        terminal_outcome: str | None = None,
    ) -> dict[str, Any]:
        evidence = _sha256(evidence_sha256, "evidence_sha256")
        if to_state not in STATES:
            raise ContinuousLedgerError("target state is invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM continuous_work
                WHERE session_id = ? AND work_kind = ? AND work_id = ?
                """,
                (session_id, work_kind, work_id),
            ).fetchone()
            if row is None:
                raise ContinuousLedgerError("work does not exist")
            record = dict(row)
            current = record["state"]
            if to_state not in TRANSITIONS[current]:
                raise ContinuousLedgerError(
                    f"illegal continuous transition: {current} -> {to_state}"
                )
            if to_state == "running":
                if (
                    not isinstance(owner_pid, int)
                    or isinstance(owner_pid, bool)
                    or owner_pid <= 0
                    or not owner_start_token
                    or not selected_route
                ):
                    raise ContinuousLedgerError(
                        "running transition requires owner PID/token and route"
                    )
            if to_state == "terminal" and not terminal_outcome:
                raise ContinuousLedgerError("terminal transition requires terminal_outcome")
            binding = json.loads(record["binding_json"])
            self._append_transition(
                connection,
                binding=binding,
                from_state=current,
                to_state=to_state,
                evidence_sha256=evidence,
            )
            connection.execute(
                """
                UPDATE continuous_work
                SET state = ?, owner_pid = COALESCE(?, owner_pid),
                    owner_start_token = COALESCE(?, owner_start_token),
                    selected_route = COALESCE(?, selected_route),
                    terminal_outcome = COALESCE(?, terminal_outcome),
                    updated_at = ?
                WHERE session_id = ? AND work_kind = ? AND work_id = ?
                """,
                (
                    to_state,
                    owner_pid,
                    owner_start_token,
                    selected_route,
                    terminal_outcome,
                    self.clock(),
                    session_id,
                    work_kind,
                    work_id,
                ),
            )
        return self.get(session_id, work_kind, work_id) or {}

    def reconcile_owner(
        self,
        session_id: str,
        work_kind: str,
        work_id: str,
        *,
        process_identity_probe: Callable[[int], str | None],
        evidence_sha256: str,
    ) -> dict[str, Any]:
        record = self.get(session_id, work_kind, work_id)
        if record is None:
            raise ContinuousLedgerError("work does not exist")
        if record["state"] != "running":
            return {"outcome": "not_running", "work": record}
        observed = process_identity_probe(int(record["owner_pid"]))
        if observed == record["owner_start_token"]:
            return {"outcome": "owner_alive", "work": record}
        recovered = self.transition(
            session_id,
            work_kind,
            work_id,
            to_state="recovery_required",
            evidence_sha256=evidence_sha256,
        )
        return {
            "outcome": "recovery_required",
            "observed_process_start_token": observed,
            "work": recovered,
        }


__all__ = [
    "CONTINUOUS_BINDING_SCHEMA",
    "ContinuousBindingError",
    "ContinuousLedgerError",
    "ContinuousWorkLedger",
    "STATES",
    "TRANSITIONS",
    "canonical_sha256",
    "seal_continuous_binding",
    "validate_continuous_binding",
]
