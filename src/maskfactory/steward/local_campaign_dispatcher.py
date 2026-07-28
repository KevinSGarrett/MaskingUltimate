"""Restart-safe dispatch of prepared local 25-mission engineering campaigns.

The dispatcher is deliberately CPU-safe.  It discovers only fully bound
campaign roots, persists an immutable launch intent before process creation,
starts the shared-Pod guard (never the model directly), and never reissues a
campaign after an ambiguous owner interruption.  The guarded child owns GPU
admission, lease heartbeat, model lifetime, and durable release.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import IO, Any

from .core import canonical_sha256
from .engineering_campaign_runtime import (
    BINDING_NAME,
    TERMINAL_NAME,
    validate_engineering_campaign_runtime_binding,
    validate_engineering_campaign_runtime_terminal,
)
from .runtime import file_sha256, read_json
from .supervisor import default_process_identity

INTENT_SCHEMA = "maskfactory.local_engineering_campaign_launch_intent.v1"
STATUS_SCHEMA = "maskfactory.local_engineering_campaign_dispatch_status.v1"
TERMINAL_SCHEMA = "maskfactory.local_engineering_campaign_dispatch_terminal.v1"
INTENT_NAME = "local_campaign_launch_intent.json"
STATUS_NAME = "local_campaign_dispatch_status.json"
DISPATCH_TERMINAL_NAME = "local_campaign_dispatch_terminal.json"
STDOUT_NAME = "local_campaign_guard.stdout.log"
STDERR_NAME = "local_campaign_guard.stderr.log"
ZERO_SHA256 = "0" * 64


class LocalCampaignDispatchError(RuntimeError):
    """A prepared campaign cannot be safely dispatched or reconciled."""


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(_json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def _replace(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    sealed = dict(value)
    sealed[field] = ZERO_SHA256
    sealed[field] = canonical_sha256(sealed)
    return sealed


def _validate_identity(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 200
        or any(character in value for character in "/\\\0\r\n")
    ):
        raise LocalCampaignDispatchError(f"{field} is invalid")
    return value


def _validate_self_hash(value: Mapping[str, Any], field: str) -> None:
    declared = value.get(field)
    if (
        not isinstance(declared, str)
        or len(declared) != 64
        or any(character not in "0123456789abcdef" for character in declared)
    ):
        raise LocalCampaignDispatchError(f"{field} is invalid")
    zeroed = dict(value)
    zeroed[field] = ZERO_SHA256
    if canonical_sha256(zeroed) != declared:
        raise LocalCampaignDispatchError(f"{field} canonical self-hash mismatch")


class LocalEngineeringCampaignDispatcher:
    """Discover, launch once, and reconcile prepared local campaigns."""

    def __init__(
        self,
        *,
        inbox_root: Path,
        state_root: Path,
        runtime_contract_path: Path,
        steward_database: Path,
        lease_database: Path,
        lease_manager_path: Path,
        guard_tool_path: Path,
        runtime_tool_path: Path,
        python_executable: Path | str = sys.executable,
        max_runtime_seconds: int = 3600,
        heartbeat_seconds: float = 25.0,
        popen_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
        process_identity_probe: Callable[[int], str | None] = (
            default_process_identity
        ),
        process_discovery: Callable[[str, str], Sequence[tuple[int, str]]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_runtime_seconds <= 0 or heartbeat_seconds <= 0:
            raise LocalCampaignDispatchError("runtime bounds must be positive")
        self.inbox_root = Path(inbox_root).resolve()
        self.state_root = Path(state_root).resolve()
        self.runtime_contract_path = Path(runtime_contract_path).resolve()
        self.steward_database = Path(steward_database).resolve()
        self.lease_database = Path(lease_database).resolve()
        self.lease_manager_path = Path(lease_manager_path).resolve()
        self.guard_tool_path = Path(guard_tool_path).resolve()
        self.runtime_tool_path = Path(runtime_tool_path).resolve()
        self.python_executable = str(Path(python_executable))
        self.max_runtime_seconds = int(max_runtime_seconds)
        self.heartbeat_seconds = float(heartbeat_seconds)
        self.popen_factory = popen_factory
        self.process_identity_probe = process_identity_probe
        self.process_discovery = process_discovery or self._discover_linux_process
        self.clock = clock
        self.inbox_root.mkdir(parents=True, exist_ok=True)
        self.state_root.mkdir(parents=True, exist_ok=True)
        for path, label in (
            (self.runtime_contract_path, "runtime contract"),
            (self.lease_manager_path, "lease manager"),
            (self.guard_tool_path, "guard tool"),
            (self.runtime_tool_path, "campaign runtime tool"),
        ):
            if not path.is_file():
                raise LocalCampaignDispatchError(f"{label} is missing")

    @staticmethod
    def _discover_linux_process(
        campaign_id: str,
        guard_tool: str,
    ) -> Sequence[tuple[int, str]]:
        """Find an exact guarded campaign after a crash-before-PID-persist window."""

        proc_root = Path("/proc")
        if not proc_root.is_dir():
            return ()
        matches: list[tuple[int, str]] = []
        for candidate in proc_root.iterdir():
            if not candidate.name.isdecimal():
                continue
            try:
                body = (candidate / "cmdline").read_bytes()
            except OSError:
                continue
            fields = [
                item.decode("utf-8", errors="surrogateescape")
                for item in body.split(b"\0")
                if item
            ]
            if (
                guard_tool in fields
                and "--job-id" in fields
            ):
                job_index = fields.index("--job-id")
                if (
                    job_index + 1 >= len(fields)
                    or fields[job_index + 1] != campaign_id
                ):
                    continue
                token = default_process_identity(int(candidate.name))
                if token:
                    matches.append((int(candidate.name), token))
        return tuple(matches)

    def _campaign_state_root(self, campaign_id: str) -> Path:
        return self.state_root / _validate_identity(campaign_id, "campaign_id")

    def _binding(self, campaign_root: Path) -> dict[str, Any]:
        return validate_engineering_campaign_runtime_binding(
            campaign_root / BINDING_NAME,
            campaign_root=campaign_root,
            contract_path=self.runtime_contract_path,
        )

    def discover(self) -> tuple[tuple[Path, dict[str, Any]], ...]:
        discovered: list[tuple[Path, dict[str, Any]]] = []
        for campaign_root in sorted(self.inbox_root.iterdir()):
            if (
                not campaign_root.is_dir()
                or not (campaign_root / BINDING_NAME).is_file()
            ):
                continue
            binding = self._binding(campaign_root)
            if campaign_root.name != binding["campaign_id"]:
                raise LocalCampaignDispatchError(
                    "campaign directory and canonical identity differ"
                )
            discovered.append((campaign_root, binding))
        return tuple(discovered)

    def pending_ids(self) -> tuple[str, ...]:
        pending: list[str] = []
        for campaign_root, binding in self.discover():
            terminal = self._campaign_state_root(
                binding["campaign_id"]
            ) / DISPATCH_TERMINAL_NAME
            if not terminal.is_file() and not (
                campaign_root / TERMINAL_NAME
            ).is_file():
                pending.append(binding["campaign_id"])
        return tuple(pending)

    def _command(
        self,
        *,
        campaign_root: Path,
        binding: Mapping[str, Any],
    ) -> list[str]:
        return [
            self.python_executable,
            str(self.guard_tool_path),
            "--job-id",
            str(binding["campaign_id"]),
            "--payload-sha256",
            str(binding["binding_sha256"]),
            "--work-kind",
            "self_hosted_llm_engineering_campaign",
            "--max-runtime-seconds",
            str(self.max_runtime_seconds),
            "--heartbeat-seconds",
            str(self.heartbeat_seconds),
            "--database",
            str(self.lease_database),
            "--manager",
            str(self.lease_manager_path),
            "--mission-root",
            str(campaign_root),
            "--runtime-contract",
            str(self.runtime_contract_path),
            "--",
            self.python_executable,
            str(self.runtime_tool_path),
            "--contract",
            str(self.runtime_contract_path),
            "--campaign-root",
            str(campaign_root),
            "run",
            "--database",
            str(self.steward_database),
        ]

    def _status(
        self,
        campaign_id: str,
        *,
        state: str,
        detail: str,
        pid: int | None,
    ) -> dict[str, Any]:
        document = {
            "schema_version": STATUS_SCHEMA,
            "campaign_id": campaign_id,
            "state": state,
            "detail": detail[:1000],
            "pid": pid,
            "updated_at": self.clock(),
        }
        _replace(self._campaign_state_root(campaign_id) / STATUS_NAME, document)
        return document

    def _terminalize(
        self,
        *,
        campaign_root: Path,
        binding: Mapping[str, Any],
        outcome: str,
        reason_code: str,
        detail: str,
        intent: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        path = self._campaign_state_root(
            str(binding["campaign_id"])
        ) / DISPATCH_TERMINAL_NAME
        value = {
            "schema_version": TERMINAL_SCHEMA,
            "campaign_id": binding["campaign_id"],
            "binding_sha256": binding["binding_sha256"],
            "campaign_terminal_sha256": (
                file_sha256(campaign_root / TERMINAL_NAME)
                if (campaign_root / TERMINAL_NAME).is_file()
                else None
            ),
            "launch_intent_sha256": (
                intent.get("intent_sha256") if intent is not None else None
            ),
            "outcome": outcome,
            "reason_code": reason_code,
            "detail": detail[:1000],
            "retry_permitted": False,
            "authority_claimed": False,
            "completion_claimed": False,
            "created_at": self.clock(),
            "terminal_sha256": ZERO_SHA256,
        }
        sealed = _seal(value, "terminal_sha256")
        if path.exists():
            existing = read_json(path)
            _validate_self_hash(existing, "terminal_sha256")
            if existing != sealed:
                raise LocalCampaignDispatchError(
                    "existing local dispatch terminal conflicts"
                )
            return existing
        _write_exclusive(path, sealed)
        return sealed

    def _intent_process(
        self,
        intent: Mapping[str, Any],
    ) -> tuple[int, str] | None:
        pid = intent.get("pid")
        token = intent.get("process_start_token")
        if isinstance(pid, int) and isinstance(token, str):
            if self.process_identity_probe(pid) == token:
                return pid, token
            return None
        matches = tuple(
            self.process_discovery(
                str(intent["campaign_id"]),
                str(self.guard_tool_path),
            )
        )
        if len(matches) > 1:
            raise LocalCampaignDispatchError(
                "multiple guarded processes match one campaign identity"
            )
        return matches[0] if matches else None

    def _reconcile(
        self,
        *,
        campaign_root: Path,
        binding: Mapping[str, Any],
        intent: Mapping[str, Any],
    ) -> dict[str, Any]:
        _validate_self_hash(intent, "intent_sha256")
        if (
            intent.get("schema_version") != INTENT_SCHEMA
            or intent.get("campaign_id") != binding["campaign_id"]
            or intent.get("binding_sha256") != binding["binding_sha256"]
            or intent.get("command_sha256")
            != canonical_sha256(
                self._command(campaign_root=campaign_root, binding=binding)
            )
        ):
            raise LocalCampaignDispatchError("local launch intent binding drift")
        if (campaign_root / TERMINAL_NAME).is_file():
            validate_engineering_campaign_runtime_terminal(
                campaign_root / TERMINAL_NAME,
                campaign_root=campaign_root,
                contract_path=self.runtime_contract_path,
                database=self.steward_database,
            )
            return self._terminalize(
                campaign_root=campaign_root,
                binding=binding,
                outcome="terminal",
                reason_code="campaign_terminal_present",
                detail="campaign runtime terminal exists; no dispatch replay occurred",
                intent=intent,
            )
        process = self._intent_process(intent)
        if process is not None:
            pid, token = process
            if intent.get("pid") is None:
                updated = dict(intent)
                updated["pid"] = pid
                updated["process_start_token"] = token
                updated["state"] = "started"
                updated["intent_sha256"] = ZERO_SHA256
                updated = _seal(updated, "intent_sha256")
                _replace(
                    self._campaign_state_root(
                        str(binding["campaign_id"])
                    )
                    / INTENT_NAME,
                    updated,
                )
            return self._status(
                str(binding["campaign_id"]),
                state="active",
                detail="matching guarded campaign process remains alive",
                pid=pid,
            )
        return self._terminalize(
            campaign_root=campaign_root,
            binding=binding,
            outcome="failed_closed",
            reason_code="ambiguous_guarded_child_exit",
            detail=(
                "durable launch intent exists without campaign terminal or "
                "matching live process; immutable campaign was not reissued"
            ),
            intent=intent,
        )

    def _launch(
        self,
        *,
        campaign_root: Path,
        binding: Mapping[str, Any],
    ) -> dict[str, Any]:
        command = self._command(campaign_root=campaign_root, binding=binding)
        state_root = self._campaign_state_root(str(binding["campaign_id"]))
        intent_path = state_root / INTENT_NAME
        intent = _seal(
            {
                "schema_version": INTENT_SCHEMA,
                "campaign_id": binding["campaign_id"],
                "binding_sha256": binding["binding_sha256"],
                "campaign_binding_file_sha256": file_sha256(
                    campaign_root / BINDING_NAME
                ),
                "runtime_contract_file_sha256": file_sha256(
                    self.runtime_contract_path
                ),
                "guard_tool_sha256": file_sha256(self.guard_tool_path),
                "runtime_tool_sha256": file_sha256(self.runtime_tool_path),
                "lease_manager_sha256": file_sha256(self.lease_manager_path),
                "command_sha256": canonical_sha256(command),
                "state": "prepared",
                "pid": None,
                "process_start_token": None,
                "created_at": self.clock(),
                "intent_sha256": ZERO_SHA256,
            },
            "intent_sha256",
        )
        _write_exclusive(intent_path, intent)
        stdout_path = state_root / STDOUT_NAME
        stderr_path = state_root / STDERR_NAME
        state_root.mkdir(parents=True, exist_ok=True)
        stdout: IO[bytes] = stdout_path.open("ab", buffering=0)
        stderr: IO[bytes] = stderr_path.open("ab", buffering=0)
        try:
            child = self.popen_factory(
                command,
                cwd=str(campaign_root),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
        finally:
            stdout.close()
            stderr.close()
        token = self.process_identity_probe(int(child.pid))
        if not token:
            return self._status(
                str(binding["campaign_id"]),
                state="active",
                detail=(
                    "guarded child was created but PID start identity is not "
                    "yet available; durable intent prevents reissue"
                ),
                pid=int(child.pid),
            )
        started = dict(intent)
        started["state"] = "started"
        started["pid"] = int(child.pid)
        started["process_start_token"] = token
        started["intent_sha256"] = ZERO_SHA256
        started = _seal(started, "intent_sha256")
        _replace(intent_path, started)
        return self._status(
            str(binding["campaign_id"]),
            state="active",
            detail="guarded campaign child started exactly once",
            pid=int(child.pid),
        )

    def poll_once(
        self,
        *,
        excluded_campaign_ids: Sequence[str] = (),
    ) -> tuple[dict[str, Any], ...]:
        excluded = frozenset(excluded_campaign_ids)
        results: list[dict[str, Any]] = []
        active_seen = False
        discovered = self.discover()
        pending_new: list[tuple[Path, dict[str, Any]]] = []
        for campaign_root, binding in discovered:
            campaign_id = str(binding["campaign_id"])
            state_root = self._campaign_state_root(campaign_id)
            terminal_path = state_root / DISPATCH_TERMINAL_NAME
            if terminal_path.is_file():
                continue
            intent_path = state_root / INTENT_NAME
            if intent_path.is_file():
                result = self._reconcile(
                    campaign_root=campaign_root,
                    binding=binding,
                    intent=read_json(intent_path),
                )
                results.append(result)
                if result.get("state") == "active":
                    active_seen = True
                continue
            pending_new.append((campaign_root, binding))
        for campaign_root, binding in pending_new:
            campaign_id = str(binding["campaign_id"])
            if campaign_id in excluded:
                results.append(
                    self._status(
                        campaign_id,
                        state="blocked",
                        detail=(
                            "same identity exists in another route; no local "
                            "launch occurred"
                        ),
                        pid=None,
                    )
                )
                continue
            if active_seen:
                results.append(
                    self._status(
                        campaign_id,
                        state="queued",
                        detail="another local campaign is active",
                        pid=None,
                    )
                )
                continue
            result = self._launch(
                campaign_root=campaign_root,
                binding=binding,
            )
            results.append(result)
            if result.get("state") == "active":
                active_seen = True
        return tuple(results)


__all__ = [
    "DISPATCH_TERMINAL_NAME",
    "INTENT_NAME",
    "LocalCampaignDispatchError",
    "LocalEngineeringCampaignDispatcher",
    "STATUS_NAME",
]
