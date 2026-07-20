"""Race-safe isolated commit+push of ONLY the nuclio package re-seg path files.

Uses a private GIT_INDEX_FILE and compare-and-swap against origin tip so parallel
agents cannot steal the shared index. Does not run `git checkout` (that was
racing working trees).
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
MSG = ROOT / "runtime_artifacts" / "_commit_msg_nuclio_reseg_path_20260720.txt"
TMP_INDEX = ROOT / ".git" / "mf_nuclio_reseg_tmp_index"
PATHS = [
    "src/maskfactory/providers/nuclio_sam2.py",
    "tools/repair_package_nuclio_sam2.py",
    "tests/test_nuclio_sam2_clicks.py",
    "qa/live_verification/package_nuclio_sam2_reseg_path_wired_20260720T1515.json",
    "runtime_artifacts/_seal_package_nuclio_reseg_path_20260720.py",
    "runtime_artifacts/_patch_visual_defect_policy_nuclio_20260720.py",
    "runtime_artifacts/_commit_nuclio_reseg_path_20260720.py",
    "runtime_artifacts/_commit_nuclio_reseg_retry_20260720.py",
    "runtime_artifacts/_isolated_commit_nuclio_reseg_path_20260720.py",
    "runtime_artifacts/_commit_msg_nuclio_reseg_path_20260720.txt",
]


def run(args, env=None, check=True):
    return subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, check=check, env=env
    )


def main() -> None:
    missing = [p for p in PATHS if not (ROOT / p).is_file()]
    if missing:
        raise SystemExit(f"missing paths: {missing}")

    for attempt in range(1, 16):
        fetch = run(["git", "fetch", "origin", BRANCH], check=False)
        if fetch.returncode != 0:
            print("fetch_warn", fetch.stderr.strip())
            time.sleep(2)
            continue
        parent = run(["git", "rev-parse", f"origin/{BRANCH}"]).stdout.strip()
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        run(["git", "read-tree", parent], env=env)
        run(["git", "add", "--", *PATHS], env=env)
        tree = run(["git", "write-tree"], env=env).stdout.strip()
        # Skip empty commit if tree identical to parent tree.
        parent_tree = run(["git", "rev-parse", f"{parent}^{{tree}}"]).stdout.strip()
        if tree == parent_tree:
            print(f"already_on_origin parent={parent} (attempt {attempt})")
            if TMP_INDEX.exists():
                TMP_INDEX.unlink()
            print("HEAD_origin", parent)
            return
        commit = run(
            ["git", "commit-tree", tree, "-p", parent, "-F", str(MSG)]
        ).stdout.strip()
        # Point local branch at our commit only if it still matches parent.
        cas = run(
            ["git", "update-ref", f"refs/heads/{BRANCH}", commit, parent],
            check=False,
        )
        if cas.returncode != 0:
            print(f"local CAS lost (attempt {attempt}): {cas.stderr.strip()}")
            time.sleep(1.5)
            continue
        push = run(
            ["git", "push", "origin", f"{commit}:refs/heads/{BRANCH}"],
            check=False,
        )
        if push.returncode == 0:
            print(f"pushed {commit} parent {parent} (attempt {attempt})")
            if TMP_INDEX.exists():
                TMP_INDEX.unlink()
            # Refresh remote-tracking ref.
            run(["git", "fetch", "origin", BRANCH], check=False)
            print("origin_HEAD", run(["git", "rev-parse", f"origin/{BRANCH}"]).stdout.strip())
            # Working tree may still show ?? until reset; report blob presence.
            for path in PATHS[:4]:
                show = run(["git", "cat-file", "-e", f"{commit}:{path}"], check=False)
                print(f"in_commit {path}={show.returncode == 0}")
            return
        print(f"push lost (attempt {attempt}): {push.stderr.strip()}")
        # Roll local branch back to parent so we do not leave a divergent tip.
        run(["git", "update-ref", f"refs/heads/{BRANCH}", parent], check=False)
        time.sleep(2)
    raise SystemExit("failed to land isolated commit+push after retries")


if __name__ == "__main__":
    main()
