from __future__ import annotations

from tools.launch_runpod_visual_setup import REMOTE_LAUNCH


def test_setup_is_persistent_pinned_owned_and_bounded_to_two_models() -> None:
    assert "/workspace/maskfactory/runtime_artifacts/visual_critic_setup" in REMOTE_LAUNCH
    assert "/workspace/models/visual_critics" in REMOTE_LAUNCH
    assert "nohup bash" in REMOTE_LAUNCH
    assert "flock -n 9" in REMOTE_LAUNCH
    assert "Qwen/Qwen3.6-35B-A3B-FP8" in REMOTE_LAUNCH
    assert "95a723d08a9490559dae23d0cff1d9466213d989" in REMOTE_LAUNCH
    assert "OpenGVLab/InternVL3_5-8B" in REMOTE_LAUNCH
    assert "9bb6a56ad9cc69db95e2d4eeb15a52bbcac4ef79" in REMOTE_LAUNCH
    assert "Qwen3.5-122B" not in REMOTE_LAUNCH
    assert "Qwen3.5-397B" not in REMOTE_LAUNCH
    assert "241B" not in REMOTE_LAUNCH


def test_setup_never_embeds_credentials_or_public_endpoint() -> None:
    assert "RUNPOD_API_KEY" not in REMOTE_LAUNCH
    assert "Authorization" not in REMOTE_LAUNCH
    assert "publicIp" not in REMOTE_LAUNCH
