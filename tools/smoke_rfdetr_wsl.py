from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from rfdetr import RFDETRMedium


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_detections(detections) -> list[dict[str, object]]:
    names = detections.data.get("class_name")
    records: list[dict[str, object]] = []
    for index, box in enumerate(detections.xyxy):
        record: dict[str, object] = {
            "class_id": int(detections.class_id[index]),
            "confidence": round(float(detections.confidence[index]), 8),
            "xyxy": [round(float(value), 5) for value in box],
        }
        if names is not None:
            record["class_name"] = str(names[index])
        records.append(record)
    return sorted(
        records,
        key=lambda item: (
            int(item["class_id"]),
            -float(item["confidence"]),
            tuple(item["xyxy"]),
        ),
    )


def _output_hash(records: list[dict[str, object]]) -> str:
    payload = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Live RF-DETR medium CUDA smoke")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--optimize-dtype", choices=("float16", "float32"), default="float16")
    parser.add_argument("--compile", action="store_true")
    args = parser.parse_args()

    if not args.checkpoint.is_file():
        raise FileNotFoundError(f"checkpoint not found: {args.checkpoint}")
    if not args.image.is_file():
        raise FileNotFoundError(f"image not found: {args.image}")
    if args.repeats < 2:
        raise ValueError("repeats must be at least two for determinism evidence")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")

    torch.manual_seed(0)
    np.random.seed(0)
    torch.cuda.manual_seed_all(0)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()

    image = Image.open(args.image).convert("RGB")
    build_started = time.perf_counter()
    model = RFDETRMedium(pretrain_weights=str(args.checkpoint), device="cuda")
    torch.cuda.synchronize()
    build_seconds = time.perf_counter() - build_started

    optimize_started = time.perf_counter()
    model.optimize_for_inference(compile=args.compile, dtype=args.optimize_dtype)
    torch.cuda.synchronize()
    optimization_seconds = time.perf_counter() - optimize_started

    hashes: list[str] = []
    latencies: list[float] = []
    canonical: list[dict[str, object]] = []
    for _ in range(args.repeats):
        started = time.perf_counter()
        detections = model.predict(image, threshold=args.threshold)
        torch.cuda.synchronize()
        latencies.append(time.perf_counter() - started)
        canonical = _canonical_detections(detections)
        hashes.append(_output_hash(canonical))

    if len(set(hashes)) != 1:
        raise RuntimeError(f"nondeterministic output hashes: {hashes}")
    people = [record for record in canonical if record.get("class_name") == "person"]
    if not people:
        raise RuntimeError("smoke fixture produced no person detections")

    report = {
        "build_seconds": round(build_seconds, 6),
        "checkpoint": {
            "bytes": args.checkpoint.stat().st_size,
            "path": str(args.checkpoint),
            "sha256": _sha256(args.checkpoint),
        },
        "cuda": {
            "capability": list(torch.cuda.get_device_capability(0)),
            "device": torch.cuda.get_device_name(0),
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
            "runtime": torch.version.cuda,
        },
        "detections": canonical,
        "deterministic": True,
        "image": {
            "bytes": args.image.stat().st_size,
            "path": str(args.image),
            "sha256": _sha256(args.image),
            "size": list(image.size),
        },
        "latency_seconds": [round(value, 6) for value in latencies],
        "optimization": {
            "compile": args.compile,
            "dtype": args.optimize_dtype,
            "seconds": round(optimization_seconds, 6),
        },
        "output_sha256": hashes[0],
        "person_count": len(people),
        "repeats": args.repeats,
        "rfdetr": importlib.metadata.version("rfdetr"),
        "threshold": args.threshold,
        "torch": torch.__version__,
        "torchvision": importlib.metadata.version("torchvision"),
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
