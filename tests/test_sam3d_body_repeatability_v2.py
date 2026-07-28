from __future__ import annotations

import numpy as np
import pytest
from tools.run_sam3d_body_repeatability_v2 import (
    _evaluate_measured_repeats,
    _persist_measured_output,
)


def _output(offset: float = 0.0) -> dict[str, np.ndarray]:
    return {
        "bbox": np.asarray([10.0, 20.0, 110.0, 220.0], dtype=np.float32),
        "focal_length": np.asarray([1200.0], dtype=np.float32),
        "pred_vertices": np.asarray([[0.0 + offset, 0.0, 1.0], [0.5, 1.0, 1.5]]),
        "pred_keypoints_3d": np.asarray([[0.0, 0.0, 1.0], [0.5, 0.5, 1.5]]),
        "pred_keypoints_2d": np.asarray([[25.0, 40.0], [75.0, 160.0]]),
        "pred_cam_t": np.asarray([0.0, 0.0, 2.5]),
    }


def test_warmup_is_explicitly_excluded_from_two_measured_repeat_verdict() -> None:
    summary = _evaluate_measured_repeats(
        warmup=_output(offset=99.0), measured=(_output(), _output())
    )
    assert summary["deterministic"] is True
    assert summary["repeat_comparison"]["all_arrays_exact"] is True
    assert summary["warmup_geometry_sha256"] not in summary["measured_geometry_sha256_by_repeat"]


def test_v2_keeps_strict_byte_equality_without_numeric_tolerance() -> None:
    first = _output()
    second = _output()
    second["pred_vertices"] = second["pred_vertices"].copy()
    second["pred_vertices"][1, 2] += 1e-12
    summary = _evaluate_measured_repeats(warmup=_output(), measured=(first, second))
    assert summary["deterministic"] is False
    assert summary["repeat_comparison"]["arrays"]["pred_vertices"]["exact"] is False


def test_v2_persists_both_measured_outputs_before_a_mismatch_verdict(tmp_path) -> None:
    first_path = tmp_path / "measured_repeat_1.npz"
    second_path = tmp_path / "measured_repeat_2.npz"
    first = _output()
    second = _output(offset=0.5)
    first_record = _persist_measured_output(first, first_path)
    second_record = _persist_measured_output(second, second_path)
    summary = _evaluate_measured_repeats(warmup=_output(), measured=(first, second))
    assert first_path.is_file() and second_path.is_file()
    assert first_record["geometry_sha256"] != second_record["geometry_sha256"]
    assert summary["deterministic"] is False
    with np.load(first_path, allow_pickle=False) as loaded:
        assert np.array_equal(loaded["pred_vertices"], first["pred_vertices"])
    with pytest.raises(FileExistsError):
        _persist_measured_output(first, first_path)


def test_v2_rejects_any_measured_repeat_count_other_than_two() -> None:
    with pytest.raises(ValueError, match="exactly two measured repeats"):
        _evaluate_measured_repeats(warmup=_output(), measured=(_output(),))
