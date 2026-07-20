"""Restore MVC demoted solely for source_image_unresolved (index gap, not VLM fail)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from maskfactory.validation import validate_document  # noqa: E402


def main() -> int:
    seal = REPO / "qa/live_verification/tournament_mvc_visual_hard_qa_delta_20260720T121501.json"
    doc = json.loads(seal.read_text(encoding="utf-8"))
    restored = 0
    skipped = 0
    for row in doc.get("rows") or []:
        if row.get("blocker") != "source_image_unresolved":
            skipped += 1
            continue
        rel = row.get("lifecycle_path")
        if not isinstance(rel, str):
            skipped += 1
            continue
        path = REPO / rel
        if not path.is_file():
            skipped += 1
            continue
        life = json.loads(path.read_text(encoding="utf-8"))
        if life.get("status") != "residual_human_queue":
            skipped += 1
            continue
        if "source unresolved" not in str(life.get("reason") or ""):
            skipped += 1
            continue
        life["status"] = "machine_verified_candidate"
        life["truth_tier"] = "machine_candidate"
        life["training_loss_weight"] = 0.0
        life["serve_eligible"] = False
        life["pseudo_train_eligible"] = False
        life["authoritative_human_gold"] = False
        life["certificate_valid"] = False
        life["certificate_reason"] = "restored_after_source_index_gap"
        life["reason"] = "restored_for_visual_hard_qa_retry_after_source_index_fix"
        life["human_audit_required"] = False
        issues = validate_document(life, "autonomy_lifecycle")
        if issues:
            print(json.dumps({"path": rel, "invalid": issues}))
            skipped += 1
            continue
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(life, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
        restored += 1
    print(json.dumps({"restored": restored, "skipped": skipped}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
