from __future__ import annotations

from tools.launch_runpod_critic_protocol_retry import REMOTE_LAUNCH


def test_protocol_retry_is_materially_different_and_exactly_bounded() -> None:
    assert "response_format" in REMOTE_LAUNCH
    assert "json_schema" in REMOTE_LAUNCH
    assert "/no_think" in REMOTE_LAUNCH
    assert "--generation-config vllm" in REMOTE_LAUNCH
    assert "for run in 1 2" in REMOTE_LAUNCH
    assert "Qwen/Qwen3.6-27B-FP8" in REMOTE_LAUNCH
    assert "hf download" not in REMOTE_LAUNCH


def test_protocol_retry_is_private_owned_and_secret_free() -> None:
    assert "--host 127.0.0.1" in REMOTE_LAUNCH
    assert "http://127.0.0.1:18001" in REMOTE_LAUNCH
    assert "visual_critic_qwen27_protocol_retry" in REMOTE_LAUNCH
    assert "flock -n 9" in REMOTE_LAUNCH
    assert "RUNPOD_API_KEY" not in REMOTE_LAUNCH
    assert "Authorization" not in REMOTE_LAUNCH
