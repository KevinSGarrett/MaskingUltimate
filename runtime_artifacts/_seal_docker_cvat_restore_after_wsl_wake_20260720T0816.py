"""Seal the 2026-07-20 production CVAT restore after the sibling WSL/docker-desktop wake.

Non-destructive: engine was already answering `docker ps` (29.6.1) when this stream
started; work was limited to re-asserting the pinned production stack and running the
in-scope smokes. No volume wipe, no prune, no large image builds.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "docker_cvat_restore_after_wsl_wake_20260720T0816.json"

evidence = {
    "artifact_type": "docker_cvat_restore_after_wsl_wake_wave",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "project_head": "184313d107d60f6a1fce9935658130cfeb2e09d0",
    "branch": "codex/maskfactory-runtime-implementation",
    "authority": "autonomous_production_cvat_restore_non_destructive",
    "trigger": "Sibling woke docker-desktop after a WSL wake; engine already answering `docker ps` (client/server 29.6.1). This stream restored/re-asserted the pinned production CVAT v2.24 stack and ran the in-scope smokes while siblings owned migrate/serve.",
    "restore_sequence": [
        "Preflight probe: docker ps OK, server 29.6.1; 39 containers already auto-recovered (cvat v2.24 + cvat269 rehearsal + nuclio/pth-sam2). Re-read Plan/DOCKER_RUNTIME_AND_SESSION_USE.md per mandate.",
        "Initial endpoint probe: CVAT /api/server/about -> 'Bad Gateway' (cvat_server had just restarted ~5-7s prior); ollama /api/version -> 0.32.1; nuclio dashboard 127.0.0.1:8070 -> 200.",
        "python tools/bootstrap_cvat.py: hit a transient worker recreate race (exit 1 while recreating cvat_server + annotation/export/chunks/import workers).",
        "Re-asserted stack: `docker compose ... up -d cvat_server` (Started), then full `up -d` -> exit 0, all 19 production services Running.",
        "Polled /api/server/about -> version 2.24.0 (healthy on localhost:8080).",
        "smoke_cvat_sam2 first attempts hit 504 Gateway Timeout on /api/lambda/functions/pth-sam2 during ~54-67s SAM2 CPU cold-init (logs: 'SAM2 CPU initialization 0->100%'; torchvision inference warning confirms server-side completion).",
        "Mid-wave sibling churn: production traefik briefly lost its host port binding (localhost:8080 ConnectionRefused, then Bad Gateway warmup) during a sibling compose recreate cycle; it self-settled back to 127.0.0.1:8080->8080/tcp and cvat_server Django re-warmed to 2.24.0.",
        "Re-ran smoke_cvat_sam2 warm -> PASS (task_id=1, latency 28.128s, foreground_pixels=21491, all 5 mask checks green).",
        "smoke_ollama_vlm -> PASS (qwen2.5vl:7b, latency 4.305s, verdict=pass, confidence=1).",
        "docker stats --no-stream sampled OK: 39 containers; nuclio-nuclio-pth-sam2 ~120% CPU / 871MiB of 8GiB during warm inference; cvat_server ~3.8% / 403MiB.",
    ],
    "engine_status": {
        "final": "UP",
        "docker_server_version": "29.6.1",
        "context": "docker-desktop",
        "containers_running": 39,
        "docker_ps_ok": True,
        "docker_stats_ok": True,
        "note": "Preferred docker ps / docker stats / HTTP probes over docker info per mandate (docker info hung >90s twice under concurrent sibling engine load and was aborted, not trusted).",
        "sibling_churn_observed": "Production traefik lost + regained its 127.0.0.1:8080 host binding during a concurrent sibling compose recreate; no action taken beyond re-probing until settled.",
    },
    "cvat": {
        "production_about": "2.24.0",
        "endpoint": "http://localhost:8080/api/server/about",
        "bound": "loopback (localhost:8080)",
        "stacks_present": [
            "production cvat v2.24 (cvat_server/ui/db/utils/workers + traefik v3.6.1)",
            "cvat269 v2.69 migration-rehearsal stack (isolated on 127.0.0.1:18080, untouched)",
        ],
        "warmup_window": "Bad Gateway / ConnectionRefused windows after each recreate; settled to 200/2.24.0 within ~90s.",
        "bootstrap_note": "First bootstrap_cvat.py exited 1 on a worker recreate race; re-asserted cleanly via direct compose up -d (exit 0).",
    },
    "nuclio_sam2": {
        "container": "nuclio-nuclio-pth-sam2",
        "health": "healthy",
        "function_state": "ready",
        "smoke_tool": "tools/smoke_cvat_sam2.py",
        "smoke_result": "pass",
        "smoke_detail": "cvat_sam2_smoke=pass; task_id=1; latency_seconds=28.128; foreground_pixels=21491",
        "report": "qa/reports/cvat_sam2_smoke.json",
        "cold_start_note": "First invocations timed out (504) during ~54-67s SAM2 CPU cold-init that races CVAT's ~60s lambda-proxy timeout; warm re-run passed at 28.1s. SAM2 ran on CPU this wave (siblings hold GPU per GPU_SEQUENCING_AND_VRAM_BUDGET.md).",
    },
    "ollama": {
        "host": "UP",
        "version": "0.32.1",
        "endpoint": "http://127.0.0.1:11434/api/version",
        "runtime": "native/host loopback process (no ollama Docker container present in `docker ps`)",
        "smoke_tool": "tools/smoke_ollama_vlm.py",
        "smoke_result": "pass",
        "smoke_detail": "ollama_vlm_smoke=pass; model=qwen2.5vl:7b; latency_seconds=4.305; verdict=pass; confidence=1",
    },
    "non_destructive_guarantees": [
        "No docker system prune / prune -a --volumes.",
        "No CVAT volume wipe / no docker volume rm.",
        "No large image builds (siblings own migrate/serve).",
        "No Docker Desktop factory reset; no edits to compose pins or settings-store.json.",
        "Restore limited to re-asserting the existing pinned stack via compose up -d; all prior containers/volumes preserved.",
    ],
    "honesty": [
        "Engine was already up (sibling-woken) before this stream; this wave restored the production CVAT stack + smokes only.",
        "SAM2 cold-start 504s occurred and are documented (not hidden); a genuine warm re-run passed.",
        "SAM2 ran on CPU; GPU container passthrough not independently proven here.",
        "No tier inflation: champions=0, no autonomous_certified_gold, no doctor-all-green claim from this wave.",
        "cvat269 rehearsal stack left isolated and untouched; production bridge stays on localhost:8080.",
    ],
    "claims_established_this_wave": [
        "docker_engine_healthy (ps + stats OK, 39 containers, server 29.6.1)",
        "cvat_2_24_live (about=2.24.0 on localhost:8080, loopback)",
        "nuclio_pth_sam2_smoke_pass (warm, latency 28.128s)",
        "ollama_vlm_smoke_pass (qwen2.5vl:7b)",
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
