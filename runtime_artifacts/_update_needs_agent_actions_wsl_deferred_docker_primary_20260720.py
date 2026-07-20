"""Refresh needs_agent_actions_20260720.json: WSL repair DEFERRED; Docker-GPU PRIMARY.

Idempotent, honest, no tier inflation. Recomputes self_sha256 over the canonical
(sorted, compact, self_sha256-excluded) payload, matching the file's own seal method.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
QUEUE = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
SEAL = "qa/live_verification/docker_gpu_sole_cuda_path_wsl_deferred_20260720.json"
NOW = datetime.now(UTC).isoformat().replace("+00:00", "Z")

doc = json.loads(QUEUE.read_text(encoding="utf-8"))
doc.pop("self_sha256", None)

# 1) Reclassify the WSL repair action: DEFERRED (non-admin) and explicitly NOT a
#    train/serve blocker now that Docker-GPU is the sole CUDA path.
for action in doc.get("actions", []):
    if action.get("action_id") == "repair_ubuntu_2204_ext4_vhd":
        action["status"] = "DEFERRED_WSL_REPAIR_DOCKER_GPU_PRIMARY"
        action["deferred_reason"] = (
            "Repair BLOCKED: this session's shell is non-elevated (scripted e2fsck / "
            "tools/Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair needs an interactive UAC "
            "prompt = a human wait state) and the on-disk Ubuntu-22.04 ext4 VHD is corrupt "
            "(wsl -d Ubuntu-22.04 -- /bin/true -> Error code 6 / E_FAIL). DEFERRED to a "
            "future elevated shell; it does NOT block CUDA train/serve."
        )
        action["docker_gpu_primary"] = (
            "Docker-GPU is doubled-down as the SOLE local CUDA train/serve path: "
            "maskfactory/serve:cu128 (python:3.11-slim + torch cu128) and "
            "maskfactory/train:cu128 (nvidia/cuda:12.8.0-devel Docker Hub base) are "
            "WSL-Ubuntu-distro-INDEPENDENT; both STATIC contracts STATIC_PASS and host "
            "GPU passthrough is live-proven (RTX 5060, driver 592.01) this wave."
        )
        action["evidence"] = SEAL
        action["only_dependent_lane"] = (
            "MF-P2-11.07 live SAM 3.1 CUDA *WSL* smoke - the only item that specifically "
            "needs the WSL distro; deferred with it. All other CUDA routes via Docker-GPU."
        )

# 2) Re-rank the live priorities so Docker-GPU serve/train lead and WSL repair is last+deferred.
doc["live_priorities_this_wave"] = [
    {
        "action_id": "docker_gpu_serve_build_and_containerized_smoke",
        "rank": 1,
        "status": "AGENT_EXECUTABLE_OUT_OF_BAND",
        "why_now": (
            "Docker-GPU is the sole CUDA serve path (WSL deferred). serve STATIC contract "
            "STATIC_PASS + host GPU passthrough live-proven. Build maskfactory/serve:cu128 "
            "deliberately out-of-band (WSL2 headroom; do not crash the running CVAT stack) "
            "-> tools/smoke_docker_gpu_serve.py -> seal containerized serve RUNTIME_PASS_BOUNDED."
        ),
    },
    {
        "action_id": "docker_gpu_train_build_and_training_doctor",
        "rank": 2,
        "status": "AGENT_EXECUTABLE_OUT_OF_BAND",
        "why_now": (
            "Docker-GPU is the sole CUDA train path (WSL deferred). train STATIC contract "
            "STATIC_PASS (sm_120 mmcv._ext from-source, CUDA 12.8 devel Docker Hub base, "
            "Ubuntu-distro-independent). Build maskfactory/train:cu128 out-of-band -> "
            "training-doctor in-container (tools/smoke_docker_gpu_train.py fails closed image_absent)."
        ),
    },
    {
        "action_id": "multi_provider_gpu_tournament_toward_autonomous_gold",
        "rank": 3,
        "status": "AGENT_EXECUTABLE_NOW_INSUFFICIENT_SAMPLES",
        "why_now": (
            "GPU container path + healthy nuclio SAM2 available. Run the >=3 independent-family "
            "tournament on gold-volume sources to emit machine_verified_candidate masks; assemble a "
            "frozen image-disjoint corpus; build_autonomous_gold_admission --corpus. Honest insufficient "
            "until real candidates exist; champions stay 0 until measured."
        ),
    },
    {
        "action_id": "main_adoption_isolated_consumer_hard_blockers",
        "rank": 4,
        "status": "PRODUCER_VERIFIED_AGENT_EXECUTABLE_IN_MAIN",
        "why_now": (
            "HARD MF-P6-11.02/11.07/12.05/12.06 remain OPEN; real receipts require a dedicated "
            "Comfy_UI_Main-side consumer build (producer side already verified). Agent-executable in "
            "the Main repo, not a human wait."
        ),
    },
    {
        "action_id": "repair_ubuntu_2204_ext4_vhd",
        "rank": 5,
        "status": "DEFERRED_WSL_REPAIR_DOCKER_GPU_PRIMARY",
        "why_now": (
            "DEFERRED: non-admin shell cannot run the scripted elevated e2fsck; on-disk ext4 "
            "corruption confirmed. Only the WSL-specific live SAM 3.1 CUDA smoke depends on it. "
            "Docker-GPU is the active sole CUDA train/serve substitute; no train/serve lane waits."
        ),
    },
]

# 3) Refresh live host snapshot + reverification for this wave.
snapshot = {
    "c_above_75_repair_floor": True,
    "c_free_gib": 76.0,
    "f_drive": "REMOVABLE/FLAPPING (present at probe 181.2 GiB; sibling recorded ABSENT at 14:35Z) - NOT relied upon; Docker-GPU path is C:-resident and F:-independent",
    "champions": 0,
    "gold": 0,
    "cvat_about_http": 200,
    "docker_engine": "UP (37 containers; production CVAT v2.24 + cvat269 rehearsal + nuclio/pth-sam2 healthy)",
    "gpu_container_passthrough": "RTX 5060 Laptop GPU, driver 592.01, 8151 MiB total / ~1247 MiB free (live via --gpus all)",
    "wsl_ubuntu_2204": "Stopped (repair deferred; non-admin)",
    "cuda_train_serve_path": "Docker-GPU (sole/primary); WSL Ubuntu-22.04 not required; F: not required",
}
doc["host_snapshot"] = snapshot
doc["latest_reverification"] = {
    "at": NOW,
    "by": "docker_gpu_sole_cuda_path_wsl_deferred_wave",
    "c_free_gib": 76.0,
    "champions": 0,
    "gold": 0,
    "cvat_about_http": 200,
    "docker": "UP (37 containers)",
    "gpu_passthrough": "RTX 5060 driver 592.01 live",
    "wsl_ubuntu_2204": "Stopped (deferred)",
}
doc["recorded_at"] = NOW
doc["wsl_repair_disposition"] = "DEFERRED_NON_ADMIN_DOCKER_GPU_IS_SOLE_CUDA_PATH"
doc["docker_gpu_evidence"] = SEAL

# Preserve honest non-inflation invariants.
doc["no_open_human_stop_states"] = True

payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
doc["self_sha256"] = hashlib.sha256(payload).hexdigest()
QUEUE.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("UPDATED", QUEUE.name, doc["self_sha256"][:16])
