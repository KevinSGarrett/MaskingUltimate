from __future__ import annotations

from tools.recover_runpod_critic_qualification import REMOTE_RECOVERY


def test_recovery_is_exact_scope_and_preserves_failure_state() -> None:
    assert "qwen3_6_35b_a3b_fp8" in REMOTE_RECOVERY
    assert "pgrep -f" in REMOTE_RECOVERY
    assert "kill -TERM" in REMOTE_RECOVERY
    assert "kill -KILL" in REMOTE_RECOVERY
    assert "vllm_weight_load_out_of_memory" in REMOTE_RECOVERY
    assert "state.json" in REMOTE_RECOVERY
    assert "pkill" not in REMOTE_RECOVERY


def test_recovery_never_targets_other_models_or_embeds_credentials() -> None:
    assert "internvl3_5_8b_bf16" not in REMOTE_RECOVERY
    assert "Qwen3.5" not in REMOTE_RECOVERY
    assert "RUNPOD_API_KEY" not in REMOTE_RECOVERY
    assert "Authorization" not in REMOTE_RECOVERY
