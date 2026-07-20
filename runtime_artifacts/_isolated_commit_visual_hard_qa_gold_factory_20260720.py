"""Isolated-index commit for GOLD FACTORY visual/hard QA lane only."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MSG = ROOT / "runtime_artifacts/_commit_msg_visual_hard_qa_gold_factory.txt"
TMP_INDEX = ROOT / ".git" / "mf_visual_hard_qa_tmp_index"

FILES = [
    "tools/run_tournament_mvc_visual_hard_qa.py",
    "qa/live_verification/tournament_mvc_visual_hard_qa_20260720T1153.json",
    "qa/live_verification/tournament_mvc_visual_hard_qa_delta_20260720T121501.json",
    "qa/live_verification/tournament_mvc_visual_hard_qa_delta2_20260720T121949.json",
    "qa/live_verification/gold_factory_visual_hard_qa_lane_20260720T1222.json",
    "qa/live_verification/gold_factory_visual_hard_qa_lane_latest.json",
    "qa/live_verification/autonomous_gold_admission_after_visual_20260720T122023.json",
    "qa/live_verification/gpu_sequence_ollama_mvc_visual.json",
    "qa/autonomy/corpora/autonomous_verification_20260720T122023.json",
    "runtime_artifacts/_seal_visual_hard_qa_gold_factory_20260720.py",
    "runtime_artifacts/_restore_source_unresolved_demotes.py",
    "runtime_artifacts/_commit_msg_visual_hard_qa_gold_factory.txt",
    "runtime_artifacts/_isolated_commit_visual_hard_qa_gold_factory_20260720.py",
    "Plan/OPS_LOG.md",
]


def run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    missing = [f for f in FILES if not (ROOT / f).exists()]
    if missing:
        print("MISSING:", missing, file=sys.stderr)
        return 1
    if TMP_INDEX.exists():
        TMP_INDEX.unlink()
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(TMP_INDEX)
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    tree = run(["git", "rev-parse", f"{head}^{{tree}}"]).stdout.strip()
    r = run(["git", "read-tree", tree], env=env)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode
    r = run(["git", "add", "--"] + FILES, env=env)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode
    r = run(["git", "write-tree"], env=env)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode
    new_tree = r.stdout.strip()
    r = run(["git", "commit-tree", new_tree, "-p", head, "-F", str(MSG)])
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode
    commit = r.stdout.strip()
    r = run(["git", "update-ref", "HEAD", commit])
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode
    print(commit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
