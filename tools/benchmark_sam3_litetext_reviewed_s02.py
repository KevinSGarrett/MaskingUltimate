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
sys.path.insert(0, str(ROOT / "src"))

from maskfactory.benchmarking.reviewed_s02 import (  # noqa: E402
    DEFAULT_POLICY,
    EXPECTED_CHECKPOINT_SHA256,
    EXPECTED_CHECKPOINT_SIZE,
    PRE_RESULT_POLICY_COMMIT,
    canonical_sha256,
    file_sha256,
    load_policy,
    match_best_instance,
    verify_evidence,
)

DEFAULT_MODEL = Path("/home/kevin/mfmodels/sam3-litetext-s0-b09766e5")
DEFAULT_OUTPUT = ROOT / "qa" / "live_verification" / "sam3_litetext_reviewed_s02_20260715.json"
DEFAULT_MASK_DIR = ROOT / "qa" / "live_verification" / "sam3_litetext_reviewed_s02_masks"


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
    *,
    score_threshold: float,
    mask_threshold: float,
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    with torch.inference_mode():
        outputs = model(**inputs)
    torch.cuda.synchronize()
    latency_seconds = time.perf_counter() - started
    result = processor.post_process_instance_segmentation(
        outputs,
        threshold=score_threshold,
        mask_threshold=mask_threshold,
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
    return {
        "masks": masks,
        "boxes": boxes,
        "scores": scores,
        "mask_stack_sha256": hashlib.sha256(masks.tobytes()).hexdigest(),
        "boxes_sha256": hashlib.sha256(boxes.tobytes()).hexdigest(),
        "scores_sha256": hashlib.sha256(scores.tobytes()).hexdigest(),
    }, latency_seconds


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure shadow-only SAM3-LiteText against reviewed S02 silhouettes"
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mask-dir", type=Path, default=DEFAULT_MASK_DIR)
    return parser.parse_args()


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def main() -> int:
    args = _parse_args()
    policy = load_policy(args.policy)
    checkpoint = args.model.resolve() / "model.safetensors"
    if checkpoint.stat().st_size != EXPECTED_CHECKPOINT_SIZE:
        raise RuntimeError("SAM3-LiteText checkpoint size drift")
    if file_sha256(checkpoint) != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("SAM3-LiteText checkpoint hash drift")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")

    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=True)
    torch.cuda.empty_cache()
    dtype = torch.bfloat16
    free_before, total_memory = torch.cuda.mem_get_info()
    load_started = time.perf_counter()
    processor = AutoProcessor.from_pretrained(args.model, local_files_only=True)
    model = AutoModel.from_pretrained(args.model, dtype=dtype, local_files_only=True).eval()
    model.to("cuda")
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - load_started

    args.mask_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    execution = policy["execution"]
    for reference_row in policy["references"]:
        image = Image.open(ROOT / reference_row["source_path"]).convert("RGB")
        reference_array = np.asarray(
            Image.open(ROOT / reference_row["mask_path"]).convert("L"), dtype=np.uint8
        )
        reference = reference_array == 255
        encoded = processor(images=image, text=execution["prompt"], return_tensors="pt")
        target_sizes = encoded["original_sizes"].detach().cpu().tolist()
        inputs = _cuda_inputs(encoded, dtype=dtype)
        torch.cuda.reset_peak_memory_stats()
        first, first_seconds = _predict(
            model,
            processor,
            inputs,
            target_sizes,
            score_threshold=execution["score_threshold"],
            mask_threshold=execution["mask_threshold"],
        )
        second, second_seconds = _predict(
            model,
            processor,
            inputs,
            target_sizes,
            score_threshold=execution["score_threshold"],
            mask_threshold=execution["mask_threshold"],
        )
        for name in ("mask_stack_sha256", "boxes_sha256", "scores_sha256"):
            if first[name] != second[name]:
                raise RuntimeError(f"{reference_row['case_id']} nondeterministic {name}")
        predictions = [mask.astype(bool) for mask in second["masks"]]
        matched_index, metrics = match_best_instance(predictions, reference)
        matched = predictions[matched_index]
        mask_path = args.mask_dir / f"{reference_row['case_id']}_matched.png"
        Image.fromarray(matched.astype(np.uint8) * 255, mode="L").save(mask_path)
        round_trip = np.asarray(Image.open(mask_path).convert("L"), dtype=np.uint8)
        if not np.array_equal(round_trip, matched.astype(np.uint8) * 255):
            raise RuntimeError(f"{reference_row['case_id']} matched mask changed on round trip")
        cases.append(
            {
                "case_id": reference_row["case_id"],
                "image_id": reference_row["image_id"],
                "instance_id": reference_row["instance_id"],
                "instance_count": int(second["masks"].shape[0]),
                "matched_instance_index": matched_index,
                "matched_score": float(second["scores"][matched_index]),
                "matched_box_xyxy": [float(value) for value in second["boxes"][matched_index]],
                "inference_seconds": [round(first_seconds, 6), round(second_seconds, 6)],
                "peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
                "peak_reserved_bytes": int(torch.cuda.max_memory_reserved()),
                "mask_stack_sha256": second["mask_stack_sha256"],
                "boxes_sha256": second["boxes_sha256"],
                "scores_sha256": second["scores_sha256"],
                "deterministic_two_run": True,
                "matched_mask_path": _relative(mask_path),
                "matched_mask_file_sha256": file_sha256(mask_path),
                "matched_mask_array_sha256": hashlib.sha256(
                    matched.astype(np.uint8).tobytes()
                ).hexdigest(),
                "metrics": metrics,
            }
        )
        del inputs, encoded, first, second
        torch.cuda.empty_cache()

    metric_names = ("iou", "dice", "precision", "recall", "boundary_f_2px")
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "result": "pass_diagnostic_measurement_completed",
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["sha256"],
        "execution_identity": {
            "tool_path": _relative(Path(__file__)),
            "tool_file_sha256": file_sha256(Path(__file__)),
            "pre_result_policy_commit": PRE_RESULT_POLICY_COMMIT,
        },
        "provider": {
            **policy["provider"],
            "checkpoint_path": str(checkpoint),
        },
        "runtime": {
            "environment": sys.prefix,
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "transformers": __import__("transformers").__version__,
            "device": torch.cuda.get_device_name(0),
            "device_total_bytes": total_memory,
            "device_free_before_bytes": free_before,
            "dtype": str(dtype).removeprefix("torch."),
            "model_load_seconds": round(load_seconds, 6),
        },
        "cases": cases,
        "aggregate": {
            f"mean_{name}": sum(float(row["metrics"][name]) for row in cases) / len(cases)
            for name in metric_names
        }
        | {
            f"minimum_{name}": min(float(row["metrics"][name]) for row in cases)
            for name in metric_names
        },
        "authority_limits": policy["authority_limits"],
        "interpretation": (
            "Absolute diagnostic agreement against two Kevin-reviewed S02 semantic silhouettes; "
            "not gold, not a frozen holdout, and not an official SAM3.1 comparison."
        ),
    }
    document["manifest_sha256"] = canonical_sha256(document)
    verify_evidence(document, root=ROOT, policy_path=args.policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_evidence(
        json.loads(args.output.read_text(encoding="utf-8")), root=ROOT, policy_path=args.policy
    )
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
