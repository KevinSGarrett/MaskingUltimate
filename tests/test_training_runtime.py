import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from maskfactory.training.dataset import _load_mmseg_components
from maskfactory.training.runtime import (
    TrainingRuntimeError,
    evaluate_openmmlab_runtime,
    load_training_stack_lock,
    validate_bodypart_class_contract,
)


def test_openmmlab_lock_has_exact_compatible_immutable_sources() -> None:
    lock = load_training_stack_lock()
    assert {name: item["version"] for name, item in lock["packages"].items()} == {
        "mmengine": "0.10.7",
        "mmcv": "2.1.0",
        "mmsegmentation": "1.2.2",
        "mmdet": "3.3.0",
    }
    assert lock["compatibility"]["mmcv"] == ">=2.0.0rc4,<2.2.0"
    assert lock["packages"]["mmcv"]["build_from_source"] is True
    assert lock["packages"]["mmcv"]["required_extension"] == "mmcv._ext"
    assert all(len(item["source_commit"]) == 40 for item in lock["packages"].values())


def test_runtime_evaluator_requires_exact_versions_full_ops_datasets_and_sm120() -> None:
    lock = load_training_stack_lock()
    versions = {name: item["version"] for name, item in lock["packages"].items()}
    ready = evaluate_openmmlab_runtime(
        versions=versions,
        torch_version="2.11.0+cu128",
        mmcv_ops_loaded=True,
        datasets_registered=True,
        transforms_registered=True,
        metric_registered=True,
        cuda_available=True,
        cuda_capability=(12, 0),
        lock=lock,
    )
    assert ready.ready and ready.as_dict()["cuda_capability"] == [12, 0]
    broken = evaluate_openmmlab_runtime(
        versions=versions | {"mmcv": "2.1.1"},
        torch_version="2.11.0+cu128",
        mmcv_ops_loaded=False,
        datasets_registered=False,
        transforms_registered=False,
        metric_registered=False,
        cuda_available=False,
        cuda_capability=None,
        lock=lock,
    )
    assert not broken.ready
    assert any("mmcv-lite is insufficient" in issue for issue in broken.issues)
    assert any("version mismatch: mmcv" in issue for issue in broken.issues)


def test_optional_mmseg_loader_only_swallows_missing_top_level_package() -> None:
    def missing(_name: str):
        raise ModuleNotFoundError("No module named 'mmseg'", name="mmseg")

    assert _load_mmseg_components(missing) == (None, None)

    def broken(_name: str):
        raise ModuleNotFoundError("No module named 'mmcv._ext'", name="mmcv._ext")

    with pytest.raises(ModuleNotFoundError, match="mmcv._ext"):
        _load_mmseg_components(broken)

    modules = {
        "mmseg.datasets": SimpleNamespace(BaseSegDataset=object()),
        "mmseg.registry": SimpleNamespace(DATASETS=object()),
    }
    base, registry = _load_mmseg_components(modules.__getitem__)
    assert base is modules["mmseg.datasets"].BaseSegDataset
    assert registry is modules["mmseg.registry"].DATASETS


@pytest.mark.parametrize("name", ["bodypart_segformer_b3.yaml", "bodypart_mask2former_swinb.yaml"])
def test_bodypart_class_contract_accepts_governed_v1_and_refuses_drift(name: str) -> None:
    config = yaml.safe_load(Path("configs/training", name).read_text(encoding="utf-8"))
    validate_bodypart_class_contract(config)
    drifted = json.loads(json.dumps(config))
    drifted["model"]["num_classes"] = 57
    with pytest.raises(TrainingRuntimeError, match="57 logits.*require 56"):
        validate_bodypart_class_contract(drifted)
