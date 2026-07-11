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


def test_task_registration_defines_nightly_and_weekly_limited_tasks() -> None:
    text = (ROOT / "tools" / "register_scheduled_tasks.ps1").read_text(encoding="utf-8")
    assert "MaskFactory_NightlyBackupIntegrity" in text
    assert "/SC DAILY /ST 02:00 /RL LIMITED" in text
    assert "MaskFactory_WeeklyColdCopyReminder" in text
    assert "/SC WEEKLY /D MON /ST 09:00 /RL LIMITED" in text
