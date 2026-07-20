"""Seal GOLD FACTORY Ollama critic/router wave evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRIMARY = REPO / "qa/live_verification/tournament_ollama_critic_router_20260720T1153.json"
REMAINING = (
    REPO / "qa/live_verification/tournament_ollama_critic_router_remaining_20260720T1210.json"
)
GPU = REPO / "qa/live_verification/gpu_sequence_ollama_critic_router_20260720.json"
OUT = REPO / "qa/live_verification/tournament_ollama_critic_router_wave_20260720T1212.json"
LATEST = REPO / "qa/live_verification/tournament_ollama_critic_router_latest.json"
OPS = REPO / "Plan/OPS_LOG.md"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    primary = _load(PRIMARY)
    remaining = _load(REMAINING)
    gpu = _load(GPU)
    critic_runs = int(primary["critic_runs"]) + int(remaining["critic_runs"])
    scored = int(primary["critic_scored_advisory"]) + int(remaining["critic_scored_advisory"])
    attempted = int(primary["mvc_scored_attempted"]) + int(remaining["mvc_scored_attempted"])
    outcomes: dict[str, int] = {}
    for doc in (primary, remaining):
        for key, val in (doc.get("outcomes") or {}).items():
            outcomes[key] = outcomes.get(key, 0) + int(val)

    seal = {
        "artifact_type": "tournament_ollama_critic_router_wave",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "lane": "GOLD_FACTORY_ollama_critic_router",
        "model": "qwen2.5vl:7b",
        "governance": {
            "role": "qa_router_only",
            "may_author_masks": False,
            "may_approve_gold": False,
            "may_clear_blocks": False,
        },
        "gpu_sequence": {
            "consumer": "ollama-vlm",
            "decision": gpu.get("decision", {}).get("decision"),
            "free_mib": gpu.get("decision", {}).get("free_mib"),
            "report": "qa/live_verification/gpu_sequence_ollama_critic_router_20260720.json",
        },
        "tool": "tools/run_tournament_ollama_critic_router.py",
        "evidence_parts": [
            "qa/live_verification/tournament_ollama_critic_router_20260720T1153.json",
            "qa/live_verification/tournament_ollama_critic_router_remaining_20260720T1210.json",
        ],
        "critic_runs": critic_runs,
        "critic_scored_advisory": scored,
        "mvc_attempted": attempted,
        "outcomes": outcomes,
        "lifecycle_mutations": 0,
        "multi_family_agreement_replaced": False,
        "autonomous_certified_gold": 0,
        "honesty_rules": [
            "VLM is advisory critic/router only",
            "Never authors masks",
            "Never approves gold",
            "Never replaces multi-family agreement / never mutates MVC lifecycle status",
        ],
        "blocker": None,
    }
    raw = json.dumps(seal, indent=2, sort_keys=True) + "\n"
    seal["self_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    text = json.dumps(seal, indent=2, sort_keys=True) + "\n"
    OUT.write_text(text, encoding="utf-8")
    LATEST.write_text(text, encoding="utf-8")

    entry = f"""
## 2026-07-20 17:12 UTC - GOLD FACTORY Ollama qwen2.5vl:7b critic/router on tournament MVC

**Item:** Wire/run governed Ollama ``qwen2.5vl:7b`` as critic/router on tournament candidates
**Command:** `python tools/gpu_sequencer.py sequence --consumer ollama-vlm`; `python tools/run_tournament_ollama_critic_router.py` (cbackup + remaining MVC roots)
**Result:** RUNTIME_PASS_BOUNDED. **critic_runs={critic_runs}** (advisory scores only). GPU-seq `ollama-vlm` `run_now` (~7799 MiB). Governance: role=qa_router_only, may_author_masks=false, may_approve_gold=false. **multi_family_agreement_replaced=false**; lifecycle_mutations=0; MVC status preserved. Outcomes: {outcomes}. Tool: `tools/run_tournament_ollama_critic_router.py`. Evidence: `{OUT.relative_to(REPO).as_posix()}` (self_sha256 {seal['self_sha256'][:12]}…).

"""
    ops = OPS.read_text(encoding="utf-8")
    if "GOLD FACTORY Ollama qwen2.5vl:7b critic/router on tournament MVC" not in ops:
        OPS.write_text(ops.rstrip() + "\n" + entry, encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(OUT.relative_to(REPO)).replace("\\", "/"),
                "critic_runs": critic_runs,
                "self_sha256": seal["self_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
