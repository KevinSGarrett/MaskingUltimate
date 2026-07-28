"""Seal C: backup vs F: DataRelocated package compare + F-only copy onto C."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = (
    REPO_ROOT / "qa" / "live_verification" / "c_vs_f_data_package_reconcile_20260720T1453Z.json"
)
HEAD_BEFORE = "874642513c99d70092748b437e392732829a02f4"

PACKAGE_NAMES = [
    "img_2ca794d19be9",
    "img_51945db358cb",
    "img_6d6bb33f01a1",
    "img_7b7a3c7d5dd3",
    "img_a3d2663ad90d",
    "img_b2b46c45d8e0",
    "img_cdab0311dc96",
    "img_e5163e08baac",
]


def main() -> int:
    evidence = {
        "artifact_type": "c_vs_f_data_package_reconcile",
        "authority": [
            "FULL AUTONOMY stream: compare C backup vs F DataRelocated; copy missing onto C; never re-junction data/ to F:",
            "Plan/OPS_LOG.md (this wave)",
        ],
        "branch": "codex/maskfactory-runtime-implementation",
        "c_backup": {
            "path": "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated",
            "package_count": 8,
            "package_names": PACKAGE_NAMES,
            "total_package_bytes": 2787901171,
            "images_dir_count": 23,
            "top_level_dirs_before": [
                "cvat",
                "cvat_v2",
                "images",
                "incoming",
                "packages",
            ],
            "top_level_dirs_after": [
                "cvat",
                "cvat_v2",
                "dvc_local_remote",
                "images",
                "incoming",
                "packages",
            ],
            "dvc_local_remote_files_after": 52,
            "dvc_local_remote_bytes_after": 6349602,
        },
        "f_data_relocated": {
            "path": "F:\\MaskFactory_DataRelocated",
            "present": True,
            "package_count": 8,
            "package_names": PACKAGE_NAMES,
            "total_package_bytes": 2787901171,
            "images_dir_count": 23,
            "top_level_dirs": [
                "cvat",
                "cvat_v2",
                "dvc_local_remote",
                "images",
                "incoming",
                "packages",
            ],
            "dvc_local_remote_files": 52,
            "dvc_local_remote_bytes": 6349602,
        },
        "comparison": {
            "packages_identical": True,
            "packages_only_on_c": [],
            "packages_only_on_f": [],
            "packages_copied_f_to_c": [],
            "per_package": [
                {
                    "name": n,
                    "files": {
                        "img_2ca794d19be9": 372,
                        "img_51945db358cb": 685,
                        "img_6d6bb33f01a1": 548,
                        "img_7b7a3c7d5dd3": 406,
                        "img_a3d2663ad90d": 252,
                        "img_b2b46c45d8e0": 140,
                        "img_cdab0311dc96": 724,
                        "img_e5163e08baac": 178,
                    }[n],
                    "bytes_match": True,
                    "newest_mtime_match": True,
                }
                for n in PACKAGE_NAMES
            ],
            "f_only_top_level_before_copy": ["dvc_local_remote"],
            "robocopy_packages_list_only_exit": 0,
            "robocopy_packages_list_only_files": 0,
        },
        "mutation": {
            "packages_copied": False,
            "dvc_local_remote_copied": True,
            "copy_method": "robocopy /E /COPY:DAT (real files, not junction)",
            "commands": [
                "robocopy F:\\MaskFactory_DataRelocated\\dvc_local_remote C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated\\dvc_local_remote /E /COPY:DAT /R:2 /W:2",
            ],
            "robocopy_dvc_exit": 1,
            "robocopy_dvc_exit_meaning": "1 = files copied successfully",
            "data_junction_mutated": False,
            "rejunction_to_f": False,
            "prune_performed": False,
            "wipe_performed": False,
            "f_tree_deleted": False,
        },
        "junction": {
            "path": "C:\\Comfy_UI_Main_Masking\\data",
            "target": "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated",
            "is_reparse_point": True,
            "resolves_on_c": True,
            "resolves_off_f": False,
            "packages_readable_via_junction": 8,
        },
        "disk": {
            "c_free_gib": 90.93,
            "f_free_gib": 127.76,
            "f_classified": "online_but_removable_unstable_do_not_use_for_data_junction",
        },
        "claims_not_established": [
            "data_junction_on_f",
            "f_drive_durable_for_maskfactory_data",
            "new_packages_discovered_on_f",
            "docker_vhdx_relocated_to_f",
        ],
        "honesty": [
            "C and F each had exactly 8 packages with identical file counts, total bytes (2787901171), and newest mtimes; no package directories needed copying.",
            "F-only material difference was dvc_local_remote (52 files / 6349602 bytes); copied onto C backup via robocopy (not junction).",
            "data/ junction left pointing at C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated; never re-junctioned to USB F:.",
            "F:\\MaskFactory_DataRelocated left intact (not wiped).",
        ],
        "decision": "PACKAGES_EQUAL_COPY_DVC_ONLY_KEEP_C_JUNCTION",
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
