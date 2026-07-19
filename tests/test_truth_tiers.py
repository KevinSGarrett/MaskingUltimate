from pathlib import Path

import pytest
import yaml

from maskfactory.autonomy.calibration import load_autonomy_config
from maskfactory.datasets.authority import (
    D5_CERTIFIED_PACKAGE_COUNT,
    P5_CERTIFIED_ENTRY_COUNT,
    PARTITION_CAPABILITIES,
    evaluate_certified_volume_gates,
    require_partition_capability,
    serialized_reader_capabilities,
)
from maskfactory.truth_tiers import (
    NON_TRAINING_AUTHORITY_LABELS,
    TruthTierError,
    normalize_truth_tier,
    require_training_truth_tier,
    summarize_truth_tiers,
    validate_truth_tier_policy,
)


def _policy():
    config = yaml.safe_load(Path("configs/autonomous_masks.yaml").read_text(encoding="utf-8"))
    return validate_truth_tier_policy(config["truth_tiers"])


def test_active_autonomy_config_has_distinct_truth_tiers_and_targets() -> None:
    config = load_autonomy_config()

    assert config["mode"] == "autonomous_certified_gold"
    assert config["operational_targets"] == {
        "target_zero_touch_fraction": 0.95,
        "maximum_routine_human_touch_fraction": 0.05,
        "target_manual_pixel_edit_fraction": 0.01,
        "target_ordinary_part_mean_iou": 0.95,
        "target_ordinary_boundary_f1": 0.90,
        "target_hard_anatomy_mean_iou": 0.85,
        "maximum_cross_instance_bleed_fraction": 0.0,
        "maximum_left_right_swap_count": 0,
    }
    policy = validate_truth_tier_policy(config["truth_tiers"])
    assert policy["human_anchor_gold"].training_weight == 1.0
    assert policy["human_anchor_gold"].holdout_eligible
    assert policy["autonomous_certified_gold"].training_weight == 0.65
    assert policy["autonomous_certified_gold"].dataset_volume_eligible
    assert not policy["weighted_pseudo_label"].dataset_volume_eligible


def test_effective_truth_count_keeps_every_tier_separate() -> None:
    counts = summarize_truth_tiers(
        (
            {"truth_tier": "human_anchor_gold"},
            {"truth_tier": "autonomous_certified_gold"},
            {"truth_tier": "autonomous_certified_gold"},
            {"truth_tier": "weighted_pseudo_label"},
            {"truth_tier": "machine_candidate"},
        ),
        _policy(),
    )

    assert counts.as_dict() == {
        "human_anchor_gold_count": 1,
        "autonomous_certified_gold_count": 2,
        "weighted_pseudo_label_count": 1,
        "machine_candidate_count": 1,
        "effective_training_truth_count": 2.5,
    }


def test_legacy_authority_names_are_readable_without_renaming_machine_truth_human() -> None:
    assert normalize_truth_tier("human_approved_gold") == "human_anchor_gold"
    assert normalize_truth_tier("calibrated_auto_accepted") == "autonomous_certified_gold"
    assert normalize_truth_tier("machine_verified_candidate") == "machine_candidate"


def test_operational_and_synthetic_exact_cannot_enter_training_truth_tiers() -> None:
    assert "operationally_certified_artifact" in NON_TRAINING_AUTHORITY_LABELS
    assert "synthetic_exact" in NON_TRAINING_AUTHORITY_LABELS
    for label in (
        "operationally_certified_artifact",
        "synthetic_exact",
        "external_labeled_reference",
        "qa_passed_machine_candidate",
    ):
        with pytest.raises(TruthTierError, match="non-training authority"):
            normalize_truth_tier(label)
        with pytest.raises(TruthTierError, match="non-training authority"):
            require_training_truth_tier(label)
    # DAZ / external training ingest must still land as weighted_pseudo_label.
    assert require_training_truth_tier("weighted_pseudo_label") == "weighted_pseudo_label"


def test_invalid_weights_and_machine_holdouts_fail_closed() -> None:
    document = yaml.safe_load(Path("configs/autonomous_masks.yaml").read_text(encoding="utf-8"))[
        "truth_tiers"
    ]
    document["autonomous_certified_gold"]["training_weight"] = 0.9
    with pytest.raises(TruthTierError, match="0.5..0.75"):
        validate_truth_tier_policy(document)


def test_truth_partition_reader_capabilities_are_disjoint_and_fail_closed() -> None:
    expected = {
        "train": {"trainer", "model_selector", "pseudo_label_generator"},
        "calibration": {"threshold_tuner", "certificate_fitter"},
        "holdout": {"final_evaluator"},
    }
    assert {key: set(value) for key, value in PARTITION_CAPABILITIES.items()} == expected
    assert serialized_reader_capabilities() == {
        "trainer": ["train", "val"],
        "model_selector": ["val"],
        "pseudo_label_generator": ["train"],
        "threshold_tuner": ["calibration"],
        "certificate_fitter": ["calibration"],
        "final_evaluator": ["test_holdout", "hard_case_holdout"],
    }
    for partition, permitted in expected.items():
        for capability in set().union(*expected.values()):
            if capability in permitted:
                require_partition_capability(partition, capability)
            else:
                with pytest.raises(ValueError, match="cannot access"):
                    require_partition_capability(partition, capability)


def test_certified_volume_gates_exclude_pseudo_weight_and_require_d5_coverage() -> None:
    coverage = {
        "cells": [
            {"approved_gold_count": 8},
            {"approved_gold_count": 9},
            {"approved_gold_count": 10},
            {"approved_gold_count": 8},
            {"approved_gold_count": 0},
        ],
        "attribute_totals": {"hands_visible": 40, "feet_visible": 41},
    }
    below = evaluate_certified_volume_gates(199, coverage)
    assert below["p5_entry_passed"] is False and below["d5_passed"] is False
    p5 = evaluate_certified_volume_gates(P5_CERTIFIED_ENTRY_COUNT, coverage)
    assert p5["p5_entry_passed"] is True and p5["d5_passed"] is False
    d5 = evaluate_certified_volume_gates(D5_CERTIFIED_PACKAGE_COUNT, coverage)
    assert d5["d5_covered_cell_fraction"] == 0.8 and d5["d5_passed"] is True
    coverage["attribute_totals"]["feet_visible"] = 39
    assert evaluate_certified_volume_gates(10_000, coverage)["d5_passed"] is False
