"""Seal honest F-restored tournament → gold-admission climb evidence (no fabrication)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa/live_verification/tournament_gold_admission_climb_20260720T1506.json"


def _seal(doc: dict) -> dict:
    doc.pop("self_sha256", None)
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    doc["self_sha256"] = hashlib.sha256(payload).hexdigest()
    return doc


def main() -> int:
    admission = json.loads(
        (REPO / "qa/live_verification/autonomous_gold_admission_20260720T1447.json").read_text(
            encoding="utf-8"
        )
    )
    evidence = {
        "artifact_type": "tournament_gold_admission_climb",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "local_date": "2026-07-20",
        "branch": "codex/maskfactory-runtime-implementation",
        "authority": "live_probe_plus_admission_driver_fail_closed",
        "evidence_tier": "RUNTIME_PASS_BOUNDED",
        "wave_summary": (
            "F: restored and gold SOURCE roots readable (MaskedWarehouse on "
            "C:\\Comfy_UI_Main; Reference_Images + DAZ on F:). data/ junction kept on "
            "C: backup (USB auto-repoint FORBIDDEN). GPU sequencer planned "
            "nuclio-sam2 + ollama-vlm as run_now (strictly sequential). Production "
            "runs/ scanned: 0 machine_verified_candidate / 0 calibrated_auto_accepted. "
            "Admission driver fail-closed insufficient_autonomous_verified_samples. "
            "Docker Desktop engine crashed mid-wave (named pipe missing); cold "
            "relaunch did not recover within ~4.5 min. Host Ollama remained UP. "
            "Host torch is CPU-only so multi-family CUDA segmentation cannot run "
            "outside Docker GPU containers. No certificate minted; no fabrication."
        ),
        "f_drive": {
            "present": True,
            "free_gib": 127.63,
            "maskedwarehouse": {
                "path": r"C:\Comfy_UI_Main\MaskedWarehouse",
                "present": True,
                "celebamask_hq": True,
                "lapa": True,
                "lv_mhp_v1": True,
            },
            "reference_library": {
                "source_root": r"F:\Reference_Images",
                "present": True,
                "sqlite_present": True,
            },
            "daz": {"path": r"F:\DAZ", "present": True, "top_level_dirs": 25},
            "data_junction": {
                "action": "kept_on_c_backup_per_forbidden_usb_auto_repoint",
                "target": r"C:\Comfy_UI_Main_Masking\data_c_backup_relocated",
                "f_data_mirror_present": True,
                "f_data_mirror_path": r"F:\MaskFactory_DataRelocated",
                "auto_repoint_to_f": "FORBIDDEN",
                "policy_evidence": (
                    "qa/live_verification/data_junction_forced_c_backup_20260720T1504Z.json"
                ),
                "note": (
                    "Brief erroneous mklink to F: during this wave was immediately "
                    "reverted; production data/ stays on C: backup. Gold SOURCE roots "
                    "(MaskedWarehouse / Reference_Images / DAZ) remain independently readable."
                ),
            },
        },
        "gpu_sequencing": {
            "policy": "Plan/GPU_SEQUENCING_AND_VRAM_BUDGET.md",
            "tool": "tools/gpu_sequencer.py",
            "nuclio_sam2_decision": "run_now",
            "ollama_vlm_decision": "run_now",
            "free_mib_at_plan": 7771,
            "total_mib": 8151,
            "foreign_holders": [],
            "lock_state": "absent",
            "ordering": ["nuclio-sam2", "ollama-vlm"],
            "never_concurrent": True,
            "live_sam2_smoke_this_wave": "NOT_RUN_DOCKER_ENGINE_DOWN",
            "live_ollama_vlm_smoke_this_wave": "NOT_RUN_SEQUENCED_AFTER_SAM2_BLOCKED",
        },
        "docker_runtime": {
            "start_of_wave": {
                "engine": "29.6.1 docker-desktop UP",
                "cvat": "2.24.0 localhost:8080",
                "nuclio_pth_sam2": "healthy",
                "ollama": "0.32.1",
            },
            "end_of_wave": {
                "engine": "DOWN (npipe dockerDesktopLinuxEngine missing)",
                "cvat": "unreachable (about_http=000)",
                "ollama_host": "0.32.1 UP",
                "cold_relaunch_attempted": True,
                "cold_relaunch_recovered_within_window": False,
                "prune_or_volume_wipe": False,
            },
            "c_free_gib_end": 30.21,
            "repair_floor_gib": 75,
            "below_repair_floor": True,
            "classification": "RUNTIME_BLOCKED",
        },
        "host_cuda": {
            "torch_version": "2.12.1+cpu",
            "cuda_available": False,
            "implication": (
                "Multi-provider segmentation tournament cannot mint real "
                "machine_verified_candidate sidecars on host CPU torch; "
                "requires Docker GPU train/serve container path when engine is healthy."
            ),
        },
        "production_runs_pool": {
            "runs_json_files": 4462,
            "parse_errors": 20,
            "machine_verified_candidate_count": 0,
            "calibrated_auto_accepted_count": 0,
            "lifecycle_sidecars_seen": 0,
            "top_status": [
                ["status=complete", 802],
                ["status=ingested", 123],
                ["status=quarantined", 36],
                ["status=failed", 19],
                ["status=needs_kevin_approval", 13],
                ["status=entry_gate_not_met", 11],
                ["status=ready", 1],
            ],
        },
        "admission": {
            "tool": "tools/build_autonomous_gold_admission.py",
            "evidence_path": "qa/live_verification/autonomous_gold_admission_20260720T1447.json",
            "status": admission.get("status"),
            "certificate_passed": admission.get("certificate_passed"),
            "machine_verified_candidate_count": admission["autonomous_verified_pool"][
                "machine_verified_candidate_count"
            ],
            "calibrated_auto_accepted_count": admission["autonomous_verified_pool"][
                "calibrated_auto_accepted_count"
            ],
            "self_sha256": admission.get("self_sha256"),
            "no_fabricated_samples": True,
            "certificate_minted": False,
        },
        "counts": {
            "machine_verified_candidate": 0,
            "calibrated_auto_accepted": 0,
            "autonomous_certified_gold": 0,
            "approved_gold": 0,
            "champions": 0,
            "audit_queue_population_count": 0,
        },
        "claims_established": [
            "f_drive_restored_and_readable",
            "gold_source_roots_present_maskedwarehouse_reference_daz",
            "data_junction_kept_on_c_backup_usb_auto_repoint_forbidden",
            "gpu_sequencer_run_now_for_sam2_and_ollama_sequential",
            "admission_driver_fail_closed_zero_candidates",
            "production_runs_pool_zero_machine_verified_candidate",
        ],
        "claims_not_established": [
            "machine_verified_candidate_minted",
            "autonomous_certified_gold_certificate",
            "champion_registered",
            "docker_engine_steady_state",
            "live_sam2_smoke_this_wave",
            "live_ollama_vlm_smoke_this_wave",
            "doctor_all_green",
            "production_evidence_pass",
        ],
        "next_agent_step": (
            "Recover Docker Desktop non-destructively once C: free >= 75 GiB "
            "(or after governed ephemeral reclaim); verify CVAT 2.24 + nuclio "
            "pth-sam2; sequence gpu_sequencer wait -> smoke_cvat_sam2 -> "
            "smoke_ollama_vlm; then run multi-provider tournament in "
            "maskfactory/train:cu128 on MaskedWarehouse/reference/DAZ to emit "
            "real machine_verified_candidate sidecars under runs/; re-run "
            "build_autonomous_gold_admission.py --corpus. Never fabricate."
        ),
        "claim_boundary": {
            "no_fabricated_samples": True,
            "no_tier_inflation": True,
            "no_champion_force_register": True,
            "demonstration_lifecycle_slice_is_not_production": True,
            "docker_crash_documented_not_hidden": True,
        },
    }
    _seal(evidence)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "path": str(OUT),
                "self_sha256": evidence["self_sha256"],
                "counts": evidence["counts"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
