"""One-image paired YOLOX/DWPose ONNX smoke in authoritative WSL."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

NVIDIA_ROOT = Path(sys.prefix) / "lib" / "python3.11" / "site-packages" / "nvidia"
NVIDIA_LIBS = [str(path) for path in NVIDIA_ROOT.glob("*/lib") if path.is_dir()]
os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(
    NVIDIA_LIBS + ([os.environ["LD_LIBRARY_PATH"]] if os.environ.get("LD_LIBRARY_PATH") else [])
)

import onnxruntime as ort  # noqa: E402 - provider libraries must be discoverable first

REPOSITORY = "https://github.com/Fannovel16/comfyui_controlnet_aux.git"
REVISION = "e8b689a513c3e6b63edc44066560ca5919c0576e"
SOURCE = Path.home() / ".cache" / "maskfactory" / "comfyui_controlnet_aux" / REVISION


def _ensure_source() -> None:
    marker = SOURCE / "src" / "custom_controlnet_aux" / "dwpose" / "dw_onnx" / "cv_ox_det.py"
    if marker.is_file():
        return
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--filter=blob:none", REPOSITORY, str(SOURCE)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(SOURCE), "checkout", "--detach", REVISION],
        check=True,
        capture_output=True,
        text=True,
    )


def _module(name: str, filename: str):
    path = SOURCE / "src" / "custom_controlnet_aux" / "dwpose" / "dw_onnx" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _session(path: Path) -> ort.InferenceSession:
    available = ort.get_available_providers()
    preferred = [
        provider
        for provider in ("CUDAExecutionProvider", "CPUExecutionProvider")
        if provider in available
    ]
    return ort.InferenceSession(str(path), providers=preferred)


def run(detector: Path, image_path: Path, pose: Path | None) -> dict[str, object]:
    _ensure_source()
    detection = _module("maskfactory_dw_det", "cv_ox_det.py")
    pose_module = _module("maskfactory_dw_pose", "cv_ox_pose.py")
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot read smoke image {image_path}")
    det_session = _session(detector)
    boxes = detection.inference_detector(det_session, image, detect_classes=[0])
    boxes = np.asarray(boxes if boxes is not None else [], dtype=np.float32).reshape(-1, 4)
    if boxes.shape[0] < 1:
        return {"passed": False, "output_sha256": "", "reason": "no person boxes"}
    if pose is None:
        normalized = np.round(boxes, 3).astype("<f4")
        return {
            "passed": True,
            "output_sha256": hashlib.sha256(normalized.tobytes()).hexdigest(),
            "person_boxes": int(boxes.shape[0]),
            "providers": det_session.get_providers(),
            "source_revision": REVISION,
        }
    pose_session = _session(pose)
    keypoints, scores = pose_module.inference_pose(
        pose_session, boxes, image, model_input_size=(288, 384), dtype=np.float32
    )
    if keypoints.ndim != 3 or keypoints.shape[1:] != (133, 2):
        return {
            "passed": False,
            "output_sha256": "",
            "reason": f"unexpected keypoints shape {list(keypoints.shape)}",
        }
    visible = scores >= 0.3
    payload = np.concatenate([keypoints, scores[..., None]], axis=-1)
    normalized = np.round(payload, 4).astype("<f4")
    passed = bool(visible.sum() >= 17 and np.isfinite(payload).all())
    return {
        "passed": passed,
        "output_sha256": hashlib.sha256(normalized.tobytes()).hexdigest() if passed else "",
        "person_boxes": int(boxes.shape[0]),
        "keypoints_shape": list(keypoints.shape),
        "visible_keypoints": int(visible.sum()),
        "detector_providers": det_session.get_providers(),
        "pose_providers": pose_session.get_providers(),
        "source_revision": REVISION,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--pose", type=Path)
    parser.add_argument("--image", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.detector, args.image, args.pose), sort_keys=True))


if __name__ == "__main__":
    main()
