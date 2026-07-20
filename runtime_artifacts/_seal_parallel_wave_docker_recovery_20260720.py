"""Seal the 2026-07-20 parallel-wave live re-probe (docs-only stream, honest, no tier inflation).

Independent live probe taken while multiple sibling agents hold concurrent uncommitted/committed
source edits in this shared working tree. This stream touches evidence/docs surfaces only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "parallel_wave_docker_recovery_reprobe_20260720T0806.json"

evidence = {
    "artifact_type": "parallel_wave_docker_recovery_reprobe",
    "schema_version": "1.0.0",
    "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "local_date": "2026-07-20",
    "branch": "codex/maskfactory-runtime-implementation",
    "project_head_at_authoring": "184313d1",
    "lane": "docs-only tracker/handoff refresh for the current multi-agent parallel wave; no source edits by this stream",
    "authority": "zero_human_wait_states_live_reprobe",
    "docker_engine": {
        "status": "RECOVERED_STABILIZING",
        "prior_state": "RUNTIME_BLOCKED (qa/live_verification/runtime_climb_disk_safe_20260720T0720.json)",
        "containers_observed_via_bounded_docker_ps": {
            "count": 36,
            "uptime_minutes_approx": "3-4",
            "key_services": [
                "cvat_server (Up ~3m)",
                "cvat_db / cvat_redis_ondisk (healthy)",
                "nuclio (Up ~3m, healthy)",
                "nuclio-nuclio-pth-sam2 (Up ~4m, healthy)",
                "cvat269_* rehearsal stack also up",
            ],
        },
        "flap_evidence": [
            "Bounded `docker info --format ...` CLI call hung >90s and had to be killed (pid 32728); a second bounded `docker ps` via PowerShell job (15s timeout) succeeded.",
            "First `GET http://localhost:8080/api/server/about` probe returned 502 Bad Gateway; retry ~1 minute later returned 200.",
            "Two independent SAM2 (nuclio pth-sam2) smokes bracket the blip and both PASS: qa/reports/cvat_sam2_smoke.json measured_at 2026-07-20T08:00:05Z latency 54.461s, and a fresh tools/smoke_cvat_sam2.py run this probe -> pass, latency 48.103s.",
        ],
        "classification": "RUNTIME_PASS_BOUNDED_with_residual_gateway_flap",
        "not_steady_state_pass": True,
        "no_prune_no_wipe": True,
    },
    "disk": {
        "c_free_gib_live": 47.4502906799316,
        "measured_via": "(Get-Volume -DriveLetter C).SizeRemaining / 1GB",
        "prior_wave_c_free_gib": 29.15,
        "f_free_gib_prior_wave": 249.42,
        "docker_data_vhdx_gib_on_c": 68.11,
        "note": "C: headroom improved since the prior RUNTIME_BLOCKED wave (29.15 -> ~47.45 GiB); still below the 75 GiB floor cited by that wave's repair guidance, but sufficient for the daemon to complete this recovery.",
    },
    "visual_qa": {
        "external_certifiable_subset": "VISUAL_QA_PASS_BOUNDED (15 named panels: 5 CelebAMask-HQ face + 5 LaPa face + 5 LV-MHP body; zero blocking defects; agent pixel-review verdict, not gold, human CVAT not required)",
        "machine_draft_corpus": "STAYS VISUAL_QA_REVIEWED_WITH_DEFECTS (data/packages, 14 instances; structural defects need human CVAT)",
        "source_masks_are_gold": False,
        "evidence": "qa/live_verification/visual_qa_certifiable_subset_climb_20260720.json",
        "scope_boundary": "PASS_BOUNDED applies ONLY to the external certifiable subset, not to the machine package corpus and not a project-wide visual-QA claim.",
    },
    "gold_and_champions": {
        "approved_gold_packages": 0,
        "autonomous_certified_gold_packages": 0,
        "human_anchor_gold_packages": 0,
        "champions_count": 0,
        "audit_queue_population_count": 0,
        "autonomy_lifecycle_sidecars_in_runs": 0,
        "mode_b_predict_status": "AWAITING_RUNTIME",
        "evidence": "qa/live_verification/measured_path_autonomous_gold_wiring_20260720T0745.json",
    },
    "main_adoption": {
        "status": "AWAITING_MAIN",
        "hard_blockers_still_open": ["MF-P6-11.02", "MF-P6-11.07", "MF-P6-12.05", "MF-P6-12.06"],
        "isolated_consumer_evidence": "runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T021815.json (6/6 checks PASS; NOT real Comfy_UI_Main; main_adoption_complete=false)",
        "real_main_repo_untouched": True,
    },
    "parallel_execution_context": {
        "note": "Multiple sibling agent streams hold concurrent staged/unstaged source edits (docker/, tools/gpu_sequencer.py, tests/test_gpu_sequencer.py, tools/build_autonomous_gold_admission.py, Plan/GPU_SEQUENCING_AND_VRAM_BUDGET.md, etc.) in this same shared working tree, and HEAD moved during this probe (92a463ce -> cff18735 -> 184313d1, same underlying change, sibling-authored). This stream committed ONLY its own tracker/handoff/needs-agent-actions/seal docs and left all sibling in-flight edits unstaged and untouched.",
        "head_observed_start_of_stream": "92a463ce",
        "head_observed_at_authoring": "184313d1",
    },
    "honesty": [
        "No tier inflation: champions=0; no approved/autonomous/human-anchor gold; no doctor-green; no PRODUCTION_EVIDENCE_PASS.",
        "Docker recovery is real (live docker ps + two independent SAM2 smoke PASS) but residual CLI/gateway flap is disclosed, not hidden.",
        "VISUAL_QA_PASS_BOUNDED is scoped to the 15-panel external certifiable subset only; the machine draft corpus explicitly stays VISUAL_QA_REVIEWED_WITH_DEFECTS.",
        "Main HARD blockers MF-P6-11.02/11.07/12.05/12.06 remain OPEN; isolated consumer is not real Comfy_UI_Main.",
    ],
    "claims_not_established": [
        "docker_engine_steady_state_green",
        "doctor_all_green",
        "autonomous_certified_gold",
        "human_approved_gold",
        "champions>0",
        "VISUAL_QA_PASS_BOUNDED (project-wide / machine corpus)",
        "Main-complete / MF-P6-12.06",
        "PRODUCTION_EVIDENCE_PASS",
    ],
    "no_open_human_stop_states": True,
}

payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("SEALED", OUT.name, evidence["self_sha256"][:16])
