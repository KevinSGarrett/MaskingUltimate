#!/usr/bin/env python3
"""Represent one verified legacy GPU process in the shared lease ledger."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

MASKFACTORY_SESSION_ID = "019f91d1-ea20-7d81-83ff-03d393eaa1f5"
COMFYUI_SESSION_ID = "019f9200-4805-7632-83d3-ee9ae614c603"
DEFAULT_DATABASE = Path(
    "/workspace/.maskfactory/shared_pod_coordination/shared_gpu_leases_v1.sqlite"
)
DEFAULT_MANAGER = Path(
    "/workspace/.maskfactory/shared_pod_coordination/tools/" "manage_shared_pod_gpu_lease_v2.py"
)
COORDINATION_FAILURE = 70
FALLBACK_REQUIRED = 75


class ReconciliationError(RuntimeError):
    """Raised when a process cannot be represented safely."""


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def load_manager(path: Path) -> ModuleType:
    if not path.is_file():
        raise ReconciliationError(f"shared GPU lease manager is missing: {path}")
    spec = importlib.util.spec_from_file_location("shared_gpu_lease_manager", path)
    if spec is None or spec.loader is None:
        raise ReconciliationError("shared GPU lease manager cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = {
        "ensure_owner_token_file",
        "enqueue",
        "acquire",
        "heartbeat",
        "release",
        "status",
    }
    if any(not callable(getattr(module, name, None)) for name in required):
        raise ReconciliationError("shared GPU lease manager has an invalid API")
    return module


def query_gpu_compute_pids() -> list[int]:
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
    return [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]


def _parent_pid(pid: int) -> int | None:
    try:
        for line in (
            Path(f"/proc/{pid}/status").read_text(encoding="utf-8", errors="replace").splitlines()
        ):
            if line.startswith("PPid:"):
                value = int(line.split(":", 1)[1].strip())
                return value if value > 0 else None
    except (OSError, ValueError):
        return None
    return None


def _command_line(pid: int) -> str:
    try:
        return (
            Path(f"/proc/{pid}/cmdline")
            .read_bytes()
            .replace(b"\0", b" ")
            .decode("utf-8", errors="replace")
        )
    except OSError:
        return ""


def classify_process_owner(pid: int) -> str | None:
    """Classify only exact project-root ancestry; unknown processes stay unknown."""
    fragments: list[str] = []
    current: int | None = pid
    observed: set[int] = set()
    for _ in range(10):
        if current is None or current in observed:
            break
        observed.add(current)
        fragments.append(_command_line(current).lower())
        current = _parent_pid(current)
    ancestry = "\n".join(fragments)
    if "/workspace/maskfactory/" in ancestry:
        return MASKFACTORY_SESSION_ID
    if "/workspace/comfyui/" in ancestry or "/workspace/comfy_ui_main/" in ancestry:
        return COMFYUI_SESSION_ID
    return None


def reconcile(
    *,
    manager: ModuleType,
    database: Path,
    interval_seconds: float,
    max_runtime_seconds: int,
    process_probe: Callable[[], list[int]] = query_gpu_compute_pids,
    owner_classifier: Callable[[int], str | None] = classify_process_owner,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    if interval_seconds <= 0:
        raise ReconciliationError("interval must be positive")
    pids = process_probe()
    if not pids:
        emit({"status": "IDLE", "active_gpu_processes": 0})
        return 0

    owners = {owner_classifier(pid) for pid in pids}
    if None in owners or len(owners) != 1:
        emit(
            {
                "status": "UNKNOWN_OR_MIXED_GPU_OWNER",
                "active_gpu_processes": len(pids),
                "local_gpu_process_touched": False,
            }
        )
        return FALLBACK_REQUIRED
    session_id = owners.pop()
    assert session_id is not None

    current = manager.status(database=database)
    if current.get("active") is not None:
        emit(
            {
                "status": "ACTIVE_LEASE_ALREADY_PRESENT",
                "session_id": current["active"].get("session_id"),
                "local_gpu_process_touched": False,
            }
        )
        return 0

    token_file = Path(f"/tmp/gpu-reconciler-{session_id}.token")
    owner_token = manager.ensure_owner_token_file(token_file)
    lineage = ",".join(str(pid) for pid in sorted(pids))
    payload_sha256 = hashlib.sha256(f"{session_id}:{lineage}".encode("utf-8")).hexdigest()
    queued = manager.enqueue(
        database=database,
        session_id=session_id,
        job_id=f"reconciled-legacy-gpu-{min(pids)}",
        payload_sha256=payload_sha256,
        work_kind="reconciled_legacy_gpu_process",
        max_runtime_seconds=max_runtime_seconds,
    )
    request_id = queued["request_id"]
    lease = manager.acquire(
        database=database,
        request_id=request_id,
        owner_token=owner_token,
    )
    if lease.get("acquired") is not True:
        emit(
            {
                "status": "LEASE_UNAVAILABLE",
                "reason": lease.get("reason"),
                "session_id": session_id,
                "local_gpu_process_touched": False,
            }
        )
        return FALLBACK_REQUIRED

    emit(
        {
            "status": "RECONCILED",
            "request_id": request_id,
            "session_id": session_id,
            "active_gpu_processes": len(pids),
            "local_gpu_process_touched": False,
        }
    )
    while True:
        sleeper(interval_seconds)
        observed_pids = process_probe()
        if not observed_pids:
            manager.release(
                database=database,
                request_id=request_id,
                owner_token=owner_token,
                terminal_state="completed",
                terminal_reason="reconciled GPU process exited normally",
            )
            emit(
                {
                    "status": "RELEASED",
                    "request_id": request_id,
                    "session_id": session_id,
                    "local_gpu_process_touched": False,
                }
            )
            return 0
        observed_owners = {owner_classifier(pid) for pid in observed_pids}
        if observed_owners != {session_id}:
            manager.release(
                database=database,
                request_id=request_id,
                owner_token=owner_token,
                terminal_state="failed",
                terminal_reason="GPU ownership became unknown or mixed",
            )
            emit(
                {
                    "status": "OWNERSHIP_CHANGED",
                    "request_id": request_id,
                    "session_id": session_id,
                    "local_gpu_process_touched": False,
                }
            )
            return COORDINATION_FAILURE
        manager.heartbeat(
            database=database,
            request_id=request_id,
            owner_token=owner_token,
        )


def monitor(
    *,
    manager: ModuleType,
    database: Path,
    interval_seconds: float,
    max_runtime_seconds: int,
    process_probe: Callable[[], list[int]] = query_gpu_compute_pids,
    owner_classifier: Callable[[int], str | None] = classify_process_owner,
    sleeper: Callable[[float], None] = time.sleep,
    max_cycles: int = 0,
) -> int:
    """Continuously reconcile sequential legacy processes without touching them."""
    cycles = 0
    while max_cycles <= 0 or cycles < max_cycles:
        result = reconcile(
            manager=manager,
            database=database,
            interval_seconds=interval_seconds,
            max_runtime_seconds=max_runtime_seconds,
            process_probe=process_probe,
            owner_classifier=owner_classifier,
            sleeper=sleeper,
        )
        cycles += 1
        if result == COORDINATION_FAILURE:
            return result
        if max_cycles <= 0 or cycles < max_cycles:
            sleeper(interval_seconds)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--manager", type=Path, default=DEFAULT_MANAGER)
    parser.add_argument("--interval-seconds", type=float, default=15)
    parser.add_argument("--max-runtime-seconds", type=int, default=3600)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args(argv)
    try:
        manager = load_manager(args.manager)
        function = monitor if args.watch else reconcile
        return function(
            manager=manager,
            database=args.database,
            interval_seconds=args.interval_seconds,
            max_runtime_seconds=args.max_runtime_seconds,
        )
    except Exception as exc:
        emit(
            {
                "status": "COORDINATION_FAILURE",
                "error_type": type(exc).__name__,
                "local_gpu_process_touched": False,
            }
        )
        return COORDINATION_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
