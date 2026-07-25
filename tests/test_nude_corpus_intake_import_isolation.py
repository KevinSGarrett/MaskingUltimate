from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_metadata_intake_import_avoids_optional_pixel_dependencies() -> None:
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "from maskfactory.nude_corpus_intake import load_adopted_intake; print(load_adopted_intake.__name__)",
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "load_adopted_intake"
