"""Exercise the official SAM 3.1 multiplex checkpoint on one governed JPEG."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

ARTIFACT_FIELDS = ("masks", "object_ids", "probabilities", "boxes_xywh")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_sha256(arrays: Mapping[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for name in ARTIFACT_FIELDS:
        value = np.ascontiguousarray(arrays[name])
        digest.update(name.encode("utf-8"))
        digest.update(value.dtype.str.encode("ascii"))
        digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("utf-8"))
        digest.update(value.tobytes())
    return digest.hexdigest()


def _extract(outputs: Any) -> dict[str, np.ndarray]:
    if not isinstance(outputs, Mapping):
        raise RuntimeError("SAM 3.1 multiplex output must be a mapping")
    try:
        arrays = {
            "masks": np.asarray(outputs["out_binary_masks"]),
            "object_ids": np.asarray(outputs["out_obj_ids"]),
            "probabilities": np.asarray(outputs["out_probs"]),
            "boxes_xywh": np.asarray(outputs["out_boxes_xywh"]),
        }
    except KeyError as exc:
        raise RuntimeError("SAM 3.1 multiplex output fields are incomplete") from exc
    if (
        arrays["masks"].dtype != np.bool_
        or arrays["masks"].ndim != 3
        or arrays["masks"].shape[0] != 1
        or not arrays["masks"].any()
        or arrays["object_ids"].shape != (1,)
        or int(arrays["object_ids"][0]) != 1
        or arrays["probabilities"].shape != (1,)
        or arrays["boxes_xywh"].shape != (1, 4)
        or not np.isfinite(arrays["probabilities"]).all()
        or not np.isfinite(arrays["boxes_xywh"]).all()
    ):
        raise RuntimeError("SAM 3.1 multiplex output geometry is invalid")
    return arrays


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--requirements-lock", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--repeats", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = _args()
    if args.repeats != 2:
        raise ValueError("governed SAM 3.1 smoke requires exactly two repeats")
    if args.image.suffix.lower() not in {".jpg", ".jpeg"}:
        raise ValueError("governed SAM 3.1 smoke input must be a JPEG")
    required = (
        args.source_root,
        args.checkpoint,
        args.runtime_lock,
        args.requirements_lock,
        args.image,
    )
    if not all(path.exists() for path in required):
        raise FileNotFoundError("one or more governed SAM 3.1 smoke inputs are missing")
    source_commit = subprocess.check_output(  # noqa: S603 - exact fixed git probe
        ("git", "-C", str(args.source_root), "rev-parse", "HEAD"),
        text=True,
        timeout=30,
    ).strip()
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
    if source_commit != args.expected_source_commit or source_status:
        raise RuntimeError("SAM 3.1 source identity is stale or dirty")

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(0)
    np.random.seed(0)
    sys.path.insert(0, str(args.source_root))
    import torch
    from sam3.model_builder import build_sam3_predictor

    if not torch.cuda.is_available():
        raise RuntimeError("SAM 3.1 governed smoke requires CUDA")
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)

    load_started = time.perf_counter()
    predictor = build_sam3_predictor(
        checkpoint_path=str(args.checkpoint),
        version="sam3.1",
        compile=False,
        warm_up=False,
        max_num_objects=16,
        multiplex_count=16,
        use_fa3=False,
        use_rope_real=True,
        async_loading_frames=False,
    )
    torch.cuda.synchronize()
    model_load_latency_ms = (time.perf_counter() - load_started) * 1000.0
    model_vram_bytes = int(torch.cuda.memory_allocated())
    outputs: list[dict[str, np.ndarray]] = []
    hashes: list[str] = []
    latency_ms: list[float] = []
    peak_vram_bytes: list[int] = []
    with tempfile.TemporaryDirectory(prefix="maskfactory-sam31-frame-") as directory:
        frame_dir = Path(directory)
        shutil.copyfile(args.image, frame_dir / "00000.jpg")
        for _ in range(args.repeats):
            session_id = None
            try:
                session_id = predictor.handle_request(
                    {"type": "start_session", "resource_path": str(frame_dir)}
                )["session_id"]
                torch.cuda.reset_peak_memory_stats()
                torch.cuda.synchronize()
                started = time.perf_counter()
                response = predictor.handle_request(
                    {
                        "type": "add_prompt",
                        "session_id": session_id,
                        "frame_index": 0,
                        "points": [[0.5, 0.5]],
                        "point_labels": [1],
                        "obj_id": 1,
                    }
                )
                torch.cuda.synchronize()
                latency_ms.append((time.perf_counter() - started) * 1000.0)
                peak_vram_bytes.append(int(torch.cuda.max_memory_allocated()))
                arrays = _extract(response["outputs"])
                outputs.append(arrays)
                hashes.append(_payload_sha256(arrays))
            finally:
                if session_id is not None:
                    predictor.handle_request({"type": "close_session", "session_id": session_id})
    if len(set(hashes)) != 1:
        raise RuntimeError("SAM 3.1 two-run multiplex output is not deterministic")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, **outputs[0])
    report = {
        "schema_version": "1.0.0",
        "provider": "sam3_1",
        "source_commit": source_commit,
        "source_tree_clean": True,
        "runtime_lock_sha256": _sha256(args.runtime_lock),
        "requirements_lock_sha256": _sha256(args.requirements_lock),
        "checkpoint_sha256": _sha256(args.checkpoint),
        "image_sha256": _sha256(args.image),
        "builder": "build_sam3_predictor",
        "version": "sam3.1",
        "adaptation": "single_frame_directory_via_object_multiplex",
        "prompt": {"type": "positive_point", "relative_xy": [0.5, 0.5], "obj_id": 1},
        "repeats": 2,
        "deterministic": True,
        "mask_payload_sha256": hashes[0],
        "output_npz_sha256": _sha256(args.output),
        "artifact_shapes": {name: list(value.shape) for name, value in outputs[0].items()},
        "model_load_latency_ms": model_load_latency_ms,
        "cold_latency_ms": latency_ms[0],
        "warm_latency_ms": latency_ms[1],
        "model_vram_bytes": model_vram_bytes,
        "peak_inference_vram_bytes": max(peak_vram_bytes),
        "authority": "runtime_smoke_only_no_candidate_serving_or_gold_authority",
        "may_author_gold": False,
    }
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
