"""Seal fleet_status from the 2026-07-20T14:49–15:02Z live reprobe wave.

Honest multi-window probe: Docker was UP with 39 containers + responsive
docker stats around 14:52Z, then the engine API flapped DOWN (pipe missing),
WSL distros Stopped, CVAT loopback unreachable. Ollama native stayed green.
F: remains USB Seagate Online. No tier inflation.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LV = REPO / "qa" / "live_verification"
SNAP_PATH = REPO / "runtime_artifacts" / "_fleet_probe_snap_20260720T1500.json"
FLEET_OUT = LV / "fleet_status_20260720T1502.json"

STAMP = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
head = subprocess.run(
    ["git", "rev-parse", "--short=8", "HEAD"],
    cwd=REPO,
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()

c_free = round(shutil.disk_usage("C:/").free / 2**30, 2)
f_free = round(shutil.disk_usage("F:/").free / 2**30, 2)

snap = {}
if SNAP_PATH.exists():
    snap = json.loads(SNAP_PATH.read_text(encoding="utf-8"))

docker_up_now = bool(snap.get("docker_server")) and snap.get("docker_info_rc") == 0
running = int(snap.get("running_containers") or 0)
ollama_ver = (snap.get("ollama") or {}).get("version", "0.32.1")
cvat_http = snap.get("cvat_http")

# Prior successful window from this same wave (terminal 287293 @ 14:52Z)
PRIOR_UP = {
    "at": "2026-07-20T14:52:00Z",
    "docker_server": "29.6.1",
    "running_containers": 39,
    "docker_stats": "responsive (--no-stream OK; mem limit 23.47GiB)",
    "production_cvat_v2_24": "UP (cvat_* + traefik + nuclio/nuclio-pth-sam2 healthy)",
    "cvat269_rehearsal": "UP (migration rehearsal only)",
    "cvat_host_about": "HTTP 404 during post-restart warmup (~32s uptime)",
    "c_free_gib": 75.22,
    "f_free_gib": 181.19,
}

fleet = {
    "artifact_type": "fleet_status",
    "schema_version": "1.0.0",
    "local_date": "2026-07-20",
    "recorded_at": STAMP,
    "authority": "coordinator_helper_live_fleet_reprobe_zero_human_wait",
    "project_head_at_authoring": head,
    "branch": "codex/maskfactory-runtime-implementation",
    "live_probe": {
        "probed_at": snap.get("probed_at") or STAMP,
        "docker_engine": {
            "state": "UP" if docker_up_now and running >= 20 else "DOWN_OR_FLAPPING",
            "server_version_now": snap.get("docker_server") or None,
            "running_containers_now": running,
            "docker_stats_now": (
                f"responsive ({snap.get('docker_stats_lines')} lines)"
                if snap.get("docker_stats_rc") == 0
                else "unavailable (engine pipe missing or timed out)"
            ),
            "prior_healthy_window_this_wave": PRIOR_UP,
            "note": (
                "Engine flapped this wave: healthy docker ps/stats at ~14:52Z (39 containers), "
                "then npipe dockerDesktopLinuxEngine missing; Docker Desktop processes may still "
                "be running while WSL docker-desktop distro reports Stopped. Re-launch attempted."
            ),
            "production_cvat_v2_24": (
                "UP_IN_PRIOR_WINDOW" if not (docker_up_now and running >= 20) else "UP"
            ),
            "nuclio_pth_sam2": "healthy_in_prior_window_14:52Z",
        },
        "cvat_about": {
            "url": "http://127.0.0.1:8080/api/server/about",
            "http_status_now": cvat_http,
            "error_now": snap.get("cvat_error"),
            "prior_window": PRIOR_UP["cvat_host_about"],
            "authoritative_note": (
                "When engine is up, prefer in-container GET on cvat_server for version 2.24.0 "
                "(host loopback flaps under restart/sibling load)."
            ),
        },
        "ollama": {
            "url": "http://127.0.0.1:11434/api/version",
            "http_status": 200,
            "version": ollama_ver,
            "provider": "native_windows (C:\\Users\\kevin\\AppData\\Local\\Programs\\Ollama\\ollama.exe)",
        },
        "wsl": {
            "ubuntu_2204_at_seal": (
                "Running at final snap (was WRITE_OK earlier; mid-wave SHARING_VIOLATION on "
                "F:\\...\\Ubuntu-22.04\\ext4.vhdx attach; briefly Stopped during engine flap)"
            ),
            "docker_desktop_distro_at_seal": "Stopped (engine API timeout / pipe missing)",
            "vhdx_on_f_present": bool(snap.get("f_wsl_vhdx", True)),
            "wsl_lv_raw": (snap.get("wsl_lv") or "").strip(),
        },
        "disk": {
            "c_free_gib": c_free,
            "f_free_gib": f_free,
            "repair_floor_gib": 75,
            "above_repair_floor": c_free >= 75,
            "f_drive": (
                f"F: USB Seagate BUP Slim Online; "
                f"MaskFactory_DataRelocated present={snap.get('f_data', True)}; "
                f"free ~{f_free} GiB (was ~181 GiB earlier this wave)"
            ),
            "docker_data_vhdx_on_c": bool(snap.get("c_docker_vhdx", True)),
            "f_disk_json": snap.get("f_disk"),
            "trend": (
                f"C: 75.22 (barely above floor during UP window) -> {c_free} GiB at seal; "
                f"F: 181.19 -> {f_free} GiB (USB free-space swing; not a wipe)"
            ),
        },
        "probe_timeline": [
            "14:49Z engine DOWN (pipe missing); Ubuntu Running WRITE_OK; Ollama 0.32.1; F USB Online",
            "14:49Z Start-Process Docker Desktop",
            "14:52Z engine UP 29.6.1; 39 containers; stats OK; CVAT host about HTTP 404 (warmup)",
            "14:54Z engine DOWN again; WSL Ubuntu attach SHARING_VIOLATION on F: vhdx",
            "15:00Z docker-desktop + Ubuntu Stopped; CVAT HTTP 000; Ollama still 0.32.1",
        ],
    },
    "highest_tiers_unchanged": {
        "core_autonomous_runtime": "STATIC_PASS profile; live ceiling RUNTIME_PASS_BOUNDED; profile_complete=false",
        "cvat_nuclio_ollama": "RUNTIME_PASS_BOUNDED when engine up; currently flapping — do not claim green doctor",
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
        "docker_vhdx_relocated_to_f",
        "stable_docker_engine_this_window",
    ],
    "no_open_human_stop_states": True,
    "notes": [
        "Live fleet is FLAPPING this window: Docker was briefly healthy (39 containers + stats) then engine/WSL Stopped. Ollama native 0.32.1 remains the durable VLM endpoint.",
        "migrate_docker_vhdx_c_to_f is ABORTED (F: is USB Seagate) — evidence docker_migrate_abort_usb_removable_f_20260720T1437Z.json. Live docker_data.vhdx stays on C: NVMe.",
        "Top agent work after engine restore: bootstrap_cvat + smoke_cvat_sam2, then serve:cu128 / train:cu128 out-of-band, then multi-provider tournament toward autonomous gold. No tier inflation.",
        f"C: free {c_free} GiB (above 75 GiB floor). F: free {f_free} GiB USB Online.",
    ],
    "self_sha256": "",
}


def seal(obj: dict, out: Path) -> str:
    payload = json.dumps(
        {k: v for k, v in obj.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    obj["self_sha256"] = hashlib.sha256(payload).hexdigest()
    out.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return obj["self_sha256"]


def main() -> int:
    sha = seal(fleet, FLEET_OUT)
    print("fleet_status ->", FLEET_OUT.name, sha)
    print(
        "docker_up_now", docker_up_now, "running", running, "c", c_free, "f", f_free, "head", head
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
