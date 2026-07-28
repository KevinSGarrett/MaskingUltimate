from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "env/sam3d_body_runtime_v4_warmup.lock.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v3_host_adapter_lock_binds_the_passing_repeatability_contract() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["artifact"] == "sam3d_body_v3_host_adapter_activation"
    assert lock["status"] == "runtime_pass_bounded_v3_host_adapter_static_contract_pending"
    assert lock["authority"] == {
        "lifecycle_state": "installed_unqualified",
        "may_author_gold": False,
        "may_promote_provider": False,
        "v1_provider_path_accepted": False,
    }
    runtime = lock["runtime"]
    runner = ROOT / runtime["runner"]
    repeatability_lock = ROOT / runtime["repeatability_runtime_lock"]
    assert _sha256(runner) == runtime["runner_sha256"]
    assert _sha256(repeatability_lock) == runtime["repeatability_runtime_lock_sha256"]
    receipt = lock["inherits"]["v3_runtime_receipt"]
    receipt_path = ROOT / receipt["path"]
    assert _sha256(receipt_path) == receipt["file_sha256"]
    assert receipt["self_sha256"] == "afe31a4a45f39791df6c7cda352d79acf103885a9221de700a69d01f9841c6ae"
    assert receipt["status"] == "RUNTIME_PASS_BOUNDED_V3_REQUALIFICATION_ONLY"
    assert runtime["contract"] == {
        "host_adapter_role": "shadow_only",
        "measured_repeats": 2,
        "non_evaluated_warmup_runs": 1,
        "numeric_tolerance_allowed": False,
        "raw_measured_npz_must_match": True,
        "source_root_import_injection_required": True,
    }
