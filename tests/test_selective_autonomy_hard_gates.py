from __future__ import annotations

import pytest

from maskfactory.selective_autonomy_hard_gates import (
    CROSS_INSTANCE_BLEED_QC_IDS,
    FORMAT_INTEGRITY_QC_IDS,
    ZERO_TOLERANCE,
    SelectiveAutonomyHardGateError,
    build_selective_autonomy_hard_gates_report,
)


def test_hard_gates_report_binds_zero_tolerance_and_existing_qc_ids() -> None:
    report = build_selective_autonomy_hard_gates_report(
        seeded_violation_blocks={
            "format_integrity": True,
            "cross_instance_bleed": True,
            "left_right_swap": True,
        }
    )
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["zero_tolerance"] == ZERO_TOLERANCE
    assert report["bound_qc_ids"]["format_integrity"] == list(FORMAT_INTEGRITY_QC_IDS)
    assert report["bound_qc_ids"]["cross_instance_bleed"] == list(CROSS_INSTANCE_BLEED_QC_IDS)
    assert report["any_seeded_or_audited_violation_blocks_or_revokes"] is True
    assert report["production_audit_complete"] is False
    assert report["doctor_green_claimed"] is False
    assert report["gold_claimed"] is False
    assert report["production_evidence_pass_claimed"] is False
    assert report["seal_sha256"]
    assert report["report_id"].startswith("sahg_")


def test_missing_or_unblocked_seeded_families_fail_closed() -> None:
    with pytest.raises(SelectiveAutonomyHardGateError, match="incomplete"):
        build_selective_autonomy_hard_gates_report(
            seeded_violation_blocks={"format_integrity": True, "cross_instance_bleed": True}
        )
    with pytest.raises(SelectiveAutonomyHardGateError, match="not_blocked"):
        build_selective_autonomy_hard_gates_report(
            seeded_violation_blocks={
                "format_integrity": True,
                "cross_instance_bleed": False,
                "left_right_swap": True,
            }
        )
