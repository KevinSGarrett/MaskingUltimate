"""Seal the isolated-consumer DoD-climb wave #3 evidence (deterministic self_sha256).

Focus: HARD MF-P6-11.02 (immutable Mode A package read) and MF-P6-11.07 (failure
controller) real-machinery matrices deepened beyond prior seals in
tools/run_isolated_main_consumer.py.

Producer-side, isolated-consumer-signed only. Does NOT claim real Comfy_UI_Main
adoption. HARD MF-P6-11.02/11.07/12.05/12.06 remain OPEN (AWAITING_MAIN).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_EVIDENCE = (
    REPO_ROOT
    / "runtime_artifacts"
    / "main_consumer"
    / "isolated_consumer_run_evidence_20260720T094526.json"
)
OUTPUT = REPO_ROOT / "qa" / "live_verification" / "isolated_consumer_dod_climb3_20260720T0945.json"


def main() -> int:
    run = json.loads(RUN_EVIDENCE.read_text(encoding="utf-8"))
    summary = run["summary"]
    checks = {c["check"]: c for c in run["checks"]}
    mode_a = checks.get("isolated_mode_a_package_read_matrix", {})
    failure = checks.get("isolated_failure_control_circuit", {})
    mode_a_cases = [c.get("case") for c in mode_a.get("cases", [])]

    evidence = {
        "artifact_type": "isolated_main_consumer_dod_climb_wave",
        "authority": "autonomous_isolated_main_consumer_dod_climb_zero_human_wait",
        "branch": "codex/maskfactory-runtime-implementation",
        "producer_git_commit": run.get("producer_git_commit"),
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "champions": 0,
        "runner": "tools/run_isolated_main_consumer.py",
        "run_evidence": {
            "path": "runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T094526.json",
            "self_sha256": run["self_sha256"],
            "checks_total": len(run["checks"]),
            "checks_passed": sum(1 for c in run["checks"] if c["passed"]),
            "all_pass": all(c["passed"] for c in run["checks"]),
        },
        "deepened_matrices_this_wave": {
            "isolated_mode_a_package_read_matrix": {
                "item": "MF-P6-11.02",
                "passed": summary.get("isolated_mode_a_package_read_matrix"),
                "baseline_certified": mode_a.get("baseline_certified"),
                "case_count": len(mode_a_cases),
                "prior_case_count": 8,
                "cases": mode_a_cases,
                "covers": [
                    "valid wrapper-certified single-person read accepts at certified authority",
                    "non-production QA read without wrapper accepts but is capped at "
                    "qa_passed_noncertified and is never production-eligible",
                    "raw-status escalation, claimed-certified-without-wrapper refused",
                    "path escape, source/mask/manifest/package hash drift refused",
                    "ontology/instance/character-revision mismatch, wrong owner refused",
                    "stale/missing/revoked/out-of-scope exact wrapper refused",
                    "catalog-not-adopted, rejected raw part status refused",
                    "unsigned/non-current revocation head, transform drift refused",
                    "derived-artifact parent-authority escalation refused",
                    "mutation/write attempt refused; no write path ever exposed",
                ],
            },
            "isolated_failure_control_circuit": {
                "item": "MF-P6-11.07",
                "passed": summary.get("isolated_failure_control_circuit"),
                "covers": [
                    "outage/timeout/oom/incompatible-authority fault refuses provider "
                    "invocation with EXACT scoped-DAG blocking (dependent passes only)",
                    "healthy admission (closed circuit, feasible, within deadline) PERMITS "
                    "provider invocation (not a trivial always-refuse)",
                    "open circuit blocks route with no mask substitution",
                    "half-open without authorized probe blocks; with probe permits one trial",
                    "silent-fallback artifact (empty/weaker mask) refused outright",
                    "scoped-DAG overreach and underreach both rejected",
                    "incoherent Main retry evidence (retry for non-transient authority "
                    "fault) rejected",
                    "deadline expiry, infeasible resource envelope, exhausted bounded "
                    "retry budget all refuse provider invocation",
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
            "STATIC_PASS producer + isolated-consumer real-execution evidence only. This "
            "wave deepens the immutable Mode A package-read matrix from 8 to "
            f"{len(mode_a_cases)} adversarial cases and adds 7 new failure-controller "
            "checks (healthy-admit positive baseline, open/half-open circuit gating, "
            "silent-fallback refusal, scoped-DAG over/under-reach, incoherent-retry "
            "rejection). It does NOT advance AWAITING_MAIN, does NOT close any HARD "
            "blocker, and mints no certificate. is_real_comfyui_main=false."
        ),
        "hard_blockers_still_open": ["MF-P6-11.02", "MF-P6-11.07", "MF-P6-12.05", "MF-P6-12.06"],
        "claims_not_established": [
            "real_comfyui_main_adoption",
            "main_adoption_complete / MF-P6-12.06 core close",
            "champions>0",
            "PRODUCTION_EVIDENCE_PASS",
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
