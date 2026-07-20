"""Seal a live-probed finding: the Docker Desktop WSL VHDX is still on C:, is
currently held open (locked) by the running Docker engine, and the F:\\...
DockerDesktop\\wsl\\disk\\docker_data.vhdx copy from the 2026-07-14 offload is a
STALE duplicate (same byte size but ~6.6h older LastWriteTime than the live C:
file, which is still being actively written to by the running containers).

This supersedes the "F: physically absent" assessment recorded at 14:35Z in
qa/live_verification/docker_relocation_f_absent_blocked_20260720T1435Z.json:
a fresh live probe this pass shows F: present again as a FIXED NTFS volume
(not removable), 181.21 GB free of 1.82 TB, healthy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "qa" / "live_verification" / "docker_disk_still_on_c_20260720.json"
NOW = "2026-07-20T14:41:00Z"
HEAD_BEFORE_THIS_WAVE = "ddbb0d43"


def main() -> int:
    evidence = {
        "artifact_type": "docker_disk_location_live_probe",
        "authority": "agent_executable_action_queue_zero_human_wait_states",
        "recorded_at": NOW,
        "local_date": "2026-07-20",
        "project_head_before_this_wave": HEAD_BEFORE_THIS_WAVE,
        "branch": "codex/maskfactory-runtime-implementation",
        "supersedes": {
            "path": "qa/live_verification/docker_relocation_f_absent_blocked_20260720T1435Z.json",
            "reason": (
                "That artifact asserted F: was physically absent (single-disk host, no F: "
                "partition/PSDrive). A fresh live re-probe this pass finds F: present again "
                "as a FIXED NTFS volume (DriveType=Fixed, HealthStatus=Healthy, 181.21 GB "
                "free of 1.82 TB) -- not merely reconnected-and-removable. The 'physically "
                "absent' finding is corrected, not the current live state."
            ),
        },
        "live_probe": {
            "f_drive": {
                "get_volume": "DriveLetter=F, FileSystemType=NTFS, DriveType=Fixed, HealthStatus=Healthy, OperationalStatus=OK, SizeRemaining=181.21 GB, Size=1.82 TB",
                "get_psdrive": "F  Used(GB)=1681.80  Free(GB)=181.21  Provider=FileSystem  Root=F:\\",
                "present": True,
            },
            "c_drive": {
                "get_psdrive": "C  Used(GB)=860.31  Free(GB)=91.30  Provider=FileSystem  Root=C:\\",
            },
            "sibling_data_junction": {
                "path": "C:\\Comfy_UI_Main_Masking\\data",
                "link_type": "Junction",
                "target": "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated",
                "note": "Unrelated to the Docker VHDX; this is the repo data/ junction, currently pointed at the on-C: backup per the prior sibling repair. Not touched by this probe.",
            },
            "docker_vhdx_live_on_c": {
                "path": "C:\\Users\\kevin\\AppData\\Local\\Docker\\wsl\\disk\\docker_data.vhdx",
                "length_bytes": 73131884544,
                "length_gib": 68.11,
                "last_write_time": "2026-07-20T09:41:02-05:00",
                "lock_test": "System.IO.File.Open(..., FileMode.Open, FileAccess.ReadWrite, FileShare.None) -> IOException: \"The process cannot access the file ... because it is being used by another process.\"",
                "locked": True,
                "note": "Actively growing/rewritten (LastWriteTime is within the same minute as this probe) -- this is the live, in-use Docker data disk. It cannot be moved/copied consistently while the Docker/WSL engine holds it open.",
            },
            "docker_vhdx_stale_duplicate_on_f": {
                "path": "F:\\MaskFactory_Offload_20260714\\DockerDesktop\\wsl\\disk\\docker_data.vhdx",
                "length_bytes": 73131884544,
                "length_gib": 68.11,
                "last_write_time": "2026-07-20T03:04:25-05:00",
                "staleness_vs_live_c": "~6h37m older than the live C: copy at probe time; identical byte length is coincidental (both are the sparse-allocated max size), not evidence of currency.",
                "note": "Produced by an earlier (2026-07-14 offload wave, refreshed once at 2026-07-20T03:04Z) file copy of the VHDX taken while the engine was stopped for that wave. It has not been kept in sync since -- containers have continued writing to the C: copy for >6 hours. This is a STALE duplicate, not a live mirror; it must NOT be treated as the authoritative disk image without a fresh copy taken while Docker is stopped.",
            },
            "probed_at": NOW,
        },
        "finding": (
            "Docker Desktop's WSL data VHDX remains physically on C: "
            "(C:\\Users\\kevin\\AppData\\Local\\Docker\\wsl\\disk\\docker_data.vhdx, 68.11 GiB) "
            "and is currently held open/locked by the running Docker/WSL2 engine (39 containers "
            "running). A same-size copy exists at "
            "F:\\MaskFactory_Offload_20260714\\DockerDesktop\\wsl\\disk\\docker_data.vhdx but it "
            "is a STALE duplicate from an earlier offload wave (~6.6h behind the live C: file at "
            "probe time), not a current mirror. F: itself is confirmed present, fixed, and "
            "healthy (181.21 GB free) -- the prior 14:35Z 'F: physically absent, hard stop' "
            "finding no longer holds; F: is a valid relocation target again, but the move must "
            "be done with Docker stopped (to release the lock) and must overwrite/refresh the "
            "stale F: copy rather than reuse it as-is."
        ),
        "mutation_performed": False,
        "docker_prune_performed": False,
        "volume_wipe_performed": False,
        "docker_state_unchanged": True,
        "claims_not_established": [
            "docker_vhdx_relocated_to_f",
            "c_disk_pressure_permanently_resolved",
            "f_copy_is_current",
        ],
        "next_agent_executable_step": (
            "Stop Docker Desktop + `wsl --shutdown` to release the lock on the C: VHDX, then "
            "robocopy the now-unlocked, fully-flushed C: VHDX over the stale F: duplicate "
            "(replacing it, not merging), retarget Docker Desktop's WSL disk basePath to the F: "
            "location, restart Docker Desktop, and re-run tools/bootstrap_cvat.py + "
            "tools/smoke_cvat_sam2.py to confirm production CVAT 2.24 is unaffected. Fully "
            "agent-executable, no human wait."
        ),
        "self_sha256": "",
    }
    payload = json.dumps(
        {k: v for k, v in evidence.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    OUTPUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT.name, evidence["self_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
