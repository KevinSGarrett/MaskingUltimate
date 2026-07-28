"""Append OPS_LOG entry for fleet reprobe seal 2026-07-20T15:02Z."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OPS = REPO / "Plan" / "OPS_LOG.md"
FLEET = REPO / "qa" / "live_verification" / "fleet_status_20260720T1502.json"
QUEUE = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"

fleet_sha = ""
queue_sha = ""
if FLEET.exists():
    import json

    fleet_sha = json.loads(FLEET.read_text(encoding="utf-8")).get("self_sha256", "")[:12]
if QUEUE.exists():
    import json

    queue_sha = json.loads(QUEUE.read_text(encoding="utf-8")).get("self_sha256", "")[:12]

entry = f"""
## 2026-07-20 15:02 UTC - Live fleet reprobe; seal fleet_status; refresh needs_agent_actions
**Item:** fleet_status + needs_agent_actions (coordinator helper, zero human wait)
**Command:** docker info/ps/stats; curl CVAT/Ollama; wsl -l -v; Get-Disk F:; python runtime_artifacts/_seal_fleet_status_20260720T1502.py; python runtime_artifacts/_update_needs_agent_actions_fleet_reprobe_20260720T1502.py
**Result:** SEALED (honest flap). Docker briefly UP at ~14:52Z (server 29.6.1, 39 containers, stats OK, nuclio-pth-sam2 healthy; CVAT host about HTTP 404 during warmup). Engine then flapped: dockerDesktopLinuxEngine pipe missing / docker info timeout; docker-desktop WSL Stopped at seal while Ubuntu-22.04 Running again. CVAT loopback refused (10061). Ollama native 0.32.1 continuously green. F: USB Seagate BUP Slim Online (~127.63 GiB free; earlier ~181 GiB). C: ~89.8 GiB free (above 75 GiB floor). migrate_docker_vhdx_c_to_f confirmed ABORTED_USB_REMOVABLE_F (sibling abort seal). Priorities re-ranked: restore Docker/CVAT -> serve:cu128 -> train:cu128 -> tournament -> Main HARD. No wipe. No tier inflation (champions=0, no gold/doctor-green/PRODUCTION_EVIDENCE_PASS).

Evidence: qa/live_verification/fleet_status_20260720T1502.json (self_sha256 {fleet_sha}...); qa/live_verification/needs_agent_actions_20260720.json (self_sha256 {queue_sha}...).
"""

text = OPS.read_text(encoding="utf-8")
if "Live fleet reprobe; seal fleet_status; refresh needs_agent_actions" in text:
    print("OPS_LOG already has fleet reprobe entry; skip")
else:
    OPS.write_text(text.rstrip() + "\n" + entry, encoding="utf-8")
    print("APPENDED OPS_LOG", fleet_sha, queue_sha)
