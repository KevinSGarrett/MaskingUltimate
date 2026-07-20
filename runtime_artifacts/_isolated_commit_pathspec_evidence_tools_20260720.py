"""Private-index pathspec commit for coherent evidence/tools (immune to index races)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRIVATE_INDEX = REPO / ".git" / "index.pathspec_evidence_tools"
MSG = REPO / "runtime_artifacts" / "_commit_msg_pathspec_evidence_tools_20260720.txt"

PATHSPECS = [
    "tools/scaffold_sibling_main_consumer.py",
    "tools/run_measured_champions_path.py",
    "tools/assemble_autonomous_verification_corpus.py",
    "tools/run_isolated_main_consumer.py",
    "tools/build_autonomous_gold_admission.py",
    "tools/build_production_audit_queue.py",
    "tools/mark_benchmarked_candidate.py",
    "tools/weekly_qa.ps1",
    "src/maskfactory/autonomy/corpus.py",
    "src/maskfactory/autonomy/production_audit.py",
    "src/maskfactory/models/benchmark.py",
    "src/maskfactory/cli.py",
    "src/maskfactory/stages/production.py",
    "src/maskfactory/vlm/production.py",
    "tests/test_measured_champions_path_glue.py",
    "qa/live_verification/isolated_consumer_dod_climb3_20260720T0948.json",
    "qa/live_verification/sibling_main_consumer_scaffold_20260720.json",
    "qa/live_verification/measured_champions_path_production_20260720T1517.json",
    "qa/live_verification/data_junction_forced_c_backup_20260720T1504Z.json",
    "runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T0948.json",
    "runtime_artifacts/main_consumer/sibling_consumer_scaffold_run_evidence.json",
    "runtime_artifacts/_apply_and_commit_climb3_20260720.py",
    "runtime_artifacts/_apply_measured_champions_path_glue.py",
    "runtime_artifacts/_commit_measured_champions_path_glue.py",
    "runtime_artifacts/_commit_msg_isolated_climb3_sibling.txt",
    "runtime_artifacts/_commit_msg_sibling_consumer_scaffold.txt",
    "runtime_artifacts/_isolated_commit_climb3_sibling_20260720.py",
    "runtime_artifacts/_isolated_commit_forced_c_backup_20260720.py",
    "runtime_artifacts/_isolated_commit_pathspec_evidence_tools_20260720.py",
    "runtime_artifacts/_patch_isolated_consumer_climb3_matrix_20260720.py",
    "runtime_artifacts/_patch_needs_forced_c_backup_20260720.py",
    "runtime_artifacts/_seal_data_junction_forced_c_backup_20260720.py",
    "runtime_artifacts/_seal_sibling_and_climb3_20260720.py",
    "runtime_artifacts/_verify_measured_glue.py",
    "runtime_artifacts/_commit_msg_pathspec_evidence_tools_20260720.txt",
]


def env() -> dict[str, str]:
    e = os.environ.copy()
    e["GIT_INDEX_FILE"] = str(PRIVATE_INDEX)
    # Avoid hooks fighting shared index.lock when possible.
    e.setdefault("GIT_OPTIONAL_LOCKS", "0")
    return e


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, check=False, env=env())


def run_main(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, check=False)


def main() -> int:
    MSG.write_text(
        "feat(bridge): pathspec-seal climb3 sibling, measured champions path, C-backup junction\n"
        "\n"
        "Private-index commit of coherent evidence/tools remaining after origin@6b1ad4ef:\n"
        "isolated-consumer climb3 matrices + sibling Main scaffold, measured champions-path\n"
        "glue/tests, forced C: data-junction backup seal. No secrets; champions=0 honest.\n",
        encoding="utf-8",
    )

    existing = [p for p in PATHSPECS if (REPO / p).exists()]
    if not existing:
        print("no pathspec files exist", file=sys.stderr)
        return 2

    PRIVATE_INDEX.unlink(missing_ok=True)
    head = run_main(["git", "rev-parse", "HEAD"]).stdout.strip()
    r = run(["git", "read-tree", head])
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode

    add = run(["git", "add", "-f", "--", *existing])
    if add.returncode != 0:
        print(add.stderr, file=sys.stderr)
        return add.returncode

    names = [n for n in run(["git", "diff", "--cached", "--name-only"]).stdout.splitlines() if n]
    print("private-index staged:", len(names))
    for n in names:
        print(" ", n)
    if not names:
        print("nothing to commit (already in HEAD)")
        return 0

    # Prefer commit-tree + update-ref to avoid shared-index commit races.
    wt = run(["git", "write-tree"])
    if wt.returncode != 0:
        print(wt.stderr, file=sys.stderr)
        return wt.returncode
    tree = wt.stdout.strip()

    parent = head
    commit = run(
        [
            "git",
            "commit-tree",
            tree,
            "-p",
            parent,
            "-F",
            str(MSG),
        ]
    )
    if commit.returncode != 0:
        print(commit.stderr, file=sys.stderr)
        return commit.returncode
    new_commit = commit.stdout.strip()
    print("created", new_commit)

    # Fast-forward branch tip if still at parent; else rebase onto current tip via cherry-pick onto private.
    cur = run_main(["git", "rev-parse", "HEAD"]).stdout.strip()
    if cur == parent:
        upd = run_main(["git", "update-ref", "HEAD", new_commit, parent])
        if upd.returncode != 0:
            print(upd.stderr, file=sys.stderr)
            return upd.returncode
        print("HEAD fast-forwarded", new_commit)
    else:
        # Parent moved; recreate commit on current HEAD with same tree delta via read-tree merge.
        print("HEAD moved during commit:", cur, "rebuilding on tip")
        PRIVATE_INDEX.unlink(missing_ok=True)
        r2 = run(["git", "read-tree", cur])
        if r2.returncode != 0:
            print(r2.stderr, file=sys.stderr)
            return r2.returncode
        add2 = run(["git", "add", "-f", "--", *existing])
        if add2.returncode != 0:
            print(add2.stderr, file=sys.stderr)
            return add2.returncode
        wt2 = run(["git", "write-tree"])
        if wt2.returncode != 0:
            print(wt2.stderr, file=sys.stderr)
            return wt2.returncode
        commit2 = run(
            [
                "git",
                "commit-tree",
                wt2.stdout.strip(),
                "-p",
                cur,
                "-F",
                str(MSG),
            ]
        )
        if commit2.returncode != 0:
            print(commit2.stderr, file=sys.stderr)
            return commit2.returncode
        new_commit = commit2.stdout.strip()
        cur2 = run_main(["git", "rev-parse", "HEAD"]).stdout.strip()
        if cur2 != cur:
            print("HEAD moved again during rebuild:", cur2, file=sys.stderr)
            return 3
        upd = run_main(["git", "update-ref", "HEAD", new_commit, cur])
        if upd.returncode != 0:
            print(upd.stderr, file=sys.stderr)
            return upd.returncode
        print("HEAD rebuilt", new_commit)

    final = run_main(["git", "rev-parse", "HEAD"]).stdout.strip()
    print("HEAD", final)
    show = run_main(["git", "show", "--stat", "--oneline", "-1", final])
    print(show.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
