from pathlib import Path

import numpy as np
import pytest
import yaml

from maskfactory.qa.metrics import (
    boundary_f,
    compute_part_metrics,
    hausdorff_percentile,
    package_qa_score,
)


def test_qa_config_has_qc011_024_thresholds_severities_and_score_weights() -> None:
    config = yaml.safe_load(Path("configs/qa.yaml").read_text())
    assert set(config["checks"]) == {f"QC-{number:03d}" for number in range(11, 25)}
    assert config["checks"]["QC-011"]["severity"] == "BLOCK"
    assert config["checks"]["QC-012"]["max_outside_fraction"] == 0.002
    assert config["checks"]["QC-013"]["max_overlap_fraction"] == 0.005
    assert config["checks"]["QC-018"]["min_iou"] == 0.995
    assert config["checks"]["QC-021"]["max_ratio"] == 0.01
    assert sum(
        term["weight"] for term in config["metrics"]["normalized_score_terms"].values()
    ) == pytest.approx(1)
    assert config["class_tier_weights"]["hard"] == 2.0
    assert config["qa_score"]["block_override"] is False


def test_boundary_and_hausdorff_metrics_have_exact_geometry() -> None:
    first = np.zeros((40, 40), dtype=bool)
    second = np.zeros_like(first)
    first[10:30, 10:30] = True
    second[10:30, 12:32] = True
    assert boundary_f(first, second, tolerance_px=2) == pytest.approx(1.0)
    assert hausdorff_percentile(first, second) == pytest.approx(2.0)


def test_per_part_metrics_and_hard_class_weighted_package_score() -> None:
    gold = np.zeros((20, 20), dtype=bool)
    gold[4:16, 4:16] = True
    candidate = gold.copy()
    candidate[8:10, 8:10] = False
    protected = np.zeros_like(gold)
    protected[4:6, 4:6] = True
    disagreement = np.zeros((20, 20), dtype=np.uint8)
    disagreement[candidate] = 128
    metrics = compute_part_metrics(
        candidate,
        gold,
        previous=gold,
        disagreement=disagreement,
        protected=protected,
        mutually_exclusive=np.zeros_like(gold),
        hard_class=True,
    )
    assert metrics.components == 1
    assert metrics.mask_area_px == 140
    assert metrics.mask_bbox == (4, 4, 16, 16)
    assert metrics.hole_ratio == pytest.approx(4 / 140)
    assert metrics.disagreement_score == pytest.approx(128 / 255)
    assert metrics.overlap_with_protected_regions == pytest.approx(4 / 140)
    perfect = compute_part_metrics(gold, gold)
    score = package_qa_score({"hair": metrics, "left_forearm": perfect}, hard_parts={"hair"})
    assert 0 < score < 1
    assert package_qa_score({"left_forearm": perfect}, hard_parts=set()) == pytest.approx(1)
