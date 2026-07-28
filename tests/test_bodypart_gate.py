import json
from pathlib import Path

import pytest

from maskfactory.training.bodypart.gate import (
    HARD_GROUPS,
    BodyPartGateError,
    evaluate_bodypart_promotion_gate,
    write_bodypart_promotion_gate,
)


def _row(
    *,
    run_id: str,
    model_family: str,
    mean_iou: object,
    mean_boundary_f: object,
    dataset_ref: str = "bodyparts@v7",
    split: str = "test_holdout",
) -> dict:
    return {
        "run_id": run_id,
        "model_family": model_family,
        "dataset_ref": dataset_ref,
        "split": split,
        "mean_iou": mean_iou,
        "mean_boundary_f": mean_boundary_f,
        "group_scores": {group: {"iou": 0.6, "bf": 0.6} for group in HARD_GROUPS},
    }


def _candidate(**overrides: object) -> dict:
    values = {
        "run_id": "candidate_bodypart_r1",
        "model_family": "segformer_b3_bodypart",
        "mean_iou": 0.600001,
        "mean_boundary_f": 0.650001,
    }
    values.update(overrides)
    return _row(**values)


def _baseline(**overrides: object) -> dict:
    values = {
        "run_id": "baseline_bodypart_r1",
        "model_family": "draft_pipeline_full",
        "mean_iou": 0.6,
        "mean_boundary_f": 0.65,
    }
    values.update(overrides)
    return _row(**values)


def test_d6_gate_passes_strict_pooled_wins_and_exact_two_point_floor(tmp_path: Path) -> None:
    candidate = _candidate()
    candidate["group_scores"]["fingers"]["iou"] = 0.58
    candidate["group_scores"]["toes"]["bf"] = 0.58
    result = evaluate_bodypart_promotion_gate(candidate, _baseline())
    assert result["passed"] is True
    assert len(result["checks"]) == 10
    path = write_bodypart_promotion_gate(tmp_path / "gate.json", result)
    assert json.loads(path.read_text(encoding="utf-8")) == result


@pytest.mark.parametrize("metric", ["mean_iou", "mean_boundary_f"])
def test_d6_gate_requires_strict_pooled_wins(metric: str) -> None:
    candidate = _candidate()
    baseline = _baseline()
    candidate[metric] = baseline[metric]
    assert evaluate_bodypart_promotion_gate(candidate, baseline)["passed"] is False


@pytest.mark.parametrize(
    ("group", "metric"), [(group, metric) for group in HARD_GROUPS for metric in ("iou", "bf")]
)
def test_d6_gate_rejects_more_than_two_point_hard_group_regression(group: str, metric: str) -> None:
    candidate = _candidate()
    candidate["group_scores"][group][metric] = 0.579999
    result = evaluate_bodypart_promotion_gate(candidate, _baseline())
    assert result["passed"] is False
    assert result["checks"][f"{group}_{metric}_regression"]["passed"] is False


@pytest.mark.parametrize(
    ("candidate_overrides", "baseline_overrides", "message"),
    [
        ({"dataset_ref": "bodyparts@v8"}, {}, "same dataset_ref"),
        ({"split": "val"}, {}, "same split"),
        ({"split": "val"}, {"split": "val"}, "test_holdout"),
        ({}, {"model_family": "sam2_parsing"}, "baseline must be"),
        ({"model_family": "draft_pipeline_full"}, {}, "candidate cannot"),
    ],
)
def test_d6_gate_refuses_noncomparable_rows(
    candidate_overrides: dict[str, object],
    baseline_overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(BodyPartGateError, match=message):
        evaluate_bodypart_promotion_gate(
            _candidate(**candidate_overrides), _baseline(**baseline_overrides)
        )


@pytest.mark.parametrize("metric", [None, "bad", float("nan"), -0.1, 1.1, True])
def test_d6_gate_refuses_invalid_pooled_metrics(metric: object) -> None:
    with pytest.raises(BodyPartGateError, match="numeric metric"):
        evaluate_bodypart_promotion_gate(_candidate(mean_iou=metric), _baseline())


def test_d6_gate_refuses_missing_hard_group_metric() -> None:
    candidate = _candidate()
    del candidate["group_scores"]["hairline"]["bf"]
    with pytest.raises(BodyPartGateError, match="hairline bf"):
        evaluate_bodypart_promotion_gate(candidate, _baseline())


def test_d6_gate_writer_refuses_incomplete_result(tmp_path: Path) -> None:
    with pytest.raises(BodyPartGateError, match="incomplete"):
        write_bodypart_promotion_gate(tmp_path / "gate.json", {"checks": {}})
