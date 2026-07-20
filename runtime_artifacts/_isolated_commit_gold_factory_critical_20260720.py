"""Race-safe isolated commit of Gold Factory critical status + remaining launcher."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
MSG = ROOT / "runtime_artifacts/_commit_msg_gold_factory_critical_20260720.txt"
TMP_INDEX = ROOT / ".git/mf_gold_factory_critical_tmp_index"
PATHS = [
    "qa/live_verification/gold_factory_critical_status_20260720T171840Z.json",
    "qa/live_verification/gold_factory_critical_status_latest.json",
    "runtime_artifacts/_run_tournament_remaining_locked_20260720.py",
    "runtime_artifacts/_seal_gold_factory_status_20260720T1717.py",
    "runtime_artifacts/_commit_msg_gold_factory_critical_20260720.txt",
    "runtime_artifacts/_isolated_commit_gold_factory_critical_20260720.py",
]


def run(args: list[str], env: dict[str, str] | None = None, check: bool = True):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=check, env=env)


def main() -> None:
    missing = [p for p in PATHS if not (ROOT / p).is_file()]
    if missing:
        raise SystemExit(f"missing paths: {missing}")
    for attempt in range(1, 20):
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
            print(f"committed {commit[:12]} parent {head[:12]} (attempt {attempt})")
            if TMP_INDEX.exists():
                TMP_INDEX.unlink()
            return
        print(f"CAS lost (attempt {attempt}); stderr={cas.stderr.strip()}")
        time.sleep(1.2)
    raise SystemExit("failed to CAS-update ref after retries")


if __name__ == "__main__":
    main()
