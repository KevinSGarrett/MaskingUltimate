from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from maskfactory.vlm.canonical_polygon_panels import (
    PANEL_NAMES,
    render_candidate_panels,
)


def test_renderer_writes_complete_exact_source_mask_overlay_contour_evidence(
    tmp_path: Path,
) -> None:
    source = np.zeros((64, 80, 3), dtype=np.uint8)
    source[:, :, 1] = 80
    mask = np.zeros((64, 80), dtype=bool)
    mask[20:40, 30:50] = True
    result = render_candidate_panels(source, mask, tmp_path)
    assert set(result["panel_files"]) == set(PANEL_NAMES)
    assert set(result["panel_sha256s"]) == set(PANEL_NAMES)
    assert len(result["panel_set_sha256"]) == 64
    for name, relative in result["panel_files"].items():
        path = tmp_path / relative
        assert path.is_file(), name
        with Image.open(path) as opened:
            assert opened.width > 0 and opened.height > 0


def test_renderer_preserves_binary_mask_geometry_and_values(tmp_path: Path) -> None:
    source = np.zeros((32, 48, 3), dtype=np.uint8)
    mask = np.zeros((32, 48), dtype=bool)
    mask[4:12, 5:17] = True
    result = render_candidate_panels(source, mask, tmp_path)
    with Image.open(tmp_path / result["panel_files"]["binary_mask"]) as opened:
        value = np.asarray(opened.convert("L"))
    assert value.shape == mask.shape
    assert set(np.unique(value)) == {0, 255}
    assert np.array_equal(value > 0, mask)
