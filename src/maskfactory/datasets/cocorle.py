"""Strict uncompressed COCO-RLE serialization for dataset interoperability."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np


class CocoRleError(ValueError):
    """Raised when a binary mask or COCO-RLE document is not canonical."""


def encode_binary_mask(mask: np.ndarray) -> dict[str, Any]:
    """Encode a 2-D binary mask as canonical uncompressed COCO RLE.

    COCO traverses masks in column-major (Fortran) order and requires the first
    count to describe a background run, which may therefore be zero.
    """
    binary = _binary_array(mask)
    height, width = binary.shape
    flat = binary.reshape(-1, order="F")
    counts: list[int] = []
    previous = False
    run = 0
    for value in flat:
        current = bool(value)
        if current == previous:
            run += 1
        else:
            counts.append(run)
            previous = current
            run = 1
    counts.append(run)
    document = {"size": [height, width], "counts": counts}
    validate_rle(document)
    return document


def decode_binary_mask(rle: Mapping[str, Any]) -> np.ndarray:
    """Decode canonical uncompressed COCO RLE to a boolean mask."""
    height, width, counts = _validated_fields(rle)
    flat = np.zeros(height * width, dtype=bool)
    cursor = 0
    foreground = False
    for count in counts:
        end = cursor + count
        if foreground:
            flat[cursor:end] = True
        cursor = end
        foreground = not foreground
    return flat.reshape((height, width), order="F")


def validate_rle(rle: Mapping[str, Any]) -> None:
    """Validate shape, run totals, and canonical alternating-run representation."""
    _validated_fields(rle)


def _validated_fields(rle: Mapping[str, Any]) -> tuple[int, int, tuple[int, ...]]:
    if not isinstance(rle, Mapping) or set(rle) != {"size", "counts"}:
        raise CocoRleError("COCO RLE must contain exactly size and counts")
    size = rle["size"]
    if (
        not isinstance(size, Sequence)
        or isinstance(size, (str, bytes))
        or len(size) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in size)
    ):
        raise CocoRleError("COCO RLE size must be [height, width] integers")
    height, width = (int(value) for value in size)
    if height <= 0 or width <= 0:
        raise CocoRleError("COCO RLE dimensions must be positive")
    raw_counts = rle["counts"]
    if (
        not isinstance(raw_counts, Sequence)
        or isinstance(raw_counts, (str, bytes))
        or not raw_counts
        or any(isinstance(value, bool) or not isinstance(value, int) for value in raw_counts)
    ):
        raise CocoRleError("uncompressed COCO RLE counts must be a nonempty integer sequence")
    counts = tuple(int(value) for value in raw_counts)
    if counts[0] < 0 or any(value <= 0 for value in counts[1:]):
        raise CocoRleError("only the initial background run may be zero")
    if sum(counts) != height * width:
        raise CocoRleError("COCO RLE counts do not cover exactly height*width pixels")
    return height, width, counts


def _binary_array(mask: np.ndarray) -> np.ndarray:
    array = np.asarray(mask)
    if array.ndim != 2 or 0 in array.shape:
        raise CocoRleError("COCO RLE source mask must be a nonempty 2-D array")
    if array.dtype == np.bool_:
        return array
    if not np.issubdtype(array.dtype, np.integer):
        raise CocoRleError("COCO RLE source mask must be boolean or integer binary")
    values = set(int(value) for value in np.unique(array))
    if not values <= {0, 1} and not values <= {0, 255}:
        raise CocoRleError(f"COCO RLE source mask is not binary: {sorted(values)}")
    return array != 0
