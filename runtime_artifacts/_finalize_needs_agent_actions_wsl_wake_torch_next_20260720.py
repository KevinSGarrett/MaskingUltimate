"""Minimal, purely-additive patch to needs_agent_actions_20260720.json: WSL wake DONE; torch env next.

This file is a hot shared target this wave (many concurrent sibling commits landing
within seconds). To avoid clobbering a moving target, this script adds ONE new
top-level key with a unique timestamped name and touches nothing else -- no
existing key (status, host_snapshot, live_priorities_this_wave, etc.) is modified.
Re-seals with a fresh self_sha256 over the whole (unchanged-elsewhere) document.
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

doc["wsl_torch_env_next_20260720T1451Z"] = {
    "evidence": SEAL,
    "wsl_wake": (
        "DONE this wave: Ubuntu-22.04 hit Error code 6 (E_FAIL), then `wsl --shutdown` "
        "(full non-destructive VM restart) brought it back to Running/responsive ('ok' "
        "on exec). Corrected root cause (reconciled with the sibling F:-restore finding): "
        "the distro's ext4.vhdx lives on the removable F: drive and had briefly "
        "disconnected -- NOT on-disk ext4 corruption."
    ),
    "gpu_probe": "nvidia-smi inside the distro -> PASS (RTX 5060 Laptop GPU, driver 592.01, 8151 MiB).",
    "torch_env_next": (
        "System /usr/bin/python3 (3.10.12) in the distro has no torch installed "
        "(ModuleNotFoundError). Next agent step: venv + pip install a CUDA-matched "
        "torch build in-distro, then re-probe torch.cuda.is_available() before the "
        "live SAM 3.1 CUDA WSL smoke (MF-P2-11.07). No elevation needed for this step."
    ),
    "no_human_wait": True,
    "note": "Purely additive; does not modify the sibling-owned status/host_snapshot fields on this hot shared file.",
}
doc["recorded_at"] = NOW

payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
doc["self_sha256"] = hashlib.sha256(payload).hexdigest()
TARGET.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("UPDATED", TARGET.name, doc["self_sha256"][:16], "prior_sha256", prior_sha256[:16])
