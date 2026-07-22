from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from maskfactory.nude_visual_evidence import (
    NudeVisualEvidenceError,
    verify_pixel_semantic_visual_evidence,
)
from maskfactory.providers.disagreement import binary_mask_sha256


def _write(path: Path, array: np.ndarray) -> dict[str, str]:
    Image.fromarray(array).save(path)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _evidence(tmp_path: Path) -> tuple[Path, str, str, dict[str, dict[str, str]]]:
    source = np.full((48, 48, 3), 40, dtype=np.uint8)
    source[12:36, 14:34] = [180, 130, 100]
    source_path = tmp_path / "original.png"
    Image.fromarray(source).save(source_path)
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    mask = np.zeros((48, 48), dtype=bool)
    mask[12:36, 14:34] = True
    mask_rgb = np.repeat((mask.astype(np.uint8) * 255)[..., None], 3, axis=2)
    overlay = source.copy()
    overlay[mask] = [120, 20, 20]
    contour = source.copy()
    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(contour, contours, -1, (255, 0, 0), 2)
    ownership_image = Image.fromarray(source.copy())
    ImageDraw.Draw(ownership_image).rectangle((14, 12, 34, 36), outline=(255, 0, 0), width=2)
    views = {
        "source": _write(tmp_path / "source.png", source),
        "mask": _write(tmp_path / "mask.png", mask_rgb),
        "overlay": _write(tmp_path / "overlay.png", overlay),
        "contour": _write(tmp_path / "contour.png", contour),
        "ownership": _write(tmp_path / "ownership.png", np.asarray(ownership_image)),
    }
    return source_path, source_sha, binary_mask_sha256(mask), views


def test_five_views_are_bound_to_exact_source_mask_and_semantics(tmp_path: Path) -> None:
    source, source_sha, mask_sha, views = _evidence(tmp_path)
    result = verify_pixel_semantic_visual_evidence(
        original_source_path=source,
        original_source_sha256=source_sha,
        selected_mask_sha256=mask_sha,
        views=views,
    )
    assert result["verified_semantics"]["mask_pixels_exact"] is True


def test_unrelated_overlay_pixels_fail_even_with_current_file_hash(tmp_path: Path) -> None:
    source, source_sha, mask_sha, views = _evidence(tmp_path)
    overlay_path = Path(views["overlay"]["path"])
    overlay = np.asarray(Image.open(overlay_path).convert("RGB")).copy()
    overlay[0, 0] = [255, 255, 255]
    views["overlay"] = _write(overlay_path, overlay)
    with pytest.raises(NudeVisualEvidenceError, match="overlay_view_semantics_invalid"):
        verify_pixel_semantic_visual_evidence(
            original_source_path=source,
            original_source_sha256=source_sha,
            selected_mask_sha256=mask_sha,
            views=views,
        )
