# MaskFactory local-directory disposition

Recorded: 2026-07-28T15:33:21Z

Verdict: `CLEAN_BY_EXPLICIT_ROLE_NO_UNCLASSIFIED_DELETION`

This ledger closes the directory list supplied by the user. “Retain” means the
path has a current data, evidence, recovery, or foreign-owner role; it does not
mean the path was overlooked. No data-bearing path was deleted merely to
improve a folder count.

| Path | Final disposition | Reason |
| --- | --- | --- |
| `F:\MaskFactory_WSL_VHD_BACKUPS` | retain / no-touch | Contains non-equivalent MaskFactory VHDX recovery authorities; neither is deletion-eligible without restore proof. |
| `F:\CodexRecovery` | retain / Masking authority | Primary MaskFactory checkpoints, archives, and reconciliation receipts. |
| `F:\Codex_Recovery` | retain / foreign owner | Comfy_UI_Main recovery authority owned by task `019fa6cc-eb76-74c1-8fd1-f062cec56dad`. |
| `F:\MaskFactory_DataRelocated` | retain | Active data/packages/DVC/CVAT content and dirty-work backups; not scratch. |
| `F:\Codex_Audit_Staging_Trash_20260722` | retain pending coverage proof | Contains one 448,462,848-byte tar, SHA-256 `b7d8c84bfe43f89b7d3088180051d6508f86997b74f3e84c46c6281ca02b73d6`; no independent exact-byte replacement was proven. |
| `F:\MaskFactory_Offload_20260714` | retain | Runtime/model/WSL/Docker offload authority; not repository source clutter. |
| `F:\MaskFactory_RuntimeRelocated` | removed | Verified recursively as zero files/zero bytes, then exact empty root removed. |
| `C:\w` | retain / shared owner map | Mixed-repository worktree parent; never a bulk-delete target. All noncanonical Masking worktrees are retired. |
| `C:\Comfy_UI_Main_MaskFactory_Consumer` | retain | Clean standalone Consumer repository; HEAD `1091a9c8cc01ff554907b97a7e754c6c884cee01` is remotely protected. |
| `C:\Comfy_UI_Main_Masking` | retain / protected recovery | Dirty checkpoint-protected canonical recovery checkout; semantically reconciled, never clean/reset/delete in place. |
| `C:\MaskFactory_ExternalSupervision` | retain | Small evidence collection, not a duplicate source checkout. |
| `C:\MaskFactory_FailureCampaigns` | retain | Small failure-evidence collection, not a duplicate source checkout. |
| `C:\MaskFactory_Reviews` | retain | Small review-evidence collection, not a duplicate source checkout. |
| `C:\MaskFactory_TierA_Backups` | retain | Intentional byte-preservation authority used by worktree retirement receipts. |
| `C:\MaskFactory_TierA_RestoreTests` | retain | Restore-test evidence for Tier-A preservation. |
| `C:\MaskFactory_WSL_Backup` | removed | Verified recursively as zero files/zero bytes, then exact empty root removed. |
| `C:\mf25p_4446de85` | removed | Verified recursively as zero files/zero bytes, then exact empty root removed. |
| `C:\mf25p_af493b78` | retain | Small 25-mission campaign scratch/evidence with a distinct audit role. |
| `C:\mfsnap_20260727T153945Z` | removed earlier | Redundant extracted snapshot tree removed only after ZIP/manifest and matching-extract verification. |
| `C:\mfsnap_verify_20260727T153945Z` | removed earlier | Redundant verification extract removed under the same receipt-backed gate. |

## Repository end state

- Clean authority: local `main` equals `origin/main`.
- Remote heads: seven (`main` plus six explicit recovery refs).
- Local branches: two (`main` plus the branch checked out by the protected
  dirty recovery checkout).
- Registered Masking worktrees: two (clean `main` and protected dirty
  recovery).
- Tracker: 906 non-orphaned items, 54 unresolved hard blockers, zero
  structural errors.
- Git: full and connectivity-only fsck pass.
- Storage after empty-shell cleanup: C: 66,663,493,632 bytes free; F:
  13,932,122,112 bytes free. F: remains below the 50 GiB allocation floor.

The remaining F: floor deficit is an explicit storage constraint, not
unclassified clutter. Unique recovery data, non-equivalent VHDX files, active
offload/data roots, and foreign-owned recovery data cannot be deleted to close
the floor.
