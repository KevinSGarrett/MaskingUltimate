from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1_LOCK = ROOT / "env/sam3d_body_runtime.lock.json"
V2_LOCK = ROOT / "env/sam3d_body_repeatability_v2_runtime.lock.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v2_requalification_lock_preserves_v1_and_binds_its_new_runner() -> None:
    lock = json.loads(V2_LOCK.read_text(encoding="utf-8"))
    assert lock["artifact"] == "sam3d_body_repeatability_requalification_v2"
    assert lock["status"] == "prepared_unexecuted_strict_warmup_capture_requalification"
    assert lock["inherits"]["v1_runtime_lock_sha256"] == _sha256(V1_LOCK)
    assert lock["inherits"]["v1_runner_sha256"] == _sha256(ROOT / lock["inherits"]["v1_runner"])
    assert lock["runtime"]["runner_sha256"] == _sha256(ROOT / lock["runtime"]["runner"])


def test_v2_requalification_lock_keeps_the_strict_non_promoting_contract() -> None:
    lock = json.loads(V2_LOCK.read_text(encoding="utf-8"))
    contract = lock["runtime"]["contract"]
    assert contract["non_evaluated_warmup_runs"] == 1
    assert contract["measured_repeats"] == 2
    assert contract["numeric_tolerance_allowed"] is False
    assert contract["source_runtime_checkpoint_must_match_v1"] is True
    assert "persist both raw NPZ" in contract["measured_output_retention"]
    assert lock["authority"]["may_author_gold"] is False
    assert lock["authority"]["may_promote_provider"] is False
    assert lock["authority"]["v1_result_modified"] is False
