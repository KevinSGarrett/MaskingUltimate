"""Fail-closed OpenMMLab training-runtime and class-contract checks."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..ontology import get_ontology

DEFAULT_LOCK_PATH = (
    Path(__file__).resolve().parents[3] / "env" / "openmmlab_training_stack.lock.json"
)
REQUIRED_PACKAGES = ("mmengine", "mmcv", "mmsegmentation", "mmdet")


class TrainingRuntimeError(RuntimeError):
    """The governed trainer cannot establish a coherent executable contract."""


@dataclass(frozen=True)
class TrainingRuntimeReport:
    versions: dict[str, str | None]
    torch_version: str | None
    mmcv_ops_loaded: bool
    datasets_registered: bool
    cuda_available: bool
    cuda_capability: tuple[int, int] | None
    issues: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "versions": self.versions,
            "torch_version": self.torch_version,
            "mmcv_ops_loaded": self.mmcv_ops_loaded,
            "datasets_registered": self.datasets_registered,
            "cuda_available": self.cuda_available,
            "cuda_capability": list(self.cuda_capability) if self.cuda_capability else None,
            "issues": list(self.issues),
        }


def load_training_stack_lock(path: Path = DEFAULT_LOCK_PATH) -> dict[str, Any]:
    """Load and structurally validate the immutable OpenMMLab runtime selection."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0.0":
        raise TrainingRuntimeError("OpenMMLab lock schema_version must be 1.0.0")
    packages = document.get("packages")
    if not isinstance(packages, dict) or set(packages) != set(REQUIRED_PACKAGES):
        raise TrainingRuntimeError(
            "OpenMMLab lock must define exactly mmengine/mmcv/mmsegmentation/mmdet"
        )
    for key in REQUIRED_PACKAGES:
        package = packages[key]
        if not isinstance(package, dict):
            raise TrainingRuntimeError(f"OpenMMLab lock package {key} must be a mapping")
        if package.get("distribution") != key or not isinstance(package.get("version"), str):
            raise TrainingRuntimeError(f"OpenMMLab lock package {key} identity is invalid")
        commit = package.get("source_commit")
        if not isinstance(commit, str) or len(commit) != 40:
            raise TrainingRuntimeError(f"OpenMMLab lock package {key} lacks a full source commit")
    runtime = document.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("compute_capability") != [12, 0]:
        raise TrainingRuntimeError("OpenMMLab lock must require compute capability [12, 0]")
    if runtime.get("torch") != "2.11.0+cu128":
        raise TrainingRuntimeError("OpenMMLab lock must target torch 2.11.0+cu128")
    return document


def evaluate_openmmlab_runtime(
    *,
    versions: Mapping[str, str | None],
    torch_version: str | None,
    mmcv_ops_loaded: bool,
    datasets_registered: bool,
    cuda_available: bool,
    cuda_capability: tuple[int, int] | None,
    lock: Mapping[str, Any],
) -> TrainingRuntimeReport:
    """Evaluate observed runtime facts against the exact lock without importing frameworks."""
    issues: list[str] = []
    packages = lock["packages"]
    normalized_versions = {key: versions.get(key) for key in REQUIRED_PACKAGES}
    for key in REQUIRED_PACKAGES:
        observed = normalized_versions[key]
        expected = packages[key]["version"]
        if observed is None:
            issues.append(f"missing distribution: {key}=={expected}")
        elif observed != expected:
            issues.append(f"version mismatch: {key} expected {expected}, observed {observed}")
    expected_torch = lock["runtime"]["torch"]
    if torch_version != expected_torch:
        issues.append(f"torch mismatch: expected {expected_torch}, observed {torch_version}")
    if not mmcv_ops_loaded:
        issues.append(
            "full MMCV ops extension mmcv._ext is unavailable (mmcv-lite is insufficient)"
        )
    if not datasets_registered:
        issues.append("MaskFactory MMSeg BaseSegDataset classes are not registered")
    if not cuda_available:
        issues.append("CUDA is unavailable to the training runtime")
    expected_capability = tuple(lock["runtime"]["compute_capability"])
    if cuda_capability != expected_capability:
        issues.append(
            f"CUDA capability mismatch: expected {expected_capability}, observed {cuda_capability}"
        )
    return TrainingRuntimeReport(
        versions=normalized_versions,
        torch_version=torch_version,
        mmcv_ops_loaded=mmcv_ops_loaded,
        datasets_registered=datasets_registered,
        cuda_available=cuda_available,
        cuda_capability=cuda_capability,
        issues=tuple(issues),
    )


def probe_openmmlab_runtime(path: Path = DEFAULT_LOCK_PATH) -> TrainingRuntimeReport:
    """Probe the real training process; every incomplete/broken install fails closed."""
    lock = load_training_stack_lock(path)
    versions: dict[str, str | None] = {}
    for distribution in REQUIRED_PACKAGES:
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = None

    mmcv_ops_loaded = False
    datasets_registered = False
    import_issues: list[str] = []
    if all(versions[key] == lock["packages"][key]["version"] for key in REQUIRED_PACKAGES):
        try:
            importlib.import_module("mmcv._ext")
            mmcv_ops_loaded = True
        except Exception as exc:  # pragma: no cover - exercised only in the real training env.
            import_issues.append(f"mmcv._ext import failed: {type(exc).__name__}: {exc}")
        try:
            dataset_module = importlib.import_module("maskfactory.training.dataset")
            datasets_registered = all(
                hasattr(dataset_module, name)
                for name in ("MaskFactoryBodyPartDataset", "MaskFactoryMaterialDataset")
            )
        except Exception as exc:  # pragma: no cover - exercised only in the real training env.
            import_issues.append(f"MMSeg dataset import failed: {type(exc).__name__}: {exc}")

    torch_version: str | None = None
    cuda_available = False
    cuda_capability: tuple[int, int] | None = None
    try:
        torch = importlib.import_module("torch")
        torch_version = str(torch.__version__)
        cuda_available = bool(torch.cuda.is_available())
        if cuda_available:
            cuda_capability = tuple(int(value) for value in torch.cuda.get_device_capability(0))
    except Exception as exc:  # pragma: no cover - exercised only in the real training env.
        import_issues.append(f"torch/CUDA probe failed: {type(exc).__name__}: {exc}")

    report = evaluate_openmmlab_runtime(
        versions=versions,
        torch_version=torch_version,
        mmcv_ops_loaded=mmcv_ops_loaded,
        datasets_registered=datasets_registered,
        cuda_available=cuda_available,
        cuda_capability=cuda_capability,
        lock=lock,
    )
    if not import_issues:
        return report
    return TrainingRuntimeReport(
        versions=report.versions,
        torch_version=report.torch_version,
        mmcv_ops_loaded=report.mmcv_ops_loaded,
        datasets_registered=report.datasets_registered,
        cuda_available=report.cuda_available,
        cuda_capability=report.cuda_capability,
        issues=(*report.issues, *import_issues),
    )


def validate_bodypart_class_contract(config: Mapping[str, Any]) -> None:
    """Refuse the unresolved 57-logit config against the authoritative 0..55 map."""
    if config.get("task") != "bodypart_semantic_segmentation":
        return
    model = config.get("model")
    if not isinstance(model, Mapping) or not isinstance(model.get("num_classes"), int):
        raise TrainingRuntimeError("body-part training config lacks model.num_classes")
    labels = get_ontology().labels_for_map("part")
    ontology_classes = len(labels)
    declared = int(model["num_classes"])
    if declared != ontology_classes:
        ids = sorted(int(label.id) for label in labels if label.id is not None)
        raise TrainingRuntimeError(
            "body-part class-count conflict: config declares "
            f"{declared} logits but authoritative indexed IDs {ids[0]}..{ids[-1]} require "
            f"{ontology_classes}; resolve Plan/DECISIONS_LOG.md before training"
        )
