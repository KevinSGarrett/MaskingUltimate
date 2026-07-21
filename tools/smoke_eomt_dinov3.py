from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, EomtDinov3ForUniversalSegmentation

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "runtime_cache" / "eomt_dinov3_small_602edaa"
FIXTURE = ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg"
OUTPUT = ROOT / "qa" / "live_verification" / "eomt_dinov3_runtime_20260715.json"
REVISION = "602edaa2839daf6cb3de3ad46c176098c3be9090"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if not torch.cuda.is_available():
        raise RuntimeError("EoMT-DINOv3 smoke requires CUDA")
    required = ("README.md", "config.json", "preprocessor_config.json", "model.safetensors")
    if any(not (MODEL / name).is_file() for name in required):
        raise RuntimeError("EoMT-DINOv3 immutable snapshot is incomplete")
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    processor = AutoImageProcessor.from_pretrained(MODEL, local_files_only=True)
    model = (
        EomtDinov3ForUniversalSegmentation.from_pretrained(
            MODEL, local_files_only=True, dtype=torch.float16
        )
        .cuda()
        .eval()
    )
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - started
    with Image.open(FIXTURE) as opened:
        image = opened.convert("RGB")
    inputs = processor(images=image, return_tensors="pt")
    inputs = {
        key: (
            (value.cuda().half() if value.is_floating_point() else value.cuda())
            if isinstance(value, torch.Tensor)
            else value
        )
        for key, value in inputs.items()
    }
    calls = []
    for _ in range(2):
        started = time.perf_counter()
        with torch.inference_mode():
            outputs = model(**inputs)
        torch.cuda.synchronize()
        processed = processor.post_process_panoptic_segmentation(
            outputs, target_sizes=[(image.height, image.width)]
        )[0]
        segmentation = np.asarray(processed["segmentation"].cpu(), dtype=np.int32)
        segments = [
            {
                "id": int(record["id"]),
                "label_id": int(record["label_id"]),
                "score": round(float(record["score"]), 8),
                "was_fused": bool(record.get("was_fused", False)),
            }
            for record in processed["segments_info"]
        ]
        payload = {
            "segmentation_sha256": hashlib.sha256(segmentation.tobytes()).hexdigest(),
            "segments": segments,
        }
        calls.append(
            {
                "payload": payload,
                "payload_sha256": hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "seconds": time.perf_counter() - started,
            }
        )
    if len({call["payload_sha256"] for call in calls}) != 1:
        raise RuntimeError("EoMT-DINOv3 output is nondeterministic")
    if not calls[-1]["payload"]["segments"] or len(np.unique(segmentation)) < 2:
        raise RuntimeError("EoMT-DINOv3 panoptic output is degenerate")
    config = json.loads((MODEL / "config.json").read_text(encoding="utf-8"))
    document = {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "result": "pass",
        "source": {
            "repository": "tue-mps/eomt-dinov3-coco-panoptic-small-640",
            "revision": REVISION,
            "license": "MIT",
        },
        "snapshot": {
            name: {
                "bytes": (MODEL / name).stat().st_size,
                "sha256": _sha256(MODEL / name),
            }
            for name in required
        },
        "fixture": {
            "path": FIXTURE.relative_to(ROOT).as_posix(),
            "sha256": _sha256(FIXTURE),
        },
        "model": {
            "architecture": config["architectures"],
            "pretraining_label_count": len(config["id2label"]),
            "pretraining_label_vocabulary": config["id2label"],
            "output_shape": list(segmentation.shape),
            "segment_count": len(calls[-1]["payload"]["segments"]),
            "payload_sha256": calls[-1]["payload_sha256"],
            "deterministic": True,
            "repeats": 2,
        },
        "runtime": {
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "device": torch.cuda.get_device_name(0),
            "capability": list(torch.cuda.get_device_capability(0)),
            "precision": "float16",
            "load_seconds": round(load_seconds, 6),
            "inference_seconds": [round(call["seconds"], 6) for call in calls],
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        },
        "authority": {
            "lifecycle_state": "installed",
            "shadow_only": True,
            "pretraining_labels_are_not_maskfactory_labels": True,
            "may_author_gold": False,
            "promotion_claimed": False,
        },
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
