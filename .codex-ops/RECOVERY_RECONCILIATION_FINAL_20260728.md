# MaskFactory Recovery Reconciliation — Current Authority

Updated: 2026-07-28 UTC

Verdict: `NO_LOSS_CHECKPOINTED_CLEAN_INTEGRATION_AUTHORITY_ESTABLISHED`

This document is the concise repository-reconciliation authority. It does not
claim that the original canonical checkout is clean or that MaskFactory's
runtime/E2E project gates are complete.

## Authoritative Git line

- Clean integration worktree:
  `C:\Comfy_UI_Main_Masking\.codex-ops\worktrees\canonical-reconciliation-20260728`
- Branch: `codex/reconcile-maskfactory-canonical-20260728`
- Remote: `origin/codex/reconcile-maskfactory-canonical-20260728`
- The local and remote OIDs must match before this ledger is treated as current.
- The original `C:\Comfy_UI_Main_Masking` checkout remains a dirty,
  checkpoint-protected recovery source. Do not run `git clean`, reset it,
  delete it, or treat its untracked files as disposable.

## No-loss authorities

- Primary reconciliation checkpoint:
  `F:\CodexRecovery\maskfactory_reconciliation_checkpoint_20260728T042648Z`
- Checksum-registry SHA-256:
  `903b960291b049ef26c4c36fa55d568158a0918763aea4a830fce5d1f11f2b0a`
- Corrupt-pack recovery and Tier-A archives remain retained.
- The standalone Consumer HEAD
  `1091a9c8cc01ff554907b97a7e754c6c884cee01` is remotely protected at
  `codex/recovery-maskfactory-consumer-20260728-1091a9c`.
- Both MaskFactory VHDX backups remain no-touch and non-deletion-eligible.

## Worktree outcome

Registered Masking worktrees were reduced from 17 to 2 through exact,
individually verified Git-managed retirements. The two remaining registrations
are:

1. `C:\Comfy_UI_Main_Masking` — dirty, checkpoint-protected recovery source.
2. The clean integration worktree above — current Git integration authority.

No dirty candidate was retired until its exact bytes were checkpointed or
independently archived and its semantic disposition was recorded. Important
candidate outcomes include:

- `.wt_climb4`: useful registry/training/native-doctor and strict-router work
  adopted; residuals classified; 106 untracked files independently archived;
  then retired.
- `b90c7f19654319e1`: older source rejected as a security regression; its
  operational-policy precedence tests were adapted to the current
  catalog-bound critic contract and pass 25/25; then retired.
- `a1fed8eb1622c878`: preserved as
  `PRESERVED_INCOMPLETE_REMEDIATION_REQUIRED_NOT_ADOPTABLE`; required schema
  and focused tests were absent and no compatibility contract with the current
  durable executor existed; then retired after complete 3/3 archive readback.
- Main-owned Rows333-336 remains
  `PRESERVED_REMEDIATION_REQUIRED_NOT_ADOPTABLE` because its canonical JSON
  hashing contract is inconsistent across builder/compiler/adapter/evaluators.

Every final dirty-candidate retirement passed path/registration absence,
protected-ref reachability, connectivity-only fsck, and full fsck.

## Tracker authority

`Plan/Tracker/tracker.py` remains task-state authority, not proof that arbitrary
working-tree bytes were integrated.

- Structure: 906 non-orphaned items, 54 unresolved hard blockers, no structural
  errors.
- `MF-P6-12.05`: 84%, blocked, producer-partial only.
- `MF-P6-12.06`: 79%, blocked, core close unauthorized.
- No completion tier was raised by repository cleanup.
- `SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE` remains binding.

## Storage and ownership boundaries

- `C:\w` is shared by physical location only and is never a bulk-delete target.
- Main task `019fa6cc-eb76-74c1-8fd1-f062cec56dad` owns
  `C:\Comfy_UI_Main`, Main worktrees, and `F:\Codex_Recovery`.
- This task owns Masking Git/history, Masking recovery artifacts, Consumer
  protection, and MaskFactory storage/VHD evidence.
- `F:` remains below the 50 GiB project floor. The preserved unique recovery
  payloads and both VHDX files are not safe cleanup targets.

## Recurrence controls

- One task owns canonical Git integration at a time.
- A task ends with a pushed branch or an exact patch plus untracked manifest and
  byte archive.
- Worktrees are namespaced and classified by Git common directory.
- No new worktree is created below the storage floor.
- Opportunistic Git maintenance stays disabled while storage or integrity is
  constrained; maintenance is controlled and receipt-backed.
- Never bulk-run `git clean`, `git reset --hard`, `git gc`, `git prune`, or
  filesystem deletion across the canonical checkout or `C:\w`.

## Remaining work

Repository reconciliation is closed for noncanonical Masking worktrees, but the
broader project remains active:

- preserve and later semantically reconcile the original canonical dirty
  checkout in bounded cohorts;
- resolve remaining tracker hard blockers through actual runtime/production
  evidence;
- recover the F: storage floor without deleting unique recovery or VHD data;
- fix the versioned Rows333-336 canonicalization contract before adoption;
- do not claim E2E completion from this cleanup.
