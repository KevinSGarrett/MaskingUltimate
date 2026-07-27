"""Strict ontology/CVAT label mapping and CVAT mask-RLE conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..ontology import Ontology, OntologyError, get_ontology


class CvatMappingError(ValueError):
    """CVAT labels or mask payloads do not match the canonical ontology."""


@dataclass(frozen=True)
class CvatLabel:
    id: int
    name: str
    color: str
    attributes: dict[str, int]


class CvatLabelMap:
    """Bidirectional validated mapping from ontology names to CVAT server IDs."""

    def __init__(self, labels: list[dict[str, Any]], *, ontology: Ontology | None = None) -> None:
        authority = ontology or get_ontology()
        expected = {label.name for label in authority.labels}
        by_name: dict[str, CvatLabel] = {}
        by_id: dict[int, CvatLabel] = {}
        for raw in labels:
            try:
                label_id = int(raw["id"])
                name = str(raw["name"])
                color = str(raw["color"])
                attributes = {
                    str(attribute["name"]): int(attribute["id"])
                    for attribute in raw.get("attributes", [])
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise CvatMappingError(f"invalid CVAT label record: {raw!r}") from exc
            if name in by_name or label_id in by_id:
                raise CvatMappingError(f"duplicate CVAT label name/id: {name}/{label_id}")
            record = CvatLabel(label_id, name, color, attributes)
            by_name[name] = record
            by_id[label_id] = record
        missing = sorted(expected.difference(by_name))
        extra = sorted(set(by_name).difference(expected))
        if missing or extra:
            raise CvatMappingError(f"CVAT/ontology label drift; missing={missing}, extra={extra}")
        required_attributes = {"visibility", "ambiguous", "notes"}
        wrong_attributes = sorted(
            name for name, label in by_name.items() if set(label.attributes) != required_attributes
        )
        if wrong_attributes:
            raise CvatMappingError(
                "CVAT labels have incorrect attributes: " + ", ".join(wrong_attributes)
            )
        self._by_name = by_name
        self._by_id = by_id

    def cvat_id(self, ontology_name: str) -> int:
        try:
            return self._by_name[ontology_name].id
        except KeyError as exc:
            raise CvatMappingError(f"unknown ontology/CVAT label: {ontology_name!r}") from exc

    def ontology_name(self, cvat_id: int) -> str:
        try:
            return self._by_id[cvat_id].name
        except KeyError as exc:
            raise CvatMappingError(f"unknown CVAT label id: {cvat_id}") from exc

    def attribute_id(self, ontology_name: str, attribute: str) -> int:
        try:
            return self._by_name[ontology_name].attributes[attribute]
        except KeyError as exc:
            raise CvatMappingError(
                f"unknown CVAT attribute {attribute!r} for {ontology_name!r}"
            ) from exc

    def as_document(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "labels": {
                name: {
                    "cvat_id": label.id,
                    "color": label.color,
                    "attributes": label.attributes,
                }
                for name, label in sorted(self._by_name.items())
            },
        }


def encode_mask_rle(mask: np.ndarray) -> list[int]:
    """Encode a strict binary mask in CVAT's run-counts-plus-bbox representation."""
    array = np.asarray(mask)
    if array.ndim != 2:
        raise CvatMappingError(f"mask must be 2-D, got {array.shape}")
    if array.dtype != np.bool_:
        values = set(np.unique(array).tolist())
        if not values.issubset({0, 255}):
            raise CvatMappingError(f"mask must be bool or {{0,255}}, got {sorted(values)}")
        array = array == 255
    ys, xs = np.nonzero(array)
    if len(xs) == 0:
        raise CvatMappingError("CVAT does not accept an empty mask shape")
    left, right = int(xs.min()), int(xs.max())
    top, bottom = int(ys.min()), int(ys.max())
    crop = array[top : bottom + 1, left : right + 1].reshape(-1)
    counts: list[int] = []
    current = False
    count = 0
    for value in crop:
        boolean = bool(value)
        if boolean == current:
            count += 1
        else:
            counts.append(count)
            count = 1
            current = boolean
    counts.append(count)
    return [*counts, left, top, right, bottom]


def decode_mask_rle(points: list[float | int], *, shape: tuple[int, int]) -> np.ndarray:
    """Decode CVAT mask points to a full-resolution strict uint8 mask."""
    if len(points) < 5:
        raise CvatMappingError("CVAT mask RLE must contain counts and four bbox coordinates")
    integer_points = [int(value) for value in points]
    counts = integer_points[:-4]
    left, top, right, bottom = integer_points[-4:]
    height, width = shape
    if not (0 <= left <= right < width and 0 <= top <= bottom < height):
        raise CvatMappingError(f"CVAT mask bbox is outside {width}x{height}")
    expected = (right - left + 1) * (bottom - top + 1)
    if any(count < 0 for count in counts) or sum(counts) != expected:
        raise CvatMappingError(f"CVAT RLE length {sum(counts)} != bbox area {expected}")
    flat = np.zeros(expected, dtype=np.uint8)
    cursor = 0
    foreground = False
    for count in counts:
        if foreground:
            flat[cursor : cursor + count] = 255
        cursor += count
        foreground = not foreground
    output = np.zeros(shape, dtype=np.uint8)
    output[top : bottom + 1, left : right + 1] = flat.reshape(bottom - top + 1, right - left + 1)
    return output


def require_ontology_label(name: str) -> None:
    """Convenience hard-error boundary used by import code."""
    try:
        get_ontology().label(name, require_enabled=True)
    except OntologyError as exc:
        raise CvatMappingError(str(exc)) from exc
