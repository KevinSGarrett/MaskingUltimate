"""Production wiring for governed Serverless and OpenRouter fallback work.

The route adapters already provide provider-specific exactly-once behavior.
This dispatcher supplies the missing production loop: it discovers immutable
work items, claims one canonical route per mission, and advances Serverless
and OpenRouter work concurrently for different missions.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import sys
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .openrouter_advisory import (
    GovernedOpenRouterAdvisory,
    OpenRouterAdvisoryError,
    OpenRouterOutcomeUnknown,
)
from .route_control import (
    PARENT_CHILD_ROUTES,
    CanonicalParentChildLedger,
    CanonicalMissionRouteLedger,
    RouteAlreadyActive,
    RouteControlError,
)
from .serverless_broker import (
    BrokerOnlyServerlessRoute,
    ServerlessRouteAmbiguous,
    ServerlessRouteError,
)

LEGACY_WORK_ITEM_SCHEMA = "maskfactory.steward.fallback_work_item.v1"
WORK_ITEM_SCHEMA = "maskfactory.steward.fallback_work_item.v2"
CHILD_BINDING_SCHEMA = "maskfactory.steward.fallback_child_binding.v1"
STATUS_SCHEMA = "maskfactory.steward.fallback_dispatch_status.v1"
TERMINAL_SCHEMA = "maskfactory.steward.fallback_terminal_receipt.v1"
WORK_ITEM_NAME = "fallback_work_item.json"
STATUS_NAME = "fallback_dispatch_status.json"
TERMINAL_NAME = "fallback_terminal_receipt.json"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ROUTE_NAMES = frozenset({"serverless_overflow", "openrouter_advisory"})

RouteFactory = Callable[..., Any]


class FallbackDispatchError(RuntimeError):
    """A fallback work item is malformed or cannot advance safely."""


class LegacyFallbackWorkItem(FallbackDispatchError):
    """A historical unbound item is preserved but is not eligible for dispatch."""


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


def _serverless_disposition(result: Mapping[str, Any]) -> str:
    """Classify a broker-terminal result without mistaking a semantic false for success."""
    if result.get("state") != "completed":
        return "failed"
    raw_status = result.get("provider_status_json")
    if not isinstance(raw_status, str):
        return "completed"
    try:
        provider_status = json.loads(raw_status)
    except json.JSONDecodeError:
        return "completed"
    if not isinstance(provider_status, Mapping):
        return "completed"
    output = provider_status.get("output")
    if not isinstance(output, Mapping):
        return "completed"
    stdout_tail = output.get("stdout_tail")
    if not isinstance(stdout_tail, str):
        return "completed"
    for line in reversed(stdout_tail.splitlines()):
        try:
            report = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(report, Mapping):
            return (
                "failed"
                if report.get("native_box_runtime_ready") is False
                else "completed"
            )
    return "completed"


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    sealed = copy.deepcopy(dict(value))
    sealed["self_sha256"] = "0" * 64
    sealed["self_sha256"] = _canonical_sha256(sealed)
    return sealed


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
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
        temporary.unlink(missing_ok=True)
        raise


def _safe_relative_file(root: Path, value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise FallbackDispatchError(f"{label} must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise FallbackDispatchError(f"{label} is not a safe relative path")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FallbackDispatchError(f"{label} escapes the mission root") from exc
    if not path.is_file():
        raise FallbackDispatchError(f"{label} is missing")
    return path


def seal_fallback_work_item(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical zero-self-hashed immutable work-item document."""
    return _seal(value)


def fallback_child_mission_id(
    *,
    session_id: str,
    parent_campaign_id: str,
    parent_contract_sha256: str,
    required_child_roles: tuple[str, ...],
    child_role: str,
    route: str,
) -> str:
    """Derive one child mission identity without circular payload binding."""
    return _canonical_sha256(
        {
            "schema_version": CHILD_BINDING_SCHEMA,
            "session_id": session_id,
            "parent_campaign_id": parent_campaign_id,
            "parent_contract_sha256": parent_contract_sha256,
            "required_child_roles": list(required_child_roles),
            "child_role": child_role,
            "route": route,
        }
    )


class FallbackWorkDispatcher:
    """Discover and advance governed fallback missions without dual submission."""

    def __init__(
        self,
        *,
        inbox_root: Path,
        state_root: Path,
        serverless_manager_path: Path,
        serverless_config_path: Path,
        serverless_broker_root: Path,
        openrouter_manager_path: Path,
        openrouter_policy_path: Path,
        openrouter_manager_state_root: Path,
        serverless_api_key_file: Path | None = None,
        python_executable: str = sys.executable,
        serverless_factory: RouteFactory = BrokerOnlyServerlessRoute,
        openrouter_factory: RouteFactory = GovernedOpenRouterAdvisory,
        max_serverless_workers: int = 4,
        max_openrouter_workers: int = 4,
    ) -> None:
        for value, label in (
            (max_serverless_workers, "max_serverless_workers"),
            (max_openrouter_workers, "max_openrouter_workers"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise FallbackDispatchError(f"{label} must be positive")
        self.inbox_root = Path(inbox_root)
        self.state_root = Path(state_root)
        self.inbox_root.mkdir(parents=True, exist_ok=True)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.token_root = self.state_root / "route_tokens"
        self.token_root.mkdir(exist_ok=True)
        ledger_path = self.state_root / "canonical_routes.sqlite"
        self.ledger = CanonicalMissionRouteLedger(ledger_path)
        self.parent_ledger = CanonicalParentChildLedger(ledger_path)
        self.serverless_manager_path = Path(serverless_manager_path)
        self.serverless_config_path = Path(serverless_config_path)
        self.serverless_broker_root = Path(serverless_broker_root)
        self.openrouter_manager_path = Path(openrouter_manager_path)
        self.openrouter_policy_path = Path(openrouter_policy_path)
        self.openrouter_manager_state_root = Path(openrouter_manager_state_root)
        self.serverless_api_key_file = (
            Path(serverless_api_key_file) if serverless_api_key_file is not None else None
        )
        self.python_executable = python_executable
        self.serverless_factory = serverless_factory
        self.openrouter_factory = openrouter_factory
        self.max_serverless_workers = max_serverless_workers
        self.max_openrouter_workers = max_openrouter_workers

    def _load_item(self, mission_root: Path) -> dict[str, Any]:
        path = mission_root / WORK_ITEM_NAME
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FallbackDispatchError(f"unreadable fallback work item: {path}") from exc
        if not isinstance(item, dict):
            raise FallbackDispatchError("fallback work item must be an object")
        if item.get("schema_version") == LEGACY_WORK_ITEM_SCHEMA:
            raise LegacyFallbackWorkItem(
                "legacy fallback work item has no immutable parent binding"
            )
        declared = item.get("self_sha256")
        zeroed = copy.deepcopy(item)
        zeroed["self_sha256"] = "0" * 64
        if (
            item.get("schema_version") != WORK_ITEM_SCHEMA
            or not isinstance(declared, str)
            or not SHA256_RE.fullmatch(declared)
            or _canonical_sha256(zeroed) != declared
        ):
            raise FallbackDispatchError("fallback work item seal is invalid")
        for field in ("mission_id", "payload_sha256"):
            if not isinstance(item.get(field), str) or not SHA256_RE.fullmatch(item[field]):
                raise FallbackDispatchError(f"fallback work item {field} is invalid")
        if not isinstance(item.get("session_id"), str) or not item["session_id"]:
            raise FallbackDispatchError("fallback work item session_id is invalid")
        if item.get("route") not in ROUTE_NAMES:
            raise FallbackDispatchError("fallback work item route is invalid")
        for field in ("parent_campaign_id", "parent_contract_sha256"):
            if not isinstance(item.get(field), str) or not SHA256_RE.fullmatch(
                item[field]
            ):
                raise FallbackDispatchError(
                    f"fallback work item {field} is invalid"
                )
        required_roles = item.get("required_child_roles")
        if (
            not isinstance(required_roles, list)
            or not required_roles
            or any(not isinstance(role, str) for role in required_roles)
            or required_roles != sorted(set(required_roles))
            or any(role not in PARENT_CHILD_ROUTES for role in required_roles)
        ):
            raise FallbackDispatchError(
                "fallback work item required_child_roles are invalid"
            )
        child_role = item.get("child_role")
        if child_role not in required_roles:
            raise FallbackDispatchError(
                "fallback work item child_role is not required by its parent"
            )
        if PARENT_CHILD_ROUTES.get(child_role) != item["route"]:
            raise FallbackDispatchError(
                "fallback work item child_role does not match its route"
            )
        expected_mission_id = fallback_child_mission_id(
            session_id=item["session_id"],
            parent_campaign_id=item["parent_campaign_id"],
            parent_contract_sha256=item["parent_contract_sha256"],
            required_child_roles=tuple(required_roles),
            child_role=child_role,
            route=item["route"],
        )
        if item["mission_id"] != expected_mission_id:
            raise FallbackDispatchError(
                "fallback child mission identity mismatch"
            )
        if mission_root.name != item["mission_id"]:
            raise FallbackDispatchError("mission directory identity mismatch")
        if item["route"] == "serverless_overflow":
            payload_path = _safe_relative_file(
                mission_root,
                item.get("payload_file"),
                label="payload_file",
            )
            try:
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise FallbackDispatchError("Serverless payload is unreadable") from exc
            if (
                not isinstance(payload, dict)
                or _canonical_sha256(payload) != item["payload_sha256"]
            ):
                raise FallbackDispatchError("Serverless payload identity mismatch")
            seconds = item.get("requested_seconds")
            if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
                raise FallbackDispatchError("requested_seconds must be positive")
        else:
            request_path = _safe_relative_file(
                mission_root,
                item.get("request_file"),
                label="request_file",
            )
            _safe_relative_file(
                mission_root,
                item.get("prompt_file"),
                label="prompt_file",
            )
            if _file_sha256(request_path) != item["payload_sha256"]:
                raise FallbackDispatchError("OpenRouter request identity mismatch")
        return item

    def discover(self) -> list[tuple[Path, dict[str, Any]]]:
        """Return valid, non-terminal work items in deterministic order."""
        discovered: list[tuple[Path, dict[str, Any]]] = []
        for mission_root in sorted(self.inbox_root.iterdir()):
            if (
                not mission_root.is_dir()
                or not (mission_root / WORK_ITEM_NAME).is_file()
                or (mission_root / TERMINAL_NAME).exists()
            ):
                continue
            status_path = mission_root / STATUS_NAME
            if status_path.is_file():
                try:
                    status = json.loads(status_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    status = {}
                if status.get("state") == "route_unavailable":
                    continue
            try:
                item = self._load_item(mission_root)
            except LegacyFallbackWorkItem:
                continue
            discovered.append((mission_root, item))
        return discovered

    def pending_ids(self) -> list[str]:
        return [item["mission_id"] for _, item in self.discover()]

    def _token_path(self, mission_id: str) -> Path:
        return self.token_root / f"{mission_id}.token"

    def _owner_token(self, mission_id: str) -> str:
        path = self._token_path(mission_id)
        if path.exists():
            token = path.read_text(encoding="ascii")
            if len(token) < 32:
                raise FallbackDispatchError("persisted route token is invalid")
            return token
        token = secrets.token_hex(32)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii", newline="") as stream:
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            os.chmod(path, 0o600)
        return token

    def _release_token(self, mission_id: str) -> None:
        self._token_path(mission_id).unlink(missing_ok=True)

    def _status(
        self,
        mission_root: Path,
        item: Mapping[str, Any],
        *,
        state: str,
        detail: str,
    ) -> dict[str, Any]:
        value = _seal(
            {
                "schema_version": STATUS_SCHEMA,
                "mission_id": item["mission_id"],
                "parent_campaign_id": item["parent_campaign_id"],
                "parent_contract_sha256": item["parent_contract_sha256"],
                "required_child_roles": item["required_child_roles"],
                "child_role": item["child_role"],
                "route": item["route"],
                "state": state,
                "detail": detail,
                "work_item_sha256": _file_sha256(mission_root / WORK_ITEM_NAME),
                "self_sha256": "0" * 64,
            }
        )
        _atomic_json(mission_root / STATUS_NAME, value)
        return value

    def _terminal(
        self,
        mission_root: Path,
        item: Mapping[str, Any],
        *,
        disposition: str,
        result_path: Path,
        owner_token: str,
    ) -> dict[str, Any]:
        result_sha256 = _file_sha256(result_path)
        self.ledger.terminalize(
            mission_id=item["mission_id"],
            owner_token=owner_token,
            disposition=disposition,
            result_sha256=result_sha256,
        )
        ledger_state = self.ledger.release_terminal(
            mission_id=item["mission_id"],
            owner_token=owner_token,
        )
        parent_state = self.parent_ledger.mark_child(
            parent_campaign_id=item["parent_campaign_id"],
            child_role=item["child_role"],
            owner_token=owner_token,
            state=disposition,
            terminal_disposition=disposition,
            result_sha256=result_sha256,
        )
        receipt = _seal(
            {
                "schema_version": TERMINAL_SCHEMA,
                "mission_id": item["mission_id"],
                "parent_campaign_id": item["parent_campaign_id"],
                "parent_contract_sha256": item["parent_contract_sha256"],
                "required_child_roles": item["required_child_roles"],
                "child_role": item["child_role"],
                "route": item["route"],
                "disposition": disposition,
                "result_file": result_path.name,
                "result_sha256": result_sha256,
                "ledger_state": ledger_state["state"],
                "parent_reconciliation": parent_state,
                "work_item_sha256": _file_sha256(mission_root / WORK_ITEM_NAME),
                "self_sha256": "0" * 64,
            }
        )
        _atomic_json(mission_root / TERMINAL_NAME, receipt)
        self._release_token(item["mission_id"])
        return receipt

    def _release_unavailable(
        self,
        mission_root: Path,
        item: Mapping[str, Any],
        *,
        owner_token: str,
        reason: str,
    ) -> dict[str, Any]:
        self.ledger.release_unavailable(
            mission_id=item["mission_id"],
            owner_token=owner_token,
            reason=reason,
        )
        status = self._status(
            mission_root,
            item,
            state="route_unavailable",
            detail=reason,
        )
        self.parent_ledger.mark_child(
            parent_campaign_id=item["parent_campaign_id"],
            child_role=item["child_role"],
            owner_token=owner_token,
            state="unavailable",
            terminal_disposition="unavailable",
            result_sha256=_file_sha256(mission_root / STATUS_NAME),
            reason=reason,
        )
        self._release_token(item["mission_id"])
        return status

    def _serverless(
        self,
        mission_root: Path,
        item: Mapping[str, Any],
        owner_token: str,
    ) -> dict[str, Any]:
        payload_path = _safe_relative_file(
            mission_root,
            item.get("payload_file"),
            label="payload_file",
        )
        requested_seconds = item.get("requested_seconds")
        if (
            isinstance(requested_seconds, bool)
            or not isinstance(requested_seconds, int)
            or requested_seconds <= 0
        ):
            raise FallbackDispatchError("requested_seconds must be positive")
        route = self.serverless_factory(
            mission_root=mission_root,
            mission_id=item["mission_id"],
            session_id=item["session_id"],
            profile=item.get("profile", "maskfactory"),
            payload_path=payload_path,
            manager_path=self.serverless_manager_path,
            config_path=self.serverless_config_path,
            broker_root=self.serverless_broker_root,
            python_executable=self.python_executable,
            runpod_api_key_file=self.serverless_api_key_file,
        )
        if route.state["payload_sha256"] != item["payload_sha256"]:
            raise FallbackDispatchError("Serverless payload identity mismatch")
        try:
            for _ in range(5):
                state = route.state["state"]
                if state == "intent_persisted":
                    route.decide()
                elif state == "decided":
                    route.reserve(requested_seconds=requested_seconds)
                elif state in {"reserving", "reservation_unknown"}:
                    route.reconcile_reservation()
                elif state == "reserved":
                    route.submit()
                elif state in {
                    "submitted",
                    "running",
                    "submitting",
                    "submitted_unknown",
                    "recovery_required",
                }:
                    route.reconcile()
                elif state == "rejected":
                    return self._release_unavailable(
                        mission_root,
                        item,
                        owner_token=owner_token,
                        reason=route.state.get("last_error") or "Serverless route rejected",
                    )
                elif state == "terminal":
                    result = route.state.get("last_result") or {}
                    disposition = _serverless_disposition(result)
                    return self._terminal(
                        mission_root,
                        item,
                        disposition=disposition,
                        result_path=route.state_path,
                        owner_token=owner_token,
                    )
                else:
                    raise FallbackDispatchError(f"unsupported Serverless state: {state}")
            return self._status(
                mission_root,
                item,
                state="in_progress",
                detail=f"Serverless state is {route.state['state']}",
            )
        except ServerlessRouteAmbiguous as exc:
            return self._status(
                mission_root,
                item,
                state="reconciliation_required",
                detail=str(exc),
            )
        except ServerlessRouteError as exc:
            if route.state["state"] == "rejected":
                return self._release_unavailable(
                    mission_root,
                    item,
                    owner_token=owner_token,
                    reason=str(exc),
                )
            raise

    def _openrouter(
        self,
        mission_root: Path,
        item: Mapping[str, Any],
        owner_token: str,
    ) -> dict[str, Any]:
        request_path = _safe_relative_file(
            mission_root,
            item.get("request_file"),
            label="request_file",
        )
        prompt_path = _safe_relative_file(
            mission_root,
            item.get("prompt_file"),
            label="prompt_file",
        )
        if _file_sha256(request_path) != item["payload_sha256"]:
            raise FallbackDispatchError("OpenRouter request identity mismatch")
        route = self.openrouter_factory(
            mission_root=mission_root,
            request_path=request_path,
            prompt_path=prompt_path,
            manager_path=self.openrouter_manager_path,
            policy_path=self.openrouter_policy_path,
            manager_state_root=self.openrouter_manager_state_root,
            python_executable=self.python_executable,
        )
        try:
            for _ in range(4):
                state = route.state["state"]
                if state == "intent_persisted":
                    route.decide(
                        pod_state=item.get("pod_state", "unavailable"),
                        serverless_state=item.get("serverless_state", "unavailable"),
                    )
                elif state == "decided":
                    route.reserve()
                elif state == "reserved":
                    route.submit()
                elif state in {"submitted", "running"}:
                    route.reconcile()
                elif state == "cpu_fallback":
                    return self._release_unavailable(
                        mission_root,
                        item,
                        owner_token=owner_token,
                        reason=route.state.get("last_error")
                        or "OpenRouter manager selected CPU continuation",
                    )
                elif state == "outcome_unknown":
                    route.reconcile_unknown()
                    if route.state["state"] == "reserved":
                        self.ledger.reconcile_unknown(
                            mission_id=item["mission_id"],
                            owner_token=owner_token,
                            resolution="not_submitted",
                            reason="manager proved reservation remained unsubmitted",
                        )
                        self.ledger.claim_route(
                            mission_id=item["mission_id"],
                            session_id=item["session_id"],
                            payload_sha256=item["payload_sha256"],
                            route=item["route"],
                            owner_token=owner_token,
                        )
                        self.parent_ledger.mark_child(
                            parent_campaign_id=item["parent_campaign_id"],
                            child_role=item["child_role"],
                            owner_token=owner_token,
                            state="active",
                        )
                    elif route.state["state"] == "terminal":
                        durable = self.ledger.reconcile_unknown(
                            mission_id=item["mission_id"],
                            owner_token=owner_token,
                            resolution="completed",
                            reason="manager and persisted output prove completion",
                        )
                        result_sha256 = _file_sha256(route.output_path)
                        parent_state = self.parent_ledger.mark_child(
                            parent_campaign_id=item["parent_campaign_id"],
                            child_role=item["child_role"],
                            owner_token=owner_token,
                            state="completed",
                            terminal_disposition="completed",
                            result_sha256=result_sha256,
                        )
                        receipt = _seal(
                            {
                                "schema_version": TERMINAL_SCHEMA,
                                "mission_id": item["mission_id"],
                                "parent_campaign_id": item["parent_campaign_id"],
                                "parent_contract_sha256": item[
                                    "parent_contract_sha256"
                                ],
                                "required_child_roles": item[
                                    "required_child_roles"
                                ],
                                "child_role": item["child_role"],
                                "route": item["route"],
                                "disposition": "completed",
                                "result_file": route.output_path.name,
                                "result_sha256": result_sha256,
                                "ledger_state": durable["state"],
                                "parent_reconciliation": parent_state,
                                "work_item_sha256": _file_sha256(mission_root / WORK_ITEM_NAME),
                                "self_sha256": "0" * 64,
                            }
                        )
                        _atomic_json(mission_root / TERMINAL_NAME, receipt)
                        self._release_token(item["mission_id"])
                        return receipt
                    elif route.state["state"] == "failed":
                        durable = self.ledger.reconcile_unknown(
                            mission_id=item["mission_id"],
                            owner_token=owner_token,
                            resolution="failed",
                            reason=route.state.get("last_error")
                            or "manager proved terminal failure",
                        )
                        self._status(
                            mission_root,
                            item,
                            state="failed",
                            detail=f"OpenRouter terminal failure: {durable['state']}",
                        )
                        status_sha256 = _file_sha256(
                            mission_root / STATUS_NAME
                        )
                        parent_state = self.parent_ledger.mark_child(
                            parent_campaign_id=item["parent_campaign_id"],
                            child_role=item["child_role"],
                            owner_token=owner_token,
                            state="failed",
                            terminal_disposition="failed",
                            result_sha256=status_sha256,
                            reason=route.state.get("last_error")
                            or "manager proved terminal failure",
                        )
                        receipt = _seal(
                            {
                                "schema_version": TERMINAL_SCHEMA,
                                "mission_id": item["mission_id"],
                                "parent_campaign_id": item[
                                    "parent_campaign_id"
                                ],
                                "parent_contract_sha256": item[
                                    "parent_contract_sha256"
                                ],
                                "required_child_roles": item[
                                    "required_child_roles"
                                ],
                                "child_role": item["child_role"],
                                "route": item["route"],
                                "disposition": "failed",
                                "result_file": STATUS_NAME,
                                "result_sha256": status_sha256,
                                "ledger_state": durable["state"],
                                "parent_reconciliation": parent_state,
                                "work_item_sha256": _file_sha256(
                                    mission_root / WORK_ITEM_NAME
                                ),
                                "self_sha256": "0" * 64,
                            }
                        )
                        _atomic_json(
                            mission_root / TERMINAL_NAME,
                            receipt,
                        )
                        self._release_token(item["mission_id"])
                        return receipt
                    else:
                        raise FallbackDispatchError("unsupported OpenRouter reconciliation result")
                elif state == "terminal":
                    return self._terminal(
                        mission_root,
                        item,
                        disposition="completed",
                        result_path=route.output_path,
                        owner_token=owner_token,
                    )
                else:
                    raise FallbackDispatchError(f"unsupported OpenRouter state: {state}")
            return self._status(
                mission_root,
                item,
                state="in_progress",
                detail=f"OpenRouter state is {route.state['state']}",
            )
        except OpenRouterOutcomeUnknown as exc:
            self.ledger.mark_outcome_unknown(
                mission_id=item["mission_id"],
                owner_token=owner_token,
                reason=str(exc),
            )
            self.parent_ledger.mark_child(
                parent_campaign_id=item["parent_campaign_id"],
                child_role=item["child_role"],
                owner_token=owner_token,
                state="outcome_unknown",
                reason=str(exc),
            )
            return self._status(
                mission_root,
                item,
                state="outcome_unknown",
                detail=str(exc),
            )
        except OpenRouterAdvisoryError:
            raise

    def _process(self, mission_root: Path, item: Mapping[str, Any]) -> dict[str, Any]:
        mission_id = item["mission_id"]
        result_path = (
            mission_root / "serverless_route_state.json"
            if item["route"] == "serverless_overflow"
            else mission_root / "openrouter_advisory_output.json"
        )
        token = self._owner_token(mission_id)
        self.parent_ledger.bind_child(
            parent_campaign_id=item["parent_campaign_id"],
            parent_contract_sha256=item["parent_contract_sha256"],
            required_child_roles=tuple(item["required_child_roles"]),
            child_role=item["child_role"],
            mission_id=mission_id,
            session_id=item["session_id"],
            route=item["route"],
            payload_sha256=item["payload_sha256"],
            owner_token=token,
        )
        try:
            durable = self.ledger.inspect(mission_id)
        except RouteControlError:
            durable = None
        if durable and durable["state"] in {
            "terminal_pending_release",
            "completed",
            "failed_final",
        }:
            if durable["state"] == "terminal_pending_release":
                durable = self.ledger.release_terminal(
                    mission_id=mission_id,
                    owner_token=token,
                )
            if not result_path.is_file():
                raise FallbackDispatchError("terminal route result is absent during reconstruction")
            disposition = (
                "completed" if durable["state"] == "completed" else "failed"
            )
            result_sha256 = _file_sha256(result_path)
            parent_state = self.parent_ledger.mark_child(
                parent_campaign_id=item["parent_campaign_id"],
                child_role=item["child_role"],
                owner_token=token,
                state=disposition,
                terminal_disposition=disposition,
                result_sha256=result_sha256,
            )
            receipt = _seal(
                {
                    "schema_version": TERMINAL_SCHEMA,
                    "mission_id": mission_id,
                    "parent_campaign_id": item["parent_campaign_id"],
                    "parent_contract_sha256": item[
                        "parent_contract_sha256"
                    ],
                    "required_child_roles": item["required_child_roles"],
                    "child_role": item["child_role"],
                    "route": item["route"],
                    "disposition": disposition,
                    "result_file": result_path.name,
                    "result_sha256": result_sha256,
                    "ledger_state": durable["state"],
                    "parent_reconciliation": parent_state,
                    "work_item_sha256": _file_sha256(mission_root / WORK_ITEM_NAME),
                    "self_sha256": "0" * 64,
                }
            )
            _atomic_json(mission_root / TERMINAL_NAME, receipt)
            self._release_token(mission_id)
            return receipt
        if durable and durable["state"] == "outcome_unknown":
            if item["route"] != "openrouter_advisory":
                raise FallbackDispatchError(
                    "unknown Serverless route requires broker reconciliation"
                )
            return self._openrouter(mission_root, item, token)
        try:
            self.ledger.claim_route(
                mission_id=mission_id,
                session_id=item["session_id"],
                payload_sha256=item["payload_sha256"],
                route=item["route"],
                owner_token=token,
            )
        except (RouteAlreadyActive, RouteControlError):
            # Preserve the token and durable route state for explicit recovery.
            raise
        self.parent_ledger.mark_child(
            parent_campaign_id=item["parent_campaign_id"],
            child_role=item["child_role"],
            owner_token=token,
            state="active",
        )
        if item["route"] == "serverless_overflow":
            return self._serverless(mission_root, item, token)
        return self._openrouter(mission_root, item, token)

    def poll_once(self) -> list[dict[str, Any]]:
        """Advance bounded batches on both routes concurrently."""
        selected: list[tuple[Path, dict[str, Any]]] = []
        parent_bindings: dict[str, tuple[str, str, tuple[str, ...]]] = {}
        selected_roles: set[tuple[str, str]] = set()
        route_counts = {route: 0 for route in ROUTE_NAMES}
        limits = {
            "serverless_overflow": self.max_serverless_workers,
            "openrouter_advisory": self.max_openrouter_workers,
        }
        for mission_root, item in self.discover():
            parent_campaign_id = item["parent_campaign_id"]
            parent_binding = (
                item["session_id"],
                item["parent_contract_sha256"],
                tuple(item["required_child_roles"]),
            )
            prior_binding = parent_bindings.setdefault(
                parent_campaign_id,
                parent_binding,
            )
            if prior_binding != parent_binding:
                raise FallbackDispatchError(
                    "fallback parent binding is contradictory"
                )
            role_key = (parent_campaign_id, item["child_role"])
            if role_key in selected_roles:
                raise FallbackDispatchError(
                    "fallback parent child role is duplicated"
                )
            route = item["route"]
            if route_counts[route] >= limits[route]:
                continue
            selected.append((mission_root, item))
            selected_roles.add(role_key)
            route_counts[route] += 1
        if not selected:
            return []
        with ThreadPoolExecutor(max_workers=len(selected)) as executor:
            futures = [
                executor.submit(self._process, mission_root, item)
                for mission_root, item in selected
            ]
            return [future.result() for future in futures]


__all__ = [
    "FallbackDispatchError",
    "FallbackWorkDispatcher",
    "STATUS_NAME",
    "TERMINAL_NAME",
    "WORK_ITEM_NAME",
    "WORK_ITEM_SCHEMA",
    "seal_fallback_work_item",
]
