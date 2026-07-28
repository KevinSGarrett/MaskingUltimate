from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = Path("/home/kevin/mfmodels/sam3-litetext-s0-b09766e5")
DEFAULT_FIXTURE = ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg"
DEFAULT_OUTPUT = ROOT / "qa" / "live_verification" / "sam3_litetext_s0_runtime_20260715.json"
DEFAULT_MASK = ROOT / "qa" / "live_verification" / "sam3_litetext_s0_person_mask_20260715.png"
CHECKPOINT_SHA256 = "69c86fda4d53492cca2a362dae050f3c2b92afa4faedf44262a6b6d082da9906"
CHECKPOINT_SIZE = 2_117_074_488
CHECKPOINT_REVISION = "b09766e54f5d2eba021119ec7feff13e74c0f8fc"
SOURCE_COMMIT = "bef17f5c24dc5ef19dc1d8e9663345a2ae7f2f5a"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _cuda_inputs(inputs: Any, *, dtype: torch.dtype) -> dict[str, Any]:
    prepared: dict[str, Any] = {}
    for key, value in inputs.items():
        if not isinstance(value, torch.Tensor):
            prepared[key] = value
        elif value.is_floating_point():
            prepared[key] = value.to(device="cuda", dtype=dtype)
        else:
            prepared[key] = value.to(device="cuda")
    return prepared


def _predict(
    model: Any,
    processor: Any,
    inputs: dict[str, Any],
    target_sizes: list[list[int]],
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    with torch.inference_mode():
        outputs = model(**inputs)
    torch.cuda.synchronize()
    latency_seconds = time.perf_counter() - started
    result = processor.post_process_instance_segmentation(
        outputs,
        threshold=0.5,
        mask_threshold=0.5,
        target_sizes=target_sizes,
    )[0]
    masks = result["masks"].detach().cpu().to(torch.uint8).numpy()
    boxes = result["boxes"].detach().cpu().float().numpy()
    scores = result["scores"].detach().cpu().float().numpy()
    if masks.ndim != 3 or masks.shape[0] == 0:
        raise RuntimeError("SAM3-LiteText returned no person masks")
    if boxes.shape != (masks.shape[0], 4) or scores.shape != (masks.shape[0],):
        raise RuntimeError("SAM3-LiteText result geometry is incoherent")
    if not np.isin(masks, (0, 1)).all():
        raise RuntimeError("SAM3-LiteText masks are not strict binary arrays")
    if not np.isfinite(boxes).all() or not np.isfinite(scores).all():
        raise RuntimeError("SAM3-LiteText boxes or scores are non-finite")
    if not np.logical_and(scores >= 0, scores <= 1).all():
        raise RuntimeError("SAM3-LiteText scores are outside 0..1")
    return {
        "masks": masks,
        "boxes": boxes,
        "scores": scores,
        "mask_sha256": hashlib.sha256(masks.tobytes()).hexdigest(),
        "boxes_sha256": hashlib.sha256(boxes.tobytes()).hexdigest(),
        "scores_sha256": hashlib.sha256(scores.tobytes()).hexdigest(),
    }, latency_seconds


def _failure_boundary() -> str:
    try:
        AutoModel.from_pretrained(
            "/home/kevin/mfmodels/missing-sam3-litetext-checkpoint",
            local_files_only=True,
        )
    except OSError as exc:
        if "missing-sam3-litetext-checkpoint" not in str(exc):
            raise RuntimeError("missing-checkpoint failure did not identify its path") from exc
        return "local_missing_checkpoint_refused_without_network_fallback"
    raise RuntimeError("missing SAM3-LiteText checkpoint did not fail closed")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live SAM3-LiteText S0 shadow smoke")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mask-output", type=Path, default=DEFAULT_MASK)
    parser.add_argument("--prompt", default="person")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    model_dir = args.model.resolve()
    fixture = args.fixture.resolve()
    checkpoint = model_dir / "model.safetensors"
    if checkpoint.stat().st_size != CHECKPOINT_SIZE:
        raise RuntimeError("SAM3-LiteText checkpoint size drift")
    if _sha256(checkpoint) != CHECKPOINT_SHA256:
        raise RuntimeError("SAM3-LiteText checkpoint hash drift")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")

    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=True)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    free_before, total_memory = torch.cuda.mem_get_info()
    dtype = torch.bfloat16

    load_started = time.perf_counter()
    processor = AutoProcessor.from_pretrained(model_dir, local_files_only=True)
    model = AutoModel.from_pretrained(
        model_dir,
        dtype=dtype,
        local_files_only=True,
    ).eval()
    model.to("cuda")
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_started

    image = Image.open(fixture).convert("RGB")
    encoded = processor(images=image, text=args.prompt, return_tensors="pt")
    target_sizes = encoded["original_sizes"].detach().cpu().tolist()
    inputs = _cuda_inputs(encoded, dtype=dtype)
    first, first_seconds = _predict(model, processor, inputs, target_sizes)
    second, second_seconds = _predict(model, processor, inputs, target_sizes)
    for key in ("mask_sha256", "boxes_sha256", "scores_sha256"):
        if first[key] != second[key]:
            raise RuntimeError(f"SAM3-LiteText output is nondeterministic: {key}")

    masks = second["masks"]
    foreground_pixels = [int(mask.sum()) for mask in masks]
    if any(count <= 0 or count >= image.width * image.height for count in foreground_pixels):
        raise RuntimeError("SAM3-LiteText produced a degenerate person mask")
    union = np.any(masks.astype(bool), axis=0).astype(np.uint8) * 255
    if union.shape != (image.height, image.width):
        raise RuntimeError("SAM3-LiteText result does not match source dimensions")
    args.mask_output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(union, mode="L").save(args.mask_output)
    persisted = np.asarray(Image.open(args.mask_output).convert("L"), dtype=np.uint8)
    if persisted.shape != union.shape or not np.array_equal(persisted, union):
        raise RuntimeError("persisted SAM3-LiteText strict mask changed on round trip")

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "result": "pass_installed_shadow_smoke_official_comparison_pending",
        "provider": "sam3_litetext_s0",
        "source_commit": SOURCE_COMMIT,
        "checkpoint": {
            "revision": CHECKPOINT_REVISION,
            "path": str(model_dir),
            "filename": checkpoint.name,
            "size_bytes": checkpoint.stat().st_size,
            "sha256": CHECKPOINT_SHA256,
        },
        "runtime": {
            "environment": sys.prefix,
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "transformers": __import__("transformers").__version__,
            "device": torch.cuda.get_device_name(0),
            "capability": list(torch.cuda.get_device_capability(0)),
            "dtype": str(dtype).removeprefix("torch."),
            "device_total_bytes": total_memory,
            "device_free_before_bytes": free_before,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        },
        "fixture": {
            "path": fixture.relative_to(ROOT).as_posix(),
            "sha256": _sha256(fixture),
            "width": image.width,
            "height": image.height,
            "prompt": args.prompt,
        },
        "observations": {
            "load_seconds": round(load_seconds, 6),
            "inference_seconds": [round(first_seconds, 6), round(second_seconds, 6)],
            "instance_count": int(masks.shape[0]),
            "foreground_pixels": foreground_pixels,
            "mask_stack_sha256": second["mask_sha256"],
            "boxes_sha256": second["boxes_sha256"],
            "scores_sha256": second["scores_sha256"],
            "union_mask_sha256": hashlib.sha256(union.tobytes()).hexdigest(),
            "persisted_mask_path": args.mask_output.relative_to(ROOT).as_posix(),
            "persisted_mask_file_sha256": _sha256(args.mask_output),
            "strict_binary_png": True,
            "deterministic_two_run": True,
        },
        "failure_behavior": _failure_boundary(),
        "authority": {
            "lifecycle_state": "installed",
            "role_eligibility": "shadow_only_experiment",
            "official_reference": "sam3_1",
            "substitution_forbidden": True,
            "promotion_claimed": False,
            "production_authority": False,
            "gold_authority": False,
        },
        "comparison": {
            "official_sam31_checkpoint_available": False,
            "lower_memory_than_official_claimed": False,
            "quality_noninferiority_claimed": False,
            "human_anchor_benchmark": "pending",
        },
    }
    document["manifest_sha256"] = _canonical_sha256(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
