"""Private-index pathspec commit for finished climb3/4 + sibling evidence/tools.

Avoids shared index.lock fights. Does not touch contested OPS_LOG / needs_agent /
tracker mid-edit sibling WIP. No secrets.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRIVATE_INDEX = REPO / ".git" / "index.pathspec-bridge-climb"
BRANCH = "codex/maskfactory-runtime-implementation"
MSG = (
    "feat(bridge): climb3/4 isolated-consumer depth + sibling scaffold\n"
    "\n"
    "Deepen MF-P6-11.02/11.07 producer+isolated evidence (Mode A to 30 cases,\n"
    "failure-control) with sibling Main consumer scaffold/receipts. HARD blockers\n"
    "remain open; Wave64 Main untouched.\n"
)

PATHSPECS = [
    "tools/run_isolated_main_consumer_climb4.py",
    "tools/scaffold_sibling_main_consumer.py",
    "qa/live_verification/isolated_consumer_climb4_20260720T1506.json",
    "qa/live_verification/isolated_consumer_dod_climb3_20260720T0948.json",
    "qa/live_verification/sibling_main_consumer_scaffold_20260720.json",
    "qa/live_verification/data_junction_forced_c_backup_20260720T1504Z.json",
    "runtime_artifacts/_seal_isolated_consumer_climb4_20260720.py",
    "runtime_artifacts/_seal_sibling_and_climb3_20260720.py",
    "runtime_artifacts/_seal_data_junction_forced_c_backup_20260720.py",
    "runtime_artifacts/_commit_msg_isolated_consumer_climb4_20260720.txt",
    "runtime_artifacts/_commit_msg_isolated_climb3_sibling.txt",
    "runtime_artifacts/_isolated_commit_climb4_private_index_20260720.py",
    "runtime_artifacts/_pathspec_commit_bridge_climb_20260720.py",
    "runtime_artifacts/_patch_isolated_consumer_climb3_matrix_20260720.py",
    "runtime_artifacts/_apply_and_commit_climb3_20260720.py",
    "runtime_artifacts/_isolated_commit_climb3_sibling_20260720.py",
    "runtime_artifacts/main_consumer/isolated_consumer_climb4_run_evidence_20260720T1504.json",
    "runtime_artifacts/main_consumer/isolated_sibling_consumer_run_evidence_20260720T1506.json",
    "runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T0948.json",
    "runtime_artifacts/main_consumer/sibling_consumer_scaffold_run_evidence.json",
]

OPTIONAL = [
    "runtime_artifacts/_append_ops_log_isolated_consumer_climb4_20260720.py",
    "runtime_artifacts/_isolated_commit_climb4_20260720.py",
    "runtime_artifacts/_isolated_commit_climb4_worktree_20260720.py",
    "runtime_artifacts/_patch_needs_forced_c_backup_20260720.py",
    "runtime_artifacts/_scan_runs_status_20260720.py",
]


def run(cmd: list[str], *, private: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if private:
        env["GIT_INDEX_FILE"] = str(PRIVATE_INDEX)
    return subprocess.run(
        cmd, cwd=REPO, text=True, capture_output=True, check=False, env=env
    )


def needs_landing(path: str) -> bool:
    if run(["git", "cat-file", "-e", f"HEAD:{path}"]).returncode != 0:
        return True
    wt_hash = run(["git", "hash-object", str(REPO / path)]).stdout.strip()
    head_hash = run(["git", "rev-parse", f"HEAD:{path}"]).stdout.strip()
    return bool(wt_hash and head_hash and wt_hash != head_hash)


def build_commit(parent: str, to_add: list[str]) -> str:
    PRIVATE_INDEX.unlink(missing_ok=True)
    r = run(["git", "read-tree", parent], private=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    add = run(["git", "add", "-f", "--", *to_add], private=True)
    if add.returncode != 0:
        raise RuntimeError(add.stderr)
    names = run(["git", "diff", "--cached", "--name-only"], private=True).stdout.splitlines()
    if not names:
        raise RuntimeError("empty tree delta")
    print("private-index staged:")
    for n in names:
        print(" ", n)
    tree_oid = run(["git", "write-tree"], private=True).stdout.strip()
    commit = run(["git", "commit-tree", tree_oid, "-p", parent, "-m", MSG], private=True)
    if commit.returncode != 0:
        raise RuntimeError(commit.stderr)
    return commit.stdout.strip()


def main() -> int:
    missing = [p for p in PATHSPECS if not (REPO / p).exists()]
    if missing:
        print("missing required pathspecs:", *missing, sep="\n  ", file=sys.stderr)
        return 2

    paths = [p for p in PATHSPECS + OPTIONAL if (REPO / p).exists()]
    to_add = [p for p in paths if needs_landing(p)]
    if not to_add:
        print("nothing to commit; all pathspecs already on HEAD")
        return 0

    print("pathspecs to land:")
    for p in to_add:
        print(" ", p)

    parent = run(["git", "rev-parse", f"refs/heads/{BRANCH}"]).stdout.strip()
    print("parent", parent)

    try:
        commit_oid = build_commit(parent, to_add)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 3
    print("commit", commit_oid)

    for attempt in range(5):
        cur = run(["git", "rev-parse", f"refs/heads/{BRANCH}"]).stdout.strip()
        if cur != parent:
            print(f"race: {BRANCH} moved {parent} -> {cur}; rebuild")
            parent = cur
            try:
                commit_oid = build_commit(parent, to_add)
            except RuntimeError as exc:
                print(exc, file=sys.stderr)
                return 3
            print("rebuilt commit", commit_oid, "on", parent)

        upd = run(["git", "update-ref", f"refs/heads/{BRANCH}", commit_oid, parent])
        if upd.returncode == 0:
            print("updated", BRANCH, "->", commit_oid)
            break
        print(upd.stderr or "update-ref failed", file=sys.stderr)
        time.sleep(0.5)
        parent = run(["git", "rev-parse", f"refs/heads/{BRANCH}"]).stdout.strip()
    else:
        print("failed CAS update-ref after retries", file=sys.stderr)
        return 4

    PRIVATE_INDEX.unlink(missing_ok=True)
    print("BRANCH_HEAD", run(["git", "rev-parse", BRANCH]).stdout.strip())
    print("SHOW", run(["git", "log", "-1", "--oneline", BRANCH]).stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
