"""Production multi-prompt GroundingDINO box proposals in pinned WSL source env."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path

import groundingdino
from groundingdino.util.inference import load_image, load_model, predict
from PIL import Image

SOURCE_REVISION = "856dde20aee659246248e20734ef9ba5214f5e44"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(
    checkpoint: Path,
    image_path: Path,
    prompts: tuple[str, ...],
    *,
    box_threshold: float,
    text_threshold: float,
) -> dict:
    if not all(isinstance(prompt, str) and prompt.strip() for prompt in prompts) or len(
        set(prompts)
    ) != len(prompts):
        raise ValueError("prompts must be unique non-empty strings")
    if not 0 <= box_threshold <= 1 or not 0 <= text_threshold <= 1:
        raise ValueError("thresholds must be in 0..1")
    package = Path(groundingdino.__file__).resolve().parent
    config = package / "config" / "GroundingDINO_SwinT_OGC.py"
    model = load_model(str(config), str(checkpoint), device="cpu")
    _, image = load_image(str(image_path))
    with Image.open(image_path) as opened:
        width, height = opened.size
    proposals = []
    try:
        for prompt in prompts:
            boxes, logits, phrases = predict(
                model=model,
                image=image,
                caption=prompt + " .",
                box_threshold=box_threshold,
                text_threshold=text_threshold,
                device="cpu",
            )
            for box, score, phrase in zip(
                boxes.detach().cpu().numpy(),
                logits.detach().cpu().numpy(),
                phrases,
                strict=True,
            ):
                cx, cy, box_width, box_height = box
                left = max(0.0, float((cx - box_width / 2) * width))
                top = max(0.0, float((cy - box_height / 2) * height))
                right = min(float(width), float((cx + box_width / 2) * width))
                bottom = min(float(height), float((cy + box_height / 2) * height))
                if right <= left or bottom <= top:
                    continue
                proposals.append(
                    {
                        "prompt": prompt,
                        "bbox_xyxy": [left, top, right, bottom],
                        "box_score": float(score),
                        "text_score": float(score),
                        "phrase": phrase,
                        "authority": "proposal_only",
                    }
                )
    finally:
        del model
    return {
        "protocol_version": 1,
        "schema_version": "1.0.0",
        "checkpoint_sha256": _sha256(checkpoint),
        "source_revision": SOURCE_REVISION,
        "device_type": "cpu",
        "device": platform.processor() or "cpu",
        "model_load_count": 1,
        "prompts": list(prompts),
        "box_threshold": box_threshold,
        "text_threshold": text_threshold,
        "image_size": [width, height],
        "authority": "proposal_boxes_only",
        "may_write_final_masks": False,
        "proposals": proposals,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--prompts-json", required=True)
    parser.add_argument("--box-threshold", type=float, required=True)
    parser.add_argument("--text-threshold", type=float, required=True)
    args = parser.parse_args()
    prompts = tuple(json.loads(args.prompts_json))
    print(
        json.dumps(
            run(
                args.checkpoint,
                args.image,
                prompts,
                box_threshold=args.box_threshold,
                text_threshold=args.text_threshold,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
