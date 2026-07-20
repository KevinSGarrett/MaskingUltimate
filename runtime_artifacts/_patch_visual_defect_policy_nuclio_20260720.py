"""One-shot patch: add sam2_nuclio_part_refine promotion gate."""

from __future__ import annotations

from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "src/maskfactory/autonomy/visual_defect_policy.py"

OLD1 = """MATERIAL_CLEAR_HYPOTHESES = frozenset(
    {
        "clear_forbidden_material_on_part",
        "clear_forbidden_material_then_max_components",
    }
)

MINIMUM_PROMOTE_DROP_PX = 64

HIGHEST_VISUAL_TIER_WITH_RESIDUALS = "VISUAL_QA_REVIEWED_WITH_DEFECTS"
BLOCKED_VISUAL_PASS_CLAIM = "VISUAL_QA_PASS_BOUNDED"
"""

NEW1 = """MATERIAL_CLEAR_HYPOTHESES = frozenset(
    {
        "clear_forbidden_material_on_part",
        "clear_forbidden_material_then_max_components",
    }
)

# Nuclio/CVAT pth-sam2 part refine (WSL-independent). May promote a cleaner part
# mask when component excess drops; never elevates visual tier to PASS.
SAM2_NUCLIO_PART_REFINE_HYPOTHESIS = "sam2_nuclio_part_refine"
SAM2_NUCLIO_PROMOTABLE_DEFECT_CLASSES = frozenset(
    {
        "fragmentation",
        "underfill",
    }
)

MINIMUM_PROMOTE_DROP_PX = 64
MINIMUM_SAM2_CC_EXCESS_DROP = 1

HIGHEST_VISUAL_TIER_WITH_RESIDUALS = "VISUAL_QA_REVIEWED_WITH_DEFECTS"
BLOCKED_VISUAL_PASS_CLAIM = "VISUAL_QA_PASS_BOUNDED"
"""

OLD2 = """    if not executor_accepted:
        return VisualRepairPromotionDecision(
            False,
            "ABSTAIN_BOUNDED",
            "executor_did_not_accept_reversible_repair",
            visual,
            forbidden,
        )

    if hypothesis_id in MATERIAL_CLEAR_HYPOTHESES:
"""

NEW2 = """    if not executor_accepted:
        return VisualRepairPromotionDecision(
            False,
            "ABSTAIN_BOUNDED",
            "executor_did_not_accept_reversible_repair",
            visual,
            forbidden,
        )

    if hypothesis_id == SAM2_NUCLIO_PART_REFINE_HYPOTHESIS:
        if defect_class not in SAM2_NUCLIO_PROMOTABLE_DEFECT_CLASSES:
            return VisualRepairPromotionDecision(
                False,
                "ABSTAIN_BOUNDED",
                (
                    f"sam2_nuclio_part_refine does not promote defect_class={defect_class}; "
                    f"allowed={sorted(SAM2_NUCLIO_PROMOTABLE_DEFECT_CLASSES)}"
                ),
                visual,
                forbidden,
            )
        if baseline_excess < MINIMUM_SAM2_CC_EXCESS_DROP:
            return VisualRepairPromotionDecision(
                False,
                "ABSTAIN_BOUNDED",
                (
                    f"sam2_nuclio baseline_excess={baseline_excess} "
                    f"< minimum {MINIMUM_SAM2_CC_EXCESS_DROP}; parent preserved"
                ),
                visual,
                forbidden,
            )
        if hard_qc_passed is False:
            return VisualRepairPromotionDecision(
                False,
                "ABSTAIN_BOUNDED",
                "sam2_nuclio promote failed hard QC; rolled back",
                visual,
                forbidden,
            )
        return VisualRepairPromotionDecision(
            True,
            "ACCEPTED_REVERSIBLE_REPAIR_BOUNDED",
            (
                "nuclio/CVAT pth-sam2 part refine accepted; component excess reduced; "
                f"hard QC re-pass; {BLOCKED_VISUAL_PASS_CLAIM} still forbidden "
                "(instance may retain other structural residuals)"
            ),
            visual,
            forbidden,
        )

    if hypothesis_id in MATERIAL_CLEAR_HYPOTHESES:
"""


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    if (
        "SAM2_NUCLIO_PART_REFINE_HYPOTHESIS =" in text
        and "hypothesis_id == SAM2_NUCLIO_PART_REFINE_HYPOTHESIS" in text
    ):
        print("already_patched")
        return
    if OLD1 not in text:
        raise SystemExit("anchor1 missing")
    text = text.replace(OLD1, NEW1, 1)
    if OLD2 not in text:
        raise SystemExit("anchor2 missing")
    text = text.replace(OLD2, NEW2, 1)
    # Ensure __all__ exports exist.
    for name in (
        '"MINIMUM_SAM2_CC_EXCESS_DROP",',
        '"SAM2_NUCLIO_PART_REFINE_HYPOTHESIS",',
        '"SAM2_NUCLIO_PROMOTABLE_DEFECT_CLASSES",',
    ):
        if name not in text:
            text = text.replace(
                '"MINIMUM_PROMOTE_DROP_PX",\n',
                '"MINIMUM_PROMOTE_DROP_PX",\n'
                '    "MINIMUM_SAM2_CC_EXCESS_DROP",\n'
                '    "NOISE_DEFECT_CLASSES_PLACEHOLDER",\n',
                1,
            )
            # Prefer a clean rewrite of the NOISE line block if we bungled; fix below.
            break
    # Clean accidental placeholder if introduced.
    text = text.replace(
        '    "NOISE_DEFECT_CLASSES_PLACEHOLDER",\n    "NOISE_DEFECT_CLASSES",\n',
        '    "NOISE_DEFECT_CLASSES",\n',
    )
    if '"SAM2_NUCLIO_PART_REFINE_HYPOTHESIS",' not in text:
        text = text.replace(
            '    "MINIMUM_PROMOTE_DROP_PX",\n    "NOISE_DEFECT_CLASSES",\n',
            '    "MINIMUM_PROMOTE_DROP_PX",\n'
            '    "MINIMUM_SAM2_CC_EXCESS_DROP",\n'
            '    "NOISE_DEFECT_CLASSES",\n'
            '    "SAM2_NUCLIO_PART_REFINE_HYPOTHESIS",\n'
            '    "SAM2_NUCLIO_PROMOTABLE_DEFECT_CLASSES",\n',
            1,
        )
    tmp = PATH.with_suffix(".py.tmp_nuclio")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(PATH)
    check = PATH.read_text(encoding="utf-8")
    assert "SAM2_NUCLIO_PART_REFINE_HYPOTHESIS =" in check
    assert "hypothesis_id == SAM2_NUCLIO_PART_REFINE_HYPOTHESIS" in check
    print("patched", PATH, "bytes", PATH.stat().st_size)


if __name__ == "__main__":
    main()
