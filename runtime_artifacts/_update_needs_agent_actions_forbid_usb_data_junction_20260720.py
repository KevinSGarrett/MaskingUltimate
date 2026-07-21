"""Patch needs_agent_actions: binding FORBID of USB data/ junction; cite on-C confirm seal.

Recomputes self_sha256 (sorted-key compact JSON, excluding self_sha256).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
QUEUE = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
SEAL = REPO / "qa" / "live_verification" / "data_junction_on_c_confirmed_20260720T1500Z.json"


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short=8", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    data = json.loads(QUEUE.read_text(encoding="utf-8"))
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    prior_sha = data.get("self_sha256")
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    evidence_rel = "qa/live_verification/data_junction_on_c_confirmed_20260720T1500Z.json"

    forbid_action = {
        "action_id": "forbid_usb_data_junction",
        "status": "BINDING_POLICY_FORBIDDEN",
        "no_human_wait": True,
        "evidence": evidence_rel,
        "seal_self_sha256": seal.get("self_sha256"),
        "binding_policy": "usb_data_junction=FORBIDDEN",
        "statement": (
            "Agents MUST NOT re-junction repo data/ onto USB F: (F:\\MaskFactory_DataRelocated) "
            "or any other removable/hot-pluggable volume. Live target is and remains "
            "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated. F: is approved only for "
            "cold offload / read-when-present assets with graceful degrade on disconnect."
        ),
        "live_confirmed": {
            "junction_realpath": (seal.get("junction") or {}).get("realpath"),
            "resolves_on_c": True,
            "resolves_on_f": False,
            "packages": (seal.get("packages") or {}).get("count"),
        },
        "supersedes_stale_claims": [
            "Any residual note that data/ still targets F:\\MaskFactory_DataRelocated as the live sole copy.",
            "disk_headroom residual suggesting 'extend F: relocation' for the live data/ junction.",
        ],
        "unblocks": [
            "Removes agent ambiguity that could reintroduce a dangling data/ junction on the next USB disconnect.",
        ],
    }

    actions = data.setdefault("actions", [])
    ids = [a.get("action_id") for a in actions]
    if "forbid_usb_data_junction" in ids:
        actions[ids.index("forbid_usb_data_junction")] = forbid_action
    else:
        actions.append(forbid_action)

    # Correct stale dual-anchor finding: data/ is on C backup, not F:.
    for action in actions:
        if action.get("action_id") != "f_drive_usb_removable_dual_anchor_risk":
            continue
        action["data_junction_correction_20260720T1500"] = {
            "evidence": evidence_rel,
            "note": (
                "Live data/ junction is on C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated "
                "(confirmed). USB dual-anchor residual for data/ is CLOSED by forbid_usb_data_junction; "
                "Ubuntu-22.04 VHDX on F: remains the residual USB exposure for WSL only."
            ),
            "usb_data_junction": "FORBIDDEN",
        }
        action["risk"] = (
            "A future USB disconnect can still crash/attach-fail the Ubuntu-22.04 WSL distro "
            "whose ext4.vhdx lives on F:. The live data/ junction is NO LONGER on F: "
            "(forbidden + confirmed on C backup), so package/MASKFACTORY_DATA_PATH will not "
            "dangle solely from an F: unplug."
        )
        break

    for action in actions:
        if action.get("action_id") != "disk_headroom_above_75_gib":
            continue
        action["residual_agent_steps"] = [
            "Do NOT re-junction live data/ onto USB F:. Keep data/ -> data_c_backup_relocated.",
            "If future ingest needs more headroom, prefer a PERMANENT fixed second disk or "
            "governed cold offload mirrors on F: (read-when-present), never sole live junction on USB.",
        ]
        action["usb_data_junction_policy"] = "FORBIDDEN"
        action["on_c_confirm_evidence"] = evidence_rel
        break

    data["usb_data_junction_policy"] = {
        "status": "FORBIDDEN",
        "evidence": evidence_rel,
        "seal_self_sha256": seal.get("self_sha256"),
        "required_target": "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated",
        "forbidden_targets": [
            "F:\\MaskFactory_DataRelocated",
            "any USB/removable/hot-pluggable volume as sole live data/ target",
        ],
        "recorded_at": now,
    }

    host = data.setdefault("host_snapshot", {})
    host["data_drive"] = (
        "data/ junction -> C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated "
        "(CONFIRMED on-C; USB data junction FORBIDDEN)"
    )

    f_restored = data.get("f_drive_restored_20260720T1441") or {}
    dh = f_restored.setdefault("data_health", {})
    dh["junction_target"] = (
        "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated "
        "(on-C: backup; USB re-junction FORBIDDEN)"
    )
    dh["repoint_to_f"] = "FORBIDDEN (usb_data_junction_policy); do not auto-perform"
    dh["moved_this_update"] = False
    data["f_drive_restored_20260720T1441"] = f_restored

    data["data_junction_on_c_confirmed_20260720T1500"] = {
        "evidence": evidence_rel,
        "self_sha256": seal.get("self_sha256"),
        "verdict": seal.get("verdict"),
        "usb_data_junction": "FORBIDDEN",
    }

    data["latest_reverification"] = {
        "at": now,
        "by": "data_junction_on_c_confirmed",
        "evidence": evidence_rel,
        "healthy": True,
        "usb_data_junction": "FORBIDDEN",
        "junction_realpath": (seal.get("junction") or {}).get("realpath"),
    }
    data["project_head_at_authoring"] = git_head()
    data["recorded_at"] = now
    data["supersedes"] = {
        "path": "qa/live_verification/needs_agent_actions_20260720.json (prior self)",
        "prior_self_sha256": prior_sha,
        "reason": (
            "Binding FORBID of USB data/ junction after live confirm seal "
            "data_junction_on_c_confirmed_20260720T1500Z.json; correct stale dual-anchor "
            "language that implied live data/ still targeted F:."
        ),
    }

    payload = json.dumps(
        {k: v for k, v in data.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    data["self_sha256"] = hashlib.sha256(payload).hexdigest()
    QUEUE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(QUEUE.name, data["self_sha256"])
    print("forbid_action", forbid_action["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
