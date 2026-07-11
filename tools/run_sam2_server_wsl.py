"""One-image persistent SAM2.1 predictor server for S07 embedding reuse."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor

MODEL_SHA256 = {
    "sam2.1_hiera_large": "2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318",
    "sam2.1_hiera_base_plus": "a2345aede8715ab1d5d31b4a509fb160c5a4af1970f199d9054ccfb746c004c5",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model-key", choices=tuple(MODEL_SHA256), required=True)
    args = parser.parse_args()
    checkpoint_sha = _sha256(args.checkpoint)
    if checkpoint_sha != MODEL_SHA256[args.model_key]:
        raise ValueError("SAM2 checkpoint hash does not match model key")
    model = build_sam2(args.config, str(args.checkpoint), device="cuda")
    predictor = SAM2ImagePredictor(model)
    image = np.asarray(Image.open(args.image).convert("RGB"))
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
        predictor.set_image(image)
    print(
        json.dumps(
            {
                "protocol_version": 1,
                "status": "ready",
                "shape": list(image.shape[:2]),
                "model": args.model_key,
                "checkpoint_sha256": checkpoint_sha,
                "config": args.config,
                "precision": "fp16",
                "device_type": "cuda",
                "device": torch.cuda.get_device_name(0),
                "embedding_count": 1,
            }
        ),
        flush=True,
    )
    prediction_index = 0
    for line in sys.stdin:
        request = json.loads(line)
        positives = request["positive_points"]
        negatives = request["negative_points"]
        points = np.asarray(positives + negatives, dtype=np.float32)
        labels = np.asarray([1] * len(positives) + [0] * len(negatives), dtype=np.int32)
        box = np.asarray(request["box_xyxy"], dtype=np.float32)
        height, width = image.shape[:2]
        if box.shape != (4,) or not (
            0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height
        ):
            raise ValueError("SAM2 request box is outside image geometry")
        if points.size and (
            points.ndim != 2
            or points.shape[1] != 2
            or np.any(points[:, 0] < 0)
            or np.any(points[:, 0] >= width)
            or np.any(points[:, 1] < 0)
            or np.any(points[:, 1] >= height)
        ):
            raise ValueError("SAM2 request point is outside image geometry")
        if request["multimask_output"] is not True:
            raise ValueError("SAM2 production requires multimask_output=true")
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
            logits, scores, _ = predictor.predict(
                point_coords=points if len(points) else None,
                point_labels=labels if len(points) else None,
                box=box,
                multimask_output=True,
                return_logits=True,
            )
        logits = np.asarray(logits, dtype=np.float32)
        scores = np.asarray(scores, dtype=np.float32)
        if (
            logits.shape != (3, height, width)
            or scores.shape != (3,)
            or not np.isfinite(logits).all()
            or not np.isfinite(scores).all()
            or np.any(scores < 0)
            or np.any(scores > 1)
        ):
            raise ValueError("SAM2 prediction output violates three-mask float32 contract")
        output = Path(request["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(output, logits=logits, scores=scores)
        prediction_index += 1
        print(
            json.dumps(
                {
                    "protocol_version": 1,
                    "status": "ok",
                    "request_id": request["request_id"],
                    "count": int(len(logits)),
                    "shape": list(logits.shape[1:]),
                    "embedding_count": 1,
                    "prediction_index": prediction_index,
                    "multimask_output": True,
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
