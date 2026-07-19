from __future__ import annotations

import pytest

from maskfactory.civitai_workflow_intake_static import (
    EXPECTED_CLASSIFICATION_COUNTS,
    EXPECTED_RECORD_COUNT,
    CivitaiWorkflowIntakeStaticError,
    bind_intake_memo,
    evaluate_license_provenance_gate,
    evaluate_metadata_disposition,
    load_classifications,
    refuse_civitai_intake_overclaim,
    run_civitai_workflow_intake_static_suite,
)
from maskfactory.validation import validate_document


def test_memo_binds() -> None:
    binding = bind_intake_memo()
    assert binding["path"] == "Plan/CIVITAI_WORKFLOW_INTAKE.md"
    assert binding["required_markers_present"] is True
    assert len(binding["sha256"]) == 64


def test_classifications_admit_without_plan_civitai_tree() -> None:
    classifications = load_classifications()
    assert classifications["record_count"] == EXPECTED_RECORD_COUNT
    assert classifications["policy"]["mask_authority"] == "none"
    metadata = evaluate_metadata_disposition(classifications)
    assert metadata["paid_download_required"] is False
    assert metadata["kevin_credentials_required"] is False


def test_license_provenance_refuses_gold_and_unreviewed_training() -> None:
    gate = evaluate_license_provenance_gate()
    assert gate["direct_gold_allowed"] is False
    with pytest.raises(CivitaiWorkflowIntakeStaticError, match="direct_gold_promotion_refused"):
        evaluate_license_provenance_gate(claim_direct_gold=True)
    with pytest.raises(
        CivitaiWorkflowIntakeStaticError,
        match="training_without_license_provenance_consent_review_refused",
    ):
        evaluate_license_provenance_gate(claim_training_without_review=True)


def test_static_admission_refuses_paid_or_kevin_credential_claims() -> None:
    with pytest.raises(
        CivitaiWorkflowIntakeStaticError,
        match="paid_download_not_required_for_static_admission",
    ):
        evaluate_license_provenance_gate(claim_paid_download_required=True)
    with pytest.raises(
        CivitaiWorkflowIntakeStaticError,
        match="kevin_credentials_not_required_for_static_admission",
    ):
        evaluate_license_provenance_gate(claim_kevin_credentials_required=True)


def test_overclaim_flags_fail_closed() -> None:
    with pytest.raises(CivitaiWorkflowIntakeStaticError, match="gold_overclaim"):
        refuse_civitai_intake_overclaim({"direct_gold_promotion_claimed": True})
    with pytest.raises(CivitaiWorkflowIntakeStaticError, match="paid_download_overclaim"):
        refuse_civitai_intake_overclaim({"paid_download_claimed": True})


def test_suite_seals_schema_valid_static_report() -> None:
    report = run_civitai_workflow_intake_static_suite()
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["classification_admission"]["record_count"] == EXPECTED_RECORD_COUNT
    assert (
        report["classification_admission"]["classification_counts"]
        == EXPECTED_CLASSIFICATION_COUNTS
    )
    assert report["metadata_disposition"]["download_action"] == "unnecessary"
    assert report["direct_gold_negative_fixture_blocked"] is True
    assert report["paid_download_negative_fixture_blocked"] is True
    assert report["kevin_credentials_negative_fixture_blocked"] is True
    assert report["gold_claimed"] is False
    assert report["report_id"].startswith("cwi_")
    assert (
        report["workflow_admissions"]["simpleImageToDWPoseDense_v10.zip"]["workflow_json"]
        == "imageToOpenPose.json"
    )
    assert (
        report["workflow_admissions"]["SegmentMaskMaskAddRemove_v10.zip"]["classification"]
        == "annotation_aid"
    )
    assert validate_document(report, "civitai_workflow_intake_static_report") == ()
