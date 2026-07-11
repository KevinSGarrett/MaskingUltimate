"""Fail-closed MMSeg training launcher with immutable run and GPU ownership."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

from ..gpu import GpuLock
from .mmseg_compile import TrainingCompileError, compile_mmseg_config, write_mmengine_config
from .run import initialize_training_run, transition_training_run
from .runtime import TrainingRuntimeReport, probe_openmmlab_runtime


class TrainingLaunchError(RuntimeError):
    """A real training launch failed a gate or produced incomplete evidence."""


def dataset_instance_count(dataset_root: Path) -> int:
    """Count unique instances from the immutable builder manifest, not filesystem guesses."""
    path = Path(dataset_root) / "build_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingLaunchError(f"dataset build manifest is unreadable: {path}") from exc
    instances = manifest.get("instances")
    if not isinstance(instances, dict):
        raise TrainingLaunchError("dataset build manifest lacks instances by split")
    flattened: list[str] = []
    for split in ("train", "val", "test_holdout", "hard_case_holdout"):
        values = instances.get(split)
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise TrainingLaunchError(f"dataset build manifest has invalid {split} instances")
        flattened.extend(values)
    if len(flattened) != len(set(flattened)):
        raise TrainingLaunchError("dataset build manifest repeats an instance across splits")
    return len(flattened)


def launch_training(
    *,
    model: str,
    dataset_root: Path,
    config_path: Path,
    dvc_md5: str,
    runs_root: Path,
    runtime_probe: Callable[[], TrainingRuntimeReport] = probe_openmmlab_runtime,
    process_factory: Callable[..., Any] = subprocess.Popen,
) -> Path:
    """Initialize, compile, execute, and finalize one governed local training run."""
    dataset_root = Path(dataset_root).resolve()
    config_path = Path(config_path).resolve()
    if dataset_instance_count(dataset_root) < 200:
        raise TrainingLaunchError("P5 entry gate requires at least 200 approved dataset instances")
    report = runtime_probe()
    if not report.ready:
        raise TrainingLaunchError(
            "OpenMMLab training runtime is not ready: " + "; ".join(report.issues)
        )
    try:
        governed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TrainingLaunchError(f"training config is unreadable: {config_path}") from exc
    if not isinstance(governed, dict):
        raise TrainingLaunchError("training config must be a mapping")
    run_root = initialize_training_run(
        model=model,
        dataset_root=dataset_root,
        config_path=config_path,
        dvc_md5=dvc_md5,
        runs_root=runs_root,
    )
    try:
        compiled = compile_mmseg_config(governed, dataset_root=dataset_root, work_dir=run_root)
        compiled_path = write_mmengine_config(compiled, run_root / "mmengine_config.py")
    except Exception as exc:
        transition_training_run(run_root, "failed", detail=f"compile failed: {exc}")
        if isinstance(exc, TrainingCompileError):
            raise TrainingLaunchError(str(exc)) from exc
        raise
    command = [
        sys.executable,
        "-c",
        (
            "from mmengine.config import Config; "
            "from mmengine.runner import Runner; "
            f"Runner.from_cfg(Config.fromfile({str(compiled_path)!r})).train()"
        ),
    ]
    (run_root / "trainer_command.json").write_text(
        json.dumps(command, indent=2) + "\n", encoding="utf-8"
    )
    lock = GpuLock(Path(runs_root) / "gpu.lock", purpose="training", image_id=run_root.name)
    try:
        with lock:
            transition_training_run(run_root, "running")
            with (
                (run_root / "trainer_stdout.log").open("w", encoding="utf-8") as stdout,
                (run_root / "trainer_stderr.log").open("w", encoding="utf-8") as stderr,
            ):
                process = process_factory(
                    command,
                    cwd=str(Path.cwd()),
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                )
                returncode = int(process.wait())
            if returncode:
                raise TrainingLaunchError(f"MMSeg trainer exited {returncode}")
            checkpoints = sorted((run_root / "ckpts").glob("*.pth"))
            if not checkpoints:
                raise TrainingLaunchError("MMSeg exited zero without a checkpoint")
            transition_training_run(
                run_root,
                "complete",
                detail=f"checkpoint={checkpoints[-1].name}",
            )
    except Exception as exc:
        document = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
        if document["status"] in {"initialized", "running"}:
            transition_training_run(run_root, "failed", detail=str(exc))
        if isinstance(exc, TrainingLaunchError):
            raise
        raise TrainingLaunchError(str(exc)) from exc
    return run_root
