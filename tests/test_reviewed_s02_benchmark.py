from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from maskfactory.benchmarking.reviewed_s02 import (
    CASE_IDS,
    DEFAULT_POLICY,
    LOCKED_POLICY_SHA256,
    ReviewedS02BenchmarkError,
    canonical_sha256,
    load_policy,
    mask_metrics,
    match_best_instance,
    validate_policy,
)


def _reseal(document: dict) -> None:
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )


def test_policy_is_frozen_before_results_and_all_reference_bytes_are_current() -> None:
    policy = load_policy()
    assert policy["sha256"] == LOCKED_POLICY_SHA256
    assert policy["results_existed_at_freeze"] is False
    assert tuple(row["case_id"] for row in policy["references"]) == CASE_IDS
    assert policy["execution"]["pass_thresholds"] is None


def test_policy_rejects_any_gold_or_promotion_authority() -> None:
    policy = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
    policy["authority_limits"]["gold_authority"] = True
    _reseal(policy)
    with pytest.raises(ReviewedS02BenchmarkError, match="authority limits"):
        validate_policy(policy, expected_sha256=None)


def test_policy_rejects_post_result_freeze_claim() -> None:
    policy = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
    policy["results_existed_at_freeze"] = True
    _reseal(policy)
    with pytest.raises(ReviewedS02BenchmarkError, match="before eligible results"):
        validate_policy(policy, expected_sha256=None)


def test_perfect_mask_metrics_are_exact() -> None:
    mask = np.zeros((12, 12), dtype=bool)
    mask[2:10, 3:9] = True
    metrics = mask_metrics(mask, mask)
    for name in (
        "iou",
        "dice",
        "precision",
        "recall",
        "boundary_precision_2px",
        "boundary_recall_2px",
        "boundary_f_2px",
    ):
        assert metrics[name] == 1
    assert metrics["spill_fraction"] == 0
    assert metrics["miss_fraction"] == 0


def test_overlap_metrics_expose_spill_and_miss_without_thresholds() -> None:
    reference = np.zeros((16, 16), dtype=bool)
    reference[4:12, 4:12] = True
    prediction = np.zeros_like(reference)
    prediction[4:12, 6:14] = True
    metrics = mask_metrics(prediction, reference)
    assert metrics["intersection_pixels"] == 48
    assert metrics["prediction_pixels"] == 64
    assert metrics["reference_pixels"] == 64
    assert metrics["precision"] == 0.75
    assert metrics["recall"] == 0.75
    assert metrics["spill_fraction"] == 0.25
    assert metrics["miss_fraction"] == 0.25


def test_best_instance_uses_iou_and_breaks_exact_tie_by_lower_index() -> None:
    reference = np.zeros((20, 20), dtype=bool)
    reference[5:15, 5:15] = True
    poor = np.zeros_like(reference)
    poor[1:4, 1:4] = True
    good = copy.deepcopy(reference)
    index, metrics = match_best_instance([poor, good, good], reference)
    assert index == 1
    assert metrics["iou"] == 1


def test_geometry_and_degenerate_masks_fail_closed() -> None:
    valid = np.zeros((10, 10), dtype=bool)
    valid[2:8, 2:8] = True
    with pytest.raises(ReviewedS02BenchmarkError, match="geometry"):
        mask_metrics(valid, valid[:9])
    with pytest.raises(ReviewedS02BenchmarkError, match="degenerate"):
        mask_metrics(np.zeros_like(valid), valid)
    with pytest.raises(ReviewedS02BenchmarkError, match="no person instances"):
        match_best_instance([], valid)
