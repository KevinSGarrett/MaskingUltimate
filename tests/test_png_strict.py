"""Exercise the png_strict writer contract (doc 03 §1, MF-P0-08.03)."""

from __future__ import annotations

import numpy as np
import pytest

from maskfactory.io import png_strict


def test_self_test_all_pass():
    assert png_strict.self_test() is True


def test_binary_round_trip(tmp_path):
    a = np.zeros((16, 24), np.uint8)
    a[2:6, 3:9] = 255
    p = png_strict.write_binary_mask(tmp_path / "m.png", a, source_size=(24, 16))
    back = png_strict.read_mask(p)
    assert back.shape == (16, 24)
    assert set(np.unique(back).tolist()) <= {0, 255}
    assert np.array_equal(back, a)


def test_rejects_non_binary(tmp_path):
    with pytest.raises(png_strict.PngStrictError):
        png_strict.write_binary_mask(tmp_path / "bad.png", np.full((4, 4), 7, np.uint8))


def test_rejects_non_png(tmp_path):
    with pytest.raises(png_strict.PngStrictError):
        png_strict.write_binary_mask(tmp_path / "x.jpg", np.zeros((4, 4), np.uint8))


def test_rejects_dim_mismatch(tmp_path):
    with pytest.raises(png_strict.PngStrictError):
        png_strict.write_binary_mask(
            tmp_path / "d.png", np.zeros((4, 4), np.uint8), source_size=(10, 10)
        )
