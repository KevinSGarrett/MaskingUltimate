"""Seeded structural visual defects must ABSTAIN; never claim VISUAL_QA_PASS_BOUNDED."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from maskfactory.autonomy.visual_defect_policy import (
    BLOCKED_VISUAL_PASS_CLAIM,
    HIGHEST_VISUAL_TIER_WITH_RESIDUALS,
    MINIMUM_PROMOTE_DROP_PX,
    NOISE_DEFECT_CLASSES,
    STRUCTURAL_ABSTAIN_DEFECT_CLASSES,
    decide_visual_repair_promotion,
    forbidden_material_names_for_part,
    seeded_structural_defect_kinds,
)
from maskfactory.ontology import get_ontology


@pytest.mark.parametrize("defect_class", sorted(STRUCTURAL_ABSTAIN_DEFECT_CLASSES))
def test_seeded_structural_defect_abstains_even_if_executor_accepts(defect_class: str) -> None:
    decision = decide_visual_repair_promotion(
        defect_class=defect_class,
        hypothesis_id="remove_small_components_max_ontology",
        executor_accepted=True,
        drop_px=500,
        baseline_excess=9,
        hard_qc_passed=True,
    )
    assert decision.may_promote is False
    assert decision.outcome == "ABSTAIN_BOUNDED"
    assert defect_class in decision.reason
    assert decision.visual_tier == HIGHEST_VISUAL_TIER_WITH_RESIDUALS
    assert BLOCKED_VISUAL_PASS_CLAIM in decision.claims_forbidden


@pytest.mark.parametrize("defect_class", sorted(NOISE_DEFECT_CLASSES))
def test_noise_class_may_promote_when_drop_and_excess_qualify(defect_class: str) -> None:
    decision = decide_visual_repair_promotion(
        defect_class=defect_class,
        hypothesis_id="remove_small_components_max_ontology",
        executor_accepted=True,
        drop_px=MINIMUM_PROMOTE_DROP_PX,
        baseline_excess=3,
        hard_qc_passed=True,
    )
    assert decision.may_promote is True
    assert decision.outcome == "ACCEPTED_REVERSIBLE_REPAIR_BOUNDED"
    assert BLOCKED_VISUAL_PASS_CLAIM in decision.claims_forbidden


def test_noise_class_abstains_when_hard_qc_fails() -> None:
    decision = decide_visual_repair_promotion(
        defect_class="noise_leak",
        hypothesis_id="remove_small_components_max_ontology",
        executor_accepted=True,
        drop_px=1000,
        baseline_excess=10,
        hard_qc_passed=False,
    )
    assert decision.may_promote is False
    assert decision.outcome == "ABSTAIN_BOUNDED"
    assert "hard QC" in decision.reason


def test_material_exclusivity_clear_promotes_only_with_sufficient_drop() -> None:
    too_small = decide_visual_repair_promotion(
        defect_class="garment_bias",
        hypothesis_id="clear_forbidden_material_then_max_components",
        executor_accepted=True,
        drop_px=MINIMUM_PROMOTE_DROP_PX - 1,
        baseline_excess=5,
        hard_qc_passed=True,
        label="chest_upper_torso",
    )
    assert too_small.may_promote is False
    assert too_small.outcome == "ABSTAIN_BOUNDED"

    smuggle = decide_visual_repair_promotion(
        defect_class="garment_bias",
        hypothesis_id="clear_forbidden_material_then_max_components",
        executor_accepted=True,
        drop_px=5000,
        baseline_excess=5,
        hard_qc_passed=True,
        label="chest_upper_torso",
        forbidden_material_drop_px=0,
    )
    assert smuggle.may_promote is False
    assert "smuggle" in smuggle.reason

    ok = decide_visual_repair_promotion(
        defect_class="garment_bias",
        hypothesis_id="clear_forbidden_material_then_max_components",
        executor_accepted=True,
        drop_px=MINIMUM_PROMOTE_DROP_PX,
        baseline_excess=5,
        hard_qc_passed=True,
        label="chest_upper_torso",
        forbidden_material_drop_px=MINIMUM_PROMOTE_DROP_PX,
    )
    assert ok.may_promote is True
    assert ok.outcome == "ACCEPTED_REVERSIBLE_REPAIR_BOUNDED"
    assert ok.visual_tier == HIGHEST_VISUAL_TIER_WITH_RESIDUALS
    assert BLOCKED_VISUAL_PASS_CLAIM in ok.claims_forbidden


def test_material_clear_never_promotes_multi_person_or_non_chest_parts() -> None:
    half = decide_visual_repair_promotion(
        defect_class="multi_person_half_fill",
        hypothesis_id="clear_forbidden_material_then_max_components",
        executor_accepted=True,
        drop_px=10_000,
        baseline_excess=5,
        hard_qc_passed=True,
        label="hair",
    )
    assert half.may_promote is False
    forearm = decide_visual_repair_promotion(
        defect_class="exclusivity_bleed",
        hypothesis_id="clear_forbidden_material_on_part",
        executor_accepted=True,
        drop_px=10_000,
        baseline_excess=5,
        hard_qc_passed=True,
        label="left_forearm",
    )
    assert forearm.may_promote is False


def test_seeded_kinds_cover_all_structural_classes() -> None:
    assert set(seeded_structural_defect_kinds()) == set(STRUCTURAL_ABSTAIN_DEFECT_CLASSES)


def test_chest_forbidden_materials_include_footwear_not_bra() -> None:
    forbidden = forbidden_material_names_for_part("chest_upper_torso")
    assert "footwear" in forbidden
    assert "glove_or_sock" in forbidden
    assert "bra" not in forbidden
    assert "top_garment" not in forbidden
    assert "skin" not in forbidden


def test_seeded_connected_exclusivity_bleed_cannot_be_split_by_cc_cleanup() -> None:
    """Hip triangle fused to forearm mass: largest-CC keep cannot remove bleed."""
    mask = np.zeros((40, 40), dtype=bool)
    mask[5:15, 5:15] = True  # forearm core
    mask[14:25, 14:30] = True  # connected hip/trunk bleed
    labels, count = ndimage.label(mask)
    assert count == 1
    sizes = {i: int((labels == i).sum()) for i in range(1, count + 1)}
    keep = {max(sizes, key=sizes.get)}
    candidate = np.isin(labels, list(keep))
    drop_px = int(mask.sum()) - int(candidate.sum())
    assert drop_px == 0
    decision = decide_visual_repair_promotion(
        defect_class="exclusivity_bleed",
        hypothesis_id="remove_small_components_max_ontology",
        executor_accepted=True,
        drop_px=drop_px,
        baseline_excess=0,
        hard_qc_passed=True,
    )
    assert decision.may_promote is False
    assert decision.outcome == "ABSTAIN_BOUNDED"


def test_seeded_underfill_fill_would_invent_mass_so_policy_abstains() -> None:
    """Tiny patch vs expected limb area: morphology cannot safely invent forearm."""
    ontology = get_ontology()
    assert ontology.label("left_forearm").max_components == 1
    tiny = np.zeros((64, 64), dtype=bool)
    tiny[30:34, 30:34] = True
    # A "fill" candidate that grows 20x would invent anatomy — policy forbids promote.
    decision = decide_visual_repair_promotion(
        defect_class="underfill",
        hypothesis_id="dilate_to_expected_area",
        executor_accepted=True,
        drop_px=0,
        baseline_excess=0,
        hard_qc_passed=True,
    )
    assert decision.may_promote is False
    assert decision.outcome == "ABSTAIN_BOUNDED"


def test_seeded_multi_person_half_fill_abstains() -> None:
    decision = decide_visual_repair_promotion(
        defect_class="multi_person_half_fill",
        hypothesis_id="remove_small_components_max_ontology",
        executor_accepted=True,
        drop_px=9,
        baseline_excess=9,
        hard_qc_passed=True,
    )
    assert decision.may_promote is False
    assert "multi_person_half_fill" in decision.reason


def test_seeded_garment_bias_morphology_abstains_without_material_clear() -> None:
    decision = decide_visual_repair_promotion(
        defect_class="garment_bias",
        hypothesis_id="remove_small_components_max_ontology",
        executor_accepted=True,
        drop_px=2000,
        baseline_excess=90,
        hard_qc_passed=True,
    )
    assert decision.may_promote is False
    assert decision.outcome == "ABSTAIN_BOUNDED"
    assert BLOCKED_VISUAL_PASS_CLAIM not in decision.outcome
