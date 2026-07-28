from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from maskfactory.providers.contracts import BoxProposal, PoseProvider, ProviderIdentity
from maskfactory.providers.rtm_pose import (
    COCO_WHOLEBODY_NAMES,
    CROWDPOSE_NAMES,
    RTM_RUNTIME_FINGERPRINT,
    RTM_SOURCE_COMMIT,
    RTM_VARIANTS,
    RtmPoseProvider,
    RtmPoseProviderError,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _executor_for(
    variant: str,
    image_path: Path,
    *,
    boxes: np.ndarray,
    tamper: str | None = None,
):
    vocabulary = RTM_VARIANTS[variant]["joint_vocabulary"]
    joint_count = len(vocabulary)
    keypoints = np.zeros((len(boxes), joint_count, 2), dtype=np.float32)
    confidence = np.full((len(boxes), joint_count), 0.8, dtype=np.float32)
    native_scores = np.full(
        (len(boxes), joint_count),
        4.0 if variant == "rtmw_x" else 0.8,
        dtype=np.float32,
    )
    for index, box in enumerate(boxes):
        keypoints[index, :, 0] = np.linspace(box[0] + 1, box[2] - 1, joint_count)
        keypoints[index, :, 1] = np.linspace(box[1] + 1, box[3] - 1, joint_count)

    def execute(argv, timeout):
        assert timeout == 180
        output_path = Path(argv[argv.index("--output") + 1])
        person_box = [
            float(value)
            for value in argv[argv.index("--person-box") + 1 : argv.index("--person-box") + 5]
        ]
        np.savez_compressed(
            output_path,
            keypoints=keypoints,
            confidence=confidence,
            native_scores=native_scores,
            bboxes=boxes,
        )
        payload = hashlib.sha256(
            keypoints.tobytes() + native_scores.tobytes() + boxes.tobytes()
        ).hexdigest()
        report = {
            "variant": variant,
            "source_commit": RTM_SOURCE_COMMIT,
            "runtime_fingerprint": RTM_RUNTIME_FINGERPRINT,
            "checkpoint": {"sha256": RTM_VARIANTS[variant]["checkpoint_sha256"]},
            "config": {"sha256": RTM_VARIANTS[variant]["config_sha256"]},
            "image": {"sha256": _sha256(image_path)},
            "person_box_xyxy": person_box,
            "joint_vocabulary": list(vocabulary),
            "confidence_transform": RTM_VARIANTS[variant]["confidence_transform"],
            "deterministic": True,
            "repeats": 2,
            "person_count": len(boxes),
            "keypoints_shape": list(keypoints.shape),
            "payload_sha256": payload,
            "output_npz_sha256": _sha256(output_path),
        }
        if tamper:
            report[tamper] = "tampered"
        return subprocess.CompletedProcess(argv, 0, json.dumps(report), "")

    return execute


def test_rtmw_exact_133_vocabulary_and_character_side_contract(tmp_path: Path) -> None:
    image = tmp_path / "adult.png"
    image.write_bytes(b"fixture")
    box = BoxProposal((10, 20, 110, 220), 0.9, "person", "adult-0")
    provider = RtmPoseProvider(
        "rtmw_x",
        executor=_executor_for(
            "rtmw_x", image, boxes=np.asarray([box.bbox_xyxy], dtype=np.float32)
        ),
    )

    assert isinstance(provider, PoseProvider)
    result = provider.infer_pose(image, person_box=box)

    assert result["provider_key"] == "rtmw_x"
    assert result["joint_vocabulary"] == COCO_WHOLEBODY_NAMES
    assert result["keypoints"].shape == (133, 3)
    assert result["side_semantics"] == "character_anatomical_left_right"
    assert result["character_side_indices"]["left_shoulder"] == 5
    assert result["character_side_indices"]["right_shoulder"] == 6
    assert result["character_side_indices"]["left_hand_0"] == 91
    assert result["character_side_indices"]["right_hand_0"] == 112
    assert np.all((result["keypoints"][:, 2] >= 0) & (result["keypoints"][:, 2] <= 1))


def test_rtmo_crowd_assignment_is_unique_for_distinct_character_boxes(
    tmp_path: Path,
) -> None:
    image = tmp_path / "adult-crowd.png"
    image.write_bytes(b"crowd-fixture")
    boxes = np.asarray(
        [[0, 0, 40, 100], [50, 0, 90, 100], [95, 5, 125, 95]],
        dtype=np.float32,
    )
    provider = RtmPoseProvider(
        "rtmo_crowd", executor=_executor_for("rtmo_crowd", image, boxes=boxes)
    )

    first = provider.infer_pose(
        image, person_box=BoxProposal((1, 1, 39, 99), 0.9, "person", "adult-0")
    )
    second = provider.infer_pose(
        image, person_box=BoxProposal((51, 1, 89, 99), 0.9, "person", "adult-1")
    )

    assert first["joint_vocabulary"] == CROWDPOSE_NAMES
    assert first["keypoints"].shape == (14, 3)
    assert first["candidate_count"] == 3
    assert first["selected_candidate_index"] == 0
    assert second["selected_candidate_index"] == 1
    assert first["instance_key"] != second["instance_key"]
    assert first["assignment_iou"] > 0.8
    assert second["assignment_iou"] > 0.8


def test_rtmo_rejects_unowned_crowd_candidate(tmp_path: Path) -> None:
    image = tmp_path / "adult-crowd.png"
    image.write_bytes(b"crowd-fixture")
    provider = RtmPoseProvider(
        "rtmo_crowd",
        crowd_assignment_iou=0.1,
        executor=_executor_for(
            "rtmo_crowd",
            image,
            boxes=np.asarray([[0, 0, 20, 50]], dtype=np.float32),
        ),
    )
    with pytest.raises(RtmPoseProviderError, match="do not overlap"):
        provider.infer_pose(
            image,
            person_box=BoxProposal((100, 100, 150, 200), 0.9, "person", "adult-x"),
        )


class _FallbackPose:
    identity = ProviderIdentity(
        "dwpose_133", "pose_provider", "dwpose", "incumbent", "incumbent-runtime"
    )

    def infer_pose(self, image_path: Path, *, person_box: BoxProposal):
        return {
            "provider_key": self.identity.provider_key,
            "person_box": person_box.bbox_xyxy,
        }


def test_rtm_failure_falls_back_without_stealing_incumbent_identity(tmp_path: Path) -> None:
    image = tmp_path / "adult.png"
    image.write_bytes(b"fixture")

    def fail(argv, timeout):
        return subprocess.CompletedProcess(argv, 2, "", "cuda oom")

    provider = RtmPoseProvider("rtmw_x", executor=fail, fallback=_FallbackPose())
    result = provider.infer_pose(
        image,
        person_box=BoxProposal((0, 0, 20, 30), 0.9, "person", "adult-0"),
    )
    assert result["provider_key"] == "dwpose_133"


def test_rtm_provider_fails_closed_on_runtime_provenance_drift(tmp_path: Path) -> None:
    image = tmp_path / "adult.png"
    image.write_bytes(b"fixture")
    box = BoxProposal((0, 0, 20, 30), 0.9, "person", "adult-0")
    provider = RtmPoseProvider(
        "rtmw_x",
        executor=_executor_for(
            "rtmw_x",
            image,
            boxes=np.asarray([box.bbox_xyxy], dtype=np.float32),
            tamper="runtime_fingerprint",
        ),
    )
    with pytest.raises(RtmPoseProviderError, match="provenance mismatch"):
        provider.infer_pose(image, person_box=box)
