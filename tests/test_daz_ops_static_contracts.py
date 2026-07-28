from __future__ import annotations

import pytest

from maskfactory.daz.ops_static_contracts import (
    BACKUP_CHECKS,
    FAILURE_CAMPAIGN_CHECKS,
    RECOVERY_CHECKS,
    SCHEDULER_CHECKS,
    STORAGE_CHECKS,
    DazOpsStaticError,
    refuse_daz_ops_overclaim,
    run_daz_ops_static_suite,
)
from maskfactory.validation import validate_document


def test_daz_ops_overclaim_fail_closed() -> None:
    with pytest.raises(DazOpsStaticError, match="mf_p9_12_07_soak_complete"):
        refuse_daz_ops_overclaim({"mf_p9_12_07_soak_complete": True})
    with pytest.raises(DazOpsStaticError, match="mf_p9_12_09_activation_complete"):
        refuse_daz_ops_overclaim({"mf_p9_12_09_activation_complete": True})
    with pytest.raises(DazOpsStaticError, match="live_daz_execution"):
        refuse_daz_ops_overclaim({"live_daz_execution": True})


def test_suite_seals_schema_valid_static_report() -> None:
    report = run_daz_ops_static_suite()
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["mf_p9_12_01_complete"] is False
    assert report["mf_p9_12_07_soak_complete"] is False
    assert report["mf_p9_12_09_activation_complete"] is False
    assert report["live_daz_execution"] is False
    assert report["seven_day_soak"] is False
    assert report["doctor_green_claimed"] is False
    assert report["gold_claimed"] is False
    assert report["main_complete_claimed"] is False
    assert report["production_evidence_pass_claimed"] is False
    assert set(report["backup_checks"]) == set(BACKUP_CHECKS)
    assert set(report["scheduler_checks"]) == set(SCHEDULER_CHECKS)
    assert set(report["storage_checks"]) == set(STORAGE_CHECKS)
    assert set(report["recovery_checks"]) == set(RECOVERY_CHECKS)
    assert set(report["failure_campaign_checks"]) == set(FAILURE_CAMPAIGN_CHECKS)
    assert all(report["backup_checks"].values())
    assert all(report["scheduler_checks"].values())
    assert all(report["storage_checks"].values())
    assert all(report["recovery_checks"].values())
    assert all(report["failure_campaign_checks"].values())
    assert report["bindings"]["reservation_bytes"] > 0
    assert report["bindings"]["soft_floor_gib"] > 0
    assert validate_document(report, "daz_ops_static_contracts_report") == ()
