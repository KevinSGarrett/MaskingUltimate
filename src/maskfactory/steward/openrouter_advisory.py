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
    r"C:\Comfy_UI_Main\Plan\07_IMPLEMENTATION\scripts" r"\manage_openrouter_reasoning_fallback.py"
)
POLICY_PATH = Path(
    r"C:\Comfy_UI_Main\Plan\10_REGISTRIES" r"\openrouter_reasoning_fallback_policy.json"
)
STATE_ROOT = Path.home() / ".codex/openrouter_fallback"
STATE_SCHEMA = "maskfactory.steward.openrouter_advisory_state.v2"
LEGACY_REQUEST_SCHEMA = "maskfactory.openrouter_advisory_request.v1"
REQUEST_SCHEMA = "maskfactory.openrouter_advisory_request.v2"
PARENT_BINDING_SCHEMA = "comfyui.openrouter_parent_binding.v1"
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


def _parent_binding_sha256(request: Mapping[str, Any]) -> str:
    return _sha256_bytes(
        _canonical_bytes(
            {
                "schema_version": PARENT_BINDING_SCHEMA,
                "session_id": request["session_id"],
                "parent_campaign_id": request["parent_campaign_id"],
                "parent_contract_sha256": request["parent_contract_sha256"],
                "child_role": request["child_role"],
            }
        )
    )


def _validate_seal(value: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(value))
    expected = body.pop("self_sha256", None)
    if not isinstance(expected, str) or expected != _sha256_bytes(_canonical_bytes(body)):
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
        raise OpenRouterManagerRejected(f"OpenRouter manager rejected command: {detail[-1000:]}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OpenRouterManagerProtocolError("OpenRouter manager output is not JSON") from exc
    if not isinstance(result, dict):
        raise OpenRouterManagerProtocolError("OpenRouter manager output is not an object")
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
                raise OpenRouterAdvisoryError(f"{label} must be inside mission_root") from exc
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
        try:
            policy = json.loads(self.policy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OpenRouterAdvisoryError("OpenRouter policy is unreadable") from exc
        if (
            not isinstance(policy, dict)
            or not isinstance(policy.get("models"), dict)
            or not isinstance(policy.get("work_profiles"), dict)
        ):
            raise OpenRouterAdvisoryError("OpenRouter policy contract is invalid")
        self.policy = copy.deepcopy(policy)
        self._validate_request(request)
        prompt = self.prompt_path.read_text(encoding="utf-8")
        if _sha256_bytes(prompt.encode("utf-8")) != request["prompt_sha256"]:
            raise OpenRouterAdvisoryError("prompt identity mismatch")
        lowered = prompt.lower()
        if any(marker in lowered for marker in SECRET_MARKERS):
            raise OpenRouterAdvisoryError("prompt may contain secret material")
        self.attachment_paths = self._request_paths(
            request.get("attachments", []),
            label="attachment",
        )
        actual_attachment_hashes = [_file_sha256(path) for path in self.attachment_paths]
        if request.get("attachment_sha256", []) != actual_attachment_hashes:
            raise OpenRouterAdvisoryError("attachment identity mismatch")
        system_prompt_file = request.get("system_prompt_file")
        self.system_prompt_path = None
        if system_prompt_file is not None:
            paths = self._request_paths(
                [system_prompt_file],
                label="system_prompt_file",
            )
            self.system_prompt_path = paths[0]
            system_prompt = self.system_prompt_path.read_text(encoding="utf-8")
            if request.get("system_prompt_sha256") != _file_sha256(self.system_prompt_path):
                raise OpenRouterAdvisoryError("system prompt identity mismatch")
            if any(marker in system_prompt.lower() for marker in SECRET_MARKERS):
                raise OpenRouterAdvisoryError("system prompt may contain secret material")

        self.request = copy.deepcopy(request)
        identity = {
            "schema_version": STATE_SCHEMA,
            "mission_id": request["mission_id"],
            "session_id": request["session_id"],
            "job_id": request["job_id"],
            "parent_campaign_id": request["parent_campaign_id"],
            "parent_contract_sha256": request["parent_contract_sha256"],
            "child_role": request["child_role"],
            "parent_binding_sha256": _parent_binding_sha256(request),
            "work_kind": request["work_kind"],
            "model_tier": request["model_tier"],
            "prompt_sha256": request["prompt_sha256"],
            "request_sha256": _file_sha256(self.request_path),
            "manager_sha256": _file_sha256(self.manager_path),
            "policy_sha256": _file_sha256(self.policy_path),
            "attachment_sha256": actual_attachment_hashes,
            "system_prompt_sha256": (
                _file_sha256(self.system_prompt_path)
                if self.system_prompt_path is not None
                else None
            ),
        }
        if self.state_path.exists():
            state = _validate_seal(json.loads(self.state_path.read_text(encoding="utf-8")))
            for key, value in identity.items():
                if state.get(key) != value:
                    raise OpenRouterAdvisoryError("persisted advisory identity mismatch")
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
        if request.get("schema_version") == LEGACY_REQUEST_SCHEMA:
            raise OpenRouterAdvisoryError(
                "legacy advisory request has no immutable parent binding"
            )
        if request.get("schema_version") != REQUEST_SCHEMA:
            raise OpenRouterAdvisoryError("unsupported advisory request schema")
        for field in (
            "mission_id",
            "parent_campaign_id",
            "parent_contract_sha256",
            "prompt_sha256",
        ):
            if not isinstance(request.get(field), str) or not SHA256_RE.fullmatch(request[field]):
                raise OpenRouterAdvisoryError(f"invalid {field}")
        for field in ("session_id", "work_kind", "child_role"):
            if not isinstance(request.get(field), str) or not request[field]:
                raise OpenRouterAdvisoryError(f"invalid {field}")
        if request["child_role"] != "consolidated_advisory":
            raise OpenRouterAdvisoryError("unsupported advisory child_role")
        if not isinstance(request.get("job_id"), str) or not SAFE_JOB_RE.fullmatch(
            request["job_id"]
        ):
            raise OpenRouterAdvisoryError("invalid job_id")
        model_tier = request.get("model_tier")
        work_kind = request.get("work_kind")
        if model_tier not in self.policy["models"]:
            raise OpenRouterAdvisoryError("model tier is not authorized by policy")
        required_tier = self.policy["work_profiles"].get(work_kind)
        if required_tier is None:
            raise OpenRouterAdvisoryError("work kind is not authorized by policy")
        if model_tier != required_tier and not (
            required_tier == "routine" and model_tier == "escalation"
        ):
            raise OpenRouterAdvisoryError("model tier does not match the governed work profile")
        if request.get("model_tier") == "escalation" and not request.get("materially_difficult"):
            raise OpenRouterAdvisoryError("Qwen escalation requires a materially difficult request")
        authority = request.get("authority")
        if not isinstance(authority, dict):
            raise OpenRouterAdvisoryError("authority ceiling is required")
        if any(authority.get(name) is not False for name in FORBIDDEN_AUTHORITY):
            raise OpenRouterAdvisoryError("advisory request exceeds authority ceiling")
        attachments = request.get("attachments", [])
        if not isinstance(attachments, list) or any(
            not isinstance(value, str) or not value for value in attachments
        ):
            raise OpenRouterAdvisoryError("attachments must be relative mission-root paths")
        attachment_sha256 = request.get("attachment_sha256", [])
        if (
            not isinstance(attachment_sha256, list)
            or len(attachment_sha256) != len(attachments)
            or any(
                not isinstance(value, str) or not SHA256_RE.fullmatch(value)
                for value in attachment_sha256
            )
        ):
            raise OpenRouterAdvisoryError("attachment_sha256 must bind every attachment")
        tokens = request.get("max_output_tokens")
        api_kind = self.policy["models"][model_tier].get("api_kind")
        if api_kind == "chat" and (
            isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0
        ):
            raise OpenRouterAdvisoryError("max_output_tokens must be positive")
        if api_kind != "chat" and tokens not in (None, 0):
            raise OpenRouterAdvisoryError(
                "non-chat capability max_output_tokens must be zero or null"
            )
        if request.get("system_prompt_file") is not None and not isinstance(
            request["system_prompt_file"], str
        ):
            raise OpenRouterAdvisoryError("system_prompt_file must be a relative path")
        system_prompt_sha256 = request.get("system_prompt_sha256")
        if request.get("system_prompt_file") is None:
            if system_prompt_sha256 is not None:
                raise OpenRouterAdvisoryError("system_prompt_sha256 has no bound file")
        elif not isinstance(system_prompt_sha256, str) or not SHA256_RE.fullmatch(
            system_prompt_sha256
        ):
            raise OpenRouterAdvisoryError("system_prompt_sha256 is invalid")

    def _validate_parent_binding_result(
        self,
        result: Mapping[str, Any],
        *,
        context: str,
    ) -> None:
        expected = {
            "parent_campaign_id": self.request["parent_campaign_id"],
            "parent_contract_sha256": self.request["parent_contract_sha256"],
            "child_role": self.request["child_role"],
            "parent_binding_sha256": _parent_binding_sha256(self.request),
        }
        if any(result.get(key) != value for key, value in expected.items()):
            raise OpenRouterManagerProtocolError(
                f"{context} parent binding contradicts immutable request"
            )

    def _request_paths(self, values: list[str], *, label: str) -> list[Path]:
        paths: list[Path] = []
        for value in values:
            relative = Path(value)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise OpenRouterAdvisoryError(f"{label} must remain inside mission_root")
            path = (self.mission_root / relative).resolve()
            try:
                path.relative_to(self.mission_root)
            except ValueError as exc:
                raise OpenRouterAdvisoryError(f"{label} must remain inside mission_root") from exc
            if not path.is_file():
                raise OpenRouterAdvisoryError(f"{label} file is absent")
            paths.append(path)
        return paths

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
        arguments = [
            "--session-id",
            self.request["session_id"],
            "--job-id",
            self.request["job_id"],
            "--parent-campaign-id",
            self.request["parent_campaign_id"],
            "--parent-contract-sha256",
            self.request["parent_contract_sha256"],
            "--child-role",
            self.request["child_role"],
            "--work-kind",
            self.request["work_kind"],
            "--model-tier",
            self.request["model_tier"],
            "--prompt-file",
            str(self.prompt_path),
        ]
        if self.request.get("max_output_tokens") is not None:
            arguments.extend(
                [
                    "--max-output-tokens",
                    str(self.request["max_output_tokens"]),
                ]
            )
        for attachment_path in self.attachment_paths:
            arguments.extend(["--attachment", str(attachment_path)])
        try:
            result = self._command("reserve", *arguments)
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
            raise OpenRouterOutcomeUnknown("reservation outcome is unknown; do not retry") from exc
        try:
            self._validate_parent_binding_result(result, context="reservation")
        except OpenRouterManagerProtocolError as exc:
            self._transition(
                self._state,
                "outcome_unknown",
                "reservation_parent_binding_contradiction",
                result=result,
                error=str(exc),
            )
            raise OpenRouterOutcomeUnknown(
                "reservation parent binding contradicts immutable request"
            ) from exc
        if (
            result.get("status") != "RESERVED"
            or result.get("session_id") != self.request["session_id"]
            or result.get("job_id") != self.request["job_id"]
            or result.get("work_kind") != self.request["work_kind"]
            or result.get("model_tier") != self.request["model_tier"]
            or result.get("prompt_sha256") != self.request["prompt_sha256"]
            or not isinstance(result.get("reservation_id"), str)
        ):
            self._transition(
                self._state,
                "outcome_unknown",
                "reservation_output_contradiction",
                result=result,
            )
            raise OpenRouterOutcomeUnknown("reservation output contradicts immutable request")
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
        arguments = [
            "--reservation-id",
            reservation_id,
            "--prompt-file",
            str(self.prompt_path),
            "--output",
            str(self.output_path),
        ]
        if self.system_prompt_path is not None:
            arguments.extend(["--system-prompt-file", str(self.system_prompt_path)])
        for attachment_path in self.attachment_paths:
            arguments.extend(["--attachment", str(attachment_path)])
        try:
            result = self._command("submit", *arguments)
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
        try:
            self._validate_parent_binding_result(result, context="submission")
        except OpenRouterManagerProtocolError as exc:
            self._transition(
                self._state,
                "outcome_unknown",
                "submit_parent_binding_contradiction",
                result=result,
                error=str(exc),
            )
            raise OpenRouterOutcomeUnknown(
                "submission parent binding contradicts immutable request"
            ) from exc
        if (
            result.get("status") not in {"COMPLETED", "SUBMITTED"}
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
        if result.get("content_sha256") and not SHA256_RE.fullmatch(str(result["content_sha256"])):
            raise OpenRouterManagerProtocolError("invalid advisory content hash")
        if result["status"] == "SUBMITTED":
            if self.request["model_tier"] != "video_generation":
                self._transition(
                    self._state,
                    "outcome_unknown",
                    "unexpected_async_submission",
                    result=result,
                )
                raise OpenRouterOutcomeUnknown(
                    "only governed video generation may remain asynchronous"
                )
            self._transition(
                self._state,
                "submitted",
                "video_submitted",
                result=result,
            )
            return self.state
        self._transition(
            self._state,
            "terminal",
            "advisory_completed",
            result=result,
            output_sha256=output_sha256,
        )
        return self.state

    def reconcile_unknown(self) -> dict[str, Any]:
        """Inspect manager state and never guess whether submission occurred."""
        if self._state["state"] != "outcome_unknown":
            raise OpenRouterAdvisoryError(
                f"unknown reconciliation is not allowed from state {self._state['state']}"
            )
        reservation_id = self._state.get("reservation_id")
        if not isinstance(reservation_id, str) or not reservation_id:
            raise OpenRouterOutcomeUnknown("unknown outcome has no reservation identity")
        try:
            result = self._command(
                "inspect-reservation",
                "--reservation-id",
                reservation_id,
            )
        except (
            OpenRouterManagerRejected,
            OpenRouterManagerTimeout,
            OpenRouterManagerProtocolError,
        ) as exc:
            raise OpenRouterOutcomeUnknown(
                "reservation inspection is unavailable; submission remains unknown"
            ) from exc
        try:
            self._validate_parent_binding_result(result, context="inspection")
        except OpenRouterManagerProtocolError as exc:
            raise OpenRouterOutcomeUnknown(
                "reservation inspection parent binding contradicts immutable request"
            ) from exc
        if (
            result.get("reservation_id") != reservation_id
            or result.get("session_id") != self.request["session_id"]
            or result.get("job_id") != self.request["job_id"]
            or result.get("work_kind") != self.request["work_kind"]
            or result.get("model_tier") != self.request["model_tier"]
            or result.get("prompt_sha256") != self.request["prompt_sha256"]
        ):
            raise OpenRouterOutcomeUnknown(
                "reservation inspection contradicts immutable request identity"
            )
        status = result.get("status")
        if (
            status == "RESERVED"
            and result.get("provider_job_id") is None
            and result.get("submitted_at") is None
        ):
            return self._transition(
                self._state,
                "reserved",
                "submission_absent_reconciled",
                result=result,
                error=None,
            )
        if status == "COMPLETED" and self.output_path.is_file():
            return self._transition(
                self._state,
                "terminal",
                "completed_output_reconstructed",
                result=result,
                output_sha256=_file_sha256(self.output_path),
                error=None,
            )
        if status in {"FAILED", "EXPIRED", "CANCELLED"}:
            return self._transition(
                self._state,
                "failed",
                "terminal_failure_reconstructed",
                result=result,
                error=f"manager reservation terminalized as {status}",
            )
        raise OpenRouterOutcomeUnknown(
            f"manager reservation remains {status}; submission cannot be reissued"
        )

    def reconcile(self) -> dict[str, Any]:
        """Reconcile asynchronous governed video work without resubmission."""
        if self._state["state"] not in {"submitted", "running"}:
            if self._state["state"] == "terminal":
                return self.state
            raise OpenRouterAdvisoryError(
                f"reconcile is not allowed from state {self._state['state']}"
            )
        reservation_id = self._state["reservation_id"]
        try:
            result = self._command(
                "reconcile-video",
                "--reservation-id",
                reservation_id,
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
                "video_reconcile_outcome_unknown",
                error=str(exc),
            )
            raise OpenRouterOutcomeUnknown(
                "video reconciliation is unknown; do not retry submission"
            ) from exc
        try:
            self._validate_parent_binding_result(result, context="video reconciliation")
        except OpenRouterManagerProtocolError as exc:
            self._transition(
                self._state,
                "outcome_unknown",
                "video_reconcile_parent_binding_contradiction",
                result=result,
                error=str(exc),
            )
            raise OpenRouterOutcomeUnknown(
                "video reconciliation parent binding contradicts immutable request"
            ) from exc
        if (
            result.get("reservation_id") != reservation_id
            or result.get("status") not in {"PENDING", "IN_PROGRESS", "COMPLETED"}
            or Path(str(result.get("output"))).resolve() != self.output_path
            or not self.output_path.is_file()
        ):
            self._transition(
                self._state,
                "outcome_unknown",
                "video_reconcile_contradiction",
                result=result,
            )
            raise OpenRouterOutcomeUnknown("video reconciliation contradicts immutable state")
        if result["status"] == "COMPLETED":
            self._transition(
                self._state,
                "terminal",
                "video_completed",
                result=result,
                output_sha256=_file_sha256(self.output_path),
            )
        else:
            self._transition(
                self._state,
                "running",
                "video_still_running",
                result=result,
            )
        return self.state
