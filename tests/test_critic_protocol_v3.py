from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from maskfactory.vlm.critic_protocol_v3 import (
    CHECK_KEYS,
    CriticProtocolV3Error,
    build_description_prompt,
    build_judgement_prompt,
    derive_protocol_v3_verdict,
    evaluate_visual_acceptance,
    fit_calibration_minor_budgets,
    parse_protocol_v3_response,
    protocol_registry_sha256,
    require_holdout_eligible_registry,
    resolve_minor_budget,
    validate_protocol_registry,
)

ROOT = Path(__file__).resolve().parents[1]


def _registry() -> dict:
    return yaml.safe_load((ROOT / "configs/visual_critic_protocol_v3.yaml").read_text())


def _response(*, severity: str = "none", localization: list[int] | None = None) -> dict:
    return {
        "description": "The candidate and reference both cover the declared target in the evidence board.",
        "findings": {
            dimension: {
                "severity": severity if dimension == "boundary" else "none",
                "cited_evidence_panels": (
                    ["source", "overlay"] if dimension == "boundary" and severity != "none" else []
                ),
                "localization_xyxy": (
                    localization if dimension == "boundary" and severity != "none" else None
                ),
            }
            for dimension in CHECK_KEYS
        },
    }


def test_registry_is_separate_fail_closed_and_hash_bound() -> None:
    registry = _registry()
    validate_protocol_registry(registry)
    assert len(protocol_registry_sha256(registry)) == 64
    assert (
        resolve_minor_budget(
            registry,
            label_id="hair",
            source_authority_tier="external_labeled_reference",
            label_scale="small",
        )
        == 0
    )
    with pytest.raises(CriticProtocolV3Error, match="not fitted"):
        require_holdout_eligible_registry(registry)
    with pytest.raises(CriticProtocolV3Error, match="unavailable"):
        resolve_minor_budget(
            registry,
            label_id="hand",
            source_authority_tier="external_labeled_reference",
            label_scale="small",
        )


def test_two_pass_prompt_is_reference_anchored_and_budget_bound() -> None:
    registry = _registry()
    description = build_description_prompt(
        label_id="hair",
        source_authority_tier="external_labeled_reference",
        label_scale="small",
        reference_case_id="celebamask_19094_hair",
    )
    assert "Do not issue a verdict" in description
    judgement = build_judgement_prompt(
        description="The candidate resembles the reference.",
        label_id="hair",
        source_authority_tier="external_labeled_reference",
        label_scale="small",
        reference_case_id="celebamask_19094_hair",
        registry=registry,
    )
    assert "image-disjoint known-good reference" in judgement
    assert "At most 0 minor findings" in judgement


def test_serious_finding_is_a_defect_and_never_a_pass() -> None:
    result = derive_protocol_v3_verdict(
        response=_response(severity="serious", localization=[1, 1, 9, 9]),
        registry=_registry(),
        label_id="hair",
        source_authority_tier="external_labeled_reference",
        label_scale="small",
        target_roi_xyxy=[0, 0, 10, 10],
    )
    assert result["verdict"] == "defect"
    assert result["reason"] == "serious_finding"
    assert result["authority_claimed"] is False


def test_minor_budget_is_deterministic_and_incoherent_evidence_abstains() -> None:
    registry = _registry()
    registry["tolerance_bands"][0]["minor_budget"] = 1
    within = derive_protocol_v3_verdict(
        response=_response(severity="minor", localization=[1, 1, 9, 9]),
        registry=registry,
        label_id="hair",
        source_authority_tier="external_labeled_reference",
        label_scale="small",
        target_roi_xyxy=[0, 0, 10, 10],
    )
    assert within["verdict"] == "pass_with_findings"
    incoherent = derive_protocol_v3_verdict(
        response=_response(severity="minor", localization=[20, 20, 30, 30]),
        registry=registry,
        label_id="hair",
        source_authority_tier="external_labeled_reference",
        label_scale="small",
        target_roi_xyxy=[0, 0, 10, 10],
    )
    assert incoherent["verdict"] == "abstain"
    assert incoherent["evidence_localization_coherent"] is False


def test_parser_rejects_missing_or_unlocalized_finding() -> None:
    response = _response(severity="minor", localization=[1, 1, 9, 9])
    del response["findings"]["boundary"]["cited_evidence_panels"]
    with pytest.raises(CriticProtocolV3Error, match="finding fields"):
        parse_protocol_v3_response(__import__("json").dumps(response))
    response = _response(severity="minor", localization=None)
    with pytest.raises(CriticProtocolV3Error, match="coordinate"):
        parse_protocol_v3_response(__import__("json").dumps(response))


def test_visual_acceptance_requires_hard_qa_and_a_qualified_critic() -> None:
    verdict = derive_protocol_v3_verdict(
        response=_response(),
        registry=_registry(),
        label_id="hair",
        source_authority_tier="external_labeled_reference",
        label_scale="small",
        target_roi_xyxy=[0, 0, 10, 10],
    )
    assert (
        evaluate_visual_acceptance(
            deterministic_qa_passes=True, critic_is_qualified=False, verdict=verdict
        )["status"]
        == "abstain"
    )
    assert (
        evaluate_visual_acceptance(
            deterministic_qa_passes=False, critic_is_qualified=True, verdict=verdict
        )["status"]
        == "blocked"
    )
    assert (
        evaluate_visual_acceptance(
            deterministic_qa_passes=True, critic_is_qualified=True, verdict=verdict
        )["status"]
        == "pass"
    )


def test_fit_uses_calibration_only_and_rejects_holdout_contact() -> None:
    observation = {
        "split": "calibration",
        "label_id": "hair",
        "source_authority_tier": "external_labeled_reference",
        "label_scale": "small",
        "expected_outcome": "valid_mask",
        "serious_defect_count": 0,
        "minor_finding_count": 2,
    }
    assert fit_calibration_minor_budgets([observation])[0]["minor_budget"] == 2
    holdout = deepcopy(observation)
    holdout["split"] = "qualification_holdout"
    with pytest.raises(CriticProtocolV3Error, match="may not contact holdout"):
        fit_calibration_minor_budgets([holdout])
