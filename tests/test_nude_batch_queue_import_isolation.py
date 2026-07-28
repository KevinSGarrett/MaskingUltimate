from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_basic_queue_recovery_imports_without_optional_stage_dependencies(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    script = textwrap.dedent(
        """
        import sys
        from pathlib import Path

        from maskfactory.nude_batch_queue import NudeBatchQueue

        queue = NudeBatchQueue(Path(sys.argv[1]))
        descriptor = {
            "platform": "runpod",
            "path": "runpod/import-isolation.0001.json",
            "lane": "polygon_external_supervision",
            "self_sha256": "a" * 64,
            "sample_count": 1,
        }
        assert queue.seed([descriptor], platform="runpod")["inserted"] == 1
        lease = queue.claim(platform="runpod", owner="import-isolation")
        assert lease is not None
        queue.heartbeat(
            platform="runpod",
            shard_path=lease["shard_path"],
            lease_token=lease["lease_token"],
        )
        try:
            queue.mark_submitted_unknown(
                platform="runpod",
                shard_path=lease["shard_path"],
                lease_token=lease["lease_token"],
                submission_id="",
            )
        except ValueError:
            pass
        else:
            raise AssertionError("blank submission ID was accepted")
        queue.release(
            platform="runpod",
            shard_path=lease["shard_path"],
            lease_token=lease["lease_token"],
            reason="import_isolation_verified",
        )
        assert queue.summary(platform="runpod")["states"] == {"queued": 1}
        print("QUEUE_IMPORT_ISOLATION_PASS")
        """
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [sys.executable, "-S", "-c", script, str(tmp_path / "queue.sqlite")],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "QUEUE_IMPORT_ISOLATION_PASS"
