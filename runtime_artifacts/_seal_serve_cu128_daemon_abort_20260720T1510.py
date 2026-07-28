"""Seal serve:cu128 build abort after Docker daemon death (2026-07-20).

Honest RUNTIME_BLOCKED. Does not claim image build, smoke, or CVAT restore.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "serve_cu128_daemon_abort_20260720T1510.json"


def _head() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def main() -> None:
    evidence = {
        "artifact_type": "serve_cu128_daemon_abort_wave",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "project_head_at_authoring": _head(),
        "branch": "codex/maskfactory-runtime-implementation",
        "authority": (
            "FULL AUTONOMY: build maskfactory/serve:cu128 + tools/smoke_docker_gpu_serve.py; "
            "Abort if daemon dies; restore CVAT 2.24; seal; commit+push."
        ),
        "mandate_applied": "Abort if daemon dies (no further heavy build / restart thrash).",
        "proof_tier": "RUNTIME_BLOCKED",
        "result": "ABORTED_DAEMON_DEATH",
        "sequence": [
            "Preflight: docker CLI client 29.6.1 present; named pipe dockerDesktopLinuxEngine ABSENT; C: free ~75.21 GiB; Ollama host 0.32.1 UP; CVAT unreachable.",
            "Wake 1: launched Docker Desktop; engine came UP (server 29.6.1); docker ps showed production cvat/*:v2.24.0 + cvat269 + nuclio/pth-sam2 recovering (~1 min uptime).",
            "CVAT /api/server/about still 404/warming when first probed; image maskfactory/serve:cu128 ABSENT.",
            "Prior sibling build log runtime_artifacts/_serve_cu128_build_20260720.log shows torch cu128 pip reached nvidia-cudnn-cu12 ~657.9 MB download then: ERROR failed to build: rpc Unavailable EOF (daemon died mid-wheel).",
            "bootstrap_cvat.py then failed: npipe dockerDesktopLinuxEngine missing again (daemon dead).",
            "Abort path: stopped thrashing heavy build; one careful wsl --shutdown + Desktop relaunch; docker-desktop WSL stayed Stopped / flapped Running without Linux engine pipe.",
            "Second wake attempt started com.docker.service + explicit wsl -d docker-desktop; still no dockerDesktopLinuxEngine pipe after multi-minute poll.",
            "Final probes: Ubuntu-22.04 Stopped; docker-desktop Stopped; pipes absent; CVAT timeout; Ollama 0.32.1 still UP; C: free collapsed ~75->~30.76 GiB during failed wake cycles (vhdx still 68.11 GiB on C:); no prune/wipe performed.",
        ],
        "engine_status": {
            "final": "DOWN",
            "docker_client_version": "29.6.1",
            "docker_server_version": None,
            "context": "desktop-linux",
            "named_pipe_dockerDesktopLinuxEngine": False,
            "wsl_list": {
                "Ubuntu-22.04": "Stopped",
                "docker-desktop": "Stopped",
                "Cursor-Agent-WSL1": "Stopped",
            },
            "com_docker_service": "Running (last probe) but engine pipe absent",
            "restart_cycles_attempted": 2,
            "further_restarts_aborted": True,
            "prior_build_failure": (
                "runtime_artifacts/_serve_cu128_build_20260720.log EOF during "
                "nvidia-cudnn-cu12 download inside Dockerfile.serve torch cu128 layer"
            ),
        },
        "disk": {
            "c_free_gib_at_wave_start": 75.21,
            "c_free_gib_mid_wave_peak_observed": 90.88,
            "c_free_gib_at_abort": 30.76,
            "docker_data_vhdx_gib": 68.11,
            "docker_data_vhdx_path": r"C:\Users\kevin\AppData\Local\Docker\wsl\disk\docker_data.vhdx",
            "note": (
                "C: free collapsed during failed Docker Desktop wake cycles; "
                "below safe ~60 GiB serve-build gate. No docker system prune / volume wipe."
            ),
        },
        "serve_image": {
            "tag": "maskfactory/serve:cu128",
            "dockerfile": "docker/Dockerfile.serve",
            "build_attempted_this_wave": False,
            "build_aborted_reason": "daemon died; mandate abort; C: free collapsed to ~31 GiB",
            "image_present": False,
            "smoke_tool": "tools/smoke_docker_gpu_serve.py",
            "smoke_run": False,
        },
        "cvat": {
            "restore_attempted": True,
            "restore_succeeded": False,
            "bootstrap_tool": "tools/bootstrap_cvat.py",
            "bootstrap_error": "docker pull alpine:3.17 failed — npipe dockerDesktopLinuxEngine missing",
            "production_target": "localhost:8080 CVAT v2.24.0",
            "about_at_abort": "unreachable (timeout)",
            "note": (
                "Containers were briefly visible as Up (cvat/server:v2.24.0) during the short "
                "engine-up window, then lost when the daemon died; could not re-assert stack "
                "without a stable engine."
            ),
        },
        "ollama": {
            "host": "UP",
            "version": "0.32.1",
            "endpoint": "http://127.0.0.1:11434/api/version",
            "runtime": "native/host loopback (independent of Docker daemon)",
        },
        "non_destructive_guarantees": [
            "No docker system prune / prune -a --volumes.",
            "No CVAT volume wipe / docker volume rm.",
            "No Docker Desktop factory reset.",
            "No edits to compose pins or settings-store.json.",
            "No further wake thrash after abort decision (protect engine + disk).",
            "Serve build not re-launched after daemon death.",
        ],
        "claims_established": [
            "serve_build_aborted_on_daemon_death",
            "prior_sibling_torch_cu128_layer_eof_documented",
            "c_free_collapsed_during_wake_cycles_documented",
            "ollama_host_still_up_0_32_1",
        ],
        "claims_not_established": [
            "serve_image_build_success",
            "torch_cuda_available_in_container",
            "serve_health_models_answered_in_container",
            "cvat_2_24_restored",
            "smoke_docker_gpu_serve_pass",
            "train_image_build_success",
            "doctor_all_green",
            "champions>0",
            "autonomous_certified_gold",
        ],
        "honesty": [
            "RUNTIME_BLOCKED is the honest tier; no RUNTIME_PASS_BOUNDED inflation.",
            "CVAT restore could not complete because the engine would not stay up.",
            "Disk headroom that looked sufficient at wave start (~75 GiB) collapsed to ~31 GiB during wake failures; heavy torch cu128 rebuild would be unsafe even if the daemon returned.",
            "Desktop backend logs showed repeated 'backend already running, signaling show-dashboard' without publishing dockerDesktopLinuxEngine.",
        ],
        "next_deliberate_step": (
            "Stabilize Docker Desktop once (no parallel builds): confirm named pipe + "
            "docker ps healthy + C: free >= ~60 GiB; bootstrap_cvat.py for 2.24; sole "
            "builder: docker build -f docker/Dockerfile.serve -t maskfactory/serve:cu128 . ; "
            "then python tools/smoke_docker_gpu_serve.py --serve-image maskfactory/serve:cu128."
        ),
        "no_open_human_stop_states": True,
        "evidence_refs": [
            "runtime_artifacts/_serve_cu128_build_20260720.log",
            "runtime_artifacts/_serve_cu128_build_coordination_20260720.json",
            "qa/live_verification/_bootstrap_cvat_serve_build_20260720T0949.log",
        ],
    }
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("SEALED", OUT.name, evidence["self_sha256"], "tier=", evidence["proof_tier"])


if __name__ == "__main__":
    main()
