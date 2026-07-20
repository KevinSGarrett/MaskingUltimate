"""Refresh needs_agent_actions_20260720.json: WSL Ubuntu wake DONE; torch env is the next step.

Reads the file fresh (siblings write this file concurrently this wave), updates only
the repair_ubuntu_2204_ext4_vhd action + its live-priority entry + host snapshot, and
re-seals with a fresh self_sha256 chained off the prior file's hash. No other fields
touched.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
SEAL = "qa/live_verification/wsl_ubuntu_wake_20260720.json"
NOW = datetime.now(UTC).isoformat().replace("+00:00", "Z")

prior_bytes = TARGET.read_bytes()
prior_sha256 = hashlib.sha256(prior_bytes).hexdigest()
doc = json.loads(prior_bytes.decode("utf-8"))
doc.pop("self_sha256", None)

for action in doc["actions"]:
    if action.get("action_id") == "repair_ubuntu_2204_ext4_vhd":
        action["status"] = "WSL_WAKE_DONE_TORCH_ENV_NEXT"
        action["wsl_wake_20260720"] = (
            "Live-probed this wave: `wsl -d Ubuntu-22.04 -- <cmd>` hit Error code 6 "
            "(E_FAIL, same on-disk ext4 corruption signature as before); ran "
            "`wsl --shutdown` (full WSL2 VM restart, non-destructive) then re-probed "
            "-> Ubuntu-22.04 Running, exec returned 'ok'. `nvidia-smi` inside the "
            "distro -> PASS (RTX 5060 Laptop GPU, driver 592.01, 8151 MiB). "
            "System /usr/bin/python3 (3.10.12) has no torch installed "
            "(ModuleNotFoundError) -> next step is a venv + pip install torch in-distro, "
            "not elevation/e2fsck. Root cause (on-disk corruption) is NOT proven "
            "repaired (no e2fsck run) -> could recur; this is a self-cleared wake."
        )
        action["evidence"] = SEAL
        action["no_human_wait"] = True
        action["unblocks"] = [
            "MF-P0-17.04",
            "MF-P0-17.13",
            "MF-P2-11.07 (live SAM 3.1 CUDA WSL smoke, pending torch env)",
        ]
        break
else:
    raise SystemExit("repair_ubuntu_2204_ext4_vhd action not found; refusing to append blindly")

for entry in doc.get("live_priorities_this_wave", []):
    if entry.get("action_id") == "repair_ubuntu_2204_ext4_vhd":
        entry["status"] = "WSL_WAKE_DONE_TORCH_ENV_NEXT"
        entry["why_now"] = (
            "WSL wake is DONE this wave (Running + nvidia-smi PASS after `wsl --shutdown`). "
            "Next agent-executable step: install a CUDA-matched torch build in-distro "
            "(venv + pip, no elevation needed) and re-probe torch.cuda.is_available() "
            "before the live SAM 3.1 CUDA WSL smoke (MF-P2-11.07). On-disk ext4 corruption "
            "root cause is unrepaired (no e2fsck) and could recur; Docker-GPU remains the "
            "durable fallback CUDA path regardless."
        )
        break

doc.setdefault("host_snapshot", {})["wsl_ubuntu_2204"] = (
    "Running (woken via wsl --shutdown 20260720); nvidia-smi PASS in-distro "
    "(RTX 5060, driver 592.01); torch NOT installed in system python3 (next step)"
)
doc.setdefault("latest_reverification", {})["wsl_ubuntu_2204"] = (
    "wake DONE + gpu-probe PASS; torch env next"
)
doc["recorded_at"] = NOW
doc["supersedes"] = {
    "path": "qa/live_verification/needs_agent_actions_20260720.json (prior self, this wave)",
    "file_sha256": prior_sha256,
    "reason": (
        "Mark repair_ubuntu_2204_ext4_vhd / WSL wake as DONE this wave "
        f"({SEAL}); torch env setup is the reclassified next agent step. No other "
        "fields changed besides host_snapshot/latest_reverification WSL notes."
    ),
}

payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
doc["self_sha256"] = hashlib.sha256(payload).hexdigest()
TARGET.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("UPDATED", TARGET.name, doc["self_sha256"][:16])
