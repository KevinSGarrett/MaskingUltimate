"""Run one exact-box SAM 3D Body inference inside its isolated Linux runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

REQUIRED_ARRAYS = (
    "pred_vertices",
    "pred_keypoints_3d",
    "pred_keypoints_2d",
    "pred_cam_t",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _geometry_sha256(output: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    values = {
        "bbox": output["bbox"],
        "focal_length": output["focal_length"],
        **{name: output[name] for name in REQUIRED_ARRAYS},
    }
    for name, value in sorted(values.items()):
        array = np.ascontiguousarray(value, dtype=np.float64)
        digest.update(name.encode("utf-8"))
        digest.update(json.dumps(list(array.shape), separators=(",", ":")).encode("utf-8"))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _extract_one(outputs: Any, requested_bbox: np.ndarray) -> dict[str, np.ndarray]:
    if not isinstance(outputs, (list, tuple)) or len(outputs) != 1:
        raise RuntimeError("SAM 3D Body exact-box inference must return exactly one person")
    raw = outputs[0]
    if not isinstance(raw, Mapping):
        raise RuntimeError("SAM 3D Body output must be a mapping")
    try:
        result = {
            "bbox": np.asarray(raw.get("bbox")),
            "focal_length": np.asarray(raw.get("focal_length")),
            **{name: np.asarray(raw.get(name)) for name in REQUIRED_ARRAYS},
        }
        finite = all(array.size > 0 and np.isfinite(array).all() for array in result.values())
    except (TypeError, ValueError) as exc:
        raise RuntimeError("SAM 3D Body returned non-numeric geometry") from exc
    if result["bbox"].reshape(-1).shape != (4,) or not np.allclose(
        result["bbox"].reshape(-1), requested_bbox, rtol=0.0, atol=1.0
    ):
        raise RuntimeError("SAM 3D Body returned a different person box")
    if not finite:
        raise RuntimeError("SAM 3D Body returned empty or non-finite geometry")
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--mhr", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--bbox", nargs=4, type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--inference-type", choices=("full", "body"), default="full")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.repeats != 2:
        raise ValueError("governed SAM 3D Body runner requires exactly two repeats")
    required_paths = (
        args.source_root,
        args.checkpoint,
        args.mhr,
        args.runtime_lock,
        args.image,
    )
    if not all(path.exists() for path in required_paths):
        raise FileNotFoundError("one or more governed SAM 3D Body inputs are missing")
    source_commit = subprocess.check_output(  # noqa: S603 - exact fixed git probe
        ("git", "-C", str(args.source_root), "rev-parse", "HEAD"),
        text=True,
        timeout=30,
    ).strip()
    if source_commit != args.expected_source_commit:
        raise RuntimeError("SAM 3D Body source commit mismatch")
    source_status = subprocess.check_output(  # noqa: S603 - exact fixed git probe
        (
            "git",
            "-C",
            str(args.source_root),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ),
        text=True,
        timeout=30,
    ).strip()
    if source_status:
        raise RuntimeError("SAM 3D Body tracked source tree is dirty")

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(0)
    np.random.seed(0)
    sys.path.insert(0, str(args.source_root))

    import torch
    from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body

    if not torch.cuda.is_available():
        raise RuntimeError("SAM 3D Body governed runner requires CUDA")
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)

    load_started = time.perf_counter()
    model, model_cfg = load_sam_3d_body(str(args.checkpoint), device="cuda", mhr_path=str(args.mhr))
    torch.cuda.synchronize()
    model_load_latency_ms = (time.perf_counter() - load_started) * 1000.0
    estimator = SAM3DBodyEstimator(
        sam_3d_body_model=model,
        model_cfg=model_cfg,
        human_detector=None,
        human_segmentor=None,
        fov_estimator=None,
    )
    model_vram_bytes = int(torch.cuda.memory_allocated())
    requested_bbox = np.asarray(args.bbox, dtype=np.float32)
    if (
        not np.isfinite(requested_bbox).all()
        or requested_bbox[2] <= requested_bbox[0]
        or requested_bbox[3] <= requested_bbox[1]
    ):
        raise ValueError("governed SAM 3D Body runner requires one valid finite xyxy box")
    outputs: list[dict[str, np.ndarray]] = []
    output_hashes: list[str] = []
    latency_ms: list[float] = []
    peak_vram_bytes: list[int] = []
    for _ in range(args.repeats):
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        started = time.perf_counter()
        raw = estimator.process_one_image(
            str(args.image),
            bboxes=requested_bbox.reshape(1, 4),
            inference_type=args.inference_type,
        )
        torch.cuda.synchronize()
        latency_ms.append((time.perf_counter() - started) * 1000.0)
        peak_vram_bytes.append(int(torch.cuda.max_memory_allocated()))
        output = _extract_one(raw, requested_bbox)
        outputs.append(output)
        output_hashes.append(_geometry_sha256(output))
    deterministic = len(set(output_hashes)) == 1
    if not deterministic:
        raise RuntimeError("SAM 3D Body two-run geometry output is not deterministic")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, **outputs[0])
    checkpoint_root = args.checkpoint.parent
    report = {
        "schema_version": "1.0.0",
        "provider": "sam3d_body",
        "source_commit": source_commit,
        "source_tree_clean": True,
        "runtime_lock_sha256": _sha256(args.runtime_lock),
        "checkpoint_assets": {
            "model.ckpt": _sha256(args.checkpoint),
            "model_config.yaml": _sha256(checkpoint_root / "model_config.yaml"),
            "assets/mhr_model.pt": _sha256(args.mhr),
        },
        "image": {"sha256": _sha256(args.image)},
        "requested_bbox_xyxy": [float(value) for value in requested_bbox],
        "inference_type": args.inference_type,
        "repeats": args.repeats,
        "deterministic": deterministic,
        "geometry_output_sha256": output_hashes[0],
        "output_npz_sha256": _sha256(args.output),
        "array_shapes": {name: list(value.shape) for name, value in outputs[0].items()},
        "cold_latency_ms": latency_ms[0],
        "warm_latency_ms": latency_ms[1],
        "model_load_latency_ms": model_load_latency_ms,
        "model_vram_bytes": model_vram_bytes,
        "peak_inference_vram_bytes": max(peak_vram_bytes),
        "authority": "shadow_geometry_challenger_only",
        "may_author_gold": False,
    }
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
