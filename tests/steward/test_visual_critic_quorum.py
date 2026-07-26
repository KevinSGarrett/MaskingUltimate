from __future__ import annotations

import copy
import hashlib
import json

import pytest

from maskfactory.steward.visual_critic_quorum import (
    VisualCriticQuorumError,
    build_critic_certificate,
    build_critic_response,
    build_panel_bundle,
    evaluate_visual_quorum,
    validate_visual_quorum,
)

PNG = b"\x89PNG\r\n\x1a\nbounded-panel"
ZERO_SHA256 = "0" * 64


def _panels() -> dict[str, bytes]:
    return {
        role: PNG + role.encode("ascii")
        for role in ("source", "mask", "overlay", "contour", "ownership")
    }


def _certificate(role: str, family: str) -> dict:
    return build_critic_certificate(
        role=role,
        model_id=f"{role}-model",
        model_sha256=hashlib.sha256(f"{role}-model".encode()).hexdigest(),
        runtime_sha256=hashlib.sha256(f"{role}-runtime".encode()).hexdigest(),
        family_id=family,
        capability_class=(
            "high_end_multimodal"
            if role == "primary"
            else "independent_multimodal_juror"
        ),
        qualification_report_sha256=hashlib.sha256(
            f"{role}-qualification".encode()
        ).hexdigest(),
        positive_calibration_passed=True,
        negative_calibration_passed=True,
    )


def _response(
    certificate: dict,
    panel_sha256: str,
    *,
    status: str = "COMPLETE",
    verdict: str | None = "PASS",
) -> dict:
    return build_critic_response(
        certificate=certificate,
        panel_bundle_sha256=panel_sha256,
        status=status,
        verdict=verdict,
        confidence=0.99 if status == "COMPLETE" else None,
        raw_response_sha256=hashlib.sha256(
            f"{certificate['role']}:{status}:{verdict}".encode()
        ).hexdigest(),
    )


def _inputs() -> dict:
    panels = _panels()
    bundle = build_panel_bundle(panels)
    primary = _certificate("primary", "family-primary")
    juror = _certificate("juror", "family-independent")
    return {
        "hard_qa_outcome": "PASS",
        "panel_bundle": bundle,
        "panels": panels,
        "primary_certificate": primary,
        "juror_certificate": juror,
        "primary_response": _response(primary, bundle["panel_bundle_sha256"]),
        "juror_response": _response(juror, bundle["panel_bundle_sha256"]),
    }


def _reseal(value: dict, field: str) -> dict:
    value = copy.deepcopy(value)
    value[field] = ZERO_SHA256
    value[field] = hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    return value


def test_positive_calibration_quorum_passes_but_grants_no_authority() -> None:
    result = evaluate_visual_quorum(**_inputs())

    assert result["outcome"] == "VISUAL_QA_PASS_BOUNDED"
    assert result["authority_granted"] is False
    assert "final_mask_acceptance" in result["claims_forbidden"]
    assert "text_only_acceptance" in result["claims_forbidden"]


def test_negative_calibration_failure_blocks_certificate() -> None:
    inputs = _inputs()
    bad = copy.deepcopy(inputs["primary_certificate"])
    bad["negative_calibration_passed"] = False
    inputs["primary_certificate"] = _reseal(bad, "certificate_sha256")

    result = evaluate_visual_quorum(**inputs)

    assert result["outcome"] == "VISUAL_CRITIC_BLOCKED"
    assert result["authority_granted"] is False


def test_correlated_primary_and_juror_cannot_form_quorum() -> None:
    inputs = _inputs()
    inputs["juror_certificate"] = _certificate("juror", "family-primary")
    inputs["juror_response"] = _response(
        inputs["juror_certificate"],
        inputs["panel_bundle"]["panel_bundle_sha256"],
    )

    result = evaluate_visual_quorum(**inputs)

    assert result["outcome"] == "ABSTAIN_CORRELATED_CRITICS"


def test_same_model_cannot_spoof_independence_with_a_new_family_label() -> None:
    inputs = _inputs()
    juror = copy.deepcopy(inputs["juror_certificate"])
    juror["model_id"] = inputs["primary_certificate"]["model_id"]
    juror["model_sha256"] = inputs["primary_certificate"]["model_sha256"]
    inputs["juror_certificate"] = _reseal(juror, "certificate_sha256")
    inputs["juror_response"] = _response(
        inputs["juror_certificate"],
        inputs["panel_bundle"]["panel_bundle_sha256"],
    )

    result = evaluate_visual_quorum(**inputs)

    assert result["outcome"] == "ABSTAIN_CORRELATED_CRITICS"


@pytest.mark.parametrize("status", ["UNAVAILABLE", "MALFORMED", "TIMEOUT"])
def test_incomplete_critic_status_fails_closed(status: str) -> None:
    inputs = _inputs()
    inputs["juror_response"] = _response(
        inputs["juror_certificate"],
        inputs["panel_bundle"]["panel_bundle_sha256"],
        status=status,
        verdict=None,
    )

    result = evaluate_visual_quorum(**inputs)

    assert result["outcome"] == "VISUAL_CRITIC_BLOCKED"
    assert result["authority_granted"] is False


def test_critic_disagreement_abstains() -> None:
    inputs = _inputs()
    inputs["juror_response"] = _response(
        inputs["juror_certificate"],
        inputs["panel_bundle"]["panel_bundle_sha256"],
        verdict="UNCERTAIN",
    )

    result = evaluate_visual_quorum(**inputs)

    assert result["outcome"] == "ABSTAIN_VISUAL_DISAGREEMENT"


def test_negative_visual_verdict_rejects() -> None:
    inputs = _inputs()
    inputs["primary_response"] = _response(
        inputs["primary_certificate"],
        inputs["panel_bundle"]["panel_bundle_sha256"],
        verdict="FAIL",
    )

    result = evaluate_visual_quorum(**inputs)

    assert result["outcome"] == "REJECT_VISUAL"


def test_hard_qa_veto_cannot_be_overridden_by_two_passes() -> None:
    inputs = _inputs()
    inputs["hard_qa_outcome"] = "VETO"

    result = evaluate_visual_quorum(**inputs)

    assert result["outcome"] == "ABSTAIN_HARD_QA_VETO"
    assert result["authority_granted"] is False


def test_text_only_primary_capability_fails_closed() -> None:
    inputs = _inputs()
    bad = copy.deepcopy(inputs["primary_certificate"])
    bad["capability_class"] = "text_only"
    inputs["primary_certificate"] = _reseal(bad, "certificate_sha256")

    result = evaluate_visual_quorum(**inputs)

    assert result["outcome"] == "VISUAL_CRITIC_BLOCKED"


def test_panel_byte_drift_fails_closed() -> None:
    inputs = _inputs()
    inputs["panels"]["overlay"] += b"-drift"

    result = evaluate_visual_quorum(**inputs)

    assert result["outcome"] == "VISUAL_CRITIC_BLOCKED"


def test_response_authority_claim_fails_closed() -> None:
    inputs = _inputs()
    bad = copy.deepcopy(inputs["primary_response"])
    bad["authority_claimed"] = True
    inputs["primary_response"] = _reseal(bad, "response_sha256")

    result = evaluate_visual_quorum(**inputs)

    assert result["outcome"] == "VISUAL_CRITIC_BLOCKED"


def test_deterministic_replay_rejects_rehashed_semantic_drift() -> None:
    inputs = _inputs()
    result = evaluate_visual_quorum(**inputs)
    validate_visual_quorum(result, **inputs)
    tampered = copy.deepcopy(result)
    tampered["outcome"] = "REJECT_VISUAL"
    tampered = _reseal(tampered, "quorum_sha256")

    with pytest.raises(
        VisualCriticQuorumError,
        match="deterministic replay mismatch",
    ):
        validate_visual_quorum(tampered, **inputs)
