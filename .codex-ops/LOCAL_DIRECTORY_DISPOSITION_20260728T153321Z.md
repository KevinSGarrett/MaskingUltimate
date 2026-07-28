# MaskFactory local-directory disposition

Recorded: 2026-07-28T15:33:21Z
Re-audited after physical convergence: 2026-07-28T17:31:00Z

Verdict: `PHYSICALLY_CONSOLIDATED_WITH_EXPLICIT_EXTERNAL_AUTHORITIES`

This ledger closes the directory list supplied by the user. “Retain” means the
path has a current data, evidence, recovery, or foreign-owner role; it does not
mean the path was overlooked. No data-bearing path was deleted merely to
improve a folder count.

| Path | Final disposition | Reason |
| --- | --- | --- |
| `F:\MaskFactory_WSL_VHD_BACKUPS` | removed | Fresh audit found zero files/bytes and one empty child; exact empty shell removed without touching the four VHDX authorities under `F:\MaskFactory_Offload_20260714`. |
| `F:\CodexRecovery` | retain / Masking authority | 532 files / 775,421,530 bytes; primary MaskFactory checkpoints, archives, and reconciliation receipts. |
| `F:\Codex_Recovery` | retain / foreign owner | 159 files / 13,853,556,848 bytes; Comfy_UI_Main recovery authority owned by task `019fa6cc-eb76-74c1-8fd1-f062cec56dad`. |
| `F:\MaskFactory_DataRelocated` | retain | 3,581 files / 10,531,042,439 bytes; active data/packages/DVC/CVAT content and dirty-work backups, not scratch. |
| `F:\Codex_Audit_Staging_Trash_20260722` | retain pending coverage proof | Contains one 448,462,848-byte tar, SHA-256 `b7d8c84bfe43f89b7d3088180051d6508f86997b74f3e84c46c6281ca02b73d6`; no independent exact-byte replacement was proven. |
| `F:\MaskFactory_Offload_20260714` | retain | 2,969 files / 370,294,318,983 bytes; runtime/model/WSL/Docker offload authority including four explicitly inventoried VHDX files, not repository source clutter. |
| `F:\MaskFactory_RuntimeRelocated` | removed | Verified recursively as zero files/zero bytes, then exact empty root removed. |
| `C:\w` | removed | Main checkpointed/dispositioned 5,654 files and retired its exact nine assigned paths; Masking retired `mfw`; after joint confirmation the zero-file/zero-subdirectory/non-reparse parent was removed non-recursively. |
| `C:\Comfy_UI_Main_MaskFactory_Consumer` | retain | 115 files / 509,955 bytes; clean standalone Consumer repository; HEAD `1091a9c8cc01ff554907b97a7e754c6c884cee01` is remotely protected. |
| `C:\Comfy_UI_Main_Masking` | retain / canonical clean main | 14,295 files / 11,300,667,937 bytes at final audit; sole registered worktree, clean local/remote `main`; dirty predecessor independently recoverable. |
| `C:\MaskFactory_ExternalSupervision` | retain | 6 files / 68,843,566 bytes; evidence collection, not a duplicate source checkout. |
| `C:\MaskFactory_FailureCampaigns` | retain | 27 files / 64,363 bytes; failure-evidence collection, not a duplicate source checkout. |
| `C:\MaskFactory_Reviews` | retain | 3 files / 81,166 bytes; review-evidence collection, not a duplicate source checkout. |
| `C:\MaskFactory_TierA_Backups` | retain | 12,688 files / 28,523,074,154 bytes at final audit; intentional byte-preservation authority used by retirement and convergence receipts. |
| `C:\MaskFactory_TierA_RestoreTests` | retain | 4,147 files / 756,645,523 bytes; restore-test evidence for Tier-A preservation. |
| `C:\MaskFactory_WSL_Backup` | removed | Verified recursively as zero files/zero bytes, then exact empty root removed. |
| `C:\mf25p_4446de85` | removed | Verified recursively as zero files/zero bytes, then exact empty root removed. |
| `C:\mf25p_af493b78` | retain | 50 files / 106,552 bytes; small 25-mission campaign scratch/evidence with a distinct audit role. |
| `C:\mfsnap_20260727T153945Z` | removed earlier | Redundant extracted snapshot tree removed only after ZIP/manifest and matching-extract verification. |
| `C:\mfsnap_verify_20260727T153945Z` | removed earlier | Redundant verification extract removed under the same receipt-backed gate. |

## Repository end state

- Physical authority: `C:\Comfy_UI_Main_Masking` itself is clean `main`.
- Clean authority: local `main` equals `origin/main`.
- Remote heads: seven (`main` plus six explicit recovery refs).
- Local branches: one (`main`).
- Registered Masking worktrees: one (the physical canonical root).
- Tracker: 906 non-orphaned items, 53 unresolved hard blockers, zero
  structural errors.
- Git: full and connectivity-only fsck pass.
- Shared `C:\w`: absent after exact owner-specific retirement and final
  non-recursive empty-parent removal.
- Storage at final audit: C: 78,621,347,840 bytes free; F:
  15,389,822,976 bytes free. C: remains above the 50 GiB floor but below the
  75 GiB warning threshold; F: remains below the 50 GiB allocation floor.

The remaining F: floor deficit is an explicit storage constraint, not
unclassified clutter. Unique recovery data, non-equivalent VHDX files, active
offload/data roots, and foreign-owned recovery data cannot be deleted to close
the floor.
