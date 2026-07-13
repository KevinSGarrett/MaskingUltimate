"""Geometry-restored Sapiens/SCHP probability output for the S03 provider boundary."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from smoke_sapiens_seg_wsl import infer_with_model as infer_sapiens_with_model
from smoke_sapiens_seg_wsl import load_model as load_sapiens_model
from smoke_schp_wsl import infer as infer_schp

SAPIENS_TILE_SIZE = 1536
SAPIENS_TILE_OVERLAP = 128
SAPIENS_MODEL_REVISION = "ea5545c735d1fc994d0d1aafede27df892761322"
SCHP_MODEL_REVISION = "eb84c432cc697f494d99662a05f2335eb2f26095"


def _restore(probabilities: np.ndarray, width: int, height: int) -> np.ndarray:
    return np.stack(
        [
            cv2.resize(channel, (width, height), interpolation=cv2.INTER_LINEAR)
            for channel in probabilities
        ]
    ).astype(np.float32)


def _starts(length: int, *, tile_size: int, tile_overlap: int) -> list[int]:
    if length <= tile_size:
        return [0]
    starts = list(
        range(
            0,
            length - tile_size + 1,
            tile_size - tile_overlap,
        )
    )
    if starts[-1] != length - tile_size:
        starts.append(length - tile_size)
    return starts


def _sapiens_tiled(
    checkpoint: Path, image_path: Path, *, tile_size: int, tile_overlap: int
) -> tuple[np.ndarray, int]:
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    total = np.zeros((28, height, width), dtype=np.float32)
    weights = np.zeros((height, width), dtype=np.float32)
    tile_count = 0
    model = load_sapiens_model(checkpoint)
    try:
        with tempfile.TemporaryDirectory(prefix="maskfactory-sapiens-tiles-") as temporary:
            for top in _starts(height, tile_size=tile_size, tile_overlap=tile_overlap):
                for left in _starts(width, tile_size=tile_size, tile_overlap=tile_overlap):
                    right = min(width, left + tile_size)
                    bottom = min(height, top + tile_size)
                    tile_path = Path(temporary) / f"tile_{top}_{left}.png"
                    image.crop((left, top, right, bottom)).save(tile_path, format="PNG")
                    tile = infer_sapiens_with_model(model, tile_path, use_bf16=True)
                    tile = _restore(tile, right - left, bottom - top)
                    total[:, top:bottom, left:right] += tile
                    weights[top:bottom, left:right] += 1
                    tile_count += 1
    finally:
        del model
        torch.cuda.empty_cache()
    return (
        np.divide(
            total,
            weights[None, :, :],
            out=np.zeros_like(total),
            where=weights[None, :, :] > 0,
        ),
        tile_count,
    )


def run(
    parser: str,
    checkpoint: Path,
    image_path: Path,
    output_path: Path,
    *,
    sapiens_long_side: int = 1024,
    tile_size: int = SAPIENS_TILE_SIZE,
    tile_overlap: int = SAPIENS_TILE_OVERLAP,
) -> dict:
    if sapiens_long_side != 1024:
        raise ValueError("pinned Sapiens TorchScript requires long_side=1024")
    if tile_size <= 0 or tile_overlap < 0 or tile_overlap >= tile_size:
        raise ValueError("tile contract requires 0 <= overlap < tile size")
    with Image.open(image_path) as opened:
        width, height = opened.size
    if parser == "sapiens":
        restored, tile_count = _sapiens_tiled(
            checkpoint, image_path, tile_size=tile_size, tile_overlap=tile_overlap
        )
        model_revision = SAPIENS_MODEL_REVISION
        precision = "bf16"
        model_input = [1024, 768]
        dataset = None
    elif parser == "schp_atr":
        probabilities = infer_schp(checkpoint, image_path, "atr")
        restored = _restore(probabilities, width, height)
        tile_count = 1
        model_revision = SCHP_MODEL_REVISION
        precision = "fp32"
        model_input = [512, 512]
        dataset = "atr"
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
        "protocol_version": 1,
        "parser": parser,
        "class_count": int(restored.shape[0]),
        "model_revision": model_revision,
        "precision": precision,
        "model_input": model_input,
        "dataset": dataset,
        "labels_shape": list(labels.shape),
        "probabilities_shape": list(restored.shape),
        "min": float(restored.min()),
        "max": float(restored.max()),
        "tile_count": tile_count,
        "tile_size": tile_size if parser == "sapiens" else None,
        "tile_overlap": tile_overlap if parser == "sapiens" else None,
        "device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parser", choices=("sapiens", "schp_atr"), required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sapiens-long-side", type=int, default=1024)
    parser.add_argument("--tile-size", type=int, default=SAPIENS_TILE_SIZE)
    parser.add_argument("--tile-overlap", type=int, default=SAPIENS_TILE_OVERLAP)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.parser,
                args.checkpoint,
                args.image,
                args.output,
                sapiens_long_side=args.sapiens_long_side,
                tile_size=args.tile_size,
                tile_overlap=args.tile_overlap,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
