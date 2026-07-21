"""Seal the 2026-07-20 WSL Ubuntu-22.04 execvpe/bash I/O-error probe.

VHDX confirmed present on F:; non-elevated shell hits `execvpe(/bin/bash)
failed: I/O error` starting bash inside Ubuntu-22.04; elevation is
unavailable non-interactively (IsAdmin=False); Docker-GPU stays the primary
CUDA path for serve/train/tournament work. Honest, no tier inflation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "wsl_ubuntu_io_error_20260720.json"

evidence = {
    "artifact_type": "wsl_ubuntu_io_error_probe",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "project_head_at_authoring": "eb17dd21",
    "branch": "codex/maskfactory-runtime-implementation",
    "authority": "autonomous_full_autonomy_runtime_climb_zero_human_wait",
    "summary": (
        "F: is back online and the Ubuntu-22.04 ext4.vhdx is present on it. "
        "A non-elevated probe this wave (09:33 CDT / 14:33Z) hit "
        "`execvpe(/bin/bash) failed: I/O error` when starting bash inside the "
        "distribution, even though `wsl -l -v` reports it Running. Elevation is "
        "unavailable non-interactively (IsAdmin=False), so the scripted repair "
        "(tools/Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair) was not run. "
        "Docker-GPU remains the primary/authoritative CUDA path for "
        "serve/train/tournament work; the native-WSL torch path stays a "
        "secondary, currently-unreliable lane pending an elevated shell."
    ),
    "vhdx": {
        "path": "F:\\MaskFactory_Offload_20260714\\WSL\\Ubuntu-22.04\\ext4.vhdx",
        "test_path_result": True,
        "checked_at": "2026-07-20T14:33:00Z",
        "f_drive_state_this_wave": "present (Get-PSDrive F succeeded; ~181.2 GiB free at 14:35Z re-probe)",
        "known_volatility": (
            "F: is a removable/external drive that has disconnected and "
            "reconnected multiple times this session (see Plan/OPS_LOG.md "
            "2026-07-20 14:35 UTC entry recording F: physically absent from a "
            "concurrent sibling probe at essentially the same wall-clock wave). "
            "Treat F:-dependent state as point-in-time, not durable, until the "
            "drive is confirmed to stay attached across a full session."
        ),
    },
    "admin_check": {
        "is_admin": False,
        "method": "[Security.Principal.WindowsPrincipal]::IsInRole(Administrator)",
        "checked_at": "2026-07-20T14:33:00Z",
        "reconfirmed_at": "2026-07-20T14:35:00Z",
        "reconfirmed_is_admin": False,
        "implication": (
            "tools/Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair requires an "
            "already-elevated shell and this session deliberately never "
            "self-elevates (no UAC prompts / no interactive human wait). A "
            "sibling stream this same wave is separately exhausting "
            "non-interactive elevation paths (Start-Process -Verb RunAs, "
            "schtasks, gsudo/sudo/wt helpers); this seal does not duplicate "
            "that attempt or claim its result."
        ),
    },
    "wsl_probe": {
        "command": "wsl -d Ubuntu-22.04 -- echo ok ; wsl -l -v",
        "captured_at": "2026-07-20T14:33:00Z",
        "raw_error": "<3>WSL (220 - Relay) ERROR: CreateProcessCommon:818: execvpe(/bin/bash) failed: I/O error",
        "wsl_list_verbose": [
            {"name": "Ubuntu-22.04", "state": "Running", "version": 2, "default": True},
            {"name": "docker-desktop", "state": "Running", "version": 2, "default": False},
            {"name": "Cursor-Agent-WSL1", "state": "Stopped", "version": 1, "default": False},
        ],
        "diagnosis": (
            "The distribution reports Running and the WSL kernel/init respond "
            "to `wsl -l -v`, but starting a bash init process inside it fails "
            "at execvpe with I/O error - consistent with the previously "
            "diagnosed ext4 root-filesystem corruption "
            "(qa/live_verification/wsl_emergency_ro_diagnosis_20260717T094921Z.json) "
            "persisting even though the backing VHDX is now reachable on F:."
        ),
    },
    "reverification_20260720T1435Z": {
        "note": (
            "A later re-probe in this same sealing pass, ~2 minutes after the "
            "original execvpe capture, no longer reproduced the error: "
            '`wsl -d Ubuntu-22.04 -- /bin/bash -c "echo hello"` returned '
            "`hello` (exit 0). This coincided with a Docker Desktop restart "
            "cycle observed in parallel (`docker info` briefly 500'd; "
            "`docker ps` then showed all cvat_*/cvat269_*/nuclio containers "
            "freshly Up 7-9 seconds; `wsl -l -v` showed docker-desktop flip "
            "Running -> Stopped -> restarting). Docker Desktop's WSL2 core VM "
            "restart plausibly re-attached/re-mounted the Ubuntu-22.04 VHDX "
            "cleanly, which can transiently clear this class of I/O error "
            "without a filesystem repair. This is NOT claimed as a durable fix: "
            "no e2fsck / offline repair was run, admin is still False, and the "
            "underlying root cause (documented ext4 corruption from the "
            "2026-07-17 emergency_ro incident) has not been remediated. Ollama "
            "(0.32.1) responded live; CVAT briefly reset its connection mid-restart."
        ),
        "bash_exec_result": "PASS (transient; unrepaired root cause)",
        "docker_desktop_wsl_state_observed": "Stopped -> restarting -> containers Up (7-9s)",
        "ollama_http": "200 (version 0.32.1)",
        "cvat_http": "connection reset mid-restart (Docker Desktop cycling)",
    },
    "docker_gpu_primary": {
        "decision": "Docker-GPU remains the primary/authoritative CUDA path for serve/train/tournament work.",
        "rationale": [
            "GPU CUDA capability is independently proven via `docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi` (RTX 5060 Laptop GPU, driver 592.01, 8151 MiB) regardless of native-WSL distro health.",
            "Native Ubuntu-22.04 WSL torch path is intermittent this wave (execvpe I/O error, then a transient self-clear after a Docker Desktop restart) and depends on an elevated shell for a durable repair that is not available non-interactively.",
            "No serve/train/tournament work is blocked: the Docker-GPU container path does not depend on the Ubuntu-22.04 distribution at all.",
        ],
        "wsl_repair_status": "deferred to elevated shell (tools/Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair); tracked as needs_agent_actions action_id=repair_ubuntu_2204_ext4_vhd",
    },
    "docker_engine_snapshot_20260720T1436Z": {
        "docker_ps_running_containers": 35,
        "containers_state": "all Up 7-9 seconds (mid-restart cycle observed during this pass)",
        "production_cvat": "cvat_server present; /api/server/about connection reset during restart (not sealed as a runtime PASS this file)",
        "no_destructive_ops": "No prune, no volume wipe, no factory reset performed by this seal.",
    },
    "honesty": [
        "No tier inflation: this file documents a probe/diagnostic state, not a repair. champions/gold/doctor-green/PRODUCTION_EVIDENCE_PASS are not touched by this seal.",
        "The execvpe I/O error is real and was captured verbatim; a later transient non-reproduction is reported honestly as unrepaired-root-cause, not as a fix.",
        "F: presence is volatile this session (documented disconnect/reconnect cycles); this file's F:/VHDX claims are point-in-time.",
        "Elevation remains genuinely unavailable non-interactively in this shell; no UAC self-elevation was attempted.",
    ],
    "claims_not_established": [
        "wsl_root_filesystem_repaired",
        "wsl_torch_cuda_live",
        "doctor_all_green",
        "champions>0",
        "autonomous_certified_gold",
        "PRODUCTION_EVIDENCE_PASS",
    ],
    "no_open_human_stop_states": True,
    "unblocks_note": "Does not block serve/train/tournament (Docker-GPU primary path is independent of this distro).",
}

payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("SEALED", OUT.name, evidence["self_sha256"][:16])
