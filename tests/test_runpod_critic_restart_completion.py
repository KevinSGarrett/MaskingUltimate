from __future__ import annotations

from tools.launch_runpod_critic_restart_completion import REMOTE_LAUNCH


def test_restart_completion_waits_for_observed_gpu_release_and_runs_only_second_process() -> None:
    assert "visual_critic_qwen27_restart_completion" in REMOTE_LAUNCH
    assert "memory.used" in REMOTE_LAUNCH
    assert 'if [ "$used" -le 2048 ]' in REMOTE_LAUNCH
    assert "for run in 2; do" in REMOTE_LAUNCH
    assert "for run in 1 2; do" not in REMOTE_LAUNCH


def test_restart_completion_reuses_exact_first_run_and_constant_schema() -> None:
    assert "visual_critic_qwen27_deterministic_retry/run1.json" in REMOTE_LAUNCH
    assert "'const':'synthetic diagnostic panels'" in REMOTE_LAUNCH
    assert "Qwen/Qwen3.6-27B-FP8" in REMOTE_LAUNCH
    assert "hf download" not in REMOTE_LAUNCH
    assert "RUNPOD_API_KEY" not in REMOTE_LAUNCH
