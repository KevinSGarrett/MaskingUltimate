"""One-image persistent SAM2.1 predictor server for S07 embedding reuse."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--image", type=Path, required=True)
    args = parser.parse_args()
    model = build_sam2(args.config, str(args.checkpoint), device="cuda")
    predictor = SAM2ImagePredictor(model)
    image = np.asarray(Image.open(args.image).convert("RGB"))
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
        predictor.set_image(image)
    print(json.dumps({"status": "ready", "shape": list(image.shape[:2])}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        positives = request["positive_points"]
        negatives = request["negative_points"]
        points = np.asarray(positives + negatives, dtype=np.float32)
        labels = np.asarray([1] * len(positives) + [0] * len(negatives), dtype=np.int32)
        box = np.asarray(request["box_xyxy"], dtype=np.float32)
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
            masks, scores, _ = predictor.predict(
                point_coords=points if len(points) else None,
                point_labels=labels if len(points) else None,
                box=box,
                multimask_output=bool(request["multimask_output"]),
            )
        logits = np.where(np.asarray(masks), 1.0, -1.0).astype(np.float32)
        output = Path(request["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(output, logits=logits, scores=np.asarray(scores, dtype=np.float32))
        print(
            json.dumps(
                {
                    "status": "ok",
                    "request_id": request["request_id"],
                    "count": int(len(logits)),
                    "shape": list(logits.shape[1:]),
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
