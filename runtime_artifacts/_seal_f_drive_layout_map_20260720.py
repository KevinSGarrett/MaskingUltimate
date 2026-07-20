"""Seal qa/live_verification/f_drive_layout_map_20260720.json.

Live probe of the F: drive layout at the moment this session ran, focused on the three
areas Kevin asked to have documented:
  1. F:\\MaskFactory_Offload_20260714 (the WSL Ubuntu-22.04 distro + Docker Desktop wsl/disk
     offload tree, plus the older Comfy_UI_Main / CVAT offload subtrees).
  2. F:\\MaskFactory_DataRelocated (the governed data/ relocation target).
  3. The C:\\Comfy_UI_Main_Masking\\data junction and its live health.

Every figure below was re-read live in this session (Get-Item / Get-ChildItem / Get-Volume /
Get-Disk / registry Lxss BasePath / wsl -l -v / docker info / docker ps / curl probes) rather
than copied from an older report, per Plan/DOCKER_RUNTIME_AND_SESSION_USE.md. Where this
session's finding conflicts with a very recent sibling artifact
(docker_relocation_f_absent_blocked_20260720T1435Z.json, which found F: physically absent),
that conflict is recorded honestly instead of silently overwritten.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "f_drive_layout_map_20260720.json"

c_usage = shutil.disk_usage("C:/")
f_usage = shutil.disk_usage("F:/")

evidence = {
    "artifact_type": "f_drive_layout_map",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "local_date": "2026-07-20",
    "authority": [
        "Plan/DOCKER_RUNTIME_AND_SESSION_USE.md",
        "qa/live_verification/needs_agent_actions_20260720.json",
        "qa/live_verification/docker_relocation_f_absent_blocked_20260720T1435Z.json",
    ],
    "branch": "codex/maskfactory-runtime-implementation",
    "project_head_at_authoring": "ddbb0d43eb079ece8c3047f368ccd8c1747bdf9a",
    "probe_method": [
        "Get-Volume -DriveLetter F / Get-Disk / Get-Partition (bus type, fixed-vs-removable)",
        "Get-ChildItem -Recurse on F:\\MaskFactory_Offload_20260714 and F:\\MaskFactory_DataRelocated",
        "Get-Item on C:\\Comfy_UI_Main_Masking\\data (junction target/attributes) and 'dir' for reparse confirmation",
        "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss registry BasePath per WSL distro (authoritative live location, not settings files)",
        "wsl -l -v (distro run state)",
        "Two Get-Item samples on each docker_data.vhdx (C: and F:) minutes apart to distinguish live-active vs stale-copy by LastWriteTime drift",
        "docker info / docker ps; curl.exe + Invoke-WebRequest against CVAT :8080/api/server/about; curl.exe against Ollama :11434/api/version",
    ],
    "f_drive_identity": {
        "drive_letter": "F",
        "windows_drive_type": "Fixed",
        "underlying_disk": "Disk 1, 'Seagate BUP Slim BK', BusType=USB, ~2000.4 GB",
        "note": (
            "Windows reports DriveType=Fixed (not hot-plug-flagged in the filesystem sense), but the "
            "underlying physical disk is a USB external drive (Seagate Backup Plus Slim). This matches "
            "the physically-removable-drive finding in docker_relocation_f_absent_blocked_20260720T1435Z.json. "
            "It is genuinely a detachable USB disk that happens to currently be attached and healthy."
        ),
        "health_status": "Healthy",
        "size_gib": round(f_usage.total / 2**30, 2),
        "free_gib_this_probe": round(f_usage.free / 2**30, 2),
    },
    "reconciliation_with_prior_absent_report": {
        "prior_artifact": "qa/live_verification/docker_relocation_f_absent_blocked_20260720T1435Z.json",
        "prior_finding": "F: physically absent (single-disk system observed: Disk 0 only); dangling data/ junction repointed to C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated.",
        "prior_recorded_at": "2026-07-20T14:35:00Z",
        "this_probe_recorded_at_utc_hour_matches": True,
        "this_probe_finding": "F: is present, healthy, and mounted with two disks now visible (Disk 0 NVMe + Disk 1 USB Seagate). data/ junction currently resolves to F:\\MaskFactory_DataRelocated, not the C: backup.",
        "explanation": (
            "The prior report and this probe fall in the same UTC clock hour but reflect genuinely "
            "different physical states (F: absent, then F: present) observed by different agent "
            "sessions sharing this working tree. This is consistent with a transient USB "
            "disconnect/reconnect of the Seagate drive between those two probes, not a fabrication or "
            "a stale read in either report -- both were live at their own probe time. This artifact "
            "does not overwrite or discredit the prior one; it records the drive's current state and "
            "flags the reconnect as a live risk (see kevin_flag below)."
        ),
        "kevin_flag": (
            "F: is a USB external drive that has already been observed to disconnect once this session. "
            "It now hosts BOTH the governed data/ junction target (MaskFactory_DataRelocated) AND the "
            "live WSL Ubuntu-22.04 distro (BasePath below). A future disconnect would simultaneously "
            "dangle the data junction and crash/corrupt the running Ubuntu-22.04 WSL distro. Recommend "
            "either a permanent fixed-drive host for these two governed roles, or leaving them on this "
            "USB drive only with an accepted, explicit risk of another disconnect."
        ),
    },
    "maskfactory_offload_20260714": {
        "path": "F:\\MaskFactory_Offload_20260714",
        "top_level_subdirs": ["Comfy_UI_Main", "CVAT", "DockerDesktop", "WSL"],
        "comfy_ui_main": {
            "path": "F:\\MaskFactory_Offload_20260714\\Comfy_UI_Main",
            "contents": ["models (subdir, present)"],
            "note": "Offloaded Comfy_UI_Main model weights; not touched by this probe beyond existence.",
        },
        "cvat_offload": {
            "path": "F:\\MaskFactory_Offload_20260714\\CVAT",
            "contents": ["backups", "cvat-v2.69.0"],
            "note": "cvat269 migration-rehearsal source tree offload; isolated from production CVAT v2.24 per DOCKER_RUNTIME_AND_SESSION_USE.md.",
        },
        "docker_desktop_wsl_disk": {
            "path": "F:\\MaskFactory_Offload_20260714\\DockerDesktop\\wsl\\disk\\docker_data.vhdx",
            "size_bytes": 73131884544,
            "size_gib": round(73131884544 / 2**30, 2),
            "last_write_time_this_probe": "2026-07-20T03:04:25-05:00",
            "status": "STALE_OFFLOAD_COPY_NOT_LIVE",
            "finding": (
                "Identical size to the live C: docker_data.vhdx (68.11 GiB) but its LastWriteTime has "
                "not moved across repeated probes in this session while the C: copy's LastWriteTime "
                "advanced on every probe (active container I/O). This is a stale snapshot from an "
                "earlier offload/relocation attempt, not the engine's live data disk."
            ),
        },
        "wsl_ubuntu_2204_offload": {
            "path": "F:\\MaskFactory_Offload_20260714\\WSL\\Ubuntu-22.04\\ext4.vhdx",
            "size_bytes": 57511247872,
            "size_gib": round(57511247872 / 2**30, 2),
            "last_write_time_this_probe": "2026-07-20T09:36:14-05:00",
            "status": "LIVE_ACTIVE",
            "finding": (
                "This IS the live Ubuntu-22.04 distro storage: HKCU Lxss registry BasePath for "
                "Ubuntu-22.04 = F:\\MaskFactory_Offload_20260714\\WSL\\Ubuntu-22.04, `wsl -l -v` shows "
                "Ubuntu-22.04 Running, and the file's LastWriteTime advanced during this session's "
                "`wsl -l -v` probe. Ubuntu-22.04 has been genuinely relocated off C: onto this F: path "
                "(superseding the earlier known-corrupt on-C: ext4 finding referenced in "
                "needs_agent_actions_20260720.json action_id=repair_ubuntu_2204_ext4_vhd -- that item "
                "should be re-verified fresh rather than assumed still corrupt, since the distro now "
                "lives on a different physical disk)."
            ),
        },
    },
    "docker_desktop_live_location": {
        "docker_desktop_distro_basepath": "\\\\?\\C:\\Users\\kevin\\AppData\\Local\\Docker\\wsl\\main",
        "docker_desktop_main_vhdx": {
            "path": "C:\\Users\\kevin\\AppData\\Local\\Docker\\wsl\\main\\ext4.vhdx",
            "size_bytes": 100663296,
            "note": "Small utility-VM rootfs disk; LastWriteTime advanced live during this probe (9:38:25 AM).",
        },
        "docker_data_disk_live": {
            "path": "C:\\Users\\kevin\\AppData\\Local\\Docker\\wsl\\disk\\docker_data.vhdx",
            "size_bytes": 73131884544,
            "size_gib": round(73131884544 / 2**30, 2),
            "last_write_time_samples": ["2026-07-20T09:36:16-05:00", "2026-07-20T09:37:46-05:00"],
            "status": "LIVE_ACTIVE_ON_C",
        },
        "conclusion": (
            "Docker Desktop's WSL2 backend (both the docker-desktop utility distro and its /var/lib/docker "
            "data disk) is currently running from C:, matching docker_relocation_f_absent_blocked_20260720T1435Z.json "
            "('vhdx_still_on_c': true). Only the Ubuntu-22.04 general-purpose WSL distro has actually moved to F:. "
            "The docker_data.vhdx under F:\\MaskFactory_Offload_20260714\\DockerDesktop\\wsl\\disk is a leftover "
            "stale copy from an earlier, apparently abandoned/reverted relocation attempt -- Docker was NOT "
            "successfully relocated to F: and is not relocated as of this probe."
        ),
    },
    "wsl_registry_basepaths": {
        "docker-desktop": "\\\\?\\C:\\Users\\kevin\\AppData\\Local\\Docker\\wsl\\main",
        "Ubuntu-22.04": "F:\\MaskFactory_Offload_20260714\\WSL\\Ubuntu-22.04",
        "Cursor-Agent-WSL1": "C:\\Users\\kevin\\AppData\\Local\\wsl\\{e18e8690-b5a8-4ed9-93c5-bc139944cd3c}",
    },
    "wsl_list_verbose_state": "docker-desktop=Running(2); Ubuntu-22.04=Running(2); Cursor-Agent-WSL1=Stopped(1)",
    "maskfactory_data_relocated": {
        "path": "F:\\MaskFactory_DataRelocated",
        "top_level_contents": [
            "cvat",
            "cvat_v2",
            "dvc_local_remote",
            "images",
            "incoming",
            "packages",
            "maskfactory.sqlite (49152 bytes)",
        ],
        "prior_documented_size_gib": 2.98,
        "prior_size_evidence": "qa/live_verification/needs_agent_actions_20260720.json action_id=disk_headroom_above_75_gib",
        "additions_since_relocation": [
            "dvc_local_remote/ (added by dvc_push_local_first item; local DVC remote target for cache objects)",
        ],
        "readable_this_probe": True,
    },
    "data_junction": {
        "junction_path": "C:\\Comfy_UI_Main_Masking\\data",
        "link_type": "Junction",
        "target": "F:\\MaskFactory_DataRelocated",
        "attributes": "Directory, ReparsePoint",
        "readable_this_probe": True,
        "listing_this_probe": ["cvat", "cvat_v2", "dvc_local_remote", "images", "incoming", "maskfactory.sqlite", "packages"],
        "free_space_reported_at_mount_bytes": 194575302656,
        "health": "HEALTHY_RESOLVES_TO_F",
        "contrast_with_prior_report": (
            "docker_relocation_f_absent_blocked_20260720T1435Z.json found this same junction DANGLING "
            "('File Not Found') and had repointed it to C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated "
            "as a non-destructive fix while F: was absent. This probe finds the junction resolving to "
            "F:\\MaskFactory_DataRelocated again, which is consistent with either the drive having been "
            "reconnected and the junction repointed back to F: by a sibling session, or two independent "
            "junction states existing transiently across parallel sessions. C:\\Comfy_UI_Main_Masking\\"
            "data_c_backup_relocated is confirmed still present on disk (git status shows its "
            "maskfactory.sqlite-shm/-wal as untracked) as the retained non-destructive fallback either way."
        ),
    },
    "host_snapshot_this_probe": {
        "c_free_gib": round(c_usage.free / 2**30, 2),
        "f_free_gib": round(f_usage.free / 2**30, 2),
        "f_present": True,
        "docker_engine": "UP (server 29.6.1, context docker-desktop)",
        "docker_ps_containers_up": 37,
        "docker_containers_note": "All containers showed 'Up 3 minutes' at probe time (recent engine/WSL restart in this shared session window), including production cvat_* (v2.24 pinned stack), isolated cvat269_* rehearsal stack, and nuclio-nuclio-pth-sam2 (healthy).",
        "cvat_about_http": "UNREACHABLE_AT_PROBE (curl.exe exit 52 / empty reply; Invoke-WebRequest connection closed unexpectedly) despite cvat_server showing 'Up 3 minutes' in docker ps -- most likely still warming up after the recent restart; not re-polled to green by this probe since CVAT liveness was not the primary ask.",
        "ollama_version": "0.32.1",
    },
    "honesty": [
        "This is a point-in-time layout/state map, not a doctor-all-green or relocation-success claim.",
        "Docker's live data disk is confirmed still on C:, not F:, despite an F: copy existing (stale, abandoned attempt).",
        "Ubuntu-22.04 WSL distro relocation to F: is confirmed live and genuine (registry BasePath + active LastWriteTime + Running state), superseding the previously-recorded on-C: ext4 corruption context for that distro -- that repair item needs fresh re-verification on its new F: location, not assumed carried-over corruption.",
        "F: is a physically detachable USB drive that was observed absent by a sibling session within the same probe hour; this drive now anchors both the data/ junction and the live Ubuntu-22.04 distro, which is a real risk flagged to Kevin, not silently accepted.",
        "CVAT HTTP reachability was not re-polled to green in this probe; recorded as unreachable-at-probe-time rather than assumed healthy just because docker ps showed the container Up.",
    ],
    "claims_not_established": [
        "docker_data_disk_relocated_to_f (false; still on C:)",
        "f_drive_permanently_fixed_non_removable (false; USB bus, prior disconnect observed)",
        "cvat_about_http_200_this_probe (unreachable at probe time)",
        "doctor_all_green",
    ],
    "no_open_human_stop_states": True,
}

payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("SEALED", OUT.name, evidence["self_sha256"][:16])
print("c_free_gib", round(c_usage.free / 2**30, 2), "f_free_gib", round(f_usage.free / 2**30, 2))
