import json
from pathlib import Path

import pytest

from maskfactory.orchestrator import (
    STAGE_ORDER,
    StageConfigurationError,
    StageRunnerMissingError,
    plan_stages,
    run_pipeline,
)


def test_stage_planner_is_complete_and_rejects_conflicting_controls() -> None:
    assert STAGE_ORDER == (
        "S00", "S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08",
        "S08.5", "S09", "S09.5", "S10", "S11", "S12", "S13", "S14", "S15",
    )
    plan = plan_stages(
        selected=("S04", "S03", "S02"),
        force=("S03",),
        skip=("S04",),
        config={"stages": {"S03": {"enabled": False}}},
    )
    assert [stage.name for stage in plan] == ["S02", "S03"]
    with pytest.raises(StageConfigurationError, match="both forced and skipped"):
        plan_stages(force=("S01",), skip=("S01",))


def test_pipeline_persists_exact_stage_artifacts_and_invalidates_downstream_cache(
    tmp_path: Path,
) -> None:
    calls = {"S01": 0, "S02": 0}

    def runner(stage: str):
        def execute(context):
            calls[stage] += 1
            (context.output_dir / f"{stage}.txt").write_text(str(calls[stage]), encoding="utf-8")
            return {"generation": calls[stage]}

        return execute

    args = {
        "image_id": "img_canonical_planner",
        "selected": ("S01", "S02"),
        "work_root": tmp_path,
        "runners": {"S01": runner("S01"), "S02": runner("S02")},
    }
    first = run_pipeline(**args)
    second = run_pipeline(**args)
    third = run_pipeline(**args, force=("S01",))

    assert [item.status for item in first] == ["complete", "complete"]
    assert [item.status for item in second] == ["cached", "cached"]
    assert [item.status for item in third] == ["complete", "complete"]
    assert calls == {"S01": 2, "S02": 2}
    output = tmp_path / "s02" / "img_canonical_planner"
    assert json.loads((output / "manifest_delta.json").read_text(encoding="utf-8")) == {
        "generation": 2
    }
    stamp = json.loads((output / "stage_run.json").read_text(encoding="utf-8"))
    assert stamp["stage"] == "S02"
    assert stamp["forced"] is True
    assert stamp["files"] == ["S02.txt", "manifest_delta.json"]


def test_pipeline_refuses_to_execute_without_a_materialized_stage_runner(tmp_path: Path) -> None:
    with pytest.raises(StageRunnerMissingError, match="no runner registered for S01"):
        run_pipeline("img_missing_runner", selected=("S01",), work_root=tmp_path)
