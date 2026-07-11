"""P2 overlay renderer and fixed five-tile boundary review panels."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np
from PIL import Image, ImageColor
from scipy import ndimage

from ..ontology import Ontology, get_ontology


class PanelError(ValueError):
    """Visual QA inputs violate the panel contract."""


def render_part_overlays(
    source: Image.Image,
    part_map: np.ndarray,
    output_dir: Path,
    *,
    label_colors: Mapping[str, str],
    alpha: int = 110,
    contour_width: int = 1,
    ontology: Ontology | None = None,
) -> tuple[Path, ...]:
    """Render every present PART label plus a single all-parts context overlay."""
    authority = ontology or get_ontology()
    indexed = np.asarray(part_map)
    if indexed.ndim != 2 or source.size != (indexed.shape[1], indexed.shape[0]):
        raise PanelError("source and PART map dimensions differ")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    all_image = source.convert("RGBA")
    for label in authority.labels_for_map("part", enabled_only=True):
        if label.id == 0:
            continue
        mask = indexed == int(label.id)
        if not mask.any():
            continue
        if label.name not in label_colors:
            raise PanelError(f"missing visualization color for {label.name}")
        color = ImageColor.getrgb(label_colors[label.name])
        rendered = _overlay(source, mask, color, alpha, contour_width)
        path = output_dir / f"{label.name}.png"
        rendered.save(path, format="PNG")  # png-strict: allow (RGB QA overlay, never mask)
        outputs.append(path)
        all_image = Image.alpha_composite(all_image, _rgba_layer(mask, color, alpha, contour_width))
    all_path = output_dir / "all_parts.png"
    all_image.convert("RGB").save(  # png-strict: allow (RGB QA overlay, never mask)
        all_path, format="PNG"
    )
    outputs.append(all_path)
    return tuple(outputs)


def render_boundary_panel(
    source: Image.Image,
    mask: np.ndarray,
    protected_neighbor: np.ndarray,
    output_path: Path,
    *,
    tile_size: int = 512,
    zoom_multiplier: float = 2.0,
) -> Path:
    """Render [source|mask|overlay|contour|protected-overlap] at exact tile size."""
    target = np.asarray(mask).astype(bool)
    protected = np.asarray(protected_neighbor).astype(bool)
    if target.shape != protected.shape or source.size != (target.shape[1], target.shape[0]):
        raise PanelError("panel source/mask dimensions differ")
    if not target.any() or tile_size != 512 or zoom_multiplier != 2.0:
        raise PanelError("panel requires nonempty mask, 512 tiles, and 2x bbox zoom")
    crop = _zoom_box(target, zoom_multiplier)
    source_crop = (
        source.convert("RGB").crop(crop).resize((tile_size, tile_size), Image.Resampling.LANCZOS)
    )
    target_crop = target[crop[1] : crop[3], crop[0] : crop[2]]
    protected_crop = protected[crop[1] : crop[3], crop[0] : crop[2]]
    mask_tile = (
        Image.fromarray(target_crop.astype(np.uint8) * 255, mode="L")
        .resize((tile_size, tile_size), Image.Resampling.NEAREST)
        .convert("RGB")
    )
    overlay = _overlay(source.crop(crop), target_crop, (255, 64, 64), 110, 1).resize(
        (tile_size, tile_size), Image.Resampling.LANCZOS
    )
    contour_mask = target_crop ^ ndimage.binary_erosion(target_crop)
    contour = _overlay(source.crop(crop), contour_mask, (0, 255, 255), 255, 1).resize(
        (tile_size, tile_size), Image.Resampling.LANCZOS
    )
    overlap = target_crop & protected_crop
    heat = _overlay(source.crop(crop), overlap, (255, 0, 255), 220, 1).resize(
        (tile_size, tile_size), Image.Resampling.LANCZOS
    )
    panel = Image.new("RGB", (tile_size * 5, tile_size))
    for index, tile in enumerate((source_crop, mask_tile, overlay, contour, heat)):
        panel.paste(tile, (index * tile_size, 0))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    panel.save(output_path, format="PNG")  # png-strict: allow (RGB QA panel, never mask)
    return output_path


def _overlay(source, mask, color, alpha, contour_width):
    base = source.convert("RGBA")
    return Image.alpha_composite(base, _rgba_layer(mask, color, alpha, contour_width)).convert(
        "RGB"
    )


def _rgba_layer(mask, color, alpha, contour_width):
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[mask, :3] = color
    rgba[mask, 3] = alpha
    contour = mask ^ ndimage.binary_erosion(mask, iterations=contour_width)
    rgba[contour, :3] = (255, 255, 255)
    rgba[contour, 3] = 255
    return Image.fromarray(rgba, mode="RGBA")


def _zoom_box(mask, multiplier):
    ys, xs = np.nonzero(mask)
    left, right, top, bottom = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    size = max(right - left, bottom - top) * multiplier
    height, width = mask.shape
    return (
        max(0, int(np.floor(center_x - size / 2))),
        max(0, int(np.floor(center_y - size / 2))),
        min(width, int(np.ceil(center_x + size / 2))),
        min(height, int(np.ceil(center_y + size / 2))),
    )
