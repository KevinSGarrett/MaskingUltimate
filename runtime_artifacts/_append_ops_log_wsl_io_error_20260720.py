"""Append-only OPS_LOG entry for the WSL Ubuntu-22.04 execvpe/I/O-error seal."""

ENTRY = """
## 2026-07-20 14:45 UTC - WSL Ubuntu-22.04 execvpe/bash I/O-error probe sealed; Docker-GPU stays primary CUDA path
**Item:** repair_ubuntu_2204_ext4_vhd (needs_agent_actions_20260720.json)
**Command:** python runtime_artifacts/_seal_wsl_ubuntu_io_error_20260720.py; python runtime_artifacts/_update_needs_agent_actions_wsl_io_error_20260720.py
**Result:** SEALED (probe, not a repair). F: is back online and `Test-Path F:\\MaskFactory_Offload_20260714\\WSL\\Ubuntu-22.04\\ext4.vhdx` -> True. Non-elevated (`IsAdmin=False`) probe: `wsl -d Ubuntu-22.04 -- echo ok` failed with `<3>WSL (220 - Relay) ERROR: CreateProcessCommon:818: execvpe(/bin/bash) failed: I/O error`, even though `wsl -l -v` reported Ubuntu-22.04 Running. Elevation remains genuinely unavailable non-interactively this session (no UAC self-elevation attempted); the scripted repair (`tools/Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair`) was not run.

A ~2-minute-later re-probe in this same sealing pass, coinciding with an observed Docker Desktop WSL2 core VM restart cycle (`docker info` briefly 500'd, `docker ps` then showed 35 cvat_*/cvat269_*/nuclio containers freshly Up 7-9s), no longer reproduced the error (`wsl -d Ubuntu-22.04 -- bash -c "echo hello"` -> `hello`, exit 0). This is recorded honestly as a **transient self-clear, not a repair**: no e2fsck/offline VHD repair ran, admin is still False, and the documented ext4 root-filesystem corruption from the 2026-07-17 emergency_ro incident has not been remediated. F: itself is known-intermittent this session (disconnected/reconnected multiple times; see the 14:35Z OPS_LOG entry above where a concurrent sibling probe saw F: physically absent at essentially the same wave) - all F:/VHDX claims here are point-in-time.

Per explicit direction and the sibling `docker_gpu_sole_cuda_path_wsl_deferred_20260720` reclassification already present in `needs_agent_actions_20260720.json`, Docker-GPU remains the primary/authoritative CUDA path for serve/train/tournament work; it does not depend on the Ubuntu-22.04 distribution at all, so no train/serve lane waits on this WSL state. `needs_agent_actions_20260720.json` was updated in-place (append onto the existing `repair_ubuntu_2204_ext4_vhd` action + host_snapshot/latest_reverification WSL notes only; no other fields touched) and re-sealed with a fresh `self_sha256` chained off the prior file's hash.

No wipes, no destructive ops, no tier inflation - champions/gold/doctor-green/PRODUCTION_EVIDENCE_PASS untouched by this seal.

Evidence: qa/live_verification/wsl_ubuntu_io_error_20260720.json (self_sha256 a58bf9c8...).
"""

with open("Plan/OPS_LOG.md", "a", encoding="utf-8", newline="\n") as f:
    f.write(ENTRY)
print("APPENDED", len(ENTRY), "chars")
