import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.training.run import (
    TrainingRunError,
    initialize_training_run,
    transition_training_run,
)


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "datasets/bodyparts@v7"
    dataset.mkdir(parents=True)
    (dataset / "build_manifest.json").write_text('{"dataset":"bodyparts@v7"}\n', encoding="utf-8")
    config = tmp_path / "body.yaml"
    config.write_text(
        "data: {seed: 1337}\naugmentations:\n  - {type: horizontal_flip}\n",
        encoding="utf-8",
    )
    return dataset, config


def test_training_run_tree_is_atomic_complete_and_immutable(tmp_path: Path) -> None:
    dataset, config = _inputs(tmp_path)
    created = initialize_training_run(
        model="SegFormer-B3",
        dataset_root=dataset,
        config_path=config,
        dvc_md5="a" * 32,
        runs_root=tmp_path / "runs",
        now=datetime(2026, 7, 11, 10, 30, tzinfo=UTC),
        git_sha="b" * 40,
    )
    assert created.name == "r_20260711T103000Z_segformer_b3_bodyparts_v7"
    assert {path.name for path in created.iterdir()} == {
        "run.json",
        "config.yaml",
        "git_sha",
        "dataset_ref",
        "dataset_dvc_md5",
        "ckpts",
        "tb",
        "eval",
    }
    document = json.loads((created / "run.json").read_text())
    assert document["status"] == "initialized"
    assert document["dataset_ref"] == "bodyparts@v7"
    assert document["dataset_dvc_md5"] == "a" * 32
    assert document["config_sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()
    assert (created / "config.yaml").read_bytes() == config.read_bytes()
    assert (created / "git_sha").read_text() == "b" * 40 + "\n"
    assert (created / "dataset_ref").read_text() == "bodyparts@v7\n"
    assert (created / "dataset_dvc_md5").read_text() == "a" * 32 + "\n"
    assert not list((tmp_path / "runs").glob(".*.tmp-*"))
    with pytest.raises(FileExistsError, match="already exists"):
        initialize_training_run(
            model="SegFormer-B3",
            dataset_root=dataset,
            config_path=config,
            dvc_md5="a" * 32,
            runs_root=tmp_path / "runs",
            now=datetime(2026, 7, 11, 10, 30, tzinfo=UTC),
            git_sha="b" * 40,
        )


def test_training_run_lifecycle_refuses_skips_and_final_mutation(tmp_path: Path) -> None:
    dataset, config = _inputs(tmp_path)
    run = initialize_training_run(
        model="hand_segformer_b2",
        dataset_root=dataset,
        config_path=config,
        dvc_md5="c" * 32,
        runs_root=tmp_path / "runs",
        now=datetime(2026, 7, 11, 10, 31, tzinfo=UTC),
        git_sha="d" * 40,
    )
    with pytest.raises(TrainingRunError, match="illegal"):
        transition_training_run(run, "complete")
    assert transition_training_run(run, "running")["status"] == "running"
    completed = transition_training_run(run, "complete", detail="holdouts scored")
    assert completed["status_detail"] == "holdouts scored"
    with pytest.raises(TrainingRunError, match="illegal"):
        transition_training_run(run, "running")


@pytest.mark.parametrize("dvc_md5", ["", "A" * 32, "a" * 31, "g" * 32])
def test_training_run_refuses_invalid_dataset_identity(tmp_path: Path, dvc_md5: str) -> None:
    dataset, config = _inputs(tmp_path)
    with pytest.raises(TrainingRunError, match="DVC md5"):
        initialize_training_run(
            model="body",
            dataset_root=dataset,
            config_path=config,
            dvc_md5=dvc_md5,
            runs_root=tmp_path / "runs",
            git_sha="e" * 40,
        )
    assert not (tmp_path / "runs").exists()


def test_train_cli_requires_explicit_initialize_only_and_creates_tree(tmp_path: Path) -> None:
    dataset, config = _inputs(tmp_path)
    arguments = [
        "train",
        "segformer_b3",
        "--dataset",
        str(dataset),
        "--config",
        str(config),
        "--dvc-md5",
        "f" * 32,
        "--runs-root",
        str(tmp_path / "runs"),
    ]
    refused = CliRunner().invoke(main, arguments)
    assert refused.exit_code == 1
    assert "trainer execution is not activated" in refused.output
    created = CliRunner().invoke(main, [*arguments, "--initialize-only"])
    assert created.exit_code == 0, created.output
    runs = list((tmp_path / "runs").glob("r_*"))
    assert len(runs) == 1
    assert json.loads((runs[0] / "run.json").read_text())["status"] == "initialized"
