"""Seal the P6-11/12 isolated-main-consumer producer evidence climb.

Honest ceiling: this records the deepened producer + isolated-consumer real
execution coverage for the HARD Main-adoption items. It does NOT claim real
Comfy_UI_Main adoption; every HARD blocker stays open.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RECEIPT = (
    REPO_ROOT
    / "runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T023043.json"
)
OUTPUT = REPO_ROOT / "qa/live_verification/p6_11_12_isolated_consumer_climb_20260720T0231.json"


def _git_head() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return out.stdout.strip().lower()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    doc = {
        "artifact_type": "p6_11_12_isolated_consumer_climb",
        "schema_version": "1.0.0",
        "recorded_at": "2026-07-20T07:33:00Z",
        "local_date": "2026-07-20",
        "branch": "codex/maskfactory-runtime-implementation",
        "project_head_at_authoring": _git_head(),
        "authority": [
            "Kevin mandate: FULL AUTONOMY, zero human wait, proof tiers binding; "
            "advance HARD Main-adoption items via isolated Main consumer only; "
            "do NOT touch dirty Wave64 branch on C:/Comfy_UI_Main.",
            "qa/live_verification/autonomy_reverify_20260720T0430.json",
        ],
        "main_repo_guard": {
            "path": "C:/Comfy_UI_Main",
            "branch": "codex/workflow_plan_update_improvements",
            "head": "c579b3e492b059dc98140d7af6ea9650e8bac9d7",
            "dirty_file_count": 394,
            "decision": (
                "Separate unrelated active Wave64 project with a dirty tree and NO "
                "MaskFactory consumer surface. No clean maskfactory consumer branch "
                "was created there (tree not clean). Not touched, not committed into."
            ),
        },
        "isolated_consumer_receipt": {
            "path": "runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T023043.json",
            "self_sha256": receipt["self_sha256"],
            "file_sha256": _sha256_file(RECEIPT),
            "authority_kind": receipt["authority_kind"],
            "is_real_comfyui_main": receipt["is_real_comfyui_main"],
            "summary": receipt["summary"],
        },
        "producer_isolated_coverage_advanced": {
            "MF-P6-11.02": {
                "check": "isolated_mode_a_package_read_matrix",
                "tier": "STATIC_PASS (producer real-execution)",
                "detail": (
                    "Real evaluate_mode_a_package_read matrix: valid wrapper-certified "
                    "read accepts at certified authority; raw-status escalation, path "
                    "escape, same-size mask hash drift, stale wrapper, out-of-scope "
                    "wrapper, wrong owner, and mutation/write attempts all fail closed "
                    "with typed reasons, production_eligible=false, no write path."
                ),
            },
            "MF-P6-11.07": {
                "check": "isolated_failure_control_circuit",
                "tier": "STATIC_PASS (producer real-execution)",
                "detail": (
                    "outage/timeout/oom/incompatible_authority fault injection: provider "
                    "invocation refused, exact scoped-DAG blocking (pass_predict+pass_refine "
                    "blocked, pass_unrelated continues), deadline + resource-envelope "
                    "enforcement, bounded retry-budget exhaustion, no silent fallback."
                ),
            },
            "MF-P6-12.05": {
                "check": "isolated_cross_project_producer_partial",
                "tier": "STATIC_PASS (producer_partial matrix)",
                "detail": (
                    "run_cross_project_qualification -> producer_partial; all matrix rows "
                    "pass; mf_p6_12_05_complete=false; establishes_production_qualification=false."
                ),
            },
            "MF-P6-12.06": {
                "check": "isolated_final_release_handoff_firewall",
                "tier": "STATIC_PASS (producer core-close firewall)",
                "detail": (
                    "evaluate_final_release_handoff with no Main adoption -> incomplete_core "
                    "with core_close_refused_without_exact_gates and close_authorized=false; "
                    "a fabricated core-complete claim -> rejected. No profile closed."
                ),
            },
        },
        "hard_blockers_still_open": receipt["claim_boundary"]["hard_blockers_still_open"],
        "claims_not_established": [
            "real Comfy_UI_Main adoption / installed runtime identities",
            "Main-signed adoption/qualification/adapter-execution/result-history receipts",
            "MF-P6-11.02 / 11.07 / 12.05 / 12.06 completion",
            "core_autonomous_runtime complete",
            "PRODUCTION_EVIDENCE_PASS",
        ],
        "honest_ceiling": (
            "Advances are producer + isolated-consumer real execution only. They deepen "
            "DoD verify-clause coverage but CANNOT and DO NOT close any HARD blocker; those "
            "require a real Comfy_UI_Main-side consumer that emits Main-signed receipts."
        ),
        "no_open_human_stop_states": True,
    }
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    doc["self_sha256"] = hashlib.sha256(payload).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"sealed {OUTPUT.name} self_sha256={doc['self_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
