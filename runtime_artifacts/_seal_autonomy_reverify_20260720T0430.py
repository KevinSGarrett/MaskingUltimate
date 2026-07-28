"""Seal the 2026-07-20 autonomous re-verification wave (champions + Main workstreams).

Honest, sealed live re-verification at HEAD c378499b. This wave executed the
Workstream A (champions / Mode B predict) and Workstream B (real Main adoption)
mandate as far as is honestly possible without fabrication or tier inflation,
and precisely root-caused the remaining hard gates.

NO fabrication: champions stay 0; no gold; no Main receipts invented; DAZ not
killed (live user GUI session); no tier inflated to complete/runtime/visual/gold.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa" / "live_verification" / "autonomy_reverify_20260720T0430.json"

HEAD = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
BRANCH = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

doc = {
    "artifact_type": "autonomy_reverification_wave",
    "schema_version": "1.0.0",
    "recorded_at": recorded_at,
    "local_date": "2026-07-19",
    "branch": BRANCH,
    "project_head_at_authoring": HEAD,
    "authority": [
        "Plan/RESTART_HANDOFF_AUTONOMOUS_20260719.md",
        "qa/live_verification/needs_agent_actions_20260719.json",
        "Plan/DOCKER_RUNTIME_AND_SESSION_USE.md",
        "Kevin mandate: FULL AUTONOMY, zero human wait, proof tiers binding, never force-register champions, never inflate fixture/STATIC.",
    ],
    "live_probe": {
        "docker_server": "29.4.3 (context docker-desktop)",
        "cvat_about": "http://localhost:8080/api/server/about -> 2.24.0 (production)",
        "cvat269": "rehearsal stack up (isolated; not production-bridged)",
        "ollama_version": "http://127.0.0.1:11434/api/version -> 0.32.1 (native process)",
        "nuclio_pth_sam2": "healthy",
        "gpu": "RTX 5060 Laptop; 8151 MiB total; ~2182 MiB free; resident: DAZStudio.exe pid52340 + python pid10912 + Cursor",
        "wsl_ubuntu_2204": "Stopped/corrupt; `wsl -d Ubuntu-22.04 -- /bin/true` -> distribution failed to start Error code 6 step 2 E_FAIL (ext4 VHD corruption)",
        "is_administrator": False,
        "host_python_torch": "2.12.1+cpu (NO CUDA)",
        "training_doctor": "ready=false; cuda_available=false; mmengine/mmcv/mmseg/mmdet MISSING; mmcv._ext unavailable; datasets not registered",
        "mode_b_serve_host": "cannot start: 'FastAPI serving dependencies are missing; install the pinned MaskFactory environment' -> full serve/train runtime lives in WSL (down)",
    },
    "workstream_a_champions": {
        "champions": 0,
        "force_register": "FORBIDDEN by policy -- not performed",
        "gold_corpus_probe": "data/packages: 28 manifests; approved_gold=0; human_anchor_gold=0; autonomous_certified_gold=0 (all truth_tier=None)",
        "audit_queue_root_cause": (
            "autonomy build-audit-queue counts ONLY lifecycle sidecars whose status == "
            "operations.calibrated_status ('calibrated_auto_accepted'). There are 0. The 1648 "
            "JSON files under work/instances are instance manifests (status complete/ready/"
            "residual_human_queue/none), NOT autonomy lifecycle sidecars. population_count=0 is "
            "therefore a DOWNSTREAM SYMPTOM of an empty calibration lifecycle, not a code bug in "
            "build_weekly_audit_queue."
        ),
        "calibration_gate": (
            "build_autonomy_certificate requires a FROZEN, image-disjoint human-anchor-gold audit "
            "corpus (audit_authority in {human_anchor_gold, human_approved_gold_only}), each row "
            "bound to an immutable approved_gold package part (status human_approved_gold / "
            "human_anchor_gold). Policy floors: minimum_audits_per_risk_bucket=30 AND one-sided "
            "Wilson false_accept_upper_bound <= 0.01 (=> ~>=270 zero-defect audits) AND exact "
            "zero-failure serious bound <= 0.005. With 0 human-anchor gold packages the certificate "
            "can never pass. Fabricating human audits or bypassing the human-anchor authority is "
            "FORBIDDEN (tier inflation)."
        ),
        "training_gate": (
            "Champion promotion via measured shadow tournament needs a registered training candidate "
            "from a sealed MMSeg run. Host torch is 2.12.1+cpu with no MMSeg/MMCV/CUDA; the CUDA "
            "training runtime lives in WSL Ubuntu-22.04 which is corrupt (ext4 VHD, E_FAIL) and its "
            "e2fsck repair needs elevation (IsAdmin=False this shell). There is also 0 gold training "
            "data volume. No measured D6/D7 holdout win is possible now."
        ),
        "vram_action": (
            "Did NOT kill DAZ Studio (pid52340): it is a live interactive user GUI session with "
            "possible unsaved work -- killing it is destructive and out of safe scope. Freeing VRAM "
            "is also MOOT for a training/cert window because the training AND serve runtimes are "
            "unavailable on the host regardless of VRAM (host CPU-only; WSL down). ~2182 MiB free."
        ),
        "mode_b_predict_status": "AWAITING_RUNTIME (champions=0 AND host serve deps missing). Re-probe of /predict is not applicable until an honest champion>0 exists.",
        "legitimate_next_measured_path": [
            "Elevated shell: tools/Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair (e2fsck) to restore the WSL CUDA train/serve runtime, OR build a Docker GPU train/serve container (torch cu128 + mmcv/mmseg ops).",
            "Establish a governed autonomous-gold admission tier OR real human-anchor gold audit corpus (>=270 zero-defect audits) -- a policy/data task, not fabricable.",
            "Drive draft->repair to VISUAL_QA_PASS_BOUNDED on a certifiable subset -> autonomy calibration produces calibrated_auto_accepted masks -> build-audit-queue non-empty -> process-audits -> build-certificate -> autonomous-certify-package -> P5 training -> measured shadow win -> promote champion -> re-probe Mode B /predict.",
        ],
    },
    "workstream_b_main_adoption": {
        "producer_bridge_tests": "PASS at HEAD c378499b (test_bridge_journal/external_adapter_conformance/mode_a_package_read/mode_b_localhost_client/receipt_arbitration_conformance/feedback_intake/failure_control/recovery/autonomy_registration/cross_project_qualification/main_consumer_conformance/producer_fixture_main_e2e/consumer_invalidation/consumer_requirements/fixture_main).",
        "cross_project_qualification_producer": "status=producer_partial; producer_matrix_executable=true; mf_p6_12_05_complete=false; establishes_production_qualification=false (default synthetic observation only; NOT real Main).",
        "external_main_dependencies_required": [
            "pinned_main_runtime_git_commit",
            "main_adoption_receipt",
            "main_qualification_bundle_signature",
            "main_adapter_execution_receipt",
            "comfyui_result_history_receipt",
        ],
        "main_repo_state": (
            "C:/Comfy_UI_Main HEAD b36001b9 on branch codex/workflow_plan_update_improvements is a "
            "SEPARATE, unrelated active project (Wave64 autonomous audio/video) with a dirty working "
            "tree of in-flight audio-defect work. A filename scan found NO MaskFactory consumer "
            "surface (no maskfactory/bridge/adoption/qualification files)."
        ),
        "action_taken": (
            "Did NOT fabricate Main receipts and did NOT commit into Main's active dirty branch. Real "
            "MF-P6-11.02/11.07/12.05 receipts require a dedicated cross-repo Main integration that "
            "consumes the producer MaskFactoryAdapter package and emits signed Main-side "
            "adoption/journal/circuit/execution/qualification artifacts on an isolated Main branch. "
            "Producer side is verified Main-ready; the consumer build is the honest remaining task."
        ),
        "hard_blockers_open": ["MF-P6-11.02", "MF-P6-11.07", "MF-P6-12.05", "MF-P6-12.06"],
    },
    "claims_not_established": [
        "doctor_all_green",
        "VISUAL_QA_PASS_BOUNDED",
        "champions>0",
        "Mode B champion-backed predict/refine RUNTIME_PASS_BOUNDED",
        "human_approved_gold / autonomous_certified_gold",
        "Main adoption receipts / MF-P6-11.02 / 11.07 / 12.05 / 12.06",
        "core_autonomous_runtime complete",
        "PRODUCTION_EVIDENCE_PASS",
    ],
    "no_open_human_stop_states": True,
}

body = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
self_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
doc["self_sha256"] = self_sha
OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"evidence={OUT.relative_to(ROOT).as_posix()}")
print(f"self_sha256={self_sha}")
print(f"head={HEAD}")
