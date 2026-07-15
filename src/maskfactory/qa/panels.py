"""P2 overlay renderer and fixed five-tile boundary review panels."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
from PIL import Image, ImageColor
from scipy import ndimage

from ..ontology import Ontology, get_ontology


class PanelError(ValueError):
    """Visual QA inputs violate the panel contract."""


@dataclass(frozen=True)
class WorkhorseEvidence:
    """Lossless-enough, separately addressable visual evidence for tool-using VLM QA."""

    images: tuple[Path, ...]
    crop_xyxy: tuple[int, int, int, int]
    source_size: tuple[int, int]
    metrics: tuple[tuple[str, float], ...] = ()
    specialist_metadata: tuple[tuple[str, str], ...] = ()


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


def render_workhorse_evidence(
    source: Image.Image,
    mask: np.ndarray,
    protected_neighbor: np.ndarray,
    output_dir: Path,
    *,
    tile_size: int = 1024,
    zoom_multiplier: float = 2.0,
    specialist_candidate: np.ndarray | None = None,
    specialist_metadata: Mapping[str, str] | None = None,
    focus_bbox_xyxy: tuple[int, int, int, int] | None = None,
) -> WorkhorseEvidence:
    """Render six independent high-resolution inputs instead of one compressed strip.

    Image order is a stable contract: full context, source crop, binary mask, overlay,
    contour, protected-neighbor overlap. The crop box lets a model's normalized points
    be mapped back to full-resolution SAM2 coordinates without guessing.
    """
    target = np.asarray(mask).astype(bool)
    protected = np.asarray(protected_neighbor).astype(bool)
    if target.shape != protected.shape or source.size != (target.shape[1], target.shape[0]):
        raise PanelError("workhorse evidence source/mask dimensions differ")
    if not target.any() or tile_size < 512 or tile_size > 1536:
        raise PanelError("workhorse evidence requires a nonempty mask and 512..1536 tiles")
    crop = (
        _validate_focus_box(focus_bbox_xyxy, target.shape)
        if focus_bbox_xyxy is not None
        else _zoom_box(target, zoom_multiplier)
    )
    source_crop = source.convert("RGB").crop(crop)
    target_crop = target[crop[1] : crop[3], crop[0] : crop[2]]
    protected_crop = protected[crop[1] : crop[3], crop[0] : crop[2]]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    context = source.convert("RGB").copy()
    context_array = np.asarray(context).copy()
    x1, y1, x2, y2 = crop
    width = max(2, round(max(source.size) / 512))
    context_array[max(0, y1 - width) : min(source.height, y1 + width), x1:x2] = (0, 255, 255)
    context_array[max(0, y2 - width) : min(source.height, y2 + width), x1:x2] = (0, 255, 255)
    context_array[y1:y2, max(0, x1 - width) : min(source.width, x1 + width)] = (0, 255, 255)
    context_array[y1:y2, max(0, x2 - width) : min(source.width, x2 + width)] = (0, 255, 255)
    specialist = None
    if specialist_candidate is not None:
        specialist = np.asarray(specialist_candidate).astype(bool)
        if specialist.shape != target.shape:
            raise PanelError("specialist candidate geometry differs from workhorse evidence")
        boundary = specialist ^ ndimage.binary_erosion(specialist)
        context_array[boundary] = (0, 255, 80)
    context = Image.fromarray(context_array, mode="RGB")
    context.thumbnail((1536, 1536), Image.Resampling.LANCZOS)

    tiles = (
        context,
        source_crop.resize((tile_size, tile_size), Image.Resampling.LANCZOS),
        Image.fromarray(target_crop.astype(np.uint8) * 255, mode="L")
        .resize((tile_size, tile_size), Image.Resampling.NEAREST)
        .convert("RGB"),
        _overlay(source_crop, target_crop, (255, 64, 64), 110, 1).resize(
            (tile_size, tile_size), Image.Resampling.LANCZOS
        ),
        _overlay(
            source_crop,
            target_crop ^ ndimage.binary_erosion(target_crop),
            (0, 255, 255),
            255,
            1,
        ).resize((tile_size, tile_size), Image.Resampling.LANCZOS),
        _overlay(source_crop, target_crop & protected_crop, (255, 0, 255), 220, 1).resize(
            (tile_size, tile_size), Image.Resampling.LANCZOS
        ),
    )
    names = ("full_context", "source_crop", "mask", "overlay", "contour", "neighbor_overlap")
    paths = []
    for name, tile in zip(names, tiles, strict=True):
        path = output_dir / f"{name}.png"
        tile.save(path, format="PNG")  # png-strict: allow (RGB VLM evidence, never mask)
        paths.append(path)
    labels, component_count = ndimage.label(target)
    component_areas = sorted(
        (int(np.count_nonzero(labels == index)) for index in range(1, component_count + 1)),
        reverse=True,
    )
    metrics = (
        ("mask_area_px", float(target.sum())),
        ("component_count", float(component_count)),
        (
            "largest_component_fraction",
            float(component_areas[0] / max(1, int(target.sum()))) if component_areas else 0.0,
        ),
        ("protected_overlap_px", float(np.count_nonzero(target & protected))),
        (
            "specialist_candidate_area_px",
            float(specialist.sum()) if specialist is not None else 0.0,
        ),
        (
            "specialist_iou",
            (
                float(
                    np.count_nonzero(target & specialist)
                    / max(1, np.count_nonzero(target | specialist))
                )
                if specialist is not None
                else 1.0
            ),
        ),
        (
            "specialist_disagreement_fraction",
            (
                float(
                    np.count_nonzero(target ^ specialist)
                    / max(1, np.count_nonzero(target | specialist))
                )
                if specialist is not None
                else 0.0
            ),
        ),
    )
    return WorkhorseEvidence(
        tuple(paths),
        crop,
        source.size,
        metrics,
        tuple(sorted((str(key), str(value)) for key, value in (specialist_metadata or {}).items())),
    )


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


def _validate_focus_box(box, shape):
    if (
        not isinstance(box, (tuple, list))
        or len(box) != 4
        or any(isinstance(value, bool) or not isinstance(value, int) for value in box)
    ):
        raise PanelError("workhorse focus box must contain four integers")
    left, top, right, bottom = (int(value) for value in box)
    height, width = shape
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise PanelError("workhorse focus box is outside source geometry")
    return left, top, right, bottom
