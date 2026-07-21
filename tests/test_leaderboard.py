import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.training.leaderboard import (
    append_leaderboard_row,
    compare_runs,
    ensure_standing_baselines,
    format_comparison_table,
    load_leaderboard,
    normalize_leaderboard_row,
    saturation_report,
)


def _row(run_id: str, offset: float = 0.0) -> dict:
    return {
        "run_id": run_id,
        "model_family": "segformer_b3",
        "ckpt_sha": "a" * 64,
        "dataset_ref": "bodyparts@v1",
        "split": "test_holdout",
        "mean_iou": 0.70 + offset,
        "mean_boundary_f": 0.75 + offset,
        "per_class": {"left_forearm": {"iou": 0.72 + offset, "bf": 0.77 + offset}},
        "group_scores": {"fingers": {"iou": 0.60 + offset, "bf": 0.65 + offset}},
        "latency_ms_1024": 80.0,
        "vram_gb": 7.5,
        "seeds": [1337],
        "notes": "fixture",
        "sample_count": 4,
    }


def test_legacy_rows_default_to_solo_without_changing_pooled_scores(tmp_path: Path) -> None:
    legacy = _row("legacy")
    path = tmp_path / "leaderboard.jsonl"
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    loaded = load_leaderboard(path)[0]
    assert loaded["mean_iou"] == legacy["mean_iou"]
    assert loaded["mean_boundary_f"] == legacy["mean_boundary_f"]
    assert loaded["instance_context_scores"] == {
        "solo": {
            "mean_iou": legacy["mean_iou"],
            "mean_boundary_f": legacy["mean_boundary_f"],
            "per_class": legacy["per_class"],
            "sample_count": 4,
        }
    }


def test_context_rows_append_validate_compare_and_cli_report(tmp_path: Path) -> None:
    path = tmp_path / "leaderboard.jsonl"
    first = _row("run_a")
    second = _row("run_b", 0.05)
    second["instance_context_scores"] = {
        context: {
            "mean_iou": second["mean_iou"] - index * 0.02,
            "mean_boundary_f": second["mean_boundary_f"] - index * 0.02,
            "per_class": second["per_class"],
            "sample_count": index + 1,
        }
        for index, context in enumerate(("solo", "duo", "small_group"))
    }
    append_leaderboard_row(path, first)
    append_leaderboard_row(path, second)
    rows = load_leaderboard(path)
    comparison = compare_runs(rows, "run_a", "run_b")
    assert comparison["pooled_delta"]["mean_iou"] == pytest.approx(0.05)
    assert comparison["per_class_delta"]["left_forearm"]["iou"] == pytest.approx(0.05)
    assert comparison["instance_context_delta"]["solo"]["mean_iou"] == pytest.approx(0.05)
    assert comparison["instance_context_delta"]["duo"]["mean_iou"] is None
    result = CliRunner().invoke(
        main,
        ["leaderboard", "--path", str(path), "--compare", "run_a", "run_b", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["instance_context_delta"]["small_group"]["mean_iou"] is None
    table = format_comparison_table(comparison)
    assert "| pooled | all | +0.0500 | +0.0500 |" in table
    assert "| group | fingers | +0.0500 | +0.0500 |" in table


def test_run_id_is_idempotent_only_for_byte_equivalent_evidence(tmp_path: Path) -> None:
    path = tmp_path / "leaderboard.jsonl"
    original = _row("immutable_run")
    append_leaderboard_row(path, original)
    before = path.read_bytes()
    append_leaderboard_row(path, original)
    assert path.read_bytes() == before
    changed = _row("immutable_run", 0.01)
    with pytest.raises(ValueError, match="run_id is immutable"):
        append_leaderboard_row(path, changed)
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="ambiguous duplicate run_id"):
        compare_runs((original, changed), "immutable_run", "other")


def test_leaderboard_rejects_unknown_context_and_cross_holdout_comparison() -> None:
    invalid = _row("invalid")
    invalid["instance_context_scores"] = {"crowd": {}}
    with pytest.raises(ValueError, match="unknown instance context"):
        normalize_leaderboard_row(invalid)
    a = normalize_leaderboard_row(_row("a"))
    b = _row("b")
    b["split"] = "val"
    with pytest.raises(ValueError, match="same dataset_ref and split"):
        compare_runs((a, normalize_leaderboard_row(b)), "a", "b")


def test_human_ceiling_saturation_rule() -> None:
    candidate = _row("candidate", 0.0)
    human = _row("human")
    human.update(
        {
            "model_family": "human_ceiling_iaa",
            "ckpt_sha": "0" * 64,
            "mean_iou": 0.73,
            "mean_boundary_f": 0.79,
            "per_class": {"left_forearm": {"iou": 0.735, "bf": 0.785}},
            "group_scores": {},
            "seeds": [],
        }
    )
    report = saturation_report((candidate, human), "human")
    assert report["threshold"] == 0.02
    assert report["classes"]["left_forearm"]["saturated"] is True


def test_standing_baselines_are_scored_once_per_dataset_holdout(tmp_path: Path) -> None:
    path = tmp_path / "leaderboard.jsonl"
    calls = []

    def score(baseline: str, dataset_ref: str, split: str) -> dict:
        calls.append((baseline, dataset_ref, split))
        row = _row("identity_is_stamped_by_orchestrator")
        for key in ("run_id", "model_family", "dataset_ref", "split"):
            row.pop(key)
        row["notes"] = f"measured {baseline}"
        return row

    first = ensure_standing_baselines(
        path, dataset_ref="bodyparts@v7", split="test_holdout", score=score
    )
    assert [row["model_family"] for row in first] == [
        "sam2_only",
        "sam2_pose",
        "sam2_parsing",
        "draft_pipeline_full",
    ]
    assert all(row["dataset_ref"] == "bodyparts@v7" for row in first)
    assert all(row["split"] == "test_holdout" for row in first)
    assert len(calls) == 4

    second = ensure_standing_baselines(
        path, dataset_ref="bodyparts@v7", split="test_holdout", score=score
    )
    assert second == first
    assert len(calls) == 4
    assert len(load_leaderboard(path)) == 4

    ensure_standing_baselines(path, dataset_ref="bodyparts@v8", split="val", score=score)
    assert len(calls) == 8
    assert len(load_leaderboard(path)) == 8


def test_standing_baseline_refuses_ambiguous_existing_family(tmp_path: Path) -> None:
    path = tmp_path / "leaderboard.jsonl"
    first = _row("sam2_a")
    first["model_family"] = "sam2_only"
    second = _row("sam2_b")
    second["model_family"] = "sam2_only"
    path.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="baseline is ambiguous"):
        ensure_standing_baselines(
            path,
            dataset_ref="bodyparts@v1",
            split="test_holdout",
            score=lambda *_args: {},
        )
