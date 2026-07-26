#!/usr/bin/env python3
"""Run one MaskFactory GPU command only while owning the shared Pod lease."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import threading
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


class GuardError(RuntimeError):
    """Raised when a local GPU command cannot be admitted safely."""


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
) -> int:
    """Acquire once, run one child, heartbeat, and terminally release."""
    if not command:
        raise GuardError("a child command is required after --")
    if heartbeat_seconds <= 0:
        raise GuardError("heartbeat interval must be positive")

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
