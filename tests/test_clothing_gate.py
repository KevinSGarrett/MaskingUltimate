import json
from pathlib import Path

import pytest

from maskfactory.training.clothparse.gate import (
    ClothingGateError,
    evaluate_clothing_promotion_gate,
    write_clothing_promotion_gate,
)


def _row(
    *,
    run_id: str,
    model_family: str,
    mean_iou: object,
    strap_iou: object = 0.55,
    waistband_iou: object = 0.55,
    dataset_ref: str = "bodyparts@v7",
    split: str = "test_holdout",
) -> dict:
    return {
        "run_id": run_id,
        "model_family": model_family,
        "dataset_ref": dataset_ref,
        "split": split,
        "mean_iou": mean_iou,
        "per_class": {
            "strap": {"iou": strap_iou, "bf": 0.4},
            "waistband": {"iou": waistband_iou, "bf": 0.4},
        },
    }


def _candidate(**overrides: object) -> dict:
    values = {
        "run_id": "candidate_clothing_r1",
        "model_family": "segformer_b2_clothing",
        "mean_iou": 0.600001,
    }
    values.update(overrides)
    return _row(**values)


def _baseline(**overrides: object) -> dict:
    values = {
        "run_id": "baseline_clothing_r1",
        "model_family": "schp_atr_plus_s08_heuristics",
        "mean_iou": 0.6,
    }
    values.update(overrides)
    return _row(**values)


@pytest.mark.parametrize(
    ("candidate_overrides", "passed"),
    [
        ({}, True),
        ({"mean_iou": 0.6}, False),
        ({"strap_iou": 0.549999}, False),
        ({"waistband_iou": 0.549999}, False),
    ],
)
def test_clothing_gate_exact_boundaries(
    tmp_path: Path, candidate_overrides: dict[str, object], passed: bool
) -> None:
    result = evaluate_clothing_promotion_gate(_candidate(**candidate_overrides), _baseline())
    assert result["passed"] is passed
    path = write_clothing_promotion_gate(tmp_path / "gate.json", result)
    assert json.loads(path.read_text(encoding="utf-8")) == result


@pytest.mark.parametrize(
    ("candidate_overrides", "baseline_overrides", "message"),
    [
        ({"dataset_ref": "bodyparts@v8"}, {}, "same dataset_ref"),
        ({"split": "val"}, {}, "same split"),
        ({"split": "val"}, {"split": "val"}, "test_holdout"),
        ({}, {"model_family": "draft_pipeline_full"}, "baseline must be"),
        ({"model_family": "schp_atr_plus_s08_heuristics"}, {}, "candidate cannot"),
    ],
)
def test_clothing_gate_refuses_noncomparable_rows(
    candidate_overrides: dict[str, object],
    baseline_overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ClothingGateError, match=message):
        evaluate_clothing_promotion_gate(
            _candidate(**candidate_overrides), _baseline(**baseline_overrides)
        )


@pytest.mark.parametrize("metric", [None, "bad", float("nan"), -0.1, 1.1, True])
def test_clothing_gate_refuses_invalid_metrics(metric: object) -> None:
    with pytest.raises(ClothingGateError, match="numeric metric"):
        evaluate_clothing_promotion_gate(_candidate(mean_iou=metric), _baseline())


@pytest.mark.parametrize("class_name", ["strap", "waistband"])
def test_clothing_gate_refuses_missing_thin_class_metrics(class_name: str) -> None:
    candidate = _candidate()
    del candidate["per_class"][class_name]
    with pytest.raises(ClothingGateError, match=f"{class_name} IoU"):
        evaluate_clothing_promotion_gate(candidate, _baseline())


def test_clothing_gate_writer_refuses_incomplete_result(tmp_path: Path) -> None:
    with pytest.raises(ClothingGateError, match="incomplete"):
        write_clothing_promotion_gate(tmp_path / "gate.json", {"checks": {}})
