"""Validated image, JSON, label-map, and mask readers (docs 03/04)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .png_strict import read_mask


def read_json(path: Path, *, require_object: bool = False) -> Any:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if require_object and not isinstance(document, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return document


def read_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB")).copy()


def read_label_map(path: Path, *, bits: int) -> np.ndarray:
    if bits not in {8, 16}:
        raise ValueError("label-map bits must be 8 or 16")
    with Image.open(path) as image:
        value = np.asarray(image).copy()
    maximum = 255 if bits == 8 else 65535
    if value.ndim != 2 or not np.issubdtype(value.dtype, np.integer):
        raise ValueError(f"label map must be a 2-D integer image: {path}")
    if value.size and (int(value.min()) < 0 or int(value.max()) > maximum):
        raise ValueError(f"label map exceeds {bits}-bit range: {path}")
    return value.astype(np.uint8 if bits == 8 else np.uint16, copy=False)


__all__ = ["read_json", "read_label_map", "read_mask", "read_rgb"]
