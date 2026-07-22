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
from PIL import Image
from torchvision.transforms.functional import to_tensor

SOURCE_REVISION = "d3bb5a1ebedf259a5453c6d168e6840fff85581e"
CHECKPOINT_REVISION = "40c894a6f68d1f55c86ab0de838d89dc61587930"
CHECKPOINT_SHA256 = "70d3bf1d85d0aaf2020f9ef3577239f4f83b77c2ba47fca1eebaaf872f9ad40f"
CHECKPOINT_SIZE_BYTES = 141199924
CONFIG_SHA256 = "48dfbea235039093873586f352f0d05fbfdcbfeda094f2d8b257bc6408e68063"
RESNET50_FILENAME = "resnet50-19c8e357.pth"
RESNET50_SHA256 = "19c8e3572231adff6824a2da93fd67b5986919a2e65f8b6007eab4edee220097"
RESNET50_SIZE_BYTES = 102502400
RESNET18_FILENAME = "resnet18-5c106cde.pth"
RESNET18_SHA256 = "5c106cde386e87d4033832f2996f5493238eda96ccf559d1d62760c4de0613f8"
RESNET18_SIZE_BYTES = 46827520
ROUTES = {"static_first_frame_refinement", "temporal_propagation"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inputs(frame_paths: list[Path], mask_path: Path) -> tuple[list[np.ndarray], np.ndarray]:
    frames = [
        np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8).copy() for path in frame_paths
    ]
    if not frames:
        raise ValueError("MatAnyone2 requires at least one frame")
    shape = frames[0].shape
    if any(frame.shape != shape for frame in frames):
        raise ValueError("MatAnyone2 frame geometry must be identical")
    mask = np.asarray(Image.open(mask_path).convert("L"), dtype=np.uint8)
    if mask.shape != shape[:2]:
        raise ValueError("MatAnyone2 initial mask geometry must match the frames")
    mask = np.where(mask > 0, 255, 0).astype(np.uint8)
    if not mask.any() or (mask > 0).all():
        raise ValueError("MatAnyone2 initial mask must be nondegenerate")
    return frames, mask


def _run_once(model, frames: list[np.ndarray], mask: np.ndarray, warmup: int) -> np.ndarray:
    from matanyone2.inference.inference_core import InferenceCore

    processor = InferenceCore(model, cfg=model.cfg, device="cuda:0")
    sequence = [frames[0]] * warmup + frames
    outputs: list[np.ndarray] = []
    for index, frame in enumerate(sequence):
        image = to_tensor(frame).float().to("cuda:0")
        if index == 0:
            processor.step(image, torch.from_numpy(mask).float().to("cuda:0"), objects=[1])
            output = processor.step(image, first_frame_pred=True)
        elif index <= warmup:
            output = processor.step(image, first_frame_pred=True)
        else:
            output = processor.step(image)
        alpha = np.ascontiguousarray(
            processor.output_prob_to_mask(output).detach().float().cpu().numpy(),
            dtype=np.float32,
        )
        if index >= warmup:
            outputs.append(alpha)
    torch.cuda.synchronize()
    return np.stack(outputs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--torch-home", type=Path, required=True)
    parser.add_argument("--frames", type=Path, nargs="+", required=True)
    parser.add_argument("--initial-mask", type=Path, required=True)
    parser.add_argument("--route", choices=sorted(ROUTES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--warmup", type=int, default=3)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    if args.repeats < 2:
        raise ValueError("at least two repeats are required for governed output")
    if args.warmup < 1:
        raise ValueError("MatAnyone2 warmup must be positive")
    if args.route == "static_first_frame_refinement" and len(args.frames) != 1:
        raise ValueError("static_first_frame_refinement requires exactly one frame")
    if args.route == "temporal_propagation" and len(args.frames) < 2:
        raise ValueError("temporal_propagation requires at least two frames")
    checkpoint = args.model_dir / "model.safetensors"
    config = args.model_dir / "config.json"
    if (
        checkpoint.stat().st_size != CHECKPOINT_SIZE_BYTES
        or _sha256(checkpoint) != CHECKPOINT_SHA256
    ):
        raise RuntimeError("MatAnyone2 checkpoint drift")
    if _sha256(config) != CONFIG_SHA256:
        raise RuntimeError("MatAnyone2 config drift")
    backbone_specs = (
        (RESNET50_FILENAME, RESNET50_SIZE_BYTES, RESNET50_SHA256),
        (RESNET18_FILENAME, RESNET18_SIZE_BYTES, RESNET18_SHA256),
    )
    backbone_paths: dict[str, Path] = {}
    for filename, size_bytes, sha256 in backbone_specs:
        path = args.torch_home / "hub" / "checkpoints" / filename
        if not path.is_file():
            raise RuntimeError(f"MatAnyone2 backbone is missing from governed storage: {filename}")
        if path.stat().st_size != size_bytes or _sha256(path) != sha256:
            raise RuntimeError(f"MatAnyone2 backbone drift: {filename}")
        backbone_paths[filename] = path
    os.environ["TORCH_HOME"] = str(args.torch_home.resolve())

    frames, mask = _inputs(list(args.frames), args.initial_mask)
    sys.path.insert(0, str(args.source_root.resolve()))
    from matanyone2.model.matanyone2 import MatAnyone2

    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    load_started = time.perf_counter()
    model = MatAnyone2.from_pretrained(str(args.model_dir.resolve())).to("cuda:0").eval()
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_started

    predictions: list[np.ndarray] = []
    inference_seconds: list[float] = []
    for _ in range(args.repeats):
        started = time.perf_counter()
        predictions.append(_run_once(model, frames, mask, args.warmup))
        inference_seconds.append(time.perf_counter() - started)
    hashes = [hashlib.sha256(value.tobytes()).hexdigest() for value in predictions]
    if len(set(hashes)) != 1:
        raise RuntimeError("MatAnyone2 alpha sequence is nondeterministic")
    alphas = predictions[-1]
    if alphas.shape != (len(frames), *mask.shape):
        raise RuntimeError("MatAnyone2 alpha sequence geometry mismatch")
    if not np.isfinite(alphas).all() or alphas.min() < 0 or alphas.max() > 1:
        raise RuntimeError("MatAnyone2 alpha sequence violates finite 0..1 contract")
    if any(not alpha.any() or (alpha >= 0.5).all() for alpha in alphas):
        raise RuntimeError("MatAnyone2 produced a degenerate alpha frame")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, alphas=alphas)
    report = {
        "schema_version": "1.0.0",
        "provider": "matanyone2",
        "source_revision": SOURCE_REVISION,
        "checkpoint_revision": CHECKPOINT_REVISION,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "config_sha256": CONFIG_SHA256,
        "backbone_sha256s": {filename: _sha256(path) for filename, path in backbone_paths.items()},
        "route": args.route,
        "frame_count": len(frames),
        "frame_sha256s": [_sha256(path) for path in args.frames],
        "initial_mask_sha256": _sha256(args.initial_mask),
        "semantic_authority": False,
        "repeats": args.repeats,
        "deterministic": True,
        "alpha_shape": list(alphas.shape),
        "alpha_sha256": hashes[-1],
        "output_npz_sha256": _sha256(args.output),
        "fractional_alpha_fraction": float(((alphas > 0.001) & (alphas < 0.999)).mean()),
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
