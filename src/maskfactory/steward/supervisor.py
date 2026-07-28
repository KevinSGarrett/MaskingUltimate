"""CPU-safe continuous supervisor contracts for self-hosted autonomy."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

OWNER_SCHEMA = "maskfactory_self_hosted_supervisor_owner.v1"
HEALTH_SCHEMA = "maskfactory_self_hosted_supervisor_health.v1"
QUEUE_SCHEMA = "maskfactory_self_hosted_supervisor_queue.v1"
CAMPAIGN_SCHEMA = "maskfactory_self_hosted_supervisor_campaign.v1"
EXCEPTION_SCHEMA = "maskfactory_self_hosted_supervisor_exception.v1"
SHUTDOWN_SCHEMA = "maskfactory_self_hosted_supervisor_shutdown.v1"
STALE_OWNER_SCHEMA = "maskfactory_self_hosted_supervisor_stale_owner.v1"

OWNER_STATES = frozenset({"running", "stopped"})
CAMPAIGN_STATES = frozenset({"idle", "planned", "active", "blocked", "terminal"})
EXCEPTION_KINDS = frozenset({"health", "queue", "campaign", "authority", "recovery", "shutdown"})


class SupervisorStateError(RuntimeError):
    """Durable supervisor state is malformed or conflicts with the caller."""


class SupervisorAlreadyRunning(SupervisorStateError):
    """A matching live supervisor already owns the state root."""


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SupervisorStateError(f"unreadable supervisor state: {path}") from exc
    if not isinstance(value, dict):
        raise SupervisorStateError(f"supervisor state is not an object: {path}")
    return value


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
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


def _create_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        existing = _read_json(path)
        if existing != dict(value):
            raise SupervisorStateError(f"immutable supervisor receipt conflicts: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def default_process_identity(pid: int) -> str | None:
    """Return a PID-reuse-safe Linux identity, with a bounded local fallback."""

    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        stat = stat_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeError):
        if pid == os.getpid():
            return f"local-process:{pid}:{sys.executable}"
        return None
    closing_parenthesis = stat.rfind(")")
    fields = stat[closing_parenthesis + 1 :].split() if closing_parenthesis >= 0 else []
    if len(fields) <= 19:
        return None
    return fields[19]


@contextmanager
def _exclusive_file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream: BinaryIO = path.open("a+b")
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


class CpuSafeSupervisor:
    """Durable single-owner supervisor that never requires a GPU."""

    def __init__(
        self,
        state_root: Path,
        *,
        supervisor_id: str,
        process_identity_probe: Callable[[int], str | None] = default_process_identity,
        clock: Callable[[], float] = time.time,
    ):
        if not supervisor_id or any(character in supervisor_id for character in "/\\\0"):
            raise SupervisorStateError("supervisor_id must be a plain non-empty identity")
        self.state_root = Path(state_root)
        self.supervisor_id = supervisor_id
        self.process_identity_probe = process_identity_probe
        self.clock = clock
        self.owner_path = self.state_root / "owner.json"
        self.health_path = self.state_root / "health.json"
        self.queue_path = self.state_root / "queue.json"
        self.campaign_path = self.state_root / "campaign.json"
        self.exceptions_path = self.state_root / "exceptions.jsonl"
        self.token_path = self.state_root / "owner.token"
        self.lock_path = self.state_root / ".state.lock"
        self._token: str | None = None
        self._generation: int | None = None

    @staticmethod
    def _safe_owner(owner: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in owner.items() if key != "owner_token_sha256"}

    def _verify_current_owner(self) -> dict[str, Any]:
        if self._token is None or self._generation is None:
            raise SupervisorStateError("supervisor is not started by this controller")
        owner = _read_json(self.owner_path)
        if (
            owner.get("schema_version") != OWNER_SCHEMA
            or owner.get("state") != "running"
            or owner.get("supervisor_id") != self.supervisor_id
            or owner.get("generation") != self._generation
            or owner.get("pid") != os.getpid()
            or owner.get("owner_token_sha256")
            != hashlib.sha256(self._token.encode("ascii")).hexdigest()
        ):
            raise SupervisorStateError("supervisor ownership changed")
        if self.process_identity_probe(os.getpid()) != owner.get("process_start_token"):
            raise SupervisorStateError("supervisor PID start token changed")
        return owner

    def _remove_bound_token(self, expected_sha256: str) -> None:
        if not self.token_path.exists():
            return
        observed = hashlib.sha256(self.token_path.read_bytes()).hexdigest()
        if observed != expected_sha256:
            raise SupervisorStateError("protected owner token binding drifted")
        self.token_path.unlink()

    def start(self) -> dict[str, Any]:
        """Acquire CPU supervisor ownership or recover a stale prior owner."""

        self.state_root.mkdir(parents=True, exist_ok=True)
        with _exclusive_file_lock(self.lock_path):
            previous = _read_json(self.owner_path) if self.owner_path.exists() else None
            generation = 1
            if previous is not None:
                if previous.get("schema_version") != OWNER_SCHEMA:
                    raise SupervisorStateError("owner schema mismatch")
                if previous.get("state") not in OWNER_STATES:
                    raise SupervisorStateError("owner state is invalid")
                generation = int(previous.get("generation") or 0) + 1
                if previous["state"] == "running":
                    observed_identity = self.process_identity_probe(int(previous["pid"]))
                    if observed_identity == previous.get("process_start_token"):
                        raise SupervisorAlreadyRunning(
                            "matching live supervisor already owns the state root"
                        )
                    stale_receipt = {
                        "schema_version": STALE_OWNER_SCHEMA,
                        "supervisor_id": previous["supervisor_id"],
                        "generation": previous["generation"],
                        "pid": previous["pid"],
                        "expected_process_start_token": previous["process_start_token"],
                        "observed_process_start_token": observed_identity,
                        "owner_token_sha256": previous["owner_token_sha256"],
                        "recovered_at": self.clock(),
                    }
                    _create_json(
                        self.state_root / f"stale_owner_{int(previous['generation']):06d}.json",
                        stale_receipt,
                    )
                    self._remove_bound_token(previous["owner_token_sha256"])
            if self.token_path.exists():
                raise SupervisorStateError("unbound protected owner token exists")
            token = secrets.token_hex(32)
            descriptor = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(token.encode("ascii"))
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt":
                os.chmod(self.token_path, 0o600)
            process_start_token = self.process_identity_probe(os.getpid())
            if not process_start_token:
                self.token_path.unlink()
                raise SupervisorStateError("current process identity is unavailable")
            now = self.clock()
            owner = {
                "schema_version": OWNER_SCHEMA,
                "supervisor_id": self.supervisor_id,
                "generation": generation,
                "state": "running",
                "pid": os.getpid(),
                "process_start_token": process_start_token,
                "owner_token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
                "started_at": now,
                "updated_at": now,
            }
            _replace_json(self.owner_path, owner)
            self._token = token
            self._generation = generation
            self._write_health("healthy", now)
            if not self.queue_path.exists():
                self.update_queue(())
            if not self.campaign_path.exists():
                self.update_campaign(None, state="idle")
            return self._safe_owner(owner)

    def _write_health(self, status: str, now: float) -> None:
        _replace_json(
            self.health_path,
            {
                "schema_version": HEALTH_SCHEMA,
                "supervisor_id": self.supervisor_id,
                "generation": self._generation,
                "status": status,
                "heartbeat_at": now,
                "cpu_safe": True,
                "gpu_held": False,
            },
        )

    def heartbeat(self) -> dict[str, Any]:
        with _exclusive_file_lock(self.lock_path):
            owner = self._verify_current_owner()
            now = self.clock()
            owner["updated_at"] = now
            _replace_json(self.owner_path, owner)
            self._write_health("healthy", now)
            return _read_json(self.health_path)

    def update_queue(self, item_ids: Iterable[str]) -> dict[str, Any]:
        if self._token is not None:
            self._verify_current_owner()
        normalized = tuple(item_ids)
        if len(normalized) != len(set(normalized)) or any(
            not isinstance(item_id, str) or not item_id for item_id in normalized
        ):
            raise SupervisorStateError("queue item IDs must be unique non-empty strings")
        document = {
            "schema_version": QUEUE_SCHEMA,
            "supervisor_id": self.supervisor_id,
            "generation": self._generation,
            "item_ids": list(normalized),
            "count": len(normalized),
            "updated_at": self.clock(),
        }
        _replace_json(self.queue_path, document)
        return document

    def update_campaign(self, campaign_id: str | None, *, state: str) -> dict[str, Any]:
        if self._token is not None:
            self._verify_current_owner()
        if state not in CAMPAIGN_STATES:
            raise SupervisorStateError("campaign state is invalid")
        if state == "idle":
            campaign_id = None
        elif not campaign_id or any(character in campaign_id for character in "/\\\0"):
            raise SupervisorStateError("active campaign requires a plain identity")
        document = {
            "schema_version": CAMPAIGN_SCHEMA,
            "supervisor_id": self.supervisor_id,
            "generation": self._generation,
            "campaign_id": campaign_id,
            "state": state,
            "updated_at": self.clock(),
        }
        _replace_json(self.campaign_path, document)
        return document

    def record_exception(self, kind: str, message: str) -> dict[str, Any]:
        self._verify_current_owner()
        if kind not in EXCEPTION_KINDS or not message:
            raise SupervisorStateError("exception contract is invalid")
        previous_sha256 = "0" * 64
        if self.exceptions_path.exists():
            lines = self.exceptions_path.read_text(encoding="utf-8").splitlines()
            if lines:
                previous = json.loads(lines[-1])
                previous_sha256 = previous["event_sha256"]
        event = {
            "schema_version": EXCEPTION_SCHEMA,
            "supervisor_id": self.supervisor_id,
            "generation": self._generation,
            "kind": kind,
            "message": message,
            "previous_sha256": previous_sha256,
            "created_at": self.clock(),
            "event_sha256": "0" * 64,
        }
        event["event_sha256"] = _canonical_sha256(event)
        with self.exceptions_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return event

    def snapshot(self) -> dict[str, Any]:
        owner = _read_json(self.owner_path)
        return {
            "owner": self._safe_owner(owner),
            "health": _read_json(self.health_path),
            "queue": _read_json(self.queue_path),
            "campaign": _read_json(self.campaign_path),
        }

    def shutdown(self, *, reason: str = "requested") -> dict[str, Any]:
        if not reason:
            raise SupervisorStateError("shutdown reason is required")
        with _exclusive_file_lock(self.lock_path):
            owner = self._verify_current_owner()
            now = self.clock()
            receipt = {
                "schema_version": SHUTDOWN_SCHEMA,
                "supervisor_id": self.supervisor_id,
                "generation": self._generation,
                "pid": owner["pid"],
                "process_start_token": owner["process_start_token"],
                "owner_token_sha256": owner["owner_token_sha256"],
                "reason": reason,
                "stopped_at": now,
            }
            _create_json(
                self.state_root / f"shutdown_{self._generation:06d}.json",
                receipt,
            )
            self._remove_bound_token(owner["owner_token_sha256"])
            owner["state"] = "stopped"
            owner["updated_at"] = now
            _replace_json(self.owner_path, owner)
            self._write_health("stopped", now)
            self._token = None
            return receipt


__all__ = [
    "CAMPAIGN_SCHEMA",
    "CpuSafeSupervisor",
    "HEALTH_SCHEMA",
    "OWNER_SCHEMA",
    "QUEUE_SCHEMA",
    "SHUTDOWN_SCHEMA",
    "STALE_OWNER_SCHEMA",
    "SupervisorAlreadyRunning",
    "SupervisorStateError",
    "default_process_identity",
]
