from __future__ import annotations

import pytest

from maskfactory.horizon_go_no_go_static import (
    MULTI_PERSON_GO_EVIDENCE,
    VIDEO_INDEPENDENT_GO_EVIDENCE,
    VIDEO_PRODUCTION_GO_EVIDENCE,
    HorizonGoNoGoStaticError,
    bind_horizon_memos,
    evaluate_multi_person_horizon,
    evaluate_video_horizon,
    refuse_horizon_overclaim,
    run_horizon_go_no_go_static_suite,
)
from maskfactory.validation import validate_document


def test_memos_bind() -> None:
    bindings = bind_horizon_memos()
    assert bindings["multi_person"]["path"].endswith("HORIZON_MULTI_PERSON_GO_NO_GO.md")
    assert bindings["video"]["path"].endswith("HORIZON_VIDEO_GO_NO_GO.md")
    assert len(bindings["multi_person"]["sha256"]) == 64


def test_multi_person_refuses_go_without_evidence() -> None:
    empty = {key: False for key in MULTI_PERSON_GO_EVIDENCE}
    result = evaluate_multi_person_horizon(empty)
    assert result["independent_real_accuracy_decision"] == "NO_GO"
    assert result["architecture_into_p8"] is True

    with pytest.raises(HorizonGoNoGoStaticError, match="multi_person_independent_real_go_refused"):
        evaluate_multi_person_horizon(empty, claim_independent_real_go=True)


def test_multi_person_go_when_evidence_complete() -> None:
    full = {key: True for key in MULTI_PERSON_GO_EVIDENCE}
    result = evaluate_multi_person_horizon(full, claim_independent_real_go=True)
    assert result["independent_real_accuracy_decision"] == "GO"
    assert result["evidence_complete"] is True


def test_video_refuses_production_and_independent_go() -> None:
    empty = {key: False for key in VIDEO_PRODUCTION_GO_EVIDENCE + VIDEO_INDEPENDENT_GO_EVIDENCE}
    result = evaluate_video_horizon(empty)
    assert result["core_contract_implementation_authorized"] is True
    assert result["production_use_decision"] == "NO_GO"
    assert result["independent_real_accuracy_decision"] == "NO_GO"

    with pytest.raises(HorizonGoNoGoStaticError, match="video_production_go_refused"):
        evaluate_video_horizon(empty, claim_production_go=True)
    with pytest.raises(HorizonGoNoGoStaticError, match="video_independent_real_go_refused"):
        evaluate_video_horizon(empty, claim_independent_real_go=True)


def test_overclaim_flags_fail_closed() -> None:
    with pytest.raises(HorizonGoNoGoStaticError, match="mp_independent_go_overclaim"):
        refuse_horizon_overclaim({"multi_person_independent_real_accuracy_go_claimed": True})
    with pytest.raises(HorizonGoNoGoStaticError, match="horizon_decision_overclaim"):
        refuse_horizon_overclaim(
            {
                "multi_person_independent_real_accuracy_go_claimed": False,
                "multi_person_production_go_claimed": False,
                "video_production_use_go_claimed": False,
                "video_independent_real_accuracy_go_claimed": False,
                "mf_p8_exit_complete": False,
                "mf_p7_exit_complete": False,
                "doctor_green_claimed": False,
                "gold_claimed": False,
                "visual_qa_pass_claimed": False,
                "main_complete_claimed": False,
                "production_evidence_pass_claimed": False,
                "multi_person_independent_real_accuracy_decision": "GO",
            }
        )


def test_suite_seals_schema_valid_static_report() -> None:
    report = run_horizon_go_no_go_static_suite()
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["multi_person_independent_real_accuracy_decision"] == "NO_GO"
    assert report["video_production_use_decision"] == "NO_GO"
    assert report["video_independent_real_accuracy_decision"] == "NO_GO"
    assert report["mf_p8_exit_complete"] is False
    assert report["mf_p7_exit_complete"] is False
    assert report["multi_person_negative_go_fixture_blocked"] is True
    assert report["video_production_negative_go_fixture_blocked"] is True
    assert report["video_independent_negative_go_fixture_blocked"] is True
    assert report["report_id"].startswith("hgn_")
    assert validate_document(report, "horizon_go_no_go_static_report") == ()
