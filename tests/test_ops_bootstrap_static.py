from __future__ import annotations

import pytest

from maskfactory.ops_bootstrap_static import (
    DVC_WIRING_CHECKS,
    HASH_MANIFEST_CHECKS,
    PACKAGE_REINDEX_CHECKS,
    OpsBootstrapStaticError,
    evaluate_dvc_config_wiring,
    refuse_bootstrap_overclaim,
    run_ops_bootstrap_static_suite,
)
from maskfactory.validation import validate_document


def test_dvc_config_binds_expected_remote() -> None:
    checks = evaluate_dvc_config_wiring()
    assert checks["dvc_config_remote_bound"] is True
    assert checks["remote_name"] == "maskfactory-dvc-dev"
    assert checks["remote_url"] == "s3://maskfactory-dvc-dev"


def test_bootstrap_overclaim_fail_closed() -> None:
    with pytest.raises(OpsBootstrapStaticError, match="mf_p1_07_09_complete"):
        refuse_bootstrap_overclaim({"mf_p1_07_09_complete": True})
    with pytest.raises(OpsBootstrapStaticError, match="dvc_s3_push_succeeded"):
        refuse_bootstrap_overclaim({"dvc_s3_push_succeeded": True})
    with pytest.raises(OpsBootstrapStaticError, match="dvc_push_attempted"):
        refuse_bootstrap_overclaim({"dvc_push_attempted": True})


def test_suite_seals_schema_valid_static_report() -> None:
    report = run_ops_bootstrap_static_suite()
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["mf_p1_07_09_complete"] is False
    assert report["mf_p1_09_05_complete"] is False
    assert report["dvc_s3_push_succeeded"] is False
    assert report["dvc_push_attempted"] is False
    assert report["kevin_dvc_s3_push_required"] is True
    assert report["kevin_b1_restore_required"] is True
    assert report["b1_mirror_present"] is False
    assert report["human_anchor_package_present"] is False
    assert report["doctor_green_claimed"] is False
    assert report["gold_claimed"] is False
    assert report["production_evidence_pass_claimed"] is False
    assert set(report["hash_manifest_checks"]) == set(HASH_MANIFEST_CHECKS)
    assert set(report["package_reindex_checks"]) == set(PACKAGE_REINDEX_CHECKS)
    assert set(report["dvc_wiring_checks"]) == set(DVC_WIRING_CHECKS)
    assert all(report["hash_manifest_checks"].values())
    assert all(report["package_reindex_checks"].values())
    assert all(report["dvc_wiring_checks"].values())
    assert report["dvc_runtime"]["remote_url"] == "s3://maskfactory-dvc-dev"
    assert validate_document(report, "ops_bootstrap_static_report") == ()
