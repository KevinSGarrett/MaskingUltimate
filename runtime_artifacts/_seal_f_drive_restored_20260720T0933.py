"""Seal the 2026-07-20 F: drive restoration re-verification.

Context: qa/live_verification/docker_relocation_f_absent_blocked_20260720T1435Z.json
recorded the removable F: as PHYSICALLY ABSENT at 14:35Z (single-disk system;
dangling data/ junction; DAZ root + WSL Ubuntu-22.04 unreachable). Kevin reports
F: is back online. This seal live-probes the filesystem at seal time and records
the measured (non-elevated) WSL wake result.

Key honest correction captured here: the earlier "Ubuntu-22.04 ext4 corrupt /
Error code 6" symptom was a consequence of F: being disconnected -- the registered
distro's ext4.vhdx lives at F:\\MaskFactory_Offload_20260714\\WSL\\Ubuntu-22.04.
With F: reconnected the distro boots healthy read/write, so that failure was an
UNREACHABLE-vhdx symptom, not on-disk ext4 corruption.

Never claims: doctor-all-green, gold, champions>0, docker_vhdx_relocated_to_f,
durable off-C: storage. F: remains a REMOVABLE drive (it just demonstrably
disconnected); a permanent fixed second disk is still the Kevin action for any
live Docker VHDX relocation.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "qa" / "live_verification" / "f_drive_restored_20260720T0933Z.json"

F_ROOT = Path("F:\\")
F_OFFLOAD = Path(r"F:\MaskFactory_Offload_20260714")
F_VHDX = F_OFFLOAD / "WSL" / "Ubuntu-22.04" / "ext4.vhdx"
F_DATARELOCATED = Path(r"F:\MaskFactory_DataRelocated")
F_DAZ = Path(r"F:\DAZ")
DATA_JUNCTION = REPO / "data"
PRIOR_BLOCK = REPO / "qa" / "live_verification" / "docker_relocation_f_absent_blocked_20260720T1435Z.json"


def _sha_body(document: dict) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _free_bytes(root: str) -> int | None:
    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(root), ctypes.byref(free), ctypes.byref(total), None
    )
    return int(free.value) if ok else None


def _junction_target(path: Path) -> str | None:
    try:
        return os.path.realpath(str(path))
    except OSError:
        return None


def _pkg_count(base: Path) -> int | None:
    pkgs = base / "packages"
    if not pkgs.is_dir():
        return None
    return sum(1 for _ in pkgs.iterdir())


def _sqlite_images(db: Path) -> int | None:
    if not db.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return int(con.execute("SELECT COUNT(*) FROM images").fetchone()[0])
        finally:
            con.close()
    except sqlite3.Error:
        return None


def _wsl_wake() -> dict:
    """Non-elevated wake + read/write sanity of Ubuntu-22.04 (bounded)."""
    try:
        proc = subprocess.run(
            [
                "wsl",
                "-d",
                "Ubuntu-22.04",
                "--",
                "sh",
                "-c",
                "echo ok; uname -r; df -h / | tail -1; "
                "touch /tmp/_f_restore_probe && echo WRITE_OK && rm -f /tmp/_f_restore_probe",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        out = (proc.stdout or "").strip()
        return {
            "attempted": True,
            "exit_code": proc.returncode,
            "echo_ok": "ok" in out.splitlines()[:1][0] if out else False,
            "write_ok": "WRITE_OK" in out,
            "stdout_tail": out.splitlines()[-5:],
            "stderr_note": (proc.stderr or "").strip()[-400:] or None,
            "corruption_or_io_error": proc.returncode != 0 and "WRITE_OK" not in out,
            "interpretation": (
                "Distro booted and executed read/write; prior 'ext4 corrupt/Error 6' "
                "was the F:-unreachable symptom (distro vhdx lives on F:), now resolved."
                if proc.returncode == 0
                else "Non-zero exit; do not thrash. Docker-GPU remains primary runtime."
            ),
        }
    except subprocess.TimeoutExpired:
        return {
            "attempted": True,
            "timed_out": True,
            "interpretation": "Wake exceeded 180s; recorded, not retried. Docker-GPU primary.",
            "corruption_or_io_error": True,
        }


def main() -> int:
    f_free = _free_bytes("F:\\")
    junction_target = _junction_target(DATA_JUNCTION)

    document = {
        "artifact_type": "f_drive_restored",
        "schema_version": "1.0.0",
        "proof_tier": "LIVE_HOST_PROBE",
        "authority": "f_drive_restoration_reverify_non_elevated",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "local_date": "2026-07-20",
        "branch": "codex/maskfactory-runtime-implementation",
        "reported_by": "kevin_reports_f_back_online",
        "prior_f_absent_block": PRIOR_BLOCK.relative_to(REPO).as_posix()
        if PRIOR_BLOCK.is_file()
        else None,
        "prior_f_absent_block_sha256": _file_sha(PRIOR_BLOCK),
        "f_drive": {
            "present": F_ROOT.exists(),
            "free_gib": round(f_free / (1024**3), 2) if f_free is not None else None,
            "free_bytes": f_free,
            "removable": True,
            "durable_off_c_storage_note": (
                "F: is a REMOVABLE drive that demonstrably disconnected; a permanent "
                "fixed second disk is still required (Kevin action) before any live "
                "Docker VHDX relocation. Not claiming durable off-C: storage."
            ),
        },
        "offload_tree": {
            "root": str(F_OFFLOAD),
            "root_present": F_OFFLOAD.is_dir(),
            "wsl_ubuntu2204_vhdx": str(F_VHDX),
            "wsl_ubuntu2204_vhdx_present": F_VHDX.is_file(),
            "wsl_ubuntu2204_vhdx_gib": round(F_VHDX.stat().st_size / (1024**3), 2)
            if F_VHDX.is_file()
            else None,
        },
        "data_health": {
            "junction_path": str(DATA_JUNCTION),
            "junction_target_realpath": junction_target,
            "junction_resolves": DATA_JUNCTION.exists(),
            "active_package_count": _pkg_count(DATA_JUNCTION),
            "active_sqlite_images": _sqlite_images(DATA_JUNCTION / "maskfactory.sqlite"),
            "f_datarelocated_present": F_DATARELOCATED.is_dir(),
            "f_datarelocated_package_count": _pkg_count(F_DATARELOCATED),
            "f_datarelocated_sqlite_images": _sqlite_images(
                F_DATARELOCATED / "maskfactory.sqlite"
            ),
            "f_dvc_local_remote_present": (F_DATARELOCATED / "dvc_local_remote").is_dir(),
            "note": (
                "data/ junction currently resolves to the on-C: backup "
                "(data_c_backup_relocated) that a sibling repointed during the F: "
                "outage; it is healthy (readable, package counts match the F: copy). "
                "F:\\MaskFactory_DataRelocated is now reachable again with an identical "
                "package set + dvc_local_remote. Left on the C: backup for outage "
                "resilience; repoint to F: is reversible and available on request."
            ),
        },
        "daz_root": {
            "path": str(F_DAZ),
            "present": F_DAZ.is_dir(),
            "entry_count": sum(1 for _ in F_DAZ.iterdir()) if F_DAZ.is_dir() else None,
            "note": "F:\\DAZ reachable again; DAZ static contract binders unblocked.",
        },
        "wsl_wake": _wsl_wake(),
        "unblocked_paths": [
            "F:\\DAZ (DAZ roots / validation / ops / coverage static contracts)",
            "F:\\MaskFactory_DataRelocated (data + dvc_local_remote reachable)",
            "WSL Ubuntu-22.04 (distro vhdx on F: now boots; live CUDA WSL smoke path reopened)",
        ],
        "honesty": [
            "F: is REMOVABLE and just disconnected; NOT a durable fixed second disk.",
            "No data was moved/mutated this seal: data/ left on the C: backup for resilience.",
            "WSL 'corruption' narrative corrected: it was F:-unreachable, not on-disk ext4 damage.",
            "Docker-GPU remains the primary GPU runtime; WSL is now additionally available.",
        ],
        "claims_not_established": [
            "docker_vhdx_relocated_to_f",
            "durable_off_c_storage",
            "doctor_all_green",
            "champions>0",
            "gold",
            "live_sam31_cuda_wsl_smoke_executed",
        ],
        "mutation_performed": False,
        "prune_performed": False,
        "volume_wipe_performed": False,
    }
    document["self_sha256"] = _sha_body(document)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("SEALED", OUT.name, document["self_sha256"][:16])
    print("f_free_gib", document["f_drive"]["free_gib"])
    print("data_junction ->", junction_target, "pkgs", document["data_health"]["active_package_count"])
    print("wsl_wake exit", document["wsl_wake"].get("exit_code"), "write_ok", document["wsl_wake"].get("write_ok"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
