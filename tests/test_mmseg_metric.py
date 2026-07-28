from types import SimpleNamespace

import numpy as np
import pytest

from maskfactory.training.mmseg_metric import (
    SegmentationMetricError,
    _load_metric_framework,
    aggregate_segmentation_stats,
    segmentation_sample_stats,
)


def test_segmentation_metric_ignores_255_and_reports_per_class_iou_boundary() -> None:
    target = np.array([[0, 0, 1, 1], [0, 255, 1, 1], [2, 2, 2, 2], [2, 2, 2, 2]], dtype=np.uint8)
    prediction = target.copy()
    prediction[0, 0] = 1
    prediction[1, 1] = 2  # ignored target pixel must not affect any class
    stats = segmentation_sample_stats(prediction, target, num_classes=3)
    assert stats["intersections"] == [2, 4, 8]
    assert stats["unions"] == [3, 5, 8]
    metrics = aggregate_segmentation_stats([stats], class_names=("bg", "arm", "leg"))
    assert metrics["IoU/bg"] == pytest.approx(2 / 3)
    assert metrics["IoU/arm"] == pytest.approx(4 / 5)
    assert metrics["IoU/leg"] == 1.0
    assert metrics["mIoU"] == pytest.approx((2 / 3 + 4 / 5 + 1) / 3)
    assert all(0 <= metrics[f"BoundaryF_2px/{name}"] <= 1 for name in ("bg", "arm", "leg"))


def test_metric_aggregates_iou_counts_not_per_image_means_and_skips_absent() -> None:
    first = segmentation_sample_stats(
        np.array([[0, 0], [0, 1]]), np.array([[0, 0], [1, 1]]), num_classes=3
    )
    second = segmentation_sample_stats(
        np.array([[0, 0], [0, 0]]), np.array([[0, 0], [0, 1]]), num_classes=3
    )
    metrics = aggregate_segmentation_stats([first, second], class_names=("bg", "part", "absent"))
    assert metrics["IoU/part"] == pytest.approx(1 / 3)
    assert np.isnan(metrics["IoU/absent"])
    assert np.isnan(metrics["BoundaryF_2px/absent"])
    assert metrics["mIoU"] == pytest.approx((5 / 7 + 1 / 3) / 2)


@pytest.mark.parametrize(
    "prediction,target,message",
    [
        (np.zeros((2, 2, 1)), np.zeros((2, 2)), "same-shape 2-D"),
        (np.zeros((2, 2), dtype=float), np.zeros((2, 2), dtype=np.uint8), "integer IDs"),
        (np.full((2, 2), 3), np.zeros((2, 2), dtype=np.uint8), "out-of-range"),
    ],
)
def test_metric_refuses_invalid_maps(prediction, target, message: str) -> None:
    with pytest.raises(SegmentationMetricError, match=message):
        segmentation_sample_stats(prediction, target, num_classes=3)


def test_metric_framework_loader_only_swallows_absent_top_level_package() -> None:
    def missing(_name: str):
        raise ModuleNotFoundError("No module named 'mmengine'", name="mmengine")

    assert _load_metric_framework(missing) == (None, None)

    def broken(_name: str):
        raise ModuleNotFoundError("No module named 'mmcv._ext'", name="mmcv._ext")

    with pytest.raises(ModuleNotFoundError, match="mmcv._ext"):
        _load_metric_framework(broken)
    modules = {
        "mmengine.evaluator": SimpleNamespace(BaseMetric=object()),
        "mmseg.registry": SimpleNamespace(METRICS=object()),
    }
    base, registry = _load_metric_framework(modules.__getitem__)
    assert base is modules["mmengine.evaluator"].BaseMetric
    assert registry is modules["mmseg.registry"].METRICS
