"""Seal the 2026-07-20 Docker-GPU-as-sole-CUDA-path wave (WSL repair deferred, honest).

Records that:
  * WSL Ubuntu-22.04 repair is BLOCKED (non-admin shell + prior ext4 VHD corruption)
    and therefore DEFERRED - not a human stop state for train/serve.
  * Docker-GPU is doubled-down as the SOLE/PRIMARY local CUDA train+serve path.
  * The serve+train Docker build paths are Ubuntu-22.04(WSL-distro)-INDEPENDENT and
    STATIC-coherent (both contract suites STATIC_PASS this wave), and host GPU
    passthrough is live-proven via `docker run --gpus all ... nvidia-smi`.

No build success, no torch-CUDA-in-container, no champion, no gold, no doctor-green
is claimed. The heavy image builds are a deliberate out-of-band next step, not run
this wave (protecting the running production CVAT stack + tight VRAM/daemon).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "docker_gpu_sole_cuda_path_wsl_deferred_20260720.json"

evidence = {
    "artifact_type": "docker_gpu_sole_cuda_path_wave",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "project_head_at_authoring": "eb17dd212011f89f11434d628163b11947e2dd4a",
    "branch": "codex/maskfactory-runtime-implementation",
    "authority": "docker_gpu_declared_sole_cuda_train_serve_path_wsl_repair_deferred_no_human_stop_state",
    "decision": "Double-down on Docker-GPU as the SOLE local CUDA train/serve runtime. WSL Ubuntu-22.04 repair is deferred (blocked: non-admin shell cannot run elevated e2fsck; on-disk ext4 corruption). Train/serve proceed without the WSL Ubuntu-22.04 distro.",
    "wsl_state": {
        "distro": "Ubuntu-22.04",
        "wsl_status": "Stopped",
        "default_distro": "Ubuntu-22.04",
        "docker_desktop_distro": "docker-desktop Running",
        "repair_blocked_reason": [
            "This session's shell is non-elevated (cannot run scripted e2fsck / tools/Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair without an interactive UAC prompt = a human wait state).",
            "Prior probes established on-disk ext4 corruption: `wsl -d Ubuntu-22.04 -- /bin/true` -> distribution failed to start (Error code 6 / E_FAIL) read-only fallback.",
        ],
        "repair_status": "DEFERRED_NOT_A_TRAIN_SERVE_BLOCKER",
        "only_dependent_lane": "live SAM 3.1 CUDA *WSL* smoke (MF-P2-11.07) - the one item that specifically needs the WSL distro; all other CUDA train/serve now routes through Docker-GPU.",
    },
    "gpu_passthrough_live_proof": {
        "command": "docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv",
        "gpu_name": "NVIDIA GeForce RTX 5060 Laptop GPU",
        "driver_version": "592.01",
        "memory_total_mib": 8151,
        "memory_free_mib_at_probe": 1247,
        "result": "RUNTIME_PASS_BOUNDED",
        "note": "GPU enumerated inside a host-NVIDIA container (nvidia-smi table emitted). VRAM tight (~1.2 GiB free) because production CVAT/nuclio + cvat269 rehearsal + sibling holders occupy the 8 GiB card; container teardown raced an 'unexpected EOF' AFTER the query row printed (cosmetic exit code, not a passthrough failure).",
    },
    "serve_path": {
        "image_tag": "maskfactory/serve:cu128",
        "dockerfile": "docker/Dockerfile.serve",
        "base_image": "python:3.11-slim (Docker Hub) + torch/torchvision cu128 wheels (bundle CUDA 12.8 runtime)",
        "wsl_ubuntu_distro_dependency": False,
        "requires_only": "host NVIDIA driver injected by `--gpus all`; no CUDA toolkit in image; no WSL Ubuntu-22.04 distro.",
        "static_contract": {
            "tool": "tools/verify_docker_serve_contract.py",
            "report": "qa/live_verification/docker_serve_contract_static_20260720T093557Z.json",
            "report_id": "dsc_e651e9b98b1ce5b49e1479f9",
            "proof_tier": "STATIC_PASS",
            "key_checks": [
                "base_is_slim_python_not_cuda_devel=true",
                "torch_cu128_index_used=true; torch/torchvision pins match env/requirements.lock.txt",
                "no_wsl_only_editable_git_or_file_deps=true",
                "compose maskfactory-serve: gpus_all_requested + loopback-only port + repo bind mount",
            ],
        },
        "live_smoke": "tools/smoke_docker_gpu_serve.py (NOT run this wave; image not built).",
    },
    "train_path": {
        "image_tag": "maskfactory/train:cu128",
        "dockerfile": "docker/Dockerfile.train",
        "base_image": "nvidia/cuda:12.8.0-devel-ubuntu22.04 (Docker Hub CUDA devel base - the container OS, INDEPENDENT of the local corrupt WSL Ubuntu-22.04 ext4 VHD)",
        "wsl_ubuntu_distro_dependency": False,
        "builds_from_source": "mmcv._ext for sm_120 (compute capability 12.0) at locked commit 57c4e25e, per env/openmmlab_training_stack.lock.json; torch 2.11.0+cu128.",
        "static_contract": {
            "tool": "tools/verify_docker_train_contract.py",
            "report": "qa/live_verification/docker_train_contract_static_20260720T093557Z.json",
            "report_id": "dtc_c652d7743284a510f911088d",
            "proof_tier": "STATIC_PASS",
        },
        "live_smoke": "tools/smoke_docker_gpu_train.py (NOT run; fails closed image_absent when maskfactory/train:cu128 missing - never triggers the heavy build).",
    },
    "builds_not_triggered_this_wave": {
        "reason": [
            "Build-safety guidance (Plan/DOCKER_RUNTIME_AND_SESSION_USE.md sec 6b): heavy from-source nvcc train build + ~7 GiB serve torch pull have crashed the constrained WSL2 daemon before.",
            "Engine currently loaded (37 containers: production CVAT v2.24 + cvat269 rehearsal + nuclio/pth-sam2) and a trivial nvidia-smi container just raced an 'unexpected EOF' -> daemon under stress.",
            "VRAM ~1.2 GiB free; C: ~76 GiB free (marginally above the 75 GiB repair floor).",
        ],
        "decision": "Deliberately DEFER the heavy builds out-of-band with WSL2 memory/disk headroom, to avoid crashing the production CVAT stack Kevin depends on. The build PATH viability (Ubuntu-independent + STATIC-coherent + GPU present) is what this wave establishes.",
        "next_deliberate_step": "docker compose -f docker/compose.gpu.yml build maskfactory-serve -> tools/smoke_docker_gpu_serve.py; then build maskfactory-train -> training-doctor in-container.",
    },
    "host_snapshot": {
        "docker_engine": "UP (client/server 29.6.1; 37 containers running)",
        "cvat_production": "v2.24 stack up (loopback localhost:8080)",
        "cvat269": "rehearsal stack up (isolated)",
        "nuclio_pth_sam2": "healthy",
        "c_free_gib": 76.0,
        "f_drive": "REMOVABLE / FLAPPING - present at this wave's probe (181.2 GiB free) but a sibling recorded it physically ABSENT at 2026-07-20T14:35Z; it is NOT relied upon. The Docker-GPU train/serve path (docker_data.vhdx, image builds, repo bind mount) is C:-resident and F:-INDEPENDENT.",
        "wsl_ubuntu_2204": "Stopped (repair deferred)",
    },
    "f_drive_independence": "The Docker-GPU CUDA train/serve path does not depend on F: (removable, flapping). Both the WSL Ubuntu-22.04 repair AND F: availability are irrelevant to building/running maskfactory/serve:cu128 and maskfactory/train:cu128, which live on C: via the docker-desktop WSL2 backend.",
    "claims_established_this_wave": [
        "gpu_container_passthrough_live (RTX 5060, driver 592.01, enumerated in --gpus all container)",
        "docker_serve_build_path_static_pass_and_wsl_independent",
        "docker_train_build_path_static_pass_and_wsl_independent",
        "docker_gpu_declared_sole_primary_cuda_train_serve_path",
        "wsl_ubuntu_2204_repair_deferred_without_blocking_train_or_serve",
    ],
    "claims_not_established": [
        "serve_image_build_success",
        "train_image_build_success",
        "torch_cuda_available_in_container",
        "serve_health_models_answered_in_container",
        "training_doctor_green_in_container",
        "champions>0",
        "autonomous_certified_gold",
        "doctor_all_green",
        "live_sam31_cuda_wsl_smoke",
    ],
    "honesty": [
        "This wave proves the Docker-GPU train/serve build PATH is viable and Ubuntu-22.04(WSL)-independent (STATIC contracts + live GPU passthrough); it does NOT claim the images were built or ran.",
        "WSL repair is genuinely blocked (non-admin) and honestly deferred - it only gates the WSL-specific SAM 3.1 smoke, not the Docker-GPU CUDA path.",
        "No tier inflation: champions=0, no gold, no doctor-green, no containerized runtime green.",
    ],
    "no_open_human_stop_states": True,
}

payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("SEALED", OUT.name, evidence["self_sha256"][:16])
