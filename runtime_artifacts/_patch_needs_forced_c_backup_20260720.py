"""Merge forced-C junction forbid into needs_agent_actions (sibling-safe)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NEEDS = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
SEAL = REPO / "qa" / "live_verification" / "data_junction_forced_c_backup_20260720T1504Z.json"


def main() -> int:
    rel = SEAL.relative_to(REPO).as_posix()
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    data = json.loads(NEEDS.read_text(encoding="utf-8"))
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    target = r"C:\Comfy_UI_Main_Masking\data_c_backup_relocated"

    pol = data.setdefault("usb_data_junction_policy", {})
    pol["status"] = "FORBIDDEN"
    pol["auto_repoint_to_f"] = "FORBIDDEN"
    pol["required_target"] = target
    pol["forbidden_targets"] = [
        r"F:\MaskFactory_DataRelocated",
        "any USB/removable/hot-pluggable volume as sole live data/ target",
    ]
    pol["evidence"] = rel
    pol["forced_seal_self_sha256"] = seal["self_sha256"]
    pol["also_see"] = "qa/live_verification/data_junction_on_c_confirmed_20260720T1500Z.json"
    pol["recorded_at"] = now

    data["data_junction_forced_c_backup"] = {
        "evidence": rel,
        "self_sha256": seal["self_sha256"],
        "package_count": seal["packages"]["count"],
        "junction_target": seal["junction"]["expected_target"],
        "usb_data_junction": "FORBIDDEN",
        "auto_repoint_to_f": "FORBIDDEN",
        "mutation_performed": seal["mutation"]["performed"],
    }

    if "f_drive_restored_20260720T1441" in data:
        dh = data["f_drive_restored_20260720T1441"].setdefault("data_health", {})
        dh["junction_target"] = target + " (on-C: backup; FORCED)"
        dh["active_package_count"] = seal["packages"]["count"]
        dh["repoint_to_f"] = "FORBIDDEN (usb_data_junction_policy); do not auto-perform"
        dh["moved_this_update"] = False

    hs = data.setdefault("host_snapshot", {})
    hs["data_drive"] = (
        f"data/ junction -> {target} (on-C: backup, {seal['packages']['count']} pkgs); "
        "auto-repoint to USB F: FORBIDDEN"
    )

    for action in data["actions"]:
        aid = action.get("action_id")
        if aid == "disk_headroom_above_75_gib":
            action["usb_data_junction_policy"] = "FORBIDDEN"
            action["forced_c_backup_evidence"] = rel
            action["residual_agent_steps"] = [
                "Do NOT re-junction live data/ onto USB F:. Keep data/ -> data_c_backup_relocated.",
                "If future ingest needs more headroom, prefer a PERMANENT fixed second disk or "
                "governed cold offload mirrors on F: (read-when-present), never sole live "
                "junction on USB.",
            ]
        if aid == "dvc_push_local_first":
            note = action.get("f_restored_reverification_20260720T1441")
            if isinstance(note, dict):
                note["repoint_to_f"] = "FORBIDDEN"
                note["note"] = (
                    r"F:\MaskFactory_DataRelocated\dvc_local_remote may be reachable when F: "
                    f"is present; data/ junction MUST stay on {target}. "
                    "Auto-repoint to F: is FORBIDDEN."
                )
        if aid == "f_drive_usb_removable_dual_anchor_risk":
            action["data_junction_correction_20260720"] = {
                "evidence": rel,
                "note": (
                    f"Live data/ junction is on {target}. USB dual-anchor residual for data/ "
                    "is CLOSED; Ubuntu-22.04 VHDX on F: remains the residual USB exposure "
                    "for WSL only."
                ),
                "usb_data_junction": "FORBIDDEN",
                "auto_repoint_to_f": "FORBIDDEN",
            }
            action["risk"] = (
                "A future USB disconnect can still crash/attach-fail the Ubuntu-22.04 WSL "
                "distro whose ext4.vhdx lives on F:. The live data/ junction is NO LONGER "
                "on F: (forbidden + forced on C backup), so package/MASKFACTORY_DATA_PATH "
                "will not dangle solely from an F: unplug."
            )
            action["finding"] = (
                "F: is a USB-attached Seagate BUP Slim (BusType=USB). Live data/ junction "
                f"target is {target} (forced/confirmed). F: may still host WSL "
                "Ubuntu-22.04 VHDX + cold mirrors; never the sole live data/ target."
            )
        if aid == "forbid_usb_data_junction":
            action["status"] = "DONE_BINDING_POLICY"
            action["binding_policy"] = "usb_data_junction=FORBIDDEN; auto_repoint_to_f=FORBIDDEN"
            action["evidence"] = rel
            action["executed"] = (
                f"Confirmed/forced data/ -> {target}. Package count via junction="
                f"{seal['packages']['count']}. maskfactory reindex --dry-run readable. "
                "Auto-repoint to F: forbidden for all agents."
            )
            action["no_human_wait"] = True

    ids = [a.get("action_id") for a in data["actions"]]
    if "forbid_usb_data_junction" not in ids:
        data["actions"].append(
            {
                "action_id": "forbid_usb_data_junction",
                "status": "DONE_BINDING_POLICY",
                "binding_policy": ("usb_data_junction=FORBIDDEN; auto_repoint_to_f=FORBIDDEN"),
                "evidence": rel,
                "executed": (
                    f"Confirmed/forced data/ -> {target}. Package count via junction="
                    f"{seal['packages']['count']}. Auto-repoint to F: FORBIDDEN."
                ),
                "no_human_wait": True,
                "unblocks": ["Removes data/ dangling-junction exposure on USB disconnect"],
            }
        )

    data["latest_reverification"] = {
        "at": now,
        "by": "data_junction_forced_c_backup",
        "evidence": rel,
        "package_count": seal["packages"]["count"],
        "junction_target": target,
        "usb_data_junction": "FORBIDDEN",
        "auto_repoint_to_f": "FORBIDDEN",
        "also_see": ("qa/live_verification/data_junction_on_c_confirmed_20260720T1500Z.json"),
    }
    data["recorded_at"] = now
    data["supersedes"] = {
        "path": "qa/live_verification/needs_agent_actions_20260720.json (prior self)",
        "reason": (
            f"Binding FORBID of USB data/ auto-repoint after forced-C seal {SEAL.name}; "
            "correct stale language that allowed reversible repoint to F:."
        ),
    }
    payload = json.dumps(
        {k: v for k, v in data.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    data["self_sha256"] = hashlib.sha256(payload).hexdigest()
    NEEDS.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("OK", data["self_sha256"])
    print("auto_repoint", data["usb_data_junction_policy"]["auto_repoint_to_f"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
