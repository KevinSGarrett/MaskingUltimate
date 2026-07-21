"""QC-035..038 multi-instance hard gates and routing checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
from scipy import ndimage

from .checks import QcResult


@dataclass(frozen=True)
class MultiInstanceQcInputs:
    silhouettes: Mapping[str, np.ndarray]
    atomic_unions: Mapping[str, np.ndarray]
    contact_bands: Mapping[tuple[str, str], np.ndarray] = field(default_factory=dict)
    recorded_relationships: Mapping[str, frozenset[str]] = field(default_factory=dict)
    expected_promoted_count: int = 1
    configured_cap: int = 4
    instance_overlap_max: float = 0.30


def run_multi_instance_qc(inputs: MultiInstanceQcInputs) -> tuple[QcResult, ...]:
    names = sorted(inputs.silhouettes)
    if not names or set(inputs.atomic_unions) != set(names):
        raise ValueError("multi-instance QC requires matching non-empty silhouettes/atomic unions")
    shape = np.asarray(inputs.silhouettes[names[0]]).shape
    silhouettes = {name: _shape(value, shape, name) for name, value in inputs.silhouettes.items()}
    atomics = {name: _shape(value, shape, name) for name, value in inputs.atomic_unions.items()}
    overlaps: dict[str, float] = {}
    bleed: dict[str, int] = {}
    reciprocity: list[str] = []
    for index, a in enumerate(names):
        for b in names[index + 1 :]:
            union = silhouettes[a] | silhouettes[b]
            iou = (
                float(np.count_nonzero(silhouettes[a] & silhouettes[b]) / np.count_nonzero(union))
                if union.any()
                else 0.0
            )
            if iou > inputs.instance_overlap_max:
                overlaps[f"{a}:{b}"] = iou
            band_a = _optional_band(inputs.contact_bands.get((a, b)), shape)
            band_b = _optional_band(inputs.contact_bands.get((b, a)), shape)
            core_a = ndimage.binary_erosion(silhouettes[a], iterations=3)
            core_b = ndimage.binary_erosion(silhouettes[b], iterations=3)
            a_into_b = int(np.count_nonzero(atomics[a] & core_b & ~band_a))
            b_into_a = int(np.count_nonzero(atomics[b] & core_a & ~band_b))
            if a_into_b:
                bleed[f"{a}->{b}"] = a_into_b
            if b_into_a:
                bleed[f"{b}->{a}"] = b_into_a
            a_records = b in inputs.recorded_relationships.get(a, frozenset())
            b_records = a in inputs.recorded_relationships.get(b, frozenset())
            if a_records != b_records or ((a, b) in inputs.contact_bands) != (
                (b, a) in inputs.contact_bands
            ):
                reciprocity.append(f"{a}:{b}")
    count_ok = len(names) == inputs.expected_promoted_count and len(names) <= inputs.configured_cap
    return (
        QcResult(
            "QC-035",
            "instance_silhouette_exclusivity",
            not overlaps,
            f"above_threshold={overlaps}",
            "BLOCK",
        ),
        QcResult("QC-036", "cross_instance_bleed", not bleed, f"bleed_px={bleed}", "BLOCK"),
        QcResult(
            "QC-037",
            "interperson_contact_reciprocity",
            not reciprocity,
            f"nonreciprocal={reciprocity}",
            "ROUTE",
        ),
        QcResult(
            "QC-038",
            "instance_count_sanity",
            count_ok,
            f"actual={len(names)}, expected={inputs.expected_promoted_count}, cap={inputs.configured_cap}",
            "WARN",
        ),
    )


def _shape(value: np.ndarray, shape: tuple[int, ...], name: str) -> np.ndarray:
    array = np.asarray(value).astype(bool)
    if array.ndim != 2 or array.shape != shape:
        raise ValueError(f"multi-instance evidence dimensions differ for {name}")
    return array


def _optional_band(value: np.ndarray | None, shape: tuple[int, ...]) -> np.ndarray:
    return np.zeros(shape, dtype=bool) if value is None else _shape(value, shape, "contact_band")
