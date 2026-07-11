"""S04 pose ownership, serialization, view classification, and pose tags."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy.optimize import linear_sum_assignment


class PoseError(ValueError):
    """Pose output violates the COCO-WholeBody S04 contract."""


@dataclass(frozen=True)
class PoseCandidate:
    bbox_xyxy: tuple[float, float, float, float]
    keypoints: np.ndarray  # 133 x (x, y, confidence)


@dataclass(frozen=True)
class PoseResult:
    pose_path: Path
    view: str
    pose_tags: tuple[str, ...]
    pose_degraded: bool
    careful_review: bool
    body_keypoint_fraction: float
    selected_candidate_index: int
    suppressed_candidate_indices: tuple[int, ...]
    metrics: dict[str, float]


BODY_INDICES = tuple(range(17))
NOSE, LEFT_SHOULDER, RIGHT_SHOULDER = 0, 5, 6
LEFT_ELBOW, RIGHT_ELBOW, LEFT_WRIST, RIGHT_WRIST = 7, 8, 9, 10
LEFT_HIP, RIGHT_HIP, LEFT_KNEE, RIGHT_KNEE = 11, 12, 13, 14
LEFT_ANKLE, RIGHT_ANKLE = 15, 16


def infer_dwpose_candidates(
    image_path: Path,
    *,
    detector_checkpoint: Path,
    pose_checkpoint: Path,
    require_cuda: bool = True,
    detection_confidence: float = 0.3,
    nms_iou: float = 0.45,
) -> list[PoseCandidate]:
    """Run pinned YOLOX-L + DWPose-133 ONNX with strict provider/output contracts."""
    try:
        import cv2
        import onnxruntime as ort
    except ImportError as exc:
        raise PoseError(f"DWPose runtime unavailable: {exc}") from exc
    available = ort.get_available_providers()
    if require_cuda and "CUDAExecutionProvider" not in available:
        raise PoseError("DWPose production requires ONNX CUDAExecutionProvider")
    providers = [
        provider
        for provider in ("CUDAExecutionProvider", "CPUExecutionProvider")
        if provider in available
    ]
    try:
        detector = ort.InferenceSession(str(detector_checkpoint), providers=providers)
        pose = ort.InferenceSession(str(pose_checkpoint), providers=providers)
    except Exception as exc:  # noqa: BLE001 - normalize ONNX provider boundary
        raise PoseError(f"DWPose session creation failed: {exc}") from exc
    with Image.open(image_path) as opened:
        rgb = np.asarray(opened.convert("RGB"))
    boxes = _yolox_people(
        detector,
        rgb[:, :, ::-1],
        confidence=detection_confidence,
        nms_iou=nms_iou,
        cv2=cv2,
    )
    candidates = []
    for box in boxes:
        tensor, inverse = _pose_input(rgb, tuple(box), cv2=cv2)
        outputs = pose.run(None, {pose.get_inputs()[0].name: tensor})
        if len(outputs) != 2:
            raise PoseError("DWPose pose model must return simcc_x and simcc_y")
        simcc_x, simcc_y = (np.asarray(output) for output in outputs)
        if simcc_x.shape[:2] != (1, 133) or simcc_y.shape[:2] != (1, 133):
            raise PoseError("DWPose SimCC output must contain 133 keypoints")
        x_indices = simcc_x[0].argmax(axis=1).astype(np.float32) / 2.0
        y_indices = simcc_y[0].argmax(axis=1).astype(np.float32) / 2.0
        confidences = np.minimum(simcc_x[0].max(axis=1), simcc_y[0].max(axis=1))
        points = np.stack((x_indices, y_indices, np.ones(133)), axis=1)
        original = points @ inverse.T
        keypoints = np.column_stack((original[:, :2], np.clip(confidences, 0.0, 1.0)))
        candidates.append(PoseCandidate(tuple(float(value) for value in box), keypoints))
    return candidates


def run_s04_production(
    image_path: Path,
    *,
    instance_bbox_xyxy: tuple[float, float, float, float],
    detector_checkpoint: Path,
    pose_checkpoint: Path,
    output_dir: Path,
    pose_tag_rules: dict[str, dict[str, Any]],
    require_cuda: bool = True,
    promoted_instance_bboxes: dict[int, tuple[float, float, float, float]] | None = None,
    person_index: int | None = None,
) -> PoseResult:
    """Execute real DWPose then apply instance ownership/view/tag policy."""
    candidates = infer_dwpose_candidates(
        image_path,
        detector_checkpoint=detector_checkpoint,
        pose_checkpoint=pose_checkpoint,
        require_cuda=require_cuda,
    )
    return process_pose_candidates(
        candidates,
        instance_bbox_xyxy=instance_bbox_xyxy,
        output_dir=output_dir,
        pose_tag_rules=pose_tag_rules,
        promoted_instance_bboxes=promoted_instance_bboxes,
        person_index=person_index,
    )


def _yolox_people(
    session, bgr: np.ndarray, *, confidence: float, nms_iou: float, cv2
) -> np.ndarray:
    height, width = bgr.shape[:2]
    ratio = min(640 / height, 640 / width)
    resized = cv2.resize(bgr, (int(width * ratio), int(height * ratio)))
    padded = np.full((640, 640, 3), 114, dtype=np.uint8)
    padded[: resized.shape[0], : resized.shape[1]] = resized
    tensor = np.ascontiguousarray(padded.transpose(2, 0, 1)[None], dtype=np.float32)
    raw = np.asarray(session.run(None, {session.get_inputs()[0].name: tensor})[0])[0]
    if raw.shape != (8400, 85):
        raise PoseError(f"YOLOX output shape mismatch: {raw.shape}")
    grids, strides = [], []
    for stride in (8, 16, 32):
        size = 640 // stride
        y, x = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
        grids.append(np.stack((x, y), axis=2).reshape(-1, 2))
        strides.append(np.full((size * size, 1), stride))
    grid = np.concatenate(grids)
    stride = np.concatenate(strides)
    centers = (raw[:, :2] + grid) * stride
    sizes = np.exp(np.clip(raw[:, 2:4], -20, 20)) * stride
    boxes = np.column_stack((centers - sizes / 2, centers + sizes / 2)) / ratio
    scores = raw[:, 4] * raw[:, 5]
    keep = scores >= confidence
    boxes, scores = boxes[keep], scores[keep]
    boxes[:, (0, 2)] = boxes[:, (0, 2)].clip(0, width)
    boxes[:, (1, 3)] = boxes[:, (1, 3)].clip(0, height)
    order = scores.argsort()[::-1]
    selected = []
    while len(order):
        current = int(order[0])
        selected.append(current)
        if len(order) == 1:
            break
        remaining = order[1:]
        overlaps = np.array(
            [_bbox_iou(tuple(boxes[current]), tuple(boxes[index])) for index in remaining]
        )
        order = remaining[overlaps <= nms_iou]
    return boxes[selected].astype(np.float32)


def _pose_input(rgb: np.ndarray, bbox: tuple[float, float, float, float], *, cv2):
    left, top, right, bottom = bbox
    center = np.array([(left + right) / 2, (top + bottom) / 2], dtype=np.float32)
    width, height = (right - left) * 1.25, (bottom - top) * 1.25
    aspect = 288 / 384
    if width / max(height, 1) > aspect:
        height = width / aspect
    else:
        width = height * aspect
    source = np.array(
        [
            center,
            center + [0, -height / 2],
            center + [width / 2, 0],
        ],
        dtype=np.float32,
    )
    destination = np.array([[144, 192], [144, 0], [288, 192]], dtype=np.float32)
    transform = cv2.getAffineTransform(source, destination)
    inverse = cv2.invertAffineTransform(transform)
    crop = cv2.warpAffine(rgb, transform, (288, 384), flags=cv2.INTER_LINEAR)
    tensor = crop.astype(np.float32) / 255.0
    tensor = (tensor - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
    return np.ascontiguousarray(tensor.transpose(2, 0, 1)[None], dtype=np.float32), inverse


def process_pose_candidates(
    candidates: list[PoseCandidate],
    *,
    instance_bbox_xyxy: tuple[float, float, float, float],
    output_dir: Path,
    pose_tag_rules: dict[str, dict[str, Any]],
    confidence_min: float = 0.3,
    degraded_body_fraction: float = 0.6,
    densepose_back_ratio: float | None = None,
    promoted_instance_bboxes: dict[int, tuple[float, float, float, float]] | None = None,
    person_index: int | None = None,
) -> PoseResult:
    """Select the pose owned by this instance and suppress all co-subject poses."""
    if not candidates:
        raise PoseError("DWPose returned no candidates")
    validated = [_validate_candidate(candidate) for candidate in candidates]
    ownership = [_bbox_iou(candidate.bbox_xyxy, instance_bbox_xyxy) for candidate in validated]
    if promoted_instance_bboxes is not None:
        if person_index is None or person_index not in promoted_instance_bboxes:
            raise PoseError("global pose assignment requires the target promoted person_index")
        assignments = assign_pose_candidates_to_instances(validated, promoted_instance_bboxes)
        if person_index not in assignments:
            raise PoseError("no pose candidate assigned to the promoted instance")
        selected_index = assignments[person_index]
    else:
        selected_index = max(range(len(validated)), key=lambda index: (ownership[index], -index))
    if ownership[selected_index] <= 0:
        raise PoseError("no pose candidate overlaps the instance bbox")
    selected = validated[selected_index]
    keypoints = selected.keypoints
    confident_body = keypoints[list(BODY_INDICES), 2] >= confidence_min
    body_fraction = float(confident_body.mean())
    degraded = body_fraction < degraded_body_fraction
    view = classify_view(
        keypoints,
        confidence_min=confidence_min,
        densepose_back_ratio=densepose_back_ratio,
    )
    metrics = pose_metrics(keypoints, confidence_min=confidence_min)
    tags = evaluate_pose_tags(metrics, pose_tag_rules)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pose_path = output_dir / "pose133.json"
    document = {
        "schema_version": "1.0.0",
        "format": "COCO-WholeBody-133",
        "bbox_xyxy": list(selected.bbox_xyxy),
        "keypoints": [
            {
                "index": index,
                "x": float(point[0]),
                "y": float(point[1]),
                "confidence": float(point[2]),
            }
            for index, point in enumerate(keypoints)
        ],
        "view": view,
        "pose_tags": list(tags),
        "pose_degraded": degraded,
        "geometry_prior_mode": "parsing_only" if degraded else "pose_and_parsing",
        "review_tags": ["careful_review"] if degraded else [],
        "body_keypoint_fraction": body_fraction,
        "instance_ownership": {
            "selected_candidate_index": selected_index,
            "selected_bbox_iou": ownership[selected_index],
            "suppressed_candidate_indices": [
                index for index in range(len(candidates)) if index != selected_index
            ],
        },
        "metrics": {
            name: value if math.isfinite(value) else None for name, value in metrics.items()
        },
    }
    pose_path.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return PoseResult(
        pose_path,
        view,
        tags,
        degraded,
        degraded,
        body_fraction,
        selected_index,
        tuple(index for index in range(len(candidates)) if index != selected_index),
        metrics,
    )


def assign_pose_candidates_to_instances(
    candidates: list[PoseCandidate],
    promoted_instance_bboxes: dict[int, tuple[float, float, float, float]],
) -> dict[int, int]:
    """Globally assign pose detections to promoted people with unique maximum-IoU ownership."""
    if not candidates or not promoted_instance_bboxes:
        raise PoseError("global pose assignment requires candidates and promoted instances")
    instance_ids = sorted(promoted_instance_bboxes)
    scores = np.array(
        [
            [
                _bbox_iou(candidate.bbox_xyxy, promoted_instance_bboxes[index])
                for candidate in candidates
            ]
            for index in instance_ids
        ],
        dtype=np.float64,
    )
    rows, columns = linear_sum_assignment(-scores)
    assignments = {}
    for row, column in zip(rows.tolist(), columns.tolist(), strict=True):
        if scores[row, column] > 0:
            assignments[instance_ids[row]] = column
    return assignments


def classify_view(
    keypoints: np.ndarray,
    *,
    confidence_min: float = 0.3,
    densepose_back_ratio: float | None = None,
) -> str:
    """Classify six stable views from face visibility and torso asymmetry."""
    points = np.asarray(keypoints, dtype=np.float64)
    nose_visible = points[NOSE, 2] >= confidence_min
    if densepose_back_ratio is not None and not 0 <= densepose_back_ratio <= 1:
        raise PoseError("densepose_back_ratio must be in 0..1")
    if densepose_back_ratio is not None and densepose_back_ratio >= 0.65:
        return "back"
    left_conf = min(points[LEFT_SHOULDER, 2], points[LEFT_HIP, 2])
    right_conf = min(points[RIGHT_SHOULDER, 2], points[RIGHT_HIP, 2])
    shoulder_span = abs(points[LEFT_SHOULDER, 0] - points[RIGHT_SHOULDER, 0])
    torso_height = max(
        1.0,
        abs(
            (points[LEFT_HIP, 1] + points[RIGHT_HIP, 1]) / 2
            - (points[LEFT_SHOULDER, 1] + points[RIGHT_SHOULDER, 1]) / 2
        ),
    )
    side = "left" if left_conf > right_conf else "right"
    if shoulder_span / torso_height < 0.35 or min(left_conf, right_conf) < confidence_min:
        return f"{side}_profile"
    asymmetry = abs(left_conf - right_conf)
    if asymmetry >= 0.2:
        return f"{side}_3_4"
    return "front" if nose_visible else "back"


def pose_metrics(keypoints: np.ndarray, *, confidence_min: float = 0.3) -> dict[str, float]:
    """Calculate the exact scalar inputs consumed by pipeline pose-tag rules."""
    points = np.asarray(keypoints, dtype=np.float64)
    shoulder_y = _mean_coordinate(points, (LEFT_SHOULDER, RIGHT_SHOULDER), 1, confidence_min)
    hip_y = _mean_coordinate(points, (LEFT_HIP, RIGHT_HIP), 1, confidence_min)
    torso_height = max(1.0, abs(hip_y - shoulder_y))
    wrist_values = [
        (shoulder_y - points[index, 1]) / torso_height
        for index in (LEFT_WRIST, RIGHT_WRIST)
        if points[index, 2] >= confidence_min
    ]
    vertical_fraction = max(wrist_values) if wrist_values else float("nan")
    torso_box = _box_from_points(
        points, (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP), confidence_min
    )
    cross_hits = []
    for wrist, opposite_shoulder in ((LEFT_WRIST, RIGHT_SHOULDER), (RIGHT_WRIST, LEFT_SHOULDER)):
        if points[wrist, 2] >= confidence_min and torso_box is not None:
            x, y = points[wrist, :2]
            mid_x = (torso_box[0] + torso_box[2]) / 2
            on_opposite_half = x <= mid_x if opposite_shoulder == LEFT_SHOULDER else x >= mid_x
            cross_hits.append(float(_point_in_box(x, y, torso_box) and on_opposite_half))
    knee_angles = [
        _joint_angle(points, hip, knee, ankle, confidence_min)
        for hip, knee, ankle in (
            (LEFT_HIP, LEFT_KNEE, LEFT_ANKLE),
            (RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE),
        )
    ]
    knee_angles = [angle for angle in knee_angles if math.isfinite(angle)]
    shoulder_mid = _mean_point(points, (LEFT_SHOULDER, RIGHT_SHOULDER), confidence_min)
    hip_mid = _mean_point(points, (LEFT_HIP, RIGHT_HIP), confidence_min)
    axis_angle = (
        abs(math.degrees(math.atan2(hip_mid[1] - shoulder_mid[1], hip_mid[0] - shoulder_mid[0])))
        if shoulder_mid is not None and hip_mid is not None
        else float("nan")
    )
    if axis_angle > 90:
        axis_angle = 180 - axis_angle
    hip_width = max(1.0, abs(points[LEFT_HIP, 0] - points[RIGHT_HIP, 0]))
    ankle_separation = (
        abs(points[LEFT_ANKLE, 0] - points[RIGHT_ANKLE, 0]) / hip_width
        if min(points[LEFT_ANKLE, 2], points[RIGHT_ANKLE, 2]) >= confidence_min
        else float("nan")
    )
    left_leg = _box_from_points(points, (LEFT_HIP, LEFT_KNEE, LEFT_ANKLE), confidence_min, pad=2)
    right_leg = _box_from_points(
        points, (RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE), confidence_min, pad=2
    )
    return {
        "shoulder_to_wrist_vertical_fraction": vertical_fraction,
        "wrist_opposite_torso_overlap": sum(cross_hits) / len(cross_hits)
        if cross_hits
        else float("nan"),
        "mean_hip_knee_ankle_angle_deg": sum(knee_angles) / len(knee_angles)
        if knee_angles
        else float("nan"),
        "shoulder_hip_axis_from_horizontal_deg": axis_angle,
        "ankle_horizontal_separation_over_hip_width": ankle_separation,
        "left_right_leg_bbox_iou": _bbox_iou(left_leg, right_leg)
        if left_leg and right_leg
        else float("nan"),
    }


def evaluate_pose_tags(
    metrics: dict[str, float], rules: dict[str, dict[str, Any]]
) -> tuple[str, ...]:
    operators = {
        "gt": lambda value, threshold: value > threshold,
        "gte": lambda value, threshold: value >= threshold,
        "lt": lambda value, threshold: value < threshold,
        "lte": lambda value, threshold: value <= threshold,
    }
    tags = []
    for tag, rule in rules.items():
        metric = str(rule["metric"])
        operator = str(rule["operator"])
        if metric not in metrics or operator not in operators:
            raise PoseError(f"invalid pose tag rule {tag}")
        value = metrics[metric]
        if math.isfinite(value) and operators[operator](value, float(rule["threshold"])):
            tags.append(tag)
    return tuple(tags)


def _validate_candidate(candidate: PoseCandidate) -> PoseCandidate:
    points = np.asarray(candidate.keypoints, dtype=np.float64)
    if points.shape != (133, 3) or not np.isfinite(points).all():
        raise PoseError("keypoints must be finite with shape 133x3")
    if points[:, 2].min() < 0 or points[:, 2].max() > 1:
        raise PoseError("keypoint confidence must be in 0..1")
    left, top, right, bottom = candidate.bbox_xyxy
    if right <= left or bottom <= top:
        raise PoseError("candidate bbox must have positive area")
    return PoseCandidate(tuple(float(value) for value in candidate.bbox_xyxy), points)


def _bbox_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    left, top, right, bottom = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def _mean_coordinate(
    points: np.ndarray, indices: tuple[int, ...], axis: int, threshold: float
) -> float:
    values = [points[index, axis] for index in indices if points[index, 2] >= threshold]
    return float(sum(values) / len(values)) if values else float("nan")


def _mean_point(
    points: np.ndarray, indices: tuple[int, ...], threshold: float
) -> tuple[float, float] | None:
    selected = [points[index, :2] for index in indices if points[index, 2] >= threshold]
    if not selected:
        return None
    mean = np.mean(selected, axis=0)
    return float(mean[0]), float(mean[1])


def _joint_angle(points: np.ndarray, a: int, b: int, c: int, threshold: float) -> float:
    if min(points[a, 2], points[b, 2], points[c, 2]) < threshold:
        return float("nan")
    first, second = points[a, :2] - points[b, :2], points[c, :2] - points[b, :2]
    denominator = np.linalg.norm(first) * np.linalg.norm(second)
    if denominator == 0:
        return float("nan")
    return float(math.degrees(math.acos(np.clip(np.dot(first, second) / denominator, -1, 1))))


def _box_from_points(
    points: np.ndarray, indices: tuple[int, ...], threshold: float, pad: float = 0
) -> tuple[float, float, float, float] | None:
    selected = np.asarray([points[index, :2] for index in indices if points[index, 2] >= threshold])
    if not len(selected):
        return None
    return (
        float(selected[:, 0].min() - pad),
        float(selected[:, 1].min() - pad),
        float(selected[:, 0].max() + pad),
        float(selected[:, 1].max() + pad),
    )


def _point_in_box(x: float, y: float, box: tuple[float, float, float, float]) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]
