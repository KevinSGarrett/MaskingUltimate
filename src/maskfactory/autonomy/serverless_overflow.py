"""Durable, budgeted admission for shared RunPod Serverless overflow.

The broker is intentionally workload-agnostic. It decides whether a job may use
one of two profile-specific endpoints and persists the decision on the RunPod
network volume. It never kills, pauses, or otherwise controls a local GPU process.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

import yaml


class OverflowError(RuntimeError):
    """Overflow configuration, admission, or provider interaction failed closed."""


ACTIVE_STATES = ("reserved", "submitted", "running")
TERMINAL_STATES = ("completed", "failed", "cancelled")


@dataclass(frozen=True)
class OverflowConfig:
    sessions: Mapping[str, str]
    endpoints: Mapping[str, str | None]
    hard_daily_limit_usd: float
    admission_limit_usd: float
    rolling_hour_hard_limit_usd: float
    rolling_hour_admission_limit_usd: float
    rolling_hour_seconds: int
    max_rate_usd_per_second: float
    cold_start_reserve_seconds: int
    max_global_inflight_jobs: int
    execution_timeout_seconds: int
    queue_timeout_seconds: int
    idle_timeout_seconds: int
    network_volume_id: str
    datacenter_id: str
    comfyui_queue_url: str
    probe_timeout_seconds: float
    runpod_root: Path
    sqlite_filename: str

    @classmethod
    def load(cls, path: Path) -> "OverflowConfig":
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if document.get("schema_version") != "maskfactory.runpod_serverless_overflow.v1":
            raise OverflowError("unsupported overflow configuration schema")
        sessions = document.get("sessions")
        if not isinstance(sessions, dict) or not sessions:
            raise OverflowError("overflow configuration requires sessions")
        session_profiles: dict[str, str] = {}
        for session_id, row in sessions.items():
            if not isinstance(row, dict) or row.get("profile") not in {"comfyui", "maskfactory"}:
                raise OverflowError(f"invalid session profile: {session_id}")
            session_profiles[str(session_id)] = str(row["profile"])

        runpod = document["runpod"]
        budget = document["budget"]
        local_gpu = document["local_gpu"]
        durability = document["durability"]
        hard_limit = float(budget["hard_daily_limit_usd"])
        admission_limit = float(budget["admission_limit_usd"])
        variance = float(budget["provider_variance_reserve_usd"])
        if admission_limit + variance > hard_limit:
            raise OverflowError("admission and provider variance reserves exceed hard daily limit")
        hour_hard_limit = float(budget["rolling_hour_hard_limit_usd"])
        hour_admission_limit = float(budget["rolling_hour_admission_limit_usd"])
        hour_variance = float(budget["rolling_hour_variance_reserve_usd"])
        if hour_admission_limit + hour_variance > hour_hard_limit:
            raise OverflowError("hourly admission and variance reserves exceed hourly limit")
        if int(budget["rolling_hour_seconds"]) != 3600:
            raise OverflowError("rolling hourly budget window must be 3600 seconds")
        if budget.get("timezone") != "UTC":
            raise OverflowError("provider billing boundary must be UTC")
        if int(runpod["workers_min"]) != 0 or int(runpod["workers_max"]) != 1:
            raise OverflowError("overflow endpoints must scale from zero with one worker maximum")
        queue_timeout_seconds = int(runpod["queue_timeout_seconds"])
        if queue_timeout_seconds < 10:
            raise OverflowError("Serverless queue timeout must be at least 10 seconds")
        if int(budget["max_global_inflight_jobs"]) != 1:
            raise OverflowError("shared overflow requires exactly one global in-flight job")
        if runpod["datacenter_id"] != "US-WA-1":
            raise OverflowError("overflow must remain in the network volume datacenter US-WA-1")
        if runpod["network_volume_id"] != "o9qv2ld91c":
            raise OverflowError("unexpected RunPod network volume")
        return cls(
            sessions=session_profiles,
            endpoints=dict(runpod["endpoints"]),
            hard_daily_limit_usd=hard_limit,
            admission_limit_usd=admission_limit,
            rolling_hour_hard_limit_usd=hour_hard_limit,
            rolling_hour_admission_limit_usd=hour_admission_limit,
            rolling_hour_seconds=int(budget["rolling_hour_seconds"]),
            max_rate_usd_per_second=float(budget["max_active_rate_usd_per_second"]),
            cold_start_reserve_seconds=int(budget["cold_start_reserve_seconds"]),
            max_global_inflight_jobs=int(budget["max_global_inflight_jobs"]),
            execution_timeout_seconds=int(runpod["execution_timeout_seconds"]),
            queue_timeout_seconds=queue_timeout_seconds,
            idle_timeout_seconds=int(runpod["idle_timeout_seconds"]),
            network_volume_id=str(runpod["network_volume_id"]),
            datacenter_id=str(runpod["datacenter_id"]),
            comfyui_queue_url=str(local_gpu["comfyui_queue_url"]),
            probe_timeout_seconds=float(local_gpu["probe_timeout_seconds"]),
            runpod_root=Path(durability["runpod_root"]),
            sqlite_filename=str(durability["sqlite_filename"]),
        )


def canonical_payload_sha256(value: Mapping[str, Any]) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def utc_billing_day(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).date().isoformat()


def probe_local_gpu(config: OverflowConfig) -> dict[str, Any]:
    """Return conservative local availability without controlling any process."""

    reasons: list[str] = []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_memory",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=config.probe_timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "reason": "nvidia_smi_unavailable"}
    if result.returncode != 0:
        return {"available": False, "reason": "nvidia_smi_failed"}
    if result.stdout.strip():
        reasons.append("gpu_compute_process_present")

    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed localhost URL from governed config
            config.comfyui_queue_url, timeout=config.probe_timeout_seconds
        ) as response:
            queue = json.loads(response.read().decode("utf-8"))
        if queue.get("queue_running") or queue.get("queue_pending"):
            reasons.append("comfyui_queue_nonempty")
    except (OSError, ValueError, urllib.error.URLError):
        # nvidia-smi remains authoritative for current use. A missing ComfyUI
        # service is normal for a MaskFactory-only pod.
        pass
    return {
        "available": not reasons,
        "reason": ",".join(reasons) if reasons else "gpu_idle",
    }


class RunPodClient:
    """Small stdlib-only client for RunPod queue endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        timeout_seconds: float = 30,
    ) -> None:
        if not api_key:
            raise OverflowError("RUNPOD_API_KEY is required")
        self.api_key = api_key
        self.opener = opener
        self.timeout_seconds = timeout_seconds

    def _request_json(
        self, method: str, url: str, document: Mapping[str, Any] | None = None
    ) -> Any:
        body = None
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if document is not None:
            body = json.dumps(document, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OverflowError(f"RunPod HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise OverflowError(f"RunPod request failed: {exc.reason}") from exc
        if not payload:
            return {}
        return json.loads(payload.decode("utf-8"))

    def _request(
        self, method: str, url: str, document: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        result = self._request_json(method, url, document)
        if not isinstance(result, dict):
            raise OverflowError("RunPod response must be an object")
        return result

    def submit(
        self,
        endpoint_id: str,
        payload: Mapping[str, Any],
        *,
        execution_timeout_seconds: int,
        queue_timeout_seconds: int,
    ) -> dict[str, Any]:
        execution_timeout_ms = execution_timeout_seconds * 1000
        # RunPod's ttl covers queue and execution rather than queue alone.
        # Include both windows so the broker can cancel only queued work at
        # queue_timeout_seconds without deleting a valid running job.
        ttl_ms = (queue_timeout_seconds + execution_timeout_seconds) * 1000
        return self._request(
            "POST",
            f"https://api.runpod.ai/v2/{endpoint_id}/run",
            {
                "input": payload,
                "policy": {
                    "executionTimeout": execution_timeout_ms,
                    "ttl": ttl_ms,
                },
            },
        )

    def status(self, endpoint_id: str, provider_job_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"https://api.runpod.ai/v2/{endpoint_id}/status/{provider_job_id}"
        )

    def cancel(self, endpoint_id: str, provider_job_id: str) -> dict[str, Any]:
        return self._request(
            "POST", f"https://api.runpod.ai/v2/{endpoint_id}/cancel/{provider_job_id}"
        )

    def endpoint_spend(
        self,
        endpoint_ids: list[str],
        *,
        start_timestamp: float,
        end_timestamp: float | None = None,
        bucket_size: str,
    ) -> float:
        if not endpoint_ids:
            return 0.0
        now = datetime.fromtimestamp(end_timestamp or time.time(), tz=UTC)
        start = datetime.fromtimestamp(start_timestamp, tz=UTC)
        amount = 0.0
        for endpoint_id in sorted(set(endpoint_ids)):
            query = urllib.parse.urlencode(
                {
                    "bucketSize": bucket_size,
                    "grouping": "endpointId",
                    "endpointId": endpoint_id,
                    "startTime": start.isoformat().replace("+00:00", "Z"),
                    "endTime": now.isoformat().replace("+00:00", "Z"),
                }
            )
            result = self._request_json(
                "GET", f"https://rest.runpod.io/v1/billing/endpoints?{query}"
            )
            if not isinstance(result, list):
                raise OverflowError("RunPod billing response must be an array")
            for row in result:
                if not isinstance(row, dict) or not isinstance(row.get("amount"), (int, float)):
                    raise OverflowError("RunPod billing record is invalid")
                amount += float(row["amount"])
        return amount

    def daily_endpoint_spend(
        self, endpoint_ids: list[str], *, timestamp: float | None = None
    ) -> float:
        now = timestamp or time.time()
        day_start = datetime.fromtimestamp(now, tz=UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return self.endpoint_spend(
            endpoint_ids,
            start_timestamp=day_start.timestamp(),
            end_timestamp=now,
            bucket_size="day",
        )

    def rolling_hour_endpoint_spend(
        self, endpoint_ids: list[str], *, timestamp: float | None = None
    ) -> float:
        now = timestamp or time.time()
        return self.endpoint_spend(
            endpoint_ids,
            start_timestamp=now - 3600,
            end_timestamp=now,
            bucket_size="hour",
        )


class OverflowBroker:
    """SQLite-backed, cross-session Serverless overflow admission."""

    def __init__(
        self,
        config: OverflowConfig,
        *,
        root: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.root = Path(root) if root is not None else config.runpod_root
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / config.sqlite_filename
        self._clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
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
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    billing_day TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    endpoint_id TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    requested_seconds INTEGER NOT NULL,
                    reserved_usd REAL NOT NULL,
                    actual_usd REAL,
                    state TEXT NOT NULL,
                    provider_job_id TEXT UNIQUE,
                    submitted_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    provider_status_json TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_day_state
                    ON jobs (billing_day, state);
                """
            )
            columns = {
                str(row["name"]) for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "submitted_at" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN submitted_at REAL")

    def _validate_request(
        self,
        session_id: str,
        profile: str,
        payload: Mapping[str, Any],
        requested_seconds: int,
    ) -> str:
        expected_profile = self.config.sessions.get(session_id)
        if expected_profile is None:
            raise OverflowError("session is not authorized for shared overflow")
        if profile != expected_profile:
            raise OverflowError("session/profile binding mismatch")
        endpoint_id = self.config.endpoints.get(profile)
        if not endpoint_id:
            raise OverflowError(f"Serverless endpoint is not configured: {profile}")
        if not isinstance(payload, Mapping) or not payload:
            raise OverflowError("job payload must be a non-empty object")
        if requested_seconds < 1 or requested_seconds > self.config.execution_timeout_seconds:
            raise OverflowError("requested seconds exceed endpoint execution timeout")
        return endpoint_id

    def reserve(
        self,
        *,
        session_id: str,
        profile: str,
        payload: Mapping[str, Any],
        requested_seconds: int,
        observed_provider_spend_usd: float = 0.0,
        observed_provider_hour_spend_usd: float = 0.0,
    ) -> dict[str, Any]:
        endpoint_id = self._validate_request(session_id, profile, payload, requested_seconds)
        now = self._clock()
        day = utc_billing_day(now)
        # The stock ComfyUI handler has no trustworthy per-request timeout
        # control, so reserve the endpoint's full hard timeout for that profile.
        # The MaskFactory handler enforces its payload timeout itself.
        budgeted_execution_seconds = (
            self.config.execution_timeout_seconds if profile == "comfyui" else requested_seconds
        )
        reserve_seconds = (
            budgeted_execution_seconds
            + self.config.cold_start_reserve_seconds
            + self.config.idle_timeout_seconds
        )
        reserved_usd = reserve_seconds * self.config.max_rate_usd_per_second
        with self._transaction() as connection:
            active_count = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE state IN ('reserved','submitted','running')"
            ).fetchone()[0]
            if active_count >= self.config.max_global_inflight_jobs:
                raise OverflowError("shared Serverless overflow already has an in-flight job")
            daily_terminal_reserved = connection.execute(
                """
                SELECT COALESCE(SUM(COALESCE(actual_usd, reserved_usd)), 0.0)
                FROM jobs
                WHERE billing_day = ? AND state IN ('completed','failed')
                """,
                (day,),
            ).fetchone()[0]
            daily_active_reserved = connection.execute(
                """
                SELECT COALESCE(SUM(reserved_usd), 0.0)
                FROM jobs
                WHERE billing_day = ? AND state IN ('reserved','submitted','running')
                """,
                (day,),
            ).fetchone()[0]
            hourly_terminal_reserved = connection.execute(
                """
                SELECT COALESCE(SUM(COALESCE(actual_usd, reserved_usd)), 0.0)
                FROM jobs
                WHERE created_at >= ? AND state IN ('completed','failed')
                """,
                (now - self.config.rolling_hour_seconds,),
            ).fetchone()[0]
            hourly_active_reserved = connection.execute(
                """
                SELECT COALESCE(SUM(reserved_usd), 0.0)
                FROM jobs
                WHERE created_at >= ? AND state IN ('reserved','submitted','running')
                """,
                (now - self.config.rolling_hour_seconds,),
            ).fetchone()[0]
            # Provider billing can lag while local terminal reservations are
            # immediate. Max() avoids double-counting the same completed job
            # while retaining the more conservative of the two observations.
            projected = (
                max(float(observed_provider_spend_usd), float(daily_terminal_reserved))
                + float(daily_active_reserved)
                + reserved_usd
            )
            if projected > self.config.admission_limit_usd:
                raise OverflowError(
                    "daily Serverless admission limit would be exceeded "
                    f"({projected:.4f} > {self.config.admission_limit_usd:.2f})"
                )
            hourly_projected = (
                max(
                    float(observed_provider_hour_spend_usd),
                    float(hourly_terminal_reserved),
                )
                + float(hourly_active_reserved)
                + reserved_usd
            )
            if hourly_projected > self.config.rolling_hour_admission_limit_usd:
                raise OverflowError(
                    "rolling hourly Serverless admission limit would be exceeded "
                    f"({hourly_projected:.4f} > "
                    f"{self.config.rolling_hour_admission_limit_usd:.2f})"
                )
            job_id = f"overflow-{uuid.uuid4()}"
            payload_sha256 = canonical_payload_sha256(payload)
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, billing_day, session_id, profile, endpoint_id,
                    payload_sha256, requested_seconds, reserved_usd, state,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?)
                """,
                (
                    job_id,
                    day,
                    session_id,
                    profile,
                    endpoint_id,
                    payload_sha256,
                    requested_seconds,
                    reserved_usd,
                    now,
                    now,
                ),
            )
        return {
            "job_id": job_id,
            "billing_day": day,
            "session_id": session_id,
            "profile": profile,
            "endpoint_id": endpoint_id,
            "payload_sha256": payload_sha256,
            "reserved_usd": round(reserved_usd, 6),
            "state": "reserved",
        }

    def submit_reserved(
        self, job_id: str, payload: Mapping[str, Any], client: RunPodClient
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise OverflowError("overflow job not found")
            if row["state"] != "reserved":
                raise OverflowError("only a reserved job may be submitted")
            if canonical_payload_sha256(payload) != row["payload_sha256"]:
                raise OverflowError("payload changed after budget reservation")
            # Hold the write transaction through submission. This prevents a
            # second broker process from admitting a competing profile.
            try:
                budgeted_execution_seconds = (
                    self.config.execution_timeout_seconds
                    if row["profile"] == "comfyui"
                    else int(row["requested_seconds"])
                )
                response = client.submit(
                    row["endpoint_id"],
                    payload,
                    execution_timeout_seconds=budgeted_execution_seconds,
                    queue_timeout_seconds=self.config.queue_timeout_seconds,
                )
            except Exception:
                # An HTTP timeout is ambiguous: RunPod may have accepted the
                # request. Keep the reservation active and require reconciliation.
                connection.execute(
                    "UPDATE jobs SET state='running', updated_at=? WHERE job_id=?",
                    (self._clock(), job_id),
                )
                raise
            provider_job_id = response.get("id")
            if not isinstance(provider_job_id, str) or not provider_job_id:
                connection.execute(
                    "UPDATE jobs SET state='running', updated_at=? WHERE job_id=?",
                    (self._clock(), job_id),
                )
                raise OverflowError("RunPod submission did not return a job id")
            connection.execute(
                """
                UPDATE jobs
                SET state='submitted', provider_job_id=?, submitted_at=?, updated_at=?,
                    provider_status_json=?
                WHERE job_id=?
                """,
                (
                    provider_job_id,
                    self._clock(),
                    self._clock(),
                    json.dumps(response, sort_keys=True),
                    job_id,
                ),
            )
        return {**dict(row), "state": "submitted", "provider_job_id": provider_job_id}

    def reconcile(self, job_id: str, client: RunPodClient) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise OverflowError("overflow job not found")
        if row["state"] in TERMINAL_STATES:
            return dict(row)
        if not row["provider_job_id"]:
            raise OverflowError("reserved job has no provider id; manual reconciliation required")
        response = client.status(row["endpoint_id"], row["provider_job_id"])
        provider_state = str(response.get("status", "")).upper()
        submitted_at = float(row["submitted_at"] or row["created_at"])
        if (
            provider_state == "IN_QUEUE"
            and self._clock() - submitted_at >= self.config.queue_timeout_seconds
        ):
            cancel_response = client.cancel(row["endpoint_id"], row["provider_job_id"])
            response = {
                "status": "CANCELLED",
                "reason": "queue_timeout",
                "queue_timeout_seconds": self.config.queue_timeout_seconds,
                "provider_status": response,
                "provider_cancel": cancel_response,
            }
            provider_state = "CANCELLED"
        state = {
            "IN_QUEUE": "submitted",
            "IN_PROGRESS": "running",
            "COMPLETED": "completed",
            "FAILED": "failed",
            "TIMED_OUT": "failed",
            "CANCELLED": "cancelled",
        }.get(provider_state)
        if state is None:
            raise OverflowError(f"unknown RunPod job state: {provider_state or '<missing>'}")
        execution_ms = response.get("executionTime")
        actual_usd = None
        if isinstance(execution_ms, (int, float)) and execution_ms >= 0:
            actual_usd = (
                (float(execution_ms) / 1000.0)
                + self.config.cold_start_reserve_seconds
                + self.config.idle_timeout_seconds
            ) * self.config.max_rate_usd_per_second
            actual_usd = min(actual_usd, float(row["reserved_usd"]))
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE jobs SET state=?, actual_usd=?, updated_at=?,
                    provider_status_json=? WHERE job_id=?
                """,
                (
                    state,
                    actual_usd,
                    self._clock(),
                    json.dumps(response, sort_keys=True),
                    job_id,
                ),
            )
            updated = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(updated)

    def reconcile_active(self, client: RunPodClient) -> dict[str, Any]:
        """Reconcile every submitted/running job for the durable watchdog."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT job_id FROM jobs
                WHERE state IN ('submitted','running')
                ORDER BY created_at
                """
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            try:
                result = self.reconcile(str(row["job_id"]), client)
            except OverflowError as exc:
                results.append({"job_id": row["job_id"], "error": str(exc)})
            else:
                results.append(
                    {
                        "job_id": result["job_id"],
                        "state": result["state"],
                        "provider_job_id": result["provider_job_id"],
                    }
                )
        return {
            "schema_version": "maskfactory.runpod_serverless_overflow_reconcile.v1",
            "active_jobs_checked": len(rows),
            "results": results,
        }

    def cancel(self, job_id: str, client: RunPodClient) -> dict[str, Any]:
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise OverflowError("overflow job not found")
            if row["state"] in TERMINAL_STATES:
                return dict(row)
            if not row["provider_job_id"]:
                raise OverflowError("reserved job has no provider id; cannot cancel remotely")
            response = client.cancel(row["endpoint_id"], row["provider_job_id"])
            connection.execute(
                """
                UPDATE jobs SET state='cancelled', updated_at=?,
                    provider_status_json=? WHERE job_id=?
                """,
                (
                    self._clock(),
                    json.dumps(response, sort_keys=True),
                    job_id,
                ),
            )
            updated = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(updated)

    def report(self, *, billing_day: str | None = None) -> dict[str, Any]:
        day = billing_day or utc_billing_day(self._clock())
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE billing_day=? ORDER BY created_at", (day,)
            ).fetchall()
        reserved = sum(float(row["reserved_usd"]) for row in rows if row["state"] != "cancelled")
        actual = sum(float(row["actual_usd"] or 0.0) for row in rows)
        return {
            "schema_version": "maskfactory.runpod_serverless_overflow_report.v1",
            "billing_day": day,
            "hard_daily_limit_usd": self.config.hard_daily_limit_usd,
            "admission_limit_usd": self.config.admission_limit_usd,
            "rolling_hour_hard_limit_usd": self.config.rolling_hour_hard_limit_usd,
            "rolling_hour_admission_limit_usd": (self.config.rolling_hour_admission_limit_usd),
            "reserved_usd": round(reserved, 6),
            "estimated_actual_usd": round(actual, 6),
            "remaining_admission_usd": round(
                max(0.0, self.config.admission_limit_usd - reserved), 6
            ),
            "active_jobs": sum(row["state"] in ACTIVE_STATES for row in rows),
            "jobs": [dict(row) for row in rows],
        }
