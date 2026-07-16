import sqlite3
from pathlib import Path

from tools.backup_state import backup_database

ROOT = Path(__file__).resolve().parents[1]


def test_sqlite_backup_is_consistent_and_retains_seven(tmp_path: Path) -> None:
    source = tmp_path / "state.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE evidence(value TEXT)")
        connection.execute("INSERT INTO evidence VALUES ('durable')")
    destination = tmp_path / "backups"
    for index in range(9):
        output = backup_database(source, destination, retain=7)
        output.touch()
    backups = sorted(destination.glob("maskfactory_*.sqlite"))
    assert len(backups) <= 7
    with sqlite3.connect(backups[-1]) as connection:
        assert connection.execute("SELECT value FROM evidence").fetchone()[0] == "durable"
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_nightly_script_orders_b5_before_mirrors_and_wsl_integrity_sample() -> None:
    text = (ROOT / "tools" / "nightly_backup.ps1").read_text(encoding="utf-8")
    assert text.index("backup_state.py") < text.index("Invoke-RobocopyMirror (Join-Path")
    assert "--retain 7" in text
    assert text.count("Invoke-RobocopyMirror (Join-Path") == 3
    assert "wsl.exe -d Ubuntu-22.04" in text
    assert "verify-package --root data/packages --sample 10" in text
    assert "ontology-aware integrity sample" in text
    # A colon immediately after an unbraced variable name is a PowerShell
    # parser error (it is interpreted as a drive-qualified variable).
    assert "$LASTEXITCODE:" not in text
    assert "${LASTEXITCODE}:" in text


def test_task_registration_defines_nightly_and_weekly_limited_tasks() -> None:
    text = (ROOT / "tools" / "register_scheduled_tasks.ps1").read_text(encoding="utf-8")
    assert "MaskFactory_NightlyBackupIntegrity" in text
    assert 'New-ScheduledTaskTrigger -Daily -At "02:00"' in text
    assert "MaskFactory_WeeklyColdCopyReminder" in text
    assert 'New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "09:00"' in text
    assert "MaskFactory_NightlyManifestLint" in text
    assert 'New-ScheduledTaskTrigger -Daily -At "03:00"' in text
    assert "MaskFactory_WeeklyQaMining" in text
    assert "wscript.exe" in text
    assert "Invoke-HiddenPowerShell.vbs" in text
    assert "//B //NoLogo" in text
    assert "New-ScheduledTaskAction" in text
    assert '-WindowStyle", "Hidden' in text
    assert 'New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "10:00"' in text
    assert "Register-ScheduledTask" in text
    assert "New-ScheduledTaskPrincipal" in text
    assert "-RunLevel Limited" in text
    assert "-Principal $Principal" in text
    assert "-AllowStartIfOnBatteries" in text
    assert "-DontStopIfGoingOnBatteries" in text


def test_p4_nightly_and_weekly_jobs_cross_the_governed_wsl_boundary() -> None:
    nightly = (ROOT / "tools" / "nightly_qa.ps1").read_text(encoding="utf-8")
    weekly = (ROOT / "tools" / "weekly_qa.ps1").read_text(encoding="utf-8")
    for text in (nightly, weekly):
        assert "wsl.exe -d Ubuntu-22.04 -- bash -lc" in text
        assert "PYTHONPATH=src python -m maskfactory.cli" in text
        assert "configs/vlm.yaml" in text
        assert "$LASTEXITCODE -ne 0" in text
    assert "manifest-lint" in nightly
    assert "qa/reports/manifest_lint_$Date.json" in nightly
    assert "--state qa/reports/manifest_lint_state.json" in nightly
    assert "active-learning" in weekly
    assert "--report-date $Date" in weekly
    assert "autonomy build-audit-queue" in weekly
    assert "qa/autonomy/audit_queues/$Week.json" in weekly
