import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.orchestrator import (
    STAGE_ORDER,
    FatalStageError,
    SemanticStageError,
    StageConfigurationError,
    config_digest,
    plan_stages,
    run_batch,
    run_pipeline,
)
from maskfactory.state import initialize_database, reader_connection, writer_connection


def test_stage_graph_is_complete_and_orders_multi_person_reconciliation() -> None:
    assert STAGE_ORDER == (
        "S00",
        "S01",
        "S02",
        "S03",
        "S04",
        "S05",
        "S06",
        "S07",
        "S08",
        "S08.5",
        "S09",
        "S09.5",
        "S10",
        "S11",
        "S12",
        "S13",
        "S14",
        "S15",
    )


def test_stage_plan_applies_selection_disable_force_and_skip_in_canonical_order() -> None:
    config = {"stages": {"S03": {"enabled": False}}}
    plan = plan_stages(selected=("S04", "S03", "S02"), force=("S03",), skip=("S04",), config=config)
    assert [stage.name for stage in plan] == ["S02", "S03"]
    with pytest.raises(StageConfigurationError, match="both forced and skipped"):
        plan_stages(force=("S01",), skip=("S01",))


def test_config_digest_is_stable_and_stage_scoped() -> None:
    first = {"global": {"tile": 512}, "stages": {"S02": {"threshold": 0.5}}}
    reordered = {"stages": {"S02": {"threshold": 0.5}}, "global": {"tile": 512}}
    changed_other = {**first, "stages": {**first["stages"], "S03": {"other": True}}}
    assert config_digest(first, "S02") == config_digest(reordered, "S02")
    assert config_digest(first, "S02") == config_digest(changed_other, "S02")
    changed_stage = {"global": {"tile": 512}, "stages": {"S02": {"threshold": 0.6}}}
    assert config_digest(first, "S02") != config_digest(changed_stage, "S02")


def test_rerun_cache_and_force_atomically_replace_stage_owned_work(tmp_path: Path) -> None:
    generations = 0

    def runner(context):
        nonlocal generations
        generations += 1
        (context.output_dir / f"generation_{generations}.txt").write_text(
            str(generations), encoding="utf-8"
        )
        return {"generation": generations}

    args = {
        "image_id": "img_a3f9c2e17b04",
        "selected": ("S02",),
        "work_root": tmp_path,
        "runners": {"S02": runner},
    }
    first = run_pipeline(**args)
    second = run_pipeline(**args)
    third = run_pipeline(**args, force=("S02",))
    output = tmp_path / "s02" / "img_a3f9c2e17b04"
    assert [first[0].status, second[0].status, third[0].status] == [
        "complete",
        "cached",
        "complete",
    ]
    assert generations == 2
    assert not (output / "generation_1.txt").exists()
    assert (output / "generation_2.txt").read_text(encoding="utf-8") == "2"
    assert json.loads((output / "manifest_delta.json").read_text(encoding="utf-8")) == {
        "generation": 2
    }
    stamp = json.loads((output / "stage_run.json").read_text(encoding="utf-8"))
    assert stamp["forced"] is True
    assert stamp["config_hash"] == third[0].config_hash


def test_config_change_invalidates_cache(tmp_path: Path) -> None:
    calls = 0

    def runner(context):
        nonlocal calls
        calls += 1
        return {"calls": calls}

    common = {
        "image_id": "img_a3f9c2e17b04",
        "selected": ("S02",),
        "work_root": tmp_path,
        "runners": {"S02": runner},
    }
    run_pipeline(**common, config={"stages": {"S02": {"threshold": 0.5}}})
    run_pipeline(**common, config={"stages": {"S02": {"threshold": 0.6}}})
    assert calls == 2


def test_downstream_stage_reads_prior_files_not_in_memory_results(tmp_path: Path) -> None:
    def s01(context):
        (context.output_dir / "person_bbox.json").write_text(
            '{"bbox":[1,2,3,4]}\n', encoding="utf-8"
        )
        return {"person_count": 1}

    def s02(context):
        prior = context.prior_stage_dir("S01") / "person_bbox.json"
        bbox = json.loads(prior.read_text(encoding="utf-8"))["bbox"]
        (context.output_dir / "silhouette.txt").write_text(str(bbox), encoding="utf-8")
        return {"silhouette_ready": True}

    run_pipeline(
        "img_a3f9c2e17b04",
        selected=("S01", "S02"),
        work_root=tmp_path,
        runners={"S01": s01, "S02": s02},
    )
    assert (tmp_path / "s02" / "img_a3f9c2e17b04" / "silhouette.txt").read_text(
        encoding="utf-8"
    ) == "[1, 2, 3, 4]"


def test_cli_exposes_stage_force_skip_plan_flags() -> None:
    result = CliRunner().invoke(
        main,
        [
            "run",
            "img_a3f9c2e17b04",
            "--stage",
            "S04",
            "--stage",
            "S02",
            "--force",
            "S03",
            "--skip",
            "S04",
            "--plan-only",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["S02", "S03"]


def test_transient_failure_retries_exactly_twice_with_backoff(tmp_path: Path) -> None:
    calls = 0
    delays: list[float] = []

    def runner(context):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise OSError("temporary IO")
        return {"attempt": calls}

    result = run_pipeline(
        "img_a3f9c2e17b04",
        selected=("S02",),
        work_root=tmp_path,
        runners={"S02": runner},
        sleeper=delays.append,
    )
    assert result[0].status == "complete"
    assert calls == 3
    assert delays == [1.0, 2.0]


def _batch_database(path: Path, image_ids: tuple[str, ...]) -> None:
    initialize_database(path)
    with writer_connection(path) as connection:
        for index, image_id in enumerate(image_ids):
            connection.execute(
                "INSERT INTO images VALUES (?, ?, ?, ?, ?, ?, ?)",
                (image_id, f"{index + 1:064x}", "ingested", "S00", 1, "t0", "t0"),
            )


def test_semantic_failure_routes_review_and_batch_continues(tmp_path: Path) -> None:
    image_ids = ("img_a3f9c2e17b04", "img_b3f9c2e17b04")
    database = tmp_path / "state.sqlite"
    _batch_database(database, image_ids)

    def runner(context):
        if context.image_id == image_ids[0]:
            raise SemanticStageError("ambiguous boundary")
        return {"ok": True}

    outcomes = run_batch(
        image_ids,
        database=database,
        selected=("S02",),
        work_root=tmp_path / "work",
        runners={"S02": runner},
        sleeper=lambda _: None,
    )
    assert [outcome.status for outcome in outcomes] == ["needs_review", "complete"]
    records = [
        json.loads(line)
        for line in (tmp_path / "work" / "queues" / "review_queue.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert records[0]["route"] == "review"
    assert records[0]["attempts"] == 1


def test_fatal_failure_quarantines_image_and_batch_continues(tmp_path: Path) -> None:
    image_ids = ("img_a3f9c2e17b04", "img_b3f9c2e17b04")
    database = tmp_path / "state.sqlite"
    _batch_database(database, image_ids)

    def runner(context):
        if context.image_id == image_ids[0]:
            raise FatalStageError("corrupt source")
        return {"ok": True}

    outcomes = run_batch(
        image_ids,
        database=database,
        selected=("S02",),
        work_root=tmp_path / "work",
        runners={"S02": runner},
        sleeper=lambda _: None,
    )
    assert [outcome.status for outcome in outcomes] == ["quarantined", "complete"]
    with reader_connection(database) as connection:
        status = connection.execute(
            "SELECT status FROM images WHERE image_id = ?", (image_ids[0],)
        ).fetchone()[0]
    assert status == "quarantined"
    record = json.loads(
        (tmp_path / "work" / "queues" / "quarantine_queue.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert record["route"] == "quarantine"
    assert record["category"] == "fatal"


def test_exhausted_transient_failure_is_quarantined_after_three_attempts(
    tmp_path: Path,
) -> None:
    image_ids = ("img_a3f9c2e17b04",)
    database = tmp_path / "state.sqlite"
    _batch_database(database, image_ids)
    calls = 0

    def runner(context):
        nonlocal calls
        calls += 1
        raise MemoryError("OOM")

    outcome = run_batch(
        image_ids,
        database=database,
        selected=("S02",),
        work_root=tmp_path / "work",
        runners={"S02": runner},
        sleeper=lambda _: None,
    )[0]
    assert outcome.status == "quarantined"
    assert outcome.attempts == 3
    assert calls == 3
