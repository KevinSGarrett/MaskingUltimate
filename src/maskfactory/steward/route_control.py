"""Restart-safe single-route control for canonical steward missions.

The ledger is the mandatory coordination boundary between local Pod,
broker-only Serverless, and governed OpenRouter advisory routes. It stores
only owner-token hashes, serializes claims with ``BEGIN IMMEDIATE``, and
requires an explicit release or reconciliation before a route can change.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "maskfactory.steward.canonical_route_ledger.v1"
PARENT_SCHEMA_VERSION = "maskfactory.steward.parent_child_route_ledger.v1"
ROUTES = frozenset({"local_pod", "serverless_overflow", "openrouter_advisory"})
PARENT_CHILD_ROUTES = {
    "serverless_execution": "serverless_overflow",
    "consolidated_advisory": "openrouter_advisory",
}
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
FINAL_STATES = frozenset({"completed", "failed_final"})
PARENT_FINAL_STATES = frozenset({"completed", "failed", "unavailable"})


class RouteControlError(RuntimeError):
    """Base failure for canonical mission route control."""


class RouteIdentityMismatch(RouteControlError):
    """A mission ID was reused with a different session or payload."""


class RouteAlreadyActive(RouteControlError):
    """Another route or owner already controls the canonical mission."""


class RouteOutcomeUnknown(RouteControlError):
    """The prior route must reconcile before any route change."""


class ParentChildBindingError(RouteControlError):
    """A parent or child-role binding conflicts with durable state."""


class ParentChildAlreadyActive(ParentChildBindingError):
    """Another mission or owner already controls this parent's child role."""


def _token_sha256(owner_token: str) -> str:
    if not isinstance(owner_token, str) or len(owner_token) < 32:
        raise RouteControlError("owner token is absent or too short")
    return hashlib.sha256(owner_token.encode("utf-8")).hexdigest()


def _validate_identity(
    *,
    mission_id: str,
    session_id: str,
    payload_sha256: str,
) -> None:
    if not SHA256_RE.fullmatch(mission_id):
        raise RouteControlError("mission_id must be 64 lowercase hexadecimal characters")
    if not session_id:
        raise RouteControlError("session_id is required")
    if not SHA256_RE.fullmatch(payload_sha256):
        raise RouteControlError("payload_sha256 must be 64 lowercase hexadecimal characters")


def _validate_parent_identity(
    *,
    parent_campaign_id: str,
    parent_contract_sha256: str,
    required_child_roles: tuple[str, ...],
    child_role: str,
    route: str,
) -> None:
    if not SHA256_RE.fullmatch(parent_campaign_id):
        raise ParentChildBindingError(
            "parent_campaign_id must be 64 lowercase hexadecimal characters"
        )
    if not SHA256_RE.fullmatch(parent_contract_sha256):
        raise ParentChildBindingError(
            "parent_contract_sha256 must be 64 lowercase hexadecimal characters"
        )
    if (
        not required_child_roles
        or tuple(sorted(set(required_child_roles))) != required_child_roles
        or any(role not in PARENT_CHILD_ROUTES for role in required_child_roles)
    ):
        raise ParentChildBindingError(
            "required_child_roles must be a sorted unique governed role tuple"
        )
    if child_role not in required_child_roles:
        raise ParentChildBindingError("child_role is absent from required_child_roles")
    if PARENT_CHILD_ROUTES.get(child_role) != route:
        raise ParentChildBindingError("child_role does not match the governed route")


class CanonicalParentChildLedger:
    """Bind exactly one immutable mission to each required parent child role."""

    def __init__(
        self,
        database: Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS route_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS parent_campaigns (
                    parent_campaign_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    parent_contract_sha256 TEXT NOT NULL,
                    required_child_roles_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS parent_route_children (
                    parent_campaign_id TEXT NOT NULL,
                    child_role TEXT NOT NULL,
                    mission_id TEXT NOT NULL UNIQUE,
                    route TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    owner_token_sha256 TEXT NOT NULL,
                    terminal_disposition TEXT,
                    result_sha256 TEXT,
                    reason TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(parent_campaign_id, child_role),
                    FOREIGN KEY(parent_campaign_id)
                        REFERENCES parent_campaigns(parent_campaign_id)
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO route_meta(key, value) "
                "VALUES('parent_schema_version', ?)",
                (PARENT_SCHEMA_VERSION,),
            )
            existing = connection.execute(
                "SELECT value FROM route_meta WHERE key='parent_schema_version'"
            ).fetchone()
            if (
                existing is None
                or existing["value"] != PARENT_SCHEMA_VERSION
            ):
                raise ParentChildBindingError(
                    "unsupported canonical parent-child ledger schema"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @staticmethod
    def _roles_json(required_child_roles: tuple[str, ...]) -> str:
        return json.dumps(list(required_child_roles), separators=(",", ":"))

    @staticmethod
    def _child_value(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "child_role": row["child_role"],
            "mission_id": row["mission_id"],
            "route": row["route"],
            "payload_sha256": row["payload_sha256"],
            "state": row["state"],
            "terminal_disposition": row["terminal_disposition"],
            "result_sha256": row["result_sha256"],
            "reason": row["reason"],
        }

    def bind_child(
        self,
        *,
        parent_campaign_id: str,
        parent_contract_sha256: str,
        required_child_roles: tuple[str, ...],
        child_role: str,
        mission_id: str,
        session_id: str,
        route: str,
        payload_sha256: str,
        owner_token: str,
    ) -> dict[str, Any]:
        """Bind or reconstruct one exact child role before route admission."""
        _validate_identity(
            mission_id=mission_id,
            session_id=session_id,
            payload_sha256=payload_sha256,
        )
        _validate_parent_identity(
            parent_campaign_id=parent_campaign_id,
            parent_contract_sha256=parent_contract_sha256,
            required_child_roles=required_child_roles,
            child_role=child_role,
            route=route,
        )
        token_sha256 = _token_sha256(owner_token)
        roles_json = self._roles_json(required_child_roles)
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            parent = connection.execute(
                "SELECT * FROM parent_campaigns WHERE parent_campaign_id=?",
                (parent_campaign_id,),
            ).fetchone()
            if parent is None:
                connection.execute(
                    """
                    INSERT INTO parent_campaigns(
                        parent_campaign_id, session_id,
                        parent_contract_sha256, required_child_roles_json,
                        created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        parent_campaign_id,
                        session_id,
                        parent_contract_sha256,
                        roles_json,
                        now,
                        now,
                    ),
                )
            elif (
                parent["session_id"] != session_id
                or parent["parent_contract_sha256"] != parent_contract_sha256
                or parent["required_child_roles_json"] != roles_json
            ):
                raise ParentChildBindingError(
                    "parent campaign identity conflicts with durable state"
                )
            child = connection.execute(
                "SELECT * FROM parent_route_children "
                "WHERE parent_campaign_id=? AND child_role=?",
                (parent_campaign_id, child_role),
            ).fetchone()
            if child is None:
                attached = connection.execute(
                    "SELECT parent_campaign_id, child_role "
                    "FROM parent_route_children WHERE mission_id=?",
                    (mission_id,),
                ).fetchone()
                if attached is not None:
                    raise ParentChildBindingError(
                        "child mission is already attached to another parent role"
                    )
                canonical = connection.execute(
                    "SELECT mission_id FROM canonical_missions WHERE mission_id=?",
                    (mission_id,),
                ).fetchone()
                if canonical is not None:
                    raise ParentChildBindingError(
                        "existing canonical mission cannot be attached retroactively"
                    )
                connection.execute(
                    """
                    INSERT INTO parent_route_children(
                        parent_campaign_id, child_role, mission_id, route,
                        payload_sha256, state, owner_token_sha256,
                        created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, 'bound', ?, ?, ?)
                    """,
                    (
                        parent_campaign_id,
                        child_role,
                        mission_id,
                        route,
                        payload_sha256,
                        token_sha256,
                        now,
                        now,
                    ),
                )
            else:
                if (
                    child["mission_id"] != mission_id
                    or child["route"] != route
                    or child["payload_sha256"] != payload_sha256
                ):
                    raise ParentChildAlreadyActive(
                        "parent child role is already bound to another mission"
                    )
                if child["state"] in PARENT_FINAL_STATES:
                    connection.commit()
                    return self.inspect_parent(parent_campaign_id)
                if child["owner_token_sha256"] != token_sha256:
                    raise ParentChildAlreadyActive(
                        "parent child role has another active owner"
                    )
            connection.execute(
                "UPDATE parent_campaigns SET updated_at=? "
                "WHERE parent_campaign_id=?",
                (now, parent_campaign_id),
            )
            connection.commit()
        return self.inspect_parent(parent_campaign_id)

    def mark_child(
        self,
        *,
        parent_campaign_id: str,
        child_role: str,
        owner_token: str,
        state: str,
        terminal_disposition: str | None = None,
        result_sha256: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Persist a parent-child transition after the route ledger transition."""
        allowed = {
            "active",
            "outcome_unknown",
            "terminal_pending_release",
            "completed",
            "failed",
            "unavailable",
        }
        if state not in allowed:
            raise ParentChildBindingError("parent child state is invalid")
        if state in PARENT_FINAL_STATES:
            if terminal_disposition != state or not (
                isinstance(result_sha256, str)
                and SHA256_RE.fullmatch(result_sha256)
            ):
                raise ParentChildBindingError(
                    "terminal parent child state requires matching disposition and result"
                )
        elif terminal_disposition is not None or result_sha256 is not None:
            raise ParentChildBindingError(
                "nonterminal parent child state cannot bind a terminal result"
            )
        token_sha256 = _token_sha256(owner_token)
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            child = connection.execute(
                "SELECT * FROM parent_route_children "
                "WHERE parent_campaign_id=? AND child_role=?",
                (parent_campaign_id, child_role),
            ).fetchone()
            if child is None:
                raise ParentChildBindingError("parent child role is absent")
            if child["state"] in PARENT_FINAL_STATES:
                if (
                    child["state"] != state
                    or child["terminal_disposition"] != terminal_disposition
                    or child["result_sha256"] != result_sha256
                ):
                    raise ParentChildBindingError(
                        "terminal parent child role cannot be rewritten"
                    )
                connection.commit()
                return self.inspect_parent(parent_campaign_id)
            if child["owner_token_sha256"] != token_sha256:
                raise ParentChildAlreadyActive(
                    "parent child owner token does not match"
                )
            connection.execute(
                """
                UPDATE parent_route_children
                SET state=?, terminal_disposition=?, result_sha256=?,
                    reason=?, updated_at=?
                WHERE parent_campaign_id=? AND child_role=?
                """,
                (
                    state,
                    terminal_disposition,
                    result_sha256,
                    reason,
                    now,
                    parent_campaign_id,
                    child_role,
                ),
            )
            connection.execute(
                "UPDATE parent_campaigns SET updated_at=? "
                "WHERE parent_campaign_id=?",
                (now, parent_campaign_id),
            )
            connection.commit()
        return self.inspect_parent(parent_campaign_id)

    def inspect_parent(self, parent_campaign_id: str) -> dict[str, Any]:
        """Return a reconciled non-secret parent view across required child roles."""
        if not SHA256_RE.fullmatch(parent_campaign_id):
            raise ParentChildBindingError("parent_campaign_id is invalid")
        with self._connect() as connection:
            parent = connection.execute(
                "SELECT * FROM parent_campaigns WHERE parent_campaign_id=?",
                (parent_campaign_id,),
            ).fetchone()
            if parent is None:
                raise ParentChildBindingError("parent campaign is absent")
            required_value = json.loads(parent["required_child_roles_json"])
            if not isinstance(required_value, list) or not all(
                isinstance(role, str) for role in required_value
            ):
                raise ParentChildBindingError(
                    "parent required child roles are unreadable"
                )
            required = tuple(required_value)
            children = [
                self._child_value(row)
                for row in connection.execute(
                    "SELECT * FROM parent_route_children "
                    "WHERE parent_campaign_id=? ORDER BY child_role",
                    (parent_campaign_id,),
                )
            ]
        by_role = {child["child_role"]: child for child in children}
        missing = [role for role in required if role not in by_role]
        child_states = {child["state"] for child in children}
        if "outcome_unknown" in child_states:
            state = "outcome_unknown"
        elif missing:
            state = "awaiting_children"
        elif any(child["state"] not in PARENT_FINAL_STATES for child in children):
            state = "in_progress"
        elif any(child["state"] in {"failed", "unavailable"} for child in children):
            state = "failed"
        else:
            state = "completed"
        return {
            "schema_version": PARENT_SCHEMA_VERSION,
            "parent_campaign_id": parent["parent_campaign_id"],
            "session_id": parent["session_id"],
            "parent_contract_sha256": parent["parent_contract_sha256"],
            "required_child_roles": list(required),
            "state": state,
            "missing_child_roles": missing,
            "children": children,
        }


class CanonicalMissionRouteLedger:
    """Durably admit at most one route for a canonical mission."""

    def __init__(
        self,
        database: Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS route_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS canonical_missions (
                    mission_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_attempt_id TEXT,
                    generation INTEGER NOT NULL DEFAULT 0,
                    last_route TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS route_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL,
                    route TEXT NOT NULL,
                    status TEXT NOT NULL,
                    owner_token_sha256 TEXT NOT NULL,
                    terminal_disposition TEXT,
                    result_sha256 TEXT,
                    reason TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(mission_id) REFERENCES canonical_missions(mission_id)
                );
                CREATE TABLE IF NOT EXISTS route_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mission_id TEXT NOT NULL,
                    attempt_id TEXT,
                    event TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO route_meta(key, value) "
                "VALUES('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
            existing = connection.execute(
                "SELECT value FROM route_meta WHERE key='schema_version'"
            ).fetchone()
            if existing is None or existing["value"] != SCHEMA_VERSION:
                raise RouteControlError("unsupported canonical route ledger schema")
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _mission(
        self,
        connection: sqlite3.Connection,
        mission_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM canonical_missions WHERE mission_id=?",
            (mission_id,),
        ).fetchone()

    def _assert_identity(
        self,
        mission: sqlite3.Row,
        *,
        session_id: str,
        payload_sha256: str,
    ) -> None:
        if mission["session_id"] != session_id or mission["payload_sha256"] != payload_sha256:
            raise RouteIdentityMismatch("canonical mission identity conflicts with durable state")

    def _event(
        self,
        connection: sqlite3.Connection,
        *,
        mission_id: str,
        attempt_id: str | None,
        event: str,
        state: str,
        now: float,
    ) -> None:
        connection.execute(
            """
            INSERT INTO route_events(
                mission_id, attempt_id, event, state, created_at
            ) VALUES(?, ?, ?, ?, ?)
            """,
            (mission_id, attempt_id, event, state, now),
        )

    def _authenticated_attempt(
        self,
        connection: sqlite3.Connection,
        *,
        mission: sqlite3.Row,
        owner_token: str,
        allowed_states: frozenset[str],
    ) -> sqlite3.Row:
        attempt_id = mission["current_attempt_id"]
        if not isinstance(attempt_id, str):
            raise RouteControlError("mission has no active route attempt")
        attempt = connection.execute(
            "SELECT * FROM route_attempts WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
        if attempt is None:
            raise RouteControlError("route attempt is missing")
        if attempt["owner_token_sha256"] != _token_sha256(owner_token):
            raise RouteAlreadyActive("route owner token does not match")
        if attempt["status"] not in allowed_states:
            raise RouteControlError(f"route transition is not allowed from {attempt['status']}")
        return attempt

    @staticmethod
    def _claim_value(mission: sqlite3.Row, attempt: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "mission_id": mission["mission_id"],
            "session_id": mission["session_id"],
            "payload_sha256": mission["payload_sha256"],
            "attempt_id": attempt["attempt_id"],
            "route": attempt["route"],
            "state": attempt["status"],
            "generation": mission["generation"],
        }

    def claim_route(
        self,
        *,
        mission_id: str,
        session_id: str,
        payload_sha256: str,
        route: str,
        owner_token: str,
    ) -> dict[str, Any]:
        """Claim one route, or reconstruct the same authenticated active claim."""
        _validate_identity(
            mission_id=mission_id,
            session_id=session_id,
            payload_sha256=payload_sha256,
        )
        if route not in ROUTES:
            raise RouteControlError("route is not governed")
        token_sha256 = _token_sha256(owner_token)
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            mission = self._mission(connection, mission_id)
            if mission is None:
                connection.execute(
                    """
                    INSERT INTO canonical_missions(
                        mission_id, session_id, payload_sha256, status,
                        current_attempt_id, generation, last_route,
                        created_at, updated_at
                    ) VALUES(?, ?, ?, 'available', NULL, 0, NULL, ?, ?)
                    """,
                    (mission_id, session_id, payload_sha256, now, now),
                )
                mission = self._mission(connection, mission_id)
                assert mission is not None
            self._assert_identity(
                mission,
                session_id=session_id,
                payload_sha256=payload_sha256,
            )
            if mission["status"] == "active":
                attempt = self._authenticated_attempt(
                    connection,
                    mission=mission,
                    owner_token=owner_token,
                    allowed_states=frozenset({"active"}),
                )
                if attempt["route"] != route:
                    raise RouteAlreadyActive("a different route is already active")
                connection.commit()
                return self._claim_value(mission, attempt)
            if mission["status"] == "outcome_unknown":
                raise RouteOutcomeUnknown("prior route outcome must reconcile before route change")
            if mission["status"] == "terminal_pending_release":
                raise RouteAlreadyActive("terminal route has not released")
            if mission["status"] in FINAL_STATES:
                raise RouteControlError("canonical mission is already terminal")
            if mission["status"] != "available":
                raise RouteControlError(f"unsupported canonical mission state {mission['status']}")
            generation = int(mission["generation"]) + 1
            attempt_id = f"{mission_id}.{generation:04d}"
            connection.execute(
                """
                INSERT INTO route_attempts(
                    attempt_id, mission_id, route, status,
                    owner_token_sha256, created_at, updated_at
                ) VALUES(?, ?, ?, 'active', ?, ?, ?)
                """,
                (attempt_id, mission_id, route, token_sha256, now, now),
            )
            connection.execute(
                """
                UPDATE canonical_missions
                SET status='active', current_attempt_id=?, generation=?,
                    last_route=?, updated_at=?
                WHERE mission_id=?
                """,
                (attempt_id, generation, route, now, mission_id),
            )
            self._event(
                connection,
                mission_id=mission_id,
                attempt_id=attempt_id,
                event="route_claimed",
                state="active",
                now=now,
            )
            mission = self._mission(connection, mission_id)
            attempt = connection.execute(
                "SELECT * FROM route_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            assert mission is not None and attempt is not None
            connection.commit()
            return self._claim_value(mission, attempt)

    def release_unavailable(
        self,
        *,
        mission_id: str,
        owner_token: str,
        reason: str,
    ) -> dict[str, Any]:
        """Release a route that unambiguously started no external work."""
        if not reason:
            raise RouteControlError("release reason is required")
        return self._transition_release(
            mission_id=mission_id,
            owner_token=owner_token,
            attempt_state="released_unavailable",
            mission_state="available",
            event="route_released_unavailable",
            reason=reason,
        )

    def mark_outcome_unknown(
        self,
        *,
        mission_id: str,
        owner_token: str,
        reason: str,
    ) -> dict[str, Any]:
        """Block all new routes until durable reconciliation."""
        if not reason:
            raise RouteControlError("unknown-outcome reason is required")
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            mission = self._mission(connection, mission_id)
            if mission is None:
                raise RouteControlError("canonical mission is absent")
            attempt = self._authenticated_attempt(
                connection,
                mission=mission,
                owner_token=owner_token,
                allowed_states=frozenset({"active"}),
            )
            connection.execute(
                "UPDATE route_attempts SET status='outcome_unknown', reason=?, "
                "updated_at=? WHERE attempt_id=?",
                (reason, now, attempt["attempt_id"]),
            )
            connection.execute(
                "UPDATE canonical_missions SET status='outcome_unknown', "
                "updated_at=? WHERE mission_id=?",
                (now, mission_id),
            )
            self._event(
                connection,
                mission_id=mission_id,
                attempt_id=attempt["attempt_id"],
                event="route_outcome_unknown",
                state="outcome_unknown",
                now=now,
            )
            connection.commit()
        return self.inspect(mission_id)

    def reconcile_unknown(
        self,
        *,
        mission_id: str,
        owner_token: str,
        resolution: str,
        reason: str,
    ) -> dict[str, Any]:
        """Resolve an ambiguous route from durable external evidence."""
        states = {
            "not_submitted": ("released_unavailable", "available"),
            "active": ("active", "active"),
            "completed": ("completed", "completed"),
            "failed": ("failed_final", "failed_final"),
        }
        if resolution not in states:
            raise RouteControlError("unknown-outcome resolution is invalid")
        attempt_state, mission_state = states[resolution]
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            mission = self._mission(connection, mission_id)
            if mission is None:
                raise RouteControlError("canonical mission is absent")
            attempt = self._authenticated_attempt(
                connection,
                mission=mission,
                owner_token=owner_token,
                allowed_states=frozenset({"outcome_unknown"}),
            )
            current_attempt = None if mission_state in FINAL_STATES else attempt["attempt_id"]
            if mission_state == "available":
                current_attempt = None
            connection.execute(
                "UPDATE route_attempts SET status=?, reason=?, updated_at=? " "WHERE attempt_id=?",
                (attempt_state, reason, now, attempt["attempt_id"]),
            )
            connection.execute(
                "UPDATE canonical_missions SET status=?, current_attempt_id=?, "
                "updated_at=? WHERE mission_id=?",
                (mission_state, current_attempt, now, mission_id),
            )
            self._event(
                connection,
                mission_id=mission_id,
                attempt_id=attempt["attempt_id"],
                event=f"route_reconciled_{resolution}",
                state=mission_state,
                now=now,
            )
            connection.commit()
        return self.inspect(mission_id)

    def terminalize(
        self,
        *,
        mission_id: str,
        owner_token: str,
        disposition: str,
        result_sha256: str,
    ) -> dict[str, Any]:
        """Persist terminal work before releasing the route owner."""
        if disposition not in {"completed", "failed"}:
            raise RouteControlError("terminal disposition is invalid")
        if not SHA256_RE.fullmatch(result_sha256):
            raise RouteControlError("terminal result SHA-256 is invalid")
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            mission = self._mission(connection, mission_id)
            if mission is None:
                raise RouteControlError("canonical mission is absent")
            attempt = self._authenticated_attempt(
                connection,
                mission=mission,
                owner_token=owner_token,
                allowed_states=frozenset({"active"}),
            )
            connection.execute(
                """
                UPDATE route_attempts
                SET status='terminal_pending_release',
                    terminal_disposition=?, result_sha256=?, updated_at=?
                WHERE attempt_id=?
                """,
                (disposition, result_sha256, now, attempt["attempt_id"]),
            )
            connection.execute(
                "UPDATE canonical_missions SET status='terminal_pending_release', "
                "updated_at=? WHERE mission_id=?",
                (now, mission_id),
            )
            self._event(
                connection,
                mission_id=mission_id,
                attempt_id=attempt["attempt_id"],
                event="route_terminal_persisted",
                state="terminal_pending_release",
                now=now,
            )
            connection.commit()
        return self.inspect(mission_id)

    def release_terminal(
        self,
        *,
        mission_id: str,
        owner_token: str,
    ) -> dict[str, Any]:
        """Durably release a terminal route without reopening the mission."""
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            mission = self._mission(connection, mission_id)
            if mission is None:
                raise RouteControlError("canonical mission is absent")
            attempt = self._authenticated_attempt(
                connection,
                mission=mission,
                owner_token=owner_token,
                allowed_states=frozenset({"terminal_pending_release"}),
            )
            final_state = (
                "completed" if attempt["terminal_disposition"] == "completed" else "failed_final"
            )
            connection.execute(
                "UPDATE route_attempts SET status=?, updated_at=? WHERE attempt_id=?",
                (final_state, now, attempt["attempt_id"]),
            )
            connection.execute(
                "UPDATE canonical_missions SET status=?, current_attempt_id=NULL, "
                "updated_at=? WHERE mission_id=?",
                (final_state, now, mission_id),
            )
            self._event(
                connection,
                mission_id=mission_id,
                attempt_id=attempt["attempt_id"],
                event="terminal_route_released",
                state=final_state,
                now=now,
            )
            connection.commit()
        return self.inspect(mission_id)

    def _transition_release(
        self,
        *,
        mission_id: str,
        owner_token: str,
        attempt_state: str,
        mission_state: str,
        event: str,
        reason: str,
    ) -> dict[str, Any]:
        now = self.clock()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            mission = self._mission(connection, mission_id)
            if mission is None:
                raise RouteControlError("canonical mission is absent")
            attempt = self._authenticated_attempt(
                connection,
                mission=mission,
                owner_token=owner_token,
                allowed_states=frozenset({"active"}),
            )
            connection.execute(
                "UPDATE route_attempts SET status=?, reason=?, updated_at=? " "WHERE attempt_id=?",
                (attempt_state, reason, now, attempt["attempt_id"]),
            )
            connection.execute(
                "UPDATE canonical_missions SET status=?, current_attempt_id=NULL, "
                "updated_at=? WHERE mission_id=?",
                (mission_state, now, mission_id),
            )
            self._event(
                connection,
                mission_id=mission_id,
                attempt_id=attempt["attempt_id"],
                event=event,
                state=mission_state,
                now=now,
            )
            connection.commit()
        return self.inspect(mission_id)

    def inspect(self, mission_id: str) -> dict[str, Any]:
        """Return non-secret durable route state for one mission."""
        with self._connect() as connection:
            mission = self._mission(connection, mission_id)
            if mission is None:
                raise RouteControlError("canonical mission is absent")
            attempt = None
            if mission["current_attempt_id"]:
                attempt = connection.execute(
                    "SELECT route, status, attempt_id FROM route_attempts " "WHERE attempt_id=?",
                    (mission["current_attempt_id"],),
                ).fetchone()
            return {
                "schema_version": SCHEMA_VERSION,
                "mission_id": mission["mission_id"],
                "session_id": mission["session_id"],
                "payload_sha256": mission["payload_sha256"],
                "state": mission["status"],
                "route": attempt["route"] if attempt else mission["last_route"],
                "attempt_id": attempt["attempt_id"] if attempt else None,
                "generation": mission["generation"],
            }

    def events(self, mission_id: str) -> list[dict[str, Any]]:
        """Return ordered non-secret transition evidence."""
        with self._connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT event_id, mission_id, attempt_id, event, state, "
                    "created_at FROM route_events WHERE mission_id=? "
                    "ORDER BY event_id",
                    (mission_id,),
                )
            ]
