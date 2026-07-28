from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "env/sam3d_body_repeatability_v3_runtime.lock.json"
V2_STARTUP_RECEIPT = ROOT / (
    "runtime_artifacts/sam3d_body_repeatability_v2_requalification_20260725T150338Z/"
    "V2_STARTUP_FAILURE_RECEIPT.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(
    not V2_STARTUP_RECEIPT.is_file(),
    reason="external SAM 3D Body V2 startup receipt is not present",
)
def test_v3_lock_binds_the_new_runner_and_preserves_v2_startup_evidence() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    assert lock["artifact"] == "sam3d_body_repeatability_requalification_v3"
    assert lock["runtime"]["runner_sha256"] == _sha256(ROOT / lock["runtime"]["runner"])
    assert lock["inherits"]["v2_runner_sha256"] == _sha256(ROOT / lock["inherits"]["v2_runner"])
    receipt = ROOT / lock["inherits"]["v2_startup_failure_receipt"]
    assert lock["inherits"]["v2_startup_failure_receipt_sha256"] == _sha256(receipt)


def test_v3_lock_keeps_the_strict_non_promoting_contract() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    contract = lock["runtime"]["contract"]
    assert contract["source_root_import_injection"].startswith("add exact --source-root")
    assert contract["non_evaluated_warmup_runs"] == 1
    assert contract["measured_repeats"] == 2
    assert contract["numeric_tolerance_allowed"] is False
    assert lock["authority"]["may_author_gold"] is False
    assert lock["authority"]["may_promote_provider"] is False
