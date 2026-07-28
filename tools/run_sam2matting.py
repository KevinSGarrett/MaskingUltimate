from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch
import torch.nn.functional as functional
from PIL import Image

SOURCE_REVISION = "73dd721d77b56749248aefe5e8824d7f61b9d13c"
CHECKPOINT_REVISION = "4315db9c60d27fde396b09765748a0ca6c97bed5"
CHECKPOINT_SHA256 = "1f0eb2eda3e8bc9101eafc0b30b8b8fcae1ff83d8fd3adc18e2f3b410fdaae60"
CHECKPOINT_SIZE_BYTES = 383180506
MODEL_CONFIG = "configs/sam2matting-sam2.1base+.yaml"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_inputs(image_path: Path, prior_path: Path) -> tuple[Image.Image, np.ndarray]:
    image = Image.open(image_path).convert("RGB")
    prior_image = Image.open(prior_path).convert("L")
    if prior_image.size != image.size:
        raise ValueError("SAM2Matting prior mask geometry must match the source image")
    prior = np.asarray(prior_image) > 0
    if not prior.any() or prior.all():
        raise ValueError("SAM2Matting prior mask must be nondegenerate")
    return image, prior


def _predict(predictor, image_tensor: torch.Tensor, prior: np.ndarray) -> np.ndarray:
    raw_mask = torch.from_numpy(prior)
    mask_input = raw_mask.float().mul(20).sub(10).unsqueeze(0).unsqueeze(0)
    mask_input = functional.interpolate(
        mask_input,
        size=(256, 256),
        mode="bilinear",
        align_corners=False,
    )
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        _, alpha, _ = predictor.predict(
            img=image_tensor,
            raw_mask=raw_mask,
            mask_input=mask_input,
            multimask_output=False,
        )
    torch.cuda.synchronize()
    return np.ascontiguousarray(np.asarray(alpha, dtype=np.float32).squeeze())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--prior-mask", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    if args.repeats < 2:
        raise ValueError("at least two repeats are required for governed output")
    if not 0 < args.threshold < 1:
        raise ValueError("SAM2Matting threshold must be within 0..1")
    if not args.source_root.is_dir():
        raise FileNotFoundError(f"SAM2Matting source root is missing: {args.source_root}")
    if args.checkpoint.stat().st_size != CHECKPOINT_SIZE_BYTES:
        raise RuntimeError("SAM2Matting checkpoint size drift")
    if _sha256(args.checkpoint) != CHECKPOINT_SHA256:
        raise RuntimeError("SAM2Matting checkpoint SHA-256 drift")

    image, prior = _load_inputs(args.image, args.prior_mask)
    sys.path.insert(0, str(args.source_root.resolve()))
    from sam2.build_sam import build_sam2matting
    from sam2.sam2matting_image_predictor import SAM2MattingImagePredictor

    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    model = build_sam2matting(MODEL_CONFIG, str(args.checkpoint.resolve()))
    predictor = SAM2MattingImagePredictor(model)
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_started

    embed_started = time.perf_counter()
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        image_tensor = predictor.set_image(image)
    torch.cuda.synchronize()
    embed_seconds = time.perf_counter() - embed_started

    predictions: list[np.ndarray] = []
    inference_seconds: list[float] = []
    for _ in range(args.repeats):
        started = time.perf_counter()
        predictions.append(_predict(predictor, image_tensor, prior))
        inference_seconds.append(time.perf_counter() - started)
    hashes = [hashlib.sha256(value.tobytes()).hexdigest() for value in predictions]
    if len(set(hashes)) != 1:
        raise RuntimeError("SAM2Matting alpha output is nondeterministic")

    alpha = predictions[-1]
    if alpha.shape != prior.shape:
        raise RuntimeError("SAM2Matting alpha geometry mismatch")
    if not np.isfinite(alpha).all() or alpha.min() < 0 or alpha.max() > 1:
        raise RuntimeError("SAM2Matting alpha violates finite 0..1 contract")
    binary = alpha >= args.threshold
    if not binary.any() or binary.all():
        raise RuntimeError("SAM2Matting thresholded mask is degenerate")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.output, alpha, allow_pickle=False)
    preview_path = args.output.with_suffix(".png")
    Image.fromarray(np.rint(alpha * 255).astype(np.uint8), mode="L").save(preview_path)
    report = {
        "schema_version": "1.0.0",
        "provider": "sam2matting_base_plus",
        "source_revision": SOURCE_REVISION,
        "checkpoint_revision": CHECKPOINT_REVISION,
        "checkpoint": {
            "path": args.checkpoint.as_posix(),
            "sha256": _sha256(args.checkpoint),
            "size_bytes": args.checkpoint.stat().st_size,
        },
        "image": {
            "path": args.image.as_posix(),
            "sha256": _sha256(args.image),
            "shape": [image.height, image.width],
        },
        "prior_mask": {
            "path": args.prior_mask.as_posix(),
            "sha256": _sha256(args.prior_mask),
            "payload_sha256": hashlib.sha256(prior.astype(np.uint8).tobytes()).hexdigest(),
            "foreground_fraction": float(prior.mean()),
        },
        "semantic_authority": False,
        "threshold": args.threshold,
        "repeats": args.repeats,
        "deterministic": True,
        "alpha_shape": list(alpha.shape),
        "alpha_sha256": hashes[-1],
        "output_npy_sha256": _sha256(args.output),
        "output_png_sha256": _sha256(preview_path),
        "binary_sha256": hashlib.sha256(binary.astype(np.uint8).tobytes()).hexdigest(),
        "foreground_fraction": float(binary.mean()),
        "fractional_alpha_fraction": float(((alpha > 0.001) & (alpha < 0.999)).mean()),
        "load_seconds": round(load_seconds, 6),
        "embed_seconds": round(embed_seconds, 6),
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
