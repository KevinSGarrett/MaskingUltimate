import json
from pathlib import Path

import pytest

from maskfactory.orchestrator import FatalStageError, StagePolicyError, run_pipeline
from maskfactory.runlog import PipelineRunLog


def test_run_log_records_config_models_duration_vram_and_daily_text(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    runs = tmp_path / "runs"
    config = {"stages": {"S02": {"model_keys": ["birefnet_general"]}}}

    def runner(context):
        return {
            "silhouette_ready": True,
            "_telemetry": {
                "model_keys": ["birefnet_general"],
                "vram_peak_mb": 2450.5,
            },
        }

    with PipelineRunLog(
        image_ids=("img_a3f9c2e17b04",),
        config=config,
        logs_root=logs,
        runs_root=runs,
        run_id="run_fixture_success",
    ) as run_log:
        run_pipeline(
            "img_a3f9c2e17b04",
            selected=("S02",),
            config=config,
            work_root=tmp_path / "work",
            runners={"S02": runner},
            run_log=run_log,
        )

    document = json.loads((runs / "run_fixture_success" / "run.json").read_text(encoding="utf-8"))
    assert document["status"] == "complete"
    assert document["model_keys"] == ["birefnet_general"]
    assert document["vram_peak_mb"] == 2450.5
    assert document["duration_sec"] >= 0
    assert document["stages"][0]["config_hash"]
    assert document["stages"][0]["duration_sec"] >= 0
    assert "_telemetry" not in json.loads(
        (tmp_path / "work" / "s02" / "img_a3f9c2e17b04" / "manifest_delta.json").read_text(
            encoding="utf-8"
        )
    )
    daily = next(logs.glob("maskfactory_*.log")).read_text(encoding="utf-8")
    assert "run_fixture_success" in daily
    assert "stage=S02" in daily


def test_failed_run_persists_classification_attempts_and_error(tmp_path: Path) -> None:
    def runner(context):
        raise FatalStageError("bad fixture")

    with pytest.raises(StagePolicyError):
        with PipelineRunLog(
            image_ids=("img_a3f9c2e17b04",),
            config={},
            logs_root=tmp_path / "logs",
            runs_root=tmp_path / "runs",
            run_id="run_fixture_failure",
        ) as run_log:
            run_pipeline(
                "img_a3f9c2e17b04",
                selected=("S02",),
                work_root=tmp_path / "work",
                runners={"S02": runner},
                run_log=run_log,
            )

    document = json.loads(
        (tmp_path / "runs" / "run_fixture_failure" / "run.json").read_text(encoding="utf-8")
    )
    assert document["status"] == "failed"
    assert "S02 fatal" in document["error"]
    assert document["stages"] == [
        {
            "attempts": 1,
            "category": "fatal",
            "error": "bad fixture",
            "image_id": "img_a3f9c2e17b04",
            "stage": "S02",
            "status": "failed",
        }
    ]
