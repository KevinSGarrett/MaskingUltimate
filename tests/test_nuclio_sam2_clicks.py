"""Unit tests for Nuclio SAM2 click derivation + promotion gate (no live CVAT)."""

from __future__ import annotations

import numpy as np

from maskfactory.providers.nuclio_sam2 import (
    BLOCKED_VISUAL_PASS_CLAIM,
    HIGHEST_VISUAL_TIER_WITH_RESIDUALS,
    decide_sam2_nuclio_promotion,
    derive_clicks_from_mask,
)


def test_derive_clicks_prefers_largest_component_and_roi() -> None:
    mask = np.zeros((64, 64), dtype=bool)
    mask[10:30, 10:30] = True  # large
    mask[50:52, 50:52] = True  # noise island
    protected = np.zeros_like(mask)
    protected[10:30, 40:50] = True
    pos, neg, roi = derive_clicks_from_mask(mask, protected=protected, max_positives=3)
    assert len(pos) >= 1
    assert all(mask[y, x] for x, y in pos)
    left, top, right, bottom = roi
    assert left <= 10 and top <= 10 and right >= 30 and bottom >= 30
    assert any(not mask[y, x] for x, y in neg)


def test_sam2_nuclio_promotion_fragmentation_without_visual_pass() -> None:
    decision = decide_sam2_nuclio_promotion(
        defect_class="fragmentation",
        executor_accepted=True,
        baseline_excess=76,
        hard_qc_passed=True,
    )
    assert decision.may_promote is True
    assert decision.outcome == "ACCEPTED_REVERSIBLE_REPAIR_BOUNDED"
    assert decision.visual_tier == HIGHEST_VISUAL_TIER_WITH_RESIDUALS
    assert BLOCKED_VISUAL_PASS_CLAIM in decision.claims_forbidden


def test_sam2_nuclio_promotion_abstains_on_garment_bias() -> None:
    decision = decide_sam2_nuclio_promotion(
        defect_class="garment_bias",
        executor_accepted=True,
        baseline_excess=10,
        hard_qc_passed=True,
    )
    assert decision.may_promote is False
    assert decision.outcome == "ABSTAIN_BOUNDED"
