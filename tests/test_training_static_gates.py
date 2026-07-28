from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.training.leaderboard import (
    FINAL_EVALUATION_AUTHORITY,
    append_leaderboard_row,
    enforce_final_evaluation_authority,
    normalize_leaderboard_row,
)
from maskfactory.training_static_gates import (
    AUTHORITY,
    LEADERBOARD_CHECKS,
    LEAKAGE_CHECKS,
    PROOF_TIER,
    VOLUME_CHECKS,
    WEIGHT_ELIGIBILITY_CHECKS,
    TrainingStaticGateError,
    evaluate_certified_volume_honesty,
    run_training_static_gate_suite,
)
from maskfactory.validation import validate_document


def _row(**overrides):
    row = {
        "run_id": "auth_row",
        "model_family": "segformer_b3",
        "ckpt_sha": "a" * 64,
        "dataset_ref": "bodyparts@v1",
        "split": "test_holdout",
        "mean_iou": 0.70,
        "mean_boundary_f": 0.75,
        "per_class": {"left_forearm": {"iou": 0.72, "bf": 0.77}},
        "group_scores": {"fingers": {"iou": 0.60, "bf": 0.65}},
        "latency_ms_1024": 80.0,
        "vram_gb": 7.5,
        "seeds": [1337],
        "notes": "fixture",
        "sample_count": 4,
    }
    row.update(overrides)
    return row


def test_training_static_suite_binds_weights_leakage_volume_leaderboard() -> None:
    report = run_training_static_gate_suite()
    assert validate_document(report, "training_static_gates_report") == ()
    assert report["proof_tier"] == PROOF_TIER
    assert report["authority"] == AUTHORITY
    assert set(report["weight_eligibility_checks"]) == set(WEIGHT_ELIGIBILITY_CHECKS)
    assert all(report["weight_eligibility_checks"].values())
    assert set(report["leakage_firewall_checks"]) == set(LEAKAGE_CHECKS)
    assert all(report["leakage_firewall_checks"].values())
    assert set(report["volume_honesty"]["checks"]) == set(VOLUME_CHECKS)
    assert report["volume_honesty"]["certified_training_package_count"] == 0
    assert report["volume_honesty"]["p5_entry_passed"] is False
    assert set(report["leaderboard_schema_checks"]) == set(LEADERBOARD_CHECKS)
    assert all(report["leaderboard_schema_checks"].values())
    assert report["flip_swap_ci_already_complete"] is True
    assert report["certified_training_package_count"] == 0
    assert report["p5_entry_gate_open"] is False
    assert report["d6_claimed"] is False
    assert report["d7_claimed"] is False
    assert report["champion_claimed"] is False
    assert report["live_training_run_claimed"] is False
    assert report["report_id"].startswith("tsg_")
    assert len(report["seal_sha256"]) == 64


def test_schema_rejects_d6_or_nonzero_certified_overclaim() -> None:
    report = run_training_static_gate_suite()
    report["d6_claimed"] = True
    assert validate_document(report, "training_static_gates_report")
    report = run_training_static_gate_suite()
    report["certified_training_package_count"] = 1
    assert validate_document(report, "training_static_gates_report")


def test_volume_honesty_refuses_nonzero_certified_count() -> None:
    with pytest.raises(TrainingStaticGateError, match="must_remain_zero"):
        evaluate_certified_volume_honesty(
            certified_training_package_count=1,
            human_anchor_train_count=1,
            autonomous_certified_gold_count=0,
        )


def test_final_holdout_leaderboard_rejects_autonomous_and_accepts_human_anchor(
    tmp_path: Path,
) -> None:
    good = _row(
        evaluation_authority=FINAL_EVALUATION_AUTHORITY,
        evaluation_truth_tier="human_anchor_gold",
        evaluation_manifest_sha256="b" * 64,
    )
    path = tmp_path / "leaderboard.jsonl"
    append_leaderboard_row(path, good)
    loaded = normalize_leaderboard_row(json.loads(path.read_text(encoding="utf-8").strip()))
    assert loaded["evaluation_truth_tier"] == "human_anchor_gold"

    with pytest.raises(ValueError, match="autonomous/pseudo/machine"):
        enforce_final_evaluation_authority(
            _row(
                evaluation_authority=FINAL_EVALUATION_AUTHORITY,
                evaluation_truth_tier="autonomous_certified_gold",
                evaluation_manifest_sha256="c" * 64,
            )
        )
    with pytest.raises(ValueError, match="autonomous/pseudo/machine"):
        normalize_leaderboard_row(
            _row(
                run_id="bad_pseudo",
                evaluation_authority=FINAL_EVALUATION_AUTHORITY,
                evaluation_truth_tier="weighted_pseudo_label",
                evaluation_manifest_sha256="d" * 64,
            )
        )
    with pytest.raises(ValueError, match="split"):
        enforce_final_evaluation_authority(
            _row(
                split="val",
                evaluation_authority=FINAL_EVALUATION_AUTHORITY,
                evaluation_truth_tier="human_anchor_gold",
                evaluation_manifest_sha256="e" * 64,
            )
        )


def test_cli_verify_training_static_gates(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    result = CliRunner().invoke(
        main,
        ["verify-training-static-gates", "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["proof_tier"] == "STATIC_PASS"
    assert report["certified_training_package_count"] == 0
    assert report["d6_claimed"] is False
    assert report["d7_claimed"] is False
