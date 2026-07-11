import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.doctor import (
    CVAT_BASE_URL,
    DEFAULT_CHECKS,
    CheckResult,
    check_cvat_project,
    check_disk_free,
    check_gpu_lock,
    run_doctor,
)


def test_cvat_uses_traefik_canonical_host() -> None:
    assert CVAT_BASE_URL == "http://localhost:8080"


def test_default_doctor_battery_covers_every_p0_requirement() -> None:
    assert [check.__name__ for check in DEFAULT_CHECKS] == [
        "check_torch_cuda",
        "check_registered_models",
        "check_cvat_api",
        "check_cvat_project",
        "check_nuclio_interactor",
        "check_ollama_image",
        "check_disk_free",
        "check_wsl_roundtrip",
        "check_png_strict",
        "check_sqlite",
        "check_gpu_lock",
    ]


def test_run_doctor_preserves_statuses_and_converts_unexpected_exceptions() -> None:
    def passing() -> CheckResult:
        return CheckResult("passing", "PASS", "ok")

    def crashing() -> CheckResult:
        raise RuntimeError("boom")

    results = run_doctor([passing, crashing])

    assert results[0] == CheckResult("passing", "PASS", "ok")
    assert results[1].name == "crashing"
    assert results[1].status == "FAIL"
    assert "boom" in results[1].detail
    assert results[1].hint


def test_disk_thresholds_match_operations_runbook(tmp_path: Path) -> None:
    gib = 1024**3
    cases = [(250, "PASS"), (175, "WARN"), (100, "WARN"), (74, "FAIL")]
    for free, expected in cases:
        with patch("maskfactory.doctor.shutil.disk_usage") as disk_usage:
            disk_usage.return_value = type("Usage", (), {"free": free * gib})()
            assert check_disk_free(tmp_path).status == expected


def test_gpu_lock_distinguishes_absent_active_and_stale(tmp_path: Path) -> None:
    lock = tmp_path / "gpu.lock"
    assert check_gpu_lock(lock).status == "PASS"

    lock.write_text(json.dumps({"pid": 1234}), encoding="utf-8")
    with patch("maskfactory.gpu.pid_exists", return_value=True):
        assert check_gpu_lock(lock).status == "WARN"

    old = time.time() - 8000
    os.utime(lock, (old, old))
    with patch("maskfactory.gpu.pid_exists", return_value=False):
        result = check_gpu_lock(lock)
    assert result.status == "FAIL"
    assert "remove runs/gpu.lock" in result.hint


def test_cvat_project_skip_is_only_allowed_before_p1() -> None:
    with (
        patch("maskfactory.doctor._env_values", return_value={}),
        patch("maskfactory.doctor._p1_started", return_value=False),
    ):
        assert check_cvat_project().status == "SKIP"
    with (
        patch("maskfactory.doctor._env_values", return_value={}),
        patch("maskfactory.doctor._p1_started", return_value=True),
    ):
        assert check_cvat_project().status == "FAIL"


def test_doctor_cli_prints_hints_and_exits_nonzero_on_fail() -> None:
    results = [
        CheckResult("healthy", "PASS", "ok"),
        CheckResult("broken", "FAIL", "not ok", "repair it"),
    ]
    with patch("maskfactory.cli.run_doctor", return_value=results):
        invocation = CliRunner().invoke(main, ["doctor"])

    assert invocation.exit_code == 1
    assert "[PASS] healthy: ok" in invocation.output
    assert "[FAIL] broken: not ok" in invocation.output
    assert "FIX: repair it" in invocation.output
    assert "FAIL=1" in invocation.output


def test_doctor_cli_exits_zero_without_failures() -> None:
    results = [
        CheckResult("healthy", "PASS", "ok"),
        CheckResult("capacity", "WARN", "low"),
        CheckResult("project", "SKIP", "pre-P1"),
    ]
    with patch("maskfactory.cli.run_doctor", return_value=results):
        invocation = CliRunner().invoke(main, ["doctor"])

    assert invocation.exit_code == 0
    assert "PASS=1 WARN=1 SKIP=1 FAIL=0" in invocation.output
