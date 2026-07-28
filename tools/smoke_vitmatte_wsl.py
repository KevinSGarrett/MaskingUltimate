"""Run one real trimap-conditioned ViTMatte-S CUDA inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import VitMatteConfig, VitMatteForImageMatting, VitMatteImageProcessor

MODEL_ID = "hustvl/vitmatte-small-composition-1k"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    return parser.parse_args()


def build_trimap(size: int = 512) -> np.ndarray:
    yy, xx = np.mgrid[:size, :size]
    distance = ((xx - size * 0.55) / (size * 0.27)) ** 2 + ((yy - size * 0.52) / (size * 0.40)) ** 2
    trimap = np.zeros((size, size), dtype=np.uint8)
    trimap[distance <= 1.0] = 128
    trimap[distance <= 0.58] = 255
    return trimap


def main() -> None:
    args = parse_args()
    image = Image.open(args.image).convert("RGB")
    width, height = image.size
    crop_box = (
        round(width * 0.62),
        round(height * 0.25),
        width,
        round(height * 0.88),
    )
    crop = image.crop(crop_box).resize((512, 512), Image.Resampling.BILINEAR)
    trimap_array = build_trimap()
    trimap = Image.fromarray(trimap_array, mode="L")

    processor = VitMatteImageProcessor.from_pretrained(MODEL_ID, revision=args.revision)
    config = VitMatteConfig.from_pretrained(MODEL_ID, revision=args.revision)
    model = VitMatteForImageMatting(config)
    state = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(state, strict=True)
    model = model.cuda().eval()

    inputs = processor(images=crop, trimaps=trimap, return_tensors="pt")
    pixel_values = inputs["pixel_values"].cuda()
    with torch.inference_mode():
        alphas = model(pixel_values=pixel_values).alphas
    torch.cuda.synchronize()

    alpha = alphas.squeeze().float().clamp(0.0, 1.0)
    unknown = torch.from_numpy(trimap_array == 128).to(alpha.device)
    unknown_values = alpha[unknown]
    if unknown_values.numel() == 0 or float(unknown_values.std().item()) <= 0.001:
        raise RuntimeError("ViTMatte unknown band did not produce a nontrivial alpha transition")
    alpha_u8 = (alpha * 255.0).round().to(torch.uint8).cpu().numpy()
    result = {
        "passed": True,
        "output_sha256": hashlib.sha256(np.ascontiguousarray(alpha_u8).tobytes()).hexdigest(),
        "crop_box": list(crop_box),
        "pixel_values_shape": list(pixel_values.shape),
        "alpha_shape": list(alphas.shape),
        "alpha_min": round(float(alpha.min().item()), 6),
        "alpha_max": round(float(alpha.max().item()), 6),
        "alpha_mean": round(float(alpha.mean().item()), 6),
        "unknown_mean": round(float(unknown_values.mean().item()), 6),
        "unknown_std": round(float(unknown_values.std().item()), 6),
        "device": torch.cuda.get_device_name(0),
        "capability": list(torch.cuda.get_device_capability(0)),
    }
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
