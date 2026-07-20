"""Seal the isolated-consumer DoD-climb wave #2 evidence (deterministic self_sha256).

Producer-side, isolated-consumer-signed only. Does NOT claim real Comfy_UI_Main
adoption. HARD MF-P6-11.02/11.07/12.05/12.06 remain OPEN (AWAITING_MAIN). This wave
extends real-machinery DoD coverage for MF-P6-11.04 (receipt arbitration) and
MF-P6-11.08 (receipt-last recovery) via tools/run_isolated_main_consumer_dod2.py.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_EVIDENCE_NAME = "isolated_consumer_dod2_run_evidence_20260720T0928.json"
RUN_EVIDENCE = REPO_ROOT / "runtime_artifacts" / "main_consumer" / RUN_EVIDENCE_NAME
OUTPUT = REPO_ROOT / "qa" / "live_verification" / "isolated_consumer_dod_climb2_20260720.json"


def main() -> int:
    run = json.loads(RUN_EVIDENCE.read_text(encoding="utf-8"))
    summary = run["summary"]
    evidence = {
        "artifact_type": "isolated_main_consumer_dod_climb_wave",
        "authority": "autonomous_isolated_main_consumer_dod_climb_zero_human_wait",
        "branch": "codex/maskfactory-runtime-implementation",
        "producer_git_commit": run.get("producer_git_commit"),
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "champions": 0,
        "runner": "tools/run_isolated_main_consumer_dod2.py",
        "run_evidence": {
            "path": f"runtime_artifacts/main_consumer/{RUN_EVIDENCE_NAME}",
            "self_sha256": run["self_sha256"],
            "checks_total": len(run["checks"]),
            "checks_passed": sum(1 for c in run["checks"] if c["passed"]),
            "all_pass": all(c["passed"] for c in run["checks"]),
        },
        "new_dod_checks_this_wave": {
            "isolated_receipt_arbitration_dod_matrix": {
                "item": "MF-P6-11.04",
                "passed": summary.get("isolated_receipt_arbitration_dod_matrix"),
                "covers": [
                    "wrapper-certified Mode A dominates an uncertified Mode B draft (choose)",
                    "two same-scope certified alternatives branch deterministically",
                    "a third same-scope candidate forces deterministic abstain",
                    "Main selecting the stale cheap draft is refused as silent weakening",
                    "high preservation risk + insufficient authority floor abstains",
                    "real normalize_and_arbitrate_receipts + conformance validator",
                ],
            },
            "isolated_recovery_dod_matrix": {
                "item": "MF-P6-11.08",
                "passed": summary.get("isolated_recovery_dod_matrix"),
                "covers": [
                    "receipt-last full-chain commit is ready and validates",
                    "kill at all 15 durable boundaries recovers fail-closed without drift",
                    "receipt-before-artifacts ordering violation rejected",
                    "unresolved receipt digest fails closed",
                    "orphan promotion + authority drift rejected",
                    "foreign GPU-lease cleanup refused (no replacement-owner deletion)",
                    "duplicate resubmit after found-running (no not-found evidence) rejected",
                    "real build_recovery_evidence / simulate_kill_at_boundary + validator",
                ],
            },
        },
        "tier_note": (
            "STATIC_PASS producer + isolated-consumer evidence only. These matrices "
            "add real-machinery DoD surface for the producer boundary (MF-P6-11.04 / "
            "11.08); they do NOT advance AWAITING_MAIN, do NOT close any HARD blocker, "
            "and mint no certificate. is_real_comfyui_main=false."
        ),
        "hard_blockers_still_open": ["MF-P6-11.02", "MF-P6-11.07", "MF-P6-12.05", "MF-P6-12.06"],
        "claims_not_established": [
            "real_comfyui_main_adoption",
            "main_adoption_complete / MF-P6-12.06 core close",
            "champions>0",
            "PRODUCTION_EVIDENCE_PASS",
        ],
        "companion_waves": [
            "qa/live_verification/isolated_consumer_dod_climb_20260720T0810.json",
        ],
        "next_agent_step": (
            "Real receipts require a dedicated Comfy_UI_Main-side integration on an "
            "isolated clean maskfactory branch that consumes the producer adapter "
            "package and emits Main-signed adoption/qualification/adapter-execution/"
            "result-history artifacts pinned back here. Comfy_UI_Main is a dirty Wave64 "
            "tree (branch codex/workflow_plan_update_improvements) and was NOT touched."
        ),
        "self_sha256": "",
    }
    payload = json.dumps(
        {k: v for k, v in evidence.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT.name, evidence["self_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
