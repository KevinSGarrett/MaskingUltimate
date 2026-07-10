"""Run one real DensePose R50-FPN CUDA inference and emit registry evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import torch
from densepose import add_densepose_config
from detectron2.config import get_cfg
from detectron2.engine import DefaultPredictor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"could not read image: {args.image}")

    cfg = get_cfg()
    add_densepose_config(cfg)
    cfg.merge_from_file(str(args.config))
    cfg.MODEL.WEIGHTS = str(args.checkpoint)
    cfg.MODEL.DEVICE = "cuda"
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = 0.5
    cfg.freeze()

    outputs = DefaultPredictor(cfg)(image)
    instances = outputs["instances"]
    if len(instances) < 1 or not instances.has("pred_densepose"):
        raise RuntimeError("DensePose produced no person surface predictions")

    densepose = instances.pred_densepose
    tensors = {
        "coarse_segm": densepose.coarse_segm,
        "fine_segm": densepose.fine_segm,
        "u": densepose.u,
        "v": densepose.v,
    }
    if any(tensor.device.type != "cuda" for tensor in tensors.values()):
        raise RuntimeError("DensePose outputs were not produced on CUDA")

    fine_labels = tensors["fine_segm"].argmax(dim=1)
    nonzero_fraction = float((fine_labels > 0).float().mean().item())
    if nonzero_fraction <= 0.0:
        raise RuntimeError("DensePose fine segmentation is empty")

    payload = {
        "image_shape": list(image.shape[:2]),
        "instance_count": len(instances),
        "boxes": [
            [round(float(value), 3) for value in box]
            for box in instances.pred_boxes.tensor.detach().cpu().tolist()
        ],
        "scores": [round(float(value), 6) for value in instances.scores.detach().cpu().tolist()],
        "tensor_shapes": {name: list(tensor.shape) for name, tensor in tensors.items()},
        "fine_label_min": int(fine_labels.min().item()),
        "fine_label_max": int(fine_labels.max().item()),
        "fine_nonzero_fraction": round(nonzero_fraction, 6),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    result = {
        "passed": True,
        "output_sha256": hashlib.sha256(encoded).hexdigest(),
        **payload,
        "device": torch.cuda.get_device_name(0),
        "capability": list(torch.cuda.get_device_capability(0)),
    }
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
