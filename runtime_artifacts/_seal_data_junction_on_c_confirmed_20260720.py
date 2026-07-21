"""Seal live confirmation that data/ junction points at on-C: data_c_backup_relocated (not F:).

Read-only. No mutation. Binding: USB F: must never host the live data/ junction.
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
OUT = REPO / "qa" / "live_verification" / "data_junction_on_c_confirmed_20260720T1500Z.json"


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


def main() -> int:
    realpath = os.path.realpath(str(DATA))
    print_name = fsutil_print_name(DATA)
    pkg_names = sorted(p.name for p in PKGS.iterdir() if p.is_dir()) if PKGS.exists() else []
    resolves_on_c = realpath.upper().startswith("C:")
    resolves_on_f = realpath.upper().startswith("F:")
    target_matches_expected = Path(realpath).resolve() == EXPECTED.resolve()
    f_present = Path("F:/").exists()
    f_free_gib = None
    if f_present:
        try:
            f_free_gib = round(shutil.disk_usage("F:/").free / 2**30, 2)
        except OSError:
            f_free_gib = None

    sample_ok = False
    if pkg_names:
        sample = PKGS / pkg_names[0]
        sample_ok = any(f.is_file() for f in sample.rglob("*"))

    if not (resolves_on_c and target_matches_expected and not resolves_on_f):
        raise SystemExit(
            f"REFUSE_SEAL: junction not on C backup. realpath={realpath!r} "
            f"print_name={print_name!r}"
        )

    evidence = {
        "artifact_type": "data_junction_on_c_confirmed",
        "schema_version": "1.0.0",
        "authority": [
            "FULL AUTONOMY: live probe confirmed data/ -> data_c_backup_relocated (not F:)",
            "qa/live_verification/data_junction_abort_f_keep_c_20260720T1438Z.json",
            "qa/live_verification/f_drive_usb_policy_20260720.json (rule_2)",
            "Plan/OPS_LOG.md (this wave)",
        ],
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "project_head_at_authoring": git("rev-parse", "HEAD"),
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "local_date": "2026-07-20",
        "verdict": "CONFIRMED_DATA_JUNCTION_ON_C_BACKUP",
        "binding_policy": {
            "usb_data_junction": "FORBIDDEN",
            "statement": (
                "Agents MUST NOT re-junction repo data/ onto USB F: (or any other "
                "removable/hot-pluggable volume). Live target remains "
                "C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated. F: may be used "
                "read-when-present for cold offload / DAZ / mirrors only."
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
            "target_matches_expected": target_matches_expected,
        },
        "packages": {
            "count": len(pkg_names),
            "names": pkg_names,
            "readable_via_junction": sample_ok,
        },
        "drives": {
            "c_free_gib": round(shutil.disk_usage("C:/").free / 2**30, 2),
            "f_present": f_present,
            "f_free_gib": f_free_gib,
            "f_classified": "usb_removable_unstable_do_not_use_for_data_junction",
        },
        "mutation_performed": False,
        "claims_not_established": [
            "data_junction_on_f",
            "f_drive_durable_for_maskfactory_data",
            "docker_vhdx_relocated_to_f",
            "doctor_all_green",
            "champions>0",
            "gold>0",
        ],
        "honesty": [
            "Read-only live confirmation; no junction mutation this wave.",
            "F: may be present; BusType=USB Seagate remains forbidden as data/ target.",
            "Prior abort seal (14:38Z) + package reconcile (14:53Z) corroborated; this seal is the explicit on-C confirmation artifact.",
        ],
        "linked_evidence": [
            "qa/live_verification/data_junction_abort_f_keep_c_20260720T1438Z.json",
            "qa/live_verification/c_vs_f_data_package_reconcile_20260720T1453Z.json",
            "qa/live_verification/f_drive_usb_policy_20260720.json",
        ],
    }

    payload = json.dumps(
        {k: v for k, v in evidence.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("SEALED", OUT.name, evidence["self_sha256"])
    print("realpath", realpath, "packages", len(pkg_names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
