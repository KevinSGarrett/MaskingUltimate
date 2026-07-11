"""MMSeg metric for MaskFactory per-class IoU and boundary-F@2px."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from ..qa.metrics import boundary_f
from .augmentations import IGNORE_INDEX


class SegmentationMetricError(ValueError):
    """A training metric input or aggregation contract is invalid."""


def segmentation_sample_stats(
    prediction: np.ndarray,
    target: np.ndarray,
    *,
    num_classes: int,
    ignore_index: int = IGNORE_INDEX,
) -> dict[str, list[int | float | None]]:
    """Return additive IoU counts and per-present-class BF values for one image."""
    pred = np.asarray(prediction)
    truth = np.asarray(target)
    if pred.ndim != 2 or truth.shape != pred.shape:
        raise SegmentationMetricError("prediction and target must be same-shape 2-D maps")
    if not np.issubdtype(pred.dtype, np.integer) or not np.issubdtype(truth.dtype, np.integer):
        raise SegmentationMetricError("prediction and target maps must use integer IDs")
    if not isinstance(num_classes, int) or num_classes < 1:
        raise SegmentationMetricError("num_classes must be a positive integer")
    valid = truth != ignore_index
    invalid_truth = np.unique(truth[valid][(truth[valid] < 0) | (truth[valid] >= num_classes)])
    invalid_pred = np.unique(pred[valid][(pred[valid] < 0) | (pred[valid] >= num_classes)])
    if invalid_truth.size or invalid_pred.size:
        raise SegmentationMetricError(
            f"metric maps contain out-of-range IDs: truth={invalid_truth.tolist()} "
            f"prediction={invalid_pred.tolist()}"
        )
    intersections: list[int] = []
    unions: list[int] = []
    boundary_values: list[float | None] = []
    for class_id in range(num_classes):
        predicted = (pred == class_id) & valid
        expected = (truth == class_id) & valid
        intersection = int(np.count_nonzero(predicted & expected))
        union = int(np.count_nonzero(predicted | expected))
        intersections.append(intersection)
        unions.append(union)
        boundary_values.append(boundary_f(predicted, expected, tolerance_px=2) if union else None)
    return {
        "intersections": intersections,
        "unions": unions,
        "boundary_f_2px": boundary_values,
    }


def aggregate_segmentation_stats(
    results: Iterable[dict[str, Sequence[int | float | None]]],
    *,
    class_names: Sequence[str],
) -> dict[str, float]:
    """Aggregate worker-safe sample records into exact leaderboard-ready metrics."""
    names = tuple(class_names)
    if not names or len(set(names)) != len(names):
        raise SegmentationMetricError("class_names must be non-empty and unique")
    intersections = np.zeros(len(names), dtype=np.int64)
    unions = np.zeros(len(names), dtype=np.int64)
    boundary_values: list[list[float]] = [[] for _ in names]
    count = 0
    for result in results:
        count += 1
        sample_intersections = result.get("intersections")
        sample_unions = result.get("unions")
        sample_boundaries = result.get("boundary_f_2px")
        if not all(
            isinstance(value, Sequence) and len(value) == len(names)
            for value in (sample_intersections, sample_unions, sample_boundaries)
        ):
            raise SegmentationMetricError("sample metric vector length differs from class_names")
        intersections += np.asarray(sample_intersections, dtype=np.int64)
        unions += np.asarray(sample_unions, dtype=np.int64)
        for index, value in enumerate(sample_boundaries):
            if value is not None:
                numeric = float(value)
                if not 0 <= numeric <= 1 or not np.isfinite(numeric):
                    raise SegmentationMetricError("boundary-F values must be finite in [0, 1]")
                boundary_values[index].append(numeric)
    if not count:
        raise SegmentationMetricError("cannot aggregate an empty metric result set")
    per_iou = [
        float(intersections[index] / unions[index]) if unions[index] else float("nan")
        for index in range(len(names))
    ]
    per_boundary = [
        float(np.mean(values)) if values else float("nan") for values in boundary_values
    ]
    present_iou = [value for value in per_iou if np.isfinite(value)]
    present_boundary = [value for value in per_boundary if np.isfinite(value)]
    if not present_iou or not present_boundary:
        raise SegmentationMetricError("metric batch contains no evaluable classes")
    metrics: dict[str, float] = {
        "mIoU": float(np.mean(present_iou)),
        "mBoundaryF_2px": float(np.mean(present_boundary)),
    }
    for index, name in enumerate(names):
        metrics[f"IoU/{name}"] = per_iou[index]
        metrics[f"BoundaryF_2px/{name}"] = per_boundary[index]
    return metrics


def _load_metric_framework(
    importer: Callable[[str], ModuleType] = importlib.import_module,
) -> tuple[object | None, object | None]:
    """Load BaseMetric/METRICS only when the full training stack is available."""
    try:
        base = importer("mmengine.evaluator").BaseMetric
        registry = importer("mmseg.registry").METRICS
    except ModuleNotFoundError as exc:
        if exc.name in {"mmengine", "mmseg"}:
            return None, None
        raise
    return base, registry


BaseMetric, METRICS = _load_metric_framework()
if BaseMetric is not None and METRICS is not None:

    @METRICS.register_module()
    class MaskFactorySegMetric(BaseMetric):
        """Distributed MMSeg adapter for exact MaskFactory IoU/BF evidence."""

        default_prefix = "maskfactory"

        def __init__(
            self,
            *,
            class_names: Sequence[str],
            ignore_index: int = IGNORE_INDEX,
            collect_device: str = "cpu",
            prefix: str | None = None,
        ) -> None:
            super().__init__(collect_device=collect_device, prefix=prefix)
            self.class_names = tuple(class_names)
            self.ignore_index = int(ignore_index)

        def process(self, data_batch: Any, data_samples: Sequence[Any]) -> None:
            del data_batch
            for sample in data_samples:
                prediction = sample.pred_sem_seg.data.squeeze().detach().cpu().numpy()
                target = sample.gt_sem_seg.data.squeeze().detach().cpu().numpy()
                self.results.append(
                    segmentation_sample_stats(
                        prediction,
                        target,
                        num_classes=len(self.class_names),
                        ignore_index=self.ignore_index,
                    )
                )

        def compute_metrics(self, results: list[dict[str, Any]]) -> dict[str, float]:
            return aggregate_segmentation_stats(results, class_names=self.class_names)
