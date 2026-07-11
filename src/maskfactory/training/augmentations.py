"""Ontology-aware segmentation augmentations (doc 12 §4)."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageEnhance

from ..ontology import Ontology, OntologyError, get_ontology

IGNORE_INDEX = 255


class AugmentationError(ValueError):
    """An augmentation would make an invalid or semantically corrupt label map."""


BANNED_AUGMENTATIONS = frozenset(
    {"vflip", "verticalflip", "elastic", "perspective", "mixup", "cutmix"}
)


@dataclass
class RareSamplingMeter:
    attempts: int = 0
    forced_attempts: int = 0
    rare_contained: int = 0

    @property
    def forced_rate(self) -> float:
        return self.forced_attempts / self.attempts if self.attempts else 0.0

    def as_dict(self) -> dict[str, int | float]:
        return {
            "attempts": self.attempts,
            "forced_attempts": self.forced_attempts,
            "rare_contained": self.rare_contained,
            "forced_rate": self.forced_rate,
        }


def write_rare_sampling_metrics(path: Path, meter: RareSamplingMeter) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(meter.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def validate_augmentation_config(config: Any) -> None:
    """Reject prohibited spatial/mixing transforms anywhere in a nested config."""
    found = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"type", "name", "transform"} and isinstance(child, str):
                    normalized = child.lower().replace("_", "").replace("-", "")
                    if normalized in BANNED_AUGMENTATIONS:
                        found.add(child)
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            normalized = value.lower().replace("_", "").replace("-", "")
            if normalized in BANNED_AUGMENTATIONS:
                found.add(value)

    visit(config)
    if found:
        raise AugmentationError(f"banned augmentation configured: {sorted(found)}")


def burn_ambiguous_to_ignore(
    label_map: NDArray[np.integer], ambiguity_mask: NDArray[np.generic]
) -> NDArray[np.uint8]:
    labels = np.asarray(label_map)
    ambiguity = np.asarray(ambiguity_mask).astype(bool)
    if labels.ndim != 2 or ambiguity.shape != labels.shape:
        raise AugmentationError("ambiguity mask must match the 2-D label map")
    if labels.size and (labels.min() < 0 or labels.max() > IGNORE_INDEX):
        raise AugmentationError("label map IDs exceed uint8/ignore_index range")
    result = labels.astype(np.uint8, copy=True)
    result[ambiguity] = IGNORE_INDEX
    return result


def random_resized_crop(
    image: NDArray[np.generic],
    label_maps: dict[str, NDArray[np.integer]],
    *,
    rng: np.random.Generator,
    output_size: int = 512,
    scale_range: tuple[float, float] = (0.5, 2.0),
    rare_ids: dict[str, frozenset[int]] | None = None,
    force_rare_probability: float = 0.4,
    meter: RareSamplingMeter | None = None,
) -> tuple[NDArray[np.uint8], dict[str, NDArray[np.uint8]], bool]:
    """Crop/resize paired data, forcing the configured share to contain a rare pixel."""
    source = np.asarray(image)
    if source.ndim != 3 or source.shape[2] != 3 or output_size < 1:
        raise AugmentationError("random crop requires an RGB image and positive output size")
    if not (0 < scale_range[0] <= scale_range[1]) or not 0 <= force_rare_probability <= 1:
        raise AugmentationError("random crop scale/probability invalid")
    maps = {name: np.asarray(value) for name, value in label_maps.items()}
    if any(value.shape != source.shape[:2] for value in maps.values()):
        raise AugmentationError("crop label map dimensions differ from image")
    meter = meter or RareSamplingMeter()
    meter.attempts += 1
    forced = bool(rng.random() < force_rare_probability)
    rare_pixels = _rare_pixels(maps, rare_ids or {})
    forced = forced and bool(len(rare_pixels))
    meter.forced_attempts += int(forced)
    scale = float(rng.uniform(*scale_range))
    crop_h = min(source.shape[0], max(1, round(output_size / scale)))
    crop_w = min(source.shape[1], max(1, round(output_size / scale)))
    if forced:
        rare_y, rare_x = rare_pixels[int(rng.integers(0, len(rare_pixels)))]
        top_min, top_max = max(0, rare_y - crop_h + 1), min(rare_y, source.shape[0] - crop_h)
        left_min, left_max = max(0, rare_x - crop_w + 1), min(rare_x, source.shape[1] - crop_w)
        top = int(rng.integers(top_min, top_max + 1))
        left = int(rng.integers(left_min, left_max + 1))
    else:
        top = int(rng.integers(0, source.shape[0] - crop_h + 1))
        left = int(rng.integers(0, source.shape[1] - crop_w + 1))
    cropped_image = source[top : top + crop_h, left : left + crop_w]
    resized_image = np.asarray(
        Image.fromarray(cropped_image.astype(np.uint8), mode="RGB").resize(
            (output_size, output_size), Image.Resampling.BILINEAR
        )
    )
    resized_maps = {
        name: np.asarray(
            Image.fromarray(
                value[top : top + crop_h, left : left + crop_w].astype(np.uint8), mode="L"
            ).resize(
                (output_size, output_size),
                Image.Resampling.NEAREST,
            )
        )
        for name, value in maps.items()
    }
    if forced and not _rare_pixels(resized_maps, rare_ids or {}).size:
        target_y = min(output_size - 1, int((rare_y - top + 0.5) * output_size / crop_h))
        target_x = min(output_size - 1, int((rare_x - left + 0.5) * output_size / crop_w))
        for name, ids in (rare_ids or {}).items():
            if name in maps and int(maps[name][rare_y, rare_x]) in ids:
                resized_maps[name] = resized_maps[name].copy()
                resized_maps[name][target_y, target_x] = maps[name][rare_y, rare_x]
    contained = bool(_rare_pixels(resized_maps, rare_ids or {}).size)
    meter.rare_contained += int(contained)
    if forced and not contained:
        raise AugmentationError("forced rare crop lost its rare-class pixel")
    return resized_image, resized_maps, forced


def photometric_jitter(
    image: NDArray[np.generic],
    *,
    brightness: float,
    contrast: float,
    saturation: float,
    hue: float,
) -> NDArray[np.uint8]:
    """Apply bounded b/c/s +/-0.25 and hue +/-0.05 to RGB pixels only."""
    if any(abs(value) > 0.25 for value in (brightness, contrast, saturation)) or abs(hue) > 0.05:
        raise AugmentationError("photometric jitter exceeds the configured bounds")
    opened = Image.fromarray(np.asarray(image).astype(np.uint8), mode="RGB")
    opened = ImageEnhance.Brightness(opened).enhance(1 + brightness)
    opened = ImageEnhance.Contrast(opened).enhance(1 + contrast)
    opened = ImageEnhance.Color(opened).enhance(1 + saturation)
    hsv = np.asarray(opened.convert("HSV")).copy()
    hsv[:, :, 0] = (hsv[:, :, 0].astype(np.int16) + round(hue * 255)) % 256
    return np.asarray(Image.fromarray(hsv, mode="HSV").convert("RGB"))


def rotate_sample(
    image: NDArray[np.generic],
    label_maps: dict[str, NDArray[np.integer]],
    *,
    degrees: float,
) -> tuple[NDArray[np.uint8], dict[str, NDArray[np.uint8]]]:
    """Rotate image bilinearly and labels nearest-neighbor with ignore-index border."""
    if abs(degrees) > 15:
        raise AugmentationError("rotation exceeds +/-15 degrees")
    source = np.asarray(image)
    if any(np.asarray(value).shape != source.shape[:2] for value in label_maps.values()):
        raise AugmentationError("rotation label map dimensions differ from image")
    rotated_image = np.asarray(
        Image.fromarray(source.astype(np.uint8), mode="RGB").rotate(
            degrees, resample=Image.Resampling.BILINEAR, fillcolor=(0, 0, 0)
        )
    )
    rotated_maps = {
        name: np.asarray(
            Image.fromarray(np.asarray(value).astype(np.uint8), mode="L").rotate(
                degrees, resample=Image.Resampling.NEAREST, fillcolor=IGNORE_INDEX
            )
        )
        for name, value in label_maps.items()
    }
    return rotated_image, rotated_maps


def _rare_pixels(
    maps: dict[str, NDArray[np.integer]], rare_ids: dict[str, frozenset[int]]
) -> NDArray[np.int64]:
    combined = None
    for name, ids in rare_ids.items():
        if name not in maps:
            continue
        selected = np.isin(maps[name], tuple(ids))
        combined = selected if combined is None else combined | selected
    return np.argwhere(combined) if combined is not None else np.empty((0, 2), dtype=np.int64)


def swap_id_lut(
    map_name: str,
    *,
    ontology: Ontology | None = None,
) -> NDArray[np.uint8]:
    """Build a reciprocal uint8 ID lookup, preserving center/NA IDs and ignore 255."""
    authority = ontology or get_ontology()
    labels = authority.labels_for_map(map_name)
    lut = np.arange(256, dtype=np.uint8)
    valid_ids: set[int] = set()
    for label in labels:
        if label.id is None or not 0 <= label.id < IGNORE_INDEX:
            raise AugmentationError(f"{map_name} label {label.name!r} lacks a trainable uint8 ID")
        valid_ids.add(label.id)
        if label.side not in {"left", "right"}:
            if label.swap_partner is not None:
                raise AugmentationError(
                    f"non-sided label {label.name!r} unexpectedly has swap_partner"
                )
            continue
        if label.swap_partner is None:
            raise AugmentationError(f"sided label {label.name!r} lacks swap_partner")
        try:
            partner = authority.label(label.swap_partner)
        except OntologyError as exc:
            raise AugmentationError(str(exc)) from exc
        expected_side = "right" if label.side == "left" else "left"
        if (
            partner.map != map_name
            or partner.id is None
            or partner.side != expected_side
            or partner.swap_partner != label.name
        ):
            raise AugmentationError(
                f"swap_partner pair is not reciprocal in {map_name}: "
                f"{label.name!r} -> {partner.name!r}"
            )
        lut[label.id] = partner.id
    if any(int(lut[int(lut[label_id])]) != label_id for label_id in valid_ids):
        raise AugmentationError(f"{map_name} swap lookup is not an involution")
    lut[IGNORE_INDEX] = IGNORE_INDEX
    return lut


def horizontal_flip_label_map(
    label_map: NDArray[np.integer],
    map_name: str,
    *,
    ontology: Ontology | None = None,
) -> NDArray[np.uint8]:
    """Flip width and remap every sided class through ontology ``swap_partner``."""
    array = np.asarray(label_map)
    if array.ndim != 2:
        raise AugmentationError("label map must be a 2D indexed array")
    if not np.issubdtype(array.dtype, np.integer):
        raise AugmentationError("label map dtype must be integer")
    if array.size and (int(array.min()) < 0 or int(array.max()) > IGNORE_INDEX):
        raise AugmentationError("label map values must be uint8 IDs or ignore_index 255")
    authority = ontology or get_ontology()
    lut = swap_id_lut(map_name, ontology=authority)
    valid_ids = {
        label.id for label in authority.labels_for_map(map_name) if label.id is not None
    } | {IGNORE_INDEX}
    unknown = set(np.unique(array).tolist()) - valid_ids
    if unknown:
        raise AugmentationError(
            f"unknown {map_name} label IDs in augmentation input: {sorted(unknown)}"
        )
    return lut[np.flip(array, axis=1)]


def maybe_horizontal_flip(
    image: NDArray[np.generic],
    label_maps: dict[str, NDArray[np.integer]],
    *,
    random: Callable[[], float],
    probability: float = 0.5,
    ontology: Ontology | None = None,
) -> tuple[NDArray[np.generic], dict[str, NDArray[np.uint8]], bool]:
    """Apply the paired image/map transform with the mandated default probability 0.5."""
    if not 0.0 <= probability <= 1.0:
        raise AugmentationError("horizontal flip probability must be in [0, 1]")
    if image.ndim not in {2, 3}:
        raise AugmentationError("image must be HxW or HxWxC")
    for map_name, label_map in label_maps.items():
        if label_map.shape != image.shape[:2]:
            raise AugmentationError(f"{map_name} map dimensions do not match the image")
    if random() >= probability:
        return (
            image.copy(),
            {name: np.asarray(value, dtype=np.uint8).copy() for name, value in label_maps.items()},
            False,
        )
    authority = ontology or get_ontology()
    return (
        np.flip(image, axis=1).copy(),
        {
            name: horizontal_flip_label_map(value, name, ontology=authority)
            for name, value in label_maps.items()
        },
        True,
    )
