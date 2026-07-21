from __future__ import annotations

from tools.launch_runpod_critic_qualification import REMOTE_LAUNCH


def test_qualification_is_restart_aware_private_and_exactly_bounded() -> None:
    assert "internvl_run.py" in REMOTE_LAUNCH
    assert "qwen_client.py" in REMOTE_LAUNCH
    assert "for run in 1 2" in REMOTE_LAUNCH
    assert "--host 127.0.0.1" in REMOTE_LAUNCH
    assert "http://127.0.0.1:18001" in REMOTE_LAUNCH
    assert "--max-model-len 8192" in REMOTE_LAUNCH
    assert "--limit-mm-per-prompt" in REMOTE_LAUNCH
    assert "Qwen/Qwen3.6-35B-A3B-FP8" in REMOTE_LAUNCH
    assert "OpenGVLab/InternVL3_5-8B" in REMOTE_LAUNCH
    assert "Qwen3.5-122B" not in REMOTE_LAUNCH
    assert "Qwen3.5-397B" not in REMOTE_LAUNCH
    assert "241B" not in REMOTE_LAUNCH


def test_qualification_preserves_failures_and_contains_no_credentials() -> None:
    assert "stdout.log" in REMOTE_LAUNCH
    assert "stderr.log" in REMOTE_LAUNCH
    assert "qualification.lock" in REMOTE_LAUNCH
    assert "RUNPOD_API_KEY" not in REMOTE_LAUNCH
    assert "Authorization" not in REMOTE_LAUNCH
    assert "publicIp" not in REMOTE_LAUNCH
