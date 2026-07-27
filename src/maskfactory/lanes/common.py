"""Specialist-lane square crop, transform, and exact nearest reprojection contract."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from ..io.png_strict import read_mask, write_binary_mask
from ..qa.metrics import iou
from ..validation import validate_document


class LaneCropError(ValueError):
    """A requested specialist crop cannot satisfy doc-03/doc-08 invariants."""


@dataclass(frozen=True)
class CropTransform:
    part: str
    x0: int
    y0: int
    scale: float
    crop_size: int
    source_sha256: str

    @property
    def full_side(self) -> int:
        return round(self.crop_size / self.scale)


@dataclass(frozen=True)
class LaneCrop:
    image_path: Path
    mask_path: Path
    transform_path: Path
    transform: CropTransform


def create_lane_crop(
    source_path: Path,
    full_mask: np.ndarray,
    *,
    part: str,
    part_bbox_xyxy: tuple[int, int, int, int],
    output_dir: Path,
    bbox_scale: float = 1.6,
    crop_size: int = 1024,
) -> LaneCrop:
    """Crop square 1.6x bbox and resample image Lanczos / mask nearest to 1024."""
    source_path = Path(source_path)
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    mask = np.asarray(full_mask)
    if mask.shape != (source.height, source.width) or mask.ndim != 2:
        raise LaneCropError("full mask dimensions differ from source")
    if bbox_scale != 1.6 or crop_size != 1024:
        raise LaneCropError("lane common contract requires bbox_scale=1.6 and crop_size=1024")
    left, top, right, bottom = part_bbox_xyxy
    if not (0 <= left < right <= source.width and 0 <= top < bottom <= source.height):
        raise LaneCropError("part bbox is outside source")
    bbox_side = max(right - left, bottom - top)
    side = int(math.ceil(bbox_side * bbox_scale))
    if side > min(source.width, source.height):
        raise LaneCropError("1.6x square crop cannot fit inside source without padding")
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    x0 = min(max(0, math.floor(center_x - side / 2)), source.width - side)
    y0 = min(max(0, math.floor(center_y - side / 2)), source.height - side)
    box = (x0, y0, x0 + side, y0 + side)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / f"{part}_crop.png"
    mask_path = output_dir / f"{part}_crop_mask.png"
    source.crop(box).resize((crop_size, crop_size), Image.Resampling.LANCZOS).save(
        image_path, format="PNG"
    )  # png-strict: allow (RGB lane source crop, never mask)
    mask_image = Image.fromarray((mask.astype(bool) * 255).astype(np.uint8), mode="L")
    crop_mask = np.asarray(
        mask_image.crop(box).resize((crop_size, crop_size), Image.Resampling.NEAREST)
    )
    write_binary_mask(mask_path, crop_mask, source_size=(crop_size, crop_size))
    transform = CropTransform(
        part=part,
        x0=x0,
        y0=y0,
        scale=crop_size / side,
        crop_size=crop_size,
        source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
    )
    transform_path = output_dir / f"{part}_crop_to_full_transform.json"
    document = asdict(transform)
    issues = validate_document(document, "crop_transform")
    if issues:
        raise LaneCropError("invalid crop transform: " + "; ".join(str(issue) for issue in issues))
    transform_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return LaneCrop(image_path, mask_path, transform_path, transform)


def read_crop_transform(path: Path) -> CropTransform:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    issues = validate_document(document, "crop_transform")
    if issues:
        raise LaneCropError("invalid crop transform: " + "; ".join(str(issue) for issue in issues))
    return CropTransform(**document)


def reproject_crop_mask(
    crop_mask: np.ndarray | Path,
    transform: CropTransform,
    *,
    full_size: tuple[int, int],
) -> np.ndarray:
    """Nearest-neighbor paste of a 1024 crop mask into its exact full-frame window."""
    crop = read_mask(crop_mask) if isinstance(crop_mask, Path) else np.asarray(crop_mask)
    if crop.shape != (transform.crop_size, transform.crop_size):
        raise LaneCropError("crop mask dimensions differ from transform crop_size")
    if not set(np.unique(crop).tolist()).issubset({0, 255, False, True}):
        raise LaneCropError("crop mask must be strict binary")
    side = transform.full_side
    width, height = full_size
    if transform.x0 + side > width or transform.y0 + side > height:
        raise LaneCropError("transform placement exceeds full frame")
    resized = (
        np.asarray(
            Image.fromarray((crop.astype(bool) * 255).astype(np.uint8), mode="L").resize(
                (side, side), Image.Resampling.NEAREST
            )
        )
        == 255
    )
    full = np.zeros((height, width), dtype=bool)
    full[transform.y0 : transform.y0 + side, transform.x0 : transform.x0 + side] = resized
    return full


def crop_roundtrip_iou(full_mask: np.ndarray, lane_crop: LaneCrop) -> float:
    """QC-018 evidence for the exact crop window, requiring caller threshold >=0.995."""
    original = np.asarray(full_mask).astype(bool)
    reprojected = reproject_crop_mask(
        lane_crop.mask_path,
        lane_crop.transform,
        full_size=(original.shape[1], original.shape[0]),
    )
    side = lane_crop.transform.full_side
    window = np.zeros_like(original)
    window[
        lane_crop.transform.y0 : lane_crop.transform.y0 + side,
        lane_crop.transform.x0 : lane_crop.transform.x0 + side,
    ] = True
    return iou(original & window, reprojected & window)
