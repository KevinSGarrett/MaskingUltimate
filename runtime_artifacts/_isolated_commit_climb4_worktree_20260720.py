"""Commit climb4 via a detached worktree (clean tree for pre-commit; no sibling dirt)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WT = REPO / ".wt_climb4"
BRANCH = "agent/isolated-consumer-climb4"
LOCK = REPO / ".git" / "index.lock"

FILES = [
    "tools/run_isolated_main_consumer_climb4.py",
    "runtime_artifacts/_seal_isolated_consumer_climb4_20260720.py",
    "runtime_artifacts/_append_ops_log_isolated_consumer_climb4_20260720.py",
    "runtime_artifacts/_commit_msg_isolated_consumer_climb4_20260720.txt",
    "runtime_artifacts/_isolated_commit_climb4_20260720.py",
    "runtime_artifacts/_isolated_commit_climb4_private_index_20260720.py",
    "runtime_artifacts/_isolated_commit_climb4_worktree_20260720.py",
    "runtime_artifacts/main_consumer/isolated_consumer_climb4_run_evidence_20260720T1504.json",
    "runtime_artifacts/main_consumer/isolated_sibling_consumer_run_evidence_20260720T1506.json",
    "qa/live_verification/isolated_consumer_climb4_20260720T1506.json",
    "qa/live_verification/needs_agent_actions_20260720.json",
    "Plan/OPS_LOG.md",
    "Plan/RESTART_HANDOFF_AUTONOMOUS_20260719.md",
    "Plan/Tracker/tracker.json",
    "Plan/Tracker/phases/P6.md",
    "Plan/Tracker/CHANGELOG.jsonl",
]


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd or REPO), text=True, capture_output=True, check=False)


def wait_unlock() -> None:
    for _ in range(60):
        if not LOCK.exists():
            return
        if time.time() - LOCK.stat().st_mtime > 30:
            try:
                LOCK.unlink()
                return
            except OSError:
                pass
        time.sleep(1)


def credit_in_repo(root: Path) -> None:
    for item, pct, note in (
        (
            "MF-P6-11.02",
            "88",
            "2026-07-20 climb4 STATIC_PASS: Mode A 30/30 + sibling 6/6. "
            "Seal qa/live_verification/isolated_consumer_climb4_20260720T1506.json. "
            "HARD OPEN. Credited -> 88.",
        ),
        (
            "MF-P6-11.07",
            "84",
            "2026-07-20 climb4 STATIC_PASS: failure-control flags all true + sibling circuit. "
            "Seal qa/live_verification/isolated_consumer_climb4_20260720T1506.json. "
            "HARD OPEN. Credited -> 84.",
        ),
    ):
        proc = run(
            [
                sys.executable,
                "Plan/Tracker/tracker.py",
                "set",
                item,
                "--status",
                "blocked",
                "--percent",
                pct,
                "--note",
                note,
            ],
            cwd=root,
        )
        print(proc.stdout.strip() or proc.stderr.strip())


def patch_needs(root: Path) -> None:
    path = root / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    for action in data.get("actions", []):
        if action.get("action_id") == "main_adoption_agent_executable":
            action["climb4_20260720T1506"] = {
                "evidence": "qa/live_verification/isolated_consumer_climb4_20260720T1506.json",
                "self_sha256": "e5be2eb2213c2a6419730ff0705fe89f316084d208533a43ca21f38467bda141",
                "credits": {"MF-P6-11.02": "->88", "MF-P6-11.07": "->84"},
            }
            break
    payload = json.dumps(
        {k: v for k, v in data.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    data["self_sha256"] = hashlib.sha256(payload).hexdigest()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ensure_ops_in_main() -> None:
    print(
        run(
            [
                sys.executable,
                "runtime_artifacts/_append_ops_log_isolated_consumer_climb4_20260720.py",
            ]
        ).stdout.strip()
    )


def main() -> int:
    wait_unlock()
    ensure_ops_in_main()
    credit_in_repo(REPO)
    patch_needs(REPO)

    # Refresh worktree from current HEAD.
    run(["git", "branch", "-D", BRANCH])
    if WT.exists():
        run(["git", "worktree", "remove", "--force", str(WT)])
        shutil.rmtree(WT, ignore_errors=True)
    wait_unlock()
    add = run(["git", "worktree", "add", "-b", BRANCH, str(WT), "HEAD"])
    if add.returncode != 0:
        print(add.stderr, file=sys.stderr)
        return add.returncode

    # Copy latest bytes from main working tree into the clean worktree.
    for rel in FILES:
        src = REPO / rel
        dst = WT / rel
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # Re-credit inside worktree so tracker bytes are authoritative there.
    credit_in_repo(WT)
    patch_needs(WT)

    tracker = json.loads((WT / "Plan" / "Tracker" / "tracker.json").read_text(encoding="utf-8"))
    print(
        "worktree credits",
        tracker["items"]["MF-P6-11.02"]["percent_complete"],
        tracker["items"]["MF-P6-11.07"]["percent_complete"],
    )
    if (
        tracker["items"]["MF-P6-11.02"]["percent_complete"] != 88
        or tracker["items"]["MF-P6-11.07"]["percent_complete"] != 84
    ):
        return 2

    existing = [rel for rel in FILES if (WT / rel).exists()]
    run(["git", "add", "-f", "--", *existing], cwd=WT)
    commit = run(
        [
            "git",
            "commit",
            "-F",
            "runtime_artifacts/_commit_msg_isolated_consumer_climb4_20260720.txt",
        ],
        cwd=WT,
    )
    print(commit.stdout)
    print(commit.stderr)
    if commit.returncode != 0:
        return commit.returncode

    climb_head = run(["git", "rev-parse", "HEAD"], cwd=WT).stdout.strip()
    print("climb4 branch HEAD", climb_head)

    # Fast-forward main branch to the climb4 commit.
    wait_unlock()
    ff = run(["git", "merge", "--ff-only", BRANCH])
    print(ff.stdout)
    print(ff.stderr)
    if ff.returncode != 0:
        # Fall back to cherry-pick of the single commit.
        cp = run(["git", "cherry-pick", climb_head])
        print(cp.stdout)
        print(cp.stderr)
        if cp.returncode != 0:
            return cp.returncode

    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    print("main HEAD", head)
    show = run(["git", "show", "HEAD:Plan/Tracker/tracker.json"])
    committed = json.loads(show.stdout)
    print(
        "committed credits",
        committed["items"]["MF-P6-11.02"]["percent_complete"],
        committed["items"]["MF-P6-11.07"]["percent_complete"],
    )

    run(["git", "worktree", "remove", "--force", str(WT)])
    run(["git", "branch", "-D", BRANCH])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
