"""Seal abort of data/ -> F: re-junction; keep C: backup target."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "qa" / "live_verification" / "data_junction_abort_f_keep_c_20260720T1438Z.json"
HEAD_BEFORE = "ddbb0d43eb079ece8c3047f368ccd8c1747bdf9a"


def main() -> int:
    evidence = {
        "artifact_type": "data_junction_abort_f_keep_c",
        "authority": [
            "explicit abort: F: is removable/unstable; keep data/ on C: data_c_backup_relocated",
            "Plan/OPS_LOG.md (this wave)",
        ],
        "branch": "codex/maskfactory-runtime-implementation",
        "c_free_gib": 91.31,
        "claims_not_established": [
            "data_junction_on_f",
            "f_drive_durable_for_maskfactory_data",
            "docker_vhdx_relocated_to_f",
        ],
        "decision": "ABORT_F_REJUNCTION_KEEP_C_BACKUP",
        "f_present": True,
        "f_free_gib": 181.21,
        "f_status": "online_but_removable_unstable_do_not_use_for_data_junction",
        "honesty": [
            "Found data/ already pointing at F:\\MaskFactory_DataRelocated; immediately reverted.",
            "F: copy left intact at F:\\MaskFactory_DataRelocated (not deleted).",
            "C: backup directory left as real directory; data/ is a junction onto it.",
        ],
        "junction": {
            "path": "C:\\Comfy_UI_Main_Masking\\data",
            "target_after": "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated",
            "target_before": "F:\\MaskFactory_DataRelocated",
            "is_reparse_point": True,
            "resolves_on_c": True,
            "resolves_off_f": False,
        },
        "mutation": {
            "commands": [
                "rmdir C:\\Comfy_UI_Main_Masking\\data",
                "mklink /J C:\\Comfy_UI_Main_Masking\\data C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated",
            ],
            "prune_performed": False,
            "wipe_performed": False,
            "f_tree_deleted": False,
        },
        "packages": {
            "count": 8,
            "names": [
                "img_2ca794d19be9",
                "img_51945db358cb",
                "img_6d6bb33f01a1",
                "img_7b7a3c7d5dd3",
                "img_a3d2663ad90d",
                "img_b2b46c45d8e0",
                "img_cdab0311dc96",
                "img_e5163e08baac",
            ],
            "readable_via_junction": True,
        },
        "project_head_at_authoring": HEAD_BEFORE,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": "1.0.0",
        "self_sha256": "",
    }
    payload = json.dumps(
        {k: v for k, v in evidence.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    OUTPUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT.name, evidence["self_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
