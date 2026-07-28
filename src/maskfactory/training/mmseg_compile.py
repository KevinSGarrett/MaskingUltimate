"""Compile governed MaskFactory YAML into self-contained MMEngine/MMSeg config."""

from __future__ import annotations

import os
import pprint
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image

from ..ontology import get_ontology
from .augmentations import IGNORE_INDEX, validate_augmentation_config
from .dataset import mmseg_dataset_config, mmseg_training_dataset_bundle
from .runtime import TrainingRuntimeError, validate_bodypart_class_contract
from .thermal import mmengine_thermal_config

SEGFORMER_B3_CHECKPOINT = (
    "https://download.openmmlab.com/mmsegmentation/v0.5/pretrain/segformer/"
    "mit_b3_20220624-13b1141c.pth"
)
SWIN_B_22K_CHECKPOINT = (
    "https://download.openmmlab.com/mmsegmentation/v0.5/pretrain/swin/"
    "swin_base_patch4_window12_384_22k_20220317-e5c09f74.pth"
)


class TrainingCompileError(ValueError):
    """A governed training config cannot compile into an executable contract."""


def class_pixel_counts(
    dataset_root: Path,
    *,
    split: str,
    target: str,
    num_classes: int,
) -> tuple[int, ...]:
    """Scan only the named trainer split and count non-ignore indexed pixels."""
    root = Path(dataset_root)
    split_path = root / f"{split}.txt"
    if target not in {"part", "material"} or not split_path.is_file():
        raise TrainingCompileError(f"invalid or missing {target} split: {split_path}")
    sample_ids = [line.strip() for line in split_path.read_text().splitlines() if line.strip()]
    if not sample_ids:
        raise TrainingCompileError(f"training split is empty: {split_path}")
    annotation_root = root / f"{target}_seg" / "annotations"
    counts = np.zeros(num_classes, dtype=np.int64)
    for sample_id in sample_ids:
        path = annotation_root / f"{sample_id}.png"
        if not path.is_file():
            raise TrainingCompileError(f"training annotation is missing: {path}")
        labels = np.asarray(Image.open(path))
        if labels.ndim != 2 or not np.issubdtype(labels.dtype, np.integer):
            raise TrainingCompileError(f"training annotation is not an indexed 2-D map: {path}")
        valid = labels != IGNORE_INDEX
        invalid = np.unique(labels[valid][labels[valid] >= num_classes])
        if invalid.size:
            raise TrainingCompileError(
                f"training annotation {path} has out-of-range IDs: {invalid.tolist()}"
            )
        counts += np.bincount(labels[valid].astype(np.int64), minlength=num_classes)[:num_classes]
    return tuple(int(value) for value in counts)


def inverse_sqrt_class_weights(
    counts: Sequence[int], *, cap_multiplier: float = 8.0
) -> tuple[float, ...]:
    """Use sqrt(max_frequency/frequency), capped at x8; absent classes receive zero."""
    values = np.asarray(counts, dtype=np.float64)
    if values.ndim != 1 or not len(values) or (values < 0).any():
        raise TrainingCompileError("class pixel counts must be a non-empty nonnegative vector")
    if not np.isfinite(cap_multiplier) or cap_multiplier < 1:
        raise TrainingCompileError("class-weight cap_multiplier must be finite and >=1")
    positive = values > 0
    if not positive.any():
        raise TrainingCompileError("training split contains no labeled pixels")
    weights = np.zeros_like(values)
    weights[positive] = np.minimum(
        np.sqrt(float(values[positive].max()) / values[positive]), cap_multiplier
    )
    return tuple(float(value) for value in weights)


def compile_mmseg_config(
    governed: Mapping[str, Any],
    *,
    dataset_root: Path,
    work_dir: Path,
) -> dict[str, Any]:
    """Compile an exact body-part SegFormer-B3 or Mask2Former-SwinB release config."""
    try:
        validate_bodypart_class_contract(governed)
    except TrainingRuntimeError as exc:
        raise TrainingCompileError(str(exc)) from exc
    validate_augmentation_config(governed)
    if governed.get("task") != "bodypart_semantic_segmentation":
        raise TrainingCompileError("compiler currently accepts bodypart_semantic_segmentation")
    model_spec = governed.get("model")
    training = governed.get("training")
    optimizer = governed.get("optimizer")
    evaluation = governed.get("evaluation")
    if not all(
        isinstance(value, Mapping) for value in (model_spec, training, optimizer, evaluation)
    ):
        raise TrainingCompileError(
            "governed model/training/optimizer/evaluation blocks are required"
        )
    num_classes = int(model_spec["num_classes"])
    class_names = tuple(
        label.name
        for label in sorted(get_ontology().labels_for_map("part"), key=lambda label: int(label.id))
    )
    if num_classes != len(class_names):
        raise TrainingCompileError("body-part num_classes differs from ontology class names")
    counts = class_pixel_counts(dataset_root, split="train", target="part", num_classes=num_classes)
    class_weights = inverse_sqrt_class_weights(
        counts, cap_multiplier=float(training["class_weights"]["cap_multiplier"])
    )
    train_bundle = mmseg_training_dataset_bundle(dataset_root, "train", "part", governed)
    val_dataset = mmseg_dataset_config(dataset_root, "val", "part")
    val_dataset["pipeline"] = [
        {"type": "LoadImageFromFile"},
        {"type": "LoadAnnotations", "reduce_zero_label": False},
        {
            "type": "PackSegInputs",
            "meta_keys": (
                "img_path",
                "seg_map_path",
                "ori_shape",
                "img_shape",
                "pad_shape",
                "scale_factor",
                "flip",
                "flip_direction",
                "reduce_zero_label",
                "sample_id",
                "truth_tier",
                "training_loss_weight",
            ),
        },
    ]
    architecture = str(model_spec["architecture"])
    if architecture == "segformer_b3":
        model = _segformer_b3_model(num_classes, class_weights)
        model_custom_imports: list[str] = []
        weight_decay = 0.01
        clip_grad = None
        paramwise_cfg = {
            "custom_keys": {
                "pos_block": {"decay_mult": 0.0},
                "norm": {"decay_mult": 0.0},
                "head": {"lr_mult": 10.0},
            }
        }
    elif architecture == "mask2former_swin_b":
        if model_spec.get("backbone", {}).get("activation_checkpointing") is not True:
            raise TrainingCompileError("Mask2Former-SwinB requires activation checkpointing")
        model = _mask2former_swin_b_model(num_classes, class_weights)
        model_custom_imports = ["mmdet.models"]
        weight_decay = float(optimizer["weight_decay"])
        clip_grad = {"max_norm": 0.01, "norm_type": 2}
        paramwise_cfg = _swin_b_paramwise_cfg()
    else:
        raise TrainingCompileError(f"unsupported body-part architecture: {architecture}")
    iterations = int(training["iterations"])
    warmup = int(optimizer["schedule"]["warmup_iters"])
    interval = int(evaluation["interval_iters"])
    if iterations <= warmup or interval <= 0 or iterations % interval:
        raise TrainingCompileError("iteration/warmup/evaluation schedule is inconsistent")
    if training["amp"] != "bf16":
        raise TrainingCompileError("release training requires bf16 AMP")
    thermal = mmengine_thermal_config(governed)
    imports = list(train_bundle["custom_imports"]["imports"])
    imports.extend(model_custom_imports)
    imports.extend(thermal["custom_imports"]["imports"])
    custom_imports = {"imports": list(dict.fromkeys(imports)), "allow_failed_imports": False}
    metric = {
        "type": "MaskFactorySegMetric",
        "class_names": list(class_names),
        "ignore_index": IGNORE_INDEX,
    }
    return {
        "default_scope": "mmseg",
        "custom_imports": custom_imports,
        "work_dir": str(Path(work_dir).resolve()),
        "randomness": {"seed": 1337, "deterministic": True},
        "env_cfg": {
            "cudnn_benchmark": False,
            "mp_cfg": {"mp_start_method": "fork", "opencv_num_threads": 0},
            "dist_cfg": {"backend": "nccl"},
        },
        "model": model,
        "train_dataloader": {
            "batch_size": int(training["batch_per_gpu"]),
            "num_workers": 2,
            "persistent_workers": True,
            "sampler": {"type": "InfiniteSampler", "shuffle": True},
            "dataset": train_bundle["dataset"],
        },
        "val_dataloader": {
            "batch_size": 1,
            "num_workers": 2,
            "persistent_workers": True,
            "sampler": {"type": "DefaultSampler", "shuffle": False},
            "dataset": val_dataset,
        },
        "test_dataloader": {
            "batch_size": 1,
            "num_workers": 2,
            "persistent_workers": True,
            "sampler": {"type": "DefaultSampler", "shuffle": False},
            "dataset": val_dataset,
        },
        "optim_wrapper": {
            "type": "AmpOptimWrapper",
            "dtype": "bfloat16",
            "accumulative_counts": int(training["gradient_accumulation"]),
            "optimizer": {
                "type": "AdamW",
                "lr": float(optimizer["learning_rate"]),
                "betas": (0.9, 0.999),
                "weight_decay": weight_decay,
            },
            "clip_grad": clip_grad,
            "paramwise_cfg": paramwise_cfg,
        },
        "param_scheduler": [
            {
                "type": "LinearLR",
                "start_factor": 1e-6,
                "by_epoch": False,
                "begin": 0,
                "end": warmup,
            },
            {
                "type": "PolyLR",
                "eta_min": 0.0,
                "power": float(optimizer["schedule"]["power"]),
                "begin": warmup,
                "end": iterations,
                "by_epoch": False,
            },
        ],
        "train_cfg": {
            "type": "IterBasedTrainLoop",
            "max_iters": iterations,
            "val_interval": interval,
        },
        "val_cfg": {"type": "ValLoop"},
        "test_cfg": {"type": "TestLoop"},
        "val_evaluator": metric,
        "test_evaluator": metric,
        "default_hooks": {
            "timer": {"type": "IterTimerHook"},
            "logger": {"type": "LoggerHook", "interval": 50, "log_metric_by_epoch": False},
            "param_scheduler": {"type": "ParamSchedulerHook"},
            "checkpoint": {
                "type": "CheckpointHook",
                "by_epoch": False,
                "interval": interval,
                "save_best": "maskfactory/mIoU",
                "rule": "greater",
                "max_keep_ckpts": 3,
                "out_dir": str(Path(work_dir).resolve() / "ckpts"),
            },
            "sampler_seed": {"type": "DistSamplerSeedHook"},
            "visualization": {"type": "SegVisualizationHook"},
        },
        "custom_hooks": thermal["custom_hooks"],
        "log_processor": {"by_epoch": False},
        "log_level": "INFO",
        "load_from": None,
        "resume": False,
        "maskfactory_class_pixel_counts": list(counts),
        "maskfactory_class_weights": list(class_weights),
    }


def write_mmengine_config(config: Mapping[str, Any], output_path: Path) -> Path:
    """Atomically render one self-contained Python config with deterministic key order."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# AUTO-GENERATED by maskfactory.training.mmseg_compile; do not hand-edit.\n"]
    for key, value in config.items():
        lines.append(f"{key} = {pprint.pformat(value, width=100, sort_dicts=False)}\n")
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text("\n".join(lines), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _data_preprocessor() -> dict[str, Any]:
    return {
        "type": "SegDataPreProcessor",
        "mean": [123.675, 116.28, 103.53],
        "std": [58.395, 57.12, 57.375],
        "bgr_to_rgb": True,
        "pad_val": 0,
        "seg_pad_val": IGNORE_INDEX,
        "size": (512, 512),
        "test_cfg": {"size_divisor": 32},
    }


def _segformer_b3_model(num_classes: int, class_weights: Sequence[float]) -> dict[str, Any]:
    return {
        "type": "MaskFactoryWeightedEncoderDecoder",
        "data_preprocessor": _data_preprocessor(),
        "backbone": {
            "type": "MixVisionTransformer",
            "in_channels": 3,
            "embed_dims": 64,
            "num_stages": 4,
            "num_layers": [3, 4, 18, 3],
            "num_heads": [1, 2, 5, 8],
            "patch_sizes": [7, 3, 3, 3],
            "sr_ratios": [8, 4, 2, 1],
            "out_indices": (0, 1, 2, 3),
            "mlp_ratio": 4,
            "qkv_bias": True,
            "drop_rate": 0.0,
            "attn_drop_rate": 0.0,
            "drop_path_rate": 0.1,
            "init_cfg": {"type": "Pretrained", "checkpoint": SEGFORMER_B3_CHECKPOINT},
        },
        "decode_head": {
            "type": "SegformerHead",
            "in_channels": [64, 128, 320, 512],
            "in_index": [0, 1, 2, 3],
            "channels": 256,
            "dropout_ratio": 0.1,
            "num_classes": num_classes,
            "norm_cfg": {"type": "SyncBN", "requires_grad": True},
            "align_corners": False,
            "loss_decode": [
                {
                    "type": "CrossEntropyLoss",
                    "use_sigmoid": False,
                    "loss_weight": 1.0,
                    "class_weight": list(class_weights),
                },
                {
                    "type": "DiceLoss",
                    "use_sigmoid": False,
                    "activate": True,
                    "loss_weight": 1.0,
                    "ignore_index": IGNORE_INDEX,
                },
            ],
        },
        "train_cfg": {},
        "test_cfg": {"mode": "whole"},
    }


def _mask2former_swin_b_model(num_classes: int, class_weights: Sequence[float]) -> dict[str, Any]:
    return {
        "type": "MaskFactoryWeightedEncoderDecoder",
        "data_preprocessor": _data_preprocessor(),
        "backbone": {
            "type": "SwinTransformer",
            "pretrain_img_size": 384,
            "embed_dims": 128,
            "depths": [2, 2, 18, 2],
            "num_heads": [4, 8, 16, 32],
            "window_size": 12,
            "mlp_ratio": 4,
            "qkv_bias": True,
            "qk_scale": None,
            "drop_rate": 0.0,
            "attn_drop_rate": 0.0,
            "drop_path_rate": 0.3,
            "patch_norm": True,
            "out_indices": (0, 1, 2, 3),
            "with_cp": True,
            "frozen_stages": -1,
            "init_cfg": {"type": "Pretrained", "checkpoint": SWIN_B_22K_CHECKPOINT},
        },
        "decode_head": {
            "type": "Mask2FormerHead",
            "in_channels": [128, 256, 512, 1024],
            "strides": [4, 8, 16, 32],
            "feat_channels": 256,
            "out_channels": 256,
            "num_classes": num_classes,
            "num_queries": 100,
            "num_transformer_feat_level": 3,
            "align_corners": False,
            "pixel_decoder": {
                "type": "mmdet.MSDeformAttnPixelDecoder",
                "num_outs": 3,
                "norm_cfg": {"type": "GN", "num_groups": 32},
                "act_cfg": {"type": "ReLU"},
                "encoder": {
                    "num_layers": 6,
                    "layer_cfg": {
                        "self_attn_cfg": {
                            "embed_dims": 256,
                            "num_heads": 8,
                            "num_levels": 3,
                            "num_points": 4,
                            "im2col_step": 64,
                            "dropout": 0.0,
                            "batch_first": True,
                            "norm_cfg": None,
                            "init_cfg": None,
                        },
                        "ffn_cfg": {
                            "embed_dims": 256,
                            "feedforward_channels": 1024,
                            "num_fcs": 2,
                            "ffn_drop": 0.0,
                            "act_cfg": {"type": "ReLU", "inplace": True},
                        },
                    },
                    "init_cfg": None,
                },
                "positional_encoding": {"num_feats": 128, "normalize": True},
                "init_cfg": None,
            },
            "enforce_decoder_input_project": False,
            "positional_encoding": {"num_feats": 128, "normalize": True},
            "transformer_decoder": {
                "return_intermediate": True,
                "num_layers": 9,
                "layer_cfg": {
                    "self_attn_cfg": {
                        "embed_dims": 256,
                        "num_heads": 8,
                        "attn_drop": 0.0,
                        "proj_drop": 0.0,
                        "dropout_layer": None,
                        "batch_first": True,
                    },
                    "cross_attn_cfg": {
                        "embed_dims": 256,
                        "num_heads": 8,
                        "attn_drop": 0.0,
                        "proj_drop": 0.0,
                        "dropout_layer": None,
                        "batch_first": True,
                    },
                    "ffn_cfg": {
                        "embed_dims": 256,
                        "feedforward_channels": 2048,
                        "num_fcs": 2,
                        "act_cfg": {"type": "ReLU", "inplace": True},
                        "ffn_drop": 0.0,
                        "dropout_layer": None,
                        "add_identity": True,
                    },
                },
                "init_cfg": None,
            },
            "loss_cls": {
                "type": "mmdet.CrossEntropyLoss",
                "use_sigmoid": False,
                "loss_weight": 2.0,
                "reduction": "mean",
                "class_weight": [*class_weights, 0.1],
            },
            "loss_mask": {
                "type": "mmdet.CrossEntropyLoss",
                "use_sigmoid": True,
                "reduction": "mean",
                "loss_weight": 5.0,
            },
            "loss_dice": {
                "type": "mmdet.DiceLoss",
                "use_sigmoid": True,
                "activate": True,
                "reduction": "mean",
                "naive_dice": True,
                "eps": 1.0,
                "loss_weight": 5.0,
            },
            "train_cfg": {
                "num_points": 12544,
                "oversample_ratio": 3.0,
                "importance_sample_ratio": 0.75,
                "assigner": {
                    "type": "mmdet.HungarianAssigner",
                    "match_costs": [
                        {"type": "mmdet.ClassificationCost", "weight": 2.0},
                        {
                            "type": "mmdet.CrossEntropyLossCost",
                            "weight": 5.0,
                            "use_sigmoid": True,
                        },
                        {"type": "mmdet.DiceCost", "weight": 5.0, "pred_act": True, "eps": 1.0},
                    ],
                },
                "sampler": {"type": "mmdet.MaskPseudoSampler"},
            },
        },
        "train_cfg": {},
        "test_cfg": {"mode": "whole"},
    }


def _swin_b_paramwise_cfg() -> dict[str, Any]:
    norm = {"lr_mult": 0.1, "decay_mult": 0.0}
    embed = {"lr_mult": 1.0, "decay_mult": 0.0}
    custom_keys: dict[str, dict[str, float]] = {
        "backbone": {"lr_mult": 0.1, "decay_mult": 1.0},
        "backbone.patch_embed.norm": norm,
        "backbone.norm": norm,
        "absolute_pos_embed": {"lr_mult": 0.1, "decay_mult": 0.0},
        "relative_position_bias_table": {"lr_mult": 0.1, "decay_mult": 0.0},
        "query_embed": embed,
        "query_feat": embed,
        "level_embed": embed,
    }
    depths = [2, 2, 18, 2]
    custom_keys.update(
        {
            f"backbone.stages.{stage}.blocks.{block}.norm": norm
            for stage, depth in enumerate(depths)
            for block in range(depth)
        }
    )
    custom_keys.update(
        {f"backbone.stages.{stage}.downsample.norm": norm for stage in range(len(depths) - 1)}
    )
    return {"custom_keys": custom_keys, "norm_decay_mult": 0.0}
