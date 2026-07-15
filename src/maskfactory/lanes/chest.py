"""P3 chest lane: visible truth, projected-only drafting, and review evidence."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from ..io.png_strict import write_binary_mask
from ..qa.panels import render_boundary_panel
from ..stages.s05_geometry import PromptPlan
from ..stages.s07_sam2 import RefinedPart, Sam2Provider, refine_part
from ..validation import validate_document
from .common import CropTransform, LaneCrop


class ChestLaneError(ValueError):
    """Chest lane inputs violate visible/projected separation or crop geometry."""


@dataclass(frozen=True)
class BreastSeeds:
    left: np.ndarray
    right: np.ndarray
    visibility_states: dict[str, str]
    lane_skipped: bool


@dataclass(frozen=True)
class VisibleBreastTruth:
    left_part: np.ndarray
    right_part: np.ndarray
    left_breast_skin: np.ndarray
    right_breast_skin: np.ndarray


def create_chest_crop(
    source_path: Path,
    chest_mask: np.ndarray,
    *,
    clavicle_y: float,
    under_bust_y: float,
    torso_left_x: float,
    torso_right_x: float,
    output_dir: Path,
) -> LaneCrop:
    """Create the explicit chest override: clavicle-to-under-bust bbox expanded 1.4x."""
    source_path = Path(source_path)
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    mask = np.asarray(chest_mask).astype(bool)
    if mask.shape != (source.height, source.width):
        raise ChestLaneError("chest mask dimensions differ from source")
    bbox = (torso_left_x, clavicle_y, torso_right_x, under_bust_y)
    if not (0 <= bbox[0] < bbox[2] <= source.width and 0 <= bbox[1] < bbox[3] <= source.height):
        raise ChestLaneError("chest landmark bbox outside source")
    base_side = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    side = math.ceil(base_side * 1.4)
    if side > min(source.width, source.height):
        raise ChestLaneError("1.4x chest square cannot fit source")
    center_x, center_y = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    x0 = min(max(0, math.floor(center_x - side / 2)), source.width - side)
    y0 = min(max(0, math.floor(center_y - side / 2)), source.height - side)
    crop_box = (x0, y0, x0 + side, y0 + side)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "chest_crop.png"
    mask_path = output_dir / "chest_crop_mask.png"
    source.crop(crop_box).resize((1024, 1024), Image.Resampling.LANCZOS).save(
        image_path, format="PNG"
    )  # png-strict: allow (RGB chest crop, never mask)
    crop_mask = np.asarray(
        Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
        .crop(crop_box)
        .resize((1024, 1024), Image.Resampling.NEAREST)
    )
    write_binary_mask(mask_path, crop_mask, source_size=(1024, 1024))
    transform = CropTransform(
        "chest_upper_torso",
        x0,
        y0,
        1024 / side,
        1024,
        hashlib.sha256(source_path.read_bytes()).hexdigest(),
    )
    document = asdict(transform)
    issues = validate_document(document, "crop_transform")
    if issues:
        raise ChestLaneError("invalid transform: " + "; ".join(str(issue) for issue in issues))
    transform_path = output_dir / "chest_crop_to_full_transform.json"
    transform_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return LaneCrop(image_path, mask_path, transform_path, transform)


def build_breast_seeds(
    torso_mask: np.ndarray,
    *,
    left_shoulder_xy: tuple[float, float],
    right_shoulder_xy: tuple[float, float],
    under_bust_y: float,
    view: str,
) -> BreastSeeds:
    """Landmark/torso ellipses: two front/3-4, one profile, none back."""
    torso = np.asarray(torso_mask).astype(bool)
    if torso.ndim != 2:
        raise ChestLaneError("torso mask must be 2-D")
    empty = np.zeros_like(torso)
    if view in {"back", "left_back_3_4", "right_back_3_4"}:
        return BreastSeeds(
            empty.copy(),
            empty.copy(),
            {"left_breast": "not_visible", "right_breast": "not_visible"},
            True,
        )
    allowed = {"front", "left_3_4", "right_3_4", "left_profile", "right_profile"}
    if view not in allowed:
        raise ChestLaneError(f"unsupported chest view: {view}")
    shoulder_mid_y = (left_shoulder_xy[1] + right_shoulder_xy[1]) / 2
    torso_width = abs(left_shoulder_xy[0] - right_shoulder_xy[0])
    if torso_width <= 0 or under_bust_y <= shoulder_mid_y:
        raise ChestLaneError("invalid shoulder/under-bust geometry")
    mid_x = (left_shoulder_xy[0] + right_shoulder_xy[0]) / 2
    left_sign = -1 if left_shoulder_xy[0] < right_shoulder_xy[0] else 1
    center_y = shoulder_mid_y + 0.62 * (under_bust_y - shoulder_mid_y)
    rx, ry = 0.20 * torso_width, 0.30 * (under_bust_y - shoulder_mid_y)
    left = _ellipse(torso.shape, mid_x + left_sign * 0.20 * torso_width, center_y, rx, ry) & torso
    right = _ellipse(torso.shape, mid_x - left_sign * 0.20 * torso_width, center_y, rx, ry) & torso
    states = {"left_breast": "visible", "right_breast": "visible"}
    if view == "left_profile":
        right[:] = False
        states["right_breast"] = "not_visible"
    elif view == "right_profile":
        left[:] = False
        states["left_breast"] = "not_visible"
    return BreastSeeds(left, right, states, False)


def visible_breast_truth(
    seeds: BreastSeeds,
    *,
    skin_contour: np.ndarray,
    fabric_contour: np.ndarray,
) -> VisibleBreastTruth:
    """PART follows whichever visible surface exists; derived skin is PART intersect skin."""
    skin = _same(skin_contour, seeds.left.shape, "skin_contour")
    fabric = _same(fabric_contour, seeds.left.shape, "fabric_contour")
    visible_surface = skin | fabric
    left_part = seeds.left & visible_surface
    right_part = seeds.right & visible_surface
    return VisibleBreastTruth(
        left_part,
        right_part,
        left_part & skin,
        right_part & skin,
    )


def projected_breast_region(
    seed: np.ndarray,
    *,
    source_rgb: np.ndarray,
    clothing: np.ndarray,
    torso: np.ndarray,
) -> np.ndarray:
    """Shape-from-shading-lite projected estimate, clipped to torso and never visible truth."""
    base = np.asarray(seed).astype(bool)
    garment = _same(clothing, base.shape, "clothing")
    torso_mask = _same(torso, base.shape, "torso")
    image = np.asarray(source_rgb, dtype=np.float32)
    if image.shape != (*base.shape, 3):
        raise ChestLaneError("source RGB dimensions differ")
    luminance = 0.2126 * image[:, :, 0] + 0.7152 * image[:, :, 1] + 0.0722 * image[:, :, 2]
    curvature = np.abs(ndimage.laplace(luminance))
    candidates = garment & ndimage.binary_dilation(base, iterations=8)
    if candidates.any():
        threshold = float(np.percentile(curvature[candidates], 60))
        shading = candidates & (curvature >= threshold)
    else:
        shading = np.zeros_like(base)
    return (base | shading) & torso_mask


def write_projected_breast(
    projected_root: Path,
    *,
    side: str,
    region: np.ndarray,
    source_size: tuple[int, int],
) -> Path:
    """The only writer for these estimates targets projected/, never masks/ or PART maps."""
    root = Path(projected_root)
    if root.name != "projected" or side not in {"left", "right"}:
        raise ChestLaneError("projected breasts may only be written under projected/")
    return write_binary_mask(
        root / f"{side}_breast_projected_region.png", region, source_size=source_size
    )


def clothing_boundary_chest(
    chest_and_breasts: np.ndarray,
    skin: np.ndarray,
    clothing: np.ndarray,
) -> np.ndarray:
    """Four-pixel material transition band within chest/breast PART regions."""
    region = np.asarray(chest_and_breasts).astype(bool)
    skin_mask = _same(skin, region.shape, "skin")
    clothing_mask = _same(clothing, region.shape, "clothing")
    transition = ndimage.binary_dilation(skin_mask, iterations=4) & ndimage.binary_dilation(
        clothing_mask, iterations=4
    )
    return transition & region


def refine_chest_boundaries(
    provider: Sam2Provider,
    embedding: object,
    regions: dict[str, np.ndarray],
    plans: dict[str, PromptPlan],
    *,
    model: str,
) -> dict[str, RefinedPart]:
    """SAM2-refine strap and inframammary/material-transition evidence on the crop."""
    required = {"strap", "inframammary_boundary"}
    if set(regions) != set(plans) or not required.issubset(regions):
        raise ChestLaneError("strap and inframammary boundary both require prompt plans")
    return {
        name: refine_part(provider, embedding, plans[name], region, model=model)
        for name, region in regions.items()
    }


def render_mandatory_chest_panels(
    source: Image.Image,
    masks: dict[str, np.ndarray],
    protected: np.ndarray,
    output_dir: Path,
) -> tuple[Path, ...]:
    output_dir = Path(output_dir)
    return tuple(
        render_boundary_panel(source, mask, protected, output_dir / f"{name}.png")
        for name, mask in sorted(masks.items())
        if np.asarray(mask).any()
    )


def _ellipse(shape, center_x, center_y, rx, ry):
    yy, xx = np.indices(shape)
    return ((xx - center_x) / rx) ** 2 + ((yy - center_y) / ry) ** 2 <= 1


def _same(value, shape, name):
    mask = np.asarray(value).astype(bool)
    if mask.shape != shape:
        raise ChestLaneError(f"{name} dimensions differ")
    return mask
