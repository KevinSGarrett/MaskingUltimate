"""Run the official 19-class face-parsing BiSeNet on a governed CUDA crop."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torchvision.transforms import functional as transform_functional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sys.path.insert(0, str(args.source))
    from model import BiSeNet  # noqa: PLC0415

    image = Image.open(args.image).convert("RGB")
    width, height = image.size
    crop_box = (
        round(width * 0.70),
        round(height * 0.22),
        width,
        round(height * 0.62),
    )
    crop = image.crop(crop_box).resize((512, 512), Image.Resampling.BILINEAR)
    tensor = transform_functional.to_tensor(crop)
    tensor = transform_functional.normalize(
        tensor,
        mean=(0.485, 0.456, 0.406),
        std=(0.229, 0.224, 0.225),
    ).unsqueeze(0)

    model = BiSeNet(n_classes=19).cuda().eval()
    state = torch.load(args.checkpoint, map_location="cuda", weights_only=True)
    model.load_state_dict(state, strict=True)
    with torch.inference_mode():
        logits = model(tensor.cuda())[0]
    labels = logits.argmax(dim=1).squeeze(0).to(torch.uint8)
    torch.cuda.synchronize()

    unique, counts = torch.unique(labels, return_counts=True)
    histogram = {
        str(int(label)): int(count)
        for label, count in zip(unique.cpu().tolist(), counts.cpu().tolist(), strict=True)
    }
    foreground_fraction = float((labels > 0).float().mean().item())
    if len(unique) < 2 or foreground_fraction <= 0.001:
        raise RuntimeError(f"face parse is nontriviality failure: {histogram}")

    label_bytes = np.ascontiguousarray(labels.cpu().numpy()).tobytes()
    result = {
        "passed": True,
        "output_sha256": hashlib.sha256(label_bytes).hexdigest(),
        "crop_box": list(crop_box),
        "input_shape": list(tensor.shape),
        "logits_shape": list(logits.shape),
        "unique_labels": [int(value) for value in unique.cpu().tolist()],
        "histogram": histogram,
        "foreground_fraction": round(foreground_fraction, 6),
        "device": torch.cuda.get_device_name(0),
        "capability": list(torch.cuda.get_device_capability(0)),
    }
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
