import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.lanes.common import CropTransform, reproject_crop_mask
from maskfactory.lanes.hand import (
    HandGeometry,
    HandLaneError,
    apply_finger_merge_policy,
    apply_hand_contact_zorder,
    assign_gap_ownership,
    build_hand_geometry,
    build_hand_prompt_plans,
    create_hand_crop,
    draft_hand_with_champion,
    evaluate_hand_predictions,
    refine_hand_with_sam2,
    write_hand_evidence,
)
from maskfactory.stages.s07_sam2 import SamCandidate
from maskfactory.training.leaderboard import load_leaderboard


def _champion_registry(tmp_path: Path) -> tuple[Path, Path, Path]:
    models_root = tmp_path / "models"
    models_root.mkdir()
    checkpoint = models_root / "hand.bin"
    checkpoint.write_bytes(b"verified hand champion")
    document = json.loads(Path("models/model_registry.json").read_text())
    entry = dict(document["models"][0])
    entry.update(
        {
            "key": "fixture_hand_champion",
            "role": "champion_hand",
            "file": "hand.bin",
            "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "verified": True,
        }
    )
    document["models"] = [entry]
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(document), encoding="utf-8")
    return registry, models_root, checkpoint


def test_promoted_hand_model_is_crop_drafter_and_sam2_boundary_stays_separate(
    tmp_path: Path,
) -> None:
    registry, models_root, checkpoint = _champion_registry(tmp_path)
    indexed = np.zeros((64, 64), dtype=np.uint8)
    indexed[30:55, 20:45] = 1
    for offset, class_id in enumerate((3, 5, 7, 9, 11)):
        indexed[8:32, 10 + offset * 9 : 16 + offset * 9] = class_id
    events = []

    class Provider:
        def __call__(self, image, side):
            events.append(("predict", image.shape, side))
            return indexed

        def close(self):
            events.append(("close",))

    def loader(path):
        assert path == checkpoint
        events.append(("load", path.name))
        return Provider()

    draft = draft_hand_with_champion(
        np.zeros((64, 64, 3), dtype=np.uint8),
        side="left",
        loader=loader,
        registry_path=registry,
        models_root=models_root,
    )
    assert draft.role == "champion_hand"
    assert draft.checkpoint_sha256 == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    assert set(draft.geometry.finger_masks) == {
        "left_thumb",
        "left_index_finger",
        "left_middle_finger",
        "left_ring_finger",
        "left_pinky",
    }
    assert draft.geometry.hand_base.any() and draft.geometry.finger_gap_regions.any()
    assert events[0] == ("load", "hand.bin") and events[-1] == ("close",)
    # Drafting never receives a SAM2 provider; refine_hand_with_sam2 remains a separate API.

    indexed[0, 0] = 4  # right-thumb class in a left-hand crop
    with pytest.raises(HandLaneError, match="opposite-side"):
        draft_hand_with_champion(
            np.zeros((64, 64, 3), dtype=np.uint8),
            side="left",
            loader=loader,
            registry_path=registry,
            models_root=models_root,
        )


def _pose() -> np.ndarray:
    pose = np.zeros((133, 3), dtype=np.float64)
    pose[:, 2] = 0.0
    pose[9] = (80, 100, 0.9)
    for offset, index in enumerate(range(91, 112)):
        pose[index] = (82 + offset % 5 * 5, 95 - offset // 5 * 6, 0.8)
    pose[10] = (220, 100, 0.9)
    for offset, index in enumerate(range(112, 133)):
        pose[index] = (218 - offset % 5 * 5, 95 - offset // 5 * 6, 0.8)
    return pose


def test_hand_crop_uses_wrist_and_all_side_dwpose_points(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (300, 200), "white").save(source)
    prior = np.zeros((200, 300), dtype=bool)
    prior[60:110, 70:110] = True
    lane = create_hand_crop(source, prior, _pose(), side="left", output_dir=tmp_path / "crops")
    assert lane.image_path.name == "left_hand_crop.png"
    assert lane.transform.part == "left_hand"
    assert lane.transform.full_side == 48  # ceil(1.6 * 30px wrist/hand extent)
    assert lane.transform.x0 <= 80 and lane.transform.y0 <= 71


def test_mediapipe_evidence_serializes_21_and_skeleton_wins_mismatch(tmp_path: Path) -> None:
    landmarks = np.arange(63, dtype=np.float64).reshape(21, 3) / 100
    evidence = write_hand_evidence(
        landmarks,
        side="left",
        mediapipe_handedness="Right",
        mediapipe_score=0.97,
        skeleton_side="left",
        output_dir=tmp_path,
    )
    assert len(evidence.landmarks) == 21
    assert evidence.handedness_mismatch and evidence.qc014_flag
    assert evidence.resolved_side == "left"
    document = json.loads(evidence.evidence_path.read_text())
    assert document["arbitration"] == "skeleton_wins"
    assert document["mediapipe"] == {"handedness": "right", "score": 0.97}
    assert len(document["landmarks"]) == 21


def test_hand_lane_rejects_insufficient_pose_and_bad_landmarks(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 100), "white").save(source)
    with pytest.raises(HandLaneError, match="insufficient"):
        create_hand_crop(
            source,
            np.zeros((100, 100), bool),
            np.zeros((133, 3)),
            side="left",
            output_dir=tmp_path,
        )
    with pytest.raises(HandLaneError, match="21x3"):
        write_hand_evidence(
            np.zeros((20, 3)),
            side="left",
            mediapipe_handedness="left",
            mediapipe_score=1,
            skeleton_side="left",
            output_dir=tmp_path,
        )


def _landmarks() -> np.ndarray:
    points = np.zeros((21, 2), dtype=np.float64)
    points[0] = (50, 90)
    # thumb, then four upright fingers with separated chains
    points[1:5] = [(42, 82), (35, 75), (30, 67), (25, 60)]
    for start, x in ((5, 28), (9, 44), (13, 60), (17, 76)):
        points[start : start + 4] = [(x, 72), (x, 58), (x, 44), (x, 30)]
    return points


def test_finger_strips_palm_subtraction_and_gap_ownership() -> None:
    parsing = np.zeros((120, 100), dtype=bool)
    parsing[20:100, 12:90] = True
    geometry = build_hand_geometry(_landmarks(), parsing, side="left")
    assert set(geometry.finger_masks) == {
        "left_thumb",
        "left_index_finger",
        "left_middle_finger",
        "left_ring_finger",
        "left_pinky",
    }
    assert all(mask.any() for mask in geometry.finger_masks.values())
    finger_union = np.logical_or.reduce(tuple(geometry.finger_masks.values()))
    assert geometry.hand_base.any()
    assert not (geometry.hand_base & finger_union).any()
    assert geometry.finger_gap_regions.any()
    assert not (geometry.finger_gap_regions & finger_union).any()
    behind = np.zeros(parsing.shape, dtype=np.uint16)
    behind[geometry.finger_gap_regions] = 7
    owned = assign_gap_ownership(geometry.finger_gap_regions, behind)
    assert np.all(owned[geometry.finger_gap_regions] == 7)
    assert np.all(owned[~geometry.finger_gap_regions] == 0)


def test_low_confidence_never_guesses_split_and_queues_finger_merge() -> None:
    parsing = np.zeros((120, 100), dtype=bool)
    parsing[20:100, 12:90] = True
    geometry = build_hand_geometry(_landmarks(), parsing, side="left")
    confidence = np.ones(21)
    confidence[6] = 0.49  # index finger chain below required 0.5
    result = apply_finger_merge_policy(geometry, confidence, side="left")
    assert result.fingers_merged_or_ambiguous
    assert result.visibility_states["left_index_finger"] == "ambiguous_do_not_use"
    assert not result.finger_masks["left_index_finger"].any()
    assert result.hand_base.sum() > geometry.hand_base.sum()
    assert result.finger_occlusion_boundary.any()
    assert result.failure_queue_record["queue"] == "failure_queue"
    assert result.failure_queue_record["reason"] == "finger_merge"
    assert "left_index_finger" in result.failure_queue_record["parts"]


def test_adjacent_overlap_merge_and_hand_contact_ownership() -> None:
    shape = (40, 40)
    shared = np.zeros(shape, dtype=bool)
    shared[10:30, 10:20] = True
    fingers = {
        "left_thumb": np.zeros(shape, bool),
        "left_index_finger": shared.copy(),
        "left_middle_finger": shared.copy(),
        "left_ring_finger": np.zeros(shape, bool),
        "left_pinky": np.zeros(shape, bool),
    }
    geometry = HandGeometry(fingers, np.zeros(shape, bool), np.zeros(shape, bool))
    merged = apply_finger_merge_policy(geometry, np.ones(21), side="left")
    assert merged.visibility_states["left_index_finger"] == "ambiguous_do_not_use"
    assert merged.visibility_states["left_middle_finger"] == "ambiguous_do_not_use"

    hand = np.zeros((100, 100), dtype=bool)
    body = np.zeros_like(hand)
    hand[30:60, 30:60] = True
    body[45:80, 45:80] = True
    hand_owned, body_carved, contact = apply_hand_contact_zorder(hand, body)
    assert np.array_equal(hand_owned, hand)
    assert not (hand_owned & body_carved).any()
    assert contact[45:60, 45:60].all()


def test_crop_sam2_plans_use_three_finger_positives_gap_negatives_and_one_embedding() -> None:
    parsing = np.zeros((120, 100), dtype=bool)
    parsing[20:100, 12:90] = True
    geometry = build_hand_geometry(_landmarks(), parsing, side="left")
    plans = build_hand_prompt_plans(geometry, _landmarks(), side="left")
    assert len(plans) == 6
    for name, plan in plans.items():
        if name != "left_hand_base":
            assert len(plan.positive_points) >= 3
            assert any(geometry.finger_gap_regions[y, x] for x, y in plan.negative_points)
    assert len(plans["left_hand_base"].negative_points) >= 5

    priors = {**geometry.finger_masks, "left_hand_base": geometry.hand_base}

    class Provider:
        def __init__(self):
            self.embed_calls = 0
            self.predict_calls = 0

        def embed(self, image, *, model, precision):
            self.embed_calls += 1
            return "crop-embedding"

        def predict(self, embedding, plan, *, multimask_output):
            self.predict_calls += 1
            return [SamCandidate(np.where(priors[plan.label], 1.0, -1.0), 0.9)]

    provider = Provider()
    refined, model = refine_hand_with_sam2(
        provider, np.zeros((120, 100, 3), dtype=np.uint8), geometry, plans
    )
    assert model == "sam2.1_hiera_large"
    assert provider.embed_calls == 1
    assert provider.predict_calls == 6
    assert set(refined) == set(plans)


def test_hand_acceptance_preserves_gaps_pasteback_and_writes_finger_leaderboard(
    tmp_path: Path,
) -> None:
    shape = (64, 64)
    labels = (
        "left_thumb",
        "left_index_finger",
        "left_middle_finger",
        "left_ring_finger",
        "left_pinky",
    )
    gold = {}
    for index, label in enumerate(labels):
        mask = np.zeros(shape, dtype=bool)
        left = 3 + index * 12
        mask[12:54, left : left + 7] = True
        gold[label] = mask
    gaps = np.zeros(shape, dtype=bool)
    for index in range(4):
        gaps[12:54, 10 + index * 12 : 15 + index * 12] = True
    assert not (np.logical_or.reduce(tuple(gold.values())) & gaps).any()
    transform = CropTransform(
        part="left_hand",
        x0=20,
        y0=10,
        scale=1.0,
        crop_size=64,
        source_sha256="a" * 64,
    )
    full_size = (110, 90)
    full_gold = {
        label: reproject_crop_mask(mask.astype(np.uint8) * 255, transform, full_size=full_size)
        for label, mask in gold.items()
    }
    leaderboard = tmp_path / "leaderboard.jsonl"
    result = evaluate_hand_predictions(
        gold,
        gold,
        finger_gap_regions=gaps,
        transform=transform,
        full_gold_masks=full_gold,
        full_size=full_size,
        leaderboard_path=leaderboard,
        run_id="hand_lane_fixture",
        dataset_ref="hand_fixture@v1",
        ckpt_sha="b" * 64,
    )
    assert result["gap_fill_px"] == 0
    assert result["minimum_paste_back_iou"] == 1.0
    assert set(result["per_class"]) == set(labels)
    row = load_leaderboard(leaderboard)[0]
    assert row["group_scores"]["fingers"] == {"iou": 1.0, "bf": 1.0}
    assert set(row["per_class"]) == set(labels)

    filled = {name: mask.copy() for name, mask in gold.items()}
    filled["left_index_finger"][20, 12] = True
    with pytest.raises(HandLaneError, match="inter-finger gaps were filled"):
        evaluate_hand_predictions(
            filled,
            gold,
            finger_gap_regions=gaps,
            transform=transform,
            full_gold_masks=full_gold,
            full_size=full_size,
            leaderboard_path=tmp_path / "must_not_write.jsonl",
            run_id="bad",
            dataset_ref="hand_fixture@v1",
            ckpt_sha="b" * 64,
        )
    assert not (tmp_path / "must_not_write.jsonl").exists()
