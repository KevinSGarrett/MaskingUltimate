"""Unit tests for the autonomous GPU sequencing helpers (pure logic only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import gpu_sequencer as seq  # noqa: E402

GPU_CSV = "NVIDIA GeForce RTX 5060 Laptop GPU, 8151 MiB, 6256 MiB, 1644 MiB, 41 %"
APPS_CSV = (
    "44008, C:\\Users\\kevin\\AppData\\Local\\Programs\\cursor\\Cursor.exe, [N/A]\n"
    "37000, C:\\Users\\kevin\\...\\python.exe main.py --port 8188, 5800 MiB"
)


def test_parse_smi_gpu_reads_memory_and_util() -> None:
    gpus = seq.parse_smi_gpu(GPU_CSV)
    assert len(gpus) == 1
    assert gpus[0].total_mib == 8151
    assert gpus[0].free_mib == 1644
    assert gpus[0].util_pct == 41


def test_parse_smi_apps_flags_foreign_comfyui_holder() -> None:
    apps = seq.parse_smi_apps(APPS_CSV, consumer="ollama-vlm")
    comfy = next(app for app in apps if app.pid == 37000)
    assert comfy.foreign is True
    assert comfy.used_mib == 5800
    cursor = next(app for app in apps if app.pid == 44008)
    assert cursor.used_mib is None


def test_decide_does_not_gate_on_foreign_process_or_vram_shortage(tmp_path: Path) -> None:
    snapshot = {
        "nvidia_smi_available": True,
        "gpus": [
            {"name": "rtx", "total_mib": 8151, "used_mib": 6256, "free_mib": 1644, "util_pct": 41}
        ],
        "compute_apps": [
            {
                "pid": 37000,
                "process_name": "python main.py --port 8188",
                "used_mib": 5800,
                "foreign": True,
            }
        ],
    }
    decision = seq.decide("ollama-vlm", snapshot, lock_path=tmp_path / "gpu.lock")
    assert decision.decision == "run_now"
    assert decision.foreign_holders


def test_decide_run_now_when_headroom_and_lock_absent(tmp_path: Path) -> None:
    snapshot = {
        "nvidia_smi_available": True,
        "gpus": [
            {"name": "rtx", "total_mib": 8151, "used_mib": 400, "free_mib": 7751, "util_pct": 3}
        ],
        "compute_apps": [],
    }
    decision = seq.decide("ollama-vlm", snapshot, lock_path=tmp_path / "gpu.lock")
    assert decision.decision == "run_now"


def test_decide_ignores_other_lock_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / "gpu.lock"
    import os

    lock_path.write_text(
        json.dumps({"pid": os.getpid(), "purpose": "nuclio-sam2", "token": "x"}), encoding="utf-8"
    )
    snapshot = {
        "nvidia_smi_available": True,
        "gpus": [
            {"name": "rtx", "total_mib": 8151, "used_mib": 400, "free_mib": 7751, "util_pct": 3}
        ],
        "compute_apps": [],
    }
    decision = seq.decide("ollama-vlm", snapshot, lock_path=lock_path)
    assert decision.decision == "run_now"


def test_decide_missing_telemetry_does_not_create_admission_gate(tmp_path: Path) -> None:
    snapshot = {"nvidia_smi_available": False, "gpus": [], "compute_apps": []}
    decision = seq.decide("pipeline", snapshot, lock_path=tmp_path / "gpu.lock")
    assert decision.decision == "run_now"


def test_reclaim_method_maps_consumers_to_recipes() -> None:
    assert seq.reclaim_method("ollama-vlm") == "none"
    assert seq.reclaim_method("ollama-text") == "none"
    assert seq.reclaim_method("nuclio-sam2") == "none"
    assert seq.reclaim_method("pipeline") == "none"
    assert seq.reclaim_method("comfyui") == "none"
    assert seq.reclaim_method("unknown") == "none"


def test_release_consumer_without_mechanism_is_no_mechanism() -> None:
    result = seq.release_consumer("comfyui")
    assert result.status == "disabled"
    assert result.freed_mib is None


def test_release_consumer_never_calls_reclaim_helpers(monkeypatch) -> None:
    monkeypatch.setattr(
        seq,
        "unload_ollama_model",
        lambda *a, **k: pytest.fail("must not unload a model"),
    )
    monkeypatch.setattr(
        seq,
        "restart_docker_container",
        lambda *a, **k: pytest.fail("must not restart a container"),
    )
    result = seq.release_consumer("ollama-vlm", settle_s=0)
    assert result.status == "disabled"
    assert result.method == "none"


def test_sequence_handoff_never_reclaims_or_waits(monkeypatch, tmp_path: Path) -> None:
    released: list[str] = []

    def fake_release(consumer, **kwargs):
        released.append(consumer)
        return seq.ReclaimResult(consumer=consumer, method="ollama_unload", target="m", status="ok")

    run_now_snapshot = {
        "probed_at": "now",
        "nvidia_smi_available": True,
        "gpus": [
            {"name": "rtx", "total_mib": 8151, "used_mib": 400, "free_mib": 7751, "util_pct": 3}
        ],
        "compute_apps": [],
    }
    monkeypatch.setattr(seq, "release_consumer", fake_release)
    monkeypatch.setattr(seq, "probe_gpu", lambda consumer="": run_now_snapshot)

    payload = seq.sequence_handoff("nuclio-sam2", lock_path=tmp_path / "gpu.lock", timeout_s=1)

    assert released == []
    assert payload["decision"]["decision"] == "run_now"
    assert payload["consumer"] == "nuclio-sam2"
