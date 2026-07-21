from __future__ import annotations

from tools.launch_runpod_critic_deterministic_retry import REMOTE_LAUNCH


def test_final_retry_freezes_every_response_field_and_prompt_hash() -> None:
    assert "visual_critic_qwen27_deterministic_retry" in REMOTE_LAUNCH
    assert "'const':'synthetic diagnostic panels'" in REMOTE_LAUNCH
    assert "set summary exactly to synthetic diagnostic panels" in REMOTE_LAUNCH
    assert "prompt='/no_think\\nReturn a JSON object" in REMOTE_LAUNCH
    assert "for run in 1 2" in REMOTE_LAUNCH


def test_final_retry_reuses_exact_model_without_download_or_credentials() -> None:
    assert "Qwen/Qwen3.6-27B-FP8" in REMOTE_LAUNCH
    assert "hf download" not in REMOTE_LAUNCH
    assert "--host 127.0.0.1" in REMOTE_LAUNCH
    assert "RUNPOD_API_KEY" not in REMOTE_LAUNCH
    assert "Authorization" not in REMOTE_LAUNCH
