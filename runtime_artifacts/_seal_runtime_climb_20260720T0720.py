"""Seal the 2026-07-20 disk-safe runtime-climb wave (honest, no tier inflation)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "runtime_climb_disk_safe_20260720T0720.json"

evidence = {
    "artifact_type": "runtime_climb_disk_safe_wave",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "project_head": "447b0f9b",
    "branch": "codex/maskfactory-runtime-implementation",
    "authority": "autonomous_disk_safe_runtime_climb_zero_human_wait",
    "honesty": [
        "No tier inflation: champions=0; no gold/autonomous_certified_gold; no doctor-green; no PRODUCTION_EVIDENCE_PASS.",
        "Docker serve:cu128 image NOT built this wave; engine RUNTIME_BLOCKED (documented, not hidden).",
        "Autonomous-gold admission remains honestly insufficient (0 machine_verified_candidate); not fabricated.",
        "Isolated Main consumer is NOT real Comfy_UI_Main; HARD MF-P6-11.02/11.07/12.05/12.06 remain OPEN.",
    ],
    "disk": {
        "c_free_gib_at_reclaim_start": 17.18,
        "c_free_gib_after_ephemeral_reclaim": 28.29,
        "c_free_gib_current": 29.15,
        "ephemeral_reclaimed_gib": 11.11,
        "f_free_gib": 249.42,
        "reclaimed_scope": [
            "pip cache",
            "uv cache",
            "npm-cache (LOCALAPPDATA, ~4.32 GiB)",
            "torch hub cache",
            "user Temp (~7.44 GiB, locked files skipped)",
        ],
        "not_touched": [
            "HuggingFace cache (~3.3 GiB weights retained)",
            "models/",
            "MaskedWarehouse",
            "data/ (F: junction)",
            "Docker volumes / docker_data.vhdx",
            "CVAT v2.24 data",
            ".ollama",
            "qa/live_verification/* seals",
            "Plan/",
            "packages",
        ],
        "governed_wipe_used": False,
        "docker_builder_prune_run": False,
        "docker_builder_prune_reason": "engine crashed on vhdx recovery before a bounded CLI call could complete; not run to avoid another crash cycle",
    },
    "docker_engine": {
        "status": "RUNTIME_BLOCKED",
        "symptom_sequence": [
            "initial probe: npipe dockerDesktopLinuxEngine missing (engine down)",
            "relaunch 1: GUI + backend up, docker CLI (version/ps) timed out >40s",
            "clean restart (kill procs + wsl --shutdown + relaunch): distro Running, pipe present",
            "docker ps -> 500 Internal Server Error (daemon degraded during containerd load)",
            "after settle: version/df timed out 60s; then named pipe vanished again (engine crashed on recovery)",
        ],
        "docker_data_vhdx_gib_on_c": 68.11,
        "likely_root_cause": "daemon cannot safely recover its 68.11 GiB dynamic ext4 vhdx with only ~29 GiB free on C:; each restart triggers a crash-prone recovery cycle (possible ext4 journal damage inside docker_data.vhdx, mirroring the corrupt Ubuntu-22.04 distro).",
        "ollama_host": "UP (0.32.1) - host process, unaffected by Docker engine",
        "cvat": "DOWN (containers cannot start while engine unhealthy)",
        "repair_paths_next_agent": [
            "Free C: to >=75 GiB (bigger reclaim / relocate large user data) so the daemon can recover the vhdx, then relaunch.",
            "Relocate Docker Desktop 'Disk image location' to F: (admin-free GUI migration preserves CVAT volumes) - do NOT blind-edit settings-store.json (risks fresh empty volume set).",
            "Elevated shell: wsl --shutdown then Optimize-VHD / diskpart compact docker_data.vhdx (+ e2fsck of its ext4) to reclaim C: and repair the journal.",
        ],
        "not_done_destructive": "No docker system prune -a --volumes, no CVAT volume wipe, no Docker Desktop factory reset (forbidden without Kevin authorization).",
    },
    "serve_image": {
        "image": "maskfactory/serve:cu128",
        "built_this_wave": False,
        "reason": "engine RUNTIME_BLOCKED; per mandate, aborted rather than risk another OOM/recovery crash on the ~7 GiB torch cu128 install.",
        "smoke": "NOT_RUN",
    },
    "autonomous_gold": {
        "tool": "tools/build_autonomous_gold_admission.py",
        "status": "insufficient_autonomous_verified_samples",
        "machine_verified_candidate_count": 0,
        "calibrated_auto_accepted_count": 0,
        "seal": "qa/live_verification/autonomous_gold_admission_20260720T021922.json",
        "why_not_advanced": "Certificate requires ~>=300 real machine_verified_candidate lifecycle sidecars per risk bucket (one-sided Wilson <=0.01, exact zero-failure <=0.005) each anchored to a genuine >=3 independent-family tournament winner in runs/. Zero exist; producing them needs a working multi-provider GPU tournament runtime (SAM2 nuclio + others + Ollama VLM). Docker GPU path is down this wave; not fabricated.",
        "next_agent_step": "Restore Docker engine (disk headroom / vhdx relocation to F:), build train:cu128, run the multi-provider tournament on gold-volume sources to emit machine_verified_candidate sidecars, freeze an image-disjoint corpus, then --corpus.",
    },
    "main_adoption_isolated": {
        "tool": "tools/run_isolated_main_consumer.py",
        "checks_passed": 6,
        "checks_total": 6,
        "all_passed": True,
        "evidence": "runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T021815.json",
        "authority_kind": "isolated_main_consumer",
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "hard_blockers_still_open": ["MF-P6-11.02", "MF-P6-11.07", "MF-P6-12.05", "MF-P6-12.06"],
    },
    "focused_tests": {
        "command": "pytest test_autonomous_gold_admission + test_autonomous_gold_demonstration + test_cross_project_qualification + test_bridge_main_consumer_conformance + test_bridge_journal + test_bridge_failure_control + test_bridge_adoption_receipt_matrix",
        "result": "52 passed",
        "at_head": "447b0f9b",
    },
    "champions": 0,
    "mode_b_predict": "AWAITING_RUNTIME (champions=0; serve/train runtime down)",
    "claims_not_established": [
        "docker_engine_healthy",
        "cvat_live_this_wave",
        "serve_cu128_built",
        "autonomous_certified_gold",
        "champions>0",
        "doctor_all_green",
        "Main-complete / MF-P6-12.06",
        "PRODUCTION_EVIDENCE_PASS",
    ],
    "no_open_human_stop_states": True,
}

payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("SEALED", OUT.name, evidence["self_sha256"][:16])
