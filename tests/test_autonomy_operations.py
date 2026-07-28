import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maskfactory.autonomy.calibration import load_autonomy_config
from maskfactory.autonomy.operations import run_serious_failure_drill


def test_serious_failure_drill_revokes_scope_and_emits_retraining_task(tmp_path: Path):
    config = load_autonomy_config()
    now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
    report = run_serious_failure_drill(
        tmp_path,
        operations_policy=config["operations"],
        retraining_policy=config["retraining"],
        now=now,
    )
    root = tmp_path / report["drill_id"]
    assert report["passed"] is True
    assert report["serving_and_certified_training_eligibility_removed"] is True
    assert report["retraining_requested"] is True
    assert report["serious_failure_count"] == config["retraining"]["minimum_audit_failures"]
    assert (
        report["sha256"]
        == hashlib.sha256(
            json.dumps(
                {key: value for key, value in report.items() if key != "sha256"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    assert json.loads((root / "retraining_task.json").read_text())["status"] == "open"
    assert json.loads(next((root / "revocations").glob("*.json")).read_text())["reasons"] == [
        "serious_false_accept"
    ]
    with pytest.raises(ValueError, match="immutable and already exists"):
        run_serious_failure_drill(
            tmp_path,
            operations_policy=config["operations"],
            retraining_policy=config["retraining"],
            now=now,
        )
