#!/usr/bin/env python3
"""Run one MaskFactory GPU command only while owning the shared Pod lease."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import signal
import shutil
import socket
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


SESSION_ID = "019f91d1-ea20-7d81-83ff-03d393eaa1f5"
DEFAULT_DATABASE = Path(
    "/workspace/.maskfactory/shared_pod_coordination/shared_gpu_leases_v1.sqlite"
)
DEFAULT_MANAGER = Path(
    "/workspace/.maskfactory/shared_pod_coordination/tools/"
    "manage_shared_pod_gpu_lease_v2.py"
)
EXPECTED_MANAGER_SHA256 = (
    "5f98839d8b0c7fd0a384a88e421088506dbb3ddd7546b7271dc5974f94e7e4c3"
)
FALLBACK_REQUIRED = 75
COORDINATION_FAILURE = 70
CHILD_TIMEOUT = 124
EXPECTED_POD_ID = "68psfqtaogg7s7"
EXPECTED_POD_NAME = "vitreous_beige_centipede"
EXPECTED_GPU = "NVIDIA RTX 6000 Ada Generation"
EXPECTED_NETWORK_VOLUME_ID = "o9qv2ld91c"
EXPECTED_WORKSPACE = Path("/workspace")
ALLOWED_ARTIFACT_ROOT = Path("/workspace/maskfactory/runtime_artifacts")
RELEASE_RECEIPT_NAME = "local_gpu_lease_release.json"
MIN_WORKSPACE_FREE_BYTES = 1024 * 1024 * 1024


class GuardError(RuntimeError):
    """Raised when a local GPU command cannot be admitted safely."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def atomic_sealed_json(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    """Persist one immutable zero-self-hashed receipt with fsync."""
    sealed = copy.deepcopy(value)
    sealed["self_sha256"] = "0" * 64
    sealed["self_sha256"] = canonical_sha256(sealed)
    body = (
        json.dumps(sealed, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return sealed


def load_closed_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuardError(f"required JSON is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise GuardError(f"required JSON is not an object: {path}")
    return value


def validate_sha256(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise GuardError(f"{field} must be lowercase SHA-256")
    return value


def probe_comfyui_queue() -> dict[str, Any]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=1) as response:
            queue = json.load(response)
    except urllib.error.URLError:
        with socket.socket() as connection:
            connection.settimeout(0.5)
            if connection.connect_ex(("127.0.0.1", 8188)) == 0:
                raise GuardError("ComfyUI queue endpoint is open but unreadable")
        return {"state": "unavailable", "running": 0, "pending": 0}
    try:
        running = len(queue["queue_running"])
        pending = len(queue["queue_pending"])
    except (KeyError, TypeError) as exc:
        raise GuardError("ComfyUI queue response is malformed") from exc
    if running or pending:
        raise GuardError("ComfyUI queue is not empty")
    return {"state": "empty", "running": running, "pending": pending}


def query_gpu_inventory() -> list[str]:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def query_workspace_mount() -> dict[str, Any]:
    result = subprocess.run(
        ["findmnt", "-J", "-T", str(EXPECTED_WORKSPACE)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        filesystems = json.loads(result.stdout)["filesystems"]
        mount = filesystems[0]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise GuardError("workspace mount telemetry is malformed") from exc
    return mount


def query_workspace_storage() -> dict[str, int]:
    """Return bounded shared-volume capacity telemetry or fail closed."""
    try:
        usage = shutil.disk_usage(EXPECTED_WORKSPACE)
    except OSError as exc:
        raise GuardError("workspace storage telemetry is unavailable") from exc
    if usage.free < MIN_WORKSPACE_FREE_BYTES:
        raise GuardError("workspace free space is below the local GPU floor")
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "minimum_free_bytes": MIN_WORKSPACE_FREE_BYTES,
    }


def run_local_admission_preflight(
    *,
    mission_root: Path,
    runtime_contract_path: Path,
    job_id: str,
    payload_sha256: str,
) -> dict[str, Any]:
    """Verify immutable job, runtime, model, GPU, queue, and shared storage."""
    mission_root = Path(mission_root).resolve()
    artifact_root = ALLOWED_ARTIFACT_ROOT.resolve()
    if artifact_root not in mission_root.parents or not mission_root.is_dir():
        raise GuardError("mission root is outside the approved artifact namespace")
    binding_path = mission_root / "binding.json"
    binding = load_closed_json(binding_path)
    observed_binding_hash = binding.get("binding_sha256")
    candidate = dict(binding)
    candidate["binding_sha256"] = "0" * 64
    if canonical_sha256(candidate) != observed_binding_hash:
        raise GuardError("mission binding self-hash mismatch")
    if binding.get("job_id") != job_id:
        raise GuardError("mission binding job identity mismatch")
    if binding.get("payload_sha256") != payload_sha256:
        raise GuardError("mission binding payload identity mismatch")
    if binding.get("authority") and any(binding["authority"].values()):
        raise GuardError("mission binding exceeds advisory authority")
    for name, expected in binding.get("input_sha256", {}).items():
        if Path(name).name != name:
            raise GuardError("mission binding input is not a root file")
        if file_sha256(mission_root / name) != validate_sha256(
            expected, f"input_sha256.{name}"
        ):
            raise GuardError(f"mission binding input drift: {name}")

    contract = load_closed_json(runtime_contract_path)
    observed_contract_hash = contract.get("contract_sha256")
    contract_candidate = json.loads(json.dumps(contract))
    contract_candidate["contract_sha256"] = "0" * 64
    if canonical_sha256(contract_candidate) != observed_contract_hash:
        raise GuardError("runtime contract self-hash mismatch")
    if binding.get("runtime_sha256") != observed_contract_hash:
        raise GuardError("mission runtime binding mismatch")
    pod = contract.get("pod", {})
    if (
        pod.get("id") != EXPECTED_POD_ID
        or pod.get("name") != EXPECTED_POD_NAME
        or pod.get("gpu") != EXPECTED_GPU
        or pod.get("gpu_count") != 1
        or pod.get("network_volume_id") != EXPECTED_NETWORK_VOLUME_ID
        or pod.get("mount") != str(EXPECTED_WORKSPACE)
    ):
        raise GuardError("runtime contract targets a different Pod")
    inventory = query_gpu_inventory()
    if inventory != [EXPECTED_GPU]:
        raise GuardError("live GPU inventory does not match the selected Pod")
    mount = query_workspace_mount()
    if (
        mount.get("target") != str(EXPECTED_WORKSPACE)
        or EXPECTED_NETWORK_VOLUME_ID not in str(mount.get("source", ""))
        or mount.get("fstype") != "fuse"
    ):
        raise GuardError("live workspace is not the selected network volume")
    storage = query_workspace_storage()
    model = contract.get("model", {})
    model_file_bytes = model.get("file_bytes")
    if (
        isinstance(model_file_bytes, bool)
        or not isinstance(model_file_bytes, int)
        or model_file_bytes <= 0
        or storage["total_bytes"] < model_file_bytes
    ):
        raise GuardError("runtime model size is incompatible with shared storage")
    if binding.get("model_tree_sha256") != model.get("tree_sha256"):
        raise GuardError("mission model binding mismatch")
    model_root = Path(str(model.get("path", "")))
    for name, expected in (
        ("config.json", model.get("config_sha256")),
        ("model.safetensors.index.json", model.get("index_sha256")),
    ):
        if file_sha256(model_root / name) != validate_sha256(
            expected, f"model.{name}"
        ):
            raise GuardError(f"model file drift: {name}")
    engine = Path(str(contract.get("engine", {}).get("vllm_executable", "")))
    if file_sha256(engine) != validate_sha256(
        contract.get("engine", {}).get("vllm_executable_sha256"),
        "engine.vllm_executable_sha256",
    ):
        raise GuardError("vLLM executable drift")
    queue = probe_comfyui_queue()
    return {
        "status": "PASS",
        "pod_id": EXPECTED_POD_ID,
        "gpu": inventory[0],
        "network_volume_id": EXPECTED_NETWORK_VOLUME_ID,
        "mission_binding_sha256": observed_binding_hash,
        "runtime_contract_sha256": observed_contract_hash,
        "model_tree_sha256": model["tree_sha256"],
        "workspace_storage": storage,
        "comfyui_queue": queue,
    }


def query_gpu_compute_processes() -> list[str]:
    """Return active NVIDIA compute PIDs, failing closed if telemetry is unavailable."""
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def load_manager(path: Path) -> ModuleType:
    """Load the shared lease authority from its exact Pod-resident path."""
    if not path.is_file():
        raise GuardError(f"shared GPU lease manager is missing: {path}")
    if file_sha256(path) != EXPECTED_MANAGER_SHA256:
        raise GuardError("shared GPU lease manager hash mismatch")
    spec = importlib.util.spec_from_file_location("shared_gpu_lease_manager", path)
    if spec is None or spec.loader is None:
        raise GuardError("shared GPU lease manager cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = {
        "ensure_owner_token_file",
        "enqueue",
        "acquire",
        "heartbeat",
        "release",
        "withdraw_queued",
    }
    if any(not callable(getattr(module, name, None)) for name in required):
        raise GuardError("shared GPU lease manager has an invalid API")
    return module


def validate_owner_token_file(
    token_file: Path,
    owner_token: str,
    *,
    platform_name: str | None = None,
    current_uid: Callable[[], int] | None = None,
) -> str:
    """Prove the manager returned the exact private regular-file token."""
    path = Path(token_file)
    platform = os.name if platform_name is None else platform_name
    uid_probe = getattr(os, "getuid", None) if current_uid is None else current_uid
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise GuardError("owner token file is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise GuardError("owner token path is not a regular file")
    if metadata.st_size < 32 or metadata.st_size > 4096:
        raise GuardError("owner token file size is invalid")
    if platform != "nt":
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise GuardError("owner token file mode is not 0600")
        if uid_probe is not None and metadata.st_uid != uid_probe():
            raise GuardError("owner token file is owned by another user")
    try:
        observed = path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise GuardError("owner token file is unreadable") from exc
    if observed != owner_token or not owner_token.isascii():
        raise GuardError("owner token file content mismatch")
    return hashlib.sha256(owner_token.encode("ascii")).hexdigest()


def emit(payload: dict[str, Any]) -> None:
    """Emit non-secret machine-readable evidence."""
    print(json.dumps(payload, sort_keys=True))


def default_token_file(job_id: str, payload_sha256: str) -> Path:
    """Return a stable mission-specific protected-token path."""
    identity = hashlib.sha256(
        f"{SESSION_ID}\0{job_id}\0{payload_sha256}".encode("utf-8")
    ).hexdigest()[:24]
    return Path(f"/tmp/maskfactory-{identity}-shared-gpu-owner.token")


def remove_owned_token(token_file: Path, owner_token: str) -> bool:
    """Remove only the exact token used by this work cell."""
    path = Path(token_file)
    if not path.exists():
        return True
    try:
        observed = path.read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return False
    if observed != owner_token:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def terminate_owned_process_group(child: subprocess.Popen[Any]) -> None:
    """Stop only the process group created for the guarded work cell."""
    if child.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    else:
        child.terminate()
    try:
        child.wait(timeout=15)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name == "posix":
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    else:
        child.kill()
    child.wait()


def persist_release_receipt(
    *,
    receipt_root: Path,
    job_id: str,
    payload_sha256: str,
    request_id: str,
    disposition: str,
    terminal_reason: str,
    lease_result: dict[str, Any],
    child_pid: int | None,
    child_returncode: int | None,
    token_file: Path,
) -> dict[str, Any]:
    """Bind a durable lease transition before protected-token cleanup."""
    root = Path(receipt_root)
    root.mkdir(parents=True, exist_ok=True)
    return atomic_sealed_json(
        root / RELEASE_RECEIPT_NAME,
        {
            "schema_version": "maskfactory.shared_gpu_release_receipt.v1",
            "session_id": SESSION_ID,
            "job_id": job_id,
            "payload_sha256": payload_sha256,
            "request_id": request_id,
            "disposition": disposition,
            "terminal_reason": terminal_reason,
            "lease_state": lease_result.get("state"),
            "lease_released_at": lease_result.get("released_at"),
            "child_pid": child_pid,
            "child_returncode": child_returncode,
            "owner_token_path": str(token_file),
            "owner_token_retained": True,
            "self_sha256": "0" * 64,
        },
    )


def run_guarded(
    *,
    manager: ModuleType,
    database: Path,
    token_file: Path,
    job_id: str,
    payload_sha256: str,
    work_kind: str,
    max_runtime_seconds: int,
    heartbeat_seconds: float,
    command: list[str],
    receipt_root: Path,
    gpu_process_probe: Callable[[], list[str]] = query_gpu_compute_processes,
    preflight_probe: Callable[[], dict[str, Any]] = lambda: {"status": "PASS"},
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Acquire once, run one child, heartbeat, and terminally release."""
    if not command:
        raise GuardError("a child command is required after --")
    if heartbeat_seconds <= 0:
        raise GuardError("heartbeat interval must be positive")
    if (
        isinstance(max_runtime_seconds, bool)
        or not isinstance(max_runtime_seconds, int)
        or max_runtime_seconds <= 0
    ):
        raise GuardError("max_runtime_seconds must be positive")
    validate_sha256(payload_sha256, "payload_sha256")
    if not job_id or len(job_id) > 200 or any(character in job_id for character in "/\\"):
        raise GuardError("job_id is invalid")

    preflight = preflight_probe()
    if preflight.get("status") != "PASS":
        raise GuardError("local GPU preflight did not pass")
    emit({"status": "LOCAL_GPU_PREFLIGHT_PASS", **preflight})
    existing_gpu_processes = gpu_process_probe()
    if existing_gpu_processes:
        emit(
            {
                "status": "FALLBACK_REQUIRED",
                "reason": "UNTRACKED_OR_ACTIVE_GPU_PROCESS",
                "session_id": SESSION_ID,
                "local_gpu_started": False,
                "gpu_process_count": len(existing_gpu_processes),
                "next_routes": ["serverless_overflow", "openrouter_advisory"],
            }
        )
        return FALLBACK_REQUIRED

    owner_token = manager.ensure_owner_token_file(token_file)
    validate_owner_token_file(token_file, owner_token)
    queued = manager.enqueue(
        database=database,
        session_id=SESSION_ID,
        job_id=job_id,
        payload_sha256=payload_sha256,
        work_kind=work_kind,
        max_runtime_seconds=max_runtime_seconds,
    )
    request_id = queued["request_id"]
    if queued.get("state") != "queued":
        raise GuardError("canonical lease request is already terminal or active")
    acquired = manager.acquire(
        database=database,
        request_id=request_id,
        owner_token=owner_token,
    )
    if acquired.get("acquired") is not True:
        terminal_reason = (
            "MaskFactory withdrew queued local GPU ownership before fallback: "
            f"{acquired.get('reason', 'SHARED_GPU_LEASE_UNAVAILABLE')}"
        )
        withdrawn = manager.withdraw_queued(
            database=database,
            request_id=request_id,
            session_id=SESSION_ID,
            job_id=job_id,
            payload_sha256=payload_sha256,
            terminal_reason=terminal_reason,
        )
        try:
            receipt = persist_release_receipt(
                receipt_root=receipt_root,
                job_id=job_id,
                payload_sha256=payload_sha256,
                request_id=request_id,
                disposition="withdrawn_before_fallback",
                terminal_reason=terminal_reason,
                lease_result=withdrawn,
                child_pid=None,
                child_returncode=None,
                token_file=token_file,
            )
        except Exception as exc:
            emit(
                {
                    "status": "LEASE_RECEIPT_FAILED",
                    "error_type": type(exc).__name__,
                    "request_id": request_id,
                    "session_id": SESSION_ID,
                    "lease_terminalized": True,
                }
            )
            return COORDINATION_FAILURE
        token_removed = remove_owned_token(token_file, owner_token)
        emit(
            {
                "status": (
                    "FALLBACK_REQUIRED"
                    if token_removed
                    else "TOKEN_CLEANUP_FAILED"
                ),
                "reason": acquired.get("reason", "SHARED_GPU_LEASE_UNAVAILABLE"),
                "request_id": request_id,
                "session_id": SESSION_ID,
                "local_gpu_started": False,
                "lease_terminalized": True,
                "release_receipt_sha256": receipt["self_sha256"],
                "owner_token_removed": token_removed,
                "next_routes": ["serverless_overflow", "openrouter_advisory"],
            }
        )
        return FALLBACK_REQUIRED if token_removed else COORDINATION_FAILURE

    raced_gpu_processes = gpu_process_probe()
    if raced_gpu_processes:
        terminal_reason = (
            "Local GPU admission aborted because an untracked or active "
            "compute process appeared after lease acquisition"
        )
        released = manager.release(
            database=database,
            request_id=request_id,
            owner_token=owner_token,
            terminal_state="failed",
            terminal_reason=terminal_reason,
        )
        try:
            receipt = persist_release_receipt(
                receipt_root=receipt_root,
                job_id=job_id,
                payload_sha256=payload_sha256,
                request_id=request_id,
                disposition="failed_before_child_start",
                terminal_reason=terminal_reason,
                lease_result=released,
                child_pid=None,
                child_returncode=None,
                token_file=token_file,
            )
        except Exception as exc:
            emit(
                {
                    "status": "LEASE_RECEIPT_FAILED",
                    "error_type": type(exc).__name__,
                    "request_id": request_id,
                    "session_id": SESSION_ID,
                    "lease_terminalized": True,
                }
            )
            return COORDINATION_FAILURE
        token_removed = remove_owned_token(token_file, owner_token)
        emit(
            {
                "status": (
                    "FALLBACK_REQUIRED"
                    if token_removed
                    else "TOKEN_CLEANUP_FAILED"
                ),
                "reason": "GPU_PROCESS_RACE_AFTER_LEASE",
                "request_id": request_id,
                "session_id": SESSION_ID,
                "local_gpu_started": False,
                "gpu_process_count": len(raced_gpu_processes),
                "lease_terminalized": True,
                "release_receipt_sha256": receipt["self_sha256"],
                "owner_token_removed": token_removed,
                "next_routes": ["serverless_overflow", "openrouter_advisory"],
            }
        )
        return FALLBACK_REQUIRED if token_removed else COORDINATION_FAILURE

    stop = threading.Event()
    heartbeat_errors: list[str] = []

    def heartbeat_worker() -> None:
        while not stop.wait(heartbeat_seconds):
            try:
                manager.heartbeat(
                    database=database,
                    request_id=request_id,
                    owner_token=owner_token,
                )
            except Exception as exc:  # fail closed; never expose the token
                heartbeat_errors.append(type(exc).__name__)
                stop.set()

    child: subprocess.Popen[Any] | None = None
    thread = threading.Thread(
        target=heartbeat_worker,
        name=f"maskfactory-shared-gpu-heartbeat-{job_id}",
        daemon=True,
    )
    try:
        child_environment = os.environ.copy()
        child_environment.update(
            {
                "MASKFACTORY_SHARED_GPU_GUARD_ACTIVE": "1",
                "MASKFACTORY_SHARED_GPU_GUARD_JOB_ID": job_id,
                "MASKFACTORY_SHARED_GPU_GUARD_PAYLOAD_SHA256": payload_sha256,
                "MASKFACTORY_SHARED_GPU_GUARD_REQUEST_ID": request_id,
                "MASKFACTORY_SHARED_GPU_GUARD_RECEIPT_ROOT": str(
                    Path(receipt_root).resolve()
                ),
            }
        )
        child = subprocess.Popen(
            command,
            start_new_session=True,
            env=child_environment,
        )
        thread.start()
        emit(
            {
                "status": "LOCAL_GPU_STARTED",
                "request_id": request_id,
                "session_id": SESSION_ID,
                "child_pid": child.pid,
                "local_gpu_started": True,
            }
        )
        deadline = monotonic() + max_runtime_seconds
        while True:
            observed = child.poll()
            if observed is not None:
                returncode = observed
                break
            if heartbeat_errors:
                terminate_owned_process_group(child)
                returncode = COORDINATION_FAILURE
                break
            if monotonic() >= deadline:
                terminate_owned_process_group(child)
                returncode = CHILD_TIMEOUT
                break
            stop.wait(min(0.25, heartbeat_seconds, max(0.0, deadline - monotonic())))
    except KeyboardInterrupt:
        if child is not None:
            terminate_owned_process_group(child)
        returncode = 130
    finally:
        stop.set()
        if thread.is_alive():
            thread.join(timeout=max(5.0, heartbeat_seconds + 1))

    terminal_state = "completed" if returncode == 0 else "failed"
    if returncode == 0:
        terminal_reason = "MaskFactory guarded local GPU command completed"
    elif returncode == CHILD_TIMEOUT:
        terminal_reason = (
            "MaskFactory guarded local GPU command exceeded its atomic runtime"
        )
    elif heartbeat_errors:
        terminal_reason = "MaskFactory shared GPU lease heartbeat failed"
    else:
        terminal_reason = f"MaskFactory guarded local GPU command exited {returncode}"
    try:
        released = manager.release(
            database=database,
            request_id=request_id,
            owner_token=owner_token,
            terminal_state=terminal_state,
            terminal_reason=terminal_reason,
        )
    except Exception as exc:
        emit(
            {
                "status": "LEASE_RELEASE_FAILED",
                "error_type": type(exc).__name__,
                "request_id": request_id,
                "session_id": SESSION_ID,
                "local_gpu_terminal": True,
            }
        )
        return COORDINATION_FAILURE

    try:
        receipt = persist_release_receipt(
            receipt_root=receipt_root,
            job_id=job_id,
            payload_sha256=payload_sha256,
            request_id=request_id,
            disposition=terminal_state,
            terminal_reason=terminal_reason,
            lease_result=released,
            child_pid=child.pid if child is not None else None,
            child_returncode=returncode,
            token_file=token_file,
        )
    except Exception as exc:
        emit(
            {
                "status": "LEASE_RECEIPT_FAILED",
                "error_type": type(exc).__name__,
                "request_id": request_id,
                "session_id": SESSION_ID,
                "lease_terminalized": True,
            }
        )
        return COORDINATION_FAILURE
    token_removed = remove_owned_token(token_file, owner_token)
    if not token_removed:
        emit(
            {
                "status": "TOKEN_CLEANUP_FAILED",
                "request_id": request_id,
                "session_id": SESSION_ID,
                "lease_terminalized": True,
                "release_receipt_sha256": receipt["self_sha256"],
            }
        )
        return COORDINATION_FAILURE

    if heartbeat_errors:
        emit(
            {
                "status": "HEARTBEAT_FAILED",
                "error_type": heartbeat_errors[0],
                "request_id": request_id,
                "session_id": SESSION_ID,
                "lease_terminalized": True,
                "release_receipt_sha256": receipt["self_sha256"],
                "owner_token_removed": True,
            }
        )
        return COORDINATION_FAILURE

    emit(
        {
            "status": "COMPLETED" if returncode == 0 else "FAILED",
            "request_id": request_id,
            "session_id": SESSION_ID,
            "child_returncode": returncode,
            "lease_terminalized": True,
            "release_receipt_sha256": receipt["self_sha256"],
            "owner_token_removed": True,
        }
    )
    return returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--payload-sha256", required=True)
    parser.add_argument("--work-kind", required=True)
    parser.add_argument("--max-runtime-seconds", type=int, required=True)
    parser.add_argument("--heartbeat-seconds", type=float, default=25)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--manager", type=Path, default=DEFAULT_MANAGER)
    parser.add_argument("--owner-token-file", type=Path)
    parser.add_argument("--mission-root", type=Path, required=True)
    parser.add_argument("--runtime-contract", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    token_file = args.owner_token_file or default_token_file(
        args.job_id,
        args.payload_sha256,
    )
    try:
        manager = load_manager(args.manager)
        return run_guarded(
            manager=manager,
            database=args.database,
            token_file=token_file,
            job_id=args.job_id,
            payload_sha256=args.payload_sha256,
            work_kind=args.work_kind,
            max_runtime_seconds=args.max_runtime_seconds,
            heartbeat_seconds=args.heartbeat_seconds,
            command=command,
            receipt_root=args.mission_root,
            preflight_probe=lambda: run_local_admission_preflight(
                mission_root=args.mission_root,
                runtime_contract_path=args.runtime_contract,
                job_id=args.job_id,
                payload_sha256=args.payload_sha256,
            ),
        )
    except Exception as exc:
        emit(
            {
                "status": "COORDINATION_FAILURE",
                "error_type": type(exc).__name__,
                "local_gpu_started": False,
            }
        )
        return COORDINATION_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
