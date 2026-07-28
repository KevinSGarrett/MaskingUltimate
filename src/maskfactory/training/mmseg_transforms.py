"""MMSeg-registered wrappers for MaskFactory's ontology-safe augmentations."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, Callable, Mapping

import numpy as np

from .augmentations import (
    IGNORE_INDEX,
    AugmentationError,
    RareSamplingMeter,
    maybe_horizontal_flip,
    photometric_jitter,
    random_resized_crop,
    rotate_sample,
    validate_augmentation_config,
)

PART_RARE_NAMES = frozenset(
    {
        "belly_button",
        "left_thumb",
        "right_thumb",
        "left_index_finger",
        "right_index_finger",
        "left_middle_finger",
        "right_middle_finger",
        "left_ring_finger",
        "right_ring_finger",
        "left_pinky",
        "right_pinky",
        "left_toes",
        "right_toes",
    }
)
MATERIAL_RARE_NAMES = frozenset({"strap"})
REGISTERED_TRANSFORMS = (
    "MaskFactoryRandomResizedCrop",
    "MaskFactoryHorizontalFlip",
    "MaskFactoryPhotometricJitter",
    "MaskFactoryRotate",
)


def _load_transform_registry(
    importer: Callable[[str], ModuleType] = importlib.import_module,
) -> object | None:
    """Treat a missing MMSeg install as optional; expose broken partial installs."""
    try:
        return importer("mmseg.registry").TRANSFORMS
    except ModuleNotFoundError as exc:
        if exc.name == "mmseg":
            return None
        raise


def _require_results(results: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    if "img" not in results or "gt_seg_map" not in results:
        raise AugmentationError("MMSeg results require img and gt_seg_map before augmentation")
    image = np.asarray(results["img"])
    labels = np.asarray(results["gt_seg_map"])
    if image.ndim != 3 or image.shape[2] != 3 or labels.shape != image.shape[:2]:
        raise AugmentationError("MMSeg image/segmentation geometry is invalid")
    return image, labels


class _RandomSource:
    def __init__(self, *, rng: np.random.Generator | None = None) -> None:
        self._fixed_rng = rng

    def _rng(self) -> np.random.Generator:
        if self._fixed_rng is not None:
            return self._fixed_rng
        # MMEngine seeds NumPy independently per worker. Draw a child seed at call time so
        # transforms copied into workers do not replay an identical Generator state.
        return np.random.default_rng(int(np.random.randint(0, 2**32 - 1)))


class MaskFactoryRandomResizedCrop(_RandomSource):
    def __init__(
        self,
        *,
        map_name: str,
        output_size: int = 512,
        scale: tuple[float, float] = (0.5, 2.0),
        rare_force_probability: float = 0.4,
        rare_ids: tuple[int, ...] = (),
        rng: np.random.Generator | None = None,
    ) -> None:
        super().__init__(rng=rng)
        if map_name not in {"part", "material"}:
            raise AugmentationError(f"unsupported MMSeg map_name: {map_name}")
        self.map_name = map_name
        self.output_size = int(output_size)
        self.scale = tuple(float(value) for value in scale)
        self.rare_force_probability = float(rare_force_probability)
        self.rare_ids = frozenset(int(value) for value in rare_ids)
        self.meter = RareSamplingMeter()

    def __call__(self, results: dict[str, Any]) -> dict[str, Any]:
        image, labels = _require_results(results)
        image, maps, forced = random_resized_crop(
            image,
            {self.map_name: labels},
            rng=self._rng(),
            output_size=self.output_size,
            scale_range=self.scale,
            rare_ids={self.map_name: self.rare_ids},
            force_rare_probability=self.rare_force_probability,
            meter=self.meter,
        )
        results["img"] = image
        results["gt_seg_map"] = maps[self.map_name]
        results["img_shape"] = image.shape[:2]
        results["maskfactory_rare_forced"] = forced
        return results


class MaskFactoryHorizontalFlip(_RandomSource):
    def __init__(
        self,
        *,
        map_name: str,
        probability: float = 0.5,
        rng: np.random.Generator | None = None,
    ) -> None:
        super().__init__(rng=rng)
        if map_name not in {"part", "material"}:
            raise AugmentationError(f"unsupported MMSeg map_name: {map_name}")
        self.map_name = map_name
        self.probability = float(probability)

    def __call__(self, results: dict[str, Any]) -> dict[str, Any]:
        image, labels = _require_results(results)
        rng = self._rng()
        image, maps, applied = maybe_horizontal_flip(
            image,
            {self.map_name: labels},
            random=rng.random,
            probability=self.probability,
        )
        results["img"] = image
        results["gt_seg_map"] = maps[self.map_name]
        results["flip"] = applied
        results["flip_direction"] = "horizontal" if applied else None
        return results


class MaskFactoryPhotometricJitter(_RandomSource):
    def __init__(
        self,
        *,
        brightness: float = 0.25,
        contrast: float = 0.25,
        saturation: float = 0.25,
        hue: float = 0.05,
        channel_order: str = "bgr",
        rng: np.random.Generator | None = None,
    ) -> None:
        super().__init__(rng=rng)
        self.bounds = {
            "brightness": float(brightness),
            "contrast": float(contrast),
            "saturation": float(saturation),
            "hue": float(hue),
        }
        if channel_order not in {"bgr", "rgb"}:
            raise AugmentationError("MMSeg photometric channel_order must be bgr or rgb")
        self.channel_order = channel_order
        # Reuse the constitutional bound validation before the first sample.
        photometric_jitter(np.zeros((1, 1, 3), dtype=np.uint8), **self.bounds)

    def __call__(self, results: dict[str, Any]) -> dict[str, Any]:
        image, _labels = _require_results(results)
        rng = self._rng()
        sampled = {name: float(rng.uniform(-bound, bound)) for name, bound in self.bounds.items()}
        rgb = image[:, :, ::-1] if self.channel_order == "bgr" else image
        jittered = photometric_jitter(rgb, **sampled)
        results["img"] = jittered[:, :, ::-1].copy() if self.channel_order == "bgr" else jittered
        return results


class MaskFactoryRotate(_RandomSource):
    def __init__(
        self,
        *,
        map_name: str,
        degrees: float = 15.0,
        rng: np.random.Generator | None = None,
    ) -> None:
        super().__init__(rng=rng)
        if map_name not in {"part", "material"}:
            raise AugmentationError(f"unsupported MMSeg map_name: {map_name}")
        if not 0 <= float(degrees) <= 15:
            raise AugmentationError("MMSeg rotation bound must be within 0..15 degrees")
        self.map_name = map_name
        self.degrees = float(degrees)

    def __call__(self, results: dict[str, Any]) -> dict[str, Any]:
        image, labels = _require_results(results)
        angle = float(self._rng().uniform(-self.degrees, self.degrees))
        image, maps = rotate_sample(image, {self.map_name: labels}, degrees=angle)
        results["img"] = image
        results["gt_seg_map"] = maps[self.map_name]
        results["img_shape"] = image.shape[:2]
        results["maskfactory_rotation_degrees"] = angle
        return results


def _rare_ids(map_name: str) -> tuple[int, ...]:
    from ..ontology import get_ontology

    names = PART_RARE_NAMES if map_name == "part" else MATERIAL_RARE_NAMES
    return tuple(sorted(int(get_ontology().label(name).id) for name in names))


def mmseg_augmentation_config(config: Mapping[str, Any], *, map_name: str) -> dict[str, Any]:
    """Compile the governed YAML augmentation section into an exact MMSeg pipeline."""
    if map_name not in {"part", "material"}:
        raise AugmentationError(f"unsupported MMSeg map_name: {map_name}")
    validate_augmentation_config(config)
    data = config.get("data")
    configured = config.get("augmentations")
    if not isinstance(data, Mapping) or not isinstance(configured, list):
        raise AugmentationError("training config requires data and augmentations")
    if [item.get("type") for item in configured if isinstance(item, Mapping)] != [
        "random_resized_crop",
        "horizontal_flip",
        "photometric_jitter",
        "rotate",
    ]:
        raise AugmentationError("training augmentations must use the exact governed order")
    if len(configured) != 4 or not all(isinstance(item, Mapping) for item in configured):
        raise AugmentationError("training augmentations must contain exactly four mappings")
    crop, flip, jitter, rotate = configured
    crop_size = data.get("crop_size")
    if crop_size != [512, 512] or crop != {
        "type": "random_resized_crop",
        "output_size": 512,
        "scale": [0.5, 2.0],
        "rare_force_probability": 0.4,
    }:
        raise AugmentationError("release crop policy must remain 512 / 0.5..2.0 / 40% rare")
    if flip != {
        "type": "horizontal_flip",
        "probability": 0.5,
        "swap_partner_remap": True,
    }:
        raise AugmentationError("release flip policy must remain p=0.5 with swap remap")
    if jitter != {
        "type": "photometric_jitter",
        "brightness": 0.25,
        "contrast": 0.25,
        "saturation": 0.25,
        "hue": 0.05,
    }:
        raise AugmentationError("release photometric policy differs from doc 12 section 4")
    if rotate != {
        "type": "rotate",
        "degrees": 15,
        "label_interpolation": "nearest",
        "border_label": IGNORE_INDEX,
    }:
        raise AugmentationError("release rotation policy must remain +/-15, nearest, border 255")
    pipeline = [
        {"type": "LoadImageFromFile"},
        {"type": "mmseg.LoadAnnotations", "reduce_zero_label": False},
        {
            "type": "mmseg.MaskFactoryRandomResizedCrop",
            "map_name": map_name,
            "output_size": 512,
            "scale": (0.5, 2.0),
            "rare_force_probability": 0.4,
            "rare_ids": _rare_ids(map_name),
        },
        {
            "type": "mmseg.MaskFactoryHorizontalFlip",
            "map_name": map_name,
            "probability": 0.5,
        },
        {
            "type": "mmseg.MaskFactoryPhotometricJitter",
            "brightness": 0.25,
            "contrast": 0.25,
            "saturation": 0.25,
            "hue": 0.05,
            "channel_order": "bgr",
        },
        {"type": "mmseg.MaskFactoryRotate", "map_name": map_name, "degrees": 15.0},
        {
            "type": "mmseg.PackSegInputs",
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
    return {
        "custom_imports": {
            "imports": [
                "maskfactory.training.dataset",
                "maskfactory.training.mmseg_metric",
                "maskfactory.training.mmseg_transforms",
                "maskfactory.training.weighted_segmentor",
            ],
            "allow_failed_imports": False,
        },
        "train_pipeline": pipeline,
    }


TRANSFORMS = _load_transform_registry()
if TRANSFORMS is not None:
    for _transform in (
        MaskFactoryRandomResizedCrop,
        MaskFactoryHorizontalFlip,
        MaskFactoryPhotometricJitter,
        MaskFactoryRotate,
    ):
        TRANSFORMS.register_module(module=_transform)
