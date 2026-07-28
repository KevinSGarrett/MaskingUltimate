"""Pod-scoped health checks for the governed MaskFactory RunPod runtime."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .providers.runtime_matrix import verify_runtime_matrix

RUNPOD_WORKSPACE_ROOT = Path("/workspace/maskfactory")
RUNPOD_GPU_NAME = "NVIDIA RTX 6000 Ada Generation"
RUNPOD_GPU_CAPABILITY = [8, 9]


def is_runpod_execution() -> bool:
    """Return whether this source package is executing in the governed Pod tree."""
    return (
        os.name != "nt"
        and Path(__file__).resolve().parents[2] == RUNPOD_WORKSPACE_ROOT
        and RUNPOD_WORKSPACE_ROOT.is_dir()
    )


def _result(name: str, status: str, detail: str, hint: str = ""):
    # Import lazily so doctor can import this module without a circular module load.
    from .doctor import CheckResult

    return CheckResult(name=name, status=status, detail=detail, hint=hint)


def check_runpod_torch_cuda():
    """Verify the exact Ada/cu128 runtime from the Pod's active interpreter."""
    script = (
        "import json,torch; print(json.dumps({'torch':torch.__version__,"
        "'cuda':torch.version.cuda,'available':torch.cuda.is_available(),"
        "'name':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,"
        "'capability':list(torch.cuda.get_device_capability(0)) if torch.cuda.is_available() else []}))"
    )
    try:
        process = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _result(
            "torch_cuda",
            "FAIL",
            str(exc),
            "Repair the Pod's selected Python environment before RunPod execution.",
        )
    if process.returncode:
        return _result(
            "torch_cuda",
            "FAIL",
            (process.stderr or process.stdout).strip(),
            "Repair the Pod's selected Python environment before RunPod execution.",
        )
    try:
        payload = json.loads(process.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return _result(
            "torch_cuda",
            "FAIL",
            f"RunPod torch probe returned invalid JSON: {exc}",
            "Repair the Pod's selected Python environment before RunPod execution.",
        )
    valid = (
        payload.get("available") is True
        and payload.get("cuda") == "12.8"
        and str(payload.get("torch", "")).endswith("+cu128")
        and payload.get("name") == RUNPOD_GPU_NAME
        and payload.get("capability") == RUNPOD_GPU_CAPABILITY
    )
    if not valid:
        return _result(
            "torch_cuda",
            "FAIL",
            json.dumps(payload, sort_keys=True),
            "Use only the governed RTX 6000 Ada / cu128 Pod runtime; do not substitute hardware.",
        )
    return _result("torch_cuda", "PASS", json.dumps(payload, sort_keys=True))


def check_runpod_runtime_matrix():
    """Verify locked provider coverage without claiming pending rows are qualified."""
    try:
        report = verify_runtime_matrix()
    except Exception as exc:  # noqa: BLE001 - doctor must convert all failures to evidence
        return _result(
            "runpod_runtime_matrix",
            "FAIL",
            str(exc),
            "Repair the hash-bound runtime matrix or its evidence before Pod execution.",
        )
    pending = int(report["pending_runtime_count"])
    detail = (
        "hash-bound provider matrix verified; "
        f"qualified={report['qualified_runtime_count']} pending={pending} "
        f"artifacts={report['artifact_count']} status={report['status']}"
    )
    if pending:
        return _result(
            "runpod_runtime_matrix",
            "WARN",
            detail,
            "Pending rows remain unqualified and cannot receive production, gold, or promotion authority.",
        )
    return _result("runpod_runtime_matrix", "PASS", detail)
