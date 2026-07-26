"""Durable broker-only Serverless routing for continuous steward missions.

This module never calls a provider endpoint.  It invokes only the deployed
shared broker manager and persists enough local state to prevent duplicate
reserve or submit calls after rejection, timeout, or process interruption.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _default_broker_paths(
    *,
    is_windows: bool,
    environment: Mapping[str, str] | None = None,
) -> tuple[Path, Path, Path]:
    """Return the checked-out manager/config and the durable ledger root.

    The former non-Windows defaults referenced a disposable historical
    `/workspace/.maskfactory/serverless_overflow_control` source tree.  That
    made a WSL or Pod caller silently diverge from the committed manager.  The
    executable and configuration must instead come from this checkout (or an
    explicit, hash-bound deployment override); only the broker SQLite ledger
    belongs on the shared execution-host volume.
    """

    values = environment if environment is not None else os.environ
    manager = Path(
        values.get(
            "MASKFACTORY_SERVERLESS_MANAGER_PATH",
            str(PROJECT_ROOT / "tools" / "manage_runpod_serverless_overflow.py"),
        )
    ).expanduser()
    config = Path(
        values.get(
            "MASKFACTORY_SERVERLESS_CONFIG_PATH",
            str(PROJECT_ROOT / "configs" / "runpod_serverless_overflow.yaml"),
        )
    ).expanduser()
    default_root = (
        Path.home() / ".maskfactory" / "serverless_overflow_control"
        if is_windows
        else Path("/workspace/.maskfactory/serverless_overflow")
    )
    broker_root = Path(
        values.get("MASKFACTORY_SERVERLESS_BROKER_ROOT", str(default_root))
    ).expanduser()
    return manager, config, broker_root


MANAGER_PATH, CONFIG_PATH, BROKER_ROOT = _default_broker_paths(is_windows=os.name == "nt")
STATE_SCHEMA = "maskfactory.steward.serverless_route_state.v1"
EVENT_SCHEMA = "maskfactory.steward.serverless_route_event.v1"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
TERMINAL_BROKER_STATES = frozenset({"completed", "failed", "cancelled"})
RECONCILABLE_STATES = frozenset(
    {
        "submitted",
        "running",
        "submitting",
        "submitted_unknown",
        "recovery_required",
    }
)


class ServerlessRouteError(RuntimeError):
    """Raised when governed Serverless routing cannot proceed safely."""


class BrokerCommandRejected(ServerlessRouteError):
    """The shared broker rejected a command unambiguously."""


class BrokerCommandTimeout(ServerlessRouteError):
    """The broker command timed out and its outcome may be ambiguous."""


class BrokerCommandProtocolError(ServerlessRouteError):
    """The broker returned malformed or contradictory output."""


class ServerlessRouteAmbiguous(ServerlessRouteError):
    """A reserve or submit outcome must reconcile before any retry."""


BrokerCommandRunner = Callable[[Sequence[str], float], Mapping[str, Any]]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _seal_state(value: Mapping[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(dict(value))
    sealed["state_sha256"] = "0" * 64
    sealed["state_sha256"] = _canonical_sha256(sealed)
    return sealed


def _validate_state(value: Mapping[str, Any]) -> dict[str, Any]:
    state = copy.deepcopy(dict(value))
    declared = state.get("state_sha256")
    if not isinstance(declared, str) or not SHA256_RE.fullmatch(declared):
        raise ServerlessRouteError("Serverless route state hash is invalid")
    zeroed = copy.deepcopy(state)
    zeroed["state_sha256"] = "0" * 64
    if _canonical_sha256(zeroed) != declared:
        raise ServerlessRouteError("Serverless route state hash mismatch")
    return state


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    body = (
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    body = (
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def _run_broker_command(
    command: Sequence[str],
    timeout_seconds: float,
    *,
    environment: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=None if environment is None else dict(environment),
        )
    except subprocess.TimeoutExpired as exc:
        raise BrokerCommandTimeout("shared broker command timed out") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        if len(detail) > 1000:
            detail = detail[-1000:]
        raise BrokerCommandRejected(
            f"shared broker command rejected: {detail or completed.returncode}"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise BrokerCommandProtocolError("shared broker output is not valid JSON") from exc
    if not isinstance(result, dict):
        raise BrokerCommandProtocolError("shared broker output is not a JSON object")
    return result


def _default_command_runner(
    command: Sequence[str],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    return _run_broker_command(command, timeout_seconds)


def _credential_command_runner(
    credential_path: Path,
) -> BrokerCommandRunner:
    """Inject a protected RunPod key without placing it in argv or artifacts."""

    path = Path(credential_path)
    if not path.is_file():
        raise ServerlessRouteError("protected RunPod credential file is missing")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ServerlessRouteError("protected RunPod credential file must have mode 0600")

    def run(
        command: Sequence[str],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        try:
            api_key = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise ServerlessRouteError("protected RunPod credential file is unreadable") from exc
        if not api_key or "\n" in api_key or "\r" in api_key:
            raise ServerlessRouteError("protected RunPod credential file is invalid")
        environment = dict(os.environ)
        environment["RUNPOD_API_KEY"] = api_key
        try:
            return _run_broker_command(
                command,
                timeout_seconds,
                environment=environment,
            )
        finally:
            environment.pop("RUNPOD_API_KEY", None)

    return run


class BrokerOnlyServerlessRoute:
    """Exactly-once adapter around the shared Serverless broker manager."""

    def __init__(
        self,
        *,
        mission_root: Path,
        mission_id: str,
        session_id: str,
        profile: str,
        payload_path: Path,
        manager_path: Path = MANAGER_PATH,
        config_path: Path = CONFIG_PATH,
        broker_root: Path = BROKER_ROOT,
        python_executable: str = sys.executable,
        command_runner: BrokerCommandRunner | None = None,
        runpod_api_key_file: Path | None = None,
        command_timeout_seconds: float = 45.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not SHA256_RE.fullmatch(mission_id):
            raise ServerlessRouteError(
                "mission_id must be exactly 64 lowercase hexadecimal characters"
            )
        if not session_id:
            raise ServerlessRouteError("session_id is required")
        if profile not in {"maskfactory", "comfyui"}:
            raise ServerlessRouteError("Serverless profile is invalid")
        if command_timeout_seconds <= 0:
            raise ServerlessRouteError("broker command timeout must be positive")
        self.mission_root = Path(mission_root)
        self.mission_root.mkdir(parents=True, exist_ok=True)
        self.payload_path = Path(payload_path)
        try:
            self.payload_path.resolve().relative_to(self.mission_root.resolve())
        except ValueError as exc:
            raise ServerlessRouteError(
                "immutable Serverless payload must be inside mission_root"
            ) from exc
        if not self.payload_path.is_file():
            raise ServerlessRouteError("immutable Serverless payload is missing")
        try:
            payload = json.loads(self.payload_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ServerlessRouteError("immutable Serverless payload is unreadable") from exc
        if not isinstance(payload, dict) or not payload:
            raise ServerlessRouteError("immutable Serverless payload must be a non-empty object")
        self.payload = payload
        self.mission_id = mission_id
        self.session_id = session_id
        self.profile = profile
        self.manager_path = Path(manager_path)
        self.config_path = Path(config_path)
        self.broker_root = Path(broker_root)
        for path, label in (
            (self.manager_path, "manager"),
            (self.config_path, "config"),
        ):
            if not path.is_file():
                raise ServerlessRouteError(f"shared broker {label} is missing")
        self.python_executable = python_executable
        if command_runner is not None and runpod_api_key_file is not None:
            raise ServerlessRouteError(
                "custom broker command runner cannot also use a credential file"
            )
        self.runpod_api_key_file = (
            Path(runpod_api_key_file) if runpod_api_key_file is not None else None
        )
        self.command_runner = command_runner or (
            _credential_command_runner(self.runpod_api_key_file)
            if self.runpod_api_key_file is not None
            else _default_command_runner
        )
        self.command_timeout_seconds = float(command_timeout_seconds)
        self.clock = clock
        self.state_path = self.mission_root / "serverless_route_state.json"
        self.events_path = self.mission_root / "serverless_route_events"
        self.events_path.mkdir(exist_ok=True)
        self._identity = {
            "mission_id": mission_id,
            "session_id": session_id,
            "profile": profile,
            "payload_path": str(self.payload_path.resolve()),
            "payload_file_sha256": _file_sha256(self.payload_path),
            "payload_sha256": _canonical_sha256(payload),
            "manager_path": str(self.manager_path),
            "manager_sha256": _file_sha256(self.manager_path),
            "config_path": str(self.config_path),
            "config_sha256": _file_sha256(self.config_path),
            "broker_root": str(self.broker_root),
            "runpod_api_key_file": (
                str(self.runpod_api_key_file.resolve())
                if self.runpod_api_key_file is not None
                else None
            ),
        }
        if self.state_path.exists():
            self._state = _validate_state(json.loads(self.state_path.read_text(encoding="utf-8")))
            for key, expected in self._identity.items():
                if self._state.get(key) != expected:
                    raise ServerlessRouteError(f"durable Serverless identity mismatch: {key}")
            if self._state["state"] == "reserving":
                self._transition(
                    "reservation_unknown",
                    "restart_after_reserve_intent",
                    error="reserve outcome requires report reconciliation",
                )
            elif self._state["state"] == "submitting":
                self._transition(
                    "submitted_unknown",
                    "restart_after_submit_intent",
                    error="submit outcome requires broker reconciliation",
                )
        else:
            now = self.clock()
            self._state = _seal_state(
                {
                    "schema_version": STATE_SCHEMA,
                    **self._identity,
                    "state": "intent_persisted",
                    "route": None,
                    "broker_job_id": None,
                    "provider_job_id": None,
                    "reserve_billing_day": None,
                    "requested_seconds": None,
                    "event_index": 0,
                    "last_result": None,
                    "last_error": None,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            _atomic_write_json(self.state_path, self._state)
            self._write_event("intent_persisted")

    @property
    def state(self) -> dict[str, Any]:
        """Return a defensive copy of the durable route state."""
        return copy.deepcopy(self._state)

    def _write_event(self, event: str) -> None:
        index = int(self._state["event_index"])
        event_value = {
            "schema_version": EVENT_SCHEMA,
            "mission_id": self.mission_id,
            "event_index": index,
            "event": event,
            "state": self._state["state"],
            "state_sha256": self._state["state_sha256"],
            "created_at": self.clock(),
        }
        event_value["event_sha256"] = _canonical_sha256(event_value)
        _write_exclusive_json(
            self.events_path / f"{index:04d}_{event}.json",
            event_value,
        )

    def _transition(
        self,
        state: str,
        event: str,
        *,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
        **updates: Any,
    ) -> dict[str, Any]:
        updated = copy.deepcopy(self._state)
        updated.update(updates)
        updated["state"] = state
        updated["event_index"] = int(updated["event_index"]) + 1
        updated["last_result"] = copy.deepcopy(dict(result)) if result else None
        updated["last_error"] = error[:1000] if error else None
        updated["updated_at"] = self.clock()
        self._state = _seal_state(updated)
        _atomic_write_json(self.state_path, self._state)
        self._write_event(event)
        return self.state

    def _command(self, command: str, *arguments: str) -> Mapping[str, Any]:
        argv = [
            self.python_executable,
            str(self.manager_path),
            "--config",
            str(self.config_path),
            "--root",
            str(self.broker_root),
            command,
            *arguments,
        ]
        return self.command_runner(argv, self.command_timeout_seconds)

    def decide(self) -> dict[str, Any]:
        """Ask only the shared broker whether Serverless overflow is eligible."""
        if self._state["state"] == "decided":
            return copy.deepcopy(self._state["last_result"])
        if self._state["state"] != "intent_persisted":
            raise ServerlessRouteError(f"decide is not allowed from state {self._state['state']}")
        try:
            result = self._command(
                "decide",
                "--session-id",
                self.session_id,
            )
        except BrokerCommandRejected as exc:
            self._transition("rejected", "decide_rejected", error=str(exc))
            raise
        if result.get("session_id") != self.session_id or result.get("profile") != self.profile:
            self._transition(
                "rejected",
                "decide_contradiction",
                error="broker decision identity mismatch",
            )
            raise BrokerCommandProtocolError("shared broker decision identity mismatch")
        if result.get("route") != "serverless_overflow":
            self._transition(
                "rejected",
                "local_route_selected",
                result=result,
                error="Serverless fallback is not selected",
            )
            raise BrokerCommandRejected("shared broker did not select Serverless overflow")
        self._transition(
            "decided",
            "serverless_decided",
            result=result,
            route="serverless_overflow",
        )
        return copy.deepcopy(dict(result))

    def reserve(
        self,
        *,
        requested_seconds: int,
        observed_provider_spend_usd: float | None = None,
        observed_provider_hour_spend_usd: float | None = None,
    ) -> dict[str, Any]:
        """Reserve shared budget/concurrency exactly once for this payload."""
        if self._state["state"] == "reserved":
            if self._state["requested_seconds"] != requested_seconds:
                raise ServerlessRouteError("requested seconds changed after reservation")
            return copy.deepcopy(self._state["last_result"])
        if self._state["state"] != "decided":
            raise ServerlessRouteError(f"reserve is not allowed from state {self._state['state']}")
        if (
            isinstance(requested_seconds, bool)
            or not isinstance(requested_seconds, int)
            or requested_seconds <= 0
        ):
            raise ServerlessRouteError("requested_seconds must be positive")
        billing_day = datetime.fromtimestamp(self.clock(), tz=UTC).date().isoformat()
        self._transition(
            "reserving",
            "reserve_intent",
            requested_seconds=requested_seconds,
            reserve_billing_day=billing_day,
        )
        arguments = [
            "--session-id",
            self.session_id,
            "--profile",
            self.profile,
            "--payload",
            str(self.payload_path),
            "--requested-seconds",
            str(requested_seconds),
        ]
        if observed_provider_spend_usd is not None:
            arguments.extend(
                [
                    "--observed-provider-spend-usd",
                    str(float(observed_provider_spend_usd)),
                ]
            )
        if observed_provider_hour_spend_usd is not None:
            arguments.extend(
                [
                    "--observed-provider-hour-spend-usd",
                    str(float(observed_provider_hour_spend_usd)),
                ]
            )
        try:
            result = self._command("reserve", *arguments)
        except BrokerCommandRejected as exc:
            self._transition("rejected", "reserve_rejected", error=str(exc))
            raise
        except (BrokerCommandTimeout, BrokerCommandProtocolError) as exc:
            self._transition(
                "reservation_unknown",
                "reserve_outcome_unknown",
                error=str(exc),
            )
            raise ServerlessRouteAmbiguous("reserve outcome must reconcile before retry") from exc
        if (
            result.get("state") != "reserved"
            or result.get("session_id") != self.session_id
            or result.get("profile") != self.profile
            or result.get("payload_sha256") != self._identity["payload_sha256"]
            or not isinstance(result.get("job_id"), str)
            or not result["job_id"]
        ):
            self._transition(
                "reservation_unknown",
                "reserve_output_contradiction",
                result=result,
                error="reserve output does not match immutable intent",
            )
            raise ServerlessRouteAmbiguous(
                "reserve output is contradictory and requires reconciliation"
            )
        self._transition(
            "reserved",
            "reserved",
            result=result,
            broker_job_id=result["job_id"],
        )
        return copy.deepcopy(dict(result))

    def reconcile_reservation(self) -> dict[str, Any]:
        """Resolve an ambiguous reserve intent by canonical payload lookup."""
        if self._state["state"] not in {"reserving", "reservation_unknown"}:
            raise ServerlessRouteError(
                "reservation reconciliation requires an unknown reserve outcome"
            )
        billing_day = self._state.get("reserve_billing_day")
        arguments = ["--billing-day", str(billing_day)] if billing_day else []
        try:
            report = self._command("report", *arguments)
        except (
            BrokerCommandRejected,
            BrokerCommandTimeout,
            BrokerCommandProtocolError,
        ) as exc:
            self._transition(
                "reservation_unknown",
                "reservation_report_failed",
                error=str(exc),
            )
            raise ServerlessRouteAmbiguous("reservation report remains unavailable") from exc
        jobs = report.get("jobs")
        if not isinstance(jobs, list):
            raise BrokerCommandProtocolError("shared broker report is missing jobs")
        matches = [
            job
            for job in jobs
            if isinstance(job, dict)
            and job.get("session_id") == self.session_id
            and job.get("profile") == self.profile
            and job.get("payload_sha256") == self._identity["payload_sha256"]
            and job.get("state") != "cancelled"
        ]
        if len(matches) > 1:
            self._transition(
                "recovery_required",
                "duplicate_reservation_detected",
                result=report,
                error="multiple broker jobs match one canonical payload",
            )
            raise ServerlessRouteAmbiguous("multiple broker jobs match one canonical payload")
        if not matches:
            resolution = {
                "resolution": "reservation_absent",
                "payload_sha256": self._identity["payload_sha256"],
            }
            self._transition(
                "decided",
                "reservation_absent",
                result=resolution,
                broker_job_id=None,
            )
            return resolution
        job = matches[0]
        job_id = job.get("job_id")
        state = job.get("state")
        if not isinstance(job_id, str) or not job_id:
            raise BrokerCommandProtocolError("matched broker reservation has no job_id")
        adopted = "terminal" if state in TERMINAL_BROKER_STATES else str(state)
        self._transition(
            adopted,
            "reservation_adopted",
            result=job,
            broker_job_id=job_id,
            provider_job_id=job.get("provider_job_id"),
        )
        return copy.deepcopy(job)

    def submit(self) -> dict[str, Any]:
        """Submit one reserved payload through the manager, never directly."""
        if self._state["state"] != "reserved":
            raise ServerlessRouteError(f"submit is not allowed from state {self._state['state']}")
        job_id = self._state.get("broker_job_id")
        if not isinstance(job_id, str) or not job_id:
            raise ServerlessRouteError("reserved state has no broker_job_id")
        self._transition("submitting", "submit_intent")
        try:
            result = self._command(
                "submit",
                "--job-id",
                job_id,
                "--payload",
                str(self.payload_path),
            )
        except (
            BrokerCommandRejected,
            BrokerCommandTimeout,
            BrokerCommandProtocolError,
        ) as exc:
            self._transition(
                "submitted_unknown",
                "submit_outcome_unknown",
                error=str(exc),
            )
            raise ServerlessRouteAmbiguous(
                "submit outcome must reconcile before any retry"
            ) from exc
        if (
            result.get("state") != "submitted"
            or result.get("job_id") != job_id
            or not isinstance(result.get("provider_job_id"), str)
            or not result["provider_job_id"]
        ):
            self._transition(
                "submitted_unknown",
                "submit_output_contradiction",
                result=result,
                error="submit output does not match reservation",
            )
            raise ServerlessRouteAmbiguous(
                "submit output is contradictory and requires reconciliation"
            )
        self._transition(
            "submitted",
            "submitted",
            result=result,
            provider_job_id=result["provider_job_id"],
        )
        return copy.deepcopy(dict(result))

    def reconcile(self) -> dict[str, Any]:
        """Reconcile submitted/unknown work; this never reissues submit."""
        if self._state["state"] not in RECONCILABLE_STATES:
            if self._state["state"] == "terminal":
                return copy.deepcopy(self._state["last_result"])
            raise ServerlessRouteError(
                f"reconcile is not allowed from state {self._state['state']}"
            )
        job_id = self._state.get("broker_job_id")
        if not isinstance(job_id, str) or not job_id:
            self._transition(
                "recovery_required",
                "reconcile_missing_broker_job_id",
                error="unknown submission has no broker job identity",
            )
            raise ServerlessRouteAmbiguous("unknown submission has no broker job identity")
        try:
            result = self._command(
                "reconcile",
                "--job-id",
                job_id,
            )
        except (
            BrokerCommandRejected,
            BrokerCommandTimeout,
            BrokerCommandProtocolError,
        ) as exc:
            self._transition(
                "recovery_required",
                "reconcile_failed",
                error=str(exc),
            )
            raise ServerlessRouteAmbiguous("submission remains unreconciled") from exc
        broker_state = result.get("state")
        if broker_state in TERMINAL_BROKER_STATES:
            self._transition(
                "terminal",
                f"reconciled_{broker_state}",
                result=result,
                provider_job_id=result.get("provider_job_id"),
            )
        elif broker_state in {"submitted", "running"}:
            self._transition(
                broker_state,
                f"reconciled_{broker_state}",
                result=result,
                provider_job_id=result.get("provider_job_id"),
            )
        else:
            self._transition(
                "recovery_required",
                "reconcile_output_contradiction",
                result=result,
                error="unknown broker state",
            )
            raise BrokerCommandProtocolError("shared broker returned an unknown job state")
        return copy.deepcopy(dict(result))
