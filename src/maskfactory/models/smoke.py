"""Model-specific one-image smoke runners registered with the model fetcher."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .registry import register_smoke_runner


def yolo11_person_detector(checkpoint: Path, image: Path) -> dict[str, Any]:
    """Load YOLO11, run one CPU image, and hash normalized person detections."""
    from ultralytics import YOLO

    model = YOLO(str(checkpoint), task="detect")
    results = model.predict(source=str(image), imgsz=640, device="cpu", verbose=False)
    if len(results) != 1:
        return {"passed": False, "output_sha256": "", "reason": "expected one result"}
    result = results[0]
    names = result.names
    person_ids = [int(class_id) for class_id, name in names.items() if name == "person"]
    if person_ids != [0]:
        return {"passed": False, "output_sha256": "", "reason": "COCO person class missing"}
    detections = []
    if result.boxes is not None:
        for class_id, confidence, box in zip(
            result.boxes.cls.tolist(),
            result.boxes.conf.tolist(),
            result.boxes.xyxy.tolist(),
            strict=True,
        ):
            detections.append(
                {
                    "class_id": int(class_id),
                    "confidence": round(float(confidence), 6),
                    "xyxy": [round(float(value), 3) for value in box],
                }
            )
    payload = {
        "image_shape": list(result.orig_shape),
        "person_class_id": person_ids[0],
        "detections": detections,
    }
    person_detection_count = sum(item["class_id"] == 0 for item in detections)
    if person_detection_count < 1:
        return {
            "passed": False,
            "output_sha256": "",
            "reason": "no class-0 person detected",
            "detection_count": len(detections),
        }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {
        "passed": True,
        "output_sha256": hashlib.sha256(encoded).hexdigest(),
        "detection_count": len(detections),
        "person_detection_count": person_detection_count,
    }


register_smoke_runner("yolo11_person_detector", yolo11_person_detector)
