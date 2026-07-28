"""Seal the 2026-07-20 tracker/evidence-hygiene sweep and refresh needs_agent_actions.

Honest, proof-tier-binding. This sweep ADVANCES NOTHING on weak proof: it only
records that the unfinished-item sweep against EXISTING sealed evidence
(STATIC_PASS / RUNTIME_PASS_BOUNDED already on disk) yielded zero legitimate
status transitions, because prior parallel waves already reflected every sealed
surface and every remaining unfinished item is gated on live/GPU/WSL/human-CVAT/
Main-adoption/DAZ-Studio/gold evidence that is not present on disk.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa" / "live_verification"
SWEEP_OUT = QA / "tracker_evidence_hygiene_sweep_20260720.json"
QUEUE_OUT = QA / "needs_agent_actions_20260719.json"

HEAD = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seal(doc: dict, out: Path) -> str:
    doc.pop("self_sha256", None)
    body = json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    doc["self_sha256"] = digest
    out.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return digest


sweep = {
    "artifact_type": "tracker_evidence_hygiene_sweep",
    "schema_version": "1.0.0",
    "recorded_at": recorded_at,
    "local_date": "2026-07-20",
    "branch": "codex/maskfactory-runtime-implementation",
    "project_head_at_authoring": HEAD,
    "stream": "tracker_and_evidence_hygiene_only",
    "authority": "Plan/Instructions/02_AUTONOMOUS_OPERATING_RULES.md §3 honesty, §11 proof tiers",
    "multi_agent_parallel_execution": {
        "observed": True,
        "sibling_agents_seen": [
            "sibling_agent_c50abb3a (Docker Desktop restart after serve-image build crash)",
            "uncommitted sibling edits in working tree: docker/Dockerfile.train, docker/compose.gpu.yml, tools/run_isolated_main_consumer.py",
        ],
        "coordination_rule": "This stream committed ONLY its own tracker-report/handoff/OPS_LOG/seal files; sibling in-flight source edits were left unstaged and untouched.",
    },
    "method": [
        "python tracker.py list --status open,in_progress,partially_complete,failed -> 135 items",
        "python tracker.py list (blocked) -> 98 items; 233 total unresolved of 798",
        "grep qa/live_verification for every currently-open item id -> no sealed STATIC_PASS/RUNTIME_PASS_BOUNDED evidence exists for any open item",
        "cross-checked residual_blocker_inventory_20260719.json (any_item_completed_by_this_inventory=false; all unfinished items classified NEEDS_KEVIN_* / LIVE_GPU_WSL / AWAITING_MAIN / LIVE_DAZ / champion)",
        "python tracker.py validate -> 798 items, 0 structural problems, 19 hard-blockers unresolved",
        "python tracker.py report -> DASHBOARD.md + phases/*.md regenerated (markdown resynced to sibling tracker.json notes)",
    ],
    "result": {
        "unresolved_items_scanned": 233,
        "open_in_progress_partial_failed": 135,
        "blocked": 98,
        "status_transitions_applied": 0,
        "reason_zero": "Every remaining unfinished item is gated on live/GPU/WSL/human-CVAT/Main-adoption/DAZ-Studio/gold evidence NOT present on disk. All 291 sealed STATIC_PASS/RUNTIME_PASS_BOUNDED artifacts were already fully reflected in tracker state by prior parallel waves; no un-applied sealed evidence remained.",
    },
    "portfolio_snapshot": {
        "portfolio_progress": "565/798 items (70.8%)",
        "core_autonomous_runtime": "blocked",
        "independent_real_accuracy": "blocked",
        "scale_daz_maturity": "waiting_for_prerequisite",
    },
    "honesty": [
        "No tier inflation: STATIC binders add STATIC_PASS surfaces only; they do not advance AWAITING_MAIN or champions.",
        "No item marked complete/not_applicable on weak proof; zero transitions is the honest outcome.",
        "core_autonomous_runtime remains blocked: champions=0, certified_training_package_count=0, P6-11/12 AWAITING_MAIN (HARD MF-P6-11.02/11.07/12.05).",
    ],
    "claims_not_established": [
        "core_autonomous_runtime complete",
        "doctor_all_green",
        "autonomous_certified_gold",
        "VISUAL_QA_PASS_BOUNDED",
        "PRODUCTION_EVIDENCE_PASS",
        "any new item completion",
    ],
    "tracker_mutations": "none (tracker.py report regeneration only; no set/metrics/goal state change)",
}

sweep_sha = seal(sweep, SWEEP_OUT)

queue = json.loads(QUEUE_OUT.read_text(encoding="utf-8"))
queue.pop("self_sha256", None)
queue["recorded_at"] = recorded_at
queue["project_head_at_authoring"] = HEAD
queue["parallel_execution_reconcile"] = {
    "recorded_at": recorded_at,
    "head": HEAD,
    "stream": "tracker_and_evidence_hygiene_only",
    "evidence_hygiene_sweep": "qa/live_verification/tracker_evidence_hygiene_sweep_20260720.json",
    "status_transitions_applied": 0,
    "note": "Multi-agent parallel execution active (sibling source edits in working tree left untouched). Evidence-hygiene sweep confirmed the tracker already reflects all sealed STATIC_PASS/RUNTIME_PASS_BOUNDED evidence; 0 unfinished items could honestly advance on existing sealed proof. Report regenerated; validate PASS (798 items, 0 structural problems).",
}
queue_body = json.dumps(queue, indent=2, ensure_ascii=False) + "\n"
queue["self_sha256"] = hashlib.sha256(queue_body.encode("utf-8")).hexdigest()
QUEUE_OUT.write_text(json.dumps(queue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print(f"sweep={SWEEP_OUT.relative_to(ROOT).as_posix()}")
print(f"sweep_self_sha256={sweep_sha}")
print(f"queue={QUEUE_OUT.relative_to(ROOT).as_posix()}")
print(f"queue_self_sha256={queue['self_sha256']}")
print(f"head={HEAD}")
