"""Model-specific one-image smoke runners registered with the model fetcher."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .registry import register_smoke_runner

ROOT = Path(__file__).resolve().parents[3]


def _wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise ValueError(f"expected Windows drive path, got {resolved}")
    relative = resolved.as_posix().split(":", 1)[1]
    return f"/mnt/{drive}{relative}"


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


def birefnet_general_wsl(checkpoint: Path, image: Path) -> dict[str, Any]:
    """Run pinned BiRefNet remote code in the authoritative CUDA WSL environment."""
    command = [
        "wsl",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        _wsl_path(ROOT / "tools" / "smoke_birefnet_wsl.py"),
        "--checkpoint",
        _wsl_path(checkpoint),
        "--image",
        _wsl_path(image),
    ]
    process = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    if process.returncode != 0:
        return {
            "passed": False,
            "output_sha256": "",
            "reason": process.stderr.strip()[-2000:] or process.stdout.strip()[-2000:],
        }
    try:
        result = json.loads(process.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return {
            "passed": False,
            "output_sha256": "",
            "reason": f"invalid WSL smoke output: {exc}: {process.stdout[-1000:]}",
        }
    return result


register_smoke_runner("birefnet_general_wsl", birefnet_general_wsl)


def sapiens_seg_0_6b_wsl(checkpoint: Path, image: Path) -> dict[str, Any]:
    """Run the official Sapiens 0.6B TorchScript parser on one CUDA image."""
    command = [
        "wsl",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        _wsl_path(ROOT / "tools" / "smoke_sapiens_seg_wsl.py"),
        "--checkpoint",
        _wsl_path(checkpoint),
        "--image",
        _wsl_path(image),
    ]
    process = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
    if process.returncode != 0:
        return {
            "passed": False,
            "output_sha256": "",
            "reason": process.stderr.strip()[-2000:] or process.stdout.strip()[-2000:],
        }
    try:
        return json.loads(process.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return {
            "passed": False,
            "output_sha256": "",
            "reason": f"invalid WSL smoke output: {exc}: {process.stdout[-1000:]}",
        }


register_smoke_runner("sapiens_seg_0_6b_wsl", sapiens_seg_0_6b_wsl)


def _schp_wsl(checkpoint: Path, image: Path, dataset: str) -> dict[str, Any]:
    command = [
        "wsl",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        _wsl_path(ROOT / "tools" / "smoke_schp_wsl.py"),
        "--checkpoint",
        _wsl_path(checkpoint),
        "--image",
        _wsl_path(image),
        "--dataset",
        dataset,
    ]
    process = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    if process.returncode != 0:
        return {
            "passed": False,
            "output_sha256": "",
            "reason": process.stderr.strip()[-2000:] or process.stdout.strip()[-2000:],
        }
    try:
        return json.loads(process.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return {
            "passed": False,
            "output_sha256": "",
            "reason": f"invalid WSL smoke output: {exc}: {process.stdout[-1000:]}",
        }


def schp_atr_wsl(checkpoint: Path, image: Path) -> dict[str, Any]:
    """Run the official SCHP ATR 18-class parser on one CUDA image."""
    return _schp_wsl(checkpoint, image, "atr")


def schp_lip_wsl(checkpoint: Path, image: Path) -> dict[str, Any]:
    """Run the official SCHP LIP 20-class parser on one CUDA image."""
    return _schp_wsl(checkpoint, image, "lip")


register_smoke_runner("schp_atr_wsl", schp_atr_wsl)
register_smoke_runner("schp_lip_wsl", schp_lip_wsl)
