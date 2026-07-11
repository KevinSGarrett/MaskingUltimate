"""Production multi-prompt GroundingDINO box proposals in pinned WSL source env."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import groundingdino
from groundingdino.util.inference import load_image, load_model, predict
from PIL import Image


def run(
    checkpoint: Path,
    image_path: Path,
    prompts: tuple[str, ...],
    *,
    box_threshold: float,
    text_threshold: float,
) -> dict:
    package = Path(groundingdino.__file__).resolve().parent
    config = package / "config" / "GroundingDINO_SwinT_OGC.py"
    model = load_model(str(config), str(checkpoint), device="cpu")
    _, image = load_image(str(image_path))
    with Image.open(image_path) as opened:
        width, height = opened.size
    proposals = []
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
            proposals.append(
                {
                    "prompt": prompt,
                    "bbox_xyxy": [
                        float((cx - box_width / 2) * width),
                        float((cy - box_height / 2) * height),
                        float((cx + box_width / 2) * width),
                        float((cy + box_height / 2) * height),
                    ],
                    "box_score": float(score),
                    "text_score": float(score),
                    "phrase": phrase,
                    "authority": "proposal_only",
                }
            )
    return {
        "schema_version": "1.0.0",
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
