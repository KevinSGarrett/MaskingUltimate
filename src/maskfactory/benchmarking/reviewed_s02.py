"""Diagnostic SAM3-LiteText agreement against Kevin-reviewed S02 silhouettes."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY = ROOT / "qa" / "governance" / "sam3_litetext_reviewed_s02_v1.json"
LOCKED_POLICY_SHA256 = "f42edcfcacc6f8aecdb3d65e108a28043bc6264e92fbcb391694234ca296080f"
CASE_IDS = ("img_c02019c4979c_p2", "img_cea6df6f0f13_p0")
EXPECTED_CHECKPOINT_SHA256 = "69c86fda4d53492cca2a362dae050f3c2b92afa4faedf44262a6b6d082da9906"
EXPECTED_CHECKPOINT_SIZE = 2_117_074_488


class ReviewedS02BenchmarkError(ValueError):
    """The diagnostic policy or its evidence is incomplete, stale, or overclaims."""


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_strict_mask(path: Path) -> np.ndarray:
    array = np.asarray(Image.open(path).convert("L"), dtype=np.uint8)
    values = np.unique(array)
    if not np.isin(values, (0, 255)).all():
        raise ReviewedS02BenchmarkError(f"mask is not strict binary: {path}")
    mask = array == 255
    if not mask.any() or mask.all():
        raise ReviewedS02BenchmarkError(f"mask is degenerate: {path}")
    return mask


def _shifted(mask: np.ndarray, dy: int, dx: int, radius: int) -> np.ndarray:
    height, width = mask.shape
    padded = np.pad(mask, radius, mode="constant", constant_values=False)
    y0 = radius + dy
    x0 = radius + dx
    return padded[y0 : y0 + height, x0 : x0 + width]


def _boundary(mask: np.ndarray) -> np.ndarray:
    eroded = np.ones_like(mask, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            eroded &= _shifted(mask, dy, dx, 1)
    return mask & ~eroded


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    dilated = np.zeros_like(mask, dtype=bool)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            dilated |= _shifted(mask, dy, dx, radius)
    return dilated


def mask_metrics(
    prediction: np.ndarray, reference: np.ndarray, *, boundary_tolerance_px: int = 2
) -> dict[str, float | int]:
    """Compute strict binary overlap and Chebyshev-tolerant boundary metrics."""
    prediction = np.asarray(prediction, dtype=bool)
    reference = np.asarray(reference, dtype=bool)
    if prediction.shape != reference.shape or prediction.ndim != 2:
        raise ReviewedS02BenchmarkError("prediction/reference geometry mismatch")
    if not prediction.any() or prediction.all() or not reference.any() or reference.all():
        raise ReviewedS02BenchmarkError("prediction/reference mask is degenerate")
    if boundary_tolerance_px < 0:
        raise ReviewedS02BenchmarkError("boundary tolerance must be nonnegative")

    intersection = int(np.logical_and(prediction, reference).sum())
    prediction_pixels = int(prediction.sum())
    reference_pixels = int(reference.sum())
    union = prediction_pixels + reference_pixels - intersection
    precision = intersection / prediction_pixels
    recall = intersection / reference_pixels
    prediction_boundary = _boundary(prediction)
    reference_boundary = _boundary(reference)
    prediction_hits = np.logical_and(
        prediction_boundary, _dilate(reference_boundary, boundary_tolerance_px)
    ).sum()
    reference_hits = np.logical_and(
        reference_boundary, _dilate(prediction_boundary, boundary_tolerance_px)
    ).sum()
    boundary_precision = float(prediction_hits / prediction_boundary.sum())
    boundary_recall = float(reference_hits / reference_boundary.sum())
    boundary_f = (
        0.0
        if boundary_precision + boundary_recall == 0
        else 2 * boundary_precision * boundary_recall / (boundary_precision + boundary_recall)
    )
    return {
        "intersection_pixels": intersection,
        "prediction_pixels": prediction_pixels,
        "reference_pixels": reference_pixels,
        "iou": intersection / union,
        "dice": 2 * intersection / (prediction_pixels + reference_pixels),
        "precision": precision,
        "recall": recall,
        "spill_fraction": 1 - precision,
        "miss_fraction": 1 - recall,
        "boundary_precision_2px": boundary_precision,
        "boundary_recall_2px": boundary_recall,
        "boundary_f_2px": boundary_f,
    }


def match_best_instance(
    predictions: Sequence[np.ndarray], reference: np.ndarray
) -> tuple[int, dict[str, float | int]]:
    """Choose the highest-IoU instance, breaking exact ties by lower index."""
    if not predictions:
        raise ReviewedS02BenchmarkError("provider returned no person instances")
    scored = [(index, mask_metrics(mask, reference)) for index, mask in enumerate(predictions)]
    return max(scored, key=lambda row: (float(row[1]["iou"]), -row[0]))


def validate_policy(
    document: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_sha256: str | None = LOCKED_POLICY_SHA256,
) -> None:
    payload = {key: value for key, value in document.items() if key != "sha256"}
    digest = canonical_sha256(payload)
    if document.get("sha256") != digest:
        raise ReviewedS02BenchmarkError("reviewed-S02 policy seal mismatch")
    if expected_sha256 is not None and digest != expected_sha256:
        raise ReviewedS02BenchmarkError("reviewed-S02 policy differs from locked hash")
    if document.get("results_existed_at_freeze") is not False:
        raise ReviewedS02BenchmarkError("policy was not frozen before eligible results")
    provider = document.get("provider", {})
    if provider.get("checkpoint_sha256") != EXPECTED_CHECKPOINT_SHA256:
        raise ReviewedS02BenchmarkError("checkpoint identity drifted")
    if provider.get("checkpoint_size_bytes") != EXPECTED_CHECKPOINT_SIZE:
        raise ReviewedS02BenchmarkError("checkpoint size drifted")
    execution = document.get("execution", {})
    if execution != {
        "prompt": "person",
        "score_threshold": 0.5,
        "mask_threshold": 0.5,
        "deterministic_repetitions": 2,
        "instance_match": "maximum_iou_then_lowest_index",
        "boundary_tolerance_px": 2,
        "boundary_distance": "chebyshev",
        "persist_strict_binary_matched_mask": True,
        "measure_latency_and_peak_vram": True,
        "pass_thresholds": None,
    }:
        raise ReviewedS02BenchmarkError("execution contract drifted")
    limits = document.get("authority_limits", {})
    required_false = (
        "human_anchor_gold_claimed",
        "benchmark_holdout_claimed",
        "official_sam31_comparison_claimed",
        "lower_memory_claimed",
        "quality_noninferiority_claimed",
        "promotion_claimed",
        "production_authority",
        "gold_authority",
    )
    if any(limits.get(name) is not False for name in required_false):
        raise ReviewedS02BenchmarkError("diagnostic authority limits drifted")
    references = document.get("references", [])
    if tuple(row.get("case_id") for row in references) != CASE_IDS:
        raise ReviewedS02BenchmarkError("reviewed-S02 case inventory/order drifted")
    for row in references:
        if row.get("reviewer") != "kevin" or row.get("decision") != "confirmed_valid":
            raise ReviewedS02BenchmarkError("reference lacks Kevin confirmed-valid authority")
        if row.get("truth_tier") != "reviewed_s02_diagnostic_reference_not_gold":
            raise ReviewedS02BenchmarkError("reference truth-tier label drifted")
        for prefix in ("source", "mask", "resolution"):
            path = (Path(root) / row[f"{prefix}_path"]).resolve()
            if not path.is_file() or file_sha256(path) != row[f"{prefix}_file_sha256"]:
                raise ReviewedS02BenchmarkError(f"{row['case_id']} {prefix} artifact drifted")
        source = Image.open(Path(root) / row["source_path"])
        reference = load_strict_mask(Path(root) / row["mask_path"])
        if [source.width, source.height] != row["source_size"]:
            raise ReviewedS02BenchmarkError(f"{row['case_id']} source dimensions drifted")
        if reference.shape != (source.height, source.width):
            raise ReviewedS02BenchmarkError(f"{row['case_id']} mask dimensions drifted")


def load_policy(path: Path = DEFAULT_POLICY, *, root: Path = ROOT) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_policy(document, root=root)
    return document


def verify_evidence(
    document: Mapping[str, Any], *, root: Path = ROOT, policy_path: Path = DEFAULT_POLICY
) -> dict[str, Any]:
    policy = load_policy(policy_path, root=root)
    payload = {key: value for key, value in document.items() if key != "manifest_sha256"}
    if document.get("manifest_sha256") != canonical_sha256(payload):
        raise ReviewedS02BenchmarkError("reviewed-S02 evidence seal mismatch")
    if document.get("policy_sha256") != policy["sha256"]:
        raise ReviewedS02BenchmarkError("reviewed-S02 evidence uses a stale policy")
    if document.get("result") != "pass_diagnostic_measurement_completed":
        raise ReviewedS02BenchmarkError("reviewed-S02 diagnostic did not complete")
    if document.get("authority_limits") != policy["authority_limits"]:
        raise ReviewedS02BenchmarkError("reviewed-S02 evidence overclaims authority")
    provider = document.get("provider", {})
    if provider.get("checkpoint_sha256") != EXPECTED_CHECKPOINT_SHA256:
        raise ReviewedS02BenchmarkError("evidence checkpoint identity drifted")
    cases = document.get("cases", [])
    if tuple(row.get("case_id") for row in cases) != CASE_IDS:
        raise ReviewedS02BenchmarkError("evidence case inventory/order drifted")
    references = {row["case_id"]: row for row in policy["references"]}
    for row in cases:
        reference_row = references[row["case_id"]]
        if row.get("deterministic_two_run") is not True:
            raise ReviewedS02BenchmarkError(f"{row['case_id']} is nondeterministic")
        if row.get("instance_count", 0) <= row.get("matched_instance_index", -1):
            raise ReviewedS02BenchmarkError(f"{row['case_id']} matched index is invalid")
        latencies = row.get("inference_seconds", [])
        if len(latencies) != 2 or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
            for value in latencies
        ):
            raise ReviewedS02BenchmarkError(f"{row['case_id']} latency evidence is invalid")
        mask_path = (Path(root) / row["matched_mask_path"]).resolve()
        if not mask_path.is_file() or file_sha256(mask_path) != row["matched_mask_file_sha256"]:
            raise ReviewedS02BenchmarkError(f"{row['case_id']} matched mask artifact drifted")
        prediction = load_strict_mask(mask_path)
        reference = load_strict_mask(Path(root) / reference_row["mask_path"])
        recomputed = mask_metrics(prediction, reference)
        for name, value in recomputed.items():
            observed = row["metrics"].get(name)
            if isinstance(value, int):
                if observed != value:
                    raise ReviewedS02BenchmarkError(f"{row['case_id']} {name} drifted")
            elif not math.isclose(float(observed), value, rel_tol=0, abs_tol=1e-12):
                raise ReviewedS02BenchmarkError(f"{row['case_id']} {name} drifted")
    return {
        "status": "pass_diagnostic_measurement_completed",
        "policy_sha256": policy["sha256"],
        "case_count": len(cases),
        "minimum_iou": min(float(row["metrics"]["iou"]) for row in cases),
        "minimum_boundary_f_2px": min(float(row["metrics"]["boundary_f_2px"]) for row in cases),
    }
