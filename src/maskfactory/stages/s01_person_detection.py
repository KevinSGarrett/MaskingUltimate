"""S01 deterministic person ranking, promotion, protection, and context crops."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image


class PersonDetectionError(ValueError):
    """Detector output violates the S01 contract."""


@dataclass(frozen=True)
class Detection:
    bbox_xyxy: tuple[float, float, float, float]
    confidence: float


@dataclass(frozen=True)
class RankedPerson:
    detection_index: int
    bbox_xyxy: tuple[int, int, int, int]
    context_bbox_xyxy: tuple[int, int, int, int]
    confidence: float
    area_px: int
    frame_area_fraction: float
    centeredness: float
    score: float
    person_index: int | None
    promoted: bool
    protected_as_part_50: bool


@dataclass(frozen=True)
class S01Result:
    outcome: str
    reason: str | None
    persons: tuple[RankedPerson, ...]
    detector_source: str = "yolo11m"


def infer_yolo11_people(
    image_path: Path,
    *,
    checkpoint: Path,
    confidence_min: float = 0.5,
    device: str | int = 0,
) -> list[Detection]:
    """Run the registered YOLO11 detector and return COCO class-0 people only."""
    if not Path(checkpoint).is_file():
        raise PersonDetectionError(f"YOLO11 checkpoint missing: {checkpoint}")
    try:
        from ultralytics import YOLO

        model = YOLO(str(checkpoint), task="detect")
        results = model.predict(
            source=str(image_path),
            conf=confidence_min,
            imgsz=640,
            device=device,
            classes=[0],
            verbose=False,
        )
    except Exception as exc:  # noqa: BLE001 - normalize provider boundary
        raise PersonDetectionError(f"YOLO11 inference failed: {exc}") from exc
    if len(results) != 1 or results[0].boxes is None:
        raise PersonDetectionError("YOLO11 must return exactly one boxes result")
    names = results[0].names
    if names.get(0) != "person":
        raise PersonDetectionError("YOLO11 class 0 is not COCO person")
    detections = []
    for class_id, confidence, bbox in zip(
        results[0].boxes.cls.tolist(),
        results[0].boxes.conf.tolist(),
        results[0].boxes.xyxy.tolist(),
        strict=True,
    ):
        if int(class_id) != 0:
            raise PersonDetectionError("YOLO11 classes=[0] returned a non-person class")
        detections.append(Detection(tuple(float(value) for value in bbox), float(confidence)))
    return detections


def run_s01(
    image_path: Path,
    output_dir: Path,
    *,
    checkpoint: Path,
    confidence_min: float = 0.5,
    device: str | int = 0,
    instance_min_area_pct: float = 0.04,
    max_instances_per_image: int = 4,
    crowd_scene_threshold: int = 8,
    context_scale: float = 1.25,
    fallback_checkpoint: Path | None = None,
    fallback_prompt: str = "person",
    fallback_box_threshold: float = 0.30,
    fallback_text_threshold: float = 0.25,
    fallback_local_python: Path | None = None,
    fallback_source_path: Path | None = None,
    fallback_dependency_site: Path | None = None,
    fallback_hf_home: Path | None = None,
) -> S01Result:
    """Execute YOLO11, then proposal-only GroundingDINO if YOLO returns zero boxes."""
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    detections = infer_yolo11_people(
        image_path,
        checkpoint=checkpoint,
        confidence_min=confidence_min,
        device=device,
    )
    detector_source = "yolo11m"
    if not detections and fallback_checkpoint is not None:
        detections = infer_groundingdino_people(
            image_path,
            checkpoint=fallback_checkpoint,
            prompt=fallback_prompt,
            box_threshold=fallback_box_threshold,
            text_threshold=fallback_text_threshold,
            local_python=fallback_local_python,
            source_path=fallback_source_path,
            dependency_site=fallback_dependency_site,
            hf_home=fallback_hf_home,
        )
        detector_source = "groundingdino_swint_ogc"
    return process_detections(
        image,
        detections,
        output_dir,
        confidence_min=confidence_min,
        instance_min_area_pct=instance_min_area_pct,
        max_instances_per_image=max_instances_per_image,
        crowd_scene_threshold=crowd_scene_threshold,
        context_scale=context_scale,
        detector_source=detector_source,
    )


def infer_groundingdino_people(
    image_path: Path,
    *,
    checkpoint: Path,
    prompt: str = "person",
    box_threshold: float = 0.30,
    text_threshold: float = 0.25,
    local_python: Path | None = None,
    source_path: Path | None = None,
    dependency_site: Path | None = None,
    hf_home: Path | None = None,
) -> list[Detection]:
    """Convert governed proposal-only person boxes into S01 detection candidates."""
    if prompt != "person":
        raise PersonDetectionError("S01 GroundingDINO fallback prompt must be exactly 'person'")
    from .s06_openvocab import OpenVocabError, infer_gdino_proposals

    try:
        proposals = infer_gdino_proposals(
            image_path,
            checkpoint=checkpoint,
            prompts=(prompt,),
            box_threshold=box_threshold,
            text_threshold=text_threshold,
            local_python=local_python,
            source_path=source_path,
            dependency_site=dependency_site,
            hf_home=hf_home,
        )
    except OpenVocabError as exc:
        raise PersonDetectionError(f"GroundingDINO person fallback failed: {exc}") from exc
    detections = [
        Detection(proposal.bbox_xyxy, min(proposal.box_score, proposal.text_score))
        for proposal in proposals
        if proposal.prompt == prompt and proposal.authority == "proposal_only"
    ]
    return _nms(detections, iou_threshold=0.60)


def process_detections(
    image: Image.Image,
    detections: list[Detection],
    output_dir: Path,
    *,
    confidence_min: float = 0.5,
    instance_min_area_pct: float = 0.04,
    max_instances_per_image: int = 4,
    crowd_scene_threshold: int = 8,
    context_scale: float = 1.25,
    detector_source: str = "yolo11m",
) -> S01Result:
    """Apply doc-17 promotion policy and write one context crop per promoted person."""
    width, height = image.size
    if width < 1 or height < 1 or context_scale < 1:
        raise PersonDetectionError("invalid frame or context scale")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if len(detections) > crowd_scene_threshold:
        result = S01Result("quarantined", "crowd_scene_out_of_scope", (), detector_source)
        _write_result(output_dir, result, detections)
        return result
    frame_area = width * height
    eligible = []
    for index, detection in enumerate(detections):
        if not 0 <= detection.confidence <= 1:
            raise PersonDetectionError(f"detection confidence outside 0..1: {detection.confidence}")
        bbox = _clamped_bbox(detection.bbox_xyxy, width, height)
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        fraction = area / frame_area
        if detection.confidence < confidence_min or fraction < instance_min_area_pct:
            continue
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        distance = math.hypot(center_x - width / 2, center_y - height / 2)
        centeredness = max(0.0, 1.0 - distance / math.hypot(width / 2, height / 2))
        eligible.append((index, detection, bbox, area, fraction, centeredness, area * centeredness))
    if not eligible:
        result = S01Result("rejected", "no_person", (), detector_source)
        _write_result(output_dir, result, detections)
        return result
    eligible.sort(key=lambda item: (-item[6], item[2][0], item[0]))
    persons = []
    for rank, (index, detection, bbox, area, fraction, centeredness, score) in enumerate(eligible):
        promoted = rank < max_instances_per_image
        context_bbox = _expanded_bbox(bbox, width, height, context_scale)
        person = RankedPerson(
            detection_index=index,
            bbox_xyxy=bbox,
            context_bbox_xyxy=context_bbox,
            confidence=detection.confidence,
            area_px=area,
            frame_area_fraction=fraction,
            centeredness=centeredness,
            score=score,
            person_index=rank if promoted else None,
            promoted=promoted,
            protected_as_part_50=not promoted,
        )
        persons.append(person)
        if promoted:
            crop_dir = output_dir / f"p{rank}"
            crop_dir.mkdir(parents=True, exist_ok=True)
            crop = image.crop(context_bbox)
            crop.save(crop_dir / "person_ctx.png", format="PNG")  # png-strict: allow (work image)
    result = S01Result("promoted", None, tuple(persons), detector_source)
    _write_result(output_dir, result, detections)
    return result


def _clamped_bbox(
    bbox: tuple[float, float, float, float], width: int, height: int
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    left = max(0, min(width - 1, math.floor(x1)))
    top = max(0, min(height - 1, math.floor(y1)))
    right = max(left + 1, min(width, math.ceil(x2)))
    bottom = max(top + 1, min(height, math.ceil(y2)))
    return left, top, right, bottom


def _expanded_bbox(
    bbox: tuple[int, int, int, int], width: int, height: int, scale: float
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    expanded_width, expanded_height = (right - left) * scale, (bottom - top) * scale
    return (
        max(0, math.floor(center_x - expanded_width / 2)),
        max(0, math.floor(center_y - expanded_height / 2)),
        min(width, math.ceil(center_x + expanded_width / 2)),
        min(height, math.ceil(center_y + expanded_height / 2)),
    )


def _write_result(output_dir: Path, result: S01Result, raw: list[Detection]) -> None:
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "outcome": result.outcome,
        "reason": result.reason,
        "raw_detection_count": len(raw),
        "detector_source": result.detector_source,
        "raw_detections": [asdict(detection) for detection in raw],
        "persons": [asdict(person) for person in result.persons],
    }
    (output_dir / "person_bbox.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _nms(detections: list[Detection], *, iou_threshold: float) -> list[Detection]:
    if not 0 < iou_threshold < 1:
        raise PersonDetectionError("NMS IoU threshold must be within 0..1")
    ordered = sorted(detections, key=lambda item: item.confidence, reverse=True)
    kept: list[Detection] = []
    for candidate in ordered:
        if all(_bbox_iou(candidate.bbox_xyxy, item.bbox_xyxy) <= iou_threshold for item in kept):
            kept.append(candidate)
    return kept


def _bbox_iou(
    first: tuple[float, float, float, float], second: tuple[float, float, float, float]
) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0
