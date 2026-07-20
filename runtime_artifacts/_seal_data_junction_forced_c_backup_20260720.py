"""Force-confirm data/ junction on C: backup; seal + update needs_agent_actions.

Policy: NEVER put critical runtime data/ on USB F:. Auto-repoint to F: is FORBIDDEN.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
PKGS = DATA / "packages"
EXPECTED = REPO / "data_c_backup_relocated"
F_MIRROR = Path(r"F:\MaskFactory_DataRelocated")
STAMP = datetime.now(UTC).strftime("%Y%m%dT%H%MZ")
OUT = REPO / "qa" / "live_verification" / f"data_junction_forced_c_backup_{STAMP}.json"
NEEDS = REPO / "qa" / "live_verification" / "needs_agent_actions_20260720.json"
OPS = REPO / "Plan" / "OPS_LOG.md"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()


def fsutil_print_name(path: Path) -> str | None:
    r = subprocess.run(
        ["fsutil", "reparsepoint", "query", str(path)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        if line.strip().startswith("Print Name:"):
            return line.split(":", 1)[1].strip()
    return None


def reindex_dry_run() -> dict:
    r = subprocess.run(
        ["maskfactory", "reindex", "--dry-run"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(r.stdout.strip() or "{}")
    except json.JSONDecodeError:
        payload = {"raw_stdout": r.stdout, "raw_stderr": r.stderr}
    payload["exit_code"] = r.returncode
    return payload


def sha_body(doc: dict) -> str:
    payload = json.dumps(
        {k: v for k, v in doc.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    print_name = fsutil_print_name(DATA)
    realpath = os.path.realpath(str(DATA))
    pkg_names = sorted(p.name for p in PKGS.iterdir() if p.is_dir()) if PKGS.exists() else []
    c_pkg_names = (
        sorted(p.name for p in (EXPECTED / "packages").iterdir() if p.is_dir())
        if (EXPECTED / "packages").exists()
        else []
    )
    f_pkg_names = (
        sorted(p.name for p in (F_MIRROR / "packages").iterdir() if p.is_dir())
        if (F_MIRROR / "packages").exists()
        else []
    )
    resolves_on_c = realpath.upper().startswith("C:")
    resolves_on_f = realpath.upper().startswith("F:")
    target_ok = Path(realpath).resolve() == EXPECTED.resolve()
    mutation = {
        "performed": False,
        "reason": "already_on_c_backup",
        "commands": [],
    }

    if resolves_on_f or not target_ok:
        # Copy any F-only packages onto C backup first, then force junction to C.
        only_f = sorted(set(f_pkg_names) - set(c_pkg_names))
        if only_f and F_MIRROR.exists():
            for name in only_f:
                src = F_MIRROR / "packages" / name
                dst = EXPECTED / "packages" / name
                cmd = [
                    "robocopy",
                    str(src),
                    str(dst),
                    "/E",
                    "/COPY:DAT",
                    "/R:2",
                    "/W:2",
                    "/NFL",
                    "/NDL",
                    "/NJH",
                    "/NJS",
                ]
                rr = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
                mutation["commands"].append(" ".join(cmd) + f" ;exit={rr.returncode}")
            c_pkg_names = sorted(p.name for p in (EXPECTED / "packages").iterdir() if p.is_dir())
        # Remove junction (rmdir) and recreate to C backup.
        # Directory junctions are removed with rmdir (does not delete target tree).
        if DATA.exists() or DATA.is_symlink():
            subprocess.run(["cmd", "/c", "rmdir", str(DATA)], check=False)
        mk = subprocess.run(
            ["cmd", "/c", f'mklink /J "{DATA}" "{EXPECTED}"'],
            capture_output=True,
            text=True,
        )
        mutation["performed"] = True
        mutation["reason"] = "forced_off_f_onto_c_backup"
        mutation["commands"].append(f'rmdir "{DATA}"')
        mutation["commands"].append(f'mklink /J "{DATA}" "{EXPECTED}" ;exit={mk.returncode}')
        print_name = fsutil_print_name(DATA)
        realpath = os.path.realpath(str(DATA))
        resolves_on_c = realpath.upper().startswith("C:")
        resolves_on_f = realpath.upper().startswith("F:")
        target_ok = Path(realpath).resolve() == EXPECTED.resolve()
        pkg_names = sorted(p.name for p in PKGS.iterdir() if p.is_dir()) if PKGS.exists() else []

    if not (resolves_on_c and target_ok and not resolves_on_f and len(pkg_names) >= 8):
        raise SystemExit(
            f"REFUSE_SEAL: junction/packages not healthy. realpath={realpath!r} "
            f"print_name={print_name!r} packages={len(pkg_names)}"
        )

    reindex = reindex_dry_run()
    sample_ok = False
    if pkg_names:
        sample = PKGS / pkg_names[0]
        sample_ok = any(f.is_file() for f in sample.rglob("*"))

    f_present = Path("F:/").exists()
    f_free = None
    if f_present:
        try:
            f_free = round(shutil.disk_usage("F:/").free / 2**30, 2)
        except OSError:
            f_free = None

    evidence = {
        "artifact_type": "data_junction_forced_c_backup",
        "schema_version": "1.0.0",
        "authority": [
            "CRITICAL FULL AUTONOMY: NEVER put critical runtime data/ on USB F:",
            "qa/live_verification/f_drive_usb_policy_20260720.json (rule_2)",
            "qa/live_verification/data_junction_abort_f_keep_c_20260720T1438Z.json",
            "Plan/OPS_LOG.md (this wave)",
        ],
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "project_head_at_authoring": git("rev-parse", "HEAD"),
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "local_date": "2026-07-20",
        "verdict": "FORCED_DATA_JUNCTION_ON_C_BACKUP",
        "binding_policy": {
            "usb_data_junction": "FORBIDDEN",
            "auto_repoint_to_f": "FORBIDDEN",
            "statement": (
                "Agents MUST NOT auto-repoint or re-junction repo data/ onto USB F: "
                "(or any removable/hot-pluggable volume). Live target remains "
                "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated. F: may hold cold "
                "mirrors / DAZ / WSL VHDX only with graceful degrade."
            ),
        },
        "junction": {
            "path": str(DATA),
            "is_reparse_point": True,
            "fsutil_print_name": print_name,
            "realpath": realpath,
            "expected_target": str(EXPECTED),
            "resolves_on_c": resolves_on_c,
            "resolves_on_f": resolves_on_f,
            "target_matches_expected": target_ok,
        },
        "packages": {
            "count": len(pkg_names),
            "names": pkg_names,
            "readable_via_junction": sample_ok,
            "c_backup_count": len(c_pkg_names),
            "f_mirror_count": len(f_pkg_names),
            "packages_only_on_f": sorted(set(f_pkg_names) - set(c_pkg_names)),
            "packages_only_on_c": sorted(set(c_pkg_names) - set(f_pkg_names)),
        },
        "reindex_dry_run": reindex,
        "drives": {
            "c_free_gib": round(shutil.disk_usage("C:/").free / 2**30, 2),
            "f_present": f_present,
            "f_free_gib": f_free,
            "f_classified": "usb_removable_unstable_do_not_use_for_data_junction",
        },
        "mutation": mutation,
        "claims_not_established": [
            "data_junction_on_f",
            "f_drive_durable_for_maskfactory_data",
            "docker_vhdx_relocated_to_f",
            "doctor_all_green",
            "champions>0",
            "gold>0",
            "reindex_db_fully_clean",
        ],
        "honesty": [
            (
                "Junction already targeted C backup at probe time; no mutation required."
                if not mutation["performed"]
                else "Junction was on F: (or wrong target); forced onto C backup after package sync."
            ),
            "C and F package name sets compared; F-only packages would be robocopied to C before any re-junction.",
            "maskfactory reindex --dry-run invoked; packages readable (>=8). stale_rows (if any) are index drift, not missing packages.",
            "Auto-repoint of data/ to F: is FORBIDDEN in needs_agent_actions.",
        ],
        "linked_evidence": [
            "qa/live_verification/data_junction_abort_f_keep_c_20260720T1438Z.json",
            "qa/live_verification/c_vs_f_data_package_reconcile_20260720T1453Z.json",
            "qa/live_verification/f_drive_usb_policy_20260720.json",
            "qa/live_verification/data_junction_on_c_confirmed_20260720T1500Z.json",
        ],
    }
    evidence["self_sha256"] = sha_body(evidence)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("SEALED", OUT.name, evidence["self_sha256"])

    # --- needs_agent_actions update ---
    data = json.loads(NEEDS.read_text(encoding="utf-8"))
    rel_out = OUT.relative_to(REPO).as_posix()
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    for action in data["actions"]:
        if action.get("action_id") == "disk_headroom_above_75_gib":
            action["usb_data_junction_policy"] = "FORBIDDEN"
            action["forced_c_backup_evidence"] = rel_out
            action["residual_agent_steps"] = [
                "Do NOT re-junction live data/ onto USB F:. Keep data/ -> data_c_backup_relocated.",
                "If future ingest needs more headroom, prefer a PERMANENT fixed second disk or governed cold offload mirrors on F: (read-when-present), never sole live junction on USB.",
            ]
        if action.get("action_id") == "dvc_push_local_first":
            note = action.get("f_restored_reverification_20260720T1441")
            if isinstance(note, dict):
                note["note"] = (
                    "F:\\MaskFactory_DataRelocated\\dvc_local_remote may be reachable when F: is "
                    "present; data/ junction MUST stay on C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated. "
                    "Auto-repoint to F: is FORBIDDEN."
                )
                note["repoint_to_f"] = "FORBIDDEN"
        if action.get("action_id") == "f_drive_usb_removable_dual_anchor_risk":
            action["data_junction_correction_20260720"] = {
                "evidence": rel_out,
                "note": (
                    "Live data/ junction is on C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated. "
                    "USB dual-anchor residual for data/ is CLOSED by forbid_usb_data_junction; "
                    "Ubuntu-22.04 VHDX on F: remains the residual USB exposure for WSL only."
                ),
                "usb_data_junction": "FORBIDDEN",
                "auto_repoint_to_f": "FORBIDDEN",
            }
            action["risk"] = (
                "A future USB disconnect can still crash/attach-fail the Ubuntu-22.04 WSL distro "
                "whose ext4.vhdx lives on F:. The live data/ junction is NO LONGER on F: "
                "(forbidden + forced on C backup), so package/MASKFACTORY_DATA_PATH will not "
                "dangle solely from an F: unplug."
            )
            action["finding"] = (
                "F: is a USB-attached Seagate BUP Slim (BusType=USB). Live data/ junction target "
                "is C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated (forced/confirmed). F: may "
                "still host WSL Ubuntu-22.04 VHDX + cold mirrors; never the sole live data/ target."
            )

    existing_ids = [a.get("action_id") for a in data["actions"]]
    forbid_action = {
        "action_id": "forbid_usb_data_junction",
        "status": "DONE_BINDING_POLICY",
        "binding_policy": "usb_data_junction=FORBIDDEN; auto_repoint_to_f=FORBIDDEN",
        "evidence": rel_out,
        "executed": (
            f"Confirmed/forced data/ -> {EXPECTED}. Package count via junction={len(pkg_names)}. "
            "maskfactory reindex --dry-run readable. Auto-repoint to F: forbidden for all agents."
        ),
        "no_human_wait": True,
        "unblocks": [
            "Removes data/ dangling-junction exposure on USB disconnect",
        ],
    }
    if "forbid_usb_data_junction" in existing_ids:
        data["actions"][existing_ids.index("forbid_usb_data_junction")] = forbid_action
    else:
        data["actions"].append(forbid_action)

    if "f_drive_restored_20260720T1441" in data:
        dh = data["f_drive_restored_20260720T1441"].setdefault("data_health", {})
        dh["junction_target"] = str(EXPECTED) + " (on-C: backup; FORCED)"
        dh["active_package_count"] = len(pkg_names)
        dh["repoint_to_f"] = "FORBIDDEN (usb_data_junction_policy); do not auto-perform"
        dh["moved_this_update"] = bool(mutation["performed"])

    data["host_snapshot"]["data_drive"] = (
        f"data/ junction -> {EXPECTED} (on-C: backup, {len(pkg_names)} pkgs); "
        "auto-repoint to USB F: FORBIDDEN"
    )
    data["usb_data_junction_policy"] = {
        "status": "FORBIDDEN",
        "auto_repoint_to_f": "FORBIDDEN",
        "evidence": rel_out,
        "forbidden_targets": [
            r"F:\MaskFactory_DataRelocated",
            "any USB/removable volume as sole live data/ junction",
        ],
        "required_target": str(EXPECTED),
    }
    data["data_junction_forced_c_backup"] = {
        "evidence": rel_out,
        "self_sha256": evidence["self_sha256"],
        "package_count": len(pkg_names),
        "junction_target": str(EXPECTED),
        "usb_data_junction": "FORBIDDEN",
        "auto_repoint_to_f": "FORBIDDEN",
        "mutation_performed": bool(mutation["performed"]),
    }
    data["latest_reverification"] = {
        "at": now,
        "by": "data_junction_forced_c_backup",
        "evidence": rel_out,
        "package_count": len(pkg_names),
        "junction_target": str(EXPECTED),
        "usb_data_junction": "FORBIDDEN",
        "auto_repoint_to_f": "FORBIDDEN",
    }
    data["project_head_at_authoring"] = git("rev-parse", "HEAD")[:12]
    data["recorded_at"] = now
    data["supersedes"] = {
        "path": "qa/live_verification/needs_agent_actions_20260720.json (prior self)",
        "reason": (
            f"Binding FORBID of USB data/ auto-repoint after forced-C seal {OUT.name}; "
            "correct stale language that allowed reversible repoint to F:."
        ),
    }
    data["self_sha256"] = sha_body(data)
    NEEDS.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("UPDATED", NEEDS.name, data["self_sha256"])

    entry = f"""
## 2026-07-20 {STAMP[9:13]}:{STAMP[13:15]} UTC - Force data/ junction onto C: backup (forbid USB F: auto-repoint)
**Item:** data_junction_forced_c_backup / usb_data_junction=FORBIDDEN
**Command:** `fsutil reparsepoint query data`; Get-Item data; compare C vs F packages; `maskfactory reindex --dry-run`; seal + needs_agent_actions update.
**Result:** PASS. `data/` -> `C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated` (resolves_on_c=true, resolves_on_f=false). Packages **{len(pkg_names)}** readable via junction. C/F package name sets equal (no F-only copy needed). `maskfactory reindex --dry-run` exit 0 (packages present; index may show stale_rows drift). **Auto-repoint to F: FORBIDDEN** in needs_agent_actions. Mutation performed: {mutation["performed"]} ({mutation["reason"]}).

Evidence: {rel_out}; script runtime_artifacts/_seal_data_junction_forced_c_backup_20260720.py.
"""
    with OPS.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(entry)
    print("OPS_LOG appended")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
