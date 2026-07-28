from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_queue_summary_cli_avoids_optional_intake_dependency(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(root / "tools" / "manage_nude_batch_queue.py"),
            "--queue",
            str(tmp_path / "queue.sqlite"),
            "--platform",
            "runpod",
            "summary",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "summary": {
            "checkpointed_records": 0,
            "outcomes": {},
            "platform": "runpod",
            "records": 0,
            "shards": 0,
            "stage_evidence": {},
            "states": {},
        }
    }
