import json
import os
from pathlib import Path

import numpy as np
import pytest
import yaml

from maskfactory.stages.s04_pose import (
    PoseCandidate,
    PoseError,
    assign_pose_candidates_to_instances,
    classify_view,
    evaluate_pose_tags,
    infer_dwpose_candidates,
    infer_dwpose_candidates_wsl,
    pose_metrics,
    process_pose_candidates,
    run_s04_production,
)


def _keypoints(confidence: float = 0.9) -> np.ndarray:
    points = np.zeros((133, 3), dtype=np.float64)
    points[:, 2] = confidence
    coordinates = {
        0: (50, 15),
        5: (35, 30),
        6: (65, 30),
        7: (30, 50),
        8: (70, 50),
        9: (25, 72),
        10: (75, 72),
        11: (40, 65),
        12: (60, 65),
        13: (38, 82),
        14: (62, 82),
        15: (35, 100),
        16: (65, 100),
    }
    for index, (x, y) in coordinates.items():
        points[index, :2] = x, y
    return points


def _rules() -> dict:
    return yaml.safe_load(Path("configs/pipeline.yaml").read_text())["pose_tags_rules"]


def test_s04_selects_instance_pose_suppresses_cosubject_and_serializes_133(
    tmp_path: Path,
) -> None:
    target = PoseCandidate((10, 5, 90, 105), _keypoints())
    other_points = _keypoints()
    other_points[:, 0] += 200
    other = PoseCandidate((200, 5, 290, 105), other_points)

    result = process_pose_candidates(
        [other, target],
        instance_bbox_xyxy=(0, 0, 100, 110),
        output_dir=tmp_path,
        pose_tag_rules=_rules(),
    )

    assert result.selected_candidate_index == 1
    assert result.suppressed_candidate_indices == (0,)
    assert result.view == "front"
    assert not result.pose_degraded
    assert "arms_down" in result.pose_tags
    assert "walking" in result.pose_tags
    document = json.loads(result.pose_path.read_text())
    assert document["format"] == "COCO-WholeBody-133"
    assert len(document["keypoints"]) == 133
    assert document["instance_ownership"]["suppressed_candidate_indices"] == [0]
    assert document["geometry_prior_mode"] == "pose_and_parsing"


def test_global_pose_assignment_is_unique_across_overlapping_promoted_people() -> None:
    candidates = [
        PoseCandidate((0, 0, 70, 100), _keypoints()),
        PoseCandidate((45, 0, 100, 100), _keypoints()),
    ]
    promoted = {0: (0, 0, 65, 100), 1: (35, 0, 100, 100)}
    assignments = assign_pose_candidates_to_instances(candidates, promoted)
    assert assignments == {0: 0, 1: 1}
    assert len(set(assignments.values())) == 2


def test_s04_degraded_path_forces_parsing_only_and_careful_review(tmp_path: Path) -> None:
    points = _keypoints(confidence=0.0)
    points[:9, 2] = 0.9  # 9/17 = 52.9%, below the 60% contract

    result = process_pose_candidates(
        [PoseCandidate((0, 0, 100, 110), points)],
        instance_bbox_xyxy=(0, 0, 100, 110),
        output_dir=tmp_path,
        pose_tag_rules=_rules(),
    )

    assert result.pose_degraded and result.careful_review
    document = json.loads(result.pose_path.read_text())
    assert document["geometry_prior_mode"] == "parsing_only"
    assert document["review_tags"] == ["careful_review"]
    assert document["body_keypoint_fraction"] == pytest.approx(9 / 17)


def test_s04_view_classifier_covers_front_back_profile_and_three_quarter() -> None:
    front = _keypoints()
    back = front.copy()
    back[0, 2] = 0.0
    profile = front.copy()
    profile[5, 0], profile[6, 0] = 48, 52
    profile[5, 2], profile[11, 2] = 0.95, 0.95
    profile[6, 2], profile[12, 2] = 0.4, 0.4
    three_quarter = front.copy()
    three_quarter[5, 2], three_quarter[11, 2] = 0.95, 0.95
    three_quarter[6, 2], three_quarter[12, 2] = 0.6, 0.6

    assert classify_view(front) == "front"
    assert classify_view(back) == "back"
    assert classify_view(profile) == "left_profile"
    assert classify_view(three_quarter) == "left_3_4"
    assert classify_view(front, densepose_back_ratio=0.8) == "back"


def test_pose_tags_use_configured_operator_table() -> None:
    rules = {
        "high": {"metric": "value", "operator": "gt", "threshold": 1},
        "low": {"metric": "value", "operator": "lt", "threshold": 0},
    }
    assert evaluate_pose_tags({"value": 2.0}, rules) == ("high",)
    with pytest.raises(PoseError, match="invalid pose tag rule"):
        evaluate_pose_tags(
            {"value": 2.0}, {"bad": {"metric": "x", "operator": "eq", "threshold": 1}}
        )


def test_pose_metric_geometry_covers_crossing_bend_and_lying() -> None:
    points = _keypoints()
    points[9, :2] = (55, 50)
    points[10, :2] = (45, 50)
    points[5, :2], points[6, :2] = (20, 50), (30, 50)
    points[11, :2], points[12, :2] = (70, 50), (80, 50)
    points[13, :2], points[15, :2] = (70, 70), (90, 70)
    points[14, :2], points[16, :2] = (80, 70), (100, 70)

    metrics = pose_metrics(points)

    assert metrics["wrist_opposite_torso_overlap"] == 1.0
    assert metrics["mean_hip_knee_ankle_angle_deg"] == pytest.approx(90)
    assert metrics["shoulder_hip_axis_from_horizontal_deg"] == pytest.approx(0)
    tags = evaluate_pose_tags(metrics, _rules())
    assert {"arms_crossed", "seated_or_crouched", "lying"} <= set(tags)


def test_s04_rejects_bad_shape_and_nonoverlapping_candidates(tmp_path: Path) -> None:
    with pytest.raises(PoseError, match="133x3"):
        process_pose_candidates(
            [PoseCandidate((0, 0, 10, 10), np.zeros((17, 3)))],
            instance_bbox_xyxy=(0, 0, 10, 10),
            output_dir=tmp_path,
            pose_tag_rules={},
        )
    with pytest.raises(PoseError, match="overlaps"):
        process_pose_candidates(
            [PoseCandidate((20, 20, 30, 30), _keypoints())],
            instance_bbox_xyxy=(0, 0, 10, 10),
            output_dir=tmp_path,
            pose_tag_rules={},
        )


def test_dwpose_onnx_adapter_decodes_yolox_and_simcc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import onnxruntime
    from PIL import Image

    image_path = tmp_path / "person.png"
    Image.new("RGB", (200, 240), "white").save(image_path)
    detector_path = tmp_path / "det.onnx"
    pose_path = tmp_path / "pose.onnx"
    detector_path.write_bytes(b"det")
    pose_path.write_bytes(b"pose")

    class Input:
        name = "input"

    class Session:
        def __init__(self, path, providers):
            self.pose = str(path).endswith("pose.onnx")

        def get_inputs(self):
            return [Input()]

        def run(self, outputs, inputs):
            if not self.pose:
                raw = np.zeros((1, 8400, 85), dtype=np.float32)
                raw[0, 0, :6] = [10, 10, np.log(10), np.log(10), 0.9, 0.9]
                return [raw]
            x = np.zeros((1, 133, 576), dtype=np.float32)
            y = np.zeros((1, 133, 768), dtype=np.float32)
            x[:, :, 288] = 0.9
            y[:, :, 384] = 0.8
            return [x, y]

    monkeypatch.setattr(onnxruntime, "get_available_providers", lambda: ["CPUExecutionProvider"])
    monkeypatch.setattr(onnxruntime, "InferenceSession", Session)
    with pytest.raises(PoseError, match="CUDAExecutionProvider"):
        infer_dwpose_candidates(
            image_path,
            detector_checkpoint=detector_path,
            pose_checkpoint=pose_path,
        )
    candidates = infer_dwpose_candidates(
        image_path,
        detector_checkpoint=detector_path,
        pose_checkpoint=pose_path,
        require_cuda=False,
    )
    assert len(candidates) == 1
    assert candidates[0].keypoints.shape == (133, 3)
    assert np.allclose(candidates[0].keypoints[:, 2], 0.8)
    assert np.isfinite(candidates[0].keypoints).all()


def test_dwpose_refuses_silent_cuda_session_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import onnxruntime
    from PIL import Image

    image = tmp_path / "person.png"
    detector = tmp_path / "det.onnx"
    pose = tmp_path / "pose.onnx"
    Image.new("RGB", (20, 20), "white").save(image)
    detector.write_bytes(b"fixture")
    pose.write_bytes(b"fixture")

    class Session:
        def __init__(self, path, providers):
            pass

        def get_providers(self):
            return ["CPUExecutionProvider"]

    monkeypatch.setattr(
        onnxruntime,
        "get_available_providers",
        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    monkeypatch.setattr(onnxruntime, "InferenceSession", Session)

    with pytest.raises(PoseError, match="did not bind CUDAExecutionProvider"):
        infer_dwpose_candidates(
            image,
            detector_checkpoint=detector,
            pose_checkpoint=pose,
            require_cuda=True,
        )


@pytest.mark.skipif(os.name != "nt", reason="WSL bridge adapter requires a Windows host")
def test_dwpose_wsl_bridge_validates_pinned_archive_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_path = tmp_path / "person.png"
    from PIL import Image

    Image.new("RGB", (200, 240), "white").save(image_path)
    detector = tmp_path / "yolox_l.onnx"
    pose = tmp_path / "dw-ll_ucoco_384.onnx"
    detector.write_bytes(b"detector fixture")
    pose.write_bytes(b"pose fixture")

    def windows_path(wsl_path: str) -> Path:
        assert wsl_path.startswith("/mnt/c/")
        return Path("C:/" + wsl_path.removeprefix("/mnt/c/"))

    def fake_run(command, **kwargs):
        output = windows_path(command[command.index("--output") + 1])
        boxes = np.array([[10, 20, 100, 220]], dtype=np.float32)
        keypoints = np.zeros((1, 133, 3), dtype=np.float32)
        keypoints[:, :, 0] = 50
        keypoints[:, :, 1] = 100
        keypoints[:, :, 2] = 0.9
        np.savez_compressed(output, bboxes=boxes, keypoints=keypoints)

        class Process:
            returncode = 0
            stderr = ""
            stdout = json.dumps(
                {
                    "protocol_version": 1,
                    "detector_sha256": (
                        "7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411"
                    ),
                    "pose_sha256": (
                        "724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843"
                    ),
                    "provider": "CUDAExecutionProvider",
                    "candidate_count": 1,
                    "bboxes_shape": [1, 4],
                    "keypoints_shape": [1, 133, 3],
                    "detection_confidence": 0.3,
                    "nms_iou": 0.45,
                    "device": "NVIDIA fixture",
                }
            )

        return Process()

    monkeypatch.setattr("maskfactory.stages.s04_pose.subprocess.run", fake_run)
    work = tmp_path / "work"
    candidates = infer_dwpose_candidates_wsl(
        image_path,
        detector_checkpoint=detector,
        pose_checkpoint=pose,
        work_dir=work,
    )

    assert len(candidates) == 1
    assert candidates[0].keypoints.shape == (133, 3)
    assert not list(work.iterdir())


def test_s04_production_uses_authoritative_wsl_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "source.png"
    detector = tmp_path / "det.onnx"
    pose = tmp_path / "pose.onnx"
    image.write_bytes(b"fixture")
    detector.write_bytes(b"fixture")
    pose.write_bytes(b"fixture")
    called = {}

    def fake_wsl(*args, **kwargs):
        called.update(kwargs)
        return [PoseCandidate((0, 0, 100, 110), _keypoints())]

    monkeypatch.setattr("maskfactory.stages.s04_pose.infer_dwpose_candidates_wsl", fake_wsl)
    result = run_s04_production(
        image,
        instance_bbox_xyxy=(0, 0, 100, 110),
        detector_checkpoint=detector,
        pose_checkpoint=pose,
        output_dir=tmp_path / "out",
        pose_tag_rules=_rules(),
    )

    assert result.pose_path.is_file()
    assert called["work_dir"] == tmp_path / "out/provider_work"
