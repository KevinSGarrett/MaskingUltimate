import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
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
    check_registered_models,
    check_torch_cuda,
    check_wsl_roundtrip,
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


def test_default_style_doctor_short_circuits_repeated_wsl_failures() -> None:
    calls = []

    def wsl_check() -> CheckResult:
        calls.append("unexpected")
        raise AssertionError("WSL-dependent check must not run after failed preflight")

    def healthy() -> CheckResult:
        calls.append("healthy")
        return CheckResult("healthy", "PASS", "ok")

    torch = wsl_check
    torch.__name__ = "check_torch_cuda"
    models = lambda: wsl_check()  # noqa: E731 - distinct callable identity for the test
    models.__name__ = "check_registered_models"
    roundtrip = lambda: wsl_check()  # noqa: E731 - distinct callable identity for the test
    roundtrip.__name__ = "check_wsl_roundtrip"
    missing = SimpleNamespace(
        returncode=1,
        stdout="",
        stderr="There is no distribution with the supplied name. WSL_E_DISTRO_NOT_FOUND",
    )
    with (
        patch("maskfactory.doctor.subprocess.run", return_value=missing) as run,
        patch("maskfactory.doctor._windows_identity", return_value="kevin\\sandbox"),
    ):
        results = run_doctor(
            [torch, models, healthy, roundtrip],
            preflight_wsl=True,
        )

    assert run.call_count == 1
    assert calls == ["healthy"]
    assert [result.name for result in results] == [
        "torch_cuda",
        "registered_models",
        "healthy",
        "wsl_roundtrip",
    ]
    assert [result.status for result in results] == ["FAIL", "FAIL", "PASS", "FAIL"]
    assert "checkpoint hashes are not implicated" in results[1].hint


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


def test_wsl_identity_failure_is_readable_and_actionable(tmp_path: Path) -> None:
    missing = (
        "T\x00h\x00e\x00r\x00e\x00 \x00i\x00s\x00 \x00n\x00o\x00 \x00d\x00i\x00s\x00t\x00r\x00i\x00b\x00u\x00t\x00i\x00o\x00n\x00 "
        "\x00w\x00i\x00t\x00h\x00 \x00t\x00h\x00e\x00 \x00s\x00u\x00p\x00p\x00l\x00i\x00e\x00d\x00 \x00n\x00a\x00m\x00e\x00.\x00\n\x00"
        "E\x00r\x00r\x00o\x00r\x00 \x00c\x00o\x00d\x00e\x00:\x00 \x00W\x00S\x00L\x00_\x00E\x00_\x00D\x00I\x00S\x00T\x00R\x00O\x00_\x00N\x00O\x00T\x00_\x00F\x00O\x00U\x00N\x00D\x00"
    )
    process = SimpleNamespace(returncode=1, stdout="", stderr=missing)
    with (
        patch("maskfactory.doctor.subprocess.run", return_value=process),
        patch("maskfactory.doctor._wsl_path", return_value="/mnt/c/doctor-probe"),
        patch("maskfactory.doctor._windows_identity", return_value="kevin\\codexsandboxonline"),
    ):
        torch = check_torch_cuda()
        roundtrip = check_wsl_roundtrip()
    for result in (torch, roundtrip):
        assert result.status == "FAIL"
        assert "codexsandboxonline" in result.detail
        assert "WSL_E_DISTRO_NOT_FOUND" in result.detail
        assert "\x00" not in result.detail
        assert "owns the Ubuntu-22.04" in result.hint

    with (
        patch(
            "maskfactory.doctor.verify_registered_model_smokes",
            side_effect=RuntimeError(missing),
        ),
        patch("maskfactory.doctor._windows_identity", return_value="kevin\\codexsandboxonline"),
    ):
        models = check_registered_models()
    assert models.status == "FAIL"
    assert "checkpoint hashes are not implicated" in models.hint
