from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from maskfactory.autonomy.repair import (
    BoundedRepairLimits,
    RepairAttempt,
    RepairRegion,
    atomic_boundary_vetoes,
    build_pose_side_evidence,
    decide_bounded_repair,
    evaluate_repair_candidate,
    immutable_protected_union,
    load_repair_regions,
    merge_specialist_repair_regions,
    normalized_roi_points_to_source,
    requires_reconstruction,
)
from maskfactory.autonomy.review_draft import compose_candidate_map_transactional
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.ontology import get_ontology
from maskfactory.serve.providers import Sam2InteractiveRefiner
from maskfactory.stages.s07_sam2 import SamCandidate


def _eligible_repair_guard() -> object:
    return evaluate_repair_candidate(
        np.pad(np.ones((2, 2), dtype=bool), 4),
        current_mask=np.pad(np.ones((2, 2), dtype=bool), 4),
        protected_mask=np.zeros((10, 10), dtype=bool),
        label="right_foot_base",
        roi_xyxy=(0, 0, 10, 10),
        person_bbox_xyxy=(0, 0, 10, 10),
        ordinary_max_changed_fraction=0.75,
        reconstruction_max_changed_fraction=2.0,
        maximum_protected_overlap_fraction=0.01,
        maximum_outside_roi_fraction=0.005,
        expected_area_slack=1.0,
    )


def test_bounded_repair_requires_distinct_hypotheses_and_immutable_parent() -> None:
    limits = BoundedRepairLimits(3, 60, 4, 2, 1_000)
    history = (RepairAttempt("parent-sha", "hypothesis-a", 500_000, 1, 1),)
    decision = decide_bounded_repair(
        accepted_parent_id="parent-sha",
        hypothesis_id="hypothesis-a",
        guard=_eligible_repair_guard(),
        current_score_ppm=600_000,
        attempt_elapsed_seconds=1,
        attempt_resource_units=1,
        limits=limits,
        history=history,
    )

    assert decision.outcome == "rolled_back_abstain"
    assert decision.reason == "hypothesis_not_distinct"
    assert decision.rollback_required
    assert decision.accepted_parent_id == "parent-sha"


def test_bounded_repair_caps_resources_and_no_progress_without_human_queue() -> None:
    limits = BoundedRepairLimits(3, 60, 2, 2, 1_000)
    history = (
        RepairAttempt("parent-sha", "hypothesis-a", 500_000, 1, 1),
        RepairAttempt("parent-sha", "hypothesis-b", 500_500, 1, 1),
    )
    decision = decide_bounded_repair(
        accepted_parent_id="parent-sha",
        hypothesis_id="hypothesis-c",
        guard=_eligible_repair_guard(),
        current_score_ppm=500_900,
        attempt_elapsed_seconds=1,
        attempt_resource_units=1,
        limits=limits,
        history=history,
    )

    assert decision.outcome == "rolled_back_abstain"
    assert decision.reason == "resource_cap_exhausted"
    assert "human" not in decision.outcome

    time_capped = decide_bounded_repair(
        accepted_parent_id="parent-sha",
        hypothesis_id="hypothesis-c",
        guard=_eligible_repair_guard(),
        current_score_ppm=500_900,
        attempt_elapsed_seconds=59,
        attempt_resource_units=0,
        limits=BoundedRepairLimits(4, 60, 4, 2, 1_000),
        history=history,
    )
    assert time_capped.reason == "time_cap_exhausted"

    decision = decide_bounded_repair(
        accepted_parent_id="parent-sha",
        hypothesis_id="hypothesis-c",
        guard=_eligible_repair_guard(),
        current_score_ppm=500_900,
        attempt_elapsed_seconds=1,
        attempt_resource_units=0,
        limits=BoundedRepairLimits(4, 60, 4, 2, 1_000),
        history=history,
    )
    assert decision.outcome == "rolled_back_abstain"
    assert decision.reason == "no_progress_cap_exhausted"
    assert decision.rollback_required


def test_bounded_repair_rolls_back_unsafe_candidate_then_accepts_progress() -> None:
    limits = BoundedRepairLimits(3, 60, 4, 2, 1_000)
    unsafe = evaluate_repair_candidate(
        np.ones((10, 10), dtype=bool),
        current_mask=np.pad(np.ones((2, 2), dtype=bool), 4),
        protected_mask=np.zeros((10, 10), dtype=bool),
        label="right_foot_base",
        roi_xyxy=(0, 0, 10, 10),
        person_bbox_xyxy=(0, 0, 10, 10),
        ordinary_max_changed_fraction=0.75,
        reconstruction_max_changed_fraction=2.0,
        maximum_protected_overlap_fraction=0.01,
        maximum_outside_roi_fraction=0.005,
        expected_area_slack=1.0,
    )
    retry = decide_bounded_repair(
        accepted_parent_id="parent-sha",
        hypothesis_id="hypothesis-a",
        guard=unsafe,
        current_score_ppm=500_000,
        attempt_elapsed_seconds=1,
        attempt_resource_units=1,
        limits=limits,
    )
    accepted = decide_bounded_repair(
        accepted_parent_id="parent-sha",
        hypothesis_id="hypothesis-b",
        guard=_eligible_repair_guard(),
        current_score_ppm=600_000,
        attempt_elapsed_seconds=1,
        attempt_resource_units=1,
        limits=limits,
        history=(RepairAttempt("parent-sha", "hypothesis-a", 500_000, 1, 1),),
    )

    assert retry.outcome == "rolled_back_retry_distinct_hypothesis"
    assert retry.rollback_required
    assert accepted.outcome == "accepted_reversible_repair"
    assert not accepted.rollback_required


def test_atomic_foot_boundary_rejects_whole_foot_when_toes_are_visible() -> None:
    pose = {
        "keypoints": [
            {"index": 20, "x": 85, "y": 30, "confidence": 0.95},
            {"index": 21, "x": 85, "y": 40, "confidence": 0.95},
            {"index": 22, "x": 15, "y": 35, "confidence": 0.95},
        ]
    }
    whole_foot = np.zeros((70, 100), dtype=bool)
    whole_foot[20:50, 10:92] = True

    vetoes = atomic_boundary_vetoes(
        whole_foot,
        label="right_foot_base",
        pose_document=pose,
        companion_parts_visible=True,
    )

    assert vetoes == ("MF-BOUNDARY-foot_mtp-whole_foot_as_foot_base",)


def test_atomic_foot_boundary_allows_mtp_split_and_closed_shoe_exception() -> None:
    pose = {
        "keypoints": [
            {"index": 20, "x": 85, "y": 30, "confidence": 0.95},
            {"index": 21, "x": 85, "y": 40, "confidence": 0.95},
            {"index": 22, "x": 15, "y": 35, "confidence": 0.95},
        ]
    }
    base_only = np.zeros((70, 100), dtype=bool)
    base_only[20:50, 10:65] = True
    whole_shoe = np.zeros_like(base_only)
    whole_shoe[20:50, 10:92] = True

    assert not atomic_boundary_vetoes(
        base_only,
        label="right_foot_base",
        pose_document=pose,
        companion_parts_visible=True,
    )
    assert not atomic_boundary_vetoes(
        whole_shoe,
        label="right_foot_base",
        pose_document=pose,
        companion_parts_visible=False,
    )


def test_atomic_hand_boundary_rejects_whole_hand_as_hand_base() -> None:
    tips = (116, 120, 124, 128, 132)
    pose = {
        "keypoints": [
            {"index": index, "x": 30 + offset * 8, "y": 20, "confidence": 0.9}
            for offset, index in enumerate(tips)
        ]
    }
    whole_hand = np.zeros((60, 80), dtype=bool)
    whole_hand[10:45, 20:70] = True

    assert atomic_boundary_vetoes(
        whole_hand,
        label="right_hand_base",
        pose_document=pose,
        companion_parts_visible=True,
    ) == ("MF-BOUNDARY-hand_mcp-whole_hand_as_hand_base",)


def test_pose_side_evidence_resolves_crossed_legs_by_semantic_chain() -> None:
    pose = {
        "keypoints": [
            {"index": index, "x": x, "y": y, "confidence": 0.9}
            for index, x, y in (
                (11, 80, 30),
                (13, 55, 60),
                (15, 25, 90),
                (12, 30, 30),
                (14, 50, 60),
                (16, 80, 90),
            )
        ]
    }
    foreground = np.zeros((100, 100), bool)
    foreground[85:95, 75:90] = True
    evidence = build_pose_side_evidence(
        "right_foot_base", pose, context_origin_xy=(0, 0), candidate_mask=foreground
    )
    assert evidence is not None
    assert evidence["nearest_semantic_chain"] == "right"
    assert evidence["assignment_consistent"] is True
    assert evidence["right_chain"][-1]["coco_index"] == 16


def test_s05_geometry_becomes_padded_repair_roi(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts.json"
    prompts.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "plans": [
                    {
                        "label": "right_foot_base",
                        "box_xyxy": [20, 70, 40, 90],
                        "prior_quality": "pose",
                    },
                    {
                        "label": "right_foot_base",
                        "box_xyxy": [25, 72, 50, 92],
                        "prior_quality": "specialist_assisted",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    regions = load_repair_regions(prompts, image_shape=(100, 80), padding_fraction=0.1)
    assert regions["right_foot_base"].bbox_xyxy == (17, 68, 53, 94)
    assert regions["right_foot_base"].source == "s05_geometry_prompt"


def test_specialist_replaces_only_a_containing_pathologically_large_s05_roi() -> None:
    regions = {
        "right_foot_base": RepairRegion(
            "right_foot_base", (150, 900, 1600, 5600), "s05_geometry_prompt", "high"
        ),
        "left_foot_base": RepairRegion(
            "left_foot_base", (100, 4700, 850, 5250), "s05_geometry_prompt", "high"
        ),
    }
    merged = merge_specialist_repair_regions(
        regions,
        label_metadata={
            "right_foot_base": (
                {
                    "bbox_xyxy": [760, 5070, 1495, 5408],
                    "confidence": 0.925,
                    "detector_key": "foot_specialist",
                },
            ),
            "left_foot_base": (
                {
                    "bbox_xyxy": [190, 4850, 770, 5210],
                    "confidence": 0.91,
                    "detector_key": "foot_specialist",
                },
            ),
        },
        image_shape=(5632, 1876),
        padding_fraction=0.1,
    )

    assert merged["right_foot_base"].source == "specialist_box_replaces_oversized_s05"
    assert merged["right_foot_base"].bbox_xyxy == (686, 5036, 1569, 5442)
    assert merged["left_foot_base"] == regions["left_foot_base"]


def test_provider_coordinates_are_relative_to_roi() -> None:
    points = normalized_roi_points_to_source(
        ((0, 0), (500, 500), (1000, 1000)),
        (100, 200, 300, 600),
        (800, 500),
    )
    assert points == ((100, 200), (200, 400), (299, 599))


def test_catastrophic_mask_uses_reconstruction_guard() -> None:
    current = np.zeros((100, 100), dtype=bool)
    current[10:40, 10:40] = True
    candidate = np.zeros_like(current)
    candidate[85:88, 30:40] = True
    assert requires_reconstruction(
        current,
        label="right_foot_base",
        person_bbox_xyxy=(0, 0, 100, 100),
    )
    guard = evaluate_repair_candidate(
        candidate,
        current_mask=current,
        protected_mask=np.zeros_like(current),
        label="right_foot_base",
        roi_xyxy=(20, 75, 50, 95),
        person_bbox_xyxy=(0, 0, 100, 100),
        ordinary_max_changed_fraction=0.75,
        reconstruction_max_changed_fraction=2.0,
        maximum_protected_overlap_fraction=0.01,
        maximum_outside_roi_fraction=0.005,
        expected_area_slack=0.5,
    )
    assert guard.eligible and guard.reconstruction_mode
    assert guard.changed_fraction > 0.75


def test_reconstruction_still_rejects_whole_image_sam_failure() -> None:
    current = np.zeros((100, 100), dtype=bool)
    current[10:40, 10:40] = True
    candidate = np.ones_like(current)
    guard = evaluate_repair_candidate(
        candidate,
        current_mask=current,
        protected_mask=np.zeros_like(current),
        label="right_foot_base",
        roi_xyxy=(20, 75, 50, 95),
        person_bbox_xyxy=(0, 0, 100, 100),
        ordinary_max_changed_fraction=0.75,
        reconstruction_max_changed_fraction=2.0,
        maximum_protected_overlap_fraction=0.01,
        maximum_outside_roi_fraction=0.005,
        expected_area_slack=0.5,
    )
    assert not guard.eligible
    assert {
        "candidate_change_limit",
        "candidate_outside_repair_roi",
        "candidate_area_sanity",
    } <= set(guard.vetoes)


def test_transaction_reassigns_only_inside_roi_and_refuses_immutable(tmp_path: Path) -> None:
    ontology = get_ontology()
    target_id = int(ontology.label("right_foot_base").id)
    incumbent_id = int(ontology.label("right_calf").id)
    immutable_id = int(ontology.label("other_person").id)
    base = np.zeros((20, 20), dtype=np.uint16)
    base[12:18, 4:12] = incumbent_id
    candidate = np.zeros((20, 20), dtype=np.uint8)
    candidate[15:18, 5:11] = 255
    path = write_binary_mask(tmp_path / "candidate.png", candidate)
    output, vetoes, displaced = compose_candidate_map_transactional(
        base,
        label="right_foot_base",
        candidate_mask_path=path,
        repair_roi_xyxy=(3, 10, 13, 19),
        immutable_label_ids=(immutable_id,),
    )
    assert not vetoes and displaced == {incumbent_id: 18}
    assert np.all(output[15:18, 5:11] == target_id)
    base[16, 6] = immutable_id
    _, vetoes, _ = compose_candidate_map_transactional(
        base,
        label="right_foot_base",
        candidate_mask_path=path,
        repair_roi_xyxy=(3, 10, 13, 19),
        immutable_label_ids=(immutable_id,),
    )
    assert vetoes == ("candidate_immutable_label_overwrite",)


def test_immutable_union_excludes_ordinary_draft_labels() -> None:
    ontology = get_ontology()
    part = np.zeros((8, 8), dtype=np.uint16)
    part[1, 1] = int(ontology.label("right_calf").id)
    part[2, 2] = int(ontology.label("other_person").id)
    protected = immutable_protected_union(part)
    assert not protected[1, 1]
    assert protected[2, 2]


def test_sam2_refiner_passes_explicit_roi_box() -> None:
    events = []

    class Provider:
        def embed(self, image, *, model, precision):
            return "embedding"

        def predict(self, embedding, plan, *, multimask_output):
            events.append(plan.box_xyxy)
            logits = np.full((20, 30), -1, dtype=np.float32)
            logits[12:18, 8:20] = 1
            return [SamCandidate(logits, 0.9)]

        def close(self, embedding):
            return None

    refiner = Sam2InteractiveRefiner(Provider())
    mask = refiner.refine_roi(
        np.zeros((20, 30, 3), dtype=np.uint8),
        "right_foot_base",
        ({"x": 10, "y": 15, "positive": True},),
        roi_xyxy=(5, 10, 25, 20),
    )
    assert mask.sum() == 72
    assert events == [(5, 10, 25, 20)]


def test_sam2_refiner_clips_roi_and_keeps_only_positive_anchored_components() -> None:
    class Provider:
        def embed(self, image, *, model, precision):
            return "embedding"

        def predict(self, embedding, plan, *, multimask_output):
            logits = np.full((20, 30), -1, dtype=np.float32)
            logits[12:18, 8:20] = 1
            logits[0:4, 0:4] = 1
            logits[14:16, 26:29] = 1
            return [SamCandidate(logits, 0.9)]

        def close(self, embedding):
            return None

    refiner = Sam2InteractiveRefiner(Provider())
    mask = refiner.refine_roi(
        np.zeros((20, 30, 3), dtype=np.uint8),
        "right_foot_base",
        ({"x": 10, "y": 15, "positive": True},),
        roi_xyxy=(5, 10, 25, 20),
    )
    assert mask.sum() == 72
    assert not mask[:10].any() and not mask[:, 25:].any()
