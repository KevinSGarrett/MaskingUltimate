"""Seal: train:cu128 build NOT started — Docker DOWN + C: CRITICAL (2026-07-20).

Honest RUNTIME_BLOCKED. No image build, no training-doctor smoke, no tier inflation.
Further Docker wake thrash aborted (protect engine + disk).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "train_cu128_blocked_20260720T1526.json"


def _head() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
    )
    return (out.stdout or "").strip()


def _run(cmd: list[str], *, timeout: float = 8) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            cmd,
            returncode=124,
            stdout="",
            stderr=f"TimeoutExpired after {timeout}s: {exc}",
        )


def _probe() -> dict:
    import shutil

    usage = shutil.disk_usage("C:\\")
    c_free = usage.free / (1024**3)
    pipe = Path("\\\\.\\pipe\\dockerDesktopLinuxEngine").exists()
    # When the named pipe is absent, skip hanging docker CLI calls entirely.
    if pipe:
        docker_info = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=12)
        serve = _run(
            ["docker", "image", "inspect", "maskfactory/serve:cu128", "--format", "{{.Id}}"],
            timeout=12,
        )
        train = _run(
            ["docker", "image", "inspect", "maskfactory/train:cu128", "--format", "{{.Id}}"],
            timeout=12,
        )
    else:
        docker_info = subprocess.CompletedProcess(
            ["docker", "info"], 1, "", "skipped: named pipe absent"
        )
        serve = subprocess.CompletedProcess(["docker", "image", "inspect"], 1, "", "skipped")
        train = subprocess.CompletedProcess(["docker", "image", "inspect"], 1, "", "skipped")
    vhdx = Path.home() / "AppData" / "Local" / "Docker" / "wsl" / "disk" / "docker_data.vhdx"
    vhdx_gib = (vhdx.stat().st_size / (1024**3)) if vhdx.exists() else None
    ollama = _run(
        ["curl.exe", "-s", "--max-time", "3", "http://127.0.0.1:11434/api/version"],
        timeout=5,
    )
    cvat = _run(
        ["curl.exe", "-s", "--max-time", "3", "http://localhost:8080/api/server/about"],
        timeout=5,
    )
    return {
        "c_free_gib": round(c_free, 2),
        "named_pipe_dockerDesktopLinuxEngine": pipe,
        "docker_server_version": (docker_info.stdout or "").strip() or None,
        "docker_info_exit": docker_info.returncode,
        "docker_info_stderr_tail": (docker_info.stderr or "")[-300:],
        "serve_cu128_present": serve.returncode == 0 and bool((serve.stdout or "").strip()),
        "train_cu128_present": train.returncode == 0 and bool((train.stdout or "").strip()),
        "docker_data_vhdx_gib": round(vhdx_gib, 2) if vhdx_gib is not None else None,
        "docker_data_vhdx_path": str(vhdx),
        "ollama_version_raw": (ollama.stdout or "").strip()[:200],
        "cvat_about_raw": (cvat.stdout or "").strip()[:200],
        "cvat_reachable": bool((cvat.stdout or "").strip()) and cvat.returncode == 0,
    }


def main() -> None:
    probe = _probe()
    evidence = {
        "artifact_type": "train_cu128_build_blocked_wave",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "project_head_at_authoring": _head(),
        "branch": "codex/maskfactory-runtime-implementation",
        "authority": (
            "FULL AUTONOMY: after serve:cu128 exists OR BuildKit free, build "
            "maskfactory/train:cu128 + training-doctor smoke; seal; commit+push."
        ),
        "verdict": "RUNTIME_BLOCKED",
        "gate_evaluation": {
            "serve_cu128_exists": probe["serve_cu128_present"],
            "buildkit_free": False,
            "buildkit_free_reason": (
                "Docker engine named pipe absent; BuildKit unavailable. "
                "Cannot claim BuildKit free while daemon is DOWN."
            ),
            "build_allowed": False,
        },
        "why_blocked": [
            f"C: free {probe['c_free_gib']} GiB CRITICAL (<< 75 GiB floor; << ~60 GiB heavy-build gate)",
            "dockerDesktopLinuxEngine named pipe absent (engine DOWN)",
            "maskfactory/serve:cu128 absent (sibling serve abort sealed earlier)",
            "train:cu128 from-source mmcv._ext sm_120 build would thrash 68.11 GiB docker_data.vhdx unsafely",
        ],
        "actions_taken": [
            "Live-probed Docker Desktop / named pipe / C: free / serve+train image inspect",
            "Hard-restart + wait loops attempted earlier this wave; engine flapped then stayed DOWN",
            "Further Docker wake thrash ABORTED (protect engine + disk per DOCKER_RUNTIME mandate)",
            "Did NOT start docker compose build maskfactory-train",
            "Did NOT run tools/smoke_docker_gpu_train.py (would fail closed image_absent)",
        ],
        "live_probe": probe,
        "build_attempted": False,
        "training_doctor_smoke_attempted": False,
        "image_tag": "maskfactory/train:cu128",
        "dockerfile": "docker/Dockerfile.train",
        "compose_service": "maskfactory-train",
        "smoke_tool": "tools/smoke_docker_gpu_train.py",
        "related_evidence": [
            "qa/live_verification/serve_cu128_daemon_abort_20260720T1510.json",
            "qa/live_verification/serve_abort_gold_drive_20260720T1515.json",
            "qa/live_verification/fleet_status_20260720T1505.json",
            "qa/live_verification/_disk_reclaim_ephemeral_20260720T1517.json",
            "runtime_artifacts/_serve_cu128_build_coordination_20260720.json",
        ],
        "claims_established": [
            "train_cu128_build_not_started",
            "training_doctor_smoke_not_run",
            "gate_serve_absent_and_buildkit_unavailable",
            "c_free_critical_blocks_heavy_cuda_devel_build",
            "further_docker_restart_thrash_aborted",
        ],
        "claims_not_established": [
            "train_image_build_success",
            "training_doctor_green_in_container",
            "mmcv._ext_sm_120_compiled",
            "serve_image_build_success",
            "doctor_all_green",
            "champions>0",
            "autonomous_certified_gold",
        ],
        "honesty": [
            "RUNTIME_BLOCKED is the honest tier; no RUNTIME_PASS_BOUNDED inflation.",
            "serve:cu128 does not exist and BuildKit is not free (daemon DOWN) — "
            "both gates for starting train:cu128 fail closed.",
            "C: ~15 GiB free cannot host CUDA 12.8 devel + from-source MMCV ops build safely.",
            "No prune, volume wipe, factory reset, or USB docker_data.vhdx migration.",
        ],
        "non_destructive_guarantees": [
            "No docker system prune / prune -a --volumes",
            "No CVAT volume wipe",
            "No Docker Desktop factory reset",
            "No migrate docker_data.vhdx to USB F:",
            "No train image build launched",
            "No further engine wake thrash after abort decision",
        ],
        "next_deliberate_step": (
            "1) Ephemeral reclaim until C: free >= 75 GiB (no governed wipe). "
            "2) Single stable Docker Desktop wake (named pipe + docker ps healthy). "
            "3) If serve:cu128 still absent and BuildKit free: finish serve first OR "
            "sole-build train:cu128 via `docker compose -f docker/compose.gpu.yml build "
            "maskfactory-train`. 4) `python tools/smoke_docker_gpu_train.py "
            "--train-image maskfactory/train:cu128 --output qa/live_verification/"
            "smoke_docker_gpu_train_<ts>.json`."
        ),
        "no_open_human_stop_states": True,
    }
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("SEALED", OUT.name, evidence["self_sha256"][:16], "verdict=", evidence["verdict"])
    print("c_free_gib=", probe["c_free_gib"], "pipe=", probe["named_pipe_dockerDesktopLinuxEngine"])


if __name__ == "__main__":
    main()
