"""Production trimap-conditioned ViTMatte-S alpha inference in pinned WSL CUDA env."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import VitMatteConfig, VitMatteForImageMatting, VitMatteImageProcessor

MODEL_ID = "hustvl/vitmatte-small-composition-1k"


def run(
    checkpoint: Path,
    image_path: Path,
    trimap_path: Path,
    output_path: Path,
    revision: str,
) -> dict:
    image = Image.open(image_path).convert("RGB")
    trimap = Image.open(trimap_path).convert("L")
    if image.size != trimap.size:
        raise ValueError("ViTMatte image and trimap dimensions differ")
    trimap_array = np.asarray(trimap)
    if set(np.unique(trimap_array).tolist()) - {0, 128, 255}:
        raise ValueError("ViTMatte trimap must contain only 0/128/255")
    processor = VitMatteImageProcessor.from_pretrained(
        MODEL_ID, revision=revision, local_files_only=True
    )
    config = VitMatteConfig.from_pretrained(MODEL_ID, revision=revision, local_files_only=True)
    model = VitMatteForImageMatting(config)
    model.load_state_dict(
        torch.load(checkpoint, map_location="cpu", weights_only=True), strict=True
    )
    model = model.cuda().eval()
    inputs = processor(images=image, trimaps=trimap, return_tensors="pt")
    pixel_values = inputs["pixel_values"].cuda()
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
        predicted = model(pixel_values=pixel_values).alphas.squeeze().float()
    height, width = trimap_array.shape
    alpha = predicted[:height, :width].clamp(0, 1).cpu().numpy()
    alpha[trimap_array == 0] = 0
    alpha[trimap_array == 255] = 1
    alpha_u8 = np.rint(alpha * 255).astype(np.uint8)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(alpha_u8, mode="L").save(output_path, format="PNG")
    unknown = alpha[trimap_array == 128]
    return {
        "shape": [height, width],
        "mode": "L",
        "min": int(alpha_u8.min()),
        "max": int(alpha_u8.max()),
        "unknown_mean": float(unknown.mean()) if unknown.size else None,
        "unknown_std": float(unknown.std()) if unknown.size else None,
        "device": torch.cuda.get_device_name(0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--trimap", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.checkpoint,
                args.image,
                args.trimap,
                args.output,
                args.revision,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
