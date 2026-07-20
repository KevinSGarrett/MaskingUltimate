"""Isolated commit for climb3 + sibling consumer scaffold (lock-wait)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCK = REPO / ".git" / "index.lock"
MSG = REPO / "runtime_artifacts" / "_commit_msg_isolated_climb3_sibling.txt"
CREDITS = {"MF-P6-11.01": 88, "MF-P6-11.02": 88, "MF-P6-11.07": 84}
FILES = [
    "tools/scaffold_sibling_main_consumer.py",
    "tools/run_isolated_main_consumer_climb3.py",
    "qa/live_verification/isolated_consumer_dod_climb3_20260720T0948.json",
    "qa/live_verification/sibling_main_consumer_scaffold_20260720.json",
    "runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T0948.json",
    "runtime_artifacts/main_consumer/sibling_consumer_scaffold_run_evidence.json",
    "runtime_artifacts/_seal_sibling_and_climb3_20260720.py",
    "Plan/Tracker/tracker.json",
]


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, check=False)


def wait_lock(timeout: float = 180.0) -> None:
    start = time.time()
    while LOCK.exists():
        if time.time() - start > timeout:
            try:
                age = time.time() - LOCK.stat().st_mtime
            except OSError:
                age = 999
            if age > 60:
                try:
                    LOCK.unlink()
                    return
                except OSError:
                    pass
            raise TimeoutError("index.lock held too long")
        time.sleep(0.5)


def apply_credits() -> None:
    path = REPO / "Plan" / "Tracker" / "tracker.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    for iid, pct in CREDITS.items():
        item = data["items"][iid]
        item["percent_complete"] = pct
        item["status"] = "blocked"
        item["updated_at"] = now
        notes = item.setdefault("notes", [])
        text = (
            f"2026-07-20 climb3+sibling seal commit: hold STATIC credit at {pct}% "
            f"(isolated_consumer_dod_climb3_20260720T0948 + sibling_main_consumer_scaffold_20260720). "
            "HARD blockers remain OPEN; Wave64 dirty Main untouched. "
            "Main sibling branch codex/maskfactory-sibling-consumer-scaffold @6f73ee00."
        )
        if not any(text[:50] in (n.get("text") or "") for n in notes[-5:]):
            notes.append({"ts": now, "actor": "ai_agent", "text": text})
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    apply_credits()
    for rel in (
        "tools/scaffold_sibling_main_consumer.py",
        "tools/run_isolated_main_consumer_climb3.py",
        "runtime_artifacts/_seal_sibling_and_climb3_20260720.py",
    ):
        path = REPO / rel
        if path.exists():
            run([sys.executable, "-m", "ruff", "check", "--fix", str(path)])
            run([sys.executable, "-m", "black", str(path)])

    existing = [f for f in FILES if (REPO / f).exists()]
    wait_lock()
    add = run(["git", "add", "-f", "--"] + existing)
    if add.returncode != 0:
        print(add.stderr)
        return add.returncode
    wait_lock()
    commit = run(["git", "commit", "-F", str(MSG)])
    print(commit.stdout)
    print(commit.stderr)
    if commit.returncode != 0:
        wait_lock()
        run(["git", "add", "-f", "--"] + existing)
        wait_lock()
        commit2 = run(["git", "commit", "-F", str(MSG)])
        print(commit2.stdout)
        print(commit2.stderr)
        if commit2.returncode != 0:
            return commit2.returncode
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    print("HEAD", head)
    push = run(["git", "push"])
    print(push.stdout)
    print(push.stderr)
    data = json.loads((REPO / "Plan" / "Tracker" / "tracker.json").read_text(encoding="utf-8"))
    print({i: data["items"][i]["percent_complete"] for i in CREDITS})
    return 0 if push.returncode == 0 else push.returncode


if __name__ == "__main__":
    raise SystemExit(main())
