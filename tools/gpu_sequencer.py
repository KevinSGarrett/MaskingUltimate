"""Autonomous VRAM-aware GPU sequencing for MaskFactory internal consumers.

The original implementation targeted one RTX 5060 Laptop GPU (8151 MiB). On the
shared 48 GB RunPod, this file remains MaskFactory-internal critical-section
advice only. Cross-project admission is owned by SharedRunPodCoordinator v2;
MaskFactory lock presence alone cannot veto unrelated ComfyUI work.

Legacy internal consumer classes:

  * ``nuclio-sam2``  - CVAT Nuclio SAM2 interactor (loads on demand).
  * ``ollama-vlm``   - Ollama VLM/LLM QA runner (qwen2.5vl:7b ~5.7 GiB weights).
  * ``pipeline``     - native maskfactory GPU pipeline / training smoke.
  * ``comfyui``      - sibling ComfyUI server (external owner, not ours to evict).

Because the weights of any one VLM already approach the whole card, two of these
cannot coexist. This module is the autonomous sequencing gate: it probes live
VRAM (``nvidia-smi``), inspects the shared ``runs/gpu.lock`` lease, and decides
whether a requested consumer may start now, must wait, or must be sequenced after
a foreign holder releases. It never kills a foreign GPU process (e.g. a sibling
ComfyUI) and never deletes a lock it does not own -- it reports typed evidence so
the caller can serialize honestly.

CLI::

    python tools/gpu_sequencer.py probe
    python tools/gpu_sequencer.py plan --consumer ollama-vlm
    python tools/gpu_sequencer.py wait --consumer ollama-vlm --timeout 600
    python tools/gpu_sequencer.py plan --consumer pipeline --require-mib 6144 \
        --json qa/live_verification/gpu_sequencer_plan.json

    # Active reclaim: free the VRAM a consumer holds between phases.
    python tools/gpu_sequencer.py release --consumer ollama-vlm     # keep_alive=0 unload
    python tools/gpu_sequencer.py release --consumer nuclio-sam2    # restart SAM2 container

    # Sequential handoff: free contending consumers, then wait for the slot.
    python tools/gpu_sequencer.py sequence --consumer nuclio-sam2 \
        --json qa/live_verification/gpu_sequence_sam2.json

``probe``/``plan``/``wait`` only *observe* and *advise*; ``release``/``sequence``
add the autonomous "stop/start or unload between phases" action that keeps
``ollama-vlm`` and ``nuclio-sam2`` strictly sequential on the single 8 GiB card.

Pure parse/classify/reclaim-lookup helpers are import-safe and unit tested; the
live probe shells out to ``nvidia-smi`` and fails closed (empty snapshot) when it
is absent, and reclaim shells out to Ollama's HTTP API / ``docker``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from maskfactory.gpu import DEFAULT_GPU_LOCK_PATH, lock_state  # noqa: E402

# Conservative per-consumer working-set estimates for the shared 8 GiB card.
# Values are weights + KV/activation headroom, rounded up; they are advisory
# sequencing budgets, not hard allocator limits.
CONSUMER_VRAM_MIB: dict[str, int] = {
    "ollama-vlm": 7168,  # qwen2.5vl:7b ~5.7 GiB weights + vision + KV headroom
    "ollama-text": 5632,  # qwen2.5:7b-instruct
    "nuclio-sam2": 4096,  # SAM2 large interactor working set
    "pipeline": 6144,  # native maskfactory GPU pipeline / training smoke
    "comfyui": 6144,  # sibling default workload (external owner)
}

# Process-name fragments that identify a *foreign* GPU holder we must sequence
# around but never evict. Matched case-insensitively against the SMI app name
# and (when available) the full command line.
FOREIGN_HOLDER_HINTS: tuple[str, ...] = (
    "comfyui",
    "main.py",
    "8188",
)

# Default safety margin kept free so the OS/compositor never OOMs the card.
DEFAULT_SAFETY_MIB = 512

# Loopback Ollama endpoint (fixed local-only, mirrors src/maskfactory/vlm/client.py).
OLLAMA_BASE_URL = "http://127.0.0.1:11434"

# Per-consumer active reclaim recipe. This is what turns the sequencer from a
# passive advisor into an autonomous "stop/start or unload between phases" gate
# so ``ollama-vlm`` and ``nuclio-sam2`` never co-reside on the 8 GiB card:
#
#   * ``ollama_unload`` - POST /api/generate with keep_alive=0 to evict the named
#     model from VRAM immediately (Ollama's documented unload path). Cheap and
#     fast; the model reloads on demand for the next Ollama phase.
#   * ``docker_restart`` - restart the on-demand Nuclio SAM2 container so its
#     lazily-loaded weights are dropped from VRAM. The container stays available
#     and reloads SAM2 on the next CVAT interactor request.
#   * ``none`` - our own ``pipeline`` process (cannot force-unload safely) and the
#     foreign ``comfyui`` sibling (never evict). Reported as no_mechanism.
NUCLIO_SAM2_CONTAINER = "nuclio-nuclio-pth-sam2"
RECLAIM_RECIPES: dict[str, dict[str, str]] = {
    "ollama-vlm": {"method": "ollama_unload", "target": "qwen2.5vl:7b"},
    "ollama-text": {"method": "ollama_unload", "target": "qwen2.5:7b-instruct"},
    "nuclio-sam2": {"method": "docker_restart", "target": NUCLIO_SAM2_CONTAINER},
    "pipeline": {"method": "none", "target": ""},
    "comfyui": {"method": "none", "target": ""},
}


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
    """Typed sequencing verdict for one requested consumer."""

    consumer: str
    required_mib: int
    safety_mib: int
    free_mib: int | None
    lock_state: str
    # run_now | wait_headroom | wait_lock | sequence_after_foreign | no_gpu | pending
    decision: str = "pending"
    reasons: list[str] = field(default_factory=list)
    foreign_holders: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReclaimResult:
    """Typed evidence for one active VRAM reclaim (unload / container restart)."""

    consumer: str
    method: str
    target: str
    # ok | no_mechanism | error
    status: str = "ok"
    free_before_mib: int | None = None
    free_after_mib: int | None = None
    freed_mib: int | None = None
    detail: str = ""

    def resolve_freed(self) -> None:
        if self.free_before_mib is not None and self.free_after_mib is not None:
            self.freed_mib = self.free_after_mib - self.free_before_mib


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


def classify_headroom(free_mib: int, required_mib: int, safety_mib: int) -> str:
    """Return fits | tight | insufficient for a required working set."""
    if free_mib >= required_mib + safety_mib:
        return "fits"
    if free_mib >= required_mib:
        return "tight"
    return "insufficient"


def decide(
    consumer: str,
    snapshot: dict[str, Any],
    *,
    required_mib: int | None = None,
    safety_mib: int = DEFAULT_SAFETY_MIB,
    lock_path: Path = DEFAULT_GPU_LOCK_PATH,
) -> SequenceDecision:
    """Combine VRAM headroom, foreign holders, and the gpu.lock lease into a verdict."""
    required = required_mib if required_mib is not None else CONSUMER_VRAM_MIB.get(consumer, 6144)
    state, owner, age = lock_state(lock_path)
    gpus = snapshot.get("gpus") or []
    apps = snapshot.get("compute_apps") or []
    foreign = [app for app in apps if app.get("foreign")]

    if consumer == "comfyui" and gpus and int(gpus[0]["total_mib"]) >= 45000:
        # Match SharedRunPodCoordinator v2's mandatory 8 GB transient reserve.
        safety_mib = max(safety_mib, 8192)

    decision = SequenceDecision(
        consumer=consumer,
        required_mib=required,
        safety_mib=safety_mib,
        free_mib=int(gpus[0]["free_mib"]) if gpus else None,
        lock_state=state,
        foreign_holders=foreign,
    )

    if not snapshot.get("nvidia_smi_available") or not gpus:
        decision.decision = "no_gpu"
        decision.reasons.append("nvidia-smi unavailable or reported no GPU; cannot sequence safely")
        return decision

    free = int(gpus[0]["free_mib"])
    headroom = classify_headroom(free, required, safety_mib)
    decision.reasons.append(
        f"free={free} MiB, required={required} MiB, safety={safety_mib} MiB -> {headroom}"
    )

    if state == "active":
        owner_pid = owner.get("pid") if owner else None
        owner_purpose = owner.get("purpose") if owner else None
        if owner_purpose == consumer:
            decision.reasons.append(f"gpu.lock already held for '{consumer}' (pid={owner_pid})")
        elif consumer == "comfyui" and gpus and int(gpus[0]["total_mib"]) >= 45000:
            # On the shared 48 GB RunPod this lock protects MaskFactory's own
            # critical section. It is not cross-project exclusion authority.
            decision.reasons.append(
                f"MaskFactory-internal gpu.lock purpose='{owner_purpose}' pid={owner_pid}; "
                "not a ComfyUI capacity veto on the 48 GB pod"
            )
        else:
            decision.decision = "wait_lock"
            decision.reasons.append(
                f"gpu.lock held by purpose='{owner_purpose}' pid={owner_pid} age={age:.0f}s; "
                "serialize behind current MaskFactory owner"
            )
            return decision
    elif state == "stale":
        decision.reasons.append(
            f"gpu.lock is STALE (age={age:.0f}s); confirm no GPU process then remove runs/gpu.lock"
        )

    if headroom == "insufficient":
        if foreign:
            decision.decision = "sequence_after_foreign"
            names = ", ".join(f"{app['process_name']}#{app['pid']}" for app in foreign)
            decision.reasons.append(
                f"insufficient VRAM and foreign holder(s) present [{names}]; do NOT evict, "
                "wait for release or run consumer after they finish"
            )
        else:
            decision.decision = "wait_headroom"
            decision.reasons.append("insufficient VRAM with no foreign holder; wait for reclaim")
        return decision

    decision.decision = "run_now"
    if headroom == "tight":
        decision.reasons.append(
            "headroom is TIGHT; proceed but expect no room for a second consumer"
        )
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
    """Block (bounded) until the consumer may run; return final decision + poll trail."""
    deadline = time.monotonic() + timeout_s
    trail: list[dict[str, Any]] = []
    while True:
        snapshot = probe_gpu(consumer=consumer)
        decision = decide(
            consumer,
            snapshot,
            required_mib=required_mib,
            safety_mib=safety_mib,
            lock_path=lock_path,
        )
        trail.append(
            {
                "at": snapshot["probed_at"],
                "decision": decision.decision,
                "free_mib": decision.free_mib,
            }
        )
        if decision.decision in {"run_now", "no_gpu"}:
            return decision, trail
        if time.monotonic() >= deadline:
            decision.reasons.append(f"timed out after {timeout_s}s waiting for a GPU slot")
            return decision, trail
        time.sleep(min(poll_s, max(1, int(deadline - time.monotonic()))))


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
    """Evict a model from VRAM via Ollama keep_alive=0 (documented unload path)."""
    payload = json.dumps({"model": model, "keep_alive": 0}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            document = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return (
            False,
            f"ollama unload HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}",
        )
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return False, f"ollama unload failed: {exc}"
    done_reason = document.get("done_reason")
    return True, f"keep_alive=0 accepted for {model} (done_reason={done_reason})"


def restart_docker_container(name: str, *, timeout: int = 120) -> tuple[bool, str]:
    """Restart a container to drop its lazily-loaded GPU weights from VRAM."""
    exe = shutil.which("docker")
    if not exe:
        return False, "docker CLI unavailable on PATH"
    try:
        proc = subprocess.run(
            [exe, "restart", name],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"docker restart {name} failed: {exc}"
    if proc.returncode != 0:
        return False, f"docker restart {name} exit={proc.returncode}: {proc.stderr.strip()[:200]}"
    return True, f"restarted container {name}"


def release_consumer(
    consumer: str,
    *,
    base_url: str = OLLAMA_BASE_URL,
    settle_s: int = 3,
) -> ReclaimResult:
    """Actively free the VRAM a consumer holds and measure the before/after delta."""
    recipe = RECLAIM_RECIPES.get(consumer, {"method": "none", "target": ""})
    method, target = recipe["method"], recipe["target"]
    result = ReclaimResult(consumer=consumer, method=method, target=target)

    if method == "none":
        result.status = "no_mechanism"
        result.detail = (
            "no safe reclaim for this consumer (own pipeline / foreign ComfyUI never evicted)"
        )
        return result

    result.free_before_mib = _free_mib(consumer=consumer)
    if method == "ollama_unload":
        ok, detail = unload_ollama_model(target, base_url=base_url)
    elif method == "docker_restart":
        ok, detail = restart_docker_container(target)
    else:  # pragma: no cover - guarded by RECLAIM_RECIPES
        ok, detail = False, f"unknown reclaim method '{method}'"
    result.detail = detail
    result.status = "ok" if ok else "error"

    # Give the driver a moment to release VRAM before measuring the delta.
    time.sleep(max(0, settle_s))
    result.free_after_mib = _free_mib(consumer=consumer)
    result.resolve_freed()
    return result


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
    """Free contending consumers, then wait for the requested consumer's slot.

    This is the autonomous sequential primitive: before starting ``consumer`` it
    releases the *other* GPU residents (Ollama unload / SAM2 container restart) so
    the two never co-reside on the 8 GiB card, then blocks (bounded) until the
    slot is genuinely available. Foreign holders (ComfyUI) are never evicted and
    surface through the final ``sequence_after_foreign`` verdict instead.
    """
    baseline = probe_gpu(consumer=consumer)
    baseline_free = (
        (baseline.get("gpus") or [{}])[0].get("free_mib") if baseline.get("gpus") else None
    )

    if free_consumers is None:
        # Default: release every reclaimable consumer that is not the requested one.
        free_consumers = [
            other
            for other in RECLAIM_RECIPES
            if other != consumer and reclaim_method(other) != "none"
        ]

    reclaims: list[ReclaimResult] = []
    for other in free_consumers:
        if other == consumer or reclaim_method(other) == "none":
            continue
        reclaims.append(release_consumer(other, base_url=base_url))

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

    p_plan = sub.add_parser("plan", help="Sequencing verdict for one consumer")
    p_plan.add_argument("--consumer", required=True, choices=sorted(CONSUMER_VRAM_MIB))
    p_plan.add_argument("--require-mib", type=int, default=None)
    p_plan.add_argument("--safety-mib", type=int, default=DEFAULT_SAFETY_MIB)
    p_plan.add_argument("--json", type=Path, default=None)

    p_wait = sub.add_parser("wait", help="Block until the consumer may run")
    p_wait.add_argument("--consumer", required=True, choices=sorted(CONSUMER_VRAM_MIB))
    p_wait.add_argument("--require-mib", type=int, default=None)
    p_wait.add_argument("--safety-mib", type=int, default=DEFAULT_SAFETY_MIB)
    p_wait.add_argument("--timeout", type=int, default=600)
    p_wait.add_argument("--poll", type=int, default=10)
    p_wait.add_argument("--json", type=Path, default=None)

    p_release = sub.add_parser(
        "release", help="Actively free the VRAM a consumer holds (unload / restart)"
    )
    p_release.add_argument("--consumer", required=True, choices=sorted(CONSUMER_VRAM_MIB))
    p_release.add_argument("--json", type=Path, default=None)

    p_seq = sub.add_parser(
        "sequence", help="Free contending consumers, then wait for the requested slot"
    )
    p_seq.add_argument("--consumer", required=True, choices=sorted(CONSUMER_VRAM_MIB))
    p_seq.add_argument(
        "--free",
        action="append",
        choices=sorted(CONSUMER_VRAM_MIB),
        default=None,
        help="Consumer(s) to release first; repeatable. Default: all other reclaimable consumers.",
    )
    p_seq.add_argument("--require-mib", type=int, default=None)
    p_seq.add_argument("--safety-mib", type=int, default=DEFAULT_SAFETY_MIB)
    p_seq.add_argument("--timeout", type=int, default=600)
    p_seq.add_argument("--poll", type=int, default=10)
    p_seq.add_argument("--json", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.command == "probe":
        snapshot = probe_gpu()
        _emit(snapshot, args.json)
        return 0 if snapshot["nvidia_smi_available"] else 1

    if args.command == "plan":
        snapshot = probe_gpu(consumer=args.consumer)
        decision = decide(
            args.consumer,
            snapshot,
            required_mib=args.require_mib,
            safety_mib=args.safety_mib,
        )
        _emit({"snapshot": snapshot, "decision": asdict(decision)}, args.json)
        return 0 if decision.decision == "run_now" else 2

    if args.command == "wait":
        decision, trail = wait_for_slot(
            args.consumer,
            required_mib=args.require_mib,
            safety_mib=args.safety_mib,
            timeout_s=args.timeout,
            poll_s=args.poll,
        )
        _emit({"decision": asdict(decision), "poll_trail": trail}, args.json)
        return 0 if decision.decision == "run_now" else 2

    if args.command == "release":
        result = release_consumer(args.consumer)
        _emit(asdict(result), args.json)
        return 0 if result.status in {"ok", "no_mechanism"} else 2

    if args.command == "sequence":
        payload = sequence_handoff(
            args.consumer,
            free_consumers=args.free,
            required_mib=args.require_mib,
            safety_mib=args.safety_mib,
            timeout_s=args.timeout,
            poll_s=args.poll,
        )
        _emit(payload, args.json)
        return 0 if payload["decision"]["decision"] == "run_now" else 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
