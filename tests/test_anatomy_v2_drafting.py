import json
from pathlib import Path

import numpy as np
import pytest

from maskfactory.anatomy_v2_drafting import (
    NEW_LABELS,
    AnatomyBoxProposal,
    AnatomyDraftCandidate,
    AnatomyV2DraftError,
    build_anatomy_crop_proposals,
    canonical_open_vocab_requests,
    fuse_anatomy_v2_candidates,
    load_anatomy_v2_config,
    proposal_to_sam2_plan,
    refine_anatomy_with_sam2,
    same_side_anatomy_priors,
    write_anatomy_review_bundle,
)
from maskfactory.stages.s07_sam2 import SamCandidate


class FakeSam2:
    def __init__(self, mask: np.ndarray, *, predicted_iou: float = 0.9) -> None:
        self.mask = mask.astype(bool)
        self.predicted_iou = predicted_iou
        self.calls = 0

    def predict(self, _embedding, _plan, *, multimask_output: bool):
        assert multimask_output is True
        self.calls += 1
        logits = np.where(self.mask, 1.0, -1.0).astype(np.float32)
        empty = np.full(self.mask.shape, -1.0, dtype=np.float32)
        return [
            SamCandidate(logits, self.predicted_iou),
            SamCandidate(empty, max(0.0, self.predicted_iou - 0.1)),
            SamCandidate(empty, max(0.0, self.predicted_iou - 0.2)),
        ]


def _regions(shape: tuple[int, int] = (128, 128)) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    silhouette = np.ones(shape, dtype=bool)
    chest = np.zeros(shape, dtype=bool)
    chest[12:62, 18:110] = True
    pelvic = np.zeros(shape, dtype=bool)
    pelvic[70:116, 30:98] = True
    return silhouette, chest, pelvic


def _candidate(
    label: str, mask: np.ndarray | None, *, confidence: float = 0.9, state: str = "visible"
) -> AnatomyDraftCandidate:
    return AnatomyDraftCandidate(
        label,
        state,
        mask,
        confidence,
        (
            "interactive_segmenter_refined_non_gold_review_draft"
            if mask is not None
            else "suppressed_for_human_review"
        ),
        f"review {label}",
        {
            "content_lane_decision": "consensual_explicit_adult",
            "sam2_required": True,
            "detector_box_used_as_mask": False,
            "geometry_prior_used_as_mask": False,
        },
    )


def test_inactive_config_is_canonical_visible_only_and_content_lane_gated() -> None:
    config = load_anatomy_v2_config()
    assert config["activation_status"] == "approved_design_not_active"
    assert tuple(config["prompts"]) == NEW_LABELS
    assert all(prompt.startswith("visible exposed") for prompt in config["prompts"].values())
    assert set(config["governance"]["permitted_content_lanes"]) == {
        "general",
        "adult_nonexplicit",
        "consensual_explicit_adult",
    }
    assert config["governance"]["detector_boxes_may_be_final_masks"] is False
    assert config["governance"]["geometry_priors_may_be_final_masks"] is False


def test_review_crops_and_prompts_assert_no_positive_or_hidden_anatomy() -> None:
    states = {name: "unreviewed_for_v2" for name in NEW_LABELS}
    states["penis_shaft"] = "occluded_by_clothing"
    crops = build_anatomy_crop_proposals(
        image_size=(100, 120),
        chest_bbox_xyxy=(-10, 5, 80, 60),
        pelvic_bbox_xyxy=(20, 55, 110, 130),
        visibility_states=states,
        content_lane_decision="consensual_explicit_adult",
    )
    assert len(crops) == 9
    assert all(crop.authority == "review_crop_only" for crop in crops)
    assert all(crop.asserts_positive_anatomy is False for crop in crops)
    assert all(0 <= crop.bbox_xyxy[0] < crop.bbox_xyxy[2] <= 100 for crop in crops)
    assert all(0 <= crop.bbox_xyxy[1] < crop.bbox_xyxy[3] <= 120 for crop in crops)
    requests = canonical_open_vocab_requests(
        crops, content_lane_decision="consensual_explicit_adult"
    )
    assert len(requests) == 8
    assert "penis_shaft" not in {request.label for request in requests}
    assert all(request.authority == "proposal_box_only" for request in requests)
    assert all(request.may_write_final_mask is False for request in requests)
    with pytest.raises(AnatomyV2DraftError, match="permitted content lane"):
        canonical_open_vocab_requests(crops, content_lane_decision="unsupported")


def test_same_side_priors_clip_clothing_hair_ambiguity_and_profile_hidden_side() -> None:
    silhouette, chest, pelvic = _regions()
    clothing = np.zeros_like(silhouette)
    clothing[20:40, 20:40] = True
    hair = np.zeros_like(silhouette)
    hair[12:30, 40:58] = True
    ambiguity = np.zeros_like(silhouette)
    ambiguity[80:90, 40:50] = True
    priors = same_side_anatomy_priors(
        silhouette=silhouette,
        chest_region=chest,
        pelvic_region=pelvic,
        midline_x=64,
        character_left_is_lower_x=True,
        view="left_profile",
        clothing=clothing,
        hair_occlusion=hair,
        ambiguity=ambiguity,
    )
    assert set(priors) == set(NEW_LABELS)
    assert priors["left_areola"].roi.any()
    assert not priors["right_areola"].roi.any()
    assert not (priors["left_areola"].roi & clothing).any()
    assert not (priors["left_nipple"].roi & hair).any()
    assert not (priors["vulva"].roi & ambiguity).any()
    assert all(prior.authority == "spatial_gate_only" for prior in priors.values())
    assert all(prior.may_write_final_mask is False for prior in priors.values())


def test_detector_box_must_route_through_sam2_and_low_confidence_never_uses_prior() -> None:
    silhouette, chest, pelvic = _regions()
    prior = same_side_anatomy_priors(
        silhouette=silhouette,
        chest_region=chest,
        pelvic_region=pelvic,
        midline_x=64,
        character_left_is_lower_x=True,
        view="front",
    )["left_areola"]
    proposal = AnatomyBoxProposal(
        "left_areola",
        "visible exposed left areolar ring",
        (20, 20, 58, 56),
        0.92,
        0.88,
        "consensual_explicit_adult",
    )
    plan = proposal_to_sam2_plan(proposal, prior, silhouette=silhouette)
    assert plan.label == "left_areola" and plan.multimask_output is True
    sam_mask = np.zeros_like(prior.roi)
    sam_mask[20:56, 20:58] = True
    sam_mask &= prior.roi
    provider = FakeSam2(sam_mask)
    candidate = refine_anatomy_with_sam2(
        provider,
        object(),
        proposal,
        prior,
        silhouette=silhouette,
        visibility_state="unreviewed_for_v2",
        model="sam2.1_hiera_large",
    )
    assert provider.calls == 1
    assert candidate.mask is not None and candidate.mask.any()
    assert candidate.authority == "interactive_segmenter_refined_non_gold_review_draft"
    assert candidate.provenance["detector_box_used_as_mask"] is False
    assert candidate.provenance["geometry_prior_used_as_mask"] is False
    assert candidate.provenance["sam2_required"] is True

    low = FakeSam2(sam_mask, predicted_iou=0.2)
    suppressed = refine_anatomy_with_sam2(
        low,
        object(),
        proposal,
        prior,
        silhouette=silhouette,
        visibility_state="visible",
        model="sam2.1_hiera_large",
    )
    assert low.calls == 1 and suppressed.mask is None
    assert suppressed.provenance["reason"] == "sam2_low_conf"

    covered = refine_anatomy_with_sam2(
        FakeSam2(sam_mask),
        object(),
        proposal,
        prior,
        silhouette=silhouette,
        visibility_state="occluded_by_clothing",
        model="sam2.1_hiera_large",
    )
    assert covered.mask is None and covered.provenance["reason"] == "occluded_by_clothing"
    with pytest.raises(AnatomyV2DraftError, match="permitted content lane"):
        refine_anatomy_with_sam2(
            FakeSam2(sam_mask),
            object(),
            AnatomyBoxProposal(
                proposal.label,
                proposal.prompt,
                proposal.bbox_xyxy,
                proposal.box_score,
                proposal.text_score,
                "unsupported",
            ),
            prior,
            silhouette=silhouette,
            visibility_state="occluded_by_clothing",
            model="sam2.1_hiera_large",
        )


def test_fusion_carves_breast_pelvic_parents_and_routes_conflicts_to_ignore() -> None:
    shape = (96, 96)
    silhouette = np.ones(shape, dtype=bool)
    left_breast = np.zeros(shape, dtype=bool)
    left_breast[10:45, 5:45] = True
    right_breast = np.zeros(shape, dtype=bool)
    right_breast[10:45, 51:91] = True
    pelvic = np.zeros(shape, dtype=bool)
    pelvic[50:92, 20:76] = True
    abdomen = np.zeros(shape, dtype=bool)
    abdomen[45:50, 20:76] = True

    left_areola = np.zeros(shape, dtype=bool)
    left_areola[22:34, 18:34] = True
    left_areola[45:48, 24:30] = True  # Unrelated abdomen overlap becomes ignore.
    left_nipple = np.zeros(shape, dtype=bool)
    left_nipple[26:30, 24:28] = True
    shaft = np.zeros(shape, dtype=bool)
    shaft[62:82, 42:54] = True
    glans = np.zeros(shape, dtype=bool)
    glans[62:68, 44:52] = True
    vulva = np.zeros(shape, dtype=bool)
    vulva[74:84, 48:58] = True  # Deliberate shaft conflict becomes ignore.
    left_scrotal = np.zeros(shape, dtype=bool)
    left_scrotal[80:88, 38:48] = True
    right_scrotal = np.zeros(shape, dtype=bool)
    right_scrotal[80:88, 46:56] = True  # Deliberate side overlap becomes ignore.
    candidates = {
        "left_areola": _candidate("left_areola", left_areola),
        "left_nipple": _candidate("left_nipple", left_nipple),
        "penis_shaft": _candidate("penis_shaft", shaft),
        "glans_penis": _candidate("glans_penis", glans),
        "vulva": _candidate("vulva", vulva),
        "left_scrotal_region": _candidate("left_scrotal_region", left_scrotal),
        "right_scrotal_region": _candidate("right_scrotal_region", right_scrotal),
    }
    result = fuse_anatomy_v2_candidates(
        {
            "left_breast": left_breast,
            "right_breast": right_breast,
            "pelvic_region": pelvic,
            "abdomen_stomach": abdomen,
        },
        candidates,
        silhouette=silhouette,
    )
    assert result.audit["authority"] == "non_gold_review_draft"
    assert result.audit["detector_boxes_used_as_masks"] is False
    assert result.audit["sam2_required_for_new_positive_masks"] is True
    assert result.audit["incompatible_overlap_pixels_to_ignore"] > 0
    assert result.audit["unrelated_v1_overlap_pixels_to_ignore"] > 0
    assert result.ambiguity_ignore.any()
    assert not (result.atomic_masks["left_areola"] & result.atomic_masks["left_nipple"]).any()
    assert not (result.atomic_masks["penis_shaft"] & result.atomic_masks["glans_penis"]).any()
    assert not (
        result.atomic_masks["left_breast"]
        & (result.atomic_masks["left_areola"] | result.atomic_masks["left_nipple"])
    ).any()
    genital = np.logical_or.reduce([result.atomic_masks[name] for name in NEW_LABELS[4:]])
    assert not (result.atomic_masks["pelvic_region"] & genital).any()
    assert set(np.unique(result.part_map)).issubset(set(range(65)))


def test_review_bundle_contains_strict_masks_panel_confidence_provenance_and_instructions(
    tmp_path: Path,
) -> None:
    shape = (64, 64)
    silhouette = np.ones(shape, dtype=bool)
    left_breast = np.zeros(shape, dtype=bool)
    left_breast[8:40, 4:30] = True
    pelvic = np.zeros(shape, dtype=bool)
    pelvic[40:62, 20:44] = True
    areola = np.zeros(shape, dtype=bool)
    areola[18:28, 12:24] = True
    candidate = _candidate("left_areola", areola, confidence=0.87)
    result = fuse_anatomy_v2_candidates(
        {"left_breast": left_breast, "pelvic_region": pelvic},
        {"left_areola": candidate},
        silhouette=silhouette,
    )
    source = np.zeros((*shape, 3), dtype=np.uint8)
    report_path, panel_path, mask_paths = write_anatomy_review_bundle(
        source, result, {"left_areola": candidate}, tmp_path / "review"
    )
    assert report_path.is_file() and panel_path.is_file() and len(mask_paths) == 9
    report = json.loads(report_path.read_text())
    assert report["human_review_required"] is True and report["gold_approved"] is False
    assert report["labels"]["left_areola"]["confidence_max"] == pytest.approx(0.87)
    assert "areolar ring" in report["labels"]["left_areola"]["correction_instruction"]
    assert report["labels"]["left_areola"]["provenance"]["status"] == "candidate"


@pytest.mark.parametrize(
    ("scenario", "view", "state", "blocker", "expect_left", "expect_right"),
    [
        ("nude", "front", "visible", "none", True, True),
        ("clothed", "front", "occluded_by_clothing", "clothing", False, False),
        ("partial", "front", "partially_visible", "partial", True, True),
        ("distant", "front", "unreviewed_for_v2", "none", True, True),
        ("hair_occluded", "front", "partially_visible", "hair", True, True),
        ("side_view", "left_profile", "partially_visible", "none", True, False),
        ("cropped", "front", "cropped_out", "none", True, True),
    ],
)
def test_required_drafting_fixture_conditions(
    scenario: str,
    view: str,
    state: str,
    blocker: str,
    expect_left: bool,
    expect_right: bool,
) -> None:
    size = 256 if scenario == "distant" else 96
    shape = (size, size)
    silhouette = np.ones(shape, dtype=bool)
    chest = np.zeros(shape, dtype=bool)
    chest[size // 8 : size // 2, size // 8 : 7 * size // 8] = True
    pelvic = np.zeros(shape, dtype=bool)
    pelvic[size // 2 : 7 * size // 8, size // 4 : 3 * size // 4] = True
    clothing = np.zeros(shape, dtype=bool)
    hair = np.zeros(shape, dtype=bool)
    if blocker == "clothing":
        clothing |= chest | pelvic
    elif blocker == "partial":
        clothing[:, : size // 5] = True
    elif blocker == "hair":
        hair[size // 8 : size // 3, size // 3 : size // 2] = True
    priors = same_side_anatomy_priors(
        silhouette=silhouette,
        chest_region=chest,
        pelvic_region=pelvic,
        midline_x=size // 2,
        character_left_is_lower_x=True,
        view=view,
        clothing=clothing,
        hair_occlusion=hair,
    )
    assert bool(priors["left_areola"].roi.any()) is expect_left
    assert bool(priors["right_areola"].roi.any()) is expect_right
    if blocker in {"clothing", "partial"}:
        assert not (priors["left_areola"].roi & clothing).any()
    if blocker == "hair":
        assert not (priors["left_areola"].roi & hair).any()
    box = (-20, -10, size // 2, size // 2) if scenario == "cropped" else (0, 0, size, size)
    crops = build_anatomy_crop_proposals(
        image_size=(size, size),
        chest_bbox_xyxy=box,
        pelvic_bbox_xyxy=(size // 4, size // 2, size + 10, size + 20),
        visibility_states={name: state for name in NEW_LABELS},
        content_lane_decision="consensual_explicit_adult",
    )
    assert len(crops) == 9
    assert all(0 <= value <= size for crop in crops for value in crop.bbox_xyxy)
    requests = canonical_open_vocab_requests(
        crops, content_lane_decision="consensual_explicit_adult"
    )
    if state in {"occluded_by_clothing", "cropped_out"}:
        assert requests == ()
    else:
        assert len(requests) == 9
