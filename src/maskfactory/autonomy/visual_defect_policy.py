"""Fail-closed policy for visual-defect bounded repair promotion.

Noise-component cleanup may promote when ontology excess drops. Structural
visual defects (garment bias, underfill, exclusivity bleed into a connected
mass, multi-person half-fill) must ABSTAIN rather than invent anatomy or claim
VISUAL_QA_PASS_BOUNDED. One narrow material-exclusivity clear is allowed when
a part carries ontologically forbidden materials (e.g. footwear on chest).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

# Promotable by remove_small_components when excess CCs drop and hard QC re-passes.
NOISE_DEFECT_CLASSES = frozenset(
    {
        "noise_leak",
        "noise_artifacts",
        "noise_spray",
    }
)

# Never morphologically invent mass / cut connected bleed / split identity.
STRUCTURAL_ABSTAIN_DEFECT_CLASSES = frozenset(
    {
        "underfill",
        "exclusivity_bleed",
        "multi_person_half_fill",
        "garment_bias",
    }
)

# Narrow ontology clear: remove part pixels whose material cannot belong to the part.
MATERIAL_EXCLUSIVITY_DEFECT_CLASS = "material_exclusivity_mismatch"

# Part → material names that are never valid on that atomic part.
FORBIDDEN_MATERIALS_BY_PART: Mapping[str, frozenset[str]] = {
    "chest_upper_torso": frozenset({"footwear", "glove_or_sock", "other_person_material"}),
    "abdomen_stomach": frozenset({"footwear", "glove_or_sock", "other_person_material"}),
    "left_forearm": frozenset({"footwear", "other_person_material"}),
    "right_forearm": frozenset({"footwear", "other_person_material"}),
}

# Material-clear may promote only on these parts (never multi-person hair/identity).
MATERIAL_CLEAR_PROMOTABLE_PARTS = frozenset({"chest_upper_torso", "abdomen_stomach"})

MATERIAL_CLEAR_HYPOTHESES = frozenset(
    {
        "clear_forbidden_material_on_part",
        "clear_forbidden_material_then_max_components",
    }
)

MINIMUM_PROMOTE_DROP_PX = 64

HIGHEST_VISUAL_TIER_WITH_RESIDUALS = "VISUAL_QA_REVIEWED_WITH_DEFECTS"
BLOCKED_VISUAL_PASS_CLAIM = "VISUAL_QA_PASS_BOUNDED"


@dataclass(frozen=True)
class VisualRepairPromotionDecision:
    """Whether a DurableRepairExecutor acceptance may mutate a live package."""

    may_promote: bool
    outcome: str
    reason: str
    visual_tier: str
    claims_forbidden: tuple[str, ...]


def is_structural_abstain_class(defect_class: str) -> bool:
    return defect_class in STRUCTURAL_ABSTAIN_DEFECT_CLASSES


def is_noise_promotable_class(defect_class: str) -> bool:
    return defect_class in NOISE_DEFECT_CLASSES


def forbidden_material_names_for_part(label: str) -> frozenset[str]:
    return FORBIDDEN_MATERIALS_BY_PART.get(label, frozenset())


def decide_visual_repair_promotion(
    *,
    defect_class: str,
    hypothesis_id: str,
    executor_accepted: bool,
    drop_px: int,
    baseline_excess: int,
    hard_qc_passed: bool | None = None,
    label: str | None = None,
    forbidden_material_drop_px: int = 0,
) -> VisualRepairPromotionDecision:
    """Gate live package promotion after an executor acceptance or veto."""
    forbidden = (
        BLOCKED_VISUAL_PASS_CLAIM,
        "gold",
        "human_approved_gold",
        "PRODUCTION_EVIDENCE_PASS",
    )
    visual = HIGHEST_VISUAL_TIER_WITH_RESIDUALS

    if not executor_accepted:
        return VisualRepairPromotionDecision(
            False,
            "ABSTAIN_BOUNDED",
            "executor_did_not_accept_reversible_repair",
            visual,
            forbidden,
        )

    if hypothesis_id in MATERIAL_CLEAR_HYPOTHESES:
        if defect_class == "multi_person_half_fill":
            return VisualRepairPromotionDecision(
                False,
                "ABSTAIN_BOUNDED",
                "material clear never promotes multi_person_half_fill identity defects",
                visual,
                forbidden,
            )
        if label is not None and label not in MATERIAL_CLEAR_PROMOTABLE_PARTS:
            return VisualRepairPromotionDecision(
                False,
                "ABSTAIN_BOUNDED",
                f"material clear not promotable for part={label}",
                visual,
                forbidden,
            )
        # Compound hypotheses may also drop noise CCs; require real forbidden-material
        # removal so garment_bias cannot smuggle a pure CC cleanup through this gate.
        if forbidden_material_drop_px < MINIMUM_PROMOTE_DROP_PX:
            return VisualRepairPromotionDecision(
                False,
                "ABSTAIN_BOUNDED",
                (
                    f"forbidden_material_drop_px={forbidden_material_drop_px} "
                    f"< minimum {MINIMUM_PROMOTE_DROP_PX}; refusing CC-only smuggle"
                ),
                visual,
                forbidden,
            )
        if drop_px < MINIMUM_PROMOTE_DROP_PX:
            return VisualRepairPromotionDecision(
                False,
                "ABSTAIN_BOUNDED",
                (
                    f"material exclusivity clear drop_px={drop_px} "
                    f"< minimum {MINIMUM_PROMOTE_DROP_PX}; parent preserved"
                ),
                visual,
                forbidden,
            )
        if hard_qc_passed is False:
            return VisualRepairPromotionDecision(
                False,
                "ABSTAIN_BOUNDED",
                "material exclusivity clear failed hard QC; rolled back",
                visual,
                forbidden,
            )
        return VisualRepairPromotionDecision(
            True,
            "ACCEPTED_REVERSIBLE_REPAIR_BOUNDED",
            (
                "forbidden-material exclusivity clear accepted; hard QC must re-pass; "
                "structural garment/underfill/bleed/half-fill residuals still block "
                f"{BLOCKED_VISUAL_PASS_CLAIM}"
            ),
            visual,
            forbidden,
        )

    if defect_class in NOISE_DEFECT_CLASSES:
        if drop_px < MINIMUM_PROMOTE_DROP_PX or baseline_excess <= 0:
            return VisualRepairPromotionDecision(
                False,
                "ABSTAIN_BOUNDED",
                (
                    f"noise class accepted by executor but drop_px={drop_px} / "
                    f"baseline_excess={baseline_excess} insufficient for live promote"
                ),
                visual,
                forbidden,
            )
        if hard_qc_passed is False:
            return VisualRepairPromotionDecision(
                False,
                "ABSTAIN_BOUNDED",
                "noise promote failed hard QC; rolled back",
                visual,
                forbidden,
            )
        return VisualRepairPromotionDecision(
            True,
            "ACCEPTED_REVERSIBLE_REPAIR_BOUNDED",
            (
                "noise-component cleanup accepted via DurableRepairExecutor; "
                "hard QC re-pass; visual gold NOT claimed"
            ),
            visual,
            forbidden,
        )

    if defect_class in STRUCTURAL_ABSTAIN_DEFECT_CLASSES:
        return VisualRepairPromotionDecision(
            False,
            "ABSTAIN_BOUNDED",
            (
                f"{defect_class} not remediable by bounded morphology without false "
                f"visual pass; require Kevin CVAT correction for {BLOCKED_VISUAL_PASS_CLAIM}"
            ),
            visual,
            forbidden,
        )

    return VisualRepairPromotionDecision(
        False,
        "ABSTAIN_BOUNDED",
        f"unknown defect_class={defect_class}; fail-closed abstention",
        visual,
        forbidden,
    )


def seeded_structural_defect_kinds() -> tuple[str, ...]:
    """Canonical seeded kinds for abstention metamorphic tests."""
    return tuple(sorted(STRUCTURAL_ABSTAIN_DEFECT_CLASSES))


__all__ = [
    "BLOCKED_VISUAL_PASS_CLAIM",
    "FORBIDDEN_MATERIALS_BY_PART",
    "HIGHEST_VISUAL_TIER_WITH_RESIDUALS",
    "MATERIAL_CLEAR_HYPOTHESES",
    "MATERIAL_CLEAR_PROMOTABLE_PARTS",
    "MATERIAL_EXCLUSIVITY_DEFECT_CLASS",
    "MINIMUM_PROMOTE_DROP_PX",
    "NOISE_DEFECT_CLASSES",
    "STRUCTURAL_ABSTAIN_DEFECT_CLASSES",
    "VisualRepairPromotionDecision",
    "decide_visual_repair_promotion",
    "forbidden_material_names_for_part",
    "is_noise_promotable_class",
    "is_structural_abstain_class",
    "seeded_structural_defect_kinds",
]
