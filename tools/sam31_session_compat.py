"""Fail-closed SAM 3.1 session startup across the frozen multiplex API boundary."""

from __future__ import annotations

import inspect
import time
import uuid
from typing import Any


def start_sam31_session(predictor: Any, *, resource_path: str) -> str:
    """Start one session while omitting only the known unsupported offload keyword.

    The frozen upstream ``Sam3BasePredictor.start_session`` always supplies
    ``offload_state_to_cpu``.  The SAM 3.1 multiplex model at the same frozen
    commit does not accept that keyword.  Keep the upstream source tree clean
    and reproduce its session bookkeeping after verifying the exact API shape.
    """

    init_state = predictor.model.init_state
    parameters = inspect.signature(init_state).parameters
    required = {"resource_path", "offload_video_to_cpu", "async_loading_frames"}
    if not required.issubset(parameters):
        raise RuntimeError("SAM 3.1 multiplex init_state API is unsupported")
    if "offload_state_to_cpu" in parameters:
        response = predictor.handle_request(
            {"type": "start_session", "resource_path": resource_path}
        )
        session_id = response.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError("SAM 3.1 predictor returned an invalid session ID")
        return session_id

    init_kwargs: dict[str, Any] = {
        "resource_path": resource_path,
        "offload_video_to_cpu": False,
        "async_loading_frames": bool(getattr(predictor, "async_loading_frames", False)),
    }
    if hasattr(predictor, "video_loader_type"):
        if "video_loader_type" not in parameters:
            raise RuntimeError("SAM 3.1 multiplex video loader API is unsupported")
        init_kwargs["video_loader_type"] = predictor.video_loader_type
    inference_state = init_state(**init_kwargs)
    if not isinstance(inference_state, dict):
        raise RuntimeError("SAM 3.1 multiplex init_state returned an invalid state")
    session_id = str(uuid.uuid4())
    now = time.time()
    predictor._all_inference_states[session_id] = {  # noqa: SLF001 - frozen API adapter
        "state": inference_state,
        "session_id": session_id,
        "start_time": now,
        "last_use_time": now,
    }
    return session_id


__all__ = ["start_sam31_session"]
