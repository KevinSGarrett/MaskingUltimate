"""Isolated-index commit for tournament Ollama critic/router wave only."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MSG = ROOT / "runtime_artifacts/_commit_msg_tournament_ollama_critic_router_20260720.txt"
TMP_INDEX = ROOT / ".git" / "mf_ollama_critic_router_tmp_index"

FILES = [
    "tools/run_tournament_ollama_critic_router.py",
    "qa/live_verification/gpu_sequence_ollama_critic_router_20260720.json",
    "qa/live_verification/tournament_ollama_critic_router_20260720T1153.json",
    "qa/live_verification/tournament_ollama_critic_router_remaining_20260720T1210.json",
    "qa/live_verification/tournament_ollama_critic_router_wave_20260720T1212.json",
    "qa/live_verification/tournament_ollama_critic_router_latest.json",
    "runtime_artifacts/_seal_tournament_ollama_critic_router_20260720.py",
    "runtime_artifacts/_commit_msg_tournament_ollama_critic_router_20260720.txt",
    "runtime_artifacts/_isolated_commit_tournament_ollama_critic_router_20260720.py",
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
    # Prefer HEAD's OPS_LOG + our seal entry already on disk; if add failed on race, stop.
    r = run(["git", "write-tree"], env=env)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode
    new_tree = r.stdout.strip()
    r = run(["git", "commit-tree", new_tree, "-p", head, "-F", str(MSG)], env=env)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode
    new_commit = r.stdout.strip()
    r = run(["git", "update-ref", "HEAD", new_commit])
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode
    if TMP_INDEX.exists():
        TMP_INDEX.unlink()
    print(new_commit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
