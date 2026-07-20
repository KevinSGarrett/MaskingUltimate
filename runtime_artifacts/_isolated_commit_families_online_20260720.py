"""Race-safe isolated commit of families-online + gold admission evidence only."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
MSG = ROOT / "runtime_artifacts" / "_commit_msg_families_online_20260720.txt"
TMP_INDEX = ROOT / ".git" / "mf_families_online_tmp_index"
PATHS = [
    "Plan/OPS_LOG.md",
    "Plan/RESTART_HANDOFF_AUTONOMOUS_20260719.md",
    "qa/live_verification/families_online_gold_drive_20260720T0957.json",
    "qa/live_verification/autonomous_gold_admission_families_online_20260720T0957.json",
    "qa/live_verification/needs_agent_actions_20260720.json",
    "qa/live_verification/_birefnet_local_cuda_20260720T0956.json",
    "qa/live_verification/_schp_atr_local_cuda_20260720T0956.json",
    "qa/live_verification/_faceparse_20260720T0956.txt",
    "runtime_artifacts/_seal_families_online_gold_drive_20260720.py",
    "runtime_artifacts/_smoke_birefnet_local_cuda_20260720.py",
    "runtime_artifacts/_smoke_schp_local_cuda_20260720.py",
    "runtime_artifacts/_append_ops_log_families_online_20260720.py",
    "runtime_artifacts/_isolated_commit_families_online_20260720.py",
]


def run(args: list[str], env: dict[str, str] | None = None, check: bool = True):
    return subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, check=check, env=env
    )


def main() -> None:
    missing = [p for p in PATHS if not (ROOT / p).is_file()]
    if missing:
        raise SystemExit(f"missing paths: {missing}")
    # Ensure faceparse txt ends with newline for end-of-file-fixer.
    faceparse = ROOT / "qa/live_verification/_faceparse_20260720T0956.txt"
    data = faceparse.read_bytes()
    if data and not data.endswith(b"\n"):
        faceparse.write_bytes(data + b"\n")
    MSG.write_text(
        "runtime(families): bring 3 mask families online via local CUDA; "
        "re-drive gold admission\n\n"
        "Clear the >=3 independent-family gate with live faceparse/birefnet/schp "
        "CUDA smokes; admission remains honestly insufficient "
        "(0 machine_verified_candidate).\n",
        encoding="utf-8",
    )
    for attempt in range(1, 10):
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        run(["git", "read-tree", head], env=env)
        run(["git", "add", "--", *PATHS], env=env)
        tree = run(["git", "write-tree"], env=env).stdout.strip()
        commit = run(
            ["git", "commit-tree", tree, "-p", head, "-F", str(MSG)]
        ).stdout.strip()
        cas = run(
            ["git", "update-ref", f"refs/heads/{BRANCH}", commit, head],
            check=False,
        )
        if cas.returncode == 0:
            print(f"committed {commit} parent {head} (attempt {attempt})")
            if TMP_INDEX.exists():
                TMP_INDEX.unlink()
            return
        print(
            f"CAS lost to concurrent sibling commit (attempt {attempt}); retrying "
            f"stderr={cas.stderr.strip()}"
        )
        time.sleep(1.5)
    raise SystemExit("failed to land isolated commit after retries")


if __name__ == "__main__":
    main()
