"""Refresh needs_agent_actions with the 2026-07-20 honest re-verification, recompute self_sha256."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa" / "live_verification" / "needs_agent_actions_20260719.json"

HEAD = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

doc = json.loads(OUT.read_text(encoding="utf-8"))
doc.pop("self_sha256", None)
doc["recorded_at"] = recorded_at
doc["project_head_at_authoring"] = HEAD
doc["latest_reverification"] = {
    "recorded_at": recorded_at,
    "head": HEAD,
    "evidence": "qa/live_verification/autonomy_reverify_20260720T0430.json",
    "champions": 0,
    "mode_b_predict": "AWAITING_RUNTIME (champions=0 + host FastAPI serve deps missing; serve/train runtime=WSL down)",
    "audit_queue_root_cause": "population_count=0 is downstream of an empty calibration lifecycle (0 calibrated_auto_accepted sidecars). Requires human-anchor-gold certificate (~>=270 zero-defect audits); data/packages has 0 approved_gold/human_anchor_gold. Not a code bug; not fabricable.",
    "training_runtime": "host torch 2.12.1+cpu; training-doctor ready=false; WSL Ubuntu-22.04 corrupt (E_FAIL); IsAdmin=False -> e2fsck elevation-gated. Docker GPU CUDA container is the agent-executable substitute path.",
    "vram_action": "DAZ NOT killed (live user GUI session; destructive). VRAM freeing moot: train/serve runtimes unavailable on host regardless.",
    "main_adoption": "Producer bridge + cross-project PASS at HEAD; run_cross_project_qualification=producer_partial. Main C:/Comfy_UI_Main HEAD b36001b9 = separate unrelated active project (Wave64), dirty tree, NO MaskFactory consumer surface. Real receipts require isolated Main-side consumer build; not fabricated.",
}
for claim in (
    "autonomous_certified_gold",
    "Main adoption receipts (MF-P6-11.02/11.07/12.05)",
):
    if claim not in doc["claims_not_established"]:
        doc["claims_not_established"].append(claim)

body = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
self_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
doc["self_sha256"] = self_sha
OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"queue={OUT.relative_to(ROOT).as_posix()}")
print(f"self_sha256={self_sha}")
print(f"head={HEAD}")
