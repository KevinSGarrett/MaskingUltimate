"""Seal Docker VHDX migrate abort: F: is USB removable (Seagate BUP Slim)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = (
    REPO_ROOT
    / "qa"
    / "live_verification"
    / "docker_migrate_abort_usb_removable_f_20260720T1437Z.json"
)


def _head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    evidence = {
        "artifact_type": "maskfactory_docker_data_relocation_abort",
        "schema_version": "1.0.0",
        "recorded_at": now,
        "local_date": "2026-07-20",
        "branch": "codex/maskfactory-runtime-implementation",
        "project_head_at_authoring": _head(),
        "requested_task": (
            "Relocate live Docker Desktop docker_data.vhdx from C: to F: "
            "(MaskFactory_Offload / DockerDesktopData); update settings-store; "
            "preserve CVAT volumes; bootstrap+smoke."
        ),
        "critical_update": (
            "Sibling cab71658: F: is a REMOVABLE external drive that disconnects; "
            "only NVMe C: is fixed. Never put docker_data.vhdx on removable media."
        ),
        "outcome": "ABORTED_HARD_STOP_F_DRIVE_USB_REMOVABLE",
        "decision": "ABORT_MIGRATE_ENTIRELY",
        "mutation_performed": False,
        "docker_vhdx_relocated": False,
        "settings_store_dataFolder_changed": False,
        "docker_prune_performed": False,
        "volume_wipe_performed": False,
        "completion_credit": False,
        "probe": {
            "test_path_f": True,
            "get_volume_drive_type": "Fixed",
            "get_volume_note": (
                "Get-Volume reports DriveType=Fixed for this USB HDD; "
                "authoritative BusType from Get-Disk is USB — treat as removable."
            ),
            "get_disk": {
                "number": 1,
                "friendly_name": "Seagate BUP Slim BK",
                "bus_type": "USB",
                "size_gib": 1863.02,
                "operational_status": "Online",
                "partition_style": "MBR",
            },
            "fixed_nvme_only": {
                "number": 0,
                "friendly_name": "SKHynix_HFS001TEM4X182N",
                "bus_type": "NVMe",
            },
            "stale_f_vhdx": {
                "path": (
                    r"F:\MaskFactory_Offload_20260714\DockerDesktop\wsl\disk\docker_data.vhdx"
                ),
                "present": True,
                "bytes": 73131884544,
                "last_write_local": "2026-07-20T03:04:25",
                "note": "STALE unlocked duplicate — not the live Docker disk; left untouched.",
            },
        },
        "blocker": {
            "summary": (
                "F: is present but is a USB Seagate Backup Plus Slim external drive. "
                "Live Docker data must remain on fixed NVMe C:. Migrating the locked "
                "live VHDX onto F: would recreate disconnect-driven daemon/crash-loop risk "
                "and endanger CVAT volumes."
            ),
            "why_not_forced": (
                "Get-Disk BusType=USB is dispositive even when Get-Volume says Fixed. "
                "settings-store.json has no dataFolder to F:; live vhdx stays on C:. "
                "No quit/shutdown/move/import was started after this critical update."
            ),
        },
        "docker_state": {
            "docker_data_vhdx_path": (
                r"C:\Users\kevin\AppData\Local\Docker\wsl\disk\docker_data.vhdx"
            ),
            "docker_data_vhdx_bytes": 73131884544,
            "docker_data_vhdx_gib": 68.11,
            "vhdx_still_on_c": True,
            "server_version": "29.6.1",
            "context": "docker-desktop",
            "docker_root_dir": "/var/lib/docker",
            "settings_store_path": r"%APPDATA%\Docker\settings-store.json",
            "settings_store_has_dataFolder": False,
            "settings_store_dataFolder_value": None,
        },
        "host_snapshot": {
            "c_free_gib": 91.336,
            "f_present": True,
            "f_bus_type": "USB",
            "f_friendly_name": "Seagate BUP Slim BK",
        },
        "cvat_status": {
            "containers_observed_running": [
                "cvat_server (cvat/server:v2.24.0)",
                "traefik (traefik:v3.6.1)",
                "nuclio (healthy)",
                "nuclio-nuclio-pth-sam2 (healthy)",
            ],
            "bootstrap_cvat_py": "ran; compose reported all production cvat_* containers Running; exit 0",
            "api_about": {
                "host_curl_127_0_0_1_8080": "empty_reply_curl_52_intermittent_under_sibling_load",
                "in_container_cvat_server": {
                    "result": "ok",
                    "version": "2.24.0",
                    "name": "Computer Vision Annotation Tool",
                },
                "note": (
                    "Production CVAT remains on C:-hosted Docker data. Host loopback about "
                    "flapped empty-reply (curl 52) under concurrent sibling traffic; "
                    "authoritative in-container GET /api/server/about -> version 2.24.0."
                ),
            },
            "production_pin": "cvat/server:v2.24.0 @ localhost:8080",
        },
        "actions_not_taken": [
            "Quit Docker Desktop",
            "wsl --shutdown",
            "move/robocopy live C: vhdx to F:",
            "settings-store.json dataFolder retarget",
            "wsl --export/--import of docker-desktop-data",
            "delete/replace stale F: vhdx copy",
            "docker system prune / volume wipe",
        ],
        "kevin_actions_required": [
            "Provision a PERMANENT fixed internal/second NVMe (or always-present non-USB volume) before any Docker dataFolder relocation.",
            "Keep F: USB drive for optional static offload only with C: disconnect-safe fallback; never host docker_data.vhdx there.",
        ],
        "claims_not_established": [
            "docker_vhdx_relocated_to_f",
            "c_disk_pressure_permanently_resolved_via_relocation",
            "doctor_all_green",
        ],
        "related_prior_seal": (
            "qa/live_verification/docker_relocation_f_absent_blocked_20260720T1435Z.json"
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
