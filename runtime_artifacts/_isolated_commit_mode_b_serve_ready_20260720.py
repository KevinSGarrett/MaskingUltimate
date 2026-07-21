"""Race-safe isolated commit for Mode-B host serve readiness seal."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
MSG = ROOT / "runtime_artifacts" / "_commit_msg_mode_b_serve_ready.txt"
TMP_INDEX = ROOT / ".git" / "mf_mode_b_serve_ready_tmp_index"
EVIDENCE = "qa/live_verification/mode_b_serve_ready_20260720T1545.json"
MARKER = "mode_b_serve_ready_20260720T1545"
PATHS = [
    "Plan/OPS_LOG.md",
    "qa/live_verification/needs_agent_actions_20260720.json",
    EVIDENCE,
    "runtime_artifacts/_seal_mode_b_serve_ready_20260720T1545.py",
    "runtime_artifacts/_append_ops_log_mode_b_serve_ready_20260720T1545.py",
    "runtime_artifacts/_update_needs_agent_mode_b_serve_ready_20260720.py",
    "runtime_artifacts/_isolated_commit_mode_b_serve_ready_20260720.py",
    "runtime_artifacts/_commit_msg_mode_b_serve_ready.txt",
]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")


def run(args, env=None, check=True):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=check, env=env)


def ensure_artifacts() -> None:
    ops = ROOT / "Plan" / "OPS_LOG.md"
    if MARKER not in ops.read_text(encoding="utf-8"):
        run([PY, "runtime_artifacts/_append_ops_log_mode_b_serve_ready_20260720T1545.py"])
    needs = ROOT / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
    doc = json.loads(needs.read_text(encoding="utf-8"))
    if MARKER not in doc:
        run([PY, "runtime_artifacts/_update_needs_agent_mode_b_serve_ready_20260720.py"])
    if not (ROOT / EVIDENCE).is_file():
        raise SystemExit(f"missing evidence {EVIDENCE}")


def main() -> None:
    for attempt in range(1, 12):
        ensure_artifacts()
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        run(["git", "read-tree", head], env=env)
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
        print(f"CAS lost (attempt {attempt}); retrying")
        time.sleep(1.2)
    raise SystemExit("failed to land isolated commit after retries")


if __name__ == "__main__":
    main()
