"""Race-safe isolated commit of ComfyUI CUDA family re-smoke + invoke-path fix."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
MSG = ROOT / "runtime_artifacts" / "_commit_msg_families_resmoke_20260720T1652.txt"
TMP_INDEX = ROOT / ".git" / "mf_families_resmoke_1652_index"
PATHS = [
    "Plan/OPS_LOG.md",
    "models/model_registry.json",
    "src/maskfactory/models/smoke.py",
    "tools/smoke_birefnet_wsl.py",
    "tools/smoke_schp_wsl.py",
    "tools/smoke_faceparse_bisenet_wsl.py",
    "qa/live_verification/families_online_tournament_sibling_20260720T1652.json",
    "qa/live_verification/families_online_tournament_sibling_latest.json",
    "qa/live_verification/_birefnet_local_cuda_20260720T1652.json",
    "qa/live_verification/_schp_atr_local_cuda_20260720T1652.json",
    "qa/live_verification/_faceparse_local_cuda_20260720T1652.json",
    "qa/live_verification/_faceparse_20260720T1652.txt",
    "qa/live_verification/_gpu_plan_pipeline_families_20260720T1652.json",
    "runtime_artifacts/_bringup_families_tournament_sibling_20260720T1511.py",
    "runtime_artifacts/_smoke_birefnet_local_cuda_20260720.py",
    "runtime_artifacts/_smoke_schp_local_cuda_20260720.py",
    "runtime_artifacts/_isolated_commit_families_resmoke_20260720T1652.py",
    "runtime_artifacts/_commit_msg_families_resmoke_20260720T1652.txt",
]


def run(args: list[str], env: dict[str, str] | None = None, check: bool = True):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=check, env=env)


def main() -> None:
    MSG.write_text(
        "runtime(families): re-smoke 3 live CUDA families; fix BiRefNet Windows invoke\n\n"
        "Point birefnet/schp registry runners at ComfyUI local CUDA (copy-not-symlink), "
        "re-verify faceparse/birefnet/schp, and seal the >=3 family floor.\n",
        encoding="utf-8",
    )
    missing = [p for p in PATHS if not (ROOT / p).is_file()]
    if missing:
        raise SystemExit(f"missing paths: {missing}")
    faceparse = ROOT / "qa/live_verification/_faceparse_20260720T1652.txt"
    data = faceparse.read_bytes()
    if data and not data.endswith(b"\n"):
        faceparse.write_bytes(data + b"\n")
    for attempt in range(1, 12):
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        run(["git", "read-tree", head], env=env)
        add = run(["git", "add", "-f", "--", *PATHS], env=env, check=False)
        if add.returncode != 0:
            print(f"add failed attempt {attempt}: {add.stderr.strip()}")
            time.sleep(1.0)
            continue
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
            return
        print(
            f"CAS lost to concurrent sibling commit (attempt {attempt}); retrying "
            f"stderr={cas.stderr.strip()}"
        )
        time.sleep(1.5)
    raise SystemExit("failed to land isolated commit after retries")


if __name__ == "__main__":
    main()
