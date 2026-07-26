from __future__ import annotations

import json

import pytest

from maskfactory.steward.core import canonical_sha256
from maskfactory.steward.recovery_drill import (
    RECOVERY_DRILL_SCHEMA,
    run_recovery_drill,
)


def test_real_recovery_drill_reconstructs_and_blocks_resend(tmp_path) -> None:
    root = tmp_path / "recovery-drill"

    result = run_recovery_drill(root)

    assert result["schema_version"] == RECOVERY_DRILL_SCHEMA
    assert result["status"] == "PASS"
    assert all(result["acceptance_gates"].values())
    assert result["stale_pid"]["mismatch_treated_as_dead"] is True
    terminal = result["persisted_terminal_case"]
    assert terminal["reconstruction_outcome"] == "reconciled_terminal_receipt"
    assert terminal["reconstructed_state"] == "completed"
    assert terminal["duplicate_admission_outcome"] == "reconciled_terminal"
    assert terminal["resend_blocked"] is True
    assert terminal["run_count_after_restart"] == 2
    assert terminal["handoff_ready"] is True
    ambiguous = result["ambiguous_without_terminal_case"]
    assert ambiguous["reconstruction_outcome"] == "recovery_required"
    assert ambiguous["reconstructed_state"] == "recovery_required"
    assert ambiguous["resend_blocked"] is True
    assert ambiguous["run_count_after_restart"] == 1
    assert ambiguous["handoff_ready"] is False

    persisted = json.loads(
        (root / "recovery_drill_result.json").read_text(encoding="utf-8")
    )
    declared = persisted.pop("result_sha256")
    assert canonical_sha256(persisted) == declared
    with pytest.raises(FileExistsError):
        run_recovery_drill(root)
