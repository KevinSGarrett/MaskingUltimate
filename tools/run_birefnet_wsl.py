"""Production BiRefNet confidence inference inside the pinned WSL CUDA environment."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as functional
from huggingface_hub import snapshot_download
from PIL import Image
from torchvision.transforms.functional import normalize, pil_to_tensor
from transformers import AutoModelForImageSegmentation

REPO_ID = "ZhengPeng7/BiRefNet"
REVISION = "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4"
DEFAULT_TILE_SIZE = 2048
DEFAULT_TILE_OVERLAP = 128


def _load_model(checkpoint: Path):
    source = snapshot_download(
        repo_id=REPO_ID,
        revision=REVISION,
        ignore_patterns=["*.safetensors", "*.bin", "*.pth", "*.onnx"],
    )
    temporary = tempfile.TemporaryDirectory(prefix="maskfactory-birefnet-")
    model_dir = Path(temporary.name) / "model"
    shutil.copytree(source, model_dir, symlinks=False)
    (model_dir / "model.safetensors").symlink_to(checkpoint.resolve())
    model = AutoModelForImageSegmentation.from_pretrained(
        model_dir, trust_remote_code=True, local_files_only=True
    ).eval()
    model.to(torch.device("cuda"))
    return model, temporary


def _predict_tile(model, image: Image.Image) -> np.ndarray:
    tensor = pil_to_tensor(image).float().div_(255)
    tensor = normalize(tensor, [0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    height, width = tensor.shape[-2:]
    pad_height = (-height) % 32
    pad_width = (-width) % 32
    if pad_height or pad_width:
        tensor = functional.pad(
            tensor,
            (0, pad_width, 0, pad_height),
            mode="replicate",
        )
    tensor = tensor.unsqueeze(0).to("cuda")
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
        prediction = model(tensor)[-1].sigmoid().float()[0, 0, :height, :width]
    output = prediction.cpu().numpy()
    del tensor, prediction
    return output


def _starts(length: int, *, tile_size: int, tile_overlap: int) -> list[int]:
    if length <= tile_size:
        return [0]
    starts = list(range(0, length - tile_size + 1, tile_size - tile_overlap))
    if starts[-1] != length - tile_size:
        starts.append(length - tile_size)
    return starts


def run(
    checkpoint: Path,
    image_path: Path,
    output_path: Path,
    *,
    tile_size: int = DEFAULT_TILE_SIZE,
    tile_overlap: int = DEFAULT_TILE_OVERLAP,
) -> dict[str, object]:
    if tile_size <= 0 or tile_overlap < 0 or tile_overlap >= tile_size:
        raise ValueError("tile contract requires 0 <= overlap < tile size")
    model, temporary = _load_model(checkpoint)
    try:
        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        total = np.zeros((height, width), dtype=np.float32)
        weights = np.zeros((height, width), dtype=np.float32)
        tile_count = 0
        for top in _starts(height, tile_size=tile_size, tile_overlap=tile_overlap):
            for left in _starts(width, tile_size=tile_size, tile_overlap=tile_overlap):
                right, bottom = min(width, left + tile_size), min(height, top + tile_size)
                prediction = _predict_tile(model, image.crop((left, top, right, bottom)))
                total[top:bottom, left:right] += prediction
                weights[top:bottom, left:right] += 1
                tile_count += 1
        confidence = np.divide(total, weights, out=np.zeros_like(total), where=weights > 0)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(output_path, confidence.astype(np.float32), allow_pickle=False)
        return {
            "protocol_version": 1,
            "model_revision": REVISION,
            "precision": "fp16",
            "shape": list(confidence.shape),
            "min": float(confidence.min()),
            "max": float(confidence.max()),
            "tile_count": tile_count,
            "tile_size": tile_size,
            "tile_overlap": tile_overlap,
            "device": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
        }
    finally:
        del model
        torch.cuda.empty_cache()
        temporary.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tile-size", type=int, default=DEFAULT_TILE_SIZE)
    parser.add_argument("--tile-overlap", type=int, default=DEFAULT_TILE_OVERLAP)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.checkpoint,
                args.image,
                args.output,
                tile_size=args.tile_size,
                tile_overlap=args.tile_overlap,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
