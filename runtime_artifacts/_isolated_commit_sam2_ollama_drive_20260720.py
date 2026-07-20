"""Race-safe isolated commit of SAM2+Ollama autonomous-gold drive evidence only."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
TMP_INDEX = ROOT / ".git/mf_sam2_ollama_drive_tmp_index"
MSG_PATH = ROOT / "runtime_artifacts/_commit_msg_sam2_ollama_drive_20260720.txt"
PATHS = [
    "qa/live_verification/autonomous_gold_sam2_ollama_drive_20260720T1520.json",
    "qa/live_verification/autonomous_gold_admission_sam2_ollama_20260720T1017.json",
    "qa/live_verification/gpu_sequence_sam2_20260720T1445.json",
    "runtime_artifacts/_seal_autonomous_gold_sam2_ollama_drive_20260720.py",
    "runtime_artifacts/_isolated_commit_sam2_ollama_drive_20260720.py",
    "runtime_artifacts/_commit_msg_sam2_ollama_drive_20260720.txt",
]
# OPS_LOG is contended across parallel agents; evidence JSONs are the sealed authority.
MSG = """evidence(gold): seal honest SAM2+Ollama autonomous-gold drive (MVC=0)

Nuclio SAM2 smoke failed 503 then Docker engine DOWN after restart; Ollama VLM critic PASS. Admission remains insufficient_autonomous_verified_samples with zero machine_verified_candidate — no fabrication.
"""


def run(args: list[str], env: dict[str, str] | None = None, check: bool = True):
    return subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, check=check, env=env
    )


def main() -> None:
    MSG_PATH.write_text(MSG, encoding="utf-8")
    missing = [p for p in PATHS if not (ROOT / p).is_file()]
    if missing:
        raise SystemExit(f"missing paths: {missing}")

    for attempt in range(1, 12):
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        run(["git", "read-tree", head], env=env)
        run(["git", "add", "--", *PATHS], env=env)
        tree = run(["git", "write-tree"], env=env).stdout.strip()
        commit = run(
            ["git", "commit-tree", tree, "-p", head, "-F", str(MSG_PATH)]
        ).stdout.strip()
        cas = run(
            ["git", "update-ref", f"refs/heads/{BRANCH}", commit, head],
            check=False,
        )
        if cas.returncode == 0:
            print(f"committed {commit} parent {head} (attempt {attempt})")
            if TMP_INDEX.exists():
                TMP_INDEX.unlink()
            short = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
            print(f"HEAD {short}")
            return
        print(
            f"CAS lost (attempt {attempt}); retrying stderr={cas.stderr.strip()}"
        )
        time.sleep(1.5)
    raise SystemExit("failed to land isolated commit after retries")


if __name__ == "__main__":
    main()
