"""Commit+push forced-C junction seal using a PRIVATE git index (sibling-race safe)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRIVATE_INDEX = REPO / ".git" / "index.forced_c_backup_20260720"
FILES = [
    "qa/live_verification/data_junction_forced_c_backup_20260720T1504Z.json",
    "qa/live_verification/needs_agent_actions_20260720.json",
    "Plan/OPS_LOG.md",
    "runtime_artifacts/_seal_data_junction_forced_c_backup_20260720.py",
]
MSG = """ops(data): force data/ junction on C: backup; forbid USB F: auto-repoint

Confirmed data/ -> data_c_backup_relocated (8 packages readable; reindex dry-run ok). Binding: auto-repoint to removable F: is FORBIDDEN.
"""


def env_with_index() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(PRIVATE_INDEX)
    return env


def run(cmd: list[str], *, use_private: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
        env=env_with_index() if use_private else None,
    )


def ensure_patch_and_ops() -> None:
    patch = run(
        [
            sys.executable,
            "-u",
            str(REPO / "runtime_artifacts/_patch_needs_forced_c_backup_20260720.py"),
        ]
    )
    sys.stdout.write(patch.stdout)
    sys.stdout.flush()
    if patch.returncode != 0:
        sys.stderr.write(patch.stderr)
        raise SystemExit(patch.returncode)
    ops_path = REPO / "Plan" / "OPS_LOG.md"
    text = ops_path.read_text(encoding="utf-8")
    marker = "data_junction_forced_c_backup_20260720T1504Z.json"
    if marker not in text:
        with ops_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(
                """
## 2026-07-20 15:04 UTC - Force data/ junction onto C: backup (forbid USB F: auto-repoint)
**Item:** data_junction_forced_c_backup / usb_data_junction=FORBIDDEN / auto_repoint_to_f=FORBIDDEN
**Command:** fsutil reparsepoint query data; maskfactory reindex --dry-run; seal+patch scripts
**Result:** PASS. data/ -> C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated (8 packages). Auto-repoint to F: FORBIDDEN.

Evidence: qa/live_verification/data_junction_forced_c_backup_20260720T1504Z.json (self_sha256 9cbf1860...).
"""
            )
        print("OPS_APPENDED", flush=True)


def main() -> int:
    ensure_patch_and_ops()
    for rel in FILES:
        path = REPO / rel
        if not path.exists():
            raise SystemExit(f"missing {rel}")
        data = path.read_bytes()
        if data and not data.endswith(b"\n"):
            path.write_bytes(data + b"\n")

    if PRIVATE_INDEX.exists():
        PRIVATE_INDEX.unlink()

    # Seed private index from HEAD, then add only our paths.
    read = run(["git", "read-tree", "HEAD"], use_private=True)
    if read.returncode != 0:
        print(read.stderr, flush=True)
        raise SystemExit(read.returncode)

    add = run(["git", "add", "-f", "--", *FILES], use_private=True)
    if add.returncode != 0:
        print(add.stderr, flush=True)
        raise SystemExit(add.returncode)

    staged = run(["git", "diff", "--cached", "--name-only"], use_private=True)
    names = [p.replace("\\", "/") for p in staged.stdout.splitlines() if p.strip()]
    print("STAGED", names, flush=True)
    wanted = {p.replace("\\", "/") for p in FILES}
    if set(names) != wanted:
        # Show status vs HEAD for diagnosis; still require all wanted files present.
        if not wanted.issubset(set(names)):
            raise SystemExit(f"private index missing files: {wanted - set(names)}")

    msg_path = (
        REPO
        / "runtime_artifacts/_commit_msg_data_junction_forced_c_backup_20260720.txt"
    )
    msg_path.write_text(MSG, encoding="utf-8")

    # Commit with private index (does not touch shared index.lock from siblings as much,
    # though refs still need updating under .git).
    for attempt in range(6):
        commit = run(["git", "commit", "-F", str(msg_path)], use_private=True)
        print(commit.stdout, flush=True)
        print(commit.stderr, flush=True)
        if commit.returncode == 0:
            break
        print(f"COMMIT_RETRY {attempt+1}", flush=True)
        ensure_patch_and_ops()
        run(["git", "add", "-f", "--", *FILES], use_private=True)
        time.sleep(1.0)
    else:
        raise SystemExit("commit failed")

    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    print("HEAD", head, flush=True)

    for attempt in range(8):
        push = run(["git", "push", "-u", "origin", "HEAD"])
        print(push.stdout, flush=True)
        print(push.stderr, flush=True)
        if push.returncode == 0:
            print("PUSH_OK", head, flush=True)
            return 0
        print(f"PUSH_RETRY {attempt+1}", flush=True)
        time.sleep(2.0)
    raise SystemExit("push failed")


if __name__ == "__main__":
    raise SystemExit(main())
