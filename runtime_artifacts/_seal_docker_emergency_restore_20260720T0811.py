"""Seal the 2026-07-20 Docker emergency restore wave (non-destructive, honest)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "docker_emergency_restore_20260720T0811.json"

evidence = {
    "artifact_type": "docker_emergency_restore_wave",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "project_head": "184313d107d60f6a1fce9935658130cfeb2e09d0",
    "branch": "codex/maskfactory-runtime-implementation",
    "authority": "autonomous_docker_emergency_restore_non_destructive",
    "trigger": "Sibling agent found Docker engine DOWN: com.docker.service reported Stopped, docker info hangs, CVAT/nuclio unreachable. Emergency non-destructive restore requested (no volume wipe, no prune -a --volumes).",
    "restore_sequence": [
        "Probe: docker ps -> npipe dockerDesktopLinuxEngine missing (engine down). com.docker.service Running but Docker Desktop backend process absent; docker-desktop WSL distro Running.",
        "Launch 1: started 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe'; polled docker ps -> ENGINE UP after ~90s; 39 containers auto-recovered (cvat v2.24 + cvat269 rehearsal + nuclio/pth-sam2).",
        "docker stats --no-stream OK; ollama /api/version 200 (0.32.1); CVAT /api/server/about warmed to 2.24.0 after ~90s Bad Gateway window; lambda gateway warmed 502->401.",
        "First smoke_cvat_sam2 hit ConnectionReset during pth-sam2 cold inference; engine then found DOWN again (com.docker.service Stopped, docker-desktop distro Stopped) - crash during SAM2 GPU/CPU cold-start.",
        "Launch 2: relaunched Docker Desktop; polled docker ps -> ENGINE UP again; 39 containers recovered; docker stats OK; CVAT warmed to 2.24.0; lambda 502->401.",
        "smoke_cvat_sam2 attempt hit 504 Gateway Timeout on /api/lambda/functions/pth-sam2 during ~75s CPU cold-init of the SAM2 processor (logs: 'SAM2 CPU initialization 0->100%' then 'Processor started'); engine stayed UP (39 containers).",
        "Re-ran smoke_cvat_sam2 warm -> PASS (task_id=1, latency 14.59s, foreground_pixels=21491); engine stable at 39 containers.",
    ],
    "engine_status": {
        "final": "UP",
        "docker_client_version": "29.6.1",
        "docker_server_version": "29.6.1",
        "context": "docker-desktop",
        "containers_running": 39,
        "docker_ps_ok": True,
        "docker_stats_ok": True,
        "restart_cycles": 2,
        "mid_restore_crash": "One engine crash observed during the first SAM2 cold-start inference (ConnectionReset then service Stopped); recovered by a second non-destructive Docker Desktop relaunch.",
        "note": "Preferred docker ps / docker stats / HTTP probes over docker info per mandate.",
    },
    "cvat": {
        "production_about": "2.24.0",
        "endpoint": "http://localhost:8080/api/server/about",
        "bound": "loopback (localhost:8080)",
        "stacks_present": [
            "production cvat v2.24 (cvat_server/ui/db/utils/workers + traefik v3.6.1)",
            "cvat269 v2.69 migration-rehearsal stack (isolated, untouched)",
        ],
        "warmup_window": "~90s of Bad Gateway/502 after each engine relaunch before 200/2.24.0.",
    },
    "nuclio_sam2": {
        "container": "nuclio-nuclio-pth-sam2",
        "health": "healthy",
        "smoke_tool": "tools/smoke_cvat_sam2.py",
        "smoke_result": "pass",
        "smoke_detail": "cvat_sam2_smoke=pass; task_id=1; latency_seconds=14.590; foreground_pixels=21491",
        "cold_start_note": "First invocation timed out (504) during ~75s SAM2 CPU cold-init; warm re-run passed. SAM2 initialized on CPU this wave (sibling ComfyUI holds most of the 8 GiB GPU per GPU_SEQUENCING_AND_VRAM_BUDGET.md).",
    },
    "ollama": {
        "host": "UP",
        "version": "0.32.1",
        "endpoint": "http://127.0.0.1:11434/api/version",
        "smoke_tool": "tools/smoke_ollama_vlm.py",
        "smoke_result": "pass",
        "smoke_detail": "ollama_vlm_smoke=pass; model=qwen2.5vl:7b; latency_seconds=61.065; verdict=pass; confidence=1",
    },
    "non_destructive_guarantees": [
        "No docker system prune -a --volumes.",
        "No CVAT volume wipe / no docker volume rm.",
        "No Docker Desktop factory reset.",
        "No edits to compose pins or settings-store.json.",
        "Restore performed purely by relaunching Docker Desktop and letting the daemon recover its existing volumes; all prior containers/volumes preserved.",
    ],
    "honesty": [
        "Docker engine crashed once mid-restore during SAM2 cold-start; recovered non-destructively (documented, not hidden).",
        "Restore restored runtime availability only; no tier inflation: champions=0, no autonomous_certified_gold, no doctor-all-green claim from this wave.",
        "SAM2 ran on CPU this wave; GPU passthrough not independently proven here.",
    ],
    "claims_established_this_wave": [
        "docker_engine_healthy (ps + stats OK, 39 containers, client/server 29.6.1)",
        "cvat_2_24_live (about=2.24.0 on localhost:8080)",
        "nuclio_pth_sam2_smoke_pass",
        "ollama_vlm_smoke_pass",
    ],
    "claims_not_established": [
        "gpu_container_passthrough_proven",
        "doctor_all_green",
        "autonomous_certified_gold",
        "champions>0",
    ],
    "no_open_human_stop_states": True,
}

payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("SEALED", OUT.name, evidence["self_sha256"][:16])
