"""Geometry-restored Sapiens/SCHP probability output for the S03 provider boundary."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from smoke_sapiens_seg_wsl import infer as infer_sapiens
from smoke_schp_wsl import infer as infer_schp

SAPIENS_TILE_SIZE = 1536
SAPIENS_TILE_OVERLAP = 128


def _restore(probabilities: np.ndarray, width: int, height: int) -> np.ndarray:
    return np.stack(
        [
            cv2.resize(channel, (width, height), interpolation=cv2.INTER_LINEAR)
            for channel in probabilities
        ]
    ).astype(np.float32)


def _starts(length: int) -> list[int]:
    if length <= SAPIENS_TILE_SIZE:
        return [0]
    starts = list(
        range(
            0,
            length - SAPIENS_TILE_SIZE + 1,
            SAPIENS_TILE_SIZE - SAPIENS_TILE_OVERLAP,
        )
    )
    if starts[-1] != length - SAPIENS_TILE_SIZE:
        starts.append(length - SAPIENS_TILE_SIZE)
    return starts


def _sapiens_tiled(checkpoint: Path, image_path: Path) -> tuple[np.ndarray, int]:
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    total = np.zeros((28, height, width), dtype=np.float32)
    weights = np.zeros((height, width), dtype=np.float32)
    tile_count = 0
    with tempfile.TemporaryDirectory(prefix="maskfactory-sapiens-tiles-") as temporary:
        for top in _starts(height):
            for left in _starts(width):
                right = min(width, left + SAPIENS_TILE_SIZE)
                bottom = min(height, top + SAPIENS_TILE_SIZE)
                tile_path = Path(temporary) / f"tile_{top}_{left}.png"
                image.crop((left, top, right, bottom)).save(tile_path, format="PNG")
                tile = infer_sapiens(checkpoint, tile_path, use_bf16=True)
                tile = _restore(tile, right - left, bottom - top)
                total[:, top:bottom, left:right] += tile
                weights[top:bottom, left:right] += 1
                tile_count += 1
    return np.divide(
        total,
        weights[None, :, :],
        out=np.zeros_like(total),
        where=weights[None, :, :] > 0,
    ), tile_count


def run(parser: str, checkpoint: Path, image_path: Path, output_path: Path) -> dict:
    with Image.open(image_path) as opened:
        width, height = opened.size
    if parser == "sapiens":
        restored, tile_count = _sapiens_tiled(checkpoint, image_path)
    elif parser == "schp_atr":
        probabilities = infer_schp(checkpoint, image_path, "atr")
        restored = _restore(probabilities, width, height)
        tile_count = 1
    else:
        raise ValueError(f"unsupported parser: {parser}")
    normalizer = restored.sum(axis=0, keepdims=True)
    restored = np.divide(
        restored,
        normalizer,
        out=np.zeros_like(restored),
        where=normalizer > 0,
    )
    labels = restored.argmax(axis=0).astype(np.uint8)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output_path, labels=labels, probabilities=restored)
    return {
        "parser": parser,
        "labels_shape": list(labels.shape),
        "probabilities_shape": list(restored.shape),
        "min": float(restored.min()),
        "max": float(restored.max()),
        "tile_count": tile_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parser", choices=("sapiens", "schp_atr"), required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.parser, args.checkpoint, args.image, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
