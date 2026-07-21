"""Deterministic target-aware visual-critic panel rendering."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from maskfactory.providers.disagreement import binary_mask_sha256

from .critic_catalog import canonical_sha256
from .target_contract import authorize_critic_invocation, validate_target_contract


class PanelRenderError(ValueError):
    """Panel inputs do not match the exact target/source/candidate geometry."""


@dataclass(frozen=True)
class RenderedPanelSet:
    manifest: dict[str, Any]
    png_bytes: dict[str, bytes]


def transform_sha256(contract: dict[str, Any]) -> str:
    return canonical_sha256(contract["transforms"])


def _png_bytes(array: np.ndarray, mode: str) -> bytes:
    stream = io.BytesIO()
    Image.fromarray(array, mode=mode).save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()


def _contour(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, constant_values=False)
    interior = padded[1:-1, 1:-1]
    eroded = interior & padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    return interior & ~eroded


def render_target_panels(
    *,
    source_rgb: np.ndarray,
    candidate_mask: np.ndarray,
    disagreement_mask: np.ndarray,
    target_contract: dict[str, Any],
    source_file_sha256: str,
    candidate_file_sha256: str,
    expected_target_contract_sha256: str,
    expected_transform_sha256: str,
    crop_xyxy: tuple[int, int, int, int],
) -> RenderedPanelSet:
    """Render source, mask, overlay, contour, zoom, and disagreement PNGs."""

    try:
        validate_target_contract(target_contract)
        authorization = authorize_critic_invocation(
            target_contract,
            source_sha256=source_file_sha256,
            candidate_mask_sha256=candidate_file_sha256,
            source_size=(source_rgb.shape[1], source_rgb.shape[0]),
        )
    except Exception as exc:
        raise PanelRenderError(f"panel input authorization failed: {exc}") from exc
    if target_contract["contract_sha256"] != expected_target_contract_sha256:
        raise PanelRenderError("panel target contract hash differs from expected target")
    actual_transform_sha256 = transform_sha256(target_contract)
    if actual_transform_sha256 != expected_transform_sha256:
        raise PanelRenderError("panel transform hash differs from expected transform")
    if source_rgb.dtype != np.uint8 or source_rgb.ndim != 3 or source_rgb.shape[2] != 3:
        raise PanelRenderError("panel source must be HxWx3 uint8 RGB")
    shape = source_rgb.shape[:2]
    if (
        candidate_mask.dtype != np.bool_
        or disagreement_mask.dtype != np.bool_
        or candidate_mask.shape != shape
        or disagreement_mask.shape != shape
    ):
        raise PanelRenderError("panel masks must be source-sized boolean arrays")
    x0, y0, x1, y1 = crop_xyxy
    width, height = shape[1], shape[0]
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise PanelRenderError("panel crop escapes source geometry")
    roi_x0, roi_y0, roi_x1, roi_y1 = target_contract["target"]["allowed_roi_xyxy"]
    if not (roi_x0 <= x0 < x1 <= roi_x1 and roi_y0 <= y0 < y1 <= roi_y1):
        raise PanelRenderError("panel crop escapes target ROI")
    allowed = np.zeros(shape, dtype=np.bool_)
    allowed[roi_y0:roi_y1, roi_x0:roi_x1] = True
    if np.any(candidate_mask & ~allowed) or np.any(disagreement_mask & ~allowed):
        raise PanelRenderError("candidate or disagreement pixels escape target ROI")

    mask_u8 = candidate_mask.astype(np.uint8) * 255
    disagreement_u8 = disagreement_mask.astype(np.uint8) * 255
    contour = _contour(candidate_mask)
    contour_rgb = source_rgb.copy()
    contour_rgb[contour] = np.array([0, 255, 0], dtype=np.uint8)
    overlay = source_rgb.astype(np.float32)
    tint = np.zeros_like(overlay)
    tint[..., 0] = 255
    overlay[candidate_mask] = overlay[candidate_mask] * 0.55 + tint[candidate_mask] * 0.45
    overlay_u8 = np.clip(np.rint(overlay), 0, 255).astype(np.uint8)
    zoom = overlay_u8[y0:y1, x0:x1]
    panels = {
        "source": _png_bytes(source_rgb, "RGB"),
        "binary_mask": _png_bytes(mask_u8, "L"),
        "overlay": _png_bytes(overlay_u8, "RGB"),
        "contour": _png_bytes(contour_rgb, "RGB"),
        "full_context": _png_bytes(source_rgb, "RGB"),
        "uncertainty_zoom": _png_bytes(zoom, "RGB"),
        "disagreement": _png_bytes(disagreement_u8, "L"),
    }
    manifest = {
        "schema_version": "1.0.0",
        "target_contract_sha256": expected_target_contract_sha256,
        "transform_sha256": expected_transform_sha256,
        "source_file_sha256": source_file_sha256,
        "candidate_file_sha256": candidate_file_sha256,
        "candidate_pixel_sha256": binary_mask_sha256(candidate_mask),
        "disagreement_pixel_sha256": binary_mask_sha256(disagreement_mask),
        "source_geometry_wh": [width, height],
        "crop_xyxy": list(crop_xyxy),
        "authorization_sha256": authorization["invocation_sha256"],
        "panel_sha256": {
            name: hashlib.sha256(content).hexdigest() for name, content in panels.items()
        },
    }
    manifest["panel_set_sha256"] = canonical_sha256(manifest)
    return RenderedPanelSet(manifest=manifest, png_bytes=panels)
