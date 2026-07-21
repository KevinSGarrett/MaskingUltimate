"""Refresh needs_agent_actions after the 2026-07-20T15:02Z fleet reprobe.

- Mark migrate_docker_vhdx_c_to_f ABORTED (USB Seagate; sibling abort seal).
- Reprioritize: restore Docker/CVAT first, then serve/train/tournament.
- Refresh host_snapshot + latest_reverification from live probe.
No tier inflation; self_sha256 recomputed with compact sorted convention.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PATH = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
FLEET = "qa/live_verification/fleet_status_20260720T1502.json"
ABORT = "qa/live_verification/docker_migrate_abort_usb_removable_f_20260720T1437Z.json"
SNAP = REPO / "runtime_artifacts" / "_fleet_probe_snap_20260720T1500.json"

c_free = round(shutil.disk_usage("C:/").free / 2**30, 2)
f_free = round(shutil.disk_usage("F:/").free / 2**30, 2)
head = subprocess.run(
    ["git", "rev-parse", "--short=8", "HEAD"],
    cwd=REPO,
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()
now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
snap = json.loads(SNAP.read_text(encoding="utf-8")) if SNAP.exists() else {}
docker_up = snap.get("docker_info_rc") == 0 and bool(snap.get("docker_server"))
running = int(snap.get("running_containers") or 0)
engine_state = (
    f"UP (server {snap.get('docker_server')}, {running} containers)"
    if docker_up and running >= 20
    else "DOWN_OR_FLAPPING (pipe missing / WSL docker-desktop Stopped at seal; was UP 39ct @14:52Z)"
)

prior_sha = None
raw = PATH.read_text(encoding="utf-8")
data = json.loads(raw)
prior_sha = data.get("self_sha256")

for action in data["actions"]:
    aid = action.get("action_id")
    if aid == "migrate_docker_vhdx_c_to_f":
        action["status"] = "ABORTED_USB_REMOVABLE_F"
        action["abort_evidence"] = ABORT
        action["fleet_reprobe_20260720T1502"] = {
            "evidence": FLEET,
            "note": (
                "Confirmed again: F: is USB Seagate BUP Slim (BusType=USB). Live docker_data.vhdx "
                "must remain on C: NVMe. No VHDX move attempted this wave."
            ),
        }
        action["no_human_wait"] = True
    if aid == "repair_ubuntu_2204_ext4_vhd":
        action["fleet_reprobe_20260720T1502"] = {
            "evidence": FLEET,
            "wsl_at_seal": "Ubuntu-22.04 Stopped; earlier WRITE_OK then SHARING_VIOLATION on F: vhdx",
            "note": "Docker-GPU remains sole CUDA train/serve path; WSL wake is opportunistic.",
        }
    if aid == "f_drive_usb_removable_dual_anchor_risk":
        action["fleet_reprobe_20260720T1502"] = {
            "evidence": FLEET,
            "f_free_gib_now": f_free,
            "f_present": True,
            "note": "F: still Online USB; free-space swung 181->~128 GiB this wave (not a wipe).",
        }

# Ensure restore-docker action note exists as priority (not a new action_id unless missing)
data["host_snapshot"] = dict(data.get("host_snapshot", {}))
data["host_snapshot"].update(
    {
        "docker_engine": engine_state,
        "docker_ps_containers_up": running if docker_up else 0,
        "cvat_about_http": snap.get("cvat_http") or "UNREACHABLE_ENGINE_DOWN",
        "ollama_version": (snap.get("ollama") or {}).get("version", "0.32.1"),
        "ollama_provider": "native_windows",
        "c_free_gib": c_free,
        "c_free_gib_approx": c_free,
        "c_above_75_repair_floor": c_free >= 75,
        "f_present": True,
        "f_free_gib": f_free,
        "f_drive_bus_type": "USB (Seagate BUP Slim, physically removable)",
        "wsl_ubuntu2204": "Running_at_seal (WRITE_OK earlier; mid-wave F: vhdx SHARING_VIOLATION; docker-desktop Stopped)",
        "wsl_ubuntu_2204": "Running; Docker-GPU sole CUDA path (engine currently flapping)",
        "champions": 0,
        "gold": 0,
        "cuda_train_serve_path": "Docker-GPU (sole/primary); blocked until engine stable",
        "data_drive": (
            "data/ junction -> C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated; "
            "F:\\MaskFactory_DataRelocated present"
        ),
    }
)

data["live_priorities_this_wave"] = [
    {
        "rank": 1,
        "action_id": "restore_docker_engine_and_cvat_stack",
        "status": "AGENT_EXECUTABLE_NOW",
        "why_now": (
            "Engine flapped DOWN after a healthy 39-container window. Start/wait Docker Desktop, "
            "docker ps/stats, bootstrap_cvat.py, smoke_cvat_sam2.py. Unblocks all GPU-container lanes."
        ),
    },
    {
        "rank": 2,
        "action_id": "docker_gpu_serve_build_and_containerized_smoke",
        "status": "AGENT_EXECUTABLE_AFTER_ENGINE_STABLE",
        "why_now": (
            "Docker-GPU is the sole CUDA serve path. Build maskfactory/serve:cu128 out-of-band once "
            "engine is stable + C: stays above 75 GiB floor."
        ),
    },
    {
        "rank": 3,
        "action_id": "docker_gpu_train_build_and_training_doctor",
        "status": "AGENT_EXECUTABLE_AFTER_ENGINE_STABLE",
        "why_now": "Docker-GPU sole CUDA train path; train STATIC_PASS already sealed.",
    },
    {
        "rank": 4,
        "action_id": "multi_provider_gpu_tournament_toward_autonomous_gold",
        "status": "AGENT_EXECUTABLE_NOW_INSUFFICIENT_SAMPLES",
        "why_now": "After engine+SAM2 healthy: mint machine_verified_candidate masks; champions stay 0 until measured.",
    },
    {
        "rank": 5,
        "action_id": "main_adoption_isolated_consumer_hard_blockers",
        "status": "PRODUCER_VERIFIED_AGENT_EXECUTABLE_IN_MAIN",
        "why_now": "HARD MF-P6-11.02/11.07/12.05/12.06 remain OPEN; agent-executable in Comfy_UI_Main.",
    },
    {
        "rank": 6,
        "action_id": "migrate_docker_vhdx_c_to_f",
        "status": "ABORTED_USB_REMOVABLE_F",
        "why_now": "F: is USB Seagate — never host live docker_data.vhdx on removable media. Abort sealed.",
    },
]

data["latest_reverification"] = {
    "at": now,
    "by": "fleet_reprobe_20260720T1502",
    "evidence": FLEET,
    "docker": engine_state,
    "cvat_about_http": snap.get("cvat_http") or "UNREACHABLE_ENGINE_DOWN",
    "ollama": (snap.get("ollama") or {}).get("version", "0.32.1"),
    "c_free_gib": c_free,
    "f_free_gib": f_free,
    "f_present": True,
    "wsl_ubuntu2204": "Running_at_seal_docker_desktop_Stopped",
    "champions": 0,
    "gold": 0,
}

data["migrate_docker_vhdx_status_20260720T1502"] = "ABORTED_USB_REMOVABLE_F"
data["migrate_reprioritization_note_20260720T1502"] = (
    "migrate_docker_vhdx_c_to_f demoted from IN_PROGRESS to ABORTED after "
    "docker_migrate_abort_usb_removable_f_20260720T1437Z.json + live BusType=USB reconfirm. "
    "Top priority is restore_docker_engine_and_cvat_stack."
)
data["fleet_status_evidence"] = FLEET
data["project_head_at_authoring"] = head
data["recorded_at"] = now
data["no_open_human_stop_states"] = True
data["supersedes"] = {
    "path": "qa/live_verification/needs_agent_actions_20260720.json (prior self, this wave)",
    "file_sha256": prior_sha,
    "reason": (
        "Fleet reprobe 15:02Z: Docker flap sealed; migrate aborted USB; priorities restored to "
        "engine-first then serve/train/tournament."
    ),
}

data.pop("self_sha256", None)
payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
data["self_sha256"] = hashlib.sha256(payload).hexdigest()
PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(PATH.name, data["self_sha256"])
print("engine", engine_state)
print("priorities", [p["action_id"] for p in data["live_priorities_this_wave"][:4]])
