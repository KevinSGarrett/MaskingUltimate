"""One-image Meta Sapiens 0.6B segmentation smoke in authoritative WSL."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as functional
from PIL import Image

INPUT_HEIGHT = 1024
INPUT_WIDTH = 768
MEAN = torch.tensor([123.5, 116.5, 103.5]).view(3, 1, 1)
STD = torch.tensor([58.5, 57.0, 57.5]).view(3, 1, 1)
EXPECTED_CLASSES = 28


def load_model(checkpoint: Path):
    """Load the pinned TorchScript model once for smoke or multi-tile inference."""
    device = torch.device("cuda")
    return torch.jit.load(str(checkpoint), map_location=device).eval()


def infer_with_model(model, image_path: Path, *, use_bf16: bool = False) -> np.ndarray:
    """Infer one tile without transferring or reloading the heavyweight model."""
    image = Image.open(image_path).convert("RGB").resize((INPUT_WIDTH, INPUT_HEIGHT))
    array = np.asarray(image, dtype=np.float32).copy()
    tensor = torch.from_numpy(array).permute(2, 0, 1)
    tensor = ((tensor - MEAN) / STD).unsqueeze(0).to("cuda")
    autocast = (
        torch.autocast("cuda", dtype=torch.bfloat16) if use_bf16 else contextlib.nullcontext()
    )
    with torch.inference_mode(), autocast:
        output = model(tensor)
    logits = output[0] if isinstance(output, (tuple, list)) else output
    if logits.ndim != 4 or logits.shape[0] != 1 or logits.shape[1] != EXPECTED_CLASSES:
        raise ValueError(f"unexpected logits shape {list(logits.shape)}")
    logits = functional.interpolate(
        logits.float(), size=(INPUT_HEIGHT, INPUT_WIDTH), mode="bilinear", align_corners=False
    )
    probabilities = logits.softmax(dim=1)[0].cpu().numpy().astype(np.float32)
    del tensor, logits, output
    return probabilities


def infer(checkpoint: Path, image_path: Path, *, use_bf16: bool = False) -> np.ndarray:
    model = load_model(checkpoint)
    try:
        return infer_with_model(model, image_path, use_bf16=use_bf16)
    finally:
        del model
        torch.cuda.empty_cache()


def run(checkpoint: Path, image_path: Path) -> dict[str, object]:
    try:
        probabilities = infer(checkpoint, image_path)
    except ValueError as exc:
        return {"passed": False, "output_sha256": "", "reason": str(exc)}
    labels = probabilities.argmax(axis=0).astype(np.uint8)
    unique_labels = sorted(int(value) for value in np.unique(labels))
    output_hash = hashlib.sha256(labels.tobytes()).hexdigest()
    foreground_fraction = float((labels != 0).mean())
    passed = bool(len(unique_labels) >= 2 and 0.01 < foreground_fraction < 0.99)
    return {
        "passed": passed,
        "output_sha256": output_hash if passed else "",
        "logits_shape": [1, EXPECTED_CLASSES, INPUT_HEIGHT, INPUT_WIDTH],
        "label_map_shape": list(labels.shape),
        "unique_labels": unique_labels,
        "foreground_fraction": round(foreground_fraction, 6),
        "torch": torch.__version__,
        "device": torch.cuda.get_device_name(0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.checkpoint, args.image), sort_keys=True))


if __name__ == "__main__":
    main()
