from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

TOOL = (
    Path(__file__).parents[1]
    / "tools"
    / "run_visual_critic_protocol_v3_qwen3vl_control_screening.py"
)
SPEC = importlib.util.spec_from_file_location("qwen3vl_v3_launcher", TOOL)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launcher
SPEC.loader.exec_module(launcher)


def test_build_server_argv_preserves_retained_qwen3vl_runtime_contract(tmp_path: Path) -> None:
    argv = launcher.build_server_argv(tmp_path / "python", tmp_path / "model", 18003)

    assert argv[:4] == [
        str(tmp_path / "python"),
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
    ]
    assert argv[argv.index("--served-model-name") + 1] == "qwen3_vl_30b_a3b_instruct_fp8"
    assert argv[argv.index("--gpu-memory-utilization") + 1] == "0.92"
    assert argv[argv.index("--max-model-len") + 1] == "16384"
    assert argv[argv.index("--max-num-seqs") + 1] == "1"
    assert argv[argv.index("--limit-mm-per-prompt") + 1] == '{"image":3}'


def test_parse_compute_processes_is_fail_closed_on_unknown_rows() -> None:
    assert launcher.parse_compute_processes("pid\n2412\n") == (2412,)
    assert launcher.parse_compute_processes("No running processes found\n") == ()

    with pytest.raises(ValueError, match="unparseable"):
        launcher.parse_compute_processes("pid\nforeign-process\n")


def test_assert_local_admission_rejects_foreign_compute_process() -> None:
    snapshot = launcher.GpuSnapshot(
        name="NVIDIA RTX 6000 Ada Generation", total_mib=49140, compute_pids=(2412,)
    )

    with pytest.raises(RuntimeError, match="another compute process"):
        launcher.assert_local_admission(snapshot)


def test_verify_expected_hash_rejects_input_drift(tmp_path: Path) -> None:
    target = tmp_path / "input.json"
    target.write_text("sealed", encoding="utf-8")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()

    assert launcher.verify_expected_hash(target, expected, "input") == expected
    target.write_text("drifted", encoding="utf-8")
    with pytest.raises(RuntimeError, match="SHA-256 drift"):
        launcher.verify_expected_hash(target, expected, "input")
