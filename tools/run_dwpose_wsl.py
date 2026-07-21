"""Authoritative WSL CUDA bridge for full DWPose candidate inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch

NVIDIA_ROOT = Path(sys.prefix) / "lib" / "python3.11" / "site-packages" / "nvidia"
NVIDIA_LIBS = [str(path) for path in NVIDIA_ROOT.glob("*/lib") if path.is_dir()]
os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(
    NVIDIA_LIBS + ([os.environ["LD_LIBRARY_PATH"]] if os.environ.get("LD_LIBRARY_PATH") else [])
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maskfactory.stages.s04_pose import infer_dwpose_candidates  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(
    image: Path,
    detector: Path,
    pose: Path,
    output: Path,
    *,
    detection_confidence: float,
    nms_iou: float,
) -> dict[str, object]:
    candidates = infer_dwpose_candidates(
        image,
        detector_checkpoint=detector,
        pose_checkpoint=pose,
        require_cuda=True,
        detection_confidence=detection_confidence,
        nms_iou=nms_iou,
    )
    boxes = np.asarray([candidate.bbox_xyxy for candidate in candidates], dtype=np.float32).reshape(
        -1, 4
    )
    keypoints = np.asarray([candidate.keypoints for candidate in candidates], dtype=np.float32)
    if not candidates:
        keypoints = np.empty((0, 133, 3), dtype=np.float32)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, bboxes=boxes, keypoints=keypoints)
    return {
        "protocol_version": 1,
        "detector_sha256": _sha256(detector),
        "pose_sha256": _sha256(pose),
        "provider": "CUDAExecutionProvider",
        "candidate_count": len(candidates),
        "bboxes_shape": list(boxes.shape),
        "keypoints_shape": list(keypoints.shape),
        "detection_confidence": detection_confidence,
        "nms_iou": nms_iou,
        "device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--pose", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--detection-confidence", type=float, default=0.3)
    parser.add_argument("--nms-iou", type=float, default=0.45)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.image,
                args.detector,
                args.pose,
                args.output,
                detection_confidence=args.detection_confidence,
                nms_iou=args.nms_iou,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
