"""Patch needs_agent_actions dvc_push_local_first with C: backup retarget proof."""

from __future__ import annotations

import json
from pathlib import Path

PATH = Path("qa/live_verification/needs_agent_actions_20260720.json")


def main() -> int:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    # File shape uses top-level list under "actions" or nested; probe keys
    container = None
    key = None
    for candidate in ("actions", "actions_remaining", "queue", "items"):
        if isinstance(data.get(candidate), list):
            container = data[candidate]
            key = candidate
            break
    if container is None:
        raise SystemExit(f"no actions list found; keys={sorted(data)}")

    updated = False
    for item in container:
        if item.get("action_id") != "dvc_push_local_first":
            continue
        item["c_backup_retarget_20260720T1503"] = {
            "evidence": "qa/live_verification/dvc_local_c_backup_verify_20260720T1503Z.json",
            "local_remote_url": "C:/Comfy_UI_Main_Masking/data_c_backup_relocated/dvc_local_remote",
            "dvc_status_c": "Cache and remote are in sync",
            "dvc_push": "Everything is up to date",
            "note": (
                "Retargeted maskfactory-dvc-local from F: USB DataRelocated onto the "
                "sibling-copied C: backup dvc_local_remote; local push/status verified."
            ),
        }
        item["executed"] = (
            "dvc 3.67.1; local remote maskfactory-dvc-local retargeted to "
            "C:/Comfy_UI_Main_Masking/data_c_backup_relocated/dvc_local_remote "
            "(52 files / 6.35 MB); dvc status -c in sync; dvc push -> Everything is up to date. "
            "Prior F: drill retained as secondary mirror. Cloud s3 still deferred."
        )
        item["evidence"] = (
            "qa/live_verification/dvc_local_c_backup_verify_20260720T1503Z.json"
            " (also qa/live_verification/agent_queue_execution_20260719T2300.json prior F: drill)"
        )
        item["status"] = "DONE_LOCAL_TIER"
        updated = True
        break

    if not updated:
        raise SystemExit("dvc_push_local_first action not found")

    PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"UPDATED {PATH} key={key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
