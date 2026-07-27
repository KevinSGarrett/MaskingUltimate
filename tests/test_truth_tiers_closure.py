"""Focused exact-source closure for training and holdout truth authority."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from maskfactory.truth_tiers import (
    AUTONOMOUS_CERTIFIED_GOLD,
    HUMAN_ANCHOR_GOLD,
    MACHINE_CANDIDATE,
    WEIGHTED_PSEUDO_LABEL,
    TruthTierError,
    require_training_truth_tier,
    summarize_truth_tiers,
    validate_truth_tier_policy,
)


def _policy() -> dict[str, dict[str, bool | float]]:
    return {
        HUMAN_ANCHOR_GOLD: {
            "training_weight": 1.0,
            "training_eligible": True,
            "holdout_eligible": True,
            "dataset_volume_eligible": True,
        },
        AUTONOMOUS_CERTIFIED_GOLD: {
            "training_weight": 0.65,
            "training_eligible": True,
            "holdout_eligible": False,
            "dataset_volume_eligible": True,
        },
        WEIGHTED_PSEUDO_LABEL: {
            "training_weight": 0.20,
            "training_eligible": True,
            "holdout_eligible": False,
            "dataset_volume_eligible": False,
        },
        MACHINE_CANDIDATE: {
            "training_weight": 0.0,
            "training_eligible": False,
            "holdout_eligible": False,
            "dataset_volume_eligible": False,
        },
    }


def test_truth_tier_module_matches_full_product_source() -> None:
    full_ref = "7d66ca27781d899a43eb644c0378bcf1478045a7"
    module_path = Path("src/maskfactory/truth_tiers.py")
    assert (
        subprocess.check_output(
            ["git", "rev-parse", f"{full_ref}:src/maskfactory/truth_tiers.py"], text=True
        ).strip()
        == subprocess.check_output(["git", "hash-object", str(module_path)], text=True).strip()
    )


def test_only_human_anchor_truth_can_enter_holdout() -> None:
    policy = _policy()
    validated = validate_truth_tier_policy(policy)
    assert validated[HUMAN_ANCHOR_GOLD].holdout_eligible is True
    policy[AUTONOMOUS_CERTIFIED_GOLD]["holdout_eligible"] = True
    with pytest.raises(TruthTierError, match="only human_anchor_gold"):
        validate_truth_tier_policy(policy)


@pytest.mark.parametrize(
    "label",
    [
        "synthetic_exact",
        "operationally_certified_artifact",
        "external_labeled_reference",
        "qa_passed_machine_candidate",
    ],
)
def test_nontraining_authority_never_becomes_training_truth(label: str) -> None:
    with pytest.raises(TruthTierError, match="non-training authority"):
        require_training_truth_tier(label)


def test_summary_preserves_weighted_provenance_without_promoting_machine_candidates() -> None:
    policy = validate_truth_tier_policy(_policy())
    result = summarize_truth_tiers(
        [
            {"truth_tier": HUMAN_ANCHOR_GOLD},
            {"truth_tier": AUTONOMOUS_CERTIFIED_GOLD},
            {"truth_tier": WEIGHTED_PSEUDO_LABEL},
            {"truth_tier": MACHINE_CANDIDATE},
            {"workflow_status": "residual_human_queue"},
        ],
        policy,
    )
    result_fields = result.as_dict()
    assert {key: value for key, value in result_fields.items() if key != "effective_training_truth_count"} == {
        "human_anchor_gold_count": 1,
        "autonomous_certified_gold_count": 1,
        "weighted_pseudo_label_count": 1,
        "machine_candidate_count": 2,
    }
    assert result_fields["effective_training_truth_count"] == pytest.approx(1.85)
