"""Seal DAZ read-when-present STATIC evidence and CAS-commit+push in one process.

Uses unique timestamped binder paths from the seal document so parallel agents
cannot overwrite the bytes bound into the consolidated seal.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/maskfactory-runtime-implementation"
TMP_INDEX = ROOT / ".git" / "mf_daz_rw_sealcommit_tmp_index"
SEAL_SCRIPT = ROOT / "runtime_artifacts" / "_seal_daz_stream_read_when_present_20260720T1449.py"
SEAL = ROOT / "qa" / "live_verification" / "daz_stream_read_when_present_20260720T1449Z.json"
GOLD = ROOT / "qa" / "live_verification" / "_gold_volume_daz_present_20260720T1449.json"
MSG_PATH = ROOT / "runtime_artifacts" / "_commit_msg_daz_read_when_present_live_20260720.txt"

BASE_PATHS = [
    "Plan/OPS_LOG.md",
    "qa/live_verification/daz_stream_read_when_present_20260720T1449Z.json",
    "qa/live_verification/_gold_volume_daz_present_20260720T1449.json",
    "runtime_artifacts/_seal_daz_stream_read_when_present_20260720T1449.py",
    "runtime_artifacts/_seal_and_commit_daz_read_when_present_20260720.py",
    "runtime_artifacts/_commit_msg_daz_read_when_present_live_20260720.txt",
]


def run(args, env=None, check=True):
    return subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, check=check, env=env
    )


def restore_bytes(snapshot: dict[str, bytes]) -> None:
    for path, payload in snapshot.items():
        Path(path).write_bytes(payload)


def main() -> int:
    if not Path(r"F:\DAZ").is_dir() or len(list(Path(r"F:\DAZ").iterdir())) != 26:
        raise SystemExit("f_daz_not_ready")

    sealed = run([sys.executable, str(SEAL_SCRIPT)], check=False)
    sys.stdout.write(sealed.stdout)
    if sealed.returncode != 0:
        sys.stderr.write(sealed.stderr)
        raise SystemExit(f"seal_failed:{sealed.returncode}")

    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    binder_rels = [
        seal["binders"]["validation_static_contracts"]["path"],
        seal["binders"]["ops_static_contracts"]["path"],
        seal["binders"]["coverage_planner_static"]["path"],
    ]
    for rel in binder_rels:
        path = ROOT / rel
        if not path.is_file():
            raise SystemExit(f"missing_unique_binder:{rel}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        key = {
            binder_rels[0]: "validation_static_contracts",
            binder_rels[1]: "ops_static_contracts",
            binder_rels[2]: "coverage_planner_static",
        }[rel]
        if digest != seal["binders"][key]["file_sha256"]:
            raise SystemExit(f"unique_binder_mismatch:{key}")

    snapshot: dict[str, bytes] = {
        str(SEAL): SEAL.read_bytes(),
        str(GOLD): GOLD.read_bytes(),
    }
    for rel in binder_rels:
        snapshot[str(ROOT / rel)] = (ROOT / rel).read_bytes()

    self_sha = seal["self_sha256"]
    binders = {
        k: v["report_id"] for k, v in seal["binders"].items() if v.get("report_id")
    }
    doctor = seal["daz_foundation_doctor"]
    ops_entry = f"""
## 2026-07-20 15:14 UTC - DAZ read-when-present STATIC seal+commit (unique binder paths)
**Item:** MF-P9-08 / 10 / 12 STATIC (F:\\\\DAZ read-when-present, 26 entries)
**Command:** python runtime_artifacts/_seal_and_commit_daz_read_when_present_20260720.py
**Result:** STATIC_PASS. Unique timestamped binder paths bound into seal (parallel-safe). F:\\\\DAZ present (26); gold_volume daz present/readable; soft_capacity_only={doctor.get('soft_capacity_only')} free_gib={doctor.get('free_gib')}; binders {binders}; pytest={seal.get('pytest_exit_code')}. No live Studio/gold/pilot/soak.

Evidence: qa/live_verification/daz_stream_read_when_present_20260720T1449Z.json (self_sha256 {self_sha}).
"""
    ops_path = ROOT / "Plan" / "OPS_LOG.md"
    ops_marker = f"self_sha256 {self_sha}"
    if ops_marker not in ops_path.read_text(encoding="utf-8", errors="replace"):
        with open(ops_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(ops_entry)

    for rel in (
        "runtime_artifacts/_seal_daz_stream_read_when_present_20260720T1449.py",
        "runtime_artifacts/_seal_and_commit_daz_read_when_present_20260720.py",
    ):
        snapshot[str(ROOT / rel)] = (ROOT / rel).read_bytes()

    MSG_PATH.write_text(
        "qa(daz): seal+commit read-when-present STATIC via unique binder paths\n\n"
        "Bind validation/ops/coverage to timestamped evidence files so parallel "
        "agents cannot overwrite sealed hashes; soft storage floor noted; no live "
        "Studio/gold claims.\n",
        encoding="utf-8",
        newline="\n",
    )
    snapshot[str(MSG_PATH)] = MSG_PATH.read_bytes()

    paths = BASE_PATHS + binder_rels
    cov_rel = seal["binders"]["coverage_planner_static"]["path"]
    cov_digest = seal["binders"]["coverage_planner_static"]["file_sha256"]

    for attempt in range(1, 20):
        restore_bytes(snapshot)
        if ops_marker not in ops_path.read_text(encoding="utf-8", errors="replace"):
            with open(ops_path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(ops_entry)

        run(["git", "fetch", "origin", BRANCH], check=False)
        head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
        remote = run(
            ["git", "rev-parse", f"refs/remotes/origin/{BRANCH}"], check=False
        ).stdout.strip()
        if remote and remote != head:
            if (
                run(
                    ["git", "merge-base", "--is-ancestor", head, remote], check=False
                ).returncode
                == 0
            ):
                run(["git", "update-ref", f"refs/heads/{BRANCH}", remote])
                head = remote

        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(TMP_INDEX)
        if TMP_INDEX.exists():
            TMP_INDEX.unlink()
        restore_bytes(snapshot)
        run(["git", "read-tree", head], env=env)
        restore_bytes(snapshot)
        run(["git", "add", "--", *paths], env=env)
        tree = run(["git", "write-tree"], env=env).stdout.strip()
        cov_blob = run(["git", "ls-tree", tree, "--", cov_rel], env=env).stdout.strip()
        if not cov_blob:
            print(f"missing coverage in tree (attempt {attempt})")
            time.sleep(0.8)
            continue
        blob_sha = cov_blob.split()[2]
        blob = subprocess.run(
            ["git", "cat-file", "-p", blob_sha],
            cwd=ROOT,
            capture_output=True,
            check=True,
            env=env,
        ).stdout
        if hashlib.sha256(blob).hexdigest() != cov_digest:
            print(f"tree coverage drift (attempt {attempt})")
            time.sleep(0.8)
            continue

        commit = run(
            ["git", "commit-tree", tree, "-p", head, "-F", str(MSG_PATH)]
        ).stdout.strip()
        cas = run(
            ["git", "update-ref", f"refs/heads/{BRANCH}", commit, head],
            check=False,
        )
        if cas.returncode != 0:
            print(f"local CAS lost (attempt {attempt})")
            time.sleep(0.8)
            continue

        push = run(
            ["git", "push", "origin", f"{commit}:refs/heads/{BRANCH}"], check=False
        )
        if push.returncode == 0:
            run(["git", "update-ref", f"refs/heads/{BRANCH}", commit])
            print(f"PUSHED {commit}")
            print(f"HEAD {commit}")
            print(f"self_sha256 {self_sha}")
            print(f"binders {binders}")
            print(f"unique_binders {binder_rels}")
            print(f"doctor {doctor}")
            if TMP_INDEX.exists():
                TMP_INDEX.unlink()
            return 0

        print(f"push rejected (attempt {attempt}): {push.stderr.strip()[:240]}")
        run(["git", "fetch", "origin", BRANCH], check=False)
        remote = run(
            ["git", "rev-parse", f"refs/remotes/origin/{BRANCH}"]
        ).stdout.strip()
        run(["git", "update-ref", f"refs/heads/{BRANCH}", remote])
        time.sleep(0.8)

    raise SystemExit("failed_seal_and_push")


if __name__ == "__main__":
    raise SystemExit(main())
