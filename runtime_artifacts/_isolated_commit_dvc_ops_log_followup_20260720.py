"""Race-safe follow-up: append DVC C: backup OPS_LOG entry onto HEAD only (no WT scoop)."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
MSG = ROOT / "runtime_artifacts" / "_commit_msg_dvc_ops_log_followup_20260720.txt"
TMP_INDEX = ROOT / ".git" / "mf_dvc_ops_tmp_index"
MARKER = "DVC local remote retargeted to C: backup"
ENTRY = """
## 2026-07-20 15:03 UTC - DVC local remote retargeted to C: backup; status -c / push PASS
**Item:** dvc_push_local_first / maskfactory-dvc-local on fixed-disk C: backup
**Command:** `dvc remote modify --local maskfactory-dvc-local url C:/Comfy_UI_Main_Masking/data_c_backup_relocated/dvc_local_remote`; `dvc status -c -r maskfactory-dvc-local`; `dvc push -r maskfactory-dvc-local`; `dvc status -c -r maskfactory-dvc-local`
**Result:** PASS. Sibling had already copied F-only `dvc_local_remote` (52 files / 6,349,602 bytes) onto `C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated\\dvc_local_remote`. Retargeted gitignored `.dvc/config.local` from `F:/MaskFactory_DataRelocated/dvc_local_remote` -> C: backup path. `dvc status -c` -> **Cache and remote are in sync**; `dvc push -r maskfactory-dvc-local` -> **Everything is up to date**; post-push status -c still in sync. `data/` junction unchanged (still C: backup). F: tree left intact as secondary mirror. Cloud s3 push still deferred (no AWS creds / dvc-s3 on active PATH dvc). No tier inflation.

Evidence: qa/live_verification/dvc_local_c_backup_verify_20260720T1503Z.json; script runtime_artifacts/_seal_dvc_local_c_backup_verify_20260720.py.
"""


def run(args, env=None, check=True, input_text=None):
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=check,
        env=env,
        input=input_text,
    )


def main() -> None:
    MSG.write_text(
        "docs(ops): append DVC C: backup local-remote verify OPS_LOG entry\n",
        encoding="utf-8",
    )
    for attempt in range(1, 12):
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        head_ops = run(["git", "show", f"{head}:Plan/OPS_LOG.md"]).stdout
        if MARKER in head_ops:
            print(f"OPS_LOG already sealed on {head}; nothing to do")
            return
        new_ops = head_ops.rstrip() + "\n" + ENTRY
        if not new_ops.endswith("\n"):
            new_ops += "\n"

        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        run(["git", "read-tree", head], env=env)
        blob = run(
            ["git", "hash-object", "-w", "--stdin"],
            env=env,
            input_text=new_ops,
        ).stdout.strip()
        run(
            [
                "git",
                "update-index",
                "--add",
                "--cacheinfo",
                f"100644,{blob},Plan/OPS_LOG.md",
            ],
            env=env,
        )
        # also land this follow-up helper itself
        run(
            [
                "git",
                "add",
                "--",
                "runtime_artifacts/_isolated_commit_dvc_ops_log_followup_20260720.py",
                "runtime_artifacts/_commit_msg_dvc_ops_log_followup_20260720.txt",
            ],
            env=env,
        )
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
            run(["git", "read-tree", "HEAD"], check=False)
            return
        print(f"CAS lost (attempt {attempt}); retrying")
        time.sleep(1.5)
    raise SystemExit("failed to land OPS_LOG follow-up after retries")


if __name__ == "__main__":
    main()
