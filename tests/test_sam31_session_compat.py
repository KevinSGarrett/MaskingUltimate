from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from tools.sam31_session_compat import start_sam31_session
from tools.smoke_sam31_multiplex_wsl import _extract


class _MultiplexModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def init_state(
        self,
        resource_path: str,
        offload_video_to_cpu: bool = False,
        async_loading_frames: bool = False,
    ) -> dict[str, object]:
        call = {
            "resource_path": resource_path,
            "offload_video_to_cpu": offload_video_to_cpu,
            "async_loading_frames": async_loading_frames,
        }
        self.calls.append(call)
        return call


def test_multiplex_session_omits_only_unsupported_state_offload_keyword() -> None:
    model = _MultiplexModel()
    predictor = SimpleNamespace(
        model=model,
        async_loading_frames=False,
        _all_inference_states={},
    )

    session_id = start_sam31_session(predictor, resource_path="/frames")

    assert session_id in predictor._all_inference_states
    assert model.calls == [
        {
            "resource_path": "/frames",
            "offload_video_to_cpu": False,
            "async_loading_frames": False,
        }
    ]
    assert predictor._all_inference_states[session_id]["state"] == model.calls[0]


def test_compatible_base_predictor_path_remains_authoritative() -> None:
    class CompatibleModel:
        def init_state(
            self,
            resource_path: str,
            offload_video_to_cpu: bool = False,
            offload_state_to_cpu: bool = False,
            async_loading_frames: bool = False,
        ) -> dict[str, object]:
            raise AssertionError("handle_request owns the compatible path")

    class Predictor:
        model = CompatibleModel()

        @staticmethod
        def handle_request(request: dict[str, object]) -> dict[str, str]:
            assert request == {"type": "start_session", "resource_path": "/frames"}
            return {"session_id": "upstream-session"}

    assert start_sam31_session(Predictor(), resource_path="/frames") == "upstream-session"


def test_unknown_multiplex_api_fails_closed() -> None:
    model = SimpleNamespace(init_state=lambda resource_path: {})
    predictor = SimpleNamespace(model=model, _all_inference_states={})

    with pytest.raises(RuntimeError, match="API is unsupported"):
        start_sam31_session(predictor, resource_path="/frames")


def test_invalid_live_output_reports_bounded_geometry_evidence() -> None:
    outputs = {
        "out_binary_masks": np.zeros((0, 10, 12), dtype=bool),
        "out_obj_ids": np.zeros((0,), dtype=np.int64),
        "out_probs": np.zeros((0,), dtype=np.float32),
        "out_boxes_xywh": np.zeros((0, 4), dtype=np.float32),
    }

    with pytest.raises(RuntimeError, match=r'"masks".*"shape":\[0,10,12\]'):
        _extract(outputs)


def test_text_discovery_accepts_multiple_unique_nonempty_masks() -> None:
    masks = np.zeros((2, 10, 12), dtype=bool)
    masks[0, 1:4, 2:5] = True
    masks[1, 5:9, 7:11] = True
    outputs = {
        "out_binary_masks": masks,
        "out_obj_ids": np.asarray([2, 7], dtype=np.int64),
        "out_probs": np.asarray([0.91, 0.87], dtype=np.float32),
        "out_boxes_xywh": np.asarray(
            [[2.0, 1.0, 3.0, 3.0], [7.0, 5.0, 4.0, 4.0]], dtype=np.float32
        ),
    }

    arrays = _extract(outputs)

    assert arrays["masks"].shape == (2, 10, 12)
    assert arrays["object_ids"].tolist() == [2, 7]
