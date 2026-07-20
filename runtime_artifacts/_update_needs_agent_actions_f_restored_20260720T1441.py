"""Targeted update of needs_agent_actions_20260720.json after removable F: was restored.

Read-modify-write in one shot to minimize collision risk with concurrent sibling
agents. Records that F: is back online and unblocks the DAZ / F: data / WSL paths.
Only touches F:/WSL/DAZ-related fields + host_snapshot + latest_reverification;
leaves every other action byte-for-byte untouched (json load -> mutate -> dump
sort_keys=True). No tier inflation; self_sha256 recomputed with the same
compact-sorted convention used by the sibling update scripts.
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
SEAL = "qa/live_verification/f_drive_restored_20260720T0933Z.json"

c_free_gib = round(shutil.disk_usage("C:/").free / 2**30, 2)
f_free_gib = round(shutil.disk_usage("F:/").free / 2**30, 2)
head = subprocess.run(
    ["git", "rev-parse", "--short=8", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
).stdout.strip()
now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

data = json.loads(PATH.read_text(encoding="utf-8"))

for action in data["actions"]:
    aid = action.get("action_id")
    if aid == "repair_ubuntu_2204_ext4_vhd":
        action["f_restored_reverification_20260720T1441"] = {
            "evidence": SEAL,
            "wsl_wake": "wsl -d Ubuntu-22.04 -- (echo ok; uname -r; df; touch) -> exit 0, WRITE_OK, kernel 6.18.33.2",
            "root_cause_correction": (
                "The 'Ubuntu-22.04 ext4 corrupt / Error code 6' symptom was the removable F: being "
                "DISCONNECTED, not on-disk ext4 damage: the registered distro's ext4.vhdx lives at "
                "F:\\MaskFactory_Offload_20260714\\WSL\\Ubuntu-22.04 (53.56 GiB). With F: reconnected "
                "the distro boots clean and root fs is read/write (WRITE_OK) with no elevated e2fsck."
            ),
            "note": (
                "Non-elevated wake succeeded; the scripted elevated e2fsck is no longer required to "
                "reach a bootable distro. Live CUDA SAM 3.1 WSL smoke path is reopened. Docker-GPU "
                "remains the primary GPU runtime; WSL is now additionally available."
            ),
        }
        action["status"] = "UNBLOCKED_WSL_HEALTHY_ON_F_RESTORE"
    if aid == "sam31_meta_terms_and_live_smoke":
        action["f_restored_reverification_20260720T1441"] = {
            "evidence": SEAL,
            "note": (
                "WSL Ubuntu-22.04 now wakes healthy (F: restored), so the live CUDA WSL smoke no longer "
                "waits on an elevated repair. Local weights already present; smoke is agent-executable."
            ),
        }
    if aid == "dvc_push_local_first":
        action["f_restored_reverification_20260720T1441"] = {
            "evidence": SEAL,
            "note": (
                "F:\\MaskFactory_DataRelocated\\dvc_local_remote reachable again (F: restored); local "
                "dvc remote path is live. data/ junction still points to the on-C: backup for outage "
                "resilience (repoint to F: reversible on request)."
            ),
        }

data["f_drive_restored_20260720T1441"] = {
    "reported_by": "kevin_reports_f_back_online",
    "evidence": SEAL,
    "ops_log": "Plan/OPS_LOG.md (2026-07-20 14:41 UTC F: restored entry)",
    "f_present": True,
    "f_free_gib": f_free_gib,
    "f_removable": True,
    "supersedes_hard_stop": "qa/live_verification/docker_relocation_f_absent_blocked_20260720T1435Z.json",
    "unblocked_paths": [
        "F:\\DAZ (roots / validation / ops / coverage static contracts; 26 entries reachable)",
        "F:\\MaskFactory_DataRelocated (8-package set + dvc_local_remote reachable; sqlite images=24)",
        "WSL Ubuntu-22.04 (distro vhdx on F: boots healthy read/write; live CUDA WSL smoke reopened)",
    ],
    "data_health": {
        "junction_target": "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated (on-C: backup, kept for resilience)",
        "active_package_count": 8,
        "f_datarelocated_package_count": 8,
        "moved_this_update": False,
        "repoint_to_f": "reversible and available on request; not auto-performed",
    },
    "honesty": [
        "F: is REMOVABLE and just disconnected; durable off-C: Docker VHDX relocation still needs a fixed second disk (Kevin).",
        "No data moved/mutated; champions=0; gold=0; doctor not all-green; no docker_vhdx_relocated_to_f.",
    ],
}

data["host_snapshot"]["f_present"] = True
data["host_snapshot"]["f_free_gib"] = f_free_gib
data["host_snapshot"]["c_free_gib_approx"] = c_free_gib
data["host_snapshot"]["wsl_ubuntu2204"] = "HEALTHY (F: restored; non-elevated wake exit 0, WRITE_OK)"
data["host_snapshot"]["data_drive"] = (
    "data/ junction -> C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated (on-C: backup, 8 pkgs); "
    "F:\\MaskFactory_DataRelocated reachable again (identical 8-pkg set + dvc_local_remote)"
)

data["latest_reverification"] = {
    "at": now,
    "by": "f_drive_restored_reverify_non_elevated",
    "c_free_gib": c_free_gib,
    "f_present": True,
    "f_free_gib": f_free_gib,
    "wsl_ubuntu2204": "HEALTHY (non-elevated wake exit 0, WRITE_OK)",
    "evidence": SEAL,
}

data["project_head_at_authoring"] = head
data["recorded_at"] = now

data.pop("self_sha256", None)
payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
data["self_sha256"] = hashlib.sha256(payload).hexdigest()

PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("UPDATED", PATH.name, "self_sha256", data["self_sha256"][:16])
print("f_present True f_free_gib", f_free_gib, "c_free_gib", c_free_gib, "head", head)
