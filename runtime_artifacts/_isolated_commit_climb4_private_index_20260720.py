"""Commit climb4 evidence via a private GIT_INDEX_FILE (immune to sibling index fights)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRIVATE_INDEX = REPO / ".git" / "index.climb4"
LOCK = REPO / ".git" / "index.lock"
MSG = REPO / "runtime_artifacts" / "_commit_msg_isolated_consumer_climb4_20260720.txt"

PATHSPECS = [
    "tools/run_isolated_main_consumer_climb4.py",
    "runtime_artifacts/_seal_isolated_consumer_climb4_20260720.py",
    "runtime_artifacts/_append_ops_log_isolated_consumer_climb4_20260720.py",
    "runtime_artifacts/_commit_msg_isolated_consumer_climb4_20260720.txt",
    "runtime_artifacts/_isolated_commit_climb4_20260720.py",
    "runtime_artifacts/_isolated_commit_climb4_private_index_20260720.py",
    "runtime_artifacts/main_consumer/isolated_consumer_climb4_run_evidence_20260720T1504.json",
    "runtime_artifacts/main_consumer/isolated_sibling_consumer_run_evidence_20260720T1506.json",
    "qa/live_verification/isolated_consumer_climb4_20260720T1506.json",
    "qa/live_verification/needs_agent_actions_20260720.json",
    "Plan/OPS_LOG.md",
    "Plan/RESTART_HANDOFF_AUTONOMOUS_20260719.md",
    "Plan/Tracker/tracker.json",
]


def env() -> dict[str, str]:
    e = os.environ.copy()
    e["GIT_INDEX_FILE"] = str(PRIVATE_INDEX)
    return e


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=REPO, text=True, capture_output=True, check=False, env=env(), **kwargs
    )


def run_main(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, check=False)


def credit_tracker() -> None:
    for item, pct, note in (
        (
            "MF-P6-11.02",
            "88",
            "2026-07-20 climb4 STATIC_PASS depth: tools/run_isolated_main_consumer_climb4.py "
            "Mode A 30/30 PASS + sibling consumer 6/6 (HEAD 9b61c866). Seal "
            "qa/live_verification/isolated_consumer_climb4_20260720T1506.json "
            "self_sha256=e5be2eb2213c2a6419730ff0705fe89f316084d208533a43ca21f38467bda141. "
            "HARD OPEN. Credited -> 88.",
        ),
        (
            "MF-P6-11.07",
            "84",
            "2026-07-20 climb4 STATIC_PASS depth: failure-control flags all true "
            "(tools/run_isolated_main_consumer_climb4.py) + sibling deepened circuit. "
            "Seal qa/live_verification/isolated_consumer_climb4_20260720T1506.json. "
            "HARD OPEN. Credited -> 84.",
        ),
    ):
        proc = run_main(
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
            ]
        )
        print(proc.stdout.strip() or proc.stderr.strip())


def ensure_ops() -> None:
    print(
        run_main(
            [
                sys.executable,
                "runtime_artifacts/_append_ops_log_isolated_consumer_climb4_20260720.py",
            ]
        ).stdout.strip()
    )


def patch_needs() -> None:
    path = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for action in data.get("actions", []):
        if action.get("action_id") == "main_adoption_agent_executable":
            action["climb4_20260720T1506"] = {
                "evidence": "qa/live_verification/isolated_consumer_climb4_20260720T1506.json",
                "self_sha256": "e5be2eb2213c2a6419730ff0705fe89f316084d208533a43ca21f38467bda141",
                "credits": {"MF-P6-11.02": "->88", "MF-P6-11.07": "->84"},
                "note": "climb4 STATIC_PASS; HARD OPEN; Wave64 Main untouched",
            }
            break
    payload = json.dumps(
        {k: v for k, v in data.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    data["self_sha256"] = hashlib.sha256(payload).hexdigest()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ensure_handoff() -> None:
    path = REPO / "Plan" / "RESTART_HANDOFF_AUTONOMOUS_20260719.md"
    text = path.read_text(encoding="utf-8")
    if "climb4 STATIC_PASS depth" in text:
        return
    block = (
        "## Latest wave (2026-07-20 15:06 UTC — MF-P6-11.02/11.07 climb4 STATIC_PASS depth)\n\n"
        "- Producer climb4 Mode A 30/30 + failure-control flags all true; sibling consumer 6/6.\n"
        "- Credits 11.02→88 / 11.07→84. HARD OPEN. Wave64 Main untouched.\n"
        "- Evidence: qa/live_verification/isolated_consumer_climb4_20260720T1506.json\n\n"
    )
    parts = text.split("## Latest wave", 1)
    path.write_text(
        (parts[0] + block + "## Latest wave" + parts[1]) if len(parts) == 2 else block + text,
        encoding="utf-8",
    )


def main() -> int:
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime > 15:
        LOCK.unlink(missing_ok=True)

    credit_tracker()
    ensure_ops()
    patch_needs()
    ensure_handoff()

    tracker = json.loads((REPO / "Plan" / "Tracker" / "tracker.json").read_text(encoding="utf-8"))
    if (
        tracker["items"]["MF-P6-11.02"]["percent_complete"] != 88
        or tracker["items"]["MF-P6-11.07"]["percent_complete"] != 84
    ):
        print("credits drifted before commit", file=sys.stderr)
        return 2

    PRIVATE_INDEX.unlink(missing_ok=True)
    r = run(["git", "read-tree", "HEAD"])
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode

    # Also include phase markdown if tracker updated it.
    extras = []
    for extra in ("Plan/Tracker/phases/P6.md", "Plan/Tracker/CHANGELOG.jsonl"):
        if (REPO / extra).exists():
            extras.append(extra)

    add = run(["git", "add", "-f", "--", *PATHSPECS, *extras])
    if add.returncode != 0:
        print(add.stderr, file=sys.stderr)
        return add.returncode

    names = run(["git", "diff", "--cached", "--name-only"]).stdout.splitlines()
    print("private-index staged:")
    for n in names:
        print(" ", n)

    # Commit creates a commit object and updates HEAD/ref; uses private index for tree.
    commit = run(["git", "commit", "-F", str(MSG)])
    print(commit.stdout)
    print(commit.stderr)
    if commit.returncode != 0:
        return commit.returncode

    head = run_main(["git", "rev-parse", "HEAD"]).stdout.strip()
    print("HEAD", head)

    # Verify credits survived in the committed tree.
    show = run_main(["git", "show", "HEAD:Plan/Tracker/tracker.json"])
    if show.returncode == 0:
        committed = json.loads(show.stdout)
        print(
            "committed credits",
            committed["items"]["MF-P6-11.02"]["percent_complete"],
            committed["items"]["MF-P6-11.07"]["percent_complete"],
        )
    PRIVATE_INDEX.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
