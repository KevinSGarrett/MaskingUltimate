from __future__ import annotations

import numpy as np
import pytest
from tools.run_sam3d_body import _extract_one
from tools.run_sam3d_body import _geometry_sha256 as runner_geometry_sha256

from maskfactory.providers.sam3d_body import _geometry_sha256 as provider_geometry_sha256


def _output() -> dict[str, np.ndarray]:
    return {
        "bbox": np.asarray([10.0, 20.0, 110.0, 220.0], dtype=np.float32),
        "focal_length": np.asarray(1200.0, dtype=np.float32),
        "pred_vertices": np.asarray([[0.0, 0.0, 1.0], [0.5, 1.0, 1.5]]),
        "pred_keypoints_3d": np.asarray([[0.0, 0.0, 1.0], [0.5, 0.5, 1.5]]),
        "pred_keypoints_2d": np.asarray([[25.0, 40.0], [75.0, 160.0]]),
        "pred_cam_t": np.asarray([0.0, 0.0, 2.5]),
    }


def test_runner_and_parent_use_the_same_geometry_hash_contract() -> None:
    output = _output()
    arrays = {
        name: output[name]
        for name in (
            "pred_vertices",
            "pred_keypoints_3d",
            "pred_keypoints_2d",
            "pred_cam_t",
        )
    }
    assert runner_geometry_sha256(output) == provider_geometry_sha256(
        output["bbox"], output["focal_length"], arrays
    )


def test_runner_accepts_exact_single_person_geometry() -> None:
    output = _output()
    extracted = _extract_one([output], output["bbox"])
    assert set(extracted) == set(output)
    assert np.array_equal(extracted["pred_vertices"], output["pred_vertices"])


@pytest.mark.parametrize(
    ("outputs", "message"),
    [
        ([], "exactly one person"),
        ([_output(), _output()], "exactly one person"),
        ([{**_output(), "bbox": np.asarray([0, 0, 1, 1])}], "different person box"),
        ([{**_output(), "pred_vertices": np.asarray([[np.nan, 0, 1]])}], "non-finite"),
        ([{**_output(), "pred_vertices": None}], "non-numeric"),
    ],
)
def test_runner_rejects_ambiguous_or_invalid_geometry(outputs, message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        _extract_one(outputs, _output()["bbox"])
