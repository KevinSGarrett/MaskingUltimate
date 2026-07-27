import json
from pathlib import Path

import numpy as np

from maskfactory.stages.s02_silhouette import SilhouetteError, build_silhouette


def test_s02_places_connected_silhouette_on_full_canvas_and_writes_metrics(tmp_path: Path) -> None:
    confidence = np.zeros((6, 6), dtype=np.float32)
    confidence[1:5, 1:5] = 0.9
    confidence[0, 0] = 0.8  # disconnected component below the configured joining floor

    result = build_silhouette(
        confidence,
        context_bbox_xyxy=(2, 2, 8, 8),
        person_bbox_xyxy=(3, 3, 7, 7),
        full_size=(10, 10),
        output_dir=tmp_path,
        connected_min_person_pct=0.5,
        ratio_range=(0.9, 1.1),
    )

    assert result.area_px == 16
    assert result.bbox_area_px == 16
    assert result.qc_passed is True
    assert result.silhouette_path.is_file()
    assert result.confidence_path.is_file()
    assert json.loads((tmp_path / "silhouette_metrics.json").read_text(encoding="utf-8")) == {
        "area_px": 16,
        "bbox_area_px": 16,
        "qc_passed": True,
        "qc_range": [0.9, 1.1],
        "silhouette_bbox_ratio": 1.0,
    }


def test_s02_rejects_context_that_does_not_contain_the_person(tmp_path: Path) -> None:
    with np.testing.assert_raises_regex(SilhouetteError, "fully contained"):
        build_silhouette(
            np.ones((4, 4), dtype=np.float32),
            context_bbox_xyxy=(0, 0, 4, 4),
            person_bbox_xyxy=(0, 0, 5, 4),
            full_size=(6, 6),
            output_dir=tmp_path,
        )
