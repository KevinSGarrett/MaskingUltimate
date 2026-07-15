import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.datasets.authority import serialized_reader_capabilities
from maskfactory.models.registry import resolve_registered_model
from maskfactory.training.launch import (
    TrainingLaunchError,
    dataset_instance_count,
    launch_training,
    validate_training_dataset_authority,
)
from maskfactory.training.runtime import TrainingRuntimeReport


def _dataset(tmp_path: Path, *, count: int = 200) -> Path:
    root = tmp_path / "bodyparts@v3"
    root.mkdir(parents=True)
    instances = [f"img_{index:012d}_p0" for index in range(count)]
    train_end = max(1, count - 1)
    manifest = {
        "schema_version": "2.0.0",
        "instances": {
            "train": instances[:train_end],
            "val": instances[train_end:],
            "calibration": [],
            "test_holdout": [],
            "hard_case_holdout": [],
        },
        "trainer_inputs": ["train.txt", "val.txt", "sample_weights.json", "part_seg"],
        "holdout_trainer_read_path": None,
        "calibration_trainer_read_path": None,
        "protected_anchor_ids": "protected_anchor_ids.txt",
        "reader_capabilities": serialized_reader_capabilities(),
        "truth_metrics": {"certified_training_package_count": count},
    }
    (root / "build_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "sample_weights.json").write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "samples": {
                    sample_id: {
                        "truth_tier": "human_anchor_gold",
                        "truth_partition": "train",
                        "training_loss_weight": 1.0 if index < train_end else 0.0,
                    }
                    for index, sample_id in enumerate(instances)
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "protected_anchor_ids.txt").write_text("", encoding="utf-8")
    for split, sample_id in (("train", instances[0]), ("val", instances[train_end])):
        (root / "part_seg/images").mkdir(parents=True, exist_ok=True)
        (root / "part_seg/annotations").mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4), "gray").save(root / f"part_seg/images/{sample_id}.png")
        Image.fromarray(np.zeros((4, 4), dtype=np.uint8), mode="L").save(
            root / f"part_seg/annotations/{sample_id}.png"
        )
        (root / f"{split}.txt").write_text(sample_id + "\n", encoding="utf-8")
    return root


def _config(tmp_path: Path) -> Path:
    config = yaml.safe_load(
        Path("configs/training/bodypart_segformer_b3.yaml").read_text(encoding="utf-8")
    )
    config["model"]["num_classes"] = 56
    path = tmp_path / "body.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _ready() -> TrainingRuntimeReport:
    return TrainingRuntimeReport(
        versions={
            "mmengine": "0.10.7",
            "mmcv": "2.1.0",
            "mmsegmentation": "1.2.2",
            "mmdet": "3.3.0",
        },
        torch_version="2.11.0+cu128",
        mmcv_ops_loaded=True,
        datasets_registered=True,
        transforms_registered=True,
        metric_registered=True,
        cuda_available=True,
        cuda_capability=(12, 0),
        issues=(),
    )


def test_dataset_instance_gate_counts_all_splits_and_refuses_duplicates(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    assert dataset_instance_count(root) == 200
    manifest = json.loads((root / "build_manifest.json").read_text())
    manifest["instances"]["val"] = [manifest["instances"]["train"][0]]
    (root / "build_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(TrainingLaunchError, match="repeats an instance"):
        dataset_instance_count(root)


def test_training_authority_rejects_calibration_leak_and_pseudo_volume(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    assert validate_training_dataset_authority(root) == 200
    build = json.loads((root / "build_manifest.json").read_text(encoding="utf-8"))
    leaked = build["instances"]["train"][0]
    weights = json.loads((root / "sample_weights.json").read_text(encoding="utf-8"))
    weights["samples"][leaked]["truth_partition"] = "calibration"
    weights["samples"][leaked]["training_loss_weight"] = 0.0
    (root / "sample_weights.json").write_text(json.dumps(weights), encoding="utf-8")
    with pytest.raises(TrainingLaunchError, match="non-training truth"):
        validate_training_dataset_authority(root)

    weights["samples"][leaked] = {
        "truth_tier": "weighted_pseudo_label",
        "truth_partition": "train",
        "training_loss_weight": 0.2,
    }
    build["truth_metrics"]["certified_training_package_count"] = 199
    (root / "sample_weights.json").write_text(json.dumps(weights), encoding="utf-8")
    (root / "build_manifest.json").write_text(json.dumps(build), encoding="utf-8")
    assert validate_training_dataset_authority(root) == 199


def test_launcher_holds_gpu_runs_compiled_config_and_requires_checkpoint(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"

    class Process:
        def __init__(self, command, **kwargs):
            assert (runs_root / "gpu.lock").is_file()
            assert "Runner.from_cfg" in command[-1]
            run_root = next(runs_root.glob("r_*"))
            (run_root / "ckpts/iter_40000.pth").write_bytes(b"checkpoint")

        def wait(self):
            return 0

    run = launch_training(
        model="segformer_b3",
        dataset_root=_dataset(tmp_path),
        config_path=_config(tmp_path),
        dvc_md5="a" * 32,
        runs_root=runs_root,
        runtime_probe=_ready,
        process_factory=Process,
    )
    document = json.loads((run / "run.json").read_text())
    assert document["status"] == "complete"
    assert document["status_detail"] == "checkpoint=iter_40000.pth"
    assert (run / "mmengine_config.py").is_file()
    candidate = json.loads((run / "candidate_artifact.json").read_text())
    assert candidate["target_champion_role"] == "champion_bodypart"
    assert candidate["checkpoint"] == "ckpts/iter_40000.pth"
    assert len(candidate["class_names"]) == 56
    assert not (runs_root / "gpu.lock").exists()


def test_completed_run_registers_atomically_as_reproducible_nonchampion(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"

    class Process:
        def __init__(self, _command, **_kwargs):
            run_root = next(runs_root.glob("r_*"))
            (run_root / "ckpts/iter_40000.pth").write_bytes(b"candidate checkpoint")

        def wait(self):
            return 0

    run = launch_training(
        model="segformer_b3",
        dataset_root=_dataset(tmp_path),
        config_path=_config(tmp_path),
        dvc_md5="a" * 32,
        runs_root=runs_root,
        runtime_probe=_ready,
        process_factory=Process,
    )
    models_root = tmp_path / "models"
    registry = models_root / "registry.json"
    original_config = (run / "mmengine_config.py").read_bytes()
    (run / "mmengine_config.py").write_bytes(original_config + b"# tampered\n")
    failed = CliRunner().invoke(
        main,
        [
            "models",
            "register-training-candidate",
            str(run),
            "--key",
            "segformer_b3_bodyparts_v3",
            "--registry",
            str(registry),
            "--models-root",
            str(models_root),
        ],
    )
    assert failed.exit_code != 0
    assert "inference config hash mismatch" in failed.output
    assert not registry.exists()
    assert not (models_root / "trained/segformer_b3_bodyparts_v3").exists()

    (run / "mmengine_config.py").write_bytes(original_config)
    result = CliRunner().invoke(
        main,
        [
            "models",
            "register-training-candidate",
            str(run),
            "--key",
            "segformer_b3_bodyparts_v3",
            "--registry",
            str(registry),
            "--models-root",
            str(models_root),
        ],
    )
    assert result.exit_code == 0, result.output
    document = json.loads(registry.read_text())
    entry = document["models"][0]
    assert entry["role"] == "challenger_bodypart"
    assert entry["target_champion_role"] == "champion_bodypart"
    assert entry["training_run"] == run.name
    assert entry["dataset_ref"] == "bodyparts@v3"
    assert len(entry["class_names"]) == 56
    resolved = resolve_registered_model(
        "segformer_b3_bodyparts_v3", registry_path=registry, models_root=models_root
    )
    assert resolved.read_bytes() == b"candidate checkpoint"
    assert (resolved.parent / "inference_config.py").read_bytes() == original_config


def test_launcher_fails_before_run_when_entry_or_runtime_gate_is_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(TrainingLaunchError, match="at least 200"):
        launch_training(
            model="segformer_b3",
            dataset_root=_dataset(tmp_path / "small", count=4),
            config_path=config,
            dvc_md5="a" * 32,
            runs_root=tmp_path / "runs",
            runtime_probe=_ready,
        )
    ready = _ready()
    broken = TrainingRuntimeReport(**(ready.__dict__ | {"issues": ("mmcv missing",)}))
    with pytest.raises(TrainingLaunchError, match="mmcv missing"):
        launch_training(
            model="segformer_b3",
            dataset_root=_dataset(tmp_path / "broken"),
            config_path=config,
            dvc_md5="a" * 32,
            runs_root=tmp_path / "runs2",
            runtime_probe=lambda: broken,
        )


def test_zero_exit_without_checkpoint_marks_run_failed(tmp_path: Path) -> None:
    class Process:
        def __init__(self, *args, **kwargs):
            pass

        def wait(self):
            return 0

    with pytest.raises(TrainingLaunchError, match="without a checkpoint"):
        launch_training(
            model="segformer_b3",
            dataset_root=_dataset(tmp_path),
            config_path=_config(tmp_path),
            dvc_md5="a" * 32,
            runs_root=tmp_path / "runs",
            runtime_probe=_ready,
            process_factory=Process,
        )
    runs = list((tmp_path / "runs").glob("r_*"))
    assert len(runs) == 1
    assert json.loads((runs[0] / "run.json").read_text())["status"] == "failed"
