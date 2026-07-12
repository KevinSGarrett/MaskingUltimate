"""Deterministic P2 per-part metrics and weighted package score."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
from scipy import ndimage


class MetricError(ValueError):
    """Metric inputs are incompatible or invalid."""


@dataclass(frozen=True)
class PartMetrics:
    iou_vs_consensus: float
    iou_vs_previous_gold_or_model: float | None
    boundary_f_2px: float
    hausdorff_95: float | None
    hole_ratio: float
    components: int
    mask_area_px: int
    mask_bbox: tuple[int, int, int, int] | None
    disagreement_score: float
    overlap_with_protected_regions: float
    overlap_with_mutually_exclusive_parts: float


def iou(first: np.ndarray, second: np.ndarray) -> float:
    a, b = _pair(first, second)
    union = int(np.count_nonzero(a | b))
    return int(np.count_nonzero(a & b)) / union if union else 1.0


def boundary_f(first: np.ndarray, second: np.ndarray, *, tolerance_px: int = 2) -> float:
    a, b = _pair(first, second)
    contour_a, contour_b = _contour(a), _contour(b)
    if not contour_a.any() and not contour_b.any():
        return 1.0
    if not contour_a.any() or not contour_b.any():
        return 0.0
    near_b = ndimage.binary_dilation(contour_b, iterations=tolerance_px)
    near_a = ndimage.binary_dilation(contour_a, iterations=tolerance_px)
    precision = np.count_nonzero(contour_a & near_b) / np.count_nonzero(contour_a)
    recall = np.count_nonzero(contour_b & near_a) / np.count_nonzero(contour_b)
    return float(2 * precision * recall / (precision + recall)) if precision + recall else 0.0


def hausdorff_percentile(first: np.ndarray, second: np.ndarray, *, percentile: float = 95) -> float:
    a, b = _pair(first, second)
    contour_a, contour_b = _contour(a), _contour(b)
    if not contour_a.any() and not contour_b.any():
        return 0.0
    if not contour_a.any() or not contour_b.any():
        return float("inf")
    distance_to_b = ndimage.distance_transform_edt(~contour_b)[contour_a]
    distance_to_a = ndimage.distance_transform_edt(~contour_a)[contour_b]
    return float(np.percentile(np.concatenate((distance_to_b, distance_to_a)), percentile))


def hole_ratio(mask: np.ndarray) -> float:
    binary = _mask(mask)
    area = int(binary.sum())
    holes = ndimage.binary_fill_holes(binary) & ~binary
    # The QA report contract is a unit interval.  A thin closed contour can enclose
    # more background than foreground, so the raw holes/foreground ratio is
    # legitimately greater than one; saturate it instead of emitting invalid JSON.
    return min(1.0, int(holes.sum()) / area) if area else 0.0


def component_count(mask: np.ndarray) -> int:
    return int(ndimage.label(_mask(mask))[1])


def mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(_mask(mask))
    return (
        None
        if not len(xs)
        else (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    )


def compute_part_metrics(
    mask: np.ndarray,
    consensus: np.ndarray,
    *,
    previous: np.ndarray | None = None,
    disagreement: np.ndarray | None = None,
    protected: np.ndarray | None = None,
    mutually_exclusive: np.ndarray | None = None,
    hard_class: bool = False,
) -> PartMetrics:
    candidate, authority = _pair(mask, consensus)
    area = int(candidate.sum())
    disagreement_value = _normalized_ramp(disagreement, candidate)
    protected_overlap = _overlap_fraction(candidate, protected)
    exclusive_overlap = _overlap_fraction(candidate, mutually_exclusive)
    return PartMetrics(
        iou(candidate, authority),
        iou(candidate, previous) if previous is not None else None,
        boundary_f(candidate, authority, tolerance_px=2),
        hausdorff_percentile(candidate, authority) if hard_class else None,
        hole_ratio(candidate),
        component_count(candidate),
        area,
        mask_bbox(candidate),
        disagreement_value,
        protected_overlap,
        exclusive_overlap,
    )


def package_qa_score(
    metrics: Mapping[str, PartMetrics],
    *,
    hard_parts: set[str],
) -> float:
    """Weighted mean; BLOCK outcomes remain external and can never be overridden by score."""
    if not metrics:
        raise MetricError("cannot score an empty package")
    weighted_sum = 0.0
    total_weight = 0.0
    for name, value in metrics.items():
        terms = (
            value.iou_vs_consensus,
            value.boundary_f_2px,
            1 - min(1.0, value.disagreement_score),
            1 - min(1.0, value.hole_ratio),
            1 - min(1.0, value.overlap_with_protected_regions),
            1 - min(1.0, value.overlap_with_mutually_exclusive_parts),
        )
        term_weights = (0.30, 0.25, 0.20, 0.10, 0.075, 0.075)
        normalized = sum(term * weight for term, weight in zip(terms, term_weights, strict=True))
        class_weight = 2.0 if name in hard_parts else 1.0
        weighted_sum += normalized * class_weight
        total_weight += class_weight
    return float(weighted_sum / total_weight)


def _mask(value: np.ndarray) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 2:
        raise MetricError("metric masks must be 2-D")
    return array.astype(bool)


def _pair(first: np.ndarray, second: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a, b = _mask(first), _mask(second)
    if a.shape != b.shape:
        raise MetricError("metric mask dimensions differ")
    return a, b


def _contour(mask: np.ndarray) -> np.ndarray:
    return mask ^ ndimage.binary_erosion(mask)


def _overlap_fraction(mask: np.ndarray, other: np.ndarray | None) -> float:
    if other is None:
        return 0.0
    candidate, comparison = _pair(mask, other)
    area = int(candidate.sum())
    return int(np.count_nonzero(candidate & comparison)) / area if area else 0.0


def _normalized_ramp(ramp: np.ndarray | None, mask: np.ndarray) -> float:
    if ramp is None or not mask.any():
        return 0.0
    value = np.asarray(ramp)
    if value.shape != mask.shape or not np.isfinite(value).all():
        raise MetricError("disagreement ramp dimensions/values invalid")
    normalized = value.astype(np.float64)
    if np.issubdtype(value.dtype, np.integer):
        if value.min() < 0 or value.max() > 255:
            raise MetricError("integer disagreement must be 0..255")
        normalized /= 255
    elif normalized.min() < 0 or normalized.max() > 1:
        raise MetricError("float disagreement must be 0..1")
    return float(normalized[mask].mean())
