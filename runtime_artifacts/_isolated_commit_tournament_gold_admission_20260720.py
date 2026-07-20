"""Race-safe isolated commit of tournament/gold admission climb evidence only."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
MSG = ROOT / "runtime_artifacts/_commit_msg_tournament_gold_admission_climb_20260720.txt"
TMP_INDEX = ROOT / ".git/mf_tournament_gold_tmp_index"
OPS_MARKER = "tournament_gold_admission_climb_20260720T1506.json"
OPS_ENTRY = """
## 2026-07-20 15:06 UTC - Tournament/gold admission climb (F: restored, Docker mid-wave DOWN, 0 candidates)
**Item:** autonomous gold admission / machine_verified_candidate (production runs/)
**Command:** `python tools/gpu_sequencer.py plan --consumer nuclio-sam2|ollama-vlm`; `python runtime_artifacts/_scan_runs_status_20260720.py`; `python tools/build_autonomous_gold_admission.py --label torso --context solo --pipeline-fingerprint runtime-probe-20260720T1447 --output qa/live_verification/autonomous_gold_admission_20260720T1447.json`; Docker Desktop cold relaunch (non-destructive); `python runtime_artifacts/_seal_tournament_gold_admission_20260720T1506.py`
**Result:** HONEST FAIL-CLOSED. F: present (~127.6 GiB free). Gold SOURCE roots readable (MaskedWarehouse CelebAMask-HQ/LaPa/LV-MHP; F:\\Reference_Images; F:\\DAZ 25 top dirs). data/ kept on C: backup (USB auto-repoint FORBIDDEN; brief mis-repoint reverted). GPU sequencer: both nuclio-sam2 and ollama-vlm `run_now` (~7771 MiB free, sequential). Production runs/: 4462 json, **machine_verified_candidate=0**, calibrated_auto_accepted=0. Admission status `insufficient_autonomous_verified_samples` (certificate_minted=false, no fabrication). Docker engine crashed mid-wave (npipe missing); cold relaunch did not recover in window; host Ollama 0.32.1 stayed UP; host torch 2.12.1+cpu CUDA=false. champions=0; autonomous_certified_gold=0.

Evidence: qa/live_verification/tournament_gold_admission_climb_20260720T1506.json (self_sha256 5dac35ed1e74e857cf883d0d83453bb899e97754cb982ef42322142d4ede6f18); qa/live_verification/autonomous_gold_admission_20260720T1447.json (self_sha256 fe30a0123be32a6a1bbc7243f521348b2f8eb31a93afba77a5a47707e73a75d4).
"""
PATHS = [
    "Plan/OPS_LOG.md",
    "qa/live_verification/tournament_gold_admission_climb_20260720T1506.json",
    "qa/live_verification/autonomous_gold_admission_20260720T1447.json",
    "runtime_artifacts/_seal_tournament_gold_admission_20260720T1506.py",
    "runtime_artifacts/_scan_runs_status_20260720.py",
    "runtime_artifacts/_commit_msg_tournament_gold_admission_climb_20260720.txt",
    "runtime_artifacts/_isolated_commit_tournament_gold_admission_20260720.py",
]


def run(args: list[str], env: dict[str, str] | None = None, check: bool = True):
    return subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, check=check, env=env
    )


def ensure_ops_log() -> None:
    path = ROOT / "Plan/OPS_LOG.md"
    text = path.read_text(encoding="utf-8")
    if OPS_MARKER not in text:
        if not text.endswith("\n"):
            text += "\n"
        path.write_text(text + OPS_ENTRY + "\n", encoding="utf-8")


def main() -> None:
    ensure_ops_log()
    missing = [p for p in PATHS if not (ROOT / p).is_file()]
    if missing:
        raise SystemExit(f"missing paths: {missing}")
    if not MSG.is_file():
        raise SystemExit(f"missing commit message: {MSG}")
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
            f"CAS lost (attempt {attempt}); retrying stderr={cas.stderr.strip()}"
        )
        time.sleep(1.5)
    raise SystemExit("failed to land isolated commit after retries")


if __name__ == "__main__":
    main()
