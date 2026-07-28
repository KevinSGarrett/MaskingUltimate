"""Corrected strict SAM 3D Body repeatability runner with warm-up and raw capture.

V3 supersedes the unexecuted V2 startup candidate only.  It preserves V2's
strict measured-repeat logic and explicitly injects the immutable source root
before importing the official ``sam_3d_body`` package.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.run_sam3d_body_repeatability_v2 import (  # noqa: E402
    MEASURED_REPEATS,
    _configure_determinism,
    _evaluate_measured_repeats,
    _parse_args,
    _persist_measured_output,
    _require_clean_source,
    _run_one,
    _sha256,
)


def _inject_source_root(source_root: Path) -> None:
    """Make the immutable official source tree importable exactly once."""
    source = str(source_root)
    if source not in sys.path:
        sys.path.insert(0, source)


def main() -> int:
    args = _parse_args()
    if args.repeats != MEASURED_REPEATS:
        raise ValueError("governed SAM 3D Body v3 runner requires exactly two measured repeats")
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
        raise FileExistsError("governed SAM 3D Body v3 output directory already exists")
    source_commit = _require_clean_source(args.source_root, args.expected_source_commit)
    requested_bbox = np.asarray(args.bbox, dtype=np.float32)
    if (
        not np.isfinite(requested_bbox).all()
        or requested_bbox[2] <= requested_bbox[0]
        or requested_bbox[3] <= requested_bbox[1]
    ):
        raise ValueError("governed SAM 3D Body runner requires one valid finite xyxy box")

    _inject_source_root(args.source_root)
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
        "schema_version": "3.0.0",
        "provider": "sam3d_body",
        "runner": "sam3d_body_repeatability_v3",
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
        "source_root_import_injected": str(args.source_root),
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
        raise RuntimeError("SAM 3D Body v3 measured repeats are not byte-exact; raw outputs retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
