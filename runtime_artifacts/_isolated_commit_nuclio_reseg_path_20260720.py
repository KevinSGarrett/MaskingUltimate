"""Race-safe isolated commit of ONLY the nuclio package re-seg path files."""

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
            # Move working tree HEAD view forward for this shell.
            run(["git", "checkout", BRANCH], check=False)
            push = run(["git", "push", "origin", BRANCH], check=False)
            print(push.stdout)
            print(push.stderr)
            print("push_rc", push.returncode)
            print("HEAD", run(["git", "rev-parse", "HEAD"]).stdout.strip())
            stream = run(["git", "status", "--short", "--", *PATHS])
            print("stream_status:\n" + stream.stdout)
            print("stream_clean", not any(line[:2].strip() for line in stream.stdout.splitlines()))
            return
        print(f"CAS lost (attempt {attempt}); retrying: {cas.stderr.strip()}")
        time.sleep(1.5)
    raise SystemExit("failed to land isolated commit after retries")


if __name__ == "__main__":
    main()
