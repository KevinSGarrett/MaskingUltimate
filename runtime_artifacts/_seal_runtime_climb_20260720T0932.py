"""Seal the 2026-07-20 autonomous runtime-climb wave (peak PASS=7 FAIL=4).

Honest, no tier inflation. Captures the peak doctor climb + live smokes, then
the later Docker flap / WSL intermittency observed when F: (USB Seagate) woke.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "runtime_climb_20260720T0932.json"

evidence = {
    "artifact_type": "runtime_climb_doctor_fail_reduction_wave",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "project_head_at_seal_start": "139b45368edf8ff5e90085a04fb465f07ed8c2f1",
    "branch": "codex/maskfactory-runtime-implementation",
    "authority": "autonomous_full_autonomy_runtime_climb_zero_human_wait",
    "honesty": [
        "No tier inflation: champions=0; no gold/autonomous_certified_gold; no doctor-green; no PRODUCTION_EVIDENCE_PASS.",
        "Peak doctor this wave: PASS=7 WARN=1 FAIL=4 (from PASS=3 FAIL=9). Later re-run after F: wake + WSL torch timeout + Docker flap: PASS=5 FAIL=6 — not claimed as the climb result.",
        "F: is USB removable Seagate BUP Slim (sibling abort seal). data/ stays on C: backup junction; NEVER host docker_data.vhdx on F:.",
        "GPU CUDA container proof (RTX 5060) is the documented substitute for WSL torch; does NOT clear WSL-specific doctor checks.",
    ],
    "peak_docker_engine": {
        "status": "UP_AT_PEAK",
        "server_version": "29.6.1",
        "context": "docker-desktop",
        "production_cvat": "v2.24.0 on localhost:8080",
        "nuclio_pth_sam2": "healthy",
        "no_destructive_ops": "No prune, no volume wipe, no factory reset.",
    },
    "cvat_server_repair_at_peak": {
        "found_state": "Exited (255)",
        "root_cause": "bind-mount data/ was a dangling junction while F: USB was asleep/disconnected",
        "action": "temporary junction to data_c_backup_relocated; docker start cvat_server; later sibling kept data/ on C: backup permanently (correct for USB F:)",
        "result_at_peak": "cvat_server Up; /api/server/about -> 200 version 2.24.0",
    },
    "data_path": {
        "final_junction": "C:\\Comfy_UI_Main_Masking\\data -> data_c_backup_relocated (fixed-disk C:)",
        "f_status": "USB Seagate intermittent; present with MaskFactory_DataRelocated + Ubuntu VHD when awake",
        "destructive": False,
    },
    "gpu_sequencing": {
        "policy": "Plan/GPU_SEQUENCING_AND_VRAM_BUDGET.md; tools/gpu_sequencer.py",
        "card": "NVIDIA GeForce RTX 5060 Laptop GPU (8151 MiB)",
        "actions": [
            "probe: initially ~7684 MiB free, no foreign holder, gpu.lock absent",
            "released Ollama VLM after doctor residency -> free ~7785 MiB -> nuclio-sam2 run_now",
            "strict sequence: SAM2 smoke then ollama-vlm plan run_now + smoke (never co-resident)",
            "cleared stale gpu.lock (dead pipeline pid 47184) mid-wave; later live pipeline lock (pid 26432) left untouched",
        ],
        "plans": [
            "qa/live_verification/gpu_sequence_sam2_20260720T0930.json",
            "qa/live_verification/gpu_plan_ollama_vlm_20260720T0932.json",
        ],
    },
    "doctor": {
        "session_start": {"pass": 3, "warn": 0, "skip": 0, "fail": 9},
        "peak_after_cvat_data_gpu_fix": {"pass": 7, "warn": 1, "skip": 0, "fail": 4},
        "peak_fails_cleared": [
            "cvat_api FAIL->PASS 2.24.0",
            "cvat_project FAIL->PASS project_count=2",
            "nuclio_interactor FAIL->PASS pth-sam2 foreground=21491",
            "check_disk_free FAIL->WARN 76.0 GiB",
            "check_sqlite FAIL->PASS sqlite_writable",
        ],
        "peak_remaining_fail": {
            "checks": ["torch_cuda", "registered_models", "wsl_backing_store", "wsl_roundtrip"],
            "note_at_peak": "F: USB was asleep so Ubuntu VHD path looked missing; later F: wake cleared wsl_backing_store + wsl_roundtrip PASS, but torch_cuda timed out (30s) and registered_models still FAIL",
        },
        "later_rerun_after_f_wake": {
            "pass": 5,
            "warn": 1,
            "fail": 6,
            "new_pass": ["wsl_backing_store", "wsl_roundtrip"],
            "regression": "cvat_*/nuclio/ollama FAILs during Docker named-pipe flap mid long WSL timeout; NOT the climb claim",
        },
    },
    "runtime_smokes_at_peak": {
        "cvat_sam2": {
            "result": "pass",
            "task_id": 1,
            "latency_seconds": 17.826,
            "foreground_pixels": 21491,
        },
        "ollama_vlm": {
            "result": "pass",
            "model": "qwen2.5vl:7b",
            "latency_seconds": 16.203,
            "verdict": "pass",
            "confidence": 1,
        },
        "gpu_container_cuda": {
            "result": "pass",
            "gpu": "NVIDIA GeForce RTX 5060 Laptop GPU",
            "driver": "592.01",
            "memory_total_mib": 8151,
        },
    },
    "post_peak_docker_flap": {
        "status": "ENGINE_FLAPPED",
        "symptom": "dockerDesktopLinuxEngine named pipe missing after WSL/torch timeout + concurrent sibling load",
        "action": "non-destructive Docker Desktop relaunch; waiting for engine; no prune/wipe",
        "related_sibling_seals": [
            "qa/live_verification/fleet_status_20260720T1502.json",
            "qa/live_verification/docker_migrate_abort_usb_removable_f_20260720T1437Z.json",
        ],
    },
    "disk": {
        "c_free_gib_at_peak": 75.95,
        "f_drive": "USB Seagate BUP Slim — intermittent; not for docker_data.vhdx or durable data/ junction",
    },
    "champions": 0,
    "mode_b_predict": "AWAITING_RUNTIME (champions=0)",
    "claims_not_established": [
        "doctor_all_green",
        "wsl_torch_cuda_live",
        "autonomous_certified_gold",
        "champions>0",
        "Main-complete / MF-P6-12.06",
        "PRODUCTION_EVIDENCE_PASS",
        "steady_state_docker_engine",
    ],
    "runtime_tier": "RUNTIME_PASS_BOUNDED (peak live CVAT 2.24 + Nuclio SAM2 + Ollama VLM + GPU container; WSL torch path still blocked; Docker later flapped)",
    "no_open_human_stop_states": True,
    "next_agent": [
        "Restore Docker Desktop engine (non-destructive relaunch already started); re-warm CVAT 2.24 / nuclio pth-sam2",
        "Keep data/ on C: backup; do not migrate docker_data.vhdx to USB F:",
        "Continue Docker-GPU as primary CUDA path; WSL Ubuntu e2fsck only from elevated shell",
    ],
}

payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("SEALED", OUT.name, evidence["self_sha256"][:16])
