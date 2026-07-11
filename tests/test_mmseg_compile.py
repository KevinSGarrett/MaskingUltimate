import copy
import runpy
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from maskfactory.training.mmseg_compile import (
    TrainingCompileError,
    class_pixel_counts,
    compile_mmseg_config,
    inverse_sqrt_class_weights,
    write_mmengine_config,
)


def _dataset(tmp_path: Path) -> Path:
    root = tmp_path / "bodyparts@v1"
    for split, sample_id in (("train", "img_train_p0"), ("val", "img_val_p0")):
        (root / "part_seg/images").mkdir(parents=True, exist_ok=True)
        (root / "part_seg/annotations").mkdir(parents=True, exist_ok=True)
        (root / split).mkdir(exist_ok=True)
        Image.new("RGB", (8, 6), "gray").save(root / f"part_seg/images/{sample_id}.png")
        labels = np.zeros((6, 8), dtype=np.uint8)
        labels[:, 4:] = 1
        if split == "train":
            labels[0, 0] = 2
            labels[1, 1] = 255
        Image.fromarray(labels, mode="L").save(root / f"part_seg/annotations/{sample_id}.png")
        (root / f"{split}.txt").write_text(sample_id + "\n", encoding="utf-8")
    return root


def _corrected(name: str) -> dict:
    config = yaml.safe_load(Path("configs/training", name).read_text(encoding="utf-8"))
    config["model"]["num_classes"] = 56
    return config


def test_pixel_counts_ignore_255_and_inverse_sqrt_weights_are_capped(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    counts = class_pixel_counts(root, split="train", target="part", num_classes=56)
    assert counts[:4] == (22, 24, 1, 0)
    assert sum(counts) == 47
    weights = inverse_sqrt_class_weights(counts, cap_multiplier=8)
    assert weights[1] == 1.0
    assert weights[2] == pytest.approx(np.sqrt(24))
    assert weights[3] == 0.0
    assert max(weights) <= 8


def test_compile_segformer_is_self_contained_and_exact(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    compiled = compile_mmseg_config(
        _corrected("bodypart_segformer_b3.yaml"),
        dataset_root=root,
        work_dir=tmp_path / "run",
    )
    assert compiled["model"]["backbone"]["num_layers"] == [3, 4, 18, 3]
    assert compiled["model"]["decode_head"]["num_classes"] == 56
    assert [loss["type"] for loss in compiled["model"]["decode_head"]["loss_decode"]] == [
        "CrossEntropyLoss",
        "DiceLoss",
    ]
    assert compiled["optim_wrapper"]["type"] == "AmpOptimWrapper"
    assert compiled["optim_wrapper"]["dtype"] == "bfloat16"
    assert compiled["optim_wrapper"]["accumulative_counts"] == 8
    assert compiled["train_cfg"] == {
        "type": "IterBasedTrainLoop",
        "max_iters": 40000,
        "val_interval": 4000,
    }
    assert compiled["val_evaluator"]["type"] == "MaskFactorySegMetric"
    assert len(compiled["val_evaluator"]["class_names"]) == 56
    output = write_mmengine_config(compiled, tmp_path / "compiled.py")
    loaded = runpy.run_path(str(output))
    assert loaded["model"] == compiled["model"]
    assert loaded["maskfactory_class_pixel_counts"] == compiled["maskfactory_class_pixel_counts"]


def test_compile_mask2former_uses_native_matcher_and_checkpointed_swin_b(
    tmp_path: Path,
) -> None:
    compiled = compile_mmseg_config(
        _corrected("bodypart_mask2former_swinb.yaml"),
        dataset_root=_dataset(tmp_path),
        work_dir=tmp_path / "run",
    )
    model = compiled["model"]
    assert model["backbone"]["type"] == "SwinTransformer"
    assert model["backbone"]["with_cp"] is True
    assert model["backbone"]["depths"] == [2, 2, 18, 2]
    assert model["decode_head"]["type"] == "Mask2FormerHead"
    assert model["decode_head"]["train_cfg"]["assigner"]["type"] == "mmdet.HungarianAssigner"
    assert len(model["decode_head"]["loss_cls"]["class_weight"]) == 57
    assert "mmdet.models" in compiled["custom_imports"]["imports"]
    assert compiled["optim_wrapper"]["clip_grad"] == {"max_norm": 0.01, "norm_type": 2}


def test_compiler_refuses_live_57_class_conflict_and_policy_drift(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    live = yaml.safe_load(
        Path("configs/training/bodypart_segformer_b3.yaml").read_text(encoding="utf-8")
    )
    with pytest.raises(TrainingCompileError, match="57 logits.*require 56"):
        compile_mmseg_config(live, dataset_root=root, work_dir=tmp_path / "run")
    drifted = copy.deepcopy(_corrected("bodypart_segformer_b3.yaml"))
    drifted["augmentations"][0]["rare_force_probability"] = 0.3
    with pytest.raises(ValueError, match="40% rare"):
        compile_mmseg_config(drifted, dataset_root=root, work_dir=tmp_path / "run")
