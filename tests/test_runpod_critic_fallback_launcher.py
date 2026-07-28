from __future__ import annotations

from tools.launch_runpod_critic_fallback import REMOTE_LAUNCH


def test_fallback_is_exact_materially_different_private_and_restart_aware() -> None:
    assert "Qwen/Qwen3.6-27B-FP8" in REMOTE_LAUNCH
    assert "e89b16ebf1988b3d6befa7de50abc2d76f26eb09" in REMOTE_LAUNCH
    assert "for run in 1 2" in REMOTE_LAUNCH
    assert "--host 127.0.0.1" in REMOTE_LAUNCH
    assert "--max-model-len 8192" in REMOTE_LAUNCH
    assert "--limit-mm-per-prompt" in REMOTE_LAUNCH
    assert "qwen3_6_35b_a3b_fp8" in REMOTE_LAUNCH
    assert "Qwen/Qwen3.6-35B-A3B-FP8" not in REMOTE_LAUNCH


def test_fallback_is_owned_persistent_and_contains_no_credentials() -> None:
    assert "/workspace/maskfactory/runtime_artifacts/visual_critic_qwen27_fallback" in REMOTE_LAUNCH
    assert "nohup bash" in REMOTE_LAUNCH
    assert "flock -n 9" in REMOTE_LAUNCH
    assert "RUNPOD_API_KEY" not in REMOTE_LAUNCH
    assert "Authorization" not in REMOTE_LAUNCH
