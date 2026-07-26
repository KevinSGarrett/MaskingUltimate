"""Governed, manager-only OpenRouter advisory routing.

The adapter never imports or calls a provider client. It persists immutable
intent before invoking the shared manager and converts ineligible, rejected,
or capped work into an explicit CPU-safe continuation. Advisory output never
receives execution or final-acceptance authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

MANAGER_PATH = Path(
    r"C:\Comfy_UI_Main\Plan\07_IMPLEMENTATION\scripts"
    r"\manage_openrouter_reasoning_fallback.py"
)
POLICY_PATH = Path(
    r"C:\Comfy_UI_Main\Plan\10_REGISTRIES"
    r"\openrouter_reasoning_fallback_policy.json"
)
STATE_ROOT = Path.home() / ".codex/openrouter_fallback"
STATE_SCHEMA = "maskfactory.steward.openrouter_advisory_state.v1"
REQUEST_SCHEMA = "maskfactory.openrouter_advisory_request.v1"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_JOB_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
FORBIDDEN_AUTHORITY = frozenset(
    {
        "read_secrets",
        "execute_tools",
        "git",
        "github",
        "runpod_lifecycle",
        "infrastructure",
        "destructive_filesystem",
        "final_acceptance",
    }
)
SECRET_MARKERS = (
    "-----begin private key-----",
    "openrouter_api_key=",
    "aws_secret_access_key=",
    "authorization: bearer ",
    "password=",
    "client_secret=",
)


class OpenRouterAdvisoryError(RuntimeError):
    """Base error for governed advisory routing."""


class OpenRouterManagerRejected(OpenRouterAdvisoryError):
    """The manager rejected a command without an ambiguous transport."""


class OpenRouterManagerTimeout(OpenRouterAdvisoryError):
    """A manager command timed out and may have changed durable state."""


class OpenRouterManagerProtocolError(OpenRouterAdvisoryError):
    """The manager returned malformed or contradictory output."""


class OpenRouterOutcomeUnknown(OpenRouterAdvisoryError):
    """A reservation or submission must not be reissued."""


CommandRunner = Callable[[Sequence[str], float], Mapping[str, Any]]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(dict(value))
    sealed.pop("self_sha256", None)
    sealed["self_sha256"] = _sha256_bytes(_canonical_bytes(sealed))
    return sealed


def _validate_seal(value: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(value))
    expected = body.pop("self_sha256", None)
    if not isinstance(expected, str) or expected != _sha256_bytes(
        _canonical_bytes(body)
    ):
        raise OpenRouterAdvisoryError("durable advisory state hash mismatch")
    body["self_sha256"] = expected
    return body


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    body = json.dumps(value, indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _default_runner(
    command: Sequence[str],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpenRouterManagerTimeout("OpenRouter manager command timed out") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise OpenRouterManagerRejected(
            f"OpenRouter manager rejected command: {detail[-1000:]}"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OpenRouterManagerProtocolError(
            "OpenRouter manager output is not JSON"
        ) from exc
    if not isinstance(result, dict):
        raise OpenRouterManagerProtocolError(
            "OpenRouter manager output is not an object"
        )
    return result


class GovernedOpenRouterAdvisory:
    """Durable Qwen-first advisory route with explicit CPU fallback."""

    def __init__(
        self,
        *,
        mission_root: Path,
        request_path: Path,
        prompt_path: Path,
        manager_path: Path = MANAGER_PATH,
        policy_path: Path = POLICY_PATH,
        manager_state_root: Path = STATE_ROOT,
        python_executable: str = sys.executable,
        command_runner: CommandRunner = _default_runner,
        command_timeout_seconds: float = 60.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.mission_root = Path(mission_root).resolve()
        self.request_path = Path(request_path).resolve()
        self.prompt_path = Path(prompt_path).resolve()
        self.manager_path = Path(manager_path)
        self.policy_path = Path(policy_path)
        self.manager_state_root = Path(manager_state_root)
        self.python_executable = python_executable
        self.command_runner = command_runner
        self.command_timeout_seconds = command_timeout_seconds
        self.clock = clock
        self.state_path = self.mission_root / "openrouter_advisory_state.json"
        self.output_path = self.mission_root / "openrouter_advisory_output.json"

        for path, label in (
            (self.request_path, "request"),
            (self.prompt_path, "prompt"),
        ):
            try:
                path.relative_to(self.mission_root)
            except ValueError as exc:
                raise OpenRouterAdvisoryError(
                    f"{label} must be inside mission_root"
                ) from exc
            if not path.is_file():
                raise OpenRouterAdvisoryError(f"{label} file is absent")
        if not self.manager_path.is_file() or not self.policy_path.is_file():
            raise OpenRouterAdvisoryError("governed OpenRouter manager is unavailable")

        try:
            request = json.loads(self.request_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OpenRouterAdvisoryError("advisory request is unreadable") from exc
        if not isinstance(request, dict):
            raise OpenRouterAdvisoryError("advisory request must be an object")
        self._validate_request(request)
        prompt = self.prompt_path.read_text(encoding="utf-8")
        if _sha256_bytes(prompt.encode("utf-8")) != request["prompt_sha256"]:
            raise OpenRouterAdvisoryError("prompt identity mismatch")
        lowered = prompt.lower()
        if any(marker in lowered for marker in SECRET_MARKERS):
            raise OpenRouterAdvisoryError("prompt may contain secret material")

        self.request = copy.deepcopy(request)
        identity = {
            "schema_version": STATE_SCHEMA,
            "mission_id": request["mission_id"],
            "session_id": request["session_id"],
            "job_id": request["job_id"],
            "work_kind": request["work_kind"],
            "model_tier": request["model_tier"],
            "prompt_sha256": request["prompt_sha256"],
            "request_sha256": _file_sha256(self.request_path),
            "manager_sha256": _file_sha256(self.manager_path),
            "policy_sha256": _file_sha256(self.policy_path),
        }
        if self.state_path.exists():
            state = _validate_seal(
                json.loads(self.state_path.read_text(encoding="utf-8"))
            )
            for key, value in identity.items():
                if state.get(key) != value:
                    raise OpenRouterAdvisoryError(
                        "persisted advisory identity mismatch"
                    )
            if state["state"] in {"reserving", "submitting"}:
                state = self._transition(
                    state,
                    "outcome_unknown",
                    "restart_after_manager_intent",
                )
            self._state = state
        else:
            self._state = _seal(
                {
                    **identity,
                    "state": "intent_persisted",
                    "route": None,
                    "reservation_id": None,
                    "output_sha256": None,
                    "last_result": None,
                    "last_error": None,
                    "updated_at": self.clock(),
                }
            )
            _atomic_write_json(self.state_path, self._state)

    @property
    def state(self) -> dict[str, Any]:
        return copy.deepcopy(self._state)

    def _validate_request(self, request: Mapping[str, Any]) -> None:
        if request.get("schema_version") != REQUEST_SCHEMA:
            raise OpenRouterAdvisoryError("unsupported advisory request schema")
        for field in ("mission_id", "prompt_sha256"):
            if not isinstance(request.get(field), str) or not SHA256_RE.fullmatch(
                request[field]
            ):
                raise OpenRouterAdvisoryError(f"invalid {field}")
        for field in ("session_id", "work_kind"):
            if not isinstance(request.get(field), str) or not request[field]:
                raise OpenRouterAdvisoryError(f"invalid {field}")
        if not isinstance(request.get("job_id"), str) or not SAFE_JOB_RE.fullmatch(
            request["job_id"]
        ):
            raise OpenRouterAdvisoryError("invalid job_id")
        if request.get("model_tier") not in {"routine", "escalation"}:
            raise OpenRouterAdvisoryError("only Qwen advisory tiers are allowed")
        if request.get("model_tier") == "escalation" and not request.get(
            "materially_difficult"
        ):
            raise OpenRouterAdvisoryError(
                "Qwen escalation requires a materially difficult request"
            )
        authority = request.get("authority")
        if not isinstance(authority, dict):
            raise OpenRouterAdvisoryError("authority ceiling is required")
        if any(authority.get(name) is not False for name in FORBIDDEN_AUTHORITY):
            raise OpenRouterAdvisoryError("advisory request exceeds authority ceiling")
        if request.get("attachments") not in (None, []):
            raise OpenRouterAdvisoryError(
                "text advisory does not admit attachments or private raw data"
            )
        tokens = request.get("max_output_tokens")
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0:
            raise OpenRouterAdvisoryError("max_output_tokens must be positive")

    def _transition(
        self,
        current: Mapping[str, Any],
        state: str,
        event: str,
        *,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
        **updates: Any,
    ) -> dict[str, Any]:
        changed = copy.deepcopy(dict(current))
        changed.update(updates)
        changed.update(
            {
                "state": state,
                "event": event,
                "last_result": copy.deepcopy(dict(result)) if result else None,
                "last_error": error[:1000] if error else None,
                "updated_at": self.clock(),
            }
        )
        self._state = _seal(changed)
        _atomic_write_json(self.state_path, self._state)
        return self.state

    def _command(self, verb: str, *arguments: str) -> Mapping[str, Any]:
        command = [
            self.python_executable,
            str(self.manager_path),
            "--policy",
            str(self.policy_path),
            "--state-root",
            str(self.manager_state_root),
            verb,
            *arguments,
        ]
        return self.command_runner(command, self.command_timeout_seconds)

    def decide(self, *, pod_state: str, serverless_state: str) -> dict[str, Any]:
        if self._state["state"] != "intent_persisted":
            raise OpenRouterAdvisoryError(
                f"decide is not allowed from state {self._state['state']}"
            )
        try:
            result = self._command(
                "decide",
                "--session-id",
                self.request["session_id"],
                "--pod-state",
                pod_state,
                "--serverless-state",
                serverless_state,
                "--work-kind",
                self.request["work_kind"],
            )
        except OpenRouterManagerRejected as exc:
            self._transition(
                self._state,
                "cpu_fallback",
                "decision_rejected_continue_cpu",
                error=str(exc),
                route="continue_cpu",
            )
            return self.state
        if result.get("session_id") != self.request["session_id"]:
            raise OpenRouterManagerProtocolError("decision session mismatch")
        if result.get("route") != "openrouter_multimodal":
            self._transition(
                self._state,
                "cpu_fallback",
                "openrouter_not_selected_continue_cpu",
                result=result,
                route="continue_cpu",
            )
        else:
            self._transition(
                self._state,
                "decided",
                "openrouter_selected",
                result=result,
                route="openrouter_advisory",
            )
        return self.state

    def reserve(self) -> dict[str, Any]:
        if self._state["state"] != "decided":
            raise OpenRouterAdvisoryError(
                f"reserve is not allowed from state {self._state['state']}"
            )
        self._transition(self._state, "reserving", "reserve_intent")
        try:
            result = self._command(
                "reserve",
                "--session-id",
                self.request["session_id"],
                "--job-id",
                self.request["job_id"],
                "--work-kind",
                self.request["work_kind"],
                "--model-tier",
                self.request["model_tier"],
                "--prompt-file",
                str(self.prompt_path),
                "--max-output-tokens",
                str(self.request["max_output_tokens"]),
            )
        except OpenRouterManagerRejected as exc:
            self._transition(
                self._state,
                "cpu_fallback",
                "reservation_rejected_continue_cpu",
                error=str(exc),
                route="continue_cpu",
            )
            return self.state
        except (OpenRouterManagerTimeout, OpenRouterManagerProtocolError) as exc:
            self._transition(
                self._state,
                "outcome_unknown",
                "reservation_outcome_unknown",
                error=str(exc),
            )
            raise OpenRouterOutcomeUnknown(
                "reservation outcome is unknown; do not retry"
            ) from exc
        if (
            result.get("status") != "RESERVED"
            or result.get("session_id") != self.request["session_id"]
            or result.get("job_id") != self.request["job_id"]
            or result.get("work_kind") != self.request["work_kind"]
            or result.get("prompt_sha256") != self.request["prompt_sha256"]
            or not isinstance(result.get("reservation_id"), str)
        ):
            self._transition(
                self._state,
                "outcome_unknown",
                "reservation_output_contradiction",
                result=result,
            )
            raise OpenRouterOutcomeUnknown(
                "reservation output contradicts immutable request"
            )
        self._transition(
            self._state,
            "reserved",
            "reserved",
            result=result,
            reservation_id=result["reservation_id"],
        )
        return self.state

    def submit(self) -> dict[str, Any]:
        if self._state["state"] != "reserved":
            raise OpenRouterAdvisoryError(
                f"submit is not allowed from state {self._state['state']}"
            )
        reservation_id = self._state["reservation_id"]
        self._transition(self._state, "submitting", "submit_intent")
        try:
            result = self._command(
                "submit",
                "--reservation-id",
                reservation_id,
                "--prompt-file",
                str(self.prompt_path),
                "--output",
                str(self.output_path),
            )
        except (
            OpenRouterManagerRejected,
            OpenRouterManagerTimeout,
            OpenRouterManagerProtocolError,
        ) as exc:
            self._transition(
                self._state,
                "outcome_unknown",
                "submit_outcome_unknown",
                error=str(exc),
            )
            raise OpenRouterOutcomeUnknown(
                "submission outcome is unknown; do not retry or change route"
            ) from exc
        if (
            result.get("status") != "COMPLETED"
            or result.get("reservation_id") != reservation_id
            or Path(str(result.get("output"))).resolve() != self.output_path
            or not self.output_path.is_file()
        ):
            self._transition(
                self._state,
                "outcome_unknown",
                "submit_output_contradiction",
                result=result,
            )
            raise OpenRouterOutcomeUnknown("submission output is contradictory")
        output_sha256 = _file_sha256(self.output_path)
        if result.get("content_sha256") and not SHA256_RE.fullmatch(
            str(result["content_sha256"])
        ):
            raise OpenRouterManagerProtocolError("invalid advisory content hash")
        self._transition(
            self._state,
            "terminal",
            "advisory_completed",
            result=result,
            output_sha256=output_sha256,
        )
        return self.state
