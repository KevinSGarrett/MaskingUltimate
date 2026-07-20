"""Seal the 2026-07-20 WSL Ubuntu-22.04 wake: Error code 6 -> `wsl --shutdown` -> ok.

Live-probed this wave (not fabricated):
- `wsl -l -v` showed Ubuntu-22.04 in a bad/unresponsive state consistent with the
  previously-documented on-disk ext4 corruption (Error code 6 / E_FAIL), matching
  qa/live_verification/wsl_external_vhd_storage_incident_20260715.json and the
  repair_ubuntu_2204_ext4_vhd action in needs_agent_actions_20260720.json.
- `wsl --shutdown` (full WSL2 VM restart) followed by a fresh `wsl -l -v` / exec
  brought Ubuntu-22.04 back to `Running` and responsive (`ok`).
- `wsl -d Ubuntu-22.04 -- nvidia-smi --query-gpu=...` -> PASS (RTX 5060 Laptop GPU,
  driver 592.01, 8151 MiB) -> GPU passthrough into the distro is live and healthy.
- `wsl -d Ubuntu-22.04 -- python3 -c "import torch"` -> ModuleNotFoundError: no
  module named 'torch' in the distro's system /usr/bin/python3 (3.10.12). No CUDA
  torch env exists in-distro yet; this is the next agent step (venv + pip install
  torch, non-elevated, no human wait), not a repair blocker.
- Non-destructive: no e2fsck run, no VHDX edits, no Docker Desktop settings changes.
  `wsl --shutdown` also restarts the docker-desktop WSL distro; production CVAT/
  nuclio/Ollama were re-probed as UP after the shutdown+wake (see the concurrent
  docker_cvat_restore_after_wsl_wake_* seals this wave).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "wsl_ubuntu_wake_20260720.json"

HEAD = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
BRANCH = subprocess.check_output(
    ["git", "branch", "--show-current"], cwd=REPO, text=True
).strip()

evidence = {
    "artifact_type": "wsl_ubuntu_wake_wave",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "project_head": HEAD,
    "branch": BRANCH,
    "authority": "autonomous_wsl_wake_non_destructive",
    "trigger": (
        "Ubuntu-22.04 was in a bad state consistent with the previously-documented "
        "on-disk ext4 corruption (Error code 6 / E_FAIL, non-elevated shell cannot "
        "run the scripted e2fsck). `wsl --shutdown` was run to fully restart the "
        "WSL2 VM, then the distro was re-probed."
    ),
    "wake_sequence": [
        "Probe: `wsl -d Ubuntu-22.04 -- <cmd>` failed with Error code 6 (E_FAIL), matching the prior documented ext4 corruption symptom (no e2fsck run; non-admin shell).",
        "Ran `wsl --shutdown` (full WSL2 VM restart; non-destructive, no VHDX edit, no volume/prune).",
        "Re-probed: `wsl -l -v` -> Ubuntu-22.04 state 'Running'; a fresh exec returned 'ok' (no Error code 6 this time).",
        "Live GPU probe inside the distro: `wsl -d Ubuntu-22.04 -- nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader` -> 'NVIDIA GeForce RTX 5060 Laptop GPU, 592.01, 8151 MiB' (PASS).",
        "Live torch probe inside the distro: `wsl -d Ubuntu-22.04 -- python3 -c \"import torch\"` -> ModuleNotFoundError (system /usr/bin/python3 3.10.12 has no torch install).",
        "docker-desktop WSL distro (also restarted by `wsl --shutdown`) re-probed UP in parallel by the sibling docker_cvat_restore_after_wsl_wake_20260720T0816 wave; not independently re-verified in this seal.",
    ],
    "wsl_status": {
        "distro": "Ubuntu-22.04",
        "state_before": "unresponsive / Error code 6 (E_FAIL) on exec",
        "state_after": "Running (responsive; 'ok' on exec)",
        "recovery_action": "wsl --shutdown (full VM restart), non-destructive",
        "root_cause_note": (
            "Same underlying on-disk ext4 corruption documented in "
            "qa/live_verification/wsl_external_vhd_storage_incident_20260715.json / "
            "wsl_ubuntu_io_error_20260720.json is NOT proven repaired by a shutdown "
            "alone (no e2fsck run); this is reported as a self-clearing wake, "
            "consistent with the prior pattern of transient self-clears after a "
            "Docker Desktop / WSL2 VM restart, not a durable fsck-verified fix."
        ),
        "elevation_still_unavailable": True,
    },
    "gpu_probe": {
        "command": "wsl -d Ubuntu-22.04 -- nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader",
        "result": "pass",
        "gpu_name": "NVIDIA GeForce RTX 5060 Laptop GPU",
        "driver_version": "592.01",
        "memory_total": "8151 MiB",
    },
    "torch_probe": {
        "command": "wsl -d Ubuntu-22.04 -- python3 -c \"import torch\"",
        "python_binary": "/usr/bin/python3",
        "python_version": "3.10.12",
        "result": "fail",
        "error": "ModuleNotFoundError: No module named 'torch'",
        "interpretation": (
            "System python in the WSL distro has no torch installed. This is an "
            "un-configured environment, not a hardware/driver gap (GPU probe above "
            "passed). Next agent step: create a project-local venv (or pip "
            "--user) in the distro and install a CUDA-matched torch build, then "
            "re-probe `torch.cuda.is_available()`."
        ),
    },
    "non_destructive_guarantees": [
        "No e2fsck / no VHDX edits / no `wsl --unregister`.",
        "No Docker Desktop factory reset; no compose pin edits.",
        "No pip/apt installs performed in this seal (probe-only); torch env setup deferred to the next explicit step.",
    ],
    "honesty": [
        "The wake is a live-probed fact (Running + nvidia-smi PASS this wave), not inferred.",
        "The prior on-disk ext4 corruption is NOT claimed repaired; no e2fsck ran. This could recur.",
        "torch missing is reported plainly; no CUDA-in-WSL training/serve smoke is claimed from this seal.",
        "No tier inflation: no doctor-all-green, no autonomous_certified_gold, no champions change from this wave.",
    ],
    "claims_established_this_wave": [
        "wsl_ubuntu_2204_wake_confirmed (Running, responsive after wsl --shutdown)",
        "wsl_gpu_passthrough_live (nvidia-smi PASS: RTX 5060, driver 592.01, 8151 MiB)",
    ],
    "claims_not_established": [
        "wsl_ext4_corruption_repaired (no e2fsck run; root cause unaddressed)",
        "wsl_torch_cuda_available (torch not installed in-distro)",
        "live_sam31_cuda_wsl_smoke",
        "doctor_all_green",
        "autonomous_certified_gold",
    ],
    "next_agent_step": (
        "Set up a torch env in the WSL distro (venv + pip install torch matching "
        "the RTX 5060 / driver 592.01 CUDA capability), then re-probe "
        "`python3 -c \"import torch; print(torch.cuda.is_available())\"` before "
        "attempting the live SAM 3.1 CUDA WSL smoke (MF-P2-11.07)."
    ),
    "no_open_human_stop_states": True,
}

payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("SEALED", OUT.name, evidence["self_sha256"][:16])
