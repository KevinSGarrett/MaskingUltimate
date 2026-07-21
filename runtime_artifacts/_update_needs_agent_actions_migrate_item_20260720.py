"""Add/refresh the docker-VHDX-migration item in needs_agent_actions_20260720.json,
reclassifying it from the earlier BLOCKED_HARD_STOP_F_DRIVE_PHYSICALLY_ABSENT
outcome to IN_PROGRESS / agent-executable, per the fresh live probe sealed in
qa/live_verification/docker_disk_still_on_c_20260720.json (F: confirmed present,
fixed, healthy; live C: vhdx locked while Docker runs; F: has a stale duplicate
that must be refreshed, not reused, before retarget).

Recomputes self_sha256 deterministically (sorted-key, compact JSON, excluding the
self_sha256 field itself), matching this repo's existing seal convention.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = REPO_ROOT / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
NOW = "2026-07-20T14:41:00Z"
HEAD_BEFORE_THIS_WAVE = "ddbb0d43"
EVIDENCE_PATH = "qa/live_verification/docker_disk_still_on_c_20260720.json"


def main() -> int:
    data = json.loads(TARGET.read_text(encoding="utf-8"))

    migrate_action = {
        "action_id": "migrate_docker_vhdx_c_to_f",
        "former": "retry_serve... N/A -- new item; supersedes docker_relocation_f_absent_blocked_20260720T1435Z (BLOCKED_HARD_STOP_F_DRIVE_PHYSICALLY_ABSENT)",
        "status": "IN_PROGRESS",
        "sibling_finding": (
            "Live re-probe (qa/live_verification/docker_disk_still_on_c_20260720.json) finds F: "
            "present again as a FIXED NTFS volume (181.21 GB free of 1.82 TB) -- the earlier "
            "'F: physically absent' hard-stop no longer holds. The live Docker VHDX "
            "(C:\\Users\\kevin\\AppData\\Local\\Docker\\wsl\\disk\\docker_data.vhdx, 68.11 GiB) "
            "is currently LOCKED (exclusive-open fails; held by the running engine, 39 "
            "containers up) and still being actively written to. A same-size copy already "
            "exists at F:\\MaskFactory_Offload_20260714\\DockerDesktop\\wsl\\disk\\docker_data.vhdx "
            "but it is a STALE duplicate (~6.6h behind the live C: file at probe time), not a "
            "current mirror -- it must be refreshed/overwritten, not reused as-is."
        ),
        "agent_executable_path": [
            "Stop Docker Desktop + `wsl --shutdown` to release the lock on the C: VHDX (no human "
            "judgment required; scripted).",
            "robocopy the now-unlocked, fully-flushed C: VHDX over the stale F: duplicate at "
            "F:\\MaskFactory_Offload_20260714\\DockerDesktop\\wsl\\disk\\docker_data.vhdx "
            "(replace, not merge).",
            "Retarget Docker Desktop's WSL disk basePath / docker-desktop-data distro location to "
            "the F: copy (Docker Desktop Settings > Resources > Advanced, or the equivalent "
            "settings.json wslEngineDiskLocation key).",
            "Restart Docker Desktop; re-run tools/bootstrap_cvat.py + tools/smoke_cvat_sam2.py to "
            "confirm production CVAT 2.24 is unaffected and C: free space rises by ~68 GiB.",
        ],
        "no_human_wait": True,
        "evidence": EVIDENCE_PATH,
        "unblocks": [
            "sustained C: headroom above the 75 GiB repair floor without relying on the data/ "
            "junction alone",
        ],
    }

    existing_ids = [a.get("action_id") for a in data["actions"]]
    if "migrate_docker_vhdx_c_to_f" in existing_ids:
        idx = existing_ids.index("migrate_docker_vhdx_c_to_f")
        data["actions"][idx] = migrate_action
    else:
        data["actions"].append(migrate_action)

    priority_entry = {
        "action_id": "migrate_docker_vhdx_c_to_f",
        "rank": 0,
        "status": "IN_PROGRESS_AGENT_EXECUTABLE",
        "why_now": (
            "F: reconfirmed present/fixed/healthy this wave; only the Docker-engine file lock "
            "gates the move, and releasing it (stop Docker + wsl --shutdown) is fully scripted. "
            "The existing F: copy is stale and must be refreshed, not reused."
        ),
    }
    existing_priority_ids = [p.get("action_id") for p in data["live_priorities_this_wave"]]
    if "migrate_docker_vhdx_c_to_f" in existing_priority_ids:
        idx = existing_priority_ids.index("migrate_docker_vhdx_c_to_f")
        data["live_priorities_this_wave"][idx] = priority_entry
    else:
        data["live_priorities_this_wave"].insert(0, priority_entry)
    for rank, entry in enumerate(data["live_priorities_this_wave"], start=1):
        entry["rank"] = rank

    data["migrate_docker_vhdx_status_20260720T1441"] = "IN_PROGRESS"
    data["migrate_reprioritization_note_20260720T1441"] = (
        "Added migrate_docker_vhdx_c_to_f as IN_PROGRESS/agent-executable per fresh live probe "
        "(sibling finding: live C: vhdx locked, F: has only a stale duplicate). Supersedes the "
        "14:35Z BLOCKED_HARD_STOP_F_DRIVE_PHYSICALLY_ABSENT assessment for F: presence; the move "
        "itself is not yet completed (still gated on stopping Docker to release the file lock)."
    )
    data["project_head_at_authoring"] = HEAD_BEFORE_THIS_WAVE
    data["recorded_at"] = NOW
    data["supersedes"] = {
        "path": "qa/live_verification/needs_agent_actions_20260720.json (prior self, HEAD "
        f"{HEAD_BEFORE_THIS_WAVE})",
        "reason": (
            "Add migrate_docker_vhdx_c_to_f as IN_PROGRESS/executable and rank it #1 this wave "
            "per the fresh live disk probe; no other fields altered besides bookkeeping "
            "(recorded_at/project_head_at_authoring/self_sha256)."
        ),
    }

    data["self_sha256"] = ""
    payload = json.dumps(
        {k: v for k, v in data.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    data["self_sha256"] = hashlib.sha256(payload).hexdigest()

    TARGET.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(TARGET.name, data["self_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
