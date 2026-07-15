"""Fail-closed MMSeg training launcher with immutable run and GPU ownership."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

import yaml

from ..datasets.authority import P5_CERTIFIED_ENTRY_COUNT, serialized_reader_capabilities
from ..gpu import GpuLock
from ..models.ontology_contract import (
    V1_ONTOLOGY_VERSION,
    V1_PART_CLASS_NAMES,
    V2_ONTOLOGY_VERSION,
    V2_PART_CLASS_NAMES,
    class_names_sha256,
)
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
    for split in ("train", "val", "calibration", "test_holdout", "hard_case_holdout"):
        values = instances.get(split)
        if split == "calibration" and values is None:
            values = []
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise TrainingLaunchError(f"dataset build manifest has invalid {split} instances")
        flattened.extend(values)
    if len(flattened) != len(set(flattened)):
        raise TrainingLaunchError("dataset build manifest repeats an instance across splits")
    return len(flattened)


def validate_training_dataset_authority(dataset_root: Path) -> int:
    """Fail closed unless trainer inputs contain only training-partition truth.

    Returns the certified training-package count used by the P5 entry gate. The
    diagnostic pseudo-label weight total is deliberately not a volume count.
    """
    root = Path(dataset_root)
    try:
        build = json.loads((root / "build_manifest.json").read_text(encoding="utf-8"))
        weights = json.loads((root / "sample_weights.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingLaunchError("training dataset authority files are unreadable") from exc
    if build.get("schema_version") != "2.0.0" or weights.get("schema_version") != "2.0.0":
        raise TrainingLaunchError("training requires dataset truth authority schema 2.0.0")
    expected_capabilities = serialized_reader_capabilities()
    if build.get("reader_capabilities") != expected_capabilities:
        raise TrainingLaunchError("dataset reader capability partition contract drifted")
    trainer_inputs = build.get("trainer_inputs")
    if not isinstance(trainer_inputs, list) or {
        "calibration",
        "holdout",
        "calibration/ids.txt",
    } & set(trainer_inputs):
        raise TrainingLaunchError("trainer inputs expose calibration or holdout authority")
    if (
        build.get("calibration_trainer_read_path") is not None
        or build.get("holdout_trainer_read_path") is not None
    ):
        raise TrainingLaunchError("trainer has a forbidden calibration/holdout read path")
    protected_path = build.get("protected_anchor_ids")
    if protected_path != "protected_anchor_ids.txt":
        raise TrainingLaunchError("dataset lacks the protected anchor identity capability")
    instances = build.get("instances")
    records = weights.get("samples")
    if not isinstance(instances, dict) or not isinstance(records, dict):
        raise TrainingLaunchError("dataset truth authority lacks instances or sample records")
    all_ids: list[str] = []
    governed_splits = list(
        dict.fromkeys(split for values in expected_capabilities.values() for split in values)
    )
    for split in governed_splits:
        values = instances.get(split)
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise TrainingLaunchError(f"dataset authority has invalid {split} instances")
        all_ids.extend(values)
    if len(all_ids) != len(set(all_ids)):
        raise TrainingLaunchError("dataset authority repeats an instance across capabilities")
    if set(all_ids) != set(records):
        raise TrainingLaunchError(
            "sample-weight authority does not exactly cover dataset instances"
        )
    for split in ("train", "val"):
        for sample_id in instances[split]:
            row = records[sample_id]
            if not isinstance(row, dict) or row.get("truth_partition") != "train":
                raise TrainingLaunchError(
                    f"trainer split contains non-training truth authority: {sample_id}"
                )
            if split == "train" and not 0 < float(row.get("training_loss_weight", 0)) <= 1:
                raise TrainingLaunchError(f"trainer sample has invalid loss weight: {sample_id}")
    for split, partition in (
        ("calibration", "calibration"),
        ("test_holdout", "holdout"),
        ("hard_case_holdout", "holdout"),
    ):
        for sample_id in instances[split]:
            row = records[sample_id]
            if (
                not isinstance(row, dict)
                or row.get("truth_tier") != "human_anchor_gold"
                or row.get("truth_partition") != partition
                or float(row.get("training_loss_weight", -1)) != 0.0
            ):
                raise TrainingLaunchError(
                    f"{split} lacks isolated human-anchor authority: {sample_id}"
                )
    try:
        protected_ids = {
            line.strip()
            for line in (root / protected_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    except OSError as exc:
        raise TrainingLaunchError("protected anchor identity file is unreadable") from exc
    expected_protected = {
        sample_id.rsplit("_p", 1)[0]
        for split in ("calibration", "test_holdout", "hard_case_holdout")
        for sample_id in instances[split]
    }
    if protected_ids != expected_protected:
        raise TrainingLaunchError("protected anchor identities do not match isolated partitions")
    computed = sum(
        row.get("truth_partition") == "train"
        and row.get("truth_tier") in {"human_anchor_gold", "autonomous_certified_gold"}
        for row in records.values()
        if isinstance(row, dict)
    )
    reported = build.get("truth_metrics", {}).get("certified_training_package_count")
    if not isinstance(reported, int) or reported != computed:
        raise TrainingLaunchError("certified training-volume metric is missing or inconsistent")
    return computed


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
    dataset_instance_count(dataset_root)
    if validate_training_dataset_authority(dataset_root) < P5_CERTIFIED_ENTRY_COUNT:
        raise TrainingLaunchError(
            f"P5 entry gate requires at least {P5_CERTIFIED_ENTRY_COUNT} certified training packages"
        )
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
            write_candidate_artifact(run_root, checkpoints[-1], compiled)
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


def write_candidate_artifact(
    run_root: Path, checkpoint: Path, compiled_config: dict[str, Any]
) -> Path:
    """Seal the exact reproducible inference artifacts from a successful training run."""
    root = Path(run_root).resolve()
    checkpoint = Path(checkpoint).resolve()
    config = (root / "mmengine_config.py").resolve()
    if root not in checkpoint.parents or checkpoint.parent != root / "ckpts":
        raise TrainingLaunchError("candidate checkpoint is outside the run ckpts directory")
    if not checkpoint.is_file() or not config.is_file():
        raise TrainingLaunchError("candidate checkpoint or generated inference config is missing")
    run = json.loads((root / "run.json").read_text(encoding="utf-8"))
    if run.get("status") != "running":
        raise TrainingLaunchError("candidate artifact may be sealed only while training is running")
    evaluator = compiled_config.get("val_evaluator")
    class_names = evaluator.get("class_names") if isinstance(evaluator, dict) else None
    if (
        not isinstance(class_names, list)
        or not class_names
        or not all(isinstance(name, str) and name for name in class_names)
        or len(class_names) != len(set(class_names))
    ):
        raise TrainingLaunchError("compiled config lacks a valid class_names vocabulary")
    vocabulary = tuple(class_names)
    if vocabulary == V1_PART_CLASS_NAMES:
        ontology_version = V1_ONTOLOGY_VERSION
    elif vocabulary == V2_PART_CLASS_NAMES:
        ontology_version = V2_ONTOLOGY_VERSION
    else:
        raise TrainingLaunchError("compiled body-part class_names are not exact v1 or v2 authority")
    checkpoint_sha256 = _file_sha256(checkpoint)
    inference_config_sha256 = _file_sha256(config)
    document = {
        "schema_version": "1.0.0",
        "run_id": run["run_id"],
        "model": run["model"],
        "dataset_ref": run["dataset_ref"],
        "dataset_dvc_md5": run["dataset_dvc_md5"],
        "target_champion_role": "champion_bodypart",
        "checkpoint": str(checkpoint.relative_to(root).as_posix()),
        "checkpoint_sha256": checkpoint_sha256,
        "inference_config": str(config.relative_to(root).as_posix()),
        "inference_config_sha256": inference_config_sha256,
        "class_names": class_names,
        "class_names_sha256": class_names_sha256(class_names),
        "ontology_version": ontology_version,
        "artifact_hashes": {
            "checkpoint_sha256": checkpoint_sha256,
            "inference_config_sha256": inference_config_sha256,
        },
    }
    path = root / "candidate_artifact.json"
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
