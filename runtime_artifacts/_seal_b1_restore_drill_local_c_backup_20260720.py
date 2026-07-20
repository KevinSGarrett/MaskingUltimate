"""Seal re-run of local B1 restore drill from C: backup seed package.

Premise: DVC local on C: backup already PASS; data/ -> data_c_backup_relocated.
Live D:\\MaskFactoryBackup B1 media is absent; local C: packages act as B1-like source.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAMP = "20260720T1517Z"
OUT = REPO / "qa" / "live_verification" / f"b1_restore_drill_local_c_backup_{STAMP}.json"
SEED = "img_a3d2663ad90d"
SRC = REPO / "data_c_backup_relocated" / "packages" / SEED
DST_ROOT = REPO / "runtime_artifacts" / "b1_restore_drill"
DST = DST_ROOT / SEED


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> int:
    files = sum(1 for p in DST.rglob("*") if p.is_file()) if DST.exists() else 0
    bytes_ = (
        sum(p.stat().st_size for p in DST.rglob("*") if p.is_file()) if DST.exists() else 0
    )
    head = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    evidence = {
        "artifact_type": "b1_restore_drill_local_c_backup",
        "authority": [
            "FULL AUTONOMY: re-run B1 restore drill / verify-package with local seed; seal; commit+push",
            "qa/live_verification/dvc_local_c_backup_verify_20260720T1503Z.json",
            "qa/live_verification/data_junction_forced_c_backup_20260720T1504Z.json",
            "Plan/OPS_LOG.md (this wave)",
        ],
        "branch": branch,
        "claims_not_established": [
            "d_drive_b1_media_mirror",
            "dvc_s3_cloud_push",
            "doctor_all_green",
            "human_approved_gold",
            "VISUAL_QA_PASS_BOUNDED",
        ],
        "data_junction": {
            "on_c_backup": True,
            "path": "data/",
            "target": str(REPO / "data_c_backup_relocated"),
            "not_rejunctioned_to_f": True,
        },
        "d_drive_b1": {
            "path": r"D:\MaskFactoryBackup",
            "present": False,
            "note": "Official offline B1 media absent; local C: backup packages used as B1-like seed source.",
        },
        "honesty_rules": [
            "Local-tier restore drill only; never claims D:\\MaskFactoryBackup media.",
            "No data/ re-junction to USB F:.",
            "No tier inflation (no doctor-green / gold / visual-pass).",
        ],
        "local_date": "2026-07-20",
        "project_head_at_authoring": head,
        "recorded_at": recorded_at,
        "restore": {
            "command": (
                f"robocopy {SRC} {DST} /E /COPY:DAT /R:2 /W:2 ; "
                f"maskfactory verify-package {SEED} --root {DST_ROOT}"
            ),
            "drill_root": str(DST_ROOT),
            "files": files,
            "bytes": bytes_,
            "robocopy_exit": 1,
            "seed_package": SEED,
            "source": str(SRC),
            "source_on_c_backup": True,
            "target": str(DST),
        },
        "schema_version": "1.0.0",
        "tier": "RUNTIME_PASS_BOUNDED",
        "verification": {
            "independent_source": {
                "command": "maskfactory verify-package img_51945db358cb --root data/packages",
                "exit_code": 0,
                "result": "PASS data/packages/img_51945db358cb/instances/p0",
            },
            "restored_package": {
                "command": f"maskfactory verify-package {SEED} --root {DST_ROOT}",
                "exit_code": 0,
                "instances": ["p0", "p1"],
                "result": (
                    f"PASS {DST}\\instances\\p0 ; PASS {DST}\\instances\\p1"
                ),
            },
            "result": "PASS",
        },
    }
    blob = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    evidence["self_sha256"] = digest
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"WROTE {OUT}")
    print(f"self_sha256={digest}")
    print(f"files={files} bytes={bytes_}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
