"""Body-part champion promotion gate for D6/G7 (doc 12 section 6.1)."""

from __future__ import annotations

import json
import math
import os
import uuid
from pathlib import Path
from typing import Any

BASELINE_MODEL_FAMILY = "draft_pipeline_full"
REQUIRED_SPLIT = "test_holdout"
HARD_GROUPS = ("fingers", "toes", "chest_boundary", "hairline")
MAX_REGRESSION = 0.02
_FLOAT_TOLERANCE = 1e-12


class BodyPartGateError(ValueError):
    """Body-part promotion evidence is incomplete or not comparable."""


def _unit_metric(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise BodyPartGateError(f"{name} must be a numeric metric in [0, 1]")
    try:
        metric = float(value)
    except (TypeError, ValueError) as exc:
        raise BodyPartGateError(f"{name} must be a numeric metric in [0, 1]") from exc
    if not math.isfinite(metric) or not 0 <= metric <= 1:
        raise BodyPartGateError(f"{name} must be a numeric metric in [0, 1]")
    return metric


def _group_metric(row: dict[str, Any], group: str, metric: str, owner: str) -> float:
    group_scores = row.get("group_scores")
    if not isinstance(group_scores, dict):
        raise BodyPartGateError(f"{owner} leaderboard row lacks group_scores")
    scores = group_scores.get(group)
    if not isinstance(scores, dict) or metric not in scores:
        raise BodyPartGateError(f"{owner} leaderboard row lacks {group} {metric}")
    return _unit_metric(scores[metric], f"{owner} {group} {metric}")


def evaluate_bodypart_promotion_gate(
    candidate_row: dict[str, Any], baseline_row: dict[str, Any]
) -> dict[str, object]:
    """Evaluate the indivisible frozen-holdout D6/G7 promotion gate."""
    if baseline_row.get("model_family") != BASELINE_MODEL_FAMILY:
        raise BodyPartGateError(f"body-part baseline must be {BASELINE_MODEL_FAMILY}")
    if candidate_row.get("model_family") == BASELINE_MODEL_FAMILY:
        raise BodyPartGateError("candidate cannot be the full draft-pipeline baseline")

    candidate_dataset = candidate_row.get("dataset_ref")
    if not isinstance(candidate_dataset, str) or not candidate_dataset:
        raise BodyPartGateError("candidate dataset_ref is missing")
    if candidate_dataset != baseline_row.get("dataset_ref"):
        raise BodyPartGateError("body-part comparison requires the same dataset_ref")
    candidate_split = candidate_row.get("split")
    if candidate_split != baseline_row.get("split"):
        raise BodyPartGateError("body-part comparison requires the same split")
    if candidate_split != REQUIRED_SPLIT:
        raise BodyPartGateError("body-part promotion requires a frozen test_holdout comparison")

    candidate_iou = _unit_metric(candidate_row.get("mean_iou"), "candidate mean IoU")
    baseline_iou = _unit_metric(baseline_row.get("mean_iou"), "baseline mean IoU")
    candidate_bf = _unit_metric(candidate_row.get("mean_boundary_f"), "candidate mean boundary-F")
    baseline_bf = _unit_metric(baseline_row.get("mean_boundary_f"), "baseline mean boundary-F")
    checks: dict[str, dict[str, object]] = {
        "mean_iou_beats_baseline": {
            "candidate": candidate_iou,
            "baseline": baseline_iou,
            "delta": candidate_iou - baseline_iou,
            "operator": "gt",
            "passed": candidate_iou > baseline_iou,
        },
        "mean_boundary_f_beats_baseline": {
            "candidate": candidate_bf,
            "baseline": baseline_bf,
            "delta": candidate_bf - baseline_bf,
            "operator": "gt",
            "passed": candidate_bf > baseline_bf,
        },
    }
    for group in HARD_GROUPS:
        for metric in ("iou", "bf"):
            candidate_value = _group_metric(candidate_row, group, metric, "candidate")
            baseline_value = _group_metric(baseline_row, group, metric, "baseline")
            delta = candidate_value - baseline_value
            checks[f"{group}_{metric}_regression"] = {
                "candidate": candidate_value,
                "baseline": baseline_value,
                "delta": delta,
                "operator": "gte",
                "threshold": -MAX_REGRESSION,
                "passed": delta >= -MAX_REGRESSION - _FLOAT_TOLERANCE,
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


def write_bodypart_promotion_gate(path: Path, result: dict[str, object]) -> Path:
    """Atomically write one complete D6/G7 evaluation result."""
    expected = {"mean_iou_beats_baseline", "mean_boundary_f_beats_baseline"}
    expected.update(
        f"{group}_{metric}_regression" for group in HARD_GROUPS for metric in ("iou", "bf")
    )
    if set(result.get("checks", {})) != expected:
        raise BodyPartGateError("body-part promotion gate result is incomplete")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
