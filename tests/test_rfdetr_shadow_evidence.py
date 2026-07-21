from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "qa" / "live_verification" / "rfdetr_yolo11_shadow_comparison_20260714.json"


def _canonical_sha256(document: dict) -> str:
    payload = {key: value for key, value in document.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_live_rfdetr_shadow_comparison_and_rollback_are_hash_bound() -> None:
    document = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    comparison = document["comparison"]
    rollback = document["role_switch_rollback"]

    assert document["sha256"] == _canonical_sha256(document)
    assert document["result"] == "pass"
    assert document["authority"] == "shadow_comparison_only_no_promotion_authority"
    assert document["promotion_claimed"] is False
    assert comparison["incumbent_count"] == comparison["challenger_count"] == 4
    assert comparison["matched_count"] == 4
    assert comparison["incumbent_recall"] == comparison["challenger_recall"] == 1.0
    assert comparison["mean_matched_iou"] > 0.95
    assert rollback == {
        "challenger_lifecycle": "installed",
        "configured_active": "yolo11m_person",
        "configured_rollback": "yolo11m_person",
        "incumbent_replay_exact": True,
        "incumbent_replay_output_sha256": document["incumbent"]["output_sha256"],
        "rejection": (
            "person_detector.active provider 'rf_detr_medium' "
            "lifecycle_state='installed'; active roles require promoted"
        ),
        "selection_unchanged": True,
        "unpromoted_switch_rejected": True,
    }
