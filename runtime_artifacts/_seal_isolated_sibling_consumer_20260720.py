"""Seal the ISOLATED SIBLING Main-consumer wave evidence (deterministic self_sha256).

This wave was produced by a genuinely separate sibling repository/program at
C:\\Comfy_UI_Main_MaskFactory_Consumer (its own git history), which imports the
producer bridge contracts from this repo and executes the real adapter/journal/
circuit/qualification machinery plus a signed adoption attestation.

Authority ceiling (binding): authority_kind = isolated_main_consumer. This is NOT
fixture_authority and NOT the real Comfy_UI_Main runtime. It does NOT claim real
Main adoption and does NOT close HARD blockers MF-P6-11.02/11.07/12.05/12.06.
The dirty C:\\Comfy_UI_Main Wave64 tree was NOT touched.
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
    / "isolated_sibling_consumer_run_evidence_20260720T1451.json"
)
OUTPUT = (
    REPO_ROOT / "qa" / "live_verification" / "isolated_sibling_consumer_climb_20260720T1451.json"
)

CONSUMER_REPO = r"C:\Comfy_UI_Main_MaskFactory_Consumer"
CONSUMER_GIT_HEAD = "5ecb9bd0a39c0cc4ae91bf3d31ea80594c084171"


def main() -> int:
    run = json.loads(RUN_EVIDENCE.read_text(encoding="utf-8"))
    checks = run["checks"]
    evidence = {
        "artifact_type": "isolated_sibling_main_consumer_climb_wave",
        "authority": "autonomous_isolated_sibling_main_consumer_zero_human_wait",
        "authority_kind": "isolated_main_consumer",
        "is_real_comfyui_main": False,
        "main_adoption_complete": False,
        "champions": 0,
        "producer_git_commit": run.get("producer_git_commit"),
        "producer_branch": "codex/maskfactory-runtime-implementation",
        "consumer_repo": CONSUMER_REPO,
        "consumer_git_head": CONSUMER_GIT_HEAD,
        "consumer_is_separate_repo": True,
        "runner": "run_consumer.py (mf_main_consumer.runner) in the sibling consumer repo",
        "run_evidence": {
            "path": "runtime_artifacts/main_consumer/isolated_sibling_consumer_run_evidence_20260720T1451.json",
            "self_sha256": run["self_sha256"],
            "checks_total": len(checks),
            "checks_passed": sum(1 for c in checks if c["passed"]),
            "all_pass": all(c["passed"] for c in checks),
            "summary": run["summary"],
        },
        "pillars_this_wave": {
            "isolated_adapter_conformance": {
                "item": "MF-P6-11.01",
                "passed": run["summary"].get("isolated_adapter_conformance"),
                "covers": [
                    "external MaskFactoryAdapter boundary living OUTSIDE the producer tree",
                    "adapter imports verified by AST to be contracts-only (maskfactory.contracts)",
                    "real sdist package_sha256 + real git commit/tree identity",
                    "producer conformance verifier ACCEPTS (no node-id/mutable-path/internal coupling)",
                ],
            },
            "isolated_signed_journal": {
                "item": "MF-P6-11.06",
                "passed": run["summary"].get("isolated_signed_journal"),
                "covers": [
                    "trusted-signed append-only journal + signed checkpoint",
                    "closed history validation returns no issues",
                    "same-key/same-body replay is idempotent (no new entry)",
                ],
            },
            "isolated_failure_control_circuit": {
                "item": "MF-P6-11.07",
                "passed": run["summary"].get("isolated_failure_control_circuit"),
                "covers": [
                    "outage/timeout/oom/incompatible-authority all refuse provider invocation",
                    "exact scoped-DAG blocking (dependent passes only)",
                    "no-silent-fallback enforced; no fallback artifact",
                    "exhausted retry budget refuses another retry",
                ],
            },
            "isolated_cross_project_producer_partial": {
                "item": "MF-P6-12.05",
                "passed": run["summary"].get("isolated_cross_project_producer_partial"),
                "covers": [
                    "real cross-project qualification matrix execution",
                    "honest producer_partial ceiling",
                    "mf_p6_12_05_complete=false, establishes_production_qualification=false",
                ],
            },
            "isolated_adoption_attestation_signed": {
                "item": "MF-P6-11/12 adoption",
                "passed": run["summary"].get("isolated_adoption_attestation_signed"),
                "covers": [
                    "real Ed25519 signature over a canonical-json-sealed attestation",
                    "key_id 'isolated-main-consumer-adoption' (deliberately NOT comfy-main-*)",
                    "verified cryptographically in-process",
                ],
            },
        },
        "tier_note": (
            "STATIC_PASS isolated-consumer evidence produced by a SEPARATE sibling repo. "
            "It deepens the real-machinery DoD surface for the Main-side consumer boundary "
            "from outside the producer tree; it does NOT advance AWAITING_MAIN to real Main "
            "adoption, does NOT close any HARD blocker, and mints no certificate. "
            "is_real_comfyui_main=false."
        ),
        "hard_blockers_still_open": ["MF-P6-11.02", "MF-P6-11.07", "MF-P6-12.05", "MF-P6-12.06"],
        "claims_not_established": [
            "real_comfyui_main_adoption",
            "main_adoption_complete / MF-P6-12.06 core close",
            "champions>0",
            "PRODUCTION_EVIDENCE_PASS",
        ],
        "next_agent_step": (
            "Real HARD-close receipts require the actual Comfy_UI_Main runtime to consume this "
            "sibling adapter package and emit comfy-main-* trust-key-signed adoption/qualification/"
            "adapter-execution/result-history artifacts pinned back here. Comfy_UI_Main is a dirty "
            "Wave64 tree and was NOT touched."
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
