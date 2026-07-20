"""Append OPS_LOG entry for isolated-consumer climb4 (MF-P6-11.02 / 11.07)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OPS = REPO / "Plan" / "OPS_LOG.md"
SEAL = REPO / "qa" / "live_verification" / "isolated_consumer_climb4_20260720T1506.json"
MARKER = "Isolated-consumer climb4 (MF-P6-11.02 / 11.07 STATIC_PASS depth)"


def main() -> int:
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    text = OPS.read_text(encoding="utf-8")
    if MARKER in text:
        print("OPS_LOG already has climb4 entry; skip")
        return 0
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    entry = f"""
## {ts} UTC - {MARKER}

**Item:** MF-P6-11.02, MF-P6-11.07 (HARD remain OPEN)
**Command:** `python tools/run_isolated_main_consumer_climb4.py --output runtime_artifacts/main_consumer/isolated_consumer_climb4_run_evidence_20260720T1504.json`; sibling `C:/Comfy_UI_Main_MaskFactory_Consumer` `python run_consumer.py`; `python runtime_artifacts/_seal_isolated_consumer_climb4_20260720.py`; tracker set 11.02 86->88 / 11.07 82->84 (blocked)

**Result:** STATIC_PASS deepened. New durable runner `tools/run_isolated_main_consumer_climb4.py` (standalone under multi-agent churn): Mode A matrix **30/30 PASS** (prior climb3 claimed 23); failure-control flags all true (healthy-admit, open/half-open, silent-fallback refuse, scoped-DAG over/under, incoherent-retry reject, deadline/resource/retry-budget). Sibling consumer HEAD `9b61c866` adds Mode A pillar + deepened circuit -> **6/6 pillars PASS** (`self_sha256` b5c03c1d…). Seal `qa/live_verification/isolated_consumer_climb4_20260720T1506.json` (`self_sha256` {seal["self_sha256"]}). Honest scope: producer + isolated-consumer only; `is_real_comfyui_main=false`; HARD MF-P6-11.02/11.07/12.05/12.06 remain OPEN (AWAITING_MAIN). Dirty Wave64 `C:/Comfy_UI_Main` untouched. champions=0; no core close.

Evidence:
- runtime_artifacts/main_consumer/isolated_consumer_climb4_run_evidence_20260720T1504.json
- runtime_artifacts/main_consumer/isolated_sibling_consumer_run_evidence_20260720T1506.json
- qa/live_verification/isolated_consumer_climb4_20260720T1506.json
"""
    OPS.write_text(text.rstrip() + "\n" + entry + "\n", encoding="utf-8")
    print("appended OPS_LOG climb4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
