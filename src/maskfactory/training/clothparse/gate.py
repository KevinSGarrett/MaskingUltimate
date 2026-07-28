"""Clothing/material parser promotion gate (doc 12 section 6.2)."""

from __future__ import annotations

import json
import math
import os
import uuid
from pathlib import Path
from typing import Any

BASELINE_MODEL_FAMILY = "schp_atr_plus_s08_heuristics"
REQUIRED_SPLIT = "test_holdout"
THIN_CLASS_IOU_MIN = 0.55


class ClothingGateError(ValueError):
    """Clothing promotion evidence is incomplete or not comparable."""


def _unit_metric(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ClothingGateError(f"{name} must be a numeric metric in [0, 1]")
    try:
        metric = float(value)
    except (TypeError, ValueError) as exc:
        raise ClothingGateError(f"{name} must be a numeric metric in [0, 1]") from exc
    if not math.isfinite(metric) or not 0 <= metric <= 1:
        raise ClothingGateError(f"{name} must be a numeric metric in [0, 1]")
    return metric


def _class_iou(row: dict[str, Any], class_name: str) -> float:
    per_class = row.get("per_class")
    if not isinstance(per_class, dict):
        raise ClothingGateError("candidate leaderboard row lacks per_class metrics")
    metrics = per_class.get(class_name)
    if not isinstance(metrics, dict) or "iou" not in metrics:
        raise ClothingGateError(f"candidate leaderboard row lacks {class_name} IoU")
    return _unit_metric(metrics["iou"], f"candidate {class_name} IoU")


def evaluate_clothing_promotion_gate(
    candidate_row: dict[str, Any], baseline_row: dict[str, Any]
) -> dict[str, object]:
    """Evaluate the indivisible material-mIoU and thin-class promotion gate."""
    if baseline_row.get("model_family") != BASELINE_MODEL_FAMILY:
        raise ClothingGateError(f"clothing promotion baseline must be {BASELINE_MODEL_FAMILY}")
    if candidate_row.get("model_family") == BASELINE_MODEL_FAMILY:
        raise ClothingGateError("candidate cannot be the clothing baseline")

    candidate_dataset = candidate_row.get("dataset_ref")
    baseline_dataset = baseline_row.get("dataset_ref")
    if not isinstance(candidate_dataset, str) or not candidate_dataset:
        raise ClothingGateError("candidate dataset_ref is missing")
    if candidate_dataset != baseline_dataset:
        raise ClothingGateError("clothing comparison requires the same dataset_ref")

    candidate_split = candidate_row.get("split")
    baseline_split = baseline_row.get("split")
    if candidate_split != baseline_split:
        raise ClothingGateError("clothing comparison requires the same split")
    if candidate_split != REQUIRED_SPLIT:
        raise ClothingGateError("clothing promotion requires a frozen test_holdout comparison")

    candidate_miou = _unit_metric(candidate_row.get("mean_iou"), "candidate material mIoU")
    baseline_miou = _unit_metric(baseline_row.get("mean_iou"), "baseline material mIoU")
    strap_iou = _class_iou(candidate_row, "strap")
    waistband_iou = _class_iou(candidate_row, "waistband")
    checks = {
        "material_mean_iou_beats_baseline": {
            "candidate": candidate_miou,
            "baseline": baseline_miou,
            "operator": "gt",
            "passed": candidate_miou > baseline_miou,
        },
        "strap_iou": {
            "measured": strap_iou,
            "operator": "gte",
            "threshold": THIN_CLASS_IOU_MIN,
            "passed": strap_iou >= THIN_CLASS_IOU_MIN,
        },
        "waistband_iou": {
            "measured": waistband_iou,
            "operator": "gte",
            "threshold": THIN_CLASS_IOU_MIN,
            "passed": waistband_iou >= THIN_CLASS_IOU_MIN,
        },
    }
    return {
        "schema_version": "1.0.0",
        "candidate_run_id": candidate_row.get("run_id"),
        "baseline_run_id": baseline_row.get("run_id"),
        "baseline_model_family": BASELINE_MODEL_FAMILY,
        "dataset_ref": candidate_dataset,
        "split": REQUIRED_SPLIT,
        "checks": checks,
        "passed": all(bool(check["passed"]) for check in checks.values()),
    }


def write_clothing_promotion_gate(path: Path, result: dict[str, object]) -> Path:
    """Atomically write a complete evaluated clothing promotion result."""
    expected = {
        "material_mean_iou_beats_baseline",
        "strap_iou",
        "waistband_iou",
    }
    if set(result.get("checks", {})) != expected:
        raise ClothingGateError("clothing promotion gate result is incomplete")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
