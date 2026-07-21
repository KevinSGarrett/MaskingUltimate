"""One-image point-prompt SAM 2.1 smoke in the authoritative CUDA WSL env."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor


def run(checkpoint: Path, image_path: Path, config: str) -> dict[str, object]:
    device = torch.device("cuda")
    model = build_sam2(config, str(checkpoint), device=device)
    predictor = SAM2ImagePredictor(model)
    image = np.asarray(Image.open(image_path).convert("RGB"))
    points = np.array([[150.0, 550.0], [600.0, 150.0]], dtype=np.float32)
    labels = np.array([1, 0], dtype=np.int32)
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        predictor.set_image(image)
        masks, scores, logits = predictor.predict(
            point_coords=points,
            point_labels=labels,
            multimask_output=False,
        )
    mask = np.asarray(masks[0], dtype=np.uint8)
    score = float(scores[0])
    area_fraction = float(mask.mean())
    passed = bool(
        mask.shape == image.shape[:2]
        and 0.005 < area_fraction < 0.6
        and np.isfinite(score)
        and logits.shape[0] == 1
    )
    return {
        "passed": passed,
        "output_sha256": hashlib.sha256(mask.tobytes()).hexdigest() if passed else "",
        "mask_shape": list(mask.shape),
        "area_fraction": round(area_fraction, 6),
        "score": round(score, 6),
        "prompt_points": points.tolist(),
        "prompt_labels": labels.tolist(),
        "device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "config": config,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.checkpoint, args.image, args.config), sort_keys=True))


if __name__ == "__main__":
    main()
