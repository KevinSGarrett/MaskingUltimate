"""Production DensePose chart inference and full-canvas IUV projection in WSL CUDA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from densepose import add_densepose_config
from detectron2.config import get_cfg
from detectron2.engine import DefaultPredictor
from PIL import Image


def _iou(box: list[float], target: tuple[float, float, float, float]) -> float:
    left, top = max(box[0], target[0]), max(box[1], target[1])
    right, bottom = min(box[2], target[2]), min(box[3], target[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
    second = max(0.0, target[2] - target[0]) * max(0.0, target[3] - target[1])
    return intersection / (first + second - intersection) if first + second > intersection else 0.0


def run(
    checkpoint: Path,
    config_path: Path,
    image_path: Path,
    target_bbox: tuple[float, float, float, float],
    output_path: Path,
) -> dict:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot read DensePose image: {image_path}")
    cfg = get_cfg()
    add_densepose_config(cfg)
    cfg.merge_from_file(str(config_path))
    cfg.MODEL.WEIGHTS = str(checkpoint)
    cfg.MODEL.DEVICE = "cuda"
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = 0.5
    cfg.freeze()
    instances = DefaultPredictor(cfg)(image)["instances"]
    if len(instances) < 1 or not instances.has("pred_densepose"):
        raise RuntimeError("DensePose produced no surface predictions")
    boxes = instances.pred_boxes.tensor.detach().cpu().tolist()
    selected = max(range(len(boxes)), key=lambda index: (_iou(boxes[index], target_bbox), -index))
    if _iou(boxes[selected], target_bbox) <= 0:
        raise RuntimeError("no DensePose candidate overlaps target bbox")
    dense = instances.pred_densepose
    fine = dense.fine_segm[selected].argmax(dim=0)
    gather_index = fine.unsqueeze(0)
    u = torch.gather(dense.u[selected], 0, gather_index).squeeze(0)
    v = torch.gather(dense.v[selected], 0, gather_index).squeeze(0)
    index = fine.to(torch.uint8).cpu().numpy()
    u_value = u.float().clamp(0, 1).cpu().numpy()
    v_value = v.float().clamp(0, 1).cpu().numpy()
    height, width = image.shape[:2]
    left, top, right, bottom = [int(round(value)) for value in boxes[selected]]
    left, top = max(0, left), max(0, top)
    right, bottom = min(width, right), min(height, bottom)
    if right <= left or bottom <= top:
        raise RuntimeError("selected DensePose bbox is empty after clamping")
    size = (right - left, bottom - top)
    roi_i = cv2.resize(index, size, interpolation=cv2.INTER_NEAREST)
    roi_u = cv2.resize(u_value, size, interpolation=cv2.INTER_LINEAR)
    roi_v = cv2.resize(v_value, size, interpolation=cv2.INTER_LINEAR)
    full_i = np.zeros((height, width), dtype=np.uint8)
    full_u = np.zeros_like(full_i)
    full_v = np.zeros_like(full_i)
    full_i[top:bottom, left:right] = roi_i
    foreground = roi_i > 0
    full_u[top:bottom, left:right][foreground] = np.rint(roi_u[foreground] * 255).astype(np.uint8)
    full_v[top:bottom, left:right][foreground] = np.rint(roi_v[foreground] * 255).astype(np.uint8)
    iuv = np.stack((full_i, full_u, full_v), axis=2)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(iuv, mode="RGB").save(output_path, format="PNG")
    return {
        "shape": [height, width],
        "selected_candidate_index": selected,
        "selected_bbox_iou": _iou(boxes[selected], target_bbox),
        "suppressed_candidate_indices": [index for index in range(len(boxes)) if index != selected],
        "surface_pixels": int((full_i > 0).sum()),
        "device": torch.cuda.get_device_name(0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--target-bbox-json", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.checkpoint,
                args.config,
                args.image,
                tuple(json.loads(args.target_bbox_json)),
                args.output,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
