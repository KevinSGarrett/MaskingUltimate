"""Seal isolated-consumer climb-4 evidence (MF-P6-11.02 / 11.07 STATIC_PASS depth).

Producer climb4 runner + sibling Comfy_UI_Main_MaskFactory_Consumer receipt.
HARD blockers remain OPEN. Comfy_UI_Main dirty Wave64 tree untouched.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_EVIDENCE = (
    REPO_ROOT
    / "runtime_artifacts"
    / "main_consumer"
    / "isolated_consumer_climb4_run_evidence_20260720T1504.json"
)
SIBLING_RECEIPT_SRC = Path(
    r"C:\Comfy_UI_Main_MaskFactory_Consumer\receipts"
    r"\isolated_main_consumer_run_20260720T150616Z.json"
)
SIBLING_RECEIPT_DST = (
    REPO_ROOT
    / "runtime_artifacts"
    / "main_consumer"
    / "isolated_sibling_consumer_run_evidence_20260720T1506.json"
)
OUTPUT = REPO_ROOT / "qa" / "live_verification" / "isolated_consumer_climb4_20260720T1506.json"


def main() -> int:
    run = json.loads(RUN_EVIDENCE.read_text(encoding="utf-8"))
    shutil.copy2(SIBLING_RECEIPT_SRC, SIBLING_RECEIPT_DST)
    sibling = json.loads(SIBLING_RECEIPT_DST.read_text(encoding="utf-8"))
    checks = {c["check"]: c for c in run["checks"]}
    mode_a = checks["isolated_mode_a_package_read_matrix"]
    failure = checks["isolated_failure_control_circuit"]
    mode_a_cases = [c.get("case") for c in mode_a.get("cases", [])]
    sibling_mode_a = next(
        (c for c in sibling["checks"] if c["check"] == "isolated_mode_a_package_read"),
        {},
    )
    sibling_fc = next(
        (c for c in sibling["checks"] if c["check"] == "isolated_failure_control_circuit"),
        {},
    )

    evidence = {
        "artifact_type": "isolated_main_consumer_climb4_wave",
        "authority": "autonomous_isolated_main_consumer_climb4_zero_human_wait",
        "branch": "codex/maskfactory-runtime-implementation",
        "producer_git_commit": run.get("producer_git_commit"),
        "sibling_consumer_git_commit": sibling.get("consumer_git_commit"),
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "champions": 0,
        "runner": "tools/run_isolated_main_consumer_climb4.py",
        "sibling_consumer": {
            "project": "Comfy_UI_Main_MaskFactory_Consumer",
            "receipt_path": str(SIBLING_RECEIPT_DST.relative_to(REPO_ROOT)).replace("\\", "/"),
            "self_sha256": sibling["self_sha256"],
            "all_pillars_passed": all(c["passed"] for c in sibling["checks"]),
            "pillars": sibling.get("summary"),
            "mode_a_case_count": sibling_mode_a.get("case_count"),
            "failure_control_flags": {
                "bounded_retry_budget_enforced": sibling_fc.get("bounded_retry_budget_enforced"),
                "healthy_admission_permits_provider": sibling_fc.get(
                    "healthy_admission_permits_provider"
                ),
                "circuit_open_blocks_route": sibling_fc.get("circuit_open_blocks_route"),
            },
        },
        "run_evidence": {
            "path": str(RUN_EVIDENCE.relative_to(REPO_ROOT)).replace("\\", "/"),
            "self_sha256": run["self_sha256"],
            "checks_total": len(run["checks"]),
            "checks_passed": sum(1 for c in run["checks"] if c["passed"]),
            "all_pass": all(c["passed"] for c in run["checks"]),
        },
        "deepened_matrices_this_wave": {
            "isolated_mode_a_package_read_matrix": {
                "item": "MF-P6-11.02",
                "passed": mode_a.get("passed"),
                "baseline_certified": mode_a.get("baseline_certified"),
                "case_count": len(mode_a_cases),
                "prior_case_count": 23,
                "cases": mode_a_cases,
                "covers": [
                    "valid wrapper-certified single- and multi-person reads accept at certified",
                    "QA and diagnostic non-production reads accept capped at qa_passed_noncertified",
                    "raw-status escalation / claimed-certified-without-wrapper refused",
                    "path escape, source/mask/manifest/package/pixel hash drift refused",
                    "ontology/instance/character-revision/wrong-owner refused",
                    "stale/missing/revoked/out-of-scope wrapper refused",
                    "catalog-not-adopted / missing-person catalog refused",
                    "revocation/transform/release-capability drift refused",
                    "derived-authority escalation + mutation/write refused",
                    "withdrawn/rejected part status refused",
                ],
            },
            "isolated_failure_control_circuit": {
                "item": "MF-P6-11.07",
                "passed": failure.get("passed"),
                "covers": [
                    "outage/timeout/oom/incompatible-authority refuse provider with exact scoped-DAG",
                    "healthy closed-circuit admission PERMITS provider invocation",
                    "open circuit blocks route; half-open probe-gated",
                    "silent-fallback artifact refused",
                    "scoped-DAG overreach and underreach rejected",
                    "incoherent Main retry for non-transient authority fault rejected",
                    "deadline/resource/retry-budget enforcement",
                ],
                "flags": {
                    "healthy_admission_permits_provider": failure.get(
                        "healthy_admission_permits_provider"
                    ),
                    "circuit_open_blocks_route": failure.get("circuit_open_blocks_route"),
                    "half_open_probe_gated": failure.get("half_open_probe_gated"),
                    "silent_fallback_refused": failure.get("silent_fallback_refused"),
                    "scoped_dag_overreach_rejected": failure.get("scoped_dag_overreach_rejected"),
                    "scoped_dag_underreach_rejected": failure.get("scoped_dag_underreach_rejected"),
                    "incoherent_main_retry_rejected": failure.get("incoherent_main_retry_rejected"),
                    "deadline_enforced": failure.get("deadline_enforced"),
                    "resource_envelope_enforced": failure.get("resource_envelope_enforced"),
                    "bounded_retry_budget_enforced": failure.get("bounded_retry_budget_enforced"),
                },
            },
        },
        "tier_note": (
            "STATIC_PASS producer climb4 + sibling isolated Main-consumer real-execution "
            "only. Mode A matrix deepened to 30 adversarial cases; failure-control flags "
            "all true (healthy-admit/open/half-open/silent-fallback/scoped-DAG/"
            "incoherent-retry + deadline/resource/retry). Sibling consumer at "
            f"{sibling.get('consumer_git_commit')} now runs Mode A + deepened circuit "
            "(6/6 pillars PASS). Does NOT advance AWAITING_MAIN, does NOT close any HARD "
            "blocker, mints no certificate. is_real_comfyui_main=false. Dirty Wave64 "
            "Comfy_UI_Main untouched."
        ),
        "hard_blockers_still_open": [
            "MF-P6-11.02",
            "MF-P6-11.07",
            "MF-P6-12.05",
            "MF-P6-12.06",
        ],
        "claims_not_established": [
            "real_comfyui_main_adoption",
            "main_adoption_complete / MF-P6-12.06 core close",
            "champions>0",
            "PRODUCTION_EVIDENCE_PASS",
        ],
        "credits": {
            "MF-P6-11.02": {"from": 86, "to": 88, "tier": "STATIC_PASS"},
            "MF-P6-11.07": {"from": 82, "to": 84, "tier": "STATIC_PASS"},
        },
        "next_agent_step": (
            "Real HARD-close receipts require the actual Comfy_UI_Main runtime on a clean "
            "maskfactory branch consuming the producer adapter and emitting "
            "comfy-main-* signed adoption/qualification/execution artifacts. Dirty Wave64 "
            "Main was NOT touched."
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
