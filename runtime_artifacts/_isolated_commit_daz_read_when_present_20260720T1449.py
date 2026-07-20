"""Race-safe isolated commit of DAZ read-when-present STATIC re-verify evidence."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
MSG = ROOT / "runtime_artifacts" / "_commit_msg_daz_read_when_present_20260720T1449.txt"
TMP_INDEX = ROOT / ".git" / "mf_daz_rw_tmp_index"
PATHS = [
    "Plan/OPS_LOG.md",
    "qa/live_verification/daz_stream_read_when_present_20260720T1449Z.json",
    "qa/live_verification/_gold_volume_daz_present_20260720T1449.json",
    "qa/live_verification/daz_coverage_planner_static_20260720.json",
    "runtime_artifacts/_seal_daz_stream_read_when_present_20260720T1449.py",
    "runtime_artifacts/_append_ops_log_daz_read_when_present_20260720T1449.py",
    "runtime_artifacts/_append_ops_log_daz_read_when_present_20260720T1449_final.py",
    "runtime_artifacts/_fix_ops_log_daz_rw_mojibake_20260720.py",
    "runtime_artifacts/_isolated_commit_daz_read_when_present_20260720T1449.py",
    "runtime_artifacts/_commit_msg_daz_read_when_present_20260720T1449.txt",
]


def run(args, env=None, check=True):
    return subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, check=check, env=env
    )


def main() -> None:
    missing = [p for p in PATHS if not (ROOT / p).exists()]
    if missing:
        raise SystemExit(f"missing_paths:{missing}")
    for attempt in range(1, 10):
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        run(["git", "read-tree", head], env=env)
        run(["git", "add", "--", *PATHS], env=env)
        tree = run(["git", "write-tree"], env=env).stdout.strip()
        commit = run(
            ["git", "commit-tree", tree, "-p", head, "-F", str(MSG)]
        ).stdout.strip()
        cas = run(
            ["git", "update-ref", f"refs/heads/{BRANCH}", commit, head],
            check=False,
        )
        if cas.returncode == 0:
            print(f"committed {commit} parent {head} (attempt {attempt})")
            if TMP_INDEX.exists():
                TMP_INDEX.unlink()
            return
        print(
            f"CAS lost to concurrent sibling commit (attempt {attempt}); retrying"
        )
        time.sleep(1.5)
    raise SystemExit("failed to land isolated commit after retries")


if __name__ == "__main__":
    main()
