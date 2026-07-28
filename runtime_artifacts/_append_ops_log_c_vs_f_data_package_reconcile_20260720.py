"""Append-only OPS_LOG entry for C vs F data package reconcile seal."""

ENTRY = """
## 2026-07-20 14:53 UTC - C backup vs F: DataRelocated package reconcile (copy missing onto C; keep C junction)
**Item:** data_c_vs_f_package_reconcile / keep runtime on fixed-disk C: backup
**Command:** Compare `data_c_backup_relocated\\packages` vs `F:\\MaskFactory_DataRelocated\\packages` (counts, per-package files/bytes/newest); robocopy /L residual; robocopy /E copy F-only `dvc_local_remote` onto C backup; fsutil/junction re-verify.
**Result:** PASS. Packages **8 = 8** with identical names, file counts, total bytes (2,787,901,171), and newest mtimes on every package — **no package copy required**. F: had one fuller top-level tree (`dvc_local_remote`, 52 files / 6,349,602 bytes) absent from C; **copied** onto `C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated\\dvc_local_remote` via robocopy (real files, exit 1 = copied). `data/` junction remains `C:\\Comfy_UI_Main_Masking\\data_c_backup_relocated` — **never re-junctioned to USB F:**. F: tree left intact. Via junction: 8 packages readable. C free ~90.93 GiB; F free ~127.76 GiB (removable/unstable — not for `data/`).

Evidence: qa/live_verification/c_vs_f_data_package_reconcile_20260720T1453Z.json; script runtime_artifacts/_seal_c_vs_f_data_package_reconcile_20260720.py.
"""

with open("Plan/OPS_LOG.md", "a", encoding="utf-8", newline="\n") as f:
    f.write(ENTRY)
print("APPENDED", len(ENTRY), "chars")
