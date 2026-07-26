from __future__ import annotations

import json

import pytest

from maskfactory.steward.core import canonical_sha256
from maskfactory.steward.interrupted_recovery_drill import (
    INTERRUPTED_RECOVERY_DRILL_SCHEMA,
    run_interrupted_recovery_drill,
)


def test_actual_child_interruption_reconstructs_without_resend(tmp_path) -> None:
    root = tmp_path / "actual-interrupted-recovery"

    result = run_interrupted_recovery_drill(root)

    assert result["schema_version"] == INTERRUPTED_RECOVERY_DRILL_SCHEMA
    assert result["status"] == "PASS"
    assert result["model_requests_issued"] == 0
    assert result["gpu_processes_started"] == 0
    assert all(result["acceptance_gates"].values())

    terminal = result["persisted_terminal_case"]
    assert terminal["actual_child_process_interrupted"] is True
    assert terminal["reconstruction_outcome"] == "reconciled_terminal_receipt"
    assert terminal["reconstructed_state"] == "completed"
    assert terminal["duplicate_admission_outcome"] == "reconciled_terminal"
    assert terminal["resend_blocked"] is True
    assert terminal["run_count_before_reconciliation_attempt"] == 2
    assert terminal["run_count_after_reconciliation_attempt"] == 2

    ambiguous = result["ambiguous_without_terminal_case"]
    assert ambiguous["actual_child_process_interrupted"] is True
    assert ambiguous["terminal_receipt_present"] is False
    assert ambiguous["reconstruction_outcome"] == "recovery_required"
    assert ambiguous["reconstructed_state"] == "recovery_required"
    assert ambiguous["resend_blocked"] is True
    assert ambiguous["run_count_before_resume_attempt"] == 1
    assert ambiguous["run_count_after_resume_attempt"] == 1

    persisted = json.loads(
        (root / "interrupted_recovery_result.json").read_text(encoding="utf-8")
    )
    declared = persisted.pop("result_sha256")
    assert canonical_sha256(persisted) == declared
    with pytest.raises(FileExistsError):
        run_interrupted_recovery_drill(root)


def test_relative_output_root_is_resolved_before_child_launch(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = run_interrupted_recovery_drill("relative-interrupted-recovery")

    assert result["status"] == "PASS"
    assert (tmp_path / "relative-interrupted-recovery" / "interrupted_recovery_result.json").is_file()
