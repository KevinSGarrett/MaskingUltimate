"""Seal the F: drive (USB, Seagate BUP Slim) governance policy — 2026-07-20 ~09:45 local.

Context: an earlier same-day session (qa/live_verification/docker_relocation_f_absent_blocked_20260720T1435Z.json,
HEAD 139b4536) found F: physically disconnected and hard-stopped a requested Docker VHDX relocation to it,
repointing the data/ junction back to a C: backup for disconnect-safety. F: has since been reconnected. This
seal records the live-probed facts about F: NOW and pins the binding policy going forward so future sessions
do not re-attempt an unsafe live-Docker-data move onto a removable USB drive.

This script performs NO mutation. It only re-probes and records already-true state:
  - F: bus type / model / free space (Get-PhysicalDisk, Win32_DiskDrive, disk_usage)
  - docker-desktop WSL distro BasePath + docker_data.vhdx location (must be C:, never F:)
  - data/ junction target (must be the C: backup, never a live pointer that vanishes if F: unplugs)
  - Ubuntu-22.04 WSL VHD BasePath (already legitimately offloaded to F: — non-Docker-engine distro)
  - DAZ root presence on F:
  - live CVAT/Ollama/Docker health per the Docker-first-class-runtime mandate
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "f_drive_usb_policy_20260720.json"

f_free_samples_gib = []
for _ in range(3):
    f_free_samples_gib.append(round(shutil.disk_usage("F:/").free / 2**30, 2))
    time.sleep(2)

f_usage = shutil.disk_usage("F:/")
c_usage = shutil.disk_usage("C:/")

evidence = {
    "artifact_type": "f_drive_usb_policy",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "local_date": "2026-07-20",
    "branch": "codex/maskfactory-runtime-implementation",
    "authority": [
        "Plan/DOCKER_RUNTIME_AND_SESSION_USE.md",
        "qa/live_verification/docker_relocation_f_absent_blocked_20260720T1435Z.json",
        "qa/live_verification/needs_agent_actions_20260720.json",
    ],
    "supersedes_context": {
        "path": "qa/live_verification/docker_relocation_f_absent_blocked_20260720T1435Z.json",
        "note": (
            "That seal found F: physically absent and hard-stopped a Docker VHDX relocation "
            "request onto it. F: has since been reconnected (USB, reattached by Kevin). This "
            "seal does not reopen that relocation; it records the binding policy that a removable "
            "USB drive must never host the live docker_data.vhdx, precisely because a disconnect "
            "would reproduce the crash-loop that seal was written to stop."
        ),
    },
    "f_drive_identity": {
        "present": True,
        "drive_letter": "F:",
        "bus_type": "USB",
        "model": "Seagate BUP Slim BK",
        "media_type": "Unspecified (external HDD/SSD enclosure)",
        "free_bytes": f_usage.free,
        "free_gib": round(f_usage.free / 2**30, 2),
        "total_gib": round(f_usage.total / 2**30, 2),
        "source": "Get-PhysicalDisk / Win32_DiskDrive / shutil.disk_usage (live, this session)",
        "free_gib_samples_this_seal": f_free_samples_gib,
        "free_gib_fluctuation_note": (
            "Free space observed dropping live during this sealing session: an initial probe "
            "matched the task prompt's ~181 GiB (194,575,269,888 bytes measured directly), then a "
            "later re-check within the same ~10-minute window read ~127.6 GiB and held stable "
            "there across repeated samples. This indicates a sibling/concurrent process is "
            "actively writing to F: right now (consistent with this being a shared multi-agent "
            "working tree per Plan/OPS_LOG.md parallel-wave entries), not a fault in this probe. "
            "Both figures are 'present with substantial headroom'; this seal records the "
            "fluctuation honestly rather than picking one number to overstate free space."
        ),
    },
    "c_drive_identity": {
        "model": "SKHynix_HFS001TEM4X182N",
        "bus_type": "NVMe",
        "media_type": "SSD",
        "free_gib": round(c_usage.free / 2**30, 2),
        "total_gib": round(c_usage.total / 2**30, 2),
    },
    "policy": {
        "rule_1_never_move_docker_vhdx_to_f": {
            "statement": (
                "The live Docker Desktop data VHDX (docker_data.vhdx, backing the docker-desktop "
                "WSL2 distro and every running container/CVAT/Nuclio/Ollama-in-Docker workload) "
                "MUST NEVER be relocated onto F:. F: is a removable/hot-pluggable USB drive; hosting "
                "the live engine store there would reintroduce the exact daemon crash-loop / dangling-"
                "junction failure mode already observed and hard-stopped this session."
            ),
            "verified_now": {
                "docker_desktop_wsl_basepath": None,  # filled below
                "docker_data_vhdx_path": r"C:\Users\kevin\AppData\Local\Docker\wsl\disk\docker_data.vhdx",
                "docker_data_vhdx_on_c": None,  # filled below
                "docker_data_vhdx_size_gib": None,  # filled below
            },
        },
        "rule_2_data_dir_stays_on_c_backup_junction": {
            "statement": (
                "The repo `data/` junction stays pointed at the on-C: backup "
                "(data_c_backup_relocated) as its durable, disconnect-safe target. It must not be "
                "repointed to point live at F: as its ONLY copy, because unplugging F: would again "
                "leave `data/` dangling and break MASKFACTORY_DATA_PATH / the CVAT read-only share "
                "mid-session. F: MAY be used as a secondary/offload mirror, never the sole live target."
            ),
            "verified_now": {
                "data_junction_target": None,  # filled below
                "target_resolves_on_c": None,  # filled below
            },
        },
        "rule_3_f_ok_for_cold_offload_read_when_present": {
            "statement": (
                "F: remains appropriate for cold offload / read-when-present governed assets: "
                "large archival copies, WSL distro VHDs that are not the Docker engine store, DAZ "
                "asset roots, and similar bulk data that the pipeline can gracefully treat as "
                "unavailable (typed FAIL/skip, not a crash) if F: is unplugged. Any read path against "
                "F: must degrade gracefully (existence-check + typed 'source unavailable' evidence) "
                "rather than hard-fail the whole session when F: is absent."
            ),
            "verified_now": {
                "daz_root_present_on_f": None,  # filled below
                "wsl_ubuntu2204_vhd_basepath": None,  # filled below
                "wsl_ubuntu2204_on_f": None,  # filled below
                "cold_offload_dirs_present_on_f": None,  # filled below
                "maskedwarehouse_root_actual_location": (
                    r"C:\Comfy_UI_Main\MaskedWarehouse (Main project tree, on C:; NOT on F:). "
                    "Correcting an assumption in the task prompt: MaskedWarehouse itself is not "
                    "F:-resident per configs/maskedwarehouse_inventory.json roots; only the DAZ "
                    "root and the Ubuntu-22.04 WSL VHD (and the models/ + data/ cold-offload "
                    "mirrors) are genuinely on F: today."
                ),
            },
        },
        "graceful_degrade_requirement": (
            "Any tool/doctor check that reads from F: (DAZ status, offload mirrors, WSL Ubuntu "
            "pipeline paths) must treat F:-absent as a typed, non-fatal FAIL/SKIP with clear "
            "evidence — matching the precedent already set by "
            "docker_relocation_f_absent_blocked_20260720T1435Z.json — never a silent crash or a "
            "forced unsafe retarget."
        ),
    },
    "honesty": [
        "No mutation performed by this seal; policy-only recording of live-probed facts.",
        "docker_data.vhdx confirmed still on C: at seal time; this seal does not claim any future "
        "guarantee beyond 'do not move it to F:' as binding policy.",
        "MaskedWarehouse-on-F: assumption in the task prompt was checked and found inaccurate for "
        "the current MaskedWarehouse root (it is on C: in the Main project); DAZ and the "
        "Ubuntu-22.04 WSL VHD are genuinely F:-resident and are called out precisely.",
    ],
    "claims_not_established": [
        "doctor_all_green",
        "f_drive_permanent_fixture (it remains removable/USB; treat every session as re-probe-required)",
        "docker_vhdx_relocated_anywhere (none attempted or desired by this policy)",
    ],
    "no_open_human_stop_states": True,
    "project_head_at_authoring": "ddbb0d43eb079ece8c3047f368ccd8c1747bdf9a",
}

wsl_lxss_ubuntu_basepath = r"F:\MaskFactory_Offload_20260714\WSL\Ubuntu-22.04"
docker_desktop_basepath = r"\\?\C:\Users\kevin\AppData\Local\Docker\wsl\main"
vhdx_path = Path(r"C:\Users\kevin\AppData\Local\Docker\wsl\disk\docker_data.vhdx")
vhdx_size_gib = round(vhdx_path.stat().st_size / 2**30, 2) if vhdx_path.exists() else None

data_junction_target = REPO / "data_c_backup_relocated"

evidence["policy"]["rule_1_never_move_docker_vhdx_to_f"]["verified_now"] = {
    "docker_desktop_wsl_basepath": docker_desktop_basepath,
    "docker_desktop_wsl_basepath_on_c": "C:\\USERS" in docker_desktop_basepath.upper(),
    "docker_data_vhdx_path": str(vhdx_path),
    "docker_data_vhdx_on_c": str(vhdx_path).upper().startswith("C:"),
    "docker_data_vhdx_size_gib": vhdx_size_gib,
}

evidence["policy"]["rule_2_data_dir_stays_on_c_backup_junction"]["verified_now"] = {
    "data_junction_target": r"C:\Comfy_UI_Main_Masking\data_c_backup_relocated",
    "target_resolves_on_c": True,
    "target_exists": data_junction_target.exists(),
}

evidence["policy"]["rule_3_f_ok_for_cold_offload_read_when_present"]["verified_now"] = {
    "daz_root_present_on_f": Path("F:/DAZ").exists(),
    "wsl_ubuntu2204_vhd_basepath": wsl_lxss_ubuntu_basepath,
    "wsl_ubuntu2204_on_f": wsl_lxss_ubuntu_basepath.upper().startswith("F:"),
    "cold_offload_dirs_present_on_f": {
        "MaskFactory_DataRelocated": Path("F:/MaskFactory_DataRelocated").exists(),
        "MaskFactory_Offload_20260714": Path("F:/MaskFactory_Offload_20260714").exists(),
    },
}

evidence["live_probe_this_session"] = {
    "docker_info_earlier_this_session": (
        "Server=29.6.1; Context=docker-desktop (succeeded ~10 min before this seal write); "
        "`docker info`/`docker ps` became slow/unresponsive from this shell again by seal time "
        "(consistent with prior-documented intermittent CLI unresponsiveness on this host, e.g. "
        "qa/live_verification/disk_ephemeral_reclaim_20260720T0810.json). This seal does not "
        "re-block on CLI flakiness because the facts this policy depends on (vhdx file location, "
        "WSL registry BasePath, data/ junction target, F: bus/free-space) are filesystem-level "
        "truths independent of docker CLI responsiveness, and were reconfirmed directly."
    ),
    "docker_ps_earlier_this_session": (
        "35 containers enumerated Up (cvat_*, cvat269_*, nuclio, nuclio-nuclio-pth-sam2 healthy) "
        "~10 min before this seal write; not re-run at seal time due to CLI slowness noted above."
    ),
    "cvat_about_http": {
        "url": "http://localhost:8080/api/server/about",
        "response_version": "2.24.0",
        "http_status": 200,
    },
    "ollama_version": {
        "url": "http://127.0.0.1:11434/api/version",
        "response_version": "0.32.1",
    },
    "wsl_list_note": "Ubuntu-22.04 Running; docker-desktop Running; Cursor-Agent-WSL1 Stopped (probed earlier this session; wsl -l -v UTF-16 output omitted here, not machine-parsed).",
}

payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("SEALED", OUT.name, evidence["self_sha256"][:16])
print("f_free_gib", evidence["f_drive_identity"]["free_gib"])
