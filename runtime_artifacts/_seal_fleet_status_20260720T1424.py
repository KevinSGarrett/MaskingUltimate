"""Seal a brief fleet_status_20260720T*.json from LIVE probes + recover/refresh the
needs_agent_actions_20260720.json queue priorities based on the same live state.

Context: needs_agent_actions_20260720.json was found ZERO-CORRUPTED on disk
(20865 bytes, all null; nonzero=0 -> an interrupted write clobbered it). This
coordinator-helper wave recovers it from the committed 20260719 queue and updates
host_snapshot + priorities to the live probe. No tier inflation: champions=0,
no gold, no doctor-green, no Main-complete. Loopback-only; no destructive ops.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LV = REPO_ROOT / "qa" / "live_verification"
PRIOR_QUEUE = LV / "needs_agent_actions_20260719.json"
QUEUE_OUT = LV / "needs_agent_actions_20260720.json"
FLEET_OUT = LV / "fleet_status_20260720T1424.json"

STAMP = "2026-07-20T14:24:00Z"
HEAD = "9dd5f758"

# ---- LIVE PROBE RESULTS (captured this wave) --------------------------------
LIVE = {
    "probed_at": STAMP,
    "docker_engine": {
        "state": "UP",
        "running_containers": 32,
        "production_cvat_v2_24": "UP (cvat_* server/ui/db/workers/opa/redis/clickhouse/vector/traefik)",
        "cvat269_rehearsal": "UP (migration rehearsal only; not production)",
        "nuclio_pth_sam2": "Up (healthy)",
        "nuclio": "Up (healthy)",
        "docker_stats": "responsive (--no-stream OK; mem limit 23.47GiB)",
        "note": "containers report 'Up About a minute' -> engine recently woke/relaunched this window; docker ps (not info) used per runbook.",
    },
    "cvat_about": {
        "url": "http://localhost:8080/api/server/about",
        "http_status": 200,
        "body_kind": "CVAT SPA index (unauthenticated route returns UI shell); production containers healthy at v2.24",
    },
    "ollama": {
        "url": "http://127.0.0.1:11434/api/version",
        "http_status": 200,
        "version": "0.32.1",
    },
    "disk": {
        "c_free_gib": 91.71,
        "repair_floor_gib": 75,
        "above_repair_floor": True,
        "trend": "climbing: ~29.15 (RUNTIME_BLOCKED wave) -> ~47.45 (recovery wave) -> 91.71 GiB now",
        "f_drive": "F:\\MaskFactory_DataRelocated ~249 GiB free (data/ junction)",
    },
}


def seal(obj: dict, out: Path) -> str:
    payload = json.dumps(
        {k: v for k, v in obj.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    obj["self_sha256"] = hashlib.sha256(payload).hexdigest()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return obj["self_sha256"]


def build_fleet_status() -> dict:
    return {
        "artifact_type": "fleet_status",
        "schema_version": "1.0.0",
        "local_date": "2026-07-20",
        "recorded_at": STAMP,
        "authority": "coordinator_helper_live_fleet_reprobe_zero_human_wait",
        "project_head_at_authoring": HEAD,
        "branch": "codex/maskfactory-runtime-implementation",
        "live_probe": LIVE,
        "highest_tiers_unchanged": {
            "core_autonomous_runtime": "STATIC_PASS profile; live ceiling RUNTIME_PASS_BOUNDED; profile_complete=false",
            "cvat_nuclio_ollama": "RUNTIME_PASS_BOUNDED (production localhost:8080; smokes pass)",
            "mode_b_predict": "AWAITING_RUNTIME (champions=0)",
            "p6_11_12_bridge": "STATIC_PASS + AWAITING_MAIN (HARD MF-P6-11.02/11.07/12.05/12.06 OPEN)",
        },
        "claims_not_established": [
            "doctor_all_green",
            "champions>0",
            "human_approved_gold / autonomous_certified_gold",
            "VISUAL_QA_PASS_BOUNDED (project-wide)",
            "PRODUCTION_EVIDENCE_PASS",
            "Main adoption receipts (MF-P6-11.02/11.07/12.05/12.06)",
            "core_autonomous_runtime complete",
        ],
        "no_open_human_stop_states": True,
        "notes": [
            "Live state is HEALTHY this window: Docker UP, production CVAT v2.24 + nuclio pth-sam2 healthy, Ollama 0.32.1, C: free 91.71 GiB (ABOVE 75 GiB repair floor).",
            "Docker being up + disk above floor unblocks retrying: (a) maskfactory/serve:cu128 build + containerized serve smoke, (b) maskfactory/train:cu128 + training-doctor, (c) multi-provider GPU tournament to mint machine_verified_candidate masks toward an autonomous-gold corpus.",
            "needs_agent_actions_20260720.json was found ZERO-CORRUPTED on disk (20865 bytes, all null) and was recovered/refreshed this wave from the committed 20260719 queue.",
        ],
        "self_sha256": "",
    }


def build_queue() -> dict:
    prior = json.loads(PRIOR_QUEUE.read_text(encoding="utf-8-sig"))
    actions = prior["actions"]  # carry the 9 canonical action_ids forward
    return {
        "artifact_type": "needs_agent_actions",
        "schema_version": "1.0.0",
        "local_date": "2026-07-20",
        "recorded_at": STAMP,
        "project_head_at_authoring": HEAD,
        "authority": "agent_executable_action_queue_zero_human_wait_states",
        "recovery_note": (
            "This file was found ZERO-CORRUPTED on disk (20865 bytes, all null bytes; "
            "nonzero=0) at authoring time -> recovered from the committed "
            "needs_agent_actions_20260719.json and re-prioritized against the live "
            "coordinator-helper re-probe. No sibling source edits were staged."
        ),
        "supersedes": {
            "path": "qa/live_verification/needs_agent_actions_20260719.json",
            "reason": "Refresh host_snapshot + priorities to the 2026-07-20T14:24Z live fleet re-probe (Docker UP, disk above 75 GiB floor).",
        },
        "honesty": prior.get("honesty", []),
        "host_snapshot": {
            "docker_engine": "UP (32 running containers; production CVAT v2.24 + cvat269 rehearsal + nuclio/nuclio-pth-sam2 healthy)",
            "cvat_about_http": 200,
            "ollama_version": "0.32.1",
            "c_free_gib": 91.71,
            "c_above_75_repair_floor": True,
            "data_drive": "F:\\MaskFactory_DataRelocated (junction from data/); ~249 GiB free",
            "champions": 0,
            "gold": 0,
        },
        "live_priorities_this_wave": [
            {
                "rank": 1,
                "action_id": "retry_serve_cu128_build_and_containerized_smoke",
                "why_now": "Docker UP + C: 91.71 GiB (above 75 floor) -> the WSL2/disk exhaustion that crashed the prior ~7 GiB torch cu128 install is relieved. Build maskfactory/serve:cu128 then tools/smoke_docker_gpu_serve.py; seal containerized serve RUNTIME_PASS_BOUNDED.",
                "status": "AGENT_EXECUTABLE_NOW",
            },
            {
                "rank": 2,
                "action_id": "multi_provider_gpu_tournament_toward_autonomous_gold",
                "why_now": "GPU container path + healthy nuclio SAM2 available. Run the >=3 independent-family tournament on gold-volume sources to emit machine_verified_candidate masks; assemble a frozen image-disjoint corpus; build_autonomous_gold_admission --corpus. Still honest insufficient until real candidates exist; champions stay 0 until measured.",
                "status": "AGENT_EXECUTABLE_NOW_INSUFFICIENT_SAMPLES",
            },
            {
                "rank": 3,
                "action_id": "build_train_cu128_and_training_doctor",
                "why_now": "Disk headroom now supports the CUDA 12.8 devel train image (mmcv._ext sm_120). Build maskfactory/train:cu128 -> training-doctor in-container.",
                "status": "AGENT_EXECUTABLE_NOW",
            },
            {
                "rank": 4,
                "action_id": "main_adoption_isolated_consumer_hard_blockers",
                "why_now": "HARD MF-P6-11.02/11.07/12.05/12.06 remain OPEN; real receipts require a dedicated Comfy_UI_Main-side consumer build (producer side already verified). Not a human wait; agent-executable in the Main repo.",
                "status": "PRODUCER_VERIFIED_AGENT_EXECUTABLE_IN_MAIN",
            },
            {
                "rank": 5,
                "action_id": "repair_ubuntu_2204_ext4_vhd",
                "why_now": "Only the live SAM 3.1 CUDA WSL smoke depends on the scripted elevated e2fsck (tools/Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair). GPU container path is the active substitute; no lane waits.",
                "status": "AGENT_EXECUTABLE_FROM_ELEVATED_SHELL_SUBSTITUTE_ACTIVE",
            },
        ],
        "actions": actions,
        "claims_not_established": prior.get("claims_not_established", []),
        "no_open_human_stop_states": True,
        "latest_reverification": {
            "at": STAMP,
            "by": "coordinator_helper_fleet_reprobe",
            "docker": "UP (32 containers)",
            "cvat_about_http": 200,
            "ollama": "0.32.1",
            "c_free_gib": 91.71,
            "champions": 0,
            "gold": 0,
        },
        "self_sha256": "",
    }


def main() -> int:
    fleet = build_fleet_status()
    fleet_sha = seal(fleet, FLEET_OUT)
    queue = build_queue()
    queue_sha = seal(queue, QUEUE_OUT)
    print("fleet_status ->", FLEET_OUT.name, fleet_sha)
    print("needs_agent_actions ->", QUEUE_OUT.name, queue_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
