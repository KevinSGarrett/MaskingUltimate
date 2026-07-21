"""Race-safe isolated commit of tournament sample-set + sibling feed only."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
MSG = ROOT / "runtime_artifacts" / "_commit_msg_tournament_sample_set_20260720.txt"
TMP_INDEX = ROOT / ".git" / "mf_tournament_sample_tmp_index"
PATHS = [
    "Plan/OPS_LOG.md",
    "qa/live_verification/tournament_sample_set_ultimate_mw_20260720T1505.json",
    "qa/live_verification/tournament_sample_set_sibling_feed_20260720T1505.json",
    "qa/live_verification/tournament_sample_set_sibling_feed_latest.json",
    "runtime_artifacts/tournament_sample_set_sibling_feed_latest.json",
    "runtime_artifacts/_build_tournament_sample_set_20260720.py",
    "runtime_artifacts/_append_ops_log_tournament_sample_set_20260720.py",
    "runtime_artifacts/_commit_msg_tournament_sample_set_20260720.txt",
    "runtime_artifacts/_isolated_commit_tournament_sample_set_20260720.py",
]


def run(args, env=None, check=True):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=check, env=env)


def main() -> None:
    missing = [path for path in PATHS if not (ROOT / path).exists()]
    if missing:
        raise SystemExit(f"missing paths: {missing}")
    for attempt in range(1, 12):
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        run(["git", "read-tree", head], env=env)
        run(["git", "add", "--", *PATHS], env=env)
        tree = run(["git", "write-tree"], env=env).stdout.strip()
        commit = run(
            ["git", "commit-tree", tree, "-p", head, "-F", str(MSG)],
        ).stdout.strip()
        cas = run(
            ["git", "update-ref", f"refs/heads/{BRANCH}", commit, head],
            check=False,
        )
        if cas.returncode == 0:
            print(f"committed {commit} parent {head} (attempt {attempt})")
            run(["git", "checkout", "-f", "HEAD", "--", *PATHS], check=False)
            if TMP_INDEX.exists():
                TMP_INDEX.unlink()
            return
        print(
            f"CAS lost to concurrent sibling commit (attempt {attempt}); "
            f"stderr={cas.stderr.strip()!r}"
        )
        time.sleep(1.5)
    raise SystemExit("failed to land isolated commit after retries")


if __name__ == "__main__":
    main()
