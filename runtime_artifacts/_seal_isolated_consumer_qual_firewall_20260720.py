"""Seal the isolated-consumer qualification + firewall depth wave (deterministic self_sha256).

Producer-side, isolated-consumer-signed only. Does NOT claim real Comfy_UI_Main
adoption. HARD MF-P6-11.02/11.07/12.05/12.06 remain OPEN (AWAITING_MAIN). This wave
DEEPENS real-machinery adversarial coverage for MF-P6-12.05 (cross-project
qualification) and MF-P6-12.06 (final-release firewall) via
tools/run_isolated_main_consumer_qual_firewall.py.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_EVIDENCE_NAME = "isolated_consumer_qual_firewall_run_evidence_20260720T0934.json"
RUN_EVIDENCE = REPO_ROOT / "runtime_artifacts" / "main_consumer" / RUN_EVIDENCE_NAME
OUTPUT = (
    REPO_ROOT / "qa" / "live_verification" / "isolated_consumer_qual_firewall_climb_20260720.json"
)


def main() -> int:
    run = json.loads(RUN_EVIDENCE.read_text(encoding="utf-8"))
    summary = run["summary"]
    by_check = {c["check"]: c for c in run["checks"]}
    evidence = {
        "artifact_type": "isolated_main_consumer_qual_firewall_climb_wave",
        "authority": "autonomous_isolated_main_consumer_qual_firewall_climb_zero_human_wait",
        "branch": "codex/maskfactory-runtime-implementation",
        "producer_git_commit": run.get("producer_git_commit"),
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "champions": 0,
        "runner": "tools/run_isolated_main_consumer_qual_firewall.py",
        "run_evidence": {
            "path": f"runtime_artifacts/main_consumer/{RUN_EVIDENCE_NAME}",
            "self_sha256": run["self_sha256"],
            "checks_total": len(run["checks"]),
            "checks_passed": sum(1 for c in run["checks"] if c["passed"]),
            "all_pass": all(c["passed"] for c in run["checks"]),
        },
        "new_depth_checks_this_wave": {
            "isolated_cross_project_qualification_depth_matrix": {
                "item": "MF-P6-12.05",
                "passed": summary.get("isolated_cross_project_qualification_depth_matrix"),
                "baseline_decision_sha256": by_check.get(
                    "isolated_cross_project_qualification_depth_matrix", {}
                ).get("baseline_decision_sha256"),
                "covers": [
                    "honest producer_partial baseline (all matrix rows pass, no overclaim)",
                    "fabricated Main receipt -> rejected (not fabricated pass)",
                    "fixture evidence claimed as production -> rejected",
                    "failed currency-review relabelled pass -> rejected",
                    "tampered decision_sha256 -> decision_hash_drift detected",
                    "forged mf_p6_12_05_complete claim -> completion_overclaim detected",
                    "dropped matrix row -> matrix_row_set_drift detected",
                    "pinned Main commit ALONE -> still producer_partial, no production qualification",
                    "real build/validate_cross_project_qualification_evidence",
                ],
            },
            "isolated_final_release_firewall_depth_matrix": {
                "item": "MF-P6-12.06",
                "passed": summary.get("isolated_final_release_firewall_depth_matrix"),
                "honest_decision_sha256": by_check.get(
                    "isolated_final_release_firewall_depth_matrix", {}
                ).get("honest_decision_sha256"),
                "covers": [
                    "no Main adoption -> incomplete_core, core close refused",
                    "fabricated core-complete claim -> rejected",
                    "fixture-only release -> published-release gate refused",
                    "fixture-authority adoption receipt -> cannot close core",
                    "adoption not pinning exact release id/hash -> refused",
                    "optional profiles independent; cannot revoke/force core",
                    "tampered decision_sha256 -> decision_hash_drift detected",
                    "dropped close gate -> gate_set_drift detected",
                    "real evaluate/validate_final_release_handoff",
                ],
            },
        },
        "tier_note": (
            "STATIC_PASS producer + isolated-consumer evidence only. These matrices "
            "DEEPEN real-machinery adversarial DoD surface for the producer boundary "
            "(MF-P6-12.05 / 12.06); they do NOT advance AWAITING_MAIN, do NOT close any "
            "HARD blocker, authorize NO core close, and mint no certificate. "
            "is_real_comfyui_main=false."
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
            "qa/live_verification/isolated_consumer_dod_climb2_20260720.json",
        ],
        "next_agent_step": (
            "Real receipts require a dedicated Comfy_UI_Main-side integration on an "
            "isolated clean maskfactory branch that consumes the producer adapter "
            "package and emits Main-signed adoption/qualification/adapter-execution/"
            "result-history artifacts pinned back here. Comfy_UI_Main is a dirty Wave64 "
            "tree and was NOT touched."
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
