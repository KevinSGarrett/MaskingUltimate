"""One-model-lifetime execution for a 25-mission engineering campaign.

The accepted steward runtime controller intentionally owns one immutable
mission.  This module composes those mission contracts into the Plan-27
campaign unit without weakening any mission-level exactly-once guarantees:

* one mission launches and owns the local vLLM process;
* the remaining missions attach to the exact PID/start-token/port;
* every request keeps an independent durable request intent and terminal;
* an interrupted request is terminalized as ambiguous and never reissued;
* unrelated missions continue after a terminal per-mission failure; and
* release evidence is recorded for every mission only after the owned process
  is absent and its loopback port is closed.

The caller must run this controller inside the governed shared-Pod GPU guard.
This module never acquires a lease, contacts a provider, or mutates source.
"""

from __future__ import annotations

import json
import os
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from .core import (
    AUTHORITY_KEYS,
    BINDING_SCHEMA as MISSION_BINDING_SCHEMA,
    TERMINAL_RECEIPT_SCHEMA,
    AmbiguousMissionError,
    MissionBindingError,
    MissionConflictError,
    canonical_sha256,
    seal_binding,
    validate_binding,
)
from .runtime import (
    LAUNCH_RECEIPT_SCHEMA,
    SHUTDOWN_RECEIPT_SCHEMA,
    StewardRuntimeController,
    file_sha256,
    load_runtime_contract,
    read_json,
    validate_request,
)

CAMPAIGN_SIZE = 25
BINDING_SCHEMA = "maskfactory.engineering_campaign_runtime_binding.v1"
TERMINAL_SCHEMA = "maskfactory.engineering_campaign_runtime_terminal.v1"
FAILURE_SCHEMA = "maskfactory.engineering_campaign_mission_failure.v1"
NO_PROCESS_RELEASE_SCHEMA = (
    "maskfactory.engineering_campaign_no_process_release.v1"
)
BINDING_NAME = "engineering_campaign_runtime_binding.json"
TERMINAL_NAME = "engineering_campaign_runtime_terminal.json"
STATE_NAME = "engineering_campaign_runtime_state.json"
SHA256_LENGTH = 64
AUTHORITY = {
    "credential_access": False,
    "destructive_filesystem": False,
    "final_acceptance": False,
    "git": False,
    "github": False,
    "infrastructure": False,
    "repository_mutation": False,
    "runpod_lifecycle": False,
    "tracker_completion": False,
}


class EngineeringCampaignRuntimeError(RuntimeError):
    """Campaign runtime evidence is malformed or cannot advance safely."""


def _sha256(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise EngineeringCampaignRuntimeError(f"{field} must be lowercase SHA-256")
    return value


def _identity(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 200
        or any(character in value for character in "/\\\0")
    ):
        raise EngineeringCampaignRuntimeError(
            f"{field} must be a plain bounded identity"
        )
    return value


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(_json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
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


def _relative_file(root: Path, path: Path, field: str) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise EngineeringCampaignRuntimeError(
            f"{field} escapes campaign root"
        ) from exc
    if len(relative.parts) < 2 or any(part in {"", ".", ".."} for part in relative.parts):
        raise EngineeringCampaignRuntimeError(
            f"{field} must be inside a namespaced mission directory"
        )
    return relative.as_posix()


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    sealed = deepcopy(dict(value))
    sealed[field] = "0" * SHA256_LENGTH
    sealed[field] = canonical_sha256(sealed)
    return sealed


def build_engineering_campaign_runtime_binding(
    *,
    campaign_root: Path,
    campaign_id: str,
    contract_path: Path,
    mission_roots: Sequence[Path],
    request_name: str = "request.json",
) -> dict[str, Any]:
    """Build one immutable binding for exactly 25 already-prepared missions."""

    root = Path(campaign_root)
    if not root.is_dir():
        raise EngineeringCampaignRuntimeError("campaign root must already exist")
    campaign = _identity(campaign_id, "campaign_id")
    if (
        not isinstance(mission_roots, Sequence)
        or isinstance(mission_roots, (str, bytes))
        or len(mission_roots) != CAMPAIGN_SIZE
    ):
        raise EngineeringCampaignRuntimeError(
            f"campaign requires exactly {CAMPAIGN_SIZE} mission roots"
        )
    if Path(request_name).name != request_name or not request_name:
        raise EngineeringCampaignRuntimeError("request_name must be a root filename")
    contract_path = Path(contract_path)
    contract = load_runtime_contract(contract_path)
    contract_raw_sha256 = file_sha256(contract_path)
    entries: list[dict[str, Any]] = []
    sessions: set[str] = set()
    jobs: set[str] = set()
    payloads: set[str] = set()
    relative_roots: set[str] = set()
    for sequence, raw_mission_root in enumerate(mission_roots, start=1):
        mission_root = Path(raw_mission_root)
        if not mission_root.is_dir():
            raise EngineeringCampaignRuntimeError("mission root is missing")
        relative_root = _relative_file(root, mission_root, "mission_root")
        if relative_root in relative_roots:
            raise EngineeringCampaignRuntimeError("mission roots must be unique")
        relative_roots.add(relative_root)
        binding_path = mission_root / "binding.json"
        request_path = mission_root / request_name
        if not binding_path.is_file() or not request_path.is_file():
            raise EngineeringCampaignRuntimeError(
                "mission binding or request is missing"
            )
        binding = validate_binding(read_json(binding_path))
        request = read_json(request_path)
        validate_request(contract, request)
        request_sha256 = file_sha256(request_path)
        if binding["input_sha256"].get(request_name) != request_sha256:
            raise EngineeringCampaignRuntimeError(
                "mission request is not bound by exact SHA-256"
            )
        if binding["runtime_sha256"] != contract["contract_sha256"]:
            raise EngineeringCampaignRuntimeError(
                "mission runtime binding differs from campaign runtime"
            )
        if binding["model_tree_sha256"] != contract["model"]["tree_sha256"]:
            raise EngineeringCampaignRuntimeError(
                "mission model tree differs from campaign runtime"
            )
        sessions.add(binding["session_id"])
        if binding["job_id"] in jobs or binding["payload_sha256"] in payloads:
            raise EngineeringCampaignRuntimeError(
                "mission job and payload identities must be unique"
            )
        jobs.add(binding["job_id"])
        payloads.add(binding["payload_sha256"])
        entries.append(
            {
                "sequence": sequence,
                "mission_root": relative_root,
                "session_id": binding["session_id"],
                "job_id": binding["job_id"],
                "payload_sha256": binding["payload_sha256"],
                "binding_sha256": binding["binding_sha256"],
                "binding_file_sha256": file_sha256(binding_path),
                "request_file": request_name,
                "request_sha256": request_sha256,
            }
        )
    if len(sessions) != 1:
        raise EngineeringCampaignRuntimeError(
            "all campaign missions must use one session"
        )
    value = {
        "schema_version": BINDING_SCHEMA,
        "campaign_id": campaign,
        "session_id": next(iter(sessions)),
        "mission_count": CAMPAIGN_SIZE,
        "runtime_contract_sha256": contract["contract_sha256"],
        "runtime_contract_file_sha256": contract_raw_sha256,
        "model_tree_sha256": contract["model"]["tree_sha256"],
        "mission_entries": entries,
        "authority": AUTHORITY,
        "binding_sha256": "0" * SHA256_LENGTH,
    }
    sealed = _seal(value, "binding_sha256")
    output = root / BINDING_NAME
    if output.exists():
        existing = validate_engineering_campaign_runtime_binding(
            output,
            campaign_root=root,
            contract_path=contract_path,
            require_guard_binding=False,
        )
        if existing != sealed:
            raise EngineeringCampaignRuntimeError(
                "existing campaign runtime binding conflicts"
            )
        sealed = existing
    else:
        _write_exclusive_json(output, sealed)
    guard_binding = seal_binding(
        {
            "schema_version": MISSION_BINDING_SCHEMA,
            "session_id": sealed["session_id"],
            "job_id": sealed["campaign_id"],
            "payload_sha256": sealed["binding_sha256"],
            "model_tree_sha256": sealed["model_tree_sha256"],
            "runtime_sha256": sealed["runtime_contract_sha256"],
            "input_sha256": {BINDING_NAME: file_sha256(output)},
            "output_namespace": (
                f"{sealed['session_id']}/{sealed['campaign_id']}"
            ),
            "requires_replay": False,
            "authority": {key: False for key in sorted(AUTHORITY_KEYS)},
        }
    )
    guard_path = root / "binding.json"
    if guard_path.exists():
        if validate_binding(read_json(guard_path)) != guard_binding:
            raise EngineeringCampaignRuntimeError(
                "existing campaign GPU guard binding conflicts"
            )
    else:
        _write_exclusive_json(guard_path, guard_binding)
    return validate_engineering_campaign_runtime_binding(
        output, campaign_root=root, contract_path=contract_path
    )


def validate_engineering_campaign_runtime_binding(
    binding_path: Path,
    *,
    campaign_root: Path,
    contract_path: Path,
    require_guard_binding: bool = True,
) -> dict[str, Any]:
    """Replay every campaign, runtime, mission, and request binding."""

    root = Path(campaign_root)
    binding = read_json(Path(binding_path))
    required = {
        "schema_version",
        "campaign_id",
        "session_id",
        "mission_count",
        "runtime_contract_sha256",
        "runtime_contract_file_sha256",
        "model_tree_sha256",
        "mission_entries",
        "authority",
        "binding_sha256",
    }
    if set(binding) != required or binding["schema_version"] != BINDING_SCHEMA:
        raise EngineeringCampaignRuntimeError(
            "campaign runtime binding field or schema mismatch"
        )
    declared = _sha256(binding["binding_sha256"], "binding_sha256")
    zeroed = deepcopy(binding)
    zeroed["binding_sha256"] = "0" * SHA256_LENGTH
    if canonical_sha256(zeroed) != declared:
        raise EngineeringCampaignRuntimeError(
            "campaign runtime binding self-hash mismatch"
        )
    _identity(binding["campaign_id"], "campaign_id")
    session = _identity(binding["session_id"], "session_id")
    if binding["mission_count"] != CAMPAIGN_SIZE:
        raise EngineeringCampaignRuntimeError("campaign mission count mismatch")
    if binding["authority"] != AUTHORITY:
        raise EngineeringCampaignRuntimeError("campaign authority ceiling mismatch")
    contract = load_runtime_contract(Path(contract_path))
    if (
        binding["runtime_contract_sha256"] != contract["contract_sha256"]
        or binding["runtime_contract_file_sha256"] != file_sha256(Path(contract_path))
        or binding["model_tree_sha256"] != contract["model"]["tree_sha256"]
    ):
        raise EngineeringCampaignRuntimeError("campaign runtime contract drift")
    entries = binding["mission_entries"]
    if not isinstance(entries, list) or len(entries) != CAMPAIGN_SIZE:
        raise EngineeringCampaignRuntimeError(
            "campaign requires exactly 25 mission entries"
        )
    jobs: set[str] = set()
    payloads: set[str] = set()
    roots: set[str] = set()
    for expected_sequence, entry in enumerate(entries, start=1):
        expected_keys = {
            "sequence",
            "mission_root",
            "session_id",
            "job_id",
            "payload_sha256",
            "binding_sha256",
            "binding_file_sha256",
            "request_file",
            "request_sha256",
        }
        if not isinstance(entry, dict) or set(entry) != expected_keys:
            raise EngineeringCampaignRuntimeError("mission entry field mismatch")
        if entry["sequence"] != expected_sequence or entry["session_id"] != session:
            raise EngineeringCampaignRuntimeError(
                "mission sequence or session mismatch"
            )
        relative = Path(entry["mission_root"])
        if (
            relative.is_absolute()
            or len(relative.parts) < 2
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise EngineeringCampaignRuntimeError("mission root is not namespaced")
        mission_root = (root / relative).resolve()
        try:
            mission_root.relative_to(root.resolve())
        except ValueError as exc:
            raise EngineeringCampaignRuntimeError("mission root escapes campaign") from exc
        request_name = entry["request_file"]
        if Path(request_name).name != request_name or not request_name:
            raise EngineeringCampaignRuntimeError(
                "mission request must be a root filename"
            )
        try:
            mission_binding = validate_binding(
                read_json(mission_root / "binding.json")
            )
            request_path = mission_root / request_name
            request = read_json(request_path)
            validate_request(contract, request)
        except (MissionBindingError, MissionConflictError, OSError) as exc:
            raise EngineeringCampaignRuntimeError(
                "mission entry binding drift"
            ) from exc
        if (
            entry["job_id"] != mission_binding["job_id"]
            or entry["payload_sha256"] != mission_binding["payload_sha256"]
            or entry["binding_sha256"] != mission_binding["binding_sha256"]
            or entry["binding_file_sha256"]
            != file_sha256(mission_root / "binding.json")
            or entry["request_sha256"] != file_sha256(request_path)
            or mission_binding["input_sha256"].get(request_name)
            != entry["request_sha256"]
            or mission_binding["runtime_sha256"] != contract["contract_sha256"]
            or mission_binding["model_tree_sha256"]
            != contract["model"]["tree_sha256"]
        ):
            raise EngineeringCampaignRuntimeError("mission entry binding drift")
        if (
            entry["job_id"] in jobs
            or entry["payload_sha256"] in payloads
            or entry["mission_root"] in roots
        ):
            raise EngineeringCampaignRuntimeError(
                "mission identities or roots are duplicated"
            )
        jobs.add(entry["job_id"])
        payloads.add(entry["payload_sha256"])
        roots.add(entry["mission_root"])
    if require_guard_binding:
        guard_path = root / "binding.json"
        if not guard_path.is_file():
            raise EngineeringCampaignRuntimeError(
                "campaign GPU guard binding is missing"
            )
        guard = validate_binding(read_json(guard_path))
        if (
            guard["session_id"] != binding["session_id"]
            or guard["job_id"] != binding["campaign_id"]
            or guard["payload_sha256"] != binding["binding_sha256"]
            or guard["model_tree_sha256"] != binding["model_tree_sha256"]
            or guard["runtime_sha256"] != binding["runtime_contract_sha256"]
            or guard["input_sha256"] != {BINDING_NAME: file_sha256(binding_path)}
            or guard["requires_replay"] is not False
            or any(guard["authority"].values())
        ):
            raise EngineeringCampaignRuntimeError(
                "campaign GPU guard binding mismatch"
            )
    return binding


class EngineeringCampaignRuntimeController:
    """Execute exactly 25 steward requests under one owned vLLM lifetime."""

    def __init__(
        self,
        *,
        contract_path: Path,
        campaign_root: Path,
        database: Path,
        port: int | None = None,
        controller_factory: Callable[..., StewardRuntimeController] = (
            StewardRuntimeController
        ),
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.campaign_root = Path(campaign_root)
        self.database = Path(database)
        self.contract = load_runtime_contract(self.contract_path)
        self.port = (
            self.contract["server"]["default_port"] if port is None else int(port)
        )
        self.controller_factory = controller_factory
        self.clock = clock
        self.binding = validate_engineering_campaign_runtime_binding(
            self.campaign_root / BINDING_NAME,
            campaign_root=self.campaign_root,
            contract_path=self.contract_path,
        )
        self.terminal_path = self.campaign_root / TERMINAL_NAME
        self.state_path = self.campaign_root / STATE_NAME

    def _controller(self, entry: Mapping[str, Any]) -> StewardRuntimeController:
        return self.controller_factory(
            contract_path=self.contract_path,
            mission_root=self.campaign_root / entry["mission_root"],
            database=self.database,
            port=self.port,
        )

    @staticmethod
    def _owned_process_alive(launch: Mapping[str, Any]) -> bool:
        from .core import StewardLedger

        return StewardLedger.owner_process_alive(
            int(launch["pid"]), str(launch["owner_start_token"])
        )

    def _service_healthy(
        self, controller: StewardRuntimeController
    ) -> bool:
        try:
            controller.health()
        except (MissionBindingError, MissionConflictError, OSError):
            return False
        return True

    def _state(
        self,
        *,
        owner_job_id: str | None,
        member_job_ids: Sequence[str],
        completed_count: int,
    ) -> None:
        _replace_json(
            self.state_path,
            {
                "schema_version": "maskfactory.engineering_campaign_runtime_state.v1",
                "campaign_id": self.binding["campaign_id"],
                "binding_sha256": self.binding["binding_sha256"],
                "owner_job_id": owner_job_id,
                "member_job_ids": list(member_job_ids),
                "completed_count": completed_count,
                "updated_at": self.clock(),
            },
        )

    def _attach(
        self,
        controller: StewardRuntimeController,
        *,
        owner_controller: StewardRuntimeController,
    ) -> dict[str, Any]:
        binding = validate_binding(read_json(controller.binding_path))
        owner_launch = read_json(owner_controller.launch_receipt_path)
        if not self._service_healthy(owner_controller):
            raise EngineeringCampaignRuntimeError(
                "shared owned runtime is unavailable during attachment"
            )
        admitted = controller.ledger.admit(binding)
        mission = admitted["mission"]
        if admitted["outcome"] == "admitted":
            pass
        elif (
            admitted["outcome"] == "duplicate_nonterminal"
            and mission["state"] == "admitted"
        ):
            pass
        else:
            raise EngineeringCampaignRuntimeError(
                f"mission attachment refused for {admitted['outcome']}"
            )
        receipt: dict[str, Any] = {
            "schema_version": LAUNCH_RECEIPT_SCHEMA,
            "session_id": binding["session_id"],
            "job_id": binding["job_id"],
            "binding_sha256": binding["binding_sha256"],
            "runtime_contract_sha256": self.contract["contract_sha256"],
            "pid": owner_launch["pid"],
            "process_group_id": owner_launch["process_group_id"],
            "owner_start_token": owner_launch["owner_start_token"],
            "port": owner_launch["port"],
            "comfyui_queue_state": owner_launch["comfyui_queue_state"],
            "command_sha256": owner_launch["command_sha256"],
            "created_at": self.clock(),
            "shared_runtime_owner_job_id": owner_launch["job_id"],
            "owner_launch_receipt_sha256": file_sha256(
                owner_controller.launch_receipt_path
            ),
        }
        if controller.launch_receipt_path.exists():
            existing = read_json(controller.launch_receipt_path)
            stable_fields = set(receipt) - {"created_at"}
            if any(existing.get(field) != receipt[field] for field in stable_fields):
                raise EngineeringCampaignRuntimeError(
                    "existing shared launch receipt conflicts"
                )
            receipt = existing
        else:
            _write_exclusive_json(controller.launch_receipt_path, receipt)
        controller.ledger.mark_running(
            binding["session_id"],
            binding["job_id"],
            owner_pid=int(owner_launch["pid"]),
            owner_start_token=str(owner_launch["owner_start_token"]),
        )
        return receipt

    def _terminalize_failure(
        self,
        controller: StewardRuntimeController,
        *,
        reason_code: str,
        detail: str,
    ) -> dict[str, Any]:
        binding = validate_binding(read_json(controller.binding_path))
        mission = controller.ledger.get(binding["session_id"], binding["job_id"])
        if mission is None:
            admitted = controller.ledger.admit(binding)
            mission = admitted["mission"]
        if controller.terminal_receipt_path.exists():
            terminal = read_json(controller.terminal_receipt_path)
            controller.ledger.reconcile_recorded_owner(
                binding["session_id"],
                binding["job_id"],
                terminal_receipt=terminal,
            )
            return terminal
        failure = {
            "schema_version": FAILURE_SCHEMA,
            "session_id": binding["session_id"],
            "job_id": binding["job_id"],
            "binding_sha256": binding["binding_sha256"],
            "request_sha256": mission.get("request_sha256") if mission else None,
            "reason_code": reason_code,
            "detail": detail[:1000],
            "retry_permitted": False,
            "authority_claimed": False,
            "created_at": self.clock(),
        }
        failure_path = controller.mission_root / "campaign_failure_receipt.json"
        if failure_path.exists():
            existing = read_json(failure_path)
            if (
                existing.get("binding_sha256") != binding["binding_sha256"]
                or existing.get("reason_code") != reason_code
                or existing.get("retry_permitted") is not False
            ):
                raise EngineeringCampaignRuntimeError(
                    "existing mission failure receipt conflicts"
                )
            failure = existing
        else:
            _write_exclusive_json(failure_path, failure)
        terminal = {
            "schema_version": TERMINAL_RECEIPT_SCHEMA,
            "session_id": binding["session_id"],
            "job_id": binding["job_id"],
            "payload_sha256": binding["payload_sha256"],
            "binding_sha256": binding["binding_sha256"],
            "state": "failed",
            "proposal_canonical_sha256": canonical_sha256(failure),
            "authority_claimed": False,
        }
        _write_exclusive_json(controller.terminal_receipt_path, terminal)
        controller.ledger.reconcile_recorded_owner(
            binding["session_id"],
            binding["job_id"],
            terminal_receipt=terminal,
        )
        return terminal

    @staticmethod
    def _port_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            return False

    def _release_attached(
        self,
        controller: StewardRuntimeController,
        *,
        owner_controller: StewardRuntimeController,
        owner_shutdown: Mapping[str, Any],
    ) -> dict[str, Any]:
        binding = validate_binding(read_json(controller.binding_path))
        if controller.mission_root == owner_controller.mission_root:
            return read_json(controller.shutdown_receipt_path)
        if self._owned_process_alive(owner_shutdown):
            raise EngineeringCampaignRuntimeError(
                "shared owner process remains alive at attached release"
            )
        owner_launch = read_json(owner_controller.launch_receipt_path)
        if self._port_open(
            self.contract["server"]["host"], int(owner_launch["port"])
        ):
            raise EngineeringCampaignRuntimeError(
                "shared runtime port remains open at attached release"
            )
        receipt: dict[str, Any] = {
            "schema_version": SHUTDOWN_RECEIPT_SCHEMA,
            "session_id": binding["session_id"],
            "job_id": binding["job_id"],
            "pid": owner_shutdown["pid"],
            "owner_start_token": owner_shutdown["owner_start_token"],
            "process_group_id": owner_shutdown["process_group_id"],
            "owned_process_absent": True,
            "loopback_port_closed": True,
            "forced": owner_shutdown["forced"],
            "created_at": self.clock(),
            "shared_runtime_owner_job_id": read_json(
                owner_controller.binding_path
            )["job_id"],
            "owner_shutdown_sha256": file_sha256(
                owner_controller.shutdown_receipt_path
            ),
        }
        if controller.shutdown_receipt_path.exists():
            existing = read_json(controller.shutdown_receipt_path)
            stable_fields = set(receipt) - {"created_at"}
            if any(existing.get(field) != receipt[field] for field in stable_fields):
                raise EngineeringCampaignRuntimeError(
                    "existing attached shutdown receipt conflicts"
                )
            receipt = existing
        else:
            _write_exclusive_json(controller.shutdown_receipt_path, receipt)
        release_sha256 = file_sha256(controller.shutdown_receipt_path)
        released = controller.ledger.record_release(
            binding["session_id"],
            binding["job_id"],
            release_kind="direct_process_exit",
            release_sha256=release_sha256,
        )
        receipt["release_sha256"] = released["release_sha256"]
        receipt["handoff_ready"] = controller.ledger.handoff_ready(
            binding["session_id"], binding["job_id"]
        )
        return receipt

    def _release_without_owned_process(
        self, controller: StewardRuntimeController
    ) -> dict[str, Any]:
        binding = validate_binding(read_json(controller.binding_path))
        mission = controller.ledger.get(binding["session_id"], binding["job_id"])
        if mission is None or mission["state"] not in {"completed", "failed"}:
            raise EngineeringCampaignRuntimeError(
                "no-process release requires a terminal mission"
            )
        if mission["release_sha256"] is not None:
            return {
                "release_sha256": mission["release_sha256"],
                "handoff_ready": controller.ledger.handoff_ready(
                    binding["session_id"], binding["job_id"]
                ),
            }
        launch = (
            read_json(controller.launch_receipt_path)
            if controller.launch_receipt_path.is_file()
            else None
        )
        if launch is not None:
            if self._owned_process_alive(launch):
                raise EngineeringCampaignRuntimeError(
                    "recorded mission process is still alive"
                )
            if self._port_open(
                self.contract["server"]["host"], int(launch["port"])
            ):
                raise EngineeringCampaignRuntimeError(
                    "recorded mission loopback port is still open"
                )
        receipt: dict[str, Any] = {
            "schema_version": NO_PROCESS_RELEASE_SCHEMA,
            "session_id": binding["session_id"],
            "job_id": binding["job_id"],
            "binding_sha256": binding["binding_sha256"],
            "process_was_started": launch is not None,
            "pid": launch["pid"] if launch is not None else None,
            "owner_start_token": (
                launch["owner_start_token"] if launch is not None else None
            ),
            "owned_process_absent": True,
            "loopback_port_closed": True,
            "authority_claimed": False,
            "created_at": self.clock(),
        }
        if controller.shutdown_receipt_path.exists():
            existing = read_json(controller.shutdown_receipt_path)
            stable_fields = set(receipt) - {"created_at"}
            if any(existing.get(field) != receipt[field] for field in stable_fields):
                raise EngineeringCampaignRuntimeError(
                    "existing no-process release receipt conflicts"
                )
            receipt = existing
        else:
            _write_exclusive_json(controller.shutdown_receipt_path, receipt)
        released = controller.ledger.record_release(
            binding["session_id"],
            binding["job_id"],
            release_kind="direct_process_exit",
            release_sha256=file_sha256(controller.shutdown_receipt_path),
        )
        receipt["release_sha256"] = released["release_sha256"]
        receipt["handoff_ready"] = controller.ledger.handoff_ready(
            binding["session_id"], binding["job_id"]
        )
        return receipt

    def _outcome(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        controller = self._controller(entry)
        binding = validate_binding(read_json(controller.binding_path))
        mission = controller.ledger.get(binding["session_id"], binding["job_id"])
        if mission is None or not controller.terminal_receipt_path.is_file():
            raise EngineeringCampaignRuntimeError("mission terminal evidence is missing")
        terminal = read_json(controller.terminal_receipt_path)
        return {
            "sequence": entry["sequence"],
            "job_id": entry["job_id"],
            "request_sha256": entry["request_sha256"],
            "state": terminal["state"],
            "terminal_receipt_sha256": file_sha256(
                controller.terminal_receipt_path
            ),
            "submission_receipt_sha256": (
                file_sha256(controller.mission_root / "submission_receipt.json")
                if (controller.mission_root / "submission_receipt.json").is_file()
                else None
            ),
            "release_sha256": mission["release_sha256"],
            "handoff_ready": controller.ledger.handoff_ready(
                binding["session_id"], binding["job_id"]
            ),
        }

    def _seal_terminal(self, service_generations: int) -> dict[str, Any]:
        outcomes = [self._outcome(entry) for entry in self.binding["mission_entries"]]
        if not all(outcome["handoff_ready"] for outcome in outcomes):
            raise EngineeringCampaignRuntimeError(
                "campaign cannot seal before every mission release"
            )
        passed = all(
            outcome["state"] == "completed" and outcome["handoff_ready"]
            for outcome in outcomes
        )
        value = {
            "schema_version": TERMINAL_SCHEMA,
            "campaign_id": self.binding["campaign_id"],
            "binding_sha256": self.binding["binding_sha256"],
            "mission_count": CAMPAIGN_SIZE,
            "completed_count": sum(
                outcome["state"] == "completed" for outcome in outcomes
            ),
            "failed_count": sum(outcome["state"] == "failed" for outcome in outcomes),
            "service_generation_count": service_generations,
            "outcome": "SUCCESS" if passed else "FAILED_CLOSED",
            "mission_outcomes": outcomes,
            "authority_claimed": False,
            "completion_claimed": False,
            "terminal_sha256": "0" * SHA256_LENGTH,
        }
        terminal = _seal(value, "terminal_sha256")
        if self.terminal_path.exists():
            existing = validate_engineering_campaign_runtime_terminal(
                self.terminal_path,
                campaign_root=self.campaign_root,
                contract_path=self.contract_path,
                database=self.database,
            )
            if existing != terminal:
                raise EngineeringCampaignRuntimeError(
                    "existing campaign terminal conflicts"
                )
            return existing
        _write_exclusive_json(self.terminal_path, terminal)
        return validate_engineering_campaign_runtime_terminal(
            self.terminal_path,
            campaign_root=self.campaign_root,
            contract_path=self.contract_path,
            database=self.database,
        )

    def run(self) -> dict[str, Any]:
        """Run or replay one bounded campaign without duplicate inference."""

        if self.terminal_path.exists():
            return validate_engineering_campaign_runtime_terminal(
                self.terminal_path,
                campaign_root=self.campaign_root,
                contract_path=self.contract_path,
                database=self.database,
            )
        owner: StewardRuntimeController | None = None
        members: list[StewardRuntimeController] = []
        launch_failed = False
        service_generations = 0
        for entry in self.binding["mission_entries"]:
            launch_path = (
                self.campaign_root
                / entry["mission_root"]
                / "runtime_launch_receipt.json"
            )
            if launch_path.is_file():
                launch = read_json(launch_path)
                if "shared_runtime_owner_job_id" not in launch:
                    service_generations += 1

        def close_service() -> None:
            nonlocal owner, members
            if owner is None:
                return
            for member in members:
                binding = validate_binding(read_json(member.binding_path))
                mission = member.ledger.get(binding["session_id"], binding["job_id"])
                if mission is None or mission["state"] not in {"completed", "failed"}:
                    self._terminalize_failure(
                        member,
                        reason_code="runtime_ended_before_terminal",
                        detail="owned shared runtime ended before mission terminal",
                    )
            shutdown = owner.shutdown()
            for member in members:
                self._release_attached(
                    member,
                    owner_controller=owner,
                    owner_shutdown=shutdown,
                )
            owner = None
            members = []

        try:
            for entry in self.binding["mission_entries"]:
                controller = self._controller(entry)
                binding = validate_binding(read_json(controller.binding_path))
                mission = controller.ledger.get(
                    binding["session_id"], binding["job_id"]
                )
                if controller.terminal_receipt_path.exists():
                    terminal = read_json(controller.terminal_receipt_path)
                    controller.ledger.reconcile_recorded_owner(
                        binding["session_id"],
                        binding["job_id"],
                        terminal_receipt=terminal,
                    )
                    if (
                        owner is None
                        and controller.launch_receipt_path.is_file()
                    ):
                        launch = read_json(controller.launch_receipt_path)
                        if (
                            "shared_runtime_owner_job_id" not in launch
                            and self._owned_process_alive(launch)
                            and self._service_healthy(controller)
                        ):
                            owner = controller
                            members = [controller]
                    elif (
                        owner is not None
                        and controller.launch_receipt_path.is_file()
                    ):
                        launch = read_json(controller.launch_receipt_path)
                        owner_binding = read_json(owner.binding_path)
                        owner_launch = read_json(owner.launch_receipt_path)
                        if (
                            launch.get("shared_runtime_owner_job_id")
                            == owner_binding["job_id"]
                            and launch.get("pid") == owner_launch["pid"]
                            and controller not in members
                        ):
                            members.append(controller)
                    continue
                if launch_failed:
                    self._terminalize_failure(
                        controller,
                        reason_code="runtime_unavailable_after_launch_failure",
                        detail=(
                            "campaign runtime launch already failed; the unchanged "
                            "launch was not retried"
                        ),
                    )
                    continue
                if owner is not None and not self._service_healthy(owner):
                    close_service()
                if mission is not None and mission["state"] == "running":
                    if mission["request_sha256"] is not None:
                        if (
                            owner is None
                            and controller.launch_receipt_path.is_file()
                        ):
                            launch = read_json(controller.launch_receipt_path)
                            if self._owned_process_alive(
                                launch
                            ) and self._service_healthy(controller):
                                owner = controller
                                members = [controller]
                        self._terminalize_failure(
                            controller,
                            reason_code="ambiguous_request_intent",
                            detail=(
                                "durable request intent exists without terminal "
                                "response; immutable request was not reissued"
                            ),
                        )
                        continue
                    if not controller.launch_receipt_path.is_file():
                        self._terminalize_failure(
                            controller,
                            reason_code="running_without_launch_receipt",
                            detail="ledger owner lacks immutable launch evidence",
                        )
                        continue
                    if owner is None:
                        launch = read_json(controller.launch_receipt_path)
                        if self._owned_process_alive(launch) and self._service_healthy(
                            controller
                        ):
                            owner = controller
                            members = [controller]
                        else:
                            self._terminalize_failure(
                                controller,
                                reason_code="stale_runtime_owner",
                                detail=(
                                    "recorded runtime owner is absent; no request "
                                    "intent was reissued"
                                ),
                            )
                            continue
                    elif controller not in members:
                        launch = read_json(controller.launch_receipt_path)
                        owner_binding = read_json(owner.binding_path)
                        owner_launch = read_json(owner.launch_receipt_path)
                        if (
                            launch.get("shared_runtime_owner_job_id")
                            != owner_binding["job_id"]
                            or launch.get("pid") != owner_launch["pid"]
                            or not self._service_healthy(owner)
                        ):
                            self._terminalize_failure(
                                controller,
                                reason_code="shared_runtime_owner_mismatch",
                                detail=(
                                    "running mission does not match the live "
                                    "campaign runtime owner"
                                ),
                            )
                            continue
                        members.append(controller)
                if owner is None:
                    try:
                        controller.launch()
                    except Exception as exc:
                        self._terminalize_failure(
                            controller,
                            reason_code="runtime_launch_failed",
                            detail=f"{type(exc).__name__}: {exc}",
                        )
                        launch_failed = True
                        continue
                    owner = controller
                    members = [controller]
                    service_generations += 1
                elif controller not in members:
                    try:
                        self._attach(controller, owner_controller=owner)
                    except Exception as exc:
                        self._terminalize_failure(
                            controller,
                            reason_code="shared_runtime_attach_failed",
                            detail=f"{type(exc).__name__}: {exc}",
                        )
                        continue
                    members.append(controller)
                self._state(
                    owner_job_id=read_json(owner.binding_path)["job_id"],
                    member_job_ids=[
                        read_json(member.binding_path)["job_id"] for member in members
                    ],
                    completed_count=sum(
                        (self.campaign_root / item["mission_root"] / "terminal_receipt.json").is_file()
                        for item in self.binding["mission_entries"]
                    ),
                )
                try:
                    controller.submit(
                        controller.mission_root / entry["request_file"]
                    )
                except AmbiguousMissionError as exc:
                    self._terminalize_failure(
                        controller,
                        reason_code="ambiguous_request_completion",
                        detail=str(exc),
                    )
                except Exception as exc:
                    self._terminalize_failure(
                        controller,
                        reason_code="mission_submission_failed",
                        detail=f"{type(exc).__name__}: {exc}",
                    )
            close_service()
        finally:
            if owner is not None:
                close_service()
        for entry in self.binding["mission_entries"]:
            controller = self._controller(entry)
            binding = validate_binding(read_json(controller.binding_path))
            mission = controller.ledger.get(binding["session_id"], binding["job_id"])
            if (
                mission is not None
                and mission["state"] in {"completed", "failed"}
                and mission["release_sha256"] is None
            ):
                self._release_without_owned_process(controller)
        self._state(
            owner_job_id=None,
            member_job_ids=[],
            completed_count=sum(
                (self.campaign_root / entry["mission_root"] / "terminal_receipt.json").is_file()
                for entry in self.binding["mission_entries"]
            ),
        )
        return self._seal_terminal(service_generations)


def validate_engineering_campaign_runtime_terminal(
    terminal_path: Path,
    *,
    campaign_root: Path,
    contract_path: Path,
    database: Path,
) -> dict[str, Any]:
    """Replay the terminal campaign against all mission and release evidence."""

    root = Path(campaign_root)
    binding = validate_engineering_campaign_runtime_binding(
        root / BINDING_NAME,
        campaign_root=root,
        contract_path=Path(contract_path),
    )
    terminal = read_json(Path(terminal_path))
    required = {
        "schema_version",
        "campaign_id",
        "binding_sha256",
        "mission_count",
        "completed_count",
        "failed_count",
        "service_generation_count",
        "outcome",
        "mission_outcomes",
        "authority_claimed",
        "completion_claimed",
        "terminal_sha256",
    }
    if set(terminal) != required or terminal["schema_version"] != TERMINAL_SCHEMA:
        raise EngineeringCampaignRuntimeError("campaign terminal schema mismatch")
    declared = _sha256(terminal["terminal_sha256"], "terminal_sha256")
    zeroed = deepcopy(terminal)
    zeroed["terminal_sha256"] = "0" * SHA256_LENGTH
    if canonical_sha256(zeroed) != declared:
        raise EngineeringCampaignRuntimeError("campaign terminal self-hash mismatch")
    if (
        terminal["campaign_id"] != binding["campaign_id"]
        or terminal["binding_sha256"] != binding["binding_sha256"]
        or terminal["mission_count"] != CAMPAIGN_SIZE
        or terminal["authority_claimed"] is not False
        or terminal["completion_claimed"] is not False
        or not isinstance(terminal["service_generation_count"], int)
        or terminal["service_generation_count"] < 0
    ):
        raise EngineeringCampaignRuntimeError("campaign terminal binding mismatch")
    replay = EngineeringCampaignRuntimeController(
        contract_path=contract_path,
        campaign_root=root,
        database=database,
    )
    observed = [replay._outcome(entry) for entry in binding["mission_entries"]]
    if observed != terminal["mission_outcomes"]:
        raise EngineeringCampaignRuntimeError(
            "campaign mission terminal replay mismatch"
        )
    completed = sum(row["state"] == "completed" for row in observed)
    failed = sum(row["state"] == "failed" for row in observed)
    passed = all(
        row["state"] == "completed" and row["handoff_ready"] for row in observed
    )
    if (
        terminal["completed_count"] != completed
        or terminal["failed_count"] != failed
        or completed + failed != CAMPAIGN_SIZE
        or not all(row["handoff_ready"] for row in observed)
        or terminal["outcome"] != ("SUCCESS" if passed else "FAILED_CLOSED")
    ):
        raise EngineeringCampaignRuntimeError(
            "campaign terminal accounting mismatch"
        )
    return terminal


__all__ = [
    "BINDING_NAME",
    "BINDING_SCHEMA",
    "CAMPAIGN_SIZE",
    "EngineeringCampaignRuntimeController",
    "EngineeringCampaignRuntimeError",
    "TERMINAL_NAME",
    "TERMINAL_SCHEMA",
    "build_engineering_campaign_runtime_binding",
    "validate_engineering_campaign_runtime_binding",
    "validate_engineering_campaign_runtime_terminal",
]
