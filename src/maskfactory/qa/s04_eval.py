"""Fail-closed scoring for the governed S04 hand-tagged evaluation set."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class S04EvalError(ValueError):
    """The S04 hand-truth set or measured result violates its contract."""


VIEWS = {"front", "back", "left_profile", "right_profile", "left_3_4", "right_3_4"}
POSE_TAGS = {
    "arms_raised",
    "arms_down",
    "arms_crossed",
    "seated_or_crouched",
    "lying",
    "walking",
    "leg_overlap",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_hand_truth(path: Path) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0.0":
        raise S04EvalError("S04 hand-truth schema_version must be 1.0.0")
    records = document.get("records")
    if not isinstance(records, list) or len(records) != 20:
        raise S04EvalError("S04 acceptance requires exactly 20 hand-tagged images")
    identifiers: set[str] = set()
    for record in records:
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise S04EvalError("S04 fixture ids must be non-empty and unique")
        identifiers.add(identifier)
        if record.get("visual_review") != "pass":
            raise S04EvalError(f"{identifier}: independent visual review is not passed")
        if record.get("expected_view") not in VIEWS:
            raise S04EvalError(f"{identifier}: invalid expected view")
        tags = record.get("expected_pose_tags")
        if not isinstance(tags, list) or len(tags) != len(set(tags)) or not set(tags) <= POSE_TAGS:
            raise S04EvalError(f"{identifier}: invalid expected pose tags")
        if not isinstance(record.get("source_sha256"), str) or len(record["source_sha256"]) != 64:
            raise S04EvalError(f"{identifier}: invalid source SHA-256")
    return document


def score_predictions(
    truth_records: list[dict[str, Any]], predictions: list[dict[str, Any]]
) -> dict[str, Any]:
    if len(truth_records) != 20 or len(predictions) != 20:
        raise S04EvalError("S04 scoring requires exactly 20 truth/prediction records")
    truth_by_id = {record["id"]: record for record in truth_records}
    prediction_by_id = {record["id"]: record for record in predictions}
    if set(truth_by_id) != set(prediction_by_id):
        raise S04EvalError("S04 prediction ids differ from hand truth")
    rows = []
    for identifier in sorted(truth_by_id):
        truth = truth_by_id[identifier]
        prediction = prediction_by_id[identifier]
        view_pass = prediction.get("view") == truth["expected_view"]
        predicted_tags = prediction.get("pose_tags")
        if not isinstance(predicted_tags, list) or not set(predicted_tags) <= POSE_TAGS:
            raise S04EvalError(f"{identifier}: invalid predicted pose tags")
        tags_pass = set(predicted_tags) == set(truth["expected_pose_tags"])
        rows.append(
            {
                "id": identifier,
                "expected_view": truth["expected_view"],
                "predicted_view": prediction.get("view"),
                "view_pass": view_pass,
                "expected_pose_tags": truth["expected_pose_tags"],
                "predicted_pose_tags": predicted_tags,
                "pose_tags_exact_pass": tags_pass,
            }
        )
    view_accuracy = sum(row["view_pass"] for row in rows) / len(rows)
    pose_tags_exact_accuracy = sum(row["pose_tags_exact_pass"] for row in rows) / len(rows)
    return {
        "fixture_count": len(rows),
        "view_accuracy": view_accuracy,
        "pose_tags_exact_accuracy": pose_tags_exact_accuracy,
        "rows": rows,
    }


def assert_s04_acceptance(score: dict[str, Any], threshold: float = 0.90) -> None:
    if score.get("fixture_count") != 20:
        raise S04EvalError("S04 acceptance requires exactly 20 scored images")
    failures = {
        metric: score.get(metric)
        for metric in ("view_accuracy", "pose_tags_exact_accuracy")
        if not isinstance(score.get(metric), (int, float)) or score[metric] < threshold
    }
    if failures:
        raise S04EvalError(f"S04 acceptance threshold failure: {failures}")
