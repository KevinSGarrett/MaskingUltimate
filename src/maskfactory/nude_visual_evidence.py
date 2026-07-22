"""Pixel-semantic verification for adult-corpus per-record visual evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np
from PIL import Image

from .providers.disagreement import binary_mask_sha256

REQUIRED_VIEWS = ("source", "mask", "overlay", "contour", "ownership")


class NudeVisualEvidenceError(ValueError):
    """A visual view was hash-valid but did not depict its declared evidence."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _load_bound_view(entry: Mapping[str, Any], kind: str) -> tuple[np.ndarray, str]:
    path = Path(str(entry.get("path") or ""))
    expected = str(entry.get("sha256") or "")
    if not path.is_file() or len(expected) != 64:
        raise NudeVisualEvidenceError(f"{kind}_view_missing_or_hash_invalid")
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed != expected:
        raise NudeVisualEvidenceError(f"{kind}_view_hash_mismatch")
    try:
        array = np.asarray(Image.open(path).convert("RGB"))
    except OSError as exc:
        raise NudeVisualEvidenceError(f"{kind}_view_decode_failed") from exc
    return array, observed


def verify_pixel_semantic_visual_evidence(
    *,
    original_source_path: Path,
    original_source_sha256: str,
    selected_mask_sha256: str,
    views: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Prove five separate views actually depict one exact source and mask."""

    if set(views) != set(REQUIRED_VIEWS):
        raise NudeVisualEvidenceError("exact_five_view_set_required")
    source_path = Path(original_source_path)
    if (
        not source_path.is_file()
        or hashlib.sha256(source_path.read_bytes()).hexdigest() != original_source_sha256
    ):
        raise NudeVisualEvidenceError("original_source_hash_mismatch")
    original = np.asarray(Image.open(source_path).convert("RGB"))
    loaded = {kind: _load_bound_view(views[kind], kind) for kind in REQUIRED_VIEWS}
    arrays = {kind: value[0] for kind, value in loaded.items()}
    if any(value.shape != original.shape for value in arrays.values()):
        raise NudeVisualEvidenceError("visual_evidence_geometry_mismatch")
    if not np.array_equal(arrays["source"], original):
        raise NudeVisualEvidenceError("source_view_pixel_mismatch")
    mask_rgb = arrays["mask"]
    if not (
        np.array_equal(mask_rgb[..., 0], mask_rgb[..., 1])
        and np.array_equal(mask_rgb[..., 1], mask_rgb[..., 2])
        and set(np.unique(mask_rgb[..., 0])).issubset({0, 255})
    ):
        raise NudeVisualEvidenceError("mask_view_not_strict_binary")
    mask = mask_rgb[..., 0] == 255
    if not mask.any() or mask.all():
        raise NudeVisualEvidenceError("mask_view_degenerate")
    observed_mask_sha256 = binary_mask_sha256(mask)
    if observed_mask_sha256 != selected_mask_sha256:
        raise NudeVisualEvidenceError("mask_view_payload_mismatch")

    overlay_diff = np.any(arrays["overlay"] != original, axis=2)
    if not overlay_diff.any() or np.any(overlay_diff & ~mask):
        raise NudeVisualEvidenceError("overlay_view_semantics_invalid")

    contour_diff = np.any(arrays["contour"] != original, axis=2)
    boundary = cv2.morphologyEx(
        mask.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)
    )
    contour_allowed = cv2.dilate(boundary, np.ones((5, 5), np.uint8)).astype(bool)
    if not contour_diff.any() or np.any(contour_diff & ~contour_allowed):
        raise NudeVisualEvidenceError("contour_view_semantics_invalid")

    ownership_diff = np.any(arrays["ownership"] != original, axis=2)
    ys, xs = np.nonzero(mask)
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)
    box = np.zeros(mask.shape, dtype=np.uint8)
    cv2.rectangle(box, (x0, y0), (x1, y1), 1, 2)
    ownership_allowed = cv2.dilate(box, np.ones((9, 9), np.uint8)).astype(bool)
    if not ownership_diff.any() or np.any(ownership_diff & ~ownership_allowed):
        raise NudeVisualEvidenceError("ownership_view_semantics_invalid")

    result = {
        "schema_version": "maskfactory.nude_pixel_semantic_visual_evidence.v1",
        "original_source_sha256": original_source_sha256,
        "decoded_source_pixels_sha256": hashlib.sha256(original.tobytes()).hexdigest(),
        "selected_mask_sha256": observed_mask_sha256,
        "source_geometry": [int(original.shape[0]), int(original.shape[1])],
        "view_file_sha256s": {kind: loaded[kind][1] for kind in REQUIRED_VIEWS},
        "verified_semantics": {
            "source_pixels_exact": True,
            "mask_pixels_exact": True,
            "overlay_changes_only_inside_mask": True,
            "contour_changes_only_near_boundary": True,
            "ownership_marks_target_bbox": True,
        },
    }
    result["self_sha256"] = _canonical_sha256(result)
    return result


__all__ = [
    "NudeVisualEvidenceError",
    "REQUIRED_VIEWS",
    "verify_pixel_semantic_visual_evidence",
]
