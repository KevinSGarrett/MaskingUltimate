from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def test_work_cell_import_does_not_eagerly_import_scipy_adapter() -> None:
    command = (
        "import sys; "
        "import maskfactory.autonomy.work_cell_mission_builder; "
        "assert 'maskfactory.autonomy.adapters' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        env=_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_mission_preparation_help_is_import_isolated() -> None:
    result = subprocess.run(
        [sys.executable, "tools/prepare_runpod_autonomous_mission.py", "--help"],
        cwd=ROOT,
        env=_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--mission-id" in result.stdout
