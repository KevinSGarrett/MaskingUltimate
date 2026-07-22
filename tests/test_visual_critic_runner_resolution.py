from __future__ import annotations

from PIL import Image
from tools.run_visual_critic_calibration import _dynamic_preprocess


def test_internvl_dynamic_preprocess_retains_high_resolution_mask_evidence() -> None:
    image = Image.new("RGB", (1200, 900), "black")
    tiles = _dynamic_preprocess(image, max_tiles=6, image_size=448)
    try:
        assert len(tiles) == 7
        assert all(tile.size == (448, 448) for tile in tiles)
        assert len(tiles) > 1
    finally:
        for tile in tiles:
            tile.close()


def test_internvl_dynamic_preprocess_is_deterministic_and_bounded() -> None:
    image = Image.new("RGB", (600, 1824), "white")
    first = _dynamic_preprocess(image, max_tiles=6, image_size=64)
    second = _dynamic_preprocess(image, max_tiles=6, image_size=64)
    try:
        assert 1 < len(first) <= 7
        assert [tile.tobytes() for tile in first] == [tile.tobytes() for tile in second]
    finally:
        for tile in first + second:
            tile.close()
