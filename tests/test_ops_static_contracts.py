from __future__ import annotations

import pytest

from maskfactory.ops_static_contracts import (
    BACKUP_RESTORE_CHECKS,
    FAILURE_MINING_OPS_CHECKS,
    NIGHTLY_REINDEX_CHECKS,
    OpsStaticContractError,
    evaluate_nightly_backup_script_contract,
    refuse_ops_overclaim,
    resolve_failure_record_ops_static,
    run_ops_static_contract_suite,
)
from maskfactory.qa.failure_mining import FailureRecord
from maskfactory.validation import validate_document


def test_nightly_backup_script_orders_b5_before_b1_and_verify_sample() -> None:
    checks = evaluate_nightly_backup_script_contract()
    assert checks["nightly_b5_before_b1_ordering"] is True
    assert checks["nightly_verify_package_sample_wired"] is True
    assert checks["nightly_verify_package_after_b5_b1"] is True


def test_resolved_failure_requires_resolution_pkg_version() -> None:
    record = FailureRecord(
        ts="2026-07-19T18:00:00Z",
        image_id="img_0a5fa1100001",
        failed_body_part="left_forearm",
        failure_reason="boundary_bleed_clothing",
        pose_angle="front",
        model_that_failed="fixture",
        correction_needed="reannotate_boundary",
        priority=0.5,
    )
    with pytest.raises(OpsStaticContractError, match="resolved_requires_resolution_pkg_version"):
        resolve_failure_record_ops_static(record, resolution_pkg_version=None, mark_resolved=True)
    resolved = resolve_failure_record_ops_static(
        record,
        resolution_pkg_version="fixture_packages@ops_static_v1",
        mark_resolved=True,
    )
    assert resolved.resolved is True
    assert resolved.resolution_pkg_version == "fixture_packages@ops_static_v1"


def test_ops_overclaim_fail_closed() -> None:
    with pytest.raises(OpsStaticContractError, match="mf_p1_09_05_complete"):
        refuse_ops_overclaim({"mf_p1_09_05_complete": True})
    with pytest.raises(OpsStaticContractError, match="mf_p7_03_06_d10_signed"):
        refuse_ops_overclaim({"mf_p7_03_06_d10_signed": True})
    with pytest.raises(OpsStaticContractError, match="b1_mirror_present"):
        refuse_ops_overclaim({"b1_mirror_present": True})


def test_suite_seals_schema_valid_static_report() -> None:
    report = run_ops_static_contract_suite()
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["mf_p1_09_05_complete"] is False
    assert report["mf_p7_03_01_complete"] is False
    assert report["mf_p7_03_03_complete"] is False
    assert report["mf_p7_03_06_d10_signed"] is False
    assert report["b1_mirror_present"] is False
    assert report["b2_media_present"] is False
    assert report["human_anchor_package_present"] is False
    assert report["d10_signed"] is False
    assert report["kevin_b1_b2_restore_required"] is True
    assert report["kevin_d10_signoff_required"] is True
    assert set(report["backup_restore_checks"]) == set(BACKUP_RESTORE_CHECKS)
    assert set(report["nightly_reindex_verify_checks"]) == set(NIGHTLY_REINDEX_CHECKS)
    assert set(report["failure_mining_ops_checks"]) == set(FAILURE_MINING_OPS_CHECKS)
    assert all(report["backup_restore_checks"].values())
    assert all(report["nightly_reindex_verify_checks"].values())
    assert all(report["failure_mining_ops_checks"].values())
    assert validate_document(report, "ops_static_contracts_report") == ()
