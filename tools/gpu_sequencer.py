"""GPU telemetry probe with all resource-governance behavior retired.

The selected RunPod executes directly. VRAM readings and process listings are
diagnostic observations only. This tool has no planning, waiting, reservation,
checkout, sequencing, reclamation, or veto command.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from maskfactory.gpu import DEFAULT_GPU_LOCK_PATH  # noqa: E402

# Legacy consumer names and numerical fields are retained only so old callers
# can parse telemetry. They have no admission, reservation, or refusal effect.
CONSUMER_VRAM_MIB: dict[str, int] = {
    "ollama-vlm": 0,
    "ollama-text": 0,
    "nuclio-sam2": 0,
    "pipeline": 0,
    "comfyui": 0,
}
DEFAULT_SAFETY_MIB = 0
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
NUCLIO_SAM2_CONTAINER = "nuclio-nuclio-pth-sam2"
RECLAIM_RECIPES: dict[str, dict[str, str]] = {
    name: {"method": "none", "target": ""} for name in CONSUMER_VRAM_MIB
}

# Process-name fragments used only to annotate telemetry.
FOREIGN_HOLDER_HINTS: tuple[str, ...] = (
    "comfyui",
    "main.py",
    "8188",
)


@dataclass
class GpuSnapshot:
    """One card's live memory/utilization reading."""

    name: str
    total_mib: int
    used_mib: int
    free_mib: int
    util_pct: int


@dataclass
class ComputeApp:
    """A process holding GPU memory as reported by nvidia-smi."""

    pid: int
    process_name: str
    used_mib: int | None
    foreign: bool = False


@dataclass
class SequenceDecision:
    """Legacy-shaped telemetry result; never an admission verdict."""

    consumer: str
    required_mib: int
    safety_mib: int
    free_mib: int | None
    lock_state: str
    decision: str = "run_now"
    reasons: list[str] = field(default_factory=list)
    foreign_holders: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReclaimResult:
    """Legacy-shaped proof that automatic VRAM reclamation is disabled."""

    consumer: str
    method: str = "none"
    target: str = ""
    status: str = "disabled"
    free_before_mib: int | None = None
    free_after_mib: int | None = None
    freed_mib: int | None = None
    detail: str = "automatic GPU/VRAM reclamation is retired"

    def resolve_freed(self) -> None:
        self.freed_mib = None


def _int(value: str) -> int:
    return int("".join(ch for ch in value if ch.isdigit() or ch == "-") or "0")


def parse_smi_gpu(csv_text: str) -> list[GpuSnapshot]:
    """Parse ``--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu``."""
    snapshots: list[GpuSnapshot] = []
    for line in csv_text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("name"):
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 5:
            continue
        snapshots.append(
            GpuSnapshot(
                name=parts[0],
                total_mib=_int(parts[1]),
                used_mib=_int(parts[2]),
                free_mib=_int(parts[3]),
                util_pct=_int(parts[4]),
            )
        )
    return snapshots


def _is_foreign(name: str, consumer: str) -> bool:
    lowered = name.lower()
    if consumer and consumer.lower() in lowered:
        return False
    return any(hint in lowered for hint in FOREIGN_HOLDER_HINTS)


def parse_smi_apps(csv_text: str, *, consumer: str = "") -> list[ComputeApp]:
    """Parse ``--query-compute-apps=pid,process_name,used_gpu_memory``."""
    apps: list[ComputeApp] = []
    for line in csv_text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("pid"):
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        raw_mem = parts[2] if len(parts) > 2 else ""
        used = None if not any(ch.isdigit() for ch in raw_mem) else _int(raw_mem)
        name = parts[1]
        apps.append(
            ComputeApp(
                pid=_int(parts[0]),
                process_name=name,
                used_mib=used,
                foreign=_is_foreign(name, consumer),
            )
        )
    return apps


def _windows_cmdline(pid: int) -> str:
    """Best-effort full command line for a Windows PID (empty on any failure)."""
    if sys.platform != "win32" or pid <= 0:
        return ""
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _augment_foreign(apps: list[ComputeApp], consumer: str) -> list[ComputeApp]:
    """Re-classify holders using the full command line (SMI only exposes the exe name)."""
    for app in apps:
        if app.foreign:
            continue
        cmdline = _windows_cmdline(app.pid)
        if cmdline and _is_foreign(cmdline, consumer):
            app.foreign = True
            app.process_name = f"{app.process_name} :: {cmdline[:160]}"
    return apps


def _run_smi(args: list[str], *, timeout: int = 30) -> str | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def probe_gpu(*, consumer: str = "") -> dict[str, Any]:
    """Live snapshot of cards + compute apps. Fails closed to an empty snapshot."""
    gpu_csv = _run_smi(
        [
            "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader",
        ]
    )
    app_csv = _run_smi(
        ["--query-compute-apps=pid,process_name,used_gpu_memory", "--format=csv,noheader"]
    )
    gpus = parse_smi_gpu(gpu_csv or "")
    apps = _augment_foreign(parse_smi_apps(app_csv or "", consumer=consumer), consumer)
    return {
        "probed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "nvidia_smi_available": gpu_csv is not None,
        "gpus": [asdict(gpu) for gpu in gpus],
        "compute_apps": [asdict(app) for app in apps],
    }


def decide(
    consumer: str,
    snapshot: dict[str, Any],
    *,
    required_mib: int | None = None,
    safety_mib: int = DEFAULT_SAFETY_MIB,
    lock_path: Path = DEFAULT_GPU_LOCK_PATH,
) -> SequenceDecision:
    """Return direct execution with optional telemetry; never gate on GPU state."""
    del required_mib, safety_mib
    required = 0
    safety = 0
    del lock_path
    gpus = snapshot.get("gpus") or []
    apps = snapshot.get("compute_apps") or []
    foreign = [app for app in apps if app.get("foreign")]

    decision = SequenceDecision(
        consumer=consumer,
        required_mib=required,
        safety_mib=safety,
        free_mib=int(gpus[0]["free_mib"]) if gpus else None,
        lock_state="retired",
        foreign_holders=foreign,
    )

    if not snapshot.get("nvidia_smi_available") or not gpus:
        decision.decision = "run_now"
        decision.reasons.append(
            "GPU telemetry unavailable; observation is non-authoritative and does not gate execution"
        )
        return decision

    free = int(gpus[0]["free_mib"])
    decision.reasons.append(f"free={free} MiB; telemetry only")

    decision.decision = "run_now"
    decision.reasons.append("VRAM and process observations are telemetry only")
    return decision


def wait_for_slot(
    consumer: str,
    *,
    required_mib: int | None = None,
    safety_mib: int = DEFAULT_SAFETY_MIB,
    timeout_s: int = 600,
    poll_s: int = 10,
    lock_path: Path = DEFAULT_GPU_LOCK_PATH,
) -> tuple[SequenceDecision, list[dict[str, Any]]]:
    """Compatibility name for one non-blocking telemetry observation."""
    snapshot = probe_gpu(consumer=consumer)
    decision = decide(
        consumer,
        snapshot,
        required_mib=required_mib,
        safety_mib=safety_mib,
        lock_path=lock_path,
    )
    return decision, [
        {
            "at": snapshot["probed_at"],
            "decision": decision.decision,
            "free_mib": decision.free_mib,
        }
    ]


def reclaim_method(consumer: str) -> str:
    """Return the active reclaim method configured for a consumer (pure lookup)."""
    return RECLAIM_RECIPES.get(consumer, {}).get("method", "none")


def _free_mib(consumer: str = "") -> int | None:
    snapshot = probe_gpu(consumer=consumer)
    gpus = snapshot.get("gpus") or []
    return int(gpus[0]["free_mib"]) if gpus else None


def unload_ollama_model(
    model: str, *, base_url: str = OLLAMA_BASE_URL, timeout: int = 60
) -> tuple[bool, str]:
    """Compatibility function that never unloads a model."""
    del model, base_url, timeout
    return False, "automatic GPU/VRAM reclamation is retired"


def restart_docker_container(name: str, *, timeout: int = 120) -> tuple[bool, str]:
    """Compatibility function that never restarts a container."""
    del name, timeout
    return False, "automatic GPU/VRAM reclamation is retired"


def release_consumer(
    consumer: str,
    *,
    base_url: str = OLLAMA_BASE_URL,
    settle_s: int = 3,
) -> ReclaimResult:
    """Return a non-mutating retirement result; never reclaim GPU resources."""
    del base_url, settle_s
    return ReclaimResult(consumer=consumer)


def sequence_handoff(
    consumer: str,
    *,
    free_consumers: list[str] | None = None,
    required_mib: int | None = None,
    safety_mib: int = DEFAULT_SAFETY_MIB,
    timeout_s: int = 600,
    poll_s: int = 10,
    lock_path: Path = DEFAULT_GPU_LOCK_PATH,
    base_url: str = OLLAMA_BASE_URL,
) -> dict[str, Any]:
    """Compatibility entry point that performs no reclaim or sequencing."""
    baseline = probe_gpu(consumer=consumer)
    baseline_free = (
        (baseline.get("gpus") or [{}])[0].get("free_mib") if baseline.get("gpus") else None
    )

    reclaims: list[ReclaimResult] = []

    decision, trail = wait_for_slot(
        consumer,
        required_mib=required_mib,
        safety_mib=safety_mib,
        timeout_s=timeout_s,
        poll_s=poll_s,
        lock_path=lock_path,
    )
    return {
        "sequenced_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "consumer": consumer,
        "baseline_free_mib": baseline_free,
        "reclaims": [asdict(item) for item in reclaims],
        "decision": asdict(decision),
        "poll_trail": trail,
    }


def _emit(payload: dict[str, Any], out: Path | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="Live VRAM + compute-app snapshot")
    p_probe.add_argument("--json", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.command == "probe":
        snapshot = probe_gpu()
        _emit(snapshot, args.json)
        return 0 if snapshot["nvidia_smi_available"] else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
