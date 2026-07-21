from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from maskfactory.ontology import get_ontology
from maskfactory.training.augmentations import AugmentationError, photometric_jitter
from maskfactory.training.dataset import mmseg_training_dataset_bundle
from maskfactory.training.mmseg_transforms import (
    MaskFactoryHorizontalFlip,
    MaskFactoryPhotometricJitter,
    MaskFactoryRandomResizedCrop,
    MaskFactoryRotate,
    _load_transform_registry,
    mmseg_augmentation_config,
)


def _sample() -> dict:
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[:, :, 0] = np.arange(64, dtype=np.uint8)
    labels = np.zeros((64, 64), dtype=np.uint8)
    labels[7, 51] = 24
    labels[20:50, 20:40] = 22
    return {"img": image, "gt_seg_map": labels, "img_shape": (64, 64)}


def test_mmseg_crop_forces_rare_pixel_and_updates_geometry() -> None:
    transform = MaskFactoryRandomResizedCrop(
        map_name="part",
        output_size=16,
        scale=(1.0, 1.0),
        rare_force_probability=1.0,
        rare_ids=(24,),
        rng=np.random.default_rng(1337),
    )
    result = transform(_sample())
    assert result["img"].shape == (16, 16, 3)
    assert result["gt_seg_map"].shape == (16, 16)
    assert result["img_shape"] == (16, 16)
    assert result["maskfactory_rare_forced"] is True
    assert 24 in result["gt_seg_map"]


def test_mmseg_flip_remaps_character_side_and_sets_metadata() -> None:
    ontology = get_ontology()
    sample = _sample()
    sample["gt_seg_map"][:] = ontology.label("left_hand_base").id
    result = MaskFactoryHorizontalFlip(
        map_name="part", probability=1.0, rng=np.random.default_rng(3)
    )(sample)
    assert np.all(result["gt_seg_map"] == ontology.label("right_hand_base").id)
    assert result["flip"] is True and result["flip_direction"] == "horizontal"


def test_mmseg_jitter_never_changes_labels_and_rotate_uses_ignore_border() -> None:
    sample = _sample()
    original = sample["gt_seg_map"].copy()
    original_bgr = sample["img"].copy()
    jittered = MaskFactoryPhotometricJitter(rng=np.random.default_rng(4))(sample)
    np.testing.assert_array_equal(jittered["gt_seg_map"], original)
    replay = np.random.default_rng(4)
    sampled = {
        "brightness": float(replay.uniform(-0.25, 0.25)),
        "contrast": float(replay.uniform(-0.25, 0.25)),
        "saturation": float(replay.uniform(-0.25, 0.25)),
        "hue": float(replay.uniform(-0.05, 0.05)),
    }
    expected_bgr = photometric_jitter(original_bgr[:, :, ::-1], **sampled)[:, :, ::-1]
    np.testing.assert_array_equal(jittered["img"], expected_bgr)
    rotated = MaskFactoryRotate(map_name="part", degrees=15, rng=np.random.default_rng(5))(jittered)
    assert 255 in rotated["gt_seg_map"]
    assert -15 <= rotated["maskfactory_rotation_degrees"] <= 15


def test_mmseg_pipeline_compiler_is_exact_and_refuses_drift() -> None:
    config = yaml.safe_load(
        Path("configs/training/bodypart_segformer_b3.yaml").read_text(encoding="utf-8")
    )
    compiled = mmseg_augmentation_config(config, map_name="part")
    assert compiled["custom_imports"] == {
        "imports": [
            "maskfactory.training.dataset",
            "maskfactory.training.mmseg_metric",
            "maskfactory.training.mmseg_transforms",
            "maskfactory.training.weighted_segmentor",
        ],
        "allow_failed_imports": False,
    }
    types = [item["type"] for item in compiled["train_pipeline"]]
    assert types == [
        "LoadImageFromFile",
        "mmseg.LoadAnnotations",
        "mmseg.MaskFactoryRandomResizedCrop",
        "mmseg.MaskFactoryHorizontalFlip",
        "mmseg.MaskFactoryPhotometricJitter",
        "mmseg.MaskFactoryRotate",
        "mmseg.PackSegInputs",
    ]
    rare_ids = compiled["train_pipeline"][2]["rare_ids"]
    assert set(rare_ids) == {8, *range(24, 34), 46, 47}
    assert compiled["train_pipeline"][4]["channel_order"] == "bgr"
    material = mmseg_augmentation_config(config, map_name="material")
    assert material["train_pipeline"][2]["rare_ids"] == (10,)
    config["augmentations"][1]["swap_partner_remap"] = False
    with pytest.raises(AugmentationError, match="swap remap"):
        mmseg_augmentation_config(config, map_name="part")


def test_training_dataset_bundle_cannot_omit_governed_pipeline(tmp_path: Path) -> None:
    (tmp_path / "train.txt").write_text("img_a_p0\n", encoding="utf-8")
    config = yaml.safe_load(
        Path("configs/training/bodypart_segformer_b3.yaml").read_text(encoding="utf-8")
    )
    bundle = mmseg_training_dataset_bundle(tmp_path, "train", "part", config)
    assert bundle["dataset"]["type"] == "MaskFactoryBodyPartDataset"
    assert (
        bundle["dataset"]["pipeline"]
        == mmseg_augmentation_config(config, map_name="part")["train_pipeline"]
    )
    assert bundle["custom_imports"]["allow_failed_imports"] is False


def test_transform_registry_loader_only_swallows_absent_top_level_mmseg() -> None:
    def missing(_name: str):
        raise ModuleNotFoundError("No module named 'mmseg'", name="mmseg")

    assert _load_transform_registry(missing) is None

    def broken(_name: str):
        raise ModuleNotFoundError("No module named 'mmcv._ext'", name="mmcv._ext")

    with pytest.raises(ModuleNotFoundError, match="mmcv._ext"):
        _load_transform_registry(broken)
    registry = object()
    assert _load_transform_registry(lambda _name: SimpleNamespace(TRANSFORMS=registry)) is registry
