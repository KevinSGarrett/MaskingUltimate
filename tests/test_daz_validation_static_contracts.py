from __future__ import annotations

import pytest

from maskfactory.daz.validation_static_contracts import (
    ACCEPTANCE_CHECKS,
    REGISTRY_CHECKS,
    REPAIR_CHECKS,
    S00_CHECKS,
    DazValidationStaticError,
    refuse_validation_overclaim,
    run_daz_validation_static_suite,
)
from maskfactory.validation import validate_document


def test_validation_overclaim_fail_closed() -> None:
    with pytest.raises(DazValidationStaticError, match="mf_p9_08_10_pilot_complete"):
        refuse_validation_overclaim({"mf_p9_08_10_pilot_complete": True})
    with pytest.raises(DazValidationStaticError, match="accepted_package_produced"):
        refuse_validation_overclaim({"accepted_package_produced": True})
    with pytest.raises(DazValidationStaticError, match="gold_claimed"):
        refuse_validation_overclaim({"gold_claimed": True})


def test_suite_seals_schema_valid_static_report() -> None:
    report = run_daz_validation_static_suite()
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["mf_p9_08_01_complete"] is False
    assert report["mf_p9_08_05_complete"] is False
    assert report["mf_p9_08_10_pilot_complete"] is False
    assert report["live_daz_validation_executed"] is False
    assert report["accepted_package_produced"] is False
    assert report["doctor_green_claimed"] is False
    assert report["gold_claimed"] is False
    assert report["main_complete_claimed"] is False
    assert report["production_evidence_pass_claimed"] is False
    assert set(report["registry_checks"]) == set(REGISTRY_CHECKS)
    assert set(report["acceptance_checks"]) == set(ACCEPTANCE_CHECKS)
    assert set(report["repair_checks"]) == set(REPAIR_CHECKS)
    assert set(report["s00_checks"]) == set(S00_CHECKS)
    assert all(report["registry_checks"].values())
    assert all(report["acceptance_checks"].values())
    assert all(report["repair_checks"].values())
    assert all(report["s00_checks"].values())
    assert report["negative_fixtures"]["completion_overclaim_blocked"] is True
    assert report["negative_fixtures"]["registry_warn_policy_tamper_blocked"] is True
    assert validate_document(report, "daz_validation_static_contracts_report") == ()
