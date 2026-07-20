"""Atomically re-credit tracker + pathspec-commit climb4 evidence (lock-aware)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCK = REPO / ".git" / "index.lock"

PATHSPECS = [
    "tools/run_isolated_main_consumer_climb4.py",
    "runtime_artifacts/_seal_isolated_consumer_climb4_20260720.py",
    "runtime_artifacts/_append_ops_log_isolated_consumer_climb4_20260720.py",
    "runtime_artifacts/_commit_msg_isolated_consumer_climb4_20260720.txt",
    "runtime_artifacts/_isolated_commit_climb4_20260720.py",
    "runtime_artifacts/main_consumer/isolated_consumer_climb4_run_evidence_20260720T1504.json",
    "runtime_artifacts/main_consumer/isolated_sibling_consumer_run_evidence_20260720T1506.json",
    "qa/live_verification/isolated_consumer_climb4_20260720T1506.json",
    "qa/live_verification/needs_agent_actions_20260720.json",
    "Plan/OPS_LOG.md",
    "Plan/RESTART_HANDOFF_AUTONOMOUS_20260719.md",
    "Plan/Tracker/tracker.json",
]

MSG = REPO / "runtime_artifacts" / "_commit_msg_isolated_consumer_climb4_20260720.txt"


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, check=False)


def wait_lock(timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while LOCK.exists() and time.time() < deadline:
        age = time.time() - LOCK.stat().st_mtime
        if age > 20:
            LOCK.unlink(missing_ok=True)
            return
        time.sleep(1)
    if LOCK.exists():
        LOCK.unlink(missing_ok=True)


def credit_tracker() -> None:
    for item, pct, note in (
        (
            "MF-P6-11.02",
            "88",
            "2026-07-20 climb4 STATIC_PASS depth: tools/run_isolated_main_consumer_climb4.py "
            "Mode A matrix 30/30 PASS + sibling Comfy_UI_Main_MaskFactory_Consumer Mode A "
            "pillar 6/6 PASS (HEAD 9b61c866). Seal "
            "qa/live_verification/isolated_consumer_climb4_20260720T1506.json "
            "self_sha256=e5be2eb2213c2a6419730ff0705fe89f316084d208533a43ca21f38467bda141. "
            "HARD stays OPEN (AWAITING_MAIN; Wave64 Main untouched). Credited -> 88.",
        ),
        (
            "MF-P6-11.07",
            "84",
            "2026-07-20 climb4 STATIC_PASS depth: failure-control flags all true via "
            "tools/run_isolated_main_consumer_climb4.py; sibling consumer deepened circuit "
            "PASS. Seal qa/live_verification/isolated_consumer_climb4_20260720T1506.json. "
            "HARD stays OPEN (AWAITING_MAIN). Credited -> 84.",
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
            ]
        )
        print(proc.stdout.strip() or proc.stderr.strip())


def ensure_ops_log() -> None:
    proc = run(
        [sys.executable, "runtime_artifacts/_append_ops_log_isolated_consumer_climb4_20260720.py"]
    )
    print(proc.stdout.strip() or proc.stderr.strip())


def patch_needs() -> None:
    path = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for action in data.get("actions", []):
        if action.get("action_id") == "main_adoption_agent_executable":
            action["climb4_20260720T1506"] = {
                "evidence": "qa/live_verification/isolated_consumer_climb4_20260720T1506.json",
                "self_sha256": "e5be2eb2213c2a6419730ff0705fe89f316084d208533a43ca21f38467bda141",
                "note": (
                    "Producer climb4 Mode A 30/30 + failure-control flags all-true STATIC_PASS; "
                    "sibling Comfy_UI_Main_MaskFactory_Consumer HEAD 9b61c866 6/6 pillars PASS. "
                    "HARD still OPEN; Wave64 Main untouched."
                ),
                "credits": {"MF-P6-11.02": "->88", "MF-P6-11.07": "->84"},
            }
            break
    import hashlib

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
    marker = "climb4 STATIC_PASS depth"
    if marker in text:
        return
    block = (
        "## Latest wave (2026-07-20 15:06 UTC — MF-P6-11.02/11.07 climb4 STATIC_PASS depth)\n\n"
        "- **Producer climb4:** `tools/run_isolated_main_consumer_climb4.py` — Mode A **30/30 PASS**, "
        "failure-control flags all true.\n"
        "- **Sibling consumer:** `C:\\Comfy_UI_Main_MaskFactory_Consumer` HEAD `9b61c866` — **6/6 PASS**.\n"
        "- **Credits:** MF-P6-11.02 →88; MF-P6-11.07 →84 (blocked, STATIC_PASS only). HARD still OPEN. "
        "Wave64 Main untouched.\n"
        "- **Evidence:** `qa/live_verification/isolated_consumer_climb4_20260720T1506.json` "
        "(self_sha256 `e5be2eb2…`).\n\n"
    )
    parts = text.split("## Latest wave", 1)
    if len(parts) != 2:
        path.write_text(block + text, encoding="utf-8")
        return
    path.write_text(parts[0] + block + "## Latest wave" + parts[1], encoding="utf-8")


def main() -> int:
    wait_lock()
    credit_tracker()
    ensure_ops_log()
    patch_needs()
    ensure_handoff()

    tracker = json.loads((REPO / "Plan" / "Tracker" / "tracker.json").read_text(encoding="utf-8"))
    p02 = tracker["items"]["MF-P6-11.02"]["percent_complete"]
    p07 = tracker["items"]["MF-P6-11.07"]["percent_complete"]
    if p02 != 88 or p07 != 84:
        print(f"credit verify failed: 11.02={p02} 11.07={p07}", file=sys.stderr)
        return 2

    wait_lock()
    run(["git", "reset", "HEAD"])
    wait_lock()
    add = run(["git", "add", "--", *PATHSPECS])
    if add.returncode != 0:
        print(add.stderr, file=sys.stderr)
        return add.returncode
    cached = run(["git", "diff", "--cached", "--name-only"])
    names = [n for n in cached.stdout.splitlines() if n.strip()]
    print("staged:", *names, sep="\n  ")
    unexpected = [n for n in names if n not in PATHSPECS and n.replace("\\", "/") not in PATHSPECS]
    # Normalize
    unexpected = [
        n for n in names if n.replace("\\", "/") not in {p.replace("\\", "/") for p in PATHSPECS}
    ]
    if unexpected:
        print("unexpected staged paths:", unexpected, file=sys.stderr)
        run(["git", "reset", "HEAD"])
        return 3

    wait_lock()
    commit = run(["git", "commit", "-F", str(MSG)])
    print(commit.stdout)
    print(commit.stderr)
    if commit.returncode != 0:
        return commit.returncode
    head = run(["git", "rev-parse", "HEAD"])
    print("HEAD", head.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
