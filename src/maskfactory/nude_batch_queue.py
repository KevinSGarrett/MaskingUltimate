"""Durable SQLite orchestration for the adult-corpus 256-record shards."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .nude_record_qualification import (
    validate_nonacceptance_queue_payload,
    validate_qualified_queue_payload,
)

TERMINAL_OUTCOMES = frozenset(
    {"accepted", "repaired", "abstained", "rejected", "quarantined", "holdout"}
)


class NudeBatchQueueError(RuntimeError):
    """Queue state or caller ownership failed closed."""


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class NudeBatchQueue:
    def __init__(self, path: Path, *, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.path = Path(path)
        self.max_attempts = max_attempts
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS shards (
                    platform TEXT NOT NULL,
                    shard_path TEXT NOT NULL,
                    lane TEXT NOT NULL,
                    shard_sha256 TEXT NOT NULL,
                    sample_count INTEGER NOT NULL CHECK(sample_count > 0),
                    state TEXT NOT NULL CHECK(state IN
                        ('queued','leased','submitted_unknown','complete','failed')),
                    next_sample_index INTEGER NOT NULL DEFAULT 0,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_token TEXT,
                    lease_expires_at REAL,
                    submission_id TEXT,
                    last_error TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(platform, shard_path)
                );
                CREATE TABLE IF NOT EXISTS record_outcomes (
                    platform TEXT NOT NULL,
                    sample_id TEXT NOT NULL,
                    shard_path TEXT NOT NULL,
                    sample_index INTEGER NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at REAL NOT NULL,
                    PRIMARY KEY(platform, sample_id),
                    UNIQUE(platform, shard_path, sample_index),
                    FOREIGN KEY(platform, shard_path) REFERENCES shards(platform, shard_path)
                );
                CREATE TABLE IF NOT EXISTS queue_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at REAL NOT NULL,
                    platform TEXT NOT NULL,
                    shard_path TEXT NOT NULL,
                    event TEXT NOT NULL,
                    detail_json TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        *,
        platform: str,
        shard_path: str,
        event: str,
        detail: Mapping[str, Any],
        now: float,
    ) -> None:
        connection.execute(
            "INSERT INTO queue_events(recorded_at,platform,shard_path,event,detail_json) "
            "VALUES(?,?,?,?,?)",
            (now, platform, shard_path, event, json.dumps(detail, sort_keys=True)),
        )

    def seed(self, descriptors: Sequence[Mapping[str, Any]], *, platform: str) -> dict[str, int]:
        selected = [row for row in descriptors if row.get("platform") == platform]
        if not selected:
            raise NudeBatchQueueError("no descriptors selected")
        inserted = 0
        retained = 0
        now = time.time()
        with self._transaction() as connection:
            for descriptor in selected:
                values = (
                    platform,
                    str(descriptor["path"]),
                    str(descriptor["lane"]),
                    str(descriptor["self_sha256"]),
                    int(descriptor["sample_count"]),
                )
                existing = connection.execute(
                    "SELECT lane,shard_sha256,sample_count FROM shards "
                    "WHERE platform=? AND shard_path=?",
                    values[:2],
                ).fetchone()
                if existing:
                    if tuple(existing) != values[2:]:
                        raise NudeBatchQueueError("seed descriptor drift")
                    retained += 1
                    continue
                connection.execute(
                    "INSERT INTO shards(platform,shard_path,lane,shard_sha256,sample_count,state,updated_at) "
                    "VALUES(?,?,?,?,?,'queued',?)",
                    (*values, now),
                )
                self._event(
                    connection,
                    platform=platform,
                    shard_path=values[1],
                    event="seeded",
                    detail={"lane": values[2], "sample_count": values[4]},
                    now=now,
                )
                inserted += 1
        return {"inserted": inserted, "retained": retained, "selected": len(selected)}

    def claim(
        self, *, platform: str, owner: str, lease_seconds: int = 900
    ) -> dict[str, Any] | None:
        if not owner or lease_seconds < 1:
            raise ValueError("owner and positive lease_seconds are required")
        now = time.time()
        with self._transaction() as connection:
            exhausted = connection.execute(
                "SELECT shard_path FROM shards WHERE platform=? AND state='leased' "
                "AND lease_expires_at<=? AND attempt_count>=?",
                (platform, now, self.max_attempts),
            ).fetchall()
            for row in exhausted:
                connection.execute(
                    "UPDATE shards SET state='failed',lease_owner=NULL,lease_token=NULL,"
                    "lease_expires_at=NULL,last_error='retry_cap_exhausted',updated_at=? "
                    "WHERE platform=? AND shard_path=?",
                    (now, platform, row["shard_path"]),
                )
            row = connection.execute(
                "SELECT * FROM shards WHERE platform=? AND "
                "(state='queued' OR (state='leased' AND lease_expires_at<=? AND attempt_count<?)) "
                "ORDER BY CASE lane "
                "WHEN 'bbox_evaluation_only' THEN 0 "
                "WHEN 'bbox_prompt_and_action_tag_supervision' THEN 1 "
                "WHEN 'bbox_prompt_supervision' THEN 2 "
                "WHEN 'polygon_external_supervision' THEN 3 ELSE 4 END, shard_path LIMIT 1",
                (platform, now, self.max_attempts),
            ).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            connection.execute(
                "UPDATE shards SET state='leased',attempt_count=attempt_count+1,lease_owner=?,"
                "lease_token=?,lease_expires_at=?,updated_at=? WHERE platform=? AND shard_path=?",
                (owner, token, now + lease_seconds, now, platform, row["shard_path"]),
            )
            self._event(
                connection,
                platform=platform,
                shard_path=row["shard_path"],
                event="claimed",
                detail={"owner": owner, "lease_token": token},
                now=now,
            )
            result = dict(row)
            result.update(
                {
                    "state": "leased",
                    "attempt_count": int(row["attempt_count"]) + 1,
                    "lease_owner": owner,
                    "lease_token": token,
                    "lease_expires_at": now + lease_seconds,
                }
            )
            return result

    @staticmethod
    def _owned_lease(
        connection: sqlite3.Connection, platform: str, shard_path: str, token: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM shards WHERE platform=? AND shard_path=?",
            (platform, shard_path),
        ).fetchone()
        if row is None or row["state"] != "leased" or row["lease_token"] != token:
            raise NudeBatchQueueError("owned live lease required")
        if float(row["lease_expires_at"] or 0) <= time.time():
            raise NudeBatchQueueError("owned lease expired")
        return row

    def heartbeat(
        self, *, platform: str, shard_path: str, lease_token: str, lease_seconds: int = 900
    ) -> None:
        now = time.time()
        with self._transaction() as connection:
            row = self._owned_lease(connection, platform, shard_path, lease_token)
            if float(row["lease_expires_at"]) <= now:
                raise NudeBatchQueueError("lease expired")
            connection.execute(
                "UPDATE shards SET lease_expires_at=?,updated_at=? WHERE platform=? AND shard_path=?",
                (now + lease_seconds, now, platform, shard_path),
            )

    def checkpoint(
        self,
        *,
        platform: str,
        shard_path: str,
        lease_token: str,
        outcomes: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if not outcomes:
            raise NudeBatchQueueError("empty checkpoint")
        now = time.time()
        with self._transaction() as connection:
            shard = self._owned_lease(connection, platform, shard_path, lease_token)
            expected_index = int(shard["next_sample_index"])
            before_total = int(
                connection.execute(
                    "SELECT COALESCE(SUM(next_sample_index),0) FROM shards WHERE platform=?",
                    (platform,),
                ).fetchone()[0]
            )
            first_index = int(outcomes[0]["sample_index"])
            if first_index < expected_index:
                for offset, outcome in enumerate(outcomes):
                    sample_index = int(outcome["sample_index"])
                    if sample_index != first_index + offset or sample_index >= expected_index:
                        raise NudeBatchQueueError("checkpoint replay overlaps new work")
                    payload_sha = _canonical_sha256(dict(outcome))
                    existing = connection.execute(
                        "SELECT payload_sha256 FROM record_outcomes WHERE platform=? "
                        "AND shard_path=? AND sample_index=?",
                        (platform, shard_path, sample_index),
                    ).fetchone()
                    if existing is None or existing["payload_sha256"] != payload_sha:
                        raise NudeBatchQueueError("idempotency conflict")
                return {
                    "inserted": 0,
                    "next_sample_index": expected_index,
                    "complete": False,
                    "idempotent_replay": True,
                }
            inserted = 0
            for offset, outcome in enumerate(outcomes):
                sample_index = int(outcome["sample_index"])
                if sample_index != expected_index + offset:
                    raise NudeBatchQueueError("checkpoint must be contiguous")
                if outcome.get("outcome") not in TERMINAL_OUTCOMES:
                    raise NudeBatchQueueError("terminal outcome invalid")
                if outcome.get("outcome") in {"accepted", "repaired"}:
                    validate_qualified_queue_payload(outcome)
                if outcome.get("outcome") in {"abstained", "rejected"}:
                    validate_nonacceptance_queue_payload(outcome)
                source_sha = str(outcome.get("source_sha256", ""))
                evidence_sha = str(outcome.get("evidence_sha256", ""))
                if len(source_sha) != 64 or len(evidence_sha) != 64:
                    raise NudeBatchQueueError("hash binding invalid")
                payload = dict(outcome)
                payload_sha = _canonical_sha256(payload)
                try:
                    connection.execute(
                        "INSERT INTO record_outcomes(platform,sample_id,shard_path,sample_index,"
                        "source_sha256,outcome,evidence_sha256,payload_sha256,payload_json,recorded_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            platform,
                            str(outcome["sample_id"]),
                            shard_path,
                            sample_index,
                            source_sha,
                            outcome["outcome"],
                            evidence_sha,
                            payload_sha,
                            json.dumps(payload, sort_keys=True),
                            now,
                        ),
                    )
                    inserted += 1
                except sqlite3.IntegrityError as exc:
                    existing = connection.execute(
                        "SELECT payload_sha256 FROM record_outcomes WHERE platform=? AND sample_id=?",
                        (platform, str(outcome["sample_id"])),
                    ).fetchone()
                    if existing is None or existing["payload_sha256"] != payload_sha:
                        raise NudeBatchQueueError("idempotency conflict") from exc
            next_index = expected_index + len(outcomes)
            if next_index > int(shard["sample_count"]):
                raise NudeBatchQueueError("checkpoint exceeds shard")
            complete = next_index == int(shard["sample_count"])
            connection.execute(
                "UPDATE shards SET next_sample_index=?,state=?,lease_owner=?,lease_token=?,"
                "lease_expires_at=?,updated_at=? WHERE platform=? AND shard_path=?",
                (
                    next_index,
                    "complete" if complete else "leased",
                    None if complete else shard["lease_owner"],
                    None if complete else lease_token,
                    None if complete else shard["lease_expires_at"],
                    now,
                    platform,
                    shard_path,
                ),
            )
            self._event(
                connection,
                platform=platform,
                shard_path=shard_path,
                event="checkpoint",
                detail={"next_sample_index": next_index, "complete": complete},
                now=now,
            )
            after_total = before_total + len(outcomes)
            if before_total // 1000 < after_total // 1000:
                self._event(
                    connection,
                    platform=platform,
                    shard_path=shard_path,
                    event="thousand_record_milestone",
                    detail={"checkpointed_records": after_total},
                    now=now,
                )
            return {"inserted": inserted, "next_sample_index": next_index, "complete": complete}

    def checkpoint_qualified(
        self,
        *,
        platform: str,
        shard_path: str,
        lease_token: str,
        outcomes: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Checkpoint accepted/repaired rows only after exact evidence revalidation."""

        validated = []
        for outcome in outcomes:
            payload = validate_qualified_queue_payload(outcome)
            if "sample_index" not in payload:
                raise NudeBatchQueueError("qualified outcome sample_index required")
            validated.append(payload)
        return self.checkpoint(
            platform=platform,
            shard_path=shard_path,
            lease_token=lease_token,
            outcomes=validated,
        )

    def mark_submitted_unknown(
        self,
        *,
        platform: str,
        shard_path: str,
        lease_token: str,
        submission_id: str,
    ) -> None:
        now = time.time()
        with self._transaction() as connection:
            self._owned_lease(connection, platform, shard_path, lease_token)
            connection.execute(
                "UPDATE shards SET state='submitted_unknown',submission_id=?,lease_owner=NULL,"
                "lease_token=NULL,lease_expires_at=NULL,updated_at=? WHERE platform=? AND shard_path=?",
                (submission_id, now, platform, shard_path),
            )

    def reconcile_submitted_unknown(
        self, *, platform: str, shard_path: str, submission_id: str, observed: str
    ) -> None:
        if observed not in {"not_submitted", "submitted"}:
            raise ValueError("observed must be not_submitted or submitted")
        now = time.time()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT state,submission_id FROM shards WHERE platform=? AND shard_path=?",
                (platform, shard_path),
            ).fetchone()
            if (
                row is None
                or row["state"] != "submitted_unknown"
                or row["submission_id"] != submission_id
            ):
                raise NudeBatchQueueError("matching submitted-unknown state required")
            state = "queued" if observed == "not_submitted" else "failed"
            reason = None if observed == "not_submitted" else "submitted_requires_external_recovery"
            connection.execute(
                "UPDATE shards SET state=?,submission_id=NULL,last_error=?,updated_at=? "
                "WHERE platform=? AND shard_path=?",
                (state, reason, now, platform, shard_path),
            )

    def summary(self, *, platform: str) -> dict[str, Any]:
        with self._connect() as connection:
            states = {
                row["state"]: int(row["count"])
                for row in connection.execute(
                    "SELECT state,COUNT(*) AS count FROM shards WHERE platform=? GROUP BY state",
                    (platform,),
                )
            }
            outcomes = {
                row["outcome"]: int(row["count"])
                for row in connection.execute(
                    "SELECT outcome,COUNT(*) AS count FROM record_outcomes "
                    "WHERE platform=? GROUP BY outcome",
                    (platform,),
                )
            }
            totals = connection.execute(
                "SELECT COUNT(*) AS shards,COALESCE(SUM(sample_count),0) AS records,"
                "COALESCE(SUM(next_sample_index),0) AS checkpointed FROM shards WHERE platform=?",
                (platform,),
            ).fetchone()
        return {
            "platform": platform,
            "shards": int(totals["shards"]),
            "records": int(totals["records"]),
            "checkpointed_records": int(totals["checkpointed"]),
            "states": states,
            "outcomes": outcomes,
        }
