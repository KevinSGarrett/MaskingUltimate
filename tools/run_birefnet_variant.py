from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as functional
from PIL import Image
from torchvision.transforms.functional import normalize, pil_to_tensor
from transformers import AutoModelForImageSegmentation

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = {
    "birefnet_dynamic": {
        "path": ROOT / "models" / "bv" / "dyn",
        "revision": "280306042f57b7a33854319da62fd86aaa89ec4c",
        "checkpoint_sha256": "e3d2e4884e51ff30f0cd630edc6b1e41b06b7f23a0a2a5169f7b7cb33a711c2d",
        "default_resolution": 0,
    },
    "birefnet_hr": {
        "path": ROOT / "models" / "bv" / "hr",
        "revision": "a7a562f6fd16021180f2f4348f4de003a2d3d1e1",
        "checkpoint_sha256": "9d678bafec0b0019fbb073b7fd02f05ede25dc4b15254f23b2fb0be333200c0d",
        "default_resolution": 1024,
    },
    "birefnet_hr_matting": {
        "path": ROOT / "models" / "bv" / "hrm",
        "revision": "5d6b6f8adcb5b417c871b1d84ceaae9871355b7f",
        "checkpoint_sha256": "a5a4de698739ea5e0e8bbab28e1b293dde95092b87a442d566cbc585c53cef55",
        "default_resolution": 1024,
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _context_box(
    bbox: tuple[float, float, float, float],
    *,
    image_size: tuple[int, int],
    scale: float,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    width, height = (right - left) * scale, (bottom - top) * scale
    return (
        max(0, int(np.floor(center_x - width / 2))),
        max(0, int(np.floor(center_y - height / 2))),
        min(image_size[0], int(np.ceil(center_x + width / 2))),
        min(image_size[1], int(np.ceil(center_y + height / 2))),
    )


def _tensor(image: Image.Image, resolution: int) -> torch.Tensor:
    if resolution:
        image = image.resize((resolution, resolution), Image.Resampling.BILINEAR)
    value = pil_to_tensor(image).float().div_(255)
    value = normalize(value, [0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    if not resolution:
        value = functional.pad(
            value,
            (0, (-value.shape[-1]) % 32, 0, (-value.shape[-2]) % 32),
            mode="replicate",
        )
    return value.unsqueeze(0).to("cuda")


def _predict(
    model,
    tensor: torch.Tensor,
    *,
    native_shape: tuple[int, int],
    resolution: int,
) -> tuple[np.ndarray, float]:
    started = time.perf_counter()
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
        prediction = model(tensor)[-1].sigmoid().float()
        if resolution:
            prediction = functional.interpolate(
                prediction,
                size=native_shape,
                mode="bilinear",
                align_corners=False,
            )
        prediction = prediction[0, 0, : native_shape[0], : native_shape[1]]
    torch.cuda.synchronize()
    return prediction.cpu().numpy(), time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True, choices=sorted(VARIANTS))
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--person-box", type=float, nargs=4, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolution", type=int)
    parser.add_argument("--context-scale", type=float, default=1.25)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    if args.repeats < 2:
        raise ValueError("at least two repeats are required for governed output")
    if args.context_scale < 1:
        raise ValueError("context scale must be at least one")

    variant = VARIANTS[args.variant]
    resolution = variant["default_resolution"] if args.resolution is None else args.resolution
    if resolution not in {0, 1024, 2048}:
        raise ValueError("BiRefNet resolution must be native, 1024, or 2048")
    model_dir = Path(variant["path"])
    checkpoint = model_dir / "model.safetensors"
    if _sha256(checkpoint) != variant["checkpoint_sha256"]:
        raise RuntimeError("BiRefNet checkpoint hash drift")

    image = Image.open(args.image).convert("RGB")
    bbox = tuple(args.person_box)
    left, top, right, bottom = bbox
    if right <= left or bottom <= top:
        raise ValueError("person box must have positive area")
    context_box = _context_box(bbox, image_size=image.size, scale=args.context_scale)
    crop = image.crop(context_box)
    tensor = _tensor(crop, resolution)

    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    model = AutoModelForImageSegmentation.from_pretrained(
        model_dir,
        trust_remote_code=True,
        local_files_only=True,
    ).eval()
    model.to("cuda")
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_started

    predictions: list[np.ndarray] = []
    inference_seconds: list[float] = []
    for _ in range(args.repeats):
        prediction, elapsed = _predict(
            model,
            tensor,
            native_shape=(crop.height, crop.width),
            resolution=resolution,
        )
        predictions.append(prediction)
        inference_seconds.append(elapsed)
    hashes = [hashlib.sha256(value.tobytes()).hexdigest() for value in predictions]
    if len(set(hashes)) != 1:
        raise RuntimeError("BiRefNet confidence output is nondeterministic")

    confidence = np.zeros((image.height, image.width), dtype=np.float32)
    x1, y1, x2, y2 = context_box
    confidence[y1:y2, x1:x2] = predictions[-1]
    if not np.isfinite(confidence).all() or confidence.min() < 0 or confidence.max() > 1:
        raise RuntimeError("BiRefNet output violates finite 0..1 confidence contract")
    binary = confidence >= 0.5
    person_region = binary[y1:y2, x1:x2]
    if not 0.01 < float(person_region.mean()) < 0.99:
        raise RuntimeError("BiRefNet thresholded silhouette is degenerate")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.output, confidence, allow_pickle=False)
    report = {
        "schema_version": "1.0.0",
        "variant": args.variant,
        "repo_revision": variant["revision"],
        "checkpoint": {"path": checkpoint.as_posix(), "sha256": _sha256(checkpoint)},
        "image": {"path": args.image.as_posix(), "sha256": _sha256(args.image)},
        "person_box_xyxy": list(bbox),
        "context_box_xyxy": list(context_box),
        "context_scale": args.context_scale,
        "resolution": resolution or "native_divisible_by_32",
        "repeats": args.repeats,
        "deterministic": True,
        "confidence_shape": list(confidence.shape),
        "confidence_sha256": hashlib.sha256(confidence.tobytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(binary.astype(np.uint8).tobytes()).hexdigest(),
        "output_npy_sha256": _sha256(args.output),
        "foreground_fraction_in_context": float(person_region.mean()),
        "fractional_alpha_fraction_in_context": float(
            ((predictions[-1] > 0.001) & (predictions[-1] < 0.999)).mean()
        ),
        "load_seconds": round(load_seconds, 6),
        "inference_seconds": [round(value, 6) for value in inference_seconds],
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "device": torch.cuda.get_device_name(0),
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
