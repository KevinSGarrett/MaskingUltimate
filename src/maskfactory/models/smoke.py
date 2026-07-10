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


def _dwpose_wsl(checkpoint: Path, image: Path, mode: str) -> dict[str, Any]:
    detector = checkpoint if mode == "detector" else ROOT / "models" / "pose" / "yolox_l.onnx"
    pose = checkpoint if mode == "pose" else None
    command = [
        "wsl",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/usr/bin/env",
        "LD_LIBRARY_PATH=/home/kevin/miniforge3/envs/maskfactory/lib/python3.11/site-packages/nvidia/cublas/lib:/home/kevin/miniforge3/envs/maskfactory/lib/python3.11/site-packages/nvidia/cudnn/lib:/home/kevin/miniforge3/envs/maskfactory/lib/python3.11/site-packages/nvidia/cuda_runtime/lib:/home/kevin/miniforge3/envs/maskfactory/lib/python3.11/site-packages/nvidia/cuda_nvrtc/lib:/home/kevin/miniforge3/envs/maskfactory/lib/python3.11/site-packages/nvidia/cufft/lib:/home/kevin/miniforge3/envs/maskfactory/lib/python3.11/site-packages/nvidia/curand/lib:/home/kevin/miniforge3/envs/maskfactory/lib/python3.11/site-packages/nvidia/cusolver/lib:/home/kevin/miniforge3/envs/maskfactory/lib/python3.11/site-packages/nvidia/cusparse/lib:/home/kevin/miniforge3/envs/maskfactory/lib/python3.11/site-packages/nvidia/nvjitlink/lib",
        "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        _wsl_path(ROOT / "tools" / "smoke_dwpose_wsl.py"),
        "--detector",
        _wsl_path(detector),
        "--image",
        _wsl_path(image),
    ]
    if pose is not None:
        command.extend(["--pose", _wsl_path(pose)])
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


def dwpose_yolox_wsl(checkpoint: Path, image: Path) -> dict[str, Any]:
    """Run the official paired YOLOX detector on one image."""
    return _dwpose_wsl(checkpoint, image, "detector")


def dwpose_133_wsl(checkpoint: Path, image: Path) -> dict[str, Any]:
    """Run YOLOX and the official 133-keypoint DWPose model together."""
    return _dwpose_wsl(checkpoint, image, "pose")


register_smoke_runner("dwpose_yolox_cuda_wsl", dwpose_yolox_wsl)
register_smoke_runner("dwpose_133_cuda_wsl", dwpose_133_wsl)


def mediapipe_hand_landmarker(checkpoint: Path, image: Path) -> dict[str, Any]:
    """Run MediaPipe Tasks and require one complete 21-landmark hand."""
    import mediapipe as mp

    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(checkpoint)),
        num_hands=2,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    sample = mp.Image.create_from_file(str(image))
    with mp.tasks.vision.HandLandmarker.create_from_options(options) as landmarker:
        result = landmarker.detect(sample)
    if len(result.hand_landmarks) != 1 or len(result.hand_landmarks[0]) != 21:
        return {
            "passed": False,
            "output_sha256": "",
            "reason": f"expected one 21-point hand, got {[len(hand) for hand in result.hand_landmarks]}",
        }
    landmarks = [
        [round(float(point.x), 6), round(float(point.y), 6), round(float(point.z), 6)]
        for point in result.hand_landmarks[0]
    ]
    world = [
        [round(float(point.x), 6), round(float(point.y), 6), round(float(point.z), 6)]
        for point in result.hand_world_landmarks[0]
    ]
    handedness = result.handedness[0][0]
    payload = {
        "landmarks": landmarks,
        "world_landmarks": world,
        "handedness": handedness.category_name,
        "handedness_score": round(float(handedness.score), 6),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {
        "passed": True,
        "output_sha256": hashlib.sha256(encoded).hexdigest(),
        "hand_count": 1,
        "landmark_count": 21,
        "world_landmark_count": 21,
        "handedness": handedness.category_name,
        "handedness_score": round(float(handedness.score), 6),
    }


register_smoke_runner("mediapipe_hand_landmarker", mediapipe_hand_landmarker)


def mediapipe_hand_landmarker_wsl(checkpoint: Path, image: Path) -> dict[str, Any]:
    """Run the same 21-landmark gate in the authoritative WSL environment."""
    command = [
        "wsl",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        _wsl_path(ROOT / "tools" / "smoke_mediapipe_hand_wsl.py"),
        "--checkpoint",
        _wsl_path(checkpoint),
        "--image",
        _wsl_path(image),
    ]
    process = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
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


register_smoke_runner("mediapipe_hand_landmarker_wsl", mediapipe_hand_landmarker_wsl)


def _sam2_wsl(checkpoint: Path, image: Path, config: str) -> dict[str, Any]:
    command = [
        "wsl",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        _wsl_path(ROOT / "tools" / "smoke_sam2_wsl.py"),
        "--checkpoint",
        _wsl_path(checkpoint),
        "--image",
        _wsl_path(image),
        "--config",
        config,
    ]
    process = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
    if process.returncode != 0:
        return {
            "passed": False,
            "output_sha256": "",
            "reason": process.stderr.strip()[-3000:] or process.stdout.strip()[-3000:],
        }
    try:
        return json.loads(process.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return {
            "passed": False,
            "output_sha256": "",
            "reason": f"invalid WSL smoke output: {exc}: {process.stdout[-1000:]}",
        }


def sam2_1_base_plus_cuda_wsl(checkpoint: Path, image: Path) -> dict[str, Any]:
    """Run a positive/negative point-prompt smoke with SAM 2.1 base-plus."""
    return _sam2_wsl(checkpoint, image, "configs/sam2.1/sam2.1_hiera_b+.yaml")


def sam2_1_large_cuda_wsl(checkpoint: Path, image: Path) -> dict[str, Any]:
    """Run a positive/negative point-prompt smoke with SAM 2.1 large."""
    return _sam2_wsl(checkpoint, image, "configs/sam2.1/sam2.1_hiera_l.yaml")


register_smoke_runner("sam2_1_base_plus_cuda_wsl", sam2_1_base_plus_cuda_wsl)
register_smoke_runner("sam2_1_large_cuda_wsl", sam2_1_large_cuda_wsl)


def groundingdino_person_boxes_wsl(checkpoint: Path, image: Path) -> dict[str, Any]:
    """Ground the text prompt 'person' to real boxes through pinned GroundingDINO."""
    command = [
        "wsl",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        _wsl_path(ROOT / "tools" / "smoke_groundingdino_wsl.py"),
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
            "reason": process.stderr.strip()[-3000:] or process.stdout.strip()[-3000:],
        }
    try:
        return json.loads(process.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return {
            "passed": False,
            "output_sha256": "",
            "reason": f"invalid WSL smoke output: {exc}: {process.stdout[-1000:]}",
        }


register_smoke_runner("groundingdino_person_boxes_wsl", groundingdino_person_boxes_wsl)
