import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.io.png_strict import write_binary_mask, write_grayscale
from maskfactory.providers.civitai_auxiliary import (
    AuxiliaryProviderError,
    build_assisted_s05,
    derive_foot_atomic_candidates,
    load_auxiliary_detectors,
    load_auxiliary_s11_evidence,
    load_material_assists,
    render_auxiliary_review_overlay,
    select_auxiliary_detectors,
)

ROOT = Path(__file__).resolve().parents[1]


def test_whole_foot_support_is_split_at_mtp_before_becoming_atomic_candidate():
    support = np.zeros((80, 120), dtype=bool)
    support[25:55, 15:105] = True
    pose = {
        "keypoints": [
            {"index": 20, "x": 100, "y": 32, "confidence": 0.95},
            {"index": 21, "x": 100, "y": 48, "confidence": 0.95},
            {"index": 22, "x": 20, "y": 40, "confidence": 0.95},
        ]
    }

    derived = derive_foot_atomic_candidates(support, side="right", pose_document=pose)

    assert set(derived) == {"right_foot_base", "right_toes"}
    assert not (derived["right_foot_base"] & derived["right_toes"]).any()
    assert np.array_equal(derived["right_foot_base"] | derived["right_toes"], support)
    assert not derived["right_foot_base"][40, 100]
    assert derived["right_toes"][40, 100]


def test_union_foot_support_without_semantic_pose_never_becomes_atomic_candidate():
    support = np.ones((20, 30), dtype=bool)

    assert derive_foot_atomic_candidates(support, side="right", pose_document={}) == {}


def test_runtime_covers_registry_and_uses_tiered_authority():
    policy, detectors = load_auxiliary_detectors(verify_payload_hashes=False)

    assert len(detectors) == 24
    assert policy["vote_requires_promotion_certificate"] is True
    assert {detector.mode for detector in detectors} <= {
        "disabled",
        "shadow",
        "assist",
        "vote",
    }
    assert all(detector.outputs for detector in detectors)
    by_key = {detector.key: detector for detector in detectors}
    assert by_key["hand_detailer_v2_v9c"].mode == "assist"
    assert by_key["foot_shoe_detailer_v04_seg"].mode == "assist"
    assert by_key["person_female_v1"].mode == "disabled"
    assert by_key["foot_anime_yolo11m_v3"].mode == "disabled"


def test_selector_is_context_gated_and_deterministic(tmp_path: Path):
    policy, detectors = load_auxiliary_detectors(verify_payload_hashes=False)
    prior = np.zeros((32, 32), dtype=np.uint8)
    prior[8:16, 8:16] = 255
    write_grayscale(tmp_path / "prior_left_hand_base.png", prior, source_size=(32, 32))
    write_grayscale(tmp_path / "prior_left_foot_base.png", prior, source_size=(32, 32))

    selected = select_auxiliary_detectors(
        detectors,
        priors_dir=tmp_path,
        view="front",
        pose_tags=(),
        crop_labels=("left_hand", "left_foot"),
        maximum=int(policy["max_models_per_instance"]),
    )
    keys = [detector.key for detector in selected]

    assert keys == [detector.key for detector in selected]
    assert "hand_detailer_v2_v9c" in keys
    assert "foot_shoe_detailer_v04_seg" in keys
    assert "rear_pelvis_assdetailer_v2_seg" not in keys
    assert "armpit_2d_yolov8_seg_v1" not in keys


def test_assisted_s05_adds_only_bounded_support(tmp_path: Path):
    priors = tmp_path / "s05"
    auxiliary = tmp_path / "aux"
    output = tmp_path / "assisted"
    priors.mkdir()
    original = np.zeros((40, 40), dtype=np.uint8)
    original[15:22, 15:22] = 255
    write_grayscale(priors / "prior_left_hand_base.png", original, source_size=(40, 40))
    (priors / "prompts.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "plans": [
                    {
                        "label": "left_hand_base",
                        "box_xyxy": [15, 15, 22, 22],
                        "positive_points": [[18, 18]],
                        "negative_points": [],
                        "prior_quality": "low",
                        "multimask_output": True,
                    }
                ],
                "crop_requests": [],
            }
        ),
        encoding="utf-8",
    )
    support = np.zeros((40, 40), dtype=bool)
    support[12:25, 12:25] = True
    support[0:4, 0:4] = True
    write_binary_mask(auxiliary / "normalized/support/hands.png", support, source_size=(40, 40))

    prompts_path = build_assisted_s05(priors_dir=priors, auxiliary_dir=auxiliary, output_dir=output)
    assisted = np.asarray(Image.open(output / "prior_left_hand_base.png")) > 0
    document = json.loads(prompts_path.read_text(encoding="utf-8"))

    assert assisted.sum() > (original > 0).sum()
    assert not assisted[0:4, 0:4].any()
    assert document["auxiliary_authority"] == "proposal_only"
    assert document["auxiliary_assists"][0]["label"] == "left_hand_base"


def test_material_assists_are_strict_binary_named_seeds(tmp_path: Path):
    mask = np.zeros((20, 30), dtype=bool)
    mask[4:12, 5:15] = True
    write_binary_mask(
        tmp_path / "normalized/material_candidate/footwear.png",
        mask,
        source_size=(30, 20),
    )

    loaded = load_material_assists(tmp_path, (20, 30))

    assert set(loaded) == {"footwear"}
    assert loaded["footwear"].dtype == np.bool_
    assert np.array_equal(loaded["footwear"], mask)


def test_exact_specialist_candidate_creates_sam2_prior_and_plan(tmp_path: Path):
    priors = tmp_path / "s05"
    auxiliary = tmp_path / "aux"
    output = tmp_path / "assisted"
    priors.mkdir()
    (priors / "prompts.json").write_text(
        json.dumps({"schema_version": "1.0.0", "plans": [], "crop_requests": []}),
        encoding="utf-8",
    )
    candidate = np.zeros((32, 48), dtype=bool)
    candidate[10:22, 9:21] = True
    write_binary_mask(
        auxiliary / "normalized/part_candidate/left_hand_base.png",
        candidate,
        source_size=(48, 32),
    )

    prompts_path = build_assisted_s05(priors_dir=priors, auxiliary_dir=auxiliary, output_dir=output)
    document = json.loads(prompts_path.read_text(encoding="utf-8"))

    assert (output / "prior_left_hand_base.png").is_file()
    assert [item["label"] for item in document["plans"]] == ["left_hand_base"]
    assert document["plans"][0]["multimask_output"] is True


def test_runtime_config_is_pipeline_hash_pinned():
    pipeline = (ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8")

    assert "civitai_auxiliary_runtime.yaml" in pipeline
    assert "runtime_sha256:" in pipeline
    assert "registry_sha256:" in pipeline


def test_review_overlay_renders_raw_specialist_evidence(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (24, 20), "gray").save(source)
    auxiliary = tmp_path / "auxiliary"
    mask = np.zeros((20, 24), dtype=bool)
    mask[5:12, 6:14] = True
    write_binary_mask(auxiliary / "raw" / "hand" / "detection_000.png", mask)
    (auxiliary / "auxiliary_predictions.json").write_text(
        json.dumps(
            {
                "detectors": [
                    {
                        "key": "hand",
                        "detections": [
                            {
                                "class_name": "hand",
                                "confidence": 0.9,
                                "bbox_xyxy": [6, 5, 14, 12],
                                "mask_path": "raw/hand/detection_000.png",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output = render_auxiliary_review_overlay(
        image_path=source,
        auxiliary_dir=auxiliary,
        output_path=tmp_path / "review.png",
    )
    assert output.is_file()
    assert not np.array_equal(np.asarray(Image.open(output)), np.asarray(Image.open(source)))


def test_s11_loader_validates_part_protected_and_detector_provenance(tmp_path: Path):
    auxiliary = tmp_path / "auxiliary"
    part = np.zeros((20, 24), dtype=bool)
    part[5:12, 6:14] = True
    protected = np.zeros_like(part)
    protected[7:9, 8:10] = True
    part_path = write_binary_mask(auxiliary / "normalized/part_candidate/left_hand_base.png", part)
    protected_path = write_binary_mask(auxiliary / "normalized/protected/nails.png", protected)
    (auxiliary / "auxiliary_predictions.json").write_text(
        json.dumps(
            {
                "authority": "proposal_only",
                "may_write_final_maps": False,
                "source_size": [24, 20],
                "normalized": [
                    part_path.relative_to(auxiliary).as_posix(),
                    protected_path.relative_to(auxiliary).as_posix(),
                ],
                "detectors": [
                    {
                        "key": "hand_detailer",
                        "checkpoint_sha256": "a" * 64,
                        "effective_mode": "assist",
                        "detections": [
                            {
                                "class_name": "hand",
                                "confidence": 0.91,
                                "bbox_xyxy": [6, 5, 14, 12],
                                "kind": "part_candidate",
                                "target": "left_hand_base",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    evidence = load_auxiliary_s11_evidence(auxiliary, (20, 24))
    assert evidence is not None
    assert np.array_equal(evidence.part_candidates["left_hand_base"], part)
    assert np.array_equal(evidence.protected_union, protected)
    assert evidence.label_metadata["left_hand_base"][0]["confidence"] == 0.91


def test_s11_loader_rejects_legacy_whole_hand_support_relabel(tmp_path: Path):
    auxiliary = tmp_path / "auxiliary"
    whole_hand = np.ones((20, 24), dtype=bool)
    part_path = write_binary_mask(
        auxiliary / "normalized/part_candidate/left_hand_base.png", whole_hand
    )
    (auxiliary / "auxiliary_predictions.json").write_text(
        json.dumps(
            {
                "authority": "proposal_only",
                "may_write_final_maps": False,
                "source_size": [24, 20],
                "normalized": [part_path.relative_to(auxiliary).as_posix()],
                "detectors": [
                    {
                        "key": "legacy_hand_support",
                        "detections": [
                            {
                                "kind": "support",
                                "target": "hands",
                                "resolved_part_target": "left_hand_base",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AuxiliaryProviderError, match="union support"):
        load_auxiliary_s11_evidence(auxiliary, (20, 24))


def test_s11_loads_whole_hand_as_union_support_but_not_atomic_candidate(tmp_path: Path):
    auxiliary = tmp_path / "auxiliary"
    whole_hand = np.zeros((20, 24), dtype=bool)
    whole_hand[4:16, 5:19] = True
    raw_path = write_binary_mask(auxiliary / "raw/hand/detection_000.png", whole_hand)
    support_path = write_binary_mask(auxiliary / "normalized/support/hands.png", whole_hand)
    (auxiliary / "auxiliary_predictions.json").write_text(
        json.dumps(
            {
                "authority": "proposal_only",
                "may_write_final_maps": False,
                "source_size": [24, 20],
                "normalized": [support_path.relative_to(auxiliary).as_posix()],
                "detectors": [
                    {
                        "key": "hand_support",
                        "checkpoint_sha256": "b" * 64,
                        "effective_mode": "assist",
                        "detections": [
                            {
                                "kind": "support",
                                "target": "hands",
                                "class_name": "hand",
                                "confidence": 0.9,
                                "bbox_xyxy": [5, 4, 19, 16],
                                "mask_path": raw_path.relative_to(auxiliary).as_posix(),
                                "resolved_union_target": "left_hand",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    evidence = load_auxiliary_s11_evidence(auxiliary, (20, 24))

    assert evidence is not None and not evidence.part_candidates
    assert set(evidence.support_candidates) == {
        "left_hand_base",
        "left_thumb",
        "left_index_finger",
        "left_middle_finger",
        "left_ring_finger",
        "left_pinky",
    }
    assert all(np.array_equal(mask, whole_hand) for mask in evidence.support_candidates.values())
    assert evidence.support_metadata["left_hand_base"][0]["authority"].endswith(
        "not_atomic_candidate"
    )
