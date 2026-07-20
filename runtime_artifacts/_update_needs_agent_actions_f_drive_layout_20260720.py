"""Update needs_agent_actions with the F: drive layout map finding (2026-07-20 ~09:45 local).

Adds one new action_id (flag F: as a physically-removable USB drive now anchoring both the
governed data/ junction and the live Ubuntu-22.04 WSL distro) and refreshes host_snapshot /
latest_reverification with this session's live probe. Does not remove or contradict any
existing action; purely additive + refreshed snapshot, per the supersedes convention used by
prior updates in this file's history.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
LAYOUT_MAP = REPO / "qa" / "live_verification" / "f_drive_layout_map_20260720.json"

prior_bytes = TARGET.read_bytes()
doc = json.loads(prior_bytes.decode("utf-8"))
layout = json.loads(LAYOUT_MAP.read_text(encoding="utf-8"))

now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

new_action = {
    "action_id": "f_drive_usb_removable_dual_anchor_risk",
    "status": "KEVIN_AWARENESS_NOT_A_BLOCKER",
    "evidence": "qa/live_verification/f_drive_layout_map_20260720.json",
    "finding": (
        "Live layout probe confirms F: (2000.4 GB) is a USB-attached Seagate BUP Slim external "
        "disk (Disk 1, BusType=USB), currently healthy and mounted with 181.21 GiB free. It now "
        "anchors TWO governed/live roles simultaneously: (1) the data/ junction target "
        "F:\\MaskFactory_DataRelocated, and (2) the live Ubuntu-22.04 WSL distro "
        "(registry BasePath F:\\MaskFactory_Offload_20260714\\WSL\\Ubuntu-22.04, confirmed Running "
        "with active LastWriteTime, i.e. genuinely relocated off C:, not merely offloaded). A prior "
        "sibling probe this same session hour (docker_relocation_f_absent_blocked_20260720T1435Z.json) "
        "found this exact drive physically absent, then this probe found it present again -- i.e. a "
        "real disconnect/reconnect happened, not a stale read."
    ),
    "risk": (
        "A future USB disconnect would simultaneously dangle the data/ junction (CVAT "
        "MASKFACTORY_DATA_PATH share, packages, DVC local remote) and crash/potentially corrupt the "
        "live Ubuntu-22.04 WSL distro (echoing the earlier on-C: ext4 corruption this project already "
        "hit once, per action_id=repair_ubuntu_2204_ext4_vhd)."
    ),
    "agent_executable_mitigation": [
        "The data/ junction already has a proven non-destructive C: fallback path "
        "(data_c_backup_relocated) that a sibling session used successfully when F: was absent; "
        "no new tooling needed there.",
        "If Ubuntu-22.04 on F: is lost to a disconnect, it can be re-registered fresh (wsl --install "
        "-d Ubuntu-22.04 or wsl --import) since it is a general-purpose pipeline distro, not the "
        "unique holder of ungoverned data; GPU capability has an independent Docker-container proof "
        "path (nvidia/cuda smoke) that does not depend on this distro.",
        "No agent action reduces the physical USB-disconnect risk itself; this is recorded for "
        "Kevin's awareness of drive placement, not as something blocking further autonomous work.",
    ],
    "docker_data_disk_note": (
        "Docker Desktop's own data disk (docker_data.vhdx, 68.11 GiB) remains live on C: "
        "(C:\\Users\\kevin\\AppData\\Local\\Docker\\wsl\\disk\\docker_data.vhdx) -- NOT relocated to "
        "F:. A stale, non-live copy exists under F:\\MaskFactory_Offload_20260714\\DockerDesktop\\wsl\\"
        "disk\\docker_data.vhdx from an earlier abandoned relocation attempt; it is not read/written by "
        "the running engine and carries no additional USB-disconnect exposure for Docker itself."
    ),
    "no_human_wait": True,
    "kevin_actions_optional": [
        "If preferred, migrate the data/ junction target and/or the Ubuntu-22.04 WSL distro to the "
        "internal NVMe (Disk 0) or another permanently-attached drive to remove the USB-disconnect "
        "exposure. Not required for current work to continue.",
    ],
}

doc.setdefault("actions", []).append(new_action)

doc["host_snapshot"] = dict(doc.get("host_snapshot", {}))
doc["host_snapshot"].update(
    {
        "f_present": True,
        "f_free_gib": layout["host_snapshot_this_probe"]["f_free_gib"],
        "c_free_gib": layout["host_snapshot_this_probe"]["c_free_gib"],
        "f_drive_bus_type": "USB (Seagate BUP Slim, physically removable)",
        "docker_engine": layout["host_snapshot_this_probe"]["docker_engine"],
        "docker_ps_containers_up": layout["host_snapshot_this_probe"]["docker_ps_containers_up"],
        "cvat_about_http": layout["host_snapshot_this_probe"]["cvat_about_http"],
        "ollama_version": layout["host_snapshot_this_probe"]["ollama_version"],
        "wsl_ubuntu_2204_location": "F:\\MaskFactory_Offload_20260714\\WSL\\Ubuntu-22.04 (relocated off C:, Running)",
        "data_drive": "F:\\MaskFactory_DataRelocated (junction from data/); ~181.21 GiB free",
    }
)

doc["latest_reverification"] = {
    "at": now,
    "by": "f_drive_layout_map_sealing_session",
    "evidence": "qa/live_verification/f_drive_layout_map_20260720.json",
    "c_free_gib": layout["host_snapshot_this_probe"]["c_free_gib"],
    "f_free_gib": layout["host_snapshot_this_probe"]["f_free_gib"],
    "f_present": True,
    "champions": doc.get("latest_reverification", {}).get("champions", 0),
    "gold": doc.get("latest_reverification", {}).get("gold", 0),
    "docker": layout["host_snapshot_this_probe"]["docker_engine"],
    "cvat_about_http": layout["host_snapshot_this_probe"]["cvat_about_http"],
    "ollama": layout["host_snapshot_this_probe"]["ollama_version"],
    "new_finding": "f_drive_usb_removable_dual_anchor_risk (Kevin-awareness, non-blocking; see actions[])",
}

doc["supersedes"] = {
    "path": "qa/live_verification/needs_agent_actions_20260720.json (prior self, before this update)",
    "file_sha256": hashlib.sha256(prior_bytes).hexdigest(),
    "reason": (
        "Additive update: append f_drive_usb_removable_dual_anchor_risk finding from "
        "qa/live_verification/f_drive_layout_map_20260720.json and refresh host_snapshot/"
        "latest_reverification with this probe's live disk/docker/CVAT/Ollama state. No prior "
        "action removed or contradicted; still zero human blocking wait states."
    ),
}
doc["recorded_at"] = now
doc.pop("self_sha256", None)

payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
doc["self_sha256"] = hashlib.sha256(payload).hexdigest()
TARGET.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("UPDATED", TARGET.name, doc["self_sha256"][:16])
