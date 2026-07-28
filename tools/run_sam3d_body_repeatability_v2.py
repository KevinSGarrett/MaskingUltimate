"""Strict warm-up and raw-capture SAM 3D Body repeatability requalification runner.

This is deliberately separate from ``run_sam3d_body.py``.  It cannot promote a
provider or relax the established byte-equality gate.  Its only new behavior is
to record a non-evaluated warm-up and retain both measured raw outputs before
reporting a strict mismatch.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.run_sam3d_body import (  # noqa: E402
    REQUIRED_ARRAYS,
    _extract_one,
    _geometry_sha256,
    _repeat_diagnostics,
    _sha256,
)


MEASURED_REPEATS = 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--mhr", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--bbox", nargs=4, type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--repeats", type=int, default=MEASURED_REPEATS)
    parser.add_argument("--inference-type", choices=("full", "body"), default="full")
    return parser.parse_args()


def _require_clean_source(source_root: Path, expected_commit: str) -> str:
    source_commit = subprocess.check_output(
        ("git", "-C", str(source_root), "rev-parse", "HEAD"), text=True, timeout=30
    ).strip()
    if source_commit != expected_commit:
        raise RuntimeError("SAM 3D Body source commit mismatch")
    source_status = subprocess.check_output(
        (
            "git",
            "-C",
            str(source_root),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ),
        text=True,
        timeout=30,
    ).strip()
    if source_status:
        raise RuntimeError("SAM 3D Body tracked source tree is dirty")
    return source_commit


def _configure_determinism() -> Any:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    os.environ.setdefault("NVIDIA_TF32_OVERRIDE", "0")
    random.seed(0)
    np.random.seed(0)

    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("SAM 3D Body governed runner requires CUDA")
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cuda.enable_flash_sdp(False)
    torch.backends.cuda.enable_mem_efficient_sdp(False)
    if hasattr(torch.backends.cuda, "enable_cudnn_sdp"):
        torch.backends.cuda.enable_cudnn_sdp(False)
    torch.backends.cuda.enable_math_sdp(True)
    torch.use_deterministic_algorithms(True)
    return torch


def _run_one(
    estimator: Any,
    *,
    image: Path,
    requested_bbox: np.ndarray,
    inference_type: str,
    torch: Any,
) -> tuple[dict[str, np.ndarray], float, int]:
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    started = time.perf_counter()
    raw = estimator.process_one_image(
        str(image), bboxes=requested_bbox.reshape(1, 4), inference_type=inference_type
    )
    torch.cuda.synchronize()
    latency_ms = (time.perf_counter() - started) * 1000.0
    peak_vram_bytes = int(torch.cuda.max_memory_allocated())
    return _extract_one(raw, requested_bbox), latency_ms, peak_vram_bytes


def _persist_measured_output(output: Mapping[str, np.ndarray], path: Path) -> dict[str, Any]:
    """Persist raw measured geometry before any equality verdict is computed."""
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite measured geometry: {path}")
    values = {
        "bbox": output["bbox"],
        "focal_length": output["focal_length"],
        **{name: output[name] for name in REQUIRED_ARRAYS},
    }
    np.savez_compressed(path, **values)
    return {
        "path": path.name,
        "npz_sha256": _sha256(path),
        "geometry_sha256": _geometry_sha256(output),
        "array_shapes": {name: list(value.shape) for name, value in values.items()},
    }


def _evaluate_measured_repeats(
    *, warmup: Mapping[str, np.ndarray], measured: Sequence[Mapping[str, np.ndarray]]
) -> dict[str, Any]:
    """Keep the warm-up outside the strict two-repeat verdict."""
    if len(measured) != MEASURED_REPEATS:
        raise ValueError("governed SAM 3D Body v2 runner requires exactly two measured repeats")
    comparison = _repeat_diagnostics(measured[0], measured[1])
    return {
        "warmup_geometry_sha256": _geometry_sha256(warmup),
        "measured_geometry_sha256_by_repeat": [
            _geometry_sha256(measured[0]),
            _geometry_sha256(measured[1]),
        ],
        "repeat_comparison": comparison,
        "deterministic": comparison["all_arrays_exact"],
    }


def main() -> int:
    args = _parse_args()
    if args.repeats != MEASURED_REPEATS:
        raise ValueError("governed SAM 3D Body v2 runner requires exactly two measured repeats")
    required_paths = (
        args.source_root,
        args.checkpoint,
        args.mhr,
        args.runtime_lock,
        args.image,
    )
    if not all(path.exists() for path in required_paths):
        raise FileNotFoundError("one or more governed SAM 3D Body inputs are missing")
    if args.output_dir.exists():
        raise FileExistsError("governed SAM 3D Body v2 output directory already exists")
    source_commit = _require_clean_source(args.source_root, args.expected_source_commit)
    requested_bbox = np.asarray(args.bbox, dtype=np.float32)
    if (
        not np.isfinite(requested_bbox).all()
        or requested_bbox[2] <= requested_bbox[0]
        or requested_bbox[3] <= requested_bbox[1]
    ):
        raise ValueError("governed SAM 3D Body runner requires one valid finite xyxy box")

    torch = _configure_determinism()
    from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body

    load_started = time.perf_counter()
    model, model_cfg = load_sam_3d_body(
        str(args.checkpoint), device="cuda", mhr_path=str(args.mhr)
    )
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

    args.output_dir.mkdir(parents=True)
    warmup, warmup_latency_ms, warmup_peak_vram_bytes = _run_one(
        estimator,
        image=args.image,
        requested_bbox=requested_bbox,
        inference_type=args.inference_type,
        torch=torch,
    )
    measured: list[dict[str, np.ndarray]] = []
    measured_latency_ms: list[float] = []
    measured_peak_vram_bytes: list[int] = []
    persisted: list[dict[str, Any]] = []
    for index in range(MEASURED_REPEATS):
        output, latency_ms, peak_vram_bytes = _run_one(
            estimator,
            image=args.image,
            requested_bbox=requested_bbox,
            inference_type=args.inference_type,
            torch=torch,
        )
        measured.append(output)
        measured_latency_ms.append(latency_ms)
        measured_peak_vram_bytes.append(peak_vram_bytes)
        persisted.append(
            _persist_measured_output(output, args.output_dir / f"measured_repeat_{index + 1}.npz")
        )

    evaluation = _evaluate_measured_repeats(warmup=warmup, measured=measured)
    checkpoint_root = args.checkpoint.parent
    report = {
        "schema_version": "2.0.0",
        "provider": "sam3d_body",
        "runner": "sam3d_body_repeatability_v2",
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
        "warmup": {
            "evaluated_for_repeatability": False,
            "geometry_sha256": evaluation["warmup_geometry_sha256"],
            "latency_ms": warmup_latency_ms,
            "peak_vram_bytes": warmup_peak_vram_bytes,
        },
        "measured_repeats": MEASURED_REPEATS,
        "measured_outputs": persisted,
        "measured_latency_ms": measured_latency_ms,
        "model_load_latency_ms": model_load_latency_ms,
        "model_vram_bytes": model_vram_bytes,
        "peak_inference_vram_bytes": max(measured_peak_vram_bytes),
        "deterministic": evaluation["deterministic"],
        "measured_geometry_sha256_by_repeat": evaluation["measured_geometry_sha256_by_repeat"],
        "repeat_comparison": evaluation["repeat_comparison"],
        "authority": "shadow_geometry_challenger_only",
        "may_author_gold": False,
    }
    report_path = args.output_dir / "repeatability_report.json"
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    if not report["deterministic"]:
        raise RuntimeError("SAM 3D Body v2 measured repeats are not byte-exact; raw outputs retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
