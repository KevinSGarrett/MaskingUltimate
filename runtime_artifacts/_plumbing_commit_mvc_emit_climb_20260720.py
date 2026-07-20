"""Pathspec plumbing commit for GOLD FACTORY tournament --emit MVC climb."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TMP_INDEX = REPO / ".git" / "_mvc_emit_climb_tmp_index"
MSG = REPO / ".git" / "COMMIT_MSG_GOLD_MVC.txt"

FILES = [
    "Plan/OPS_LOG.md",
    "Plan/RESTART_HANDOFF_AUTONOMOUS_20260719.md",
    "runtime_artifacts/_batch_emit_mvc_more_images_20260720.py",
    "runtime_artifacts/_mvc_coverage_report_20260720.py",
    "runtime_artifacts/_seal_wilson_gap_mvc_admission_20260720T1705.py",
    "runtime_artifacts/_plumbing_commit_mvc_emit_climb_20260720.py",
    "qa/live_verification/gold_factory_tournament_emit_mvc_climb_20260720T1716.json",
    "qa/live_verification/autonomy_batch_emit_more_images_20260720T171435Z.json",
    "qa/live_verification/wilson_sample_gap_mvc_20260720T171524Z.json",
    "qa/live_verification/wilson_sample_gap_mvc_20260720T171801Z.json",
    "qa/live_verification/wilson_sample_gap_mvc_20260720T171828Z.json",
    "qa/live_verification/autonomous_gold_admission_wilson_gap_20260720T171524Z.json",
    "qa/live_verification/autonomous_gold_admission_wilson_gap_20260720T171801Z.json",
    "qa/live_verification/autonomous_gold_admission_wilson_gap_20260720T171828Z.json",
    "qa/live_verification/corpus_envelope_repair_wilson_gap_20260720T171524Z.json",
    "qa/live_verification/corpus_envelope_repair_wilson_gap_20260720T171801Z.json",
    "qa/live_verification/corpus_envelope_repair_wilson_gap_20260720T171828Z.json",
] + [
    f"qa/live_verification/tournament_emit_decision_20260720T171248Z_{i:02d}_{label}.json"
    for i, label in enumerate(
        (
            "torso",
            "face",
            "hair",
            "left_hand",
            "right_hand",
            "left_foot",
            "right_foot",
            "skin",
            "torso",
            "face",
            "hair",
            "left_hand",
            "right_hand",
            "left_foot",
            "right_foot",
            "skin",
        )
    )
]


def main() -> int:
    import os

    missing = [f for f in FILES if not (REPO / f).is_file()]
    if missing:
        print("MISSING", missing[:10], file=sys.stderr)
        return 2

    MSG.write_text(
        "qa(gold): climb tournament --emit MVC pool toward Wilson binding\n\n"
        "Continue GOLD FACTORY emit path (+48 this wave) and reseal Wilson/admission;\n"
        "pool MVC~448 with gold=0 champions={} and ~154 gap to n=598.\n",
        encoding="utf-8",
    )

    if TMP_INDEX.exists():
        TMP_INDEX.unlink()
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(TMP_INDEX)

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    r = subprocess.run(
        ["git", "read-tree", head],
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode

    # Format only our Python files before staging.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "black",
            "runtime_artifacts/_batch_emit_mvc_more_images_20260720.py",
            "runtime_artifacts/_mvc_coverage_report_20260720.py",
            "runtime_artifacts/_seal_wilson_gap_mvc_admission_20260720T1705.py",
            "runtime_artifacts/_plumbing_commit_mvc_emit_climb_20260720.py",
        ],
        cwd=str(REPO),
        check=False,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--fix",
            "runtime_artifacts/_seal_wilson_gap_mvc_admission_20260720T1705.py",
            "runtime_artifacts/_plumbing_commit_mvc_emit_climb_20260720.py",
        ],
        cwd=str(REPO),
        check=False,
    )

    for path in FILES:
        r = subprocess.run(
            ["git", "add", "-f", "--", path],
            cwd=str(REPO),
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        if r.returncode != 0:
            print("ADD_FAIL", path, r.stderr, file=sys.stderr)
            return r.returncode

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    ).stdout.splitlines()
    print("STAGED", len(staged))
    for line in staged:
        print(line)
    if len(staged) > 40:
        print("REFUSING oversized staged set", file=sys.stderr)
        return 3

    tree = subprocess.run(
        ["git", "write-tree"],
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    ).stdout.strip()

    commit = subprocess.run(
        ["git", "commit-tree", tree, "-p", head, "-F", str(MSG)],
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    ).stdout.strip()

    # Move branch tip with compare-and-swap against the head we started from.
    upd = subprocess.run(
        ["git", "update-ref", f"refs/heads/{_branch()}", commit, head],
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=False,
    )
    if upd.returncode != 0:
        print("UPDATE_REF_FAIL", upd.stderr, file=sys.stderr)
        print("COMMIT_OBJ", commit)
        return upd.returncode

    print("OK", commit[:12], "tree", tree[:12], "parent", head[:12])
    return 0


def _branch() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
