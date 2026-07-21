"""Seal a brief note confirming disk repair DONE + serve/train/tournament
reprioritization of needs_agent_actions_20260720.json (deterministic self_sha256).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
QUEUE = REPO_ROOT / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
OUTPUT = REPO_ROOT / "qa" / "live_verification" / "disk_repair_done_reprioritize_20260720T0931.json"
HEAD_BEFORE_THIS_UPDATE = "139b4536"


def main() -> int:
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    evidence = {
        "artifact_type": "needs_agent_actions_reprioritization_brief",
        "authority": "agent_executable_action_queue_zero_human_wait_states",
        "at": "2026-07-20T14:31:00Z",
        "project_head_before_this_wave": HEAD_BEFORE_THIS_UPDATE,
        "host_snapshot": queue["host_snapshot"],
        "disk_repair": {
            "action_id": "disk_headroom_above_75_gib",
            "status": "DONE",
            "basis": (
                "C: free 91.71 GiB, above the 75 GiB repair/ingest floor "
                "(host_snapshot.c_above_75_repair_floor=true); Docker engine UP "
                "(32 running containers; production CVAT v2.24 + nuclio-pth-sam2 "
                "healthy; Ollama 0.32.1)."
            ),
        },
        "live_priorities_this_wave": [
            {"rank": p["rank"], "action_id": p["action_id"], "status": p["status"]}
            for p in queue["live_priorities_this_wave"]
        ],
        "note": (
            "Disk repair confirmed DONE; serve/train/tournament re-ranked to top-3 "
            "(1=serve cu128 build+containerized smoke, 2=train cu128 build+"
            "training-doctor, 3=multi-provider GPU tournament toward autonomous gold) "
            "per explicit instruction. No tier inflation: champions=0, gold=0 unchanged; "
            "this is a queue/priority update only, not a runtime or certification claim."
        ),
        "claims_not_established": [
            "PRODUCTION_EVIDENCE_PASS",
            "champions>0",
            "autonomous_certified_gold",
        ],
        "queue_source": {
            "path": "qa/live_verification/needs_agent_actions_20260720.json",
            "self_sha256": queue["self_sha256"],
        },
        "self_sha256": "",
    }
    payload = json.dumps(
        {k: v for k, v in evidence.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    OUTPUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT.name, evidence["self_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
