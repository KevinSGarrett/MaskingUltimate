"""Seal: retarget maskfactory-dvc-local to C: backup and verify status/push."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = (
    REPO_ROOT
    / "qa"
    / "live_verification"
    / "dvc_local_c_backup_verify_20260720T1503Z.json"
)


def main() -> int:
    evidence = {
        "artifact_type": "dvc_local_c_backup_verify",
        "authority": [
            "FULL AUTONOMY stream: sibling copied dvc_local_remote onto C: backup; verify dvc status -c / local push with data on C:; seal; commit+push",
            "Plan/OPS_LOG.md (this wave)",
            "qa/live_verification/c_vs_f_data_package_reconcile_20260720T1453Z.json",
        ],
        "branch": "codex/maskfactory-runtime-implementation",
        "claims_not_established": [
            "dvc_s3_cloud_push",
            "mf_p1_07_09_complete",
            "data_junction_on_f",
        ],
        "dvc": {
            "version": "3.67.1",
            "default_remote": "maskfactory-dvc-dev",
            "default_remote_url": "s3://maskfactory-dvc-dev",
            "local_remote_name": "maskfactory-dvc-local",
            "local_remote_url_before": "F:/MaskFactory_DataRelocated/dvc_local_remote",
            "local_remote_url_after": "C:/Comfy_UI_Main_Masking/data_c_backup_relocated/dvc_local_remote",
            "config_scope": ".dvc/config.local (gitignored)",
            "retarget_command": "dvc remote modify --local maskfactory-dvc-local url C:/Comfy_UI_Main_Masking/data_c_backup_relocated/dvc_local_remote",
        },
        "data_junction": {
            "path": "data/",
            "target": "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated",
            "on_c_backup": True,
            "not_rejunctioned_to_f": True,
        },
        "c_backup_remote": {
            "path": "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated\\dvc_local_remote",
            "files": 52,
            "bytes": 6349602,
            "present": True,
            "source": "sibling robocopy from F:\\MaskFactory_DataRelocated\\dvc_local_remote",
        },
        "verification": {
            "dvc_status_c_before_push": "Cache and remote 'maskfactory-dvc-local' are in sync.",
            "dvc_push_r_local": "Everything is up to date.",
            "dvc_status_c_after_push": "Cache and remote 'maskfactory-dvc-local' are in sync.",
            "exit_code": 0,
            "result": "PASS",
        },
        "f_drive": {
            "dvc_local_remote_still_present": True,
            "note": "F: copy left intact as secondary mirror; local remote intentionally retargeted to fixed-disk C: backup for disconnect resilience.",
        },
        "honesty_rules": [
            "Local-tier DVC only; cloud s3 push not attempted (dvc-s3/AWS creds absent on PATH dvc).",
            "No data/ re-junction to USB F:.",
            "No tier inflation; MF-P1-07.09 remains blocked on Kevin-authorized AWS push + eligible package.",
        ],
        "local_date": "2026-07-20",
        "project_head_at_authoring": "7f7c30ff144b3aa37bb37ddbcf3e15d65e1b46d6",
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": "1.0.0",
    }
    blob = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    evidence["self_sha256"] = digest
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"WROTE {OUTPUT} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
