"""Race-safe isolated commit of serve:cu128 daemon-abort seal only."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
MSG = ROOT / "runtime_artifacts" / "_commit_msg_serve_cu128_daemon_abort_20260720.txt"
TMP_INDEX = ROOT / ".git" / "mf_serve_abort_tmp_index"
PATHS = [
    "Plan/OPS_LOG.md",
    "qa/live_verification/serve_cu128_daemon_abort_20260720T1510.json",
    "runtime_artifacts/_seal_serve_cu128_daemon_abort_20260720T1510.py",
    "runtime_artifacts/_append_ops_log_serve_cu128_daemon_abort_20260720.py",
    "runtime_artifacts/_commit_msg_serve_cu128_daemon_abort_20260720.txt",
    "runtime_artifacts/_isolated_commit_serve_cu128_daemon_abort_20260720.py",
    "runtime_artifacts/_serve_cu128_build_coordination_20260720.json",
]


def run(args, env=None, check=True):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=check, env=env)


def main() -> None:
    for attempt in range(1, 10):
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        run(["git", "read-tree", head], env=env)
        # OPS_LOG may have sibling appends; include current working-tree bytes.
        run(["git", "add", "--", *PATHS], env=env)
        tree = run(["git", "write-tree"], env=env).stdout.strip()
        commit = run(["git", "commit-tree", tree, "-p", head, "-F", str(MSG)]).stdout.strip()
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
            f"CAS lost to concurrent sibling commit (attempt {attempt}); "
            f"stderr={(cas.stderr or '').strip()!r}; retrying"
        )
        time.sleep(1.5)
    raise SystemExit("failed to land isolated commit after retries")


if __name__ == "__main__":
    main()
