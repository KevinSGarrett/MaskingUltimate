from __future__ import annotations

import json
from pathlib import Path

import pytest

from maskfactory.qa.s04_eval import (
    S04EvalError,
    assert_s04_acceptance,
    load_hand_truth,
    score_predictions,
)


def _truth(index: int) -> dict:
    return {
        "id": str(index),
        "age_safety": "clear_adult",
        "visual_review": "pass",
        "source_sha256": "a" * 64,
        "expected_view": "front",
        "expected_pose_tags": ["arms_down"],
    }


def test_hand_truth_requires_exactly_twenty_unique_clear_adult_records(tmp_path: Path) -> None:
    document = {"schema_version": "1.0.0", "records": [_truth(i) for i in range(20)]}
    path = tmp_path / "truth.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert len(load_hand_truth(path)["records"]) == 20
    document["records"][0]["age_safety"] = "uncertain"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(S04EvalError, match="clear_adult"):
        load_hand_truth(path)


def test_s04_scores_view_and_exact_multilabel_sets_separately() -> None:
    truth = [_truth(i) for i in range(20)]
    predictions = [{"id": str(i), "view": "front", "pose_tags": ["arms_down"]} for i in range(20)]
    predictions[0]["view"] = "back"
    predictions[1]["pose_tags"] = ["arms_down", "walking"]
    score = score_predictions(truth, predictions)
    assert score["view_accuracy"] == 0.95
    assert score["pose_tags_exact_accuracy"] == 0.95
    assert_s04_acceptance(score)


def test_s04_gate_fails_below_ninety_percent() -> None:
    truth = [_truth(i) for i in range(20)]
    predictions = [{"id": str(i), "view": "front", "pose_tags": ["arms_down"]} for i in range(20)]
    for index in range(3):
        predictions[index]["view"] = "back"
    with pytest.raises(S04EvalError, match="view_accuracy"):
        assert_s04_acceptance(score_predictions(truth, predictions))
