import json
from pathlib import Path


def test_live_disk_review_matches_runbook_thresholds() -> None:
    report = json.loads(Path("qa/live_verification/disk_headroom_2026-07-12.json").read_text())
    assert report["thresholds_gib"] == {
        "target": 200,
        "warning": 150,
        "block_ingest": 75,
    }
    assert 75 <= report["free_gib"] < 150
    assert report["doctor_status"] == "WARN"
    assert report["ingest_blocked"] is False
    assert report["junction_move_required"] is True
    assert report["larger_target_available"] is False


def test_junction_script_has_apply_rollback_and_no_auto_cleanup() -> None:
    script = Path("tools/move_data_to_junction.ps1").read_text(encoding="utf-8")
    assert "ValidateSet('data', 'datasets', 'runs')" in script
    assert "SourceBytes + 20GB" in script
    assert "$LASTEXITCODE -ge 8" in script
    assert "ItemType Junction" in script
    assert "verify-package --root $Source --sample 25" in script
    assert "reindex --dry-run" in script and "maskfactory doctor" in script
    assert "Move-Item -LiteralPath $Backup -Destination $Source" in script
    assert "backup directory is never automatically deleted" in script
    assert "Remove-Item -LiteralPath $Backup" not in script
