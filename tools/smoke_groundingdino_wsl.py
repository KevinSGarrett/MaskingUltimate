"""One-image text-grounded GroundingDINO box smoke in authoritative WSL."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import groundingdino
import numpy as np
from groundingdino.util.inference import load_image, load_model, predict


def run(checkpoint: Path, image_path: Path) -> dict[str, object]:
    package = Path(groundingdino.__file__).resolve().parent
    config = package / "config" / "GroundingDINO_SwinT_OGC.py"
    model = load_model(str(config), str(checkpoint), device="cpu")
    _, image = load_image(str(image_path))
    boxes, logits, phrases = predict(
        model=model,
        image=image,
        caption="person .",
        box_threshold=0.30,
        text_threshold=0.25,
        device="cpu",
    )
    box_array = boxes.detach().cpu().numpy()
    logit_array = logits.detach().cpu().numpy()
    normalized = {
        "boxes_cxcywh": np.round(box_array, 6).tolist(),
        "logits": np.round(logit_array, 6).tolist(),
        "phrases": list(phrases),
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    passed = bool(
        len(box_array) >= 1
        and box_array.shape[1:] == (4,)
        and np.isfinite(box_array).all()
        and np.logical_and(box_array >= 0, box_array <= 1).all()
        and all("person" in phrase.lower() for phrase in phrases)
    )
    return {
        "passed": passed,
        "output_sha256": hashlib.sha256(encoded).hexdigest() if passed else "",
        "prompt": "person .",
        "box_count": int(len(box_array)),
        "box_shape": list(box_array.shape),
        "max_logit": round(float(logit_array.max()), 6) if len(logit_array) else None,
        "phrases": list(phrases),
        "device": "cpu",
        "config": str(config.name),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.checkpoint, args.image), sort_keys=True))


if __name__ == "__main__":
    main()
