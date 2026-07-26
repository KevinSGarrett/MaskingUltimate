#!/usr/bin/env python3
"""Run one MaskFactory GPU command only while owning the shared Pod lease."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import socket
import subprocess
import threading
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
DEFAULT_TOKEN_FILE = Path(
    f"/tmp/maskfactory-{SESSION_ID}-shared-gpu-owner.token"
)
FALLBACK_REQUIRED = 75
COORDINATION_FAILURE = 70
EXPECTED_POD_ID = "68psfqtaogg7s7"
EXPECTED_POD_NAME = "vitreous_beige_centipede"
EXPECTED_GPU = "NVIDIA RTX 6000 Ada Generation"
EXPECTED_NETWORK_VOLUME_ID = "o9qv2ld91c"
EXPECTED_WORKSPACE = Path("/workspace")
ALLOWED_ARTIFACT_ROOT = Path("/workspace/maskfactory/runtime_artifacts")


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
    model = contract.get("model", {})
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
    }
    if any(not callable(getattr(module, name, None)) for name in required):
        raise GuardError("shared GPU lease manager has an invalid API")
    return module


def emit(payload: dict[str, Any]) -> None:
    """Emit non-secret machine-readable evidence."""
    print(json.dumps(payload, sort_keys=True))


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
    gpu_process_probe: Callable[[], list[str]] = query_gpu_compute_processes,
    preflight_probe: Callable[[], dict[str, Any]] = lambda: {"status": "PASS"},
) -> int:
    """Acquire once, run one child, heartbeat, and terminally release."""
    if not command:
        raise GuardError("a child command is required after --")
    if heartbeat_seconds <= 0:
        raise GuardError("heartbeat interval must be positive")
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
                "next_routes": ["serverless_overflow", "openrouter_multimodal"],
            }
        )
        return FALLBACK_REQUIRED

    owner_token = manager.ensure_owner_token_file(token_file)
    queued = manager.enqueue(
        database=database,
        session_id=SESSION_ID,
        job_id=job_id,
        payload_sha256=payload_sha256,
        work_kind=work_kind,
        max_runtime_seconds=max_runtime_seconds,
    )
    request_id = queued["request_id"]
    acquired = manager.acquire(
        database=database,
        request_id=request_id,
        owner_token=owner_token,
    )
    if acquired.get("acquired") is not True:
        emit(
            {
                "status": "FALLBACK_REQUIRED",
                "reason": acquired.get("reason", "SHARED_GPU_LEASE_UNAVAILABLE"),
                "request_id": request_id,
                "session_id": SESSION_ID,
                "local_gpu_started": False,
                "next_routes": ["serverless_overflow", "openrouter_multimodal"],
            }
        )
        return FALLBACK_REQUIRED

    raced_gpu_processes = gpu_process_probe()
    if raced_gpu_processes:
        manager.release(
            database=database,
            request_id=request_id,
            owner_token=owner_token,
            terminal_state="failed",
            terminal_reason=(
                "Local GPU admission aborted because an untracked or active "
                "compute process appeared after lease acquisition"
            ),
        )
        emit(
            {
                "status": "FALLBACK_REQUIRED",
                "reason": "GPU_PROCESS_RACE_AFTER_LEASE",
                "request_id": request_id,
                "session_id": SESSION_ID,
                "local_gpu_started": False,
                "gpu_process_count": len(raced_gpu_processes),
                "lease_terminalized": True,
                "next_routes": ["serverless_overflow", "openrouter_multimodal"],
            }
        )
        return FALLBACK_REQUIRED

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
        child = subprocess.Popen(command)
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
        returncode = child.wait()
    except KeyboardInterrupt:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        returncode = 130
    finally:
        stop.set()
        if thread.is_alive():
            thread.join(timeout=max(5.0, heartbeat_seconds + 1))

    terminal_state = "completed" if returncode == 0 else "failed"
    terminal_reason = (
        "MaskFactory guarded local GPU command completed"
        if returncode == 0
        else f"MaskFactory guarded local GPU command exited {returncode}"
    )
    try:
        manager.release(
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

    if heartbeat_errors:
        emit(
            {
                "status": "HEARTBEAT_FAILED",
                "error_type": heartbeat_errors[0],
                "request_id": request_id,
                "session_id": SESSION_ID,
                "lease_terminalized": True,
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
    parser.add_argument("--owner-token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--mission-root", type=Path, required=True)
    parser.add_argument("--runtime-contract", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        manager = load_manager(args.manager)
        return run_guarded(
            manager=manager,
            database=args.database,
            token_file=args.owner_token_file,
            job_id=args.job_id,
            payload_sha256=args.payload_sha256,
            work_kind=args.work_kind,
            max_runtime_seconds=args.max_runtime_seconds,
            heartbeat_seconds=args.heartbeat_seconds,
            command=command,
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
