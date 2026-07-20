"""Normalize accidental CRLF introduced by B1 seal commit back to LF (repo norm)."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
TMP_INDEX = ROOT / ".git" / "mf_b1_lf_tmp_index"
MSG = ROOT / "runtime_artifacts" / "_commit_msg_b1_restore_lf_fix_20260720.txt"
FILES = [
    "Plan/OPS_LOG.md",
    "Plan/Tracker/tracker.json",
    "Plan/Tracker/CHANGELOG.jsonl",
    "Plan/Tracker/phases/P1.md",
    "qa/live_verification/needs_agent_actions_20260720.json",
    "qa/live_verification/b1_restore_drill_local_c_backup_20260720T1517Z.json",
    "runtime_artifacts/_commit_msg_b1_restore_drill_local_20260720.txt",
    "runtime_artifacts/_isolated_commit_b1_restore_drill_20260720.py",
    "runtime_artifacts/_seal_b1_restore_drill_local_c_backup_20260720.py",
    "runtime_artifacts/_isolated_commit_b1_restore_lf_fix_20260720.py",
    "runtime_artifacts/_commit_msg_b1_restore_lf_fix_20260720.txt",
]


def run(args, env=None, check=True, input_bytes=None):
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        check=check,
        env=env,
        input=input_bytes,
    )


def main() -> None:
    MSG.write_text(
        "fix(ops): normalize LF after B1 restore drill seal commit\n",
        encoding="utf-8",
        newline="\n",
    )
    for attempt in range(1, 12):
        head = run(["git", "rev-parse", "HEAD"]).stdout.decode().strip()
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        run(["git", "read-tree", head], env=env)

        changed = False
        for rel in FILES:
            raw = run(["git", "show", f"{head}:{rel}"], check=False)
            if raw.returncode != 0:
                # new helper may only exist on WT for this fix commit
                abs_path = ROOT / rel
                if not abs_path.is_file():
                    continue
                data = abs_path.read_bytes()
            else:
                data = raw.stdout
            if b"\r\n" in data:
                data = data.replace(b"\r\n", b"\n")
                changed = True
            elif raw.returncode != 0:
                changed = True
            else:
                # still stage identical LF content / ensure helper present
                pass
            blob = run(["git", "hash-object", "-w", "--stdin"], env=env, input_bytes=data).stdout.decode().strip()
            run(
                ["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}"],
                env=env,
            )

        if not changed:
            print(f"already LF-clean on {head}")
            if TMP_INDEX.exists():
                TMP_INDEX.unlink()
            return

        tree = run(["git", "write-tree"], env=env).stdout.decode().strip()
        commit = (
            run(["git", "commit-tree", tree, "-p", head, "-F", str(MSG)])
            .stdout.decode()
            .strip()
        )
        cas = run(
            ["git", "update-ref", f"refs/heads/{BRANCH}", commit, head],
            check=False,
        )
        if cas.returncode == 0:
            print(f"committed {commit} parent {head} (attempt {attempt})")
            if TMP_INDEX.exists():
                TMP_INDEX.unlink()
            run(["git", "read-tree", "HEAD"], check=False)
            return
        print(f"CAS lost (attempt {attempt}); retrying")
        time.sleep(1.5)
    raise SystemExit("failed LF normalize commit")


if __name__ == "__main__":
    main()
