"""Append the execvpe/bash I/O-error probe evidence onto needs_agent_actions_20260720.json.

Reads the file fresh (siblings write this file concurrently this wave),
appends new evidence to the existing repair_ubuntu_2204_ext4_vhd action
without discarding the sibling's Docker-GPU-primary reclassification, and
re-seals with a fresh self_sha256 chained off the prior file's hash.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"

prior_bytes = TARGET.read_bytes()
prior_sha256 = hashlib.sha256(prior_bytes).hexdigest()
doc = json.loads(prior_bytes.decode("utf-8"))

for action in doc["actions"]:
    if action.get("action_id") == "repair_ubuntu_2204_ext4_vhd":
        action["execvpe_io_error_probe_20260720T1433Z"] = (
            "Non-elevated probe this wave: VHDX confirmed present on F: "
            "(Test-Path True); `wsl -d Ubuntu-22.04 -- echo ok` failed with "
            "`<3>WSL (220 - Relay) ERROR: CreateProcessCommon:818: "
            "execvpe(/bin/bash) failed: I/O error`; `wsl -l -v` still reports "
            "Ubuntu-22.04 Running. IsAdmin=False reconfirmed. A ~2-minute-later "
            "re-probe (coinciding with a Docker Desktop WSL2 core VM restart) "
            'no longer reproduced the error (`bash -c "echo hello"` -> '
            "PASS), but this is reported as a transient, unrepaired-root-cause "
            "self-clear, NOT a durable fix (no e2fsck run; admin still False)."
        )
        action["execvpe_evidence"] = "qa/live_verification/wsl_ubuntu_io_error_20260720.json"
        break
else:
    raise SystemExit("repair_ubuntu_2204_ext4_vhd action not found; refusing to append blindly")

doc["host_snapshot"][
    "f_drive_state_20260720T1435Z"
] = "present (~181.2 GiB free); known intermittent this session"
doc["latest_reverification"][
    "wsl_execvpe_probe"
] = "captured then transiently self-cleared after Docker Desktop restart (not a repair)"
doc["recorded_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
doc["supersedes"] = {
    "path": "qa/live_verification/needs_agent_actions_20260720.json (prior self, this wave)",
    "file_sha256": prior_sha256,
    "reason": "Append execvpe/bash-I/O-error probe evidence (qa/live_verification/wsl_ubuntu_io_error_20260720.json) onto the existing repair_ubuntu_2204_ext4_vhd action; no other fields changed besides host_snapshot/latest_reverification WSL notes.",
}

doc.pop("self_sha256", None)
payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
doc["self_sha256"] = hashlib.sha256(payload).hexdigest()
TARGET.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("UPDATED", TARGET.name, doc["self_sha256"][:16])
