from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "integrations"
    / "daz"
    / "acquisition"
    / "capacity_guard.py"
)
SPEC = importlib.util.spec_from_file_location("daz_acquisition_capacity_guard", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_capacity_boundaries_are_exact() -> None:
    gib = MODULE.GIB
    emergency = MODULE.evaluate_capacity(59 * gib)
    hard = MODULE.evaluate_capacity(99 * gib)
    soft = MODULE.evaluate_capacity(100 * gib)
    healthy = MODULE.evaluate_capacity(150 * gib)
    assert (emergency.state, emergency.new_work_allowed, emergency.active_job_allowed) == (
        "emergency",
        False,
        False,
    )
    assert (hard.state, hard.new_work_allowed, hard.active_job_allowed) == (
        "hard",
        False,
        False,
    )
    assert (soft.state, soft.new_work_allowed, soft.active_job_allowed) == (
        "soft",
        False,
        True,
    )
    assert (healthy.state, healthy.new_work_allowed, healthy.active_job_allowed) == (
        "healthy",
        True,
        True,
    )


@pytest.mark.parametrize(
    "free_bytes,operation,allowed",
    [
        (151 * MODULE.GIB, "new-work", True),
        (149 * MODULE.GIB, "new-work", False),
        (101 * MODULE.GIB, "active-job", True),
        (99 * MODULE.GIB, "active-job", False),
    ],
)
def test_cli_contract(
    tmp_path: Path,
    free_bytes: int,
    operation: str,
    allowed: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "capacity_guard.py",
            "--root",
            str(tmp_path),
            "--operation",
            operation,
            "--free-bytes",
            str(free_bytes),
        ],
    )
    exit_code = MODULE.main()
    assert exit_code == (0 if allowed else MODULE.CAPACITY_REFUSED_EXIT)
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == operation
    assert (
        payload["new_work_allowed" if operation == "new-work" else "active_job_allowed"] is allowed
    )


def test_invalid_thresholds_fail_closed() -> None:
    with pytest.raises(MODULE.CapacityPolicyError):
        MODULE.evaluate_capacity(
            200 * MODULE.GIB,
            soft_floor_gib=100,
            hard_floor_gib=150,
            emergency_floor_gib=60,
        )


def test_source_and_live_guard_bytes_are_identical() -> None:
    live = Path(r"F:\DAZ\00_control\render_state_ingest\capacity_guard.py")
    if not live.is_file():
        pytest.skip("live F-drive acquisition guard is not mounted")
    assert SOURCE.read_bytes() == live.read_bytes()


def test_live_worker_and_launchers_are_capacity_guarded() -> None:
    root = Path(r"F:\DAZ\00_control\render_state_ingest")
    if not root.is_dir():
        pytest.skip("live F-drive acquisition worker is not mounted")
    worker = (root / "rs_ingest.py").read_text(encoding="utf-8")
    config = (root / "config.yaml").read_text(encoding="utf-8")
    start_pool = (root / "start_pool_background.ps1").read_text(encoding="utf-8")
    scale_pool = (root / "scale_pool_background.ps1").read_text(encoding="utf-8")
    start_single = (root / "start_background.ps1").read_text(encoding="utf-8")
    assert 'VERSION = "0.3.7"' in worker
    assert "ensure_new_work_allowed(paths.daz_root" in worker
    assert worker.count("ensure_active_job_allowed(paths.daz_root") >= 3
    assert '"capacity_hold"' in worker
    assert "storage_soft_floor_gib: 150" in config
    assert "storage_hard_floor_gib: 100" in config
    assert "storage_emergency_floor_gib: 60" in config
    for launcher in (start_pool, scale_pool, start_single):
        assert "capacity_guard.py" in launcher
        assert "--operation new-work" in launcher
