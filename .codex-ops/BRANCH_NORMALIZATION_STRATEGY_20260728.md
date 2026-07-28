# MaskFactory branch normalization strategy

Date: 2026-07-28

## Completion outcome

This strategy completed on 2026-07-28. The validated product authority was
promoted to `origin/main` by non-forced fast-forward. Remote heads were reduced
from 30 to seven (`main` plus six explicit recovery refs). Local branches were
reduced from 21 to two (`main` plus the branch checked out by the protected
dirty recovery checkout). The exact validation plan and post-promotion receipt
are:

- `.codex-ops/NORMALIZATION_VALIDATION_AND_BRANCH_PLAN_20260728T151802Z.json`
- `.codex-ops/MAIN_PROMOTION_AND_BRANCH_CLEANUP_20260728T152359Z.json`

The one-local-branch aspiration was corrected because deleting or moving the
branch checked out by the dirty recovery checkout would violate the no-loss
boundary. The sections below retain the historical starting state and
procedure for auditability.

## Required outcome

Produce one clean, installable, fully tested MaskFactory authority on
`origin/main`, preserve every unique candidate byte until it has an explicit
semantic disposition, reduce branch/worktree clutter only after proof, and
leave a durable recovery and branch-retirement ledger.

## Verified starting state

| Role | Ref | OID | Disposition |
| --- | --- | --- | --- |
| stale public authority | `origin/main` | `d6a3c0e00d01536504f737aff84891cf8bd4efb3` | preserve, then fast-forward only |
| clean reconciliation authority | `codex/reconcile-maskfactory-canonical-20260728` | `4316297024734d8741370905ad185a7fcccfeb8f` | normalization base |
| maximal current product/steward line | `origin/codex/fallback-dispatcher-podbase-20260726` | `7d66ca27781d899a43eb644c0378bcf1478045a7` | merge semantically |
| divergent serverless line | `origin/codex/runpod-serverless-overflow-20260724` | `966b95a3c36fb0ed9d6c236c97d97cc4fd6a352d` | reconcile post-split cohort |
| product-line common predecessor | `origin/codex/maskfactory-plan-modernization` | `0dad835d034df395158f3bd26302e6a638adb600` | ancestry marker |
| earlier product predecessor | `origin/codex/runpod-autonomous-work-cell` | `1e05a624a4de43c758040bb6a1df7f7e27cea4c9` | ancestry marker |
| historical product reservoir | `origin/agent/maskfactory-build-progress-20260711` | `8550209f2607369ab3e32053be86f2fa40a7db90` | inventory unique candidates |

`origin/main` is an ancestor of the reconciliation authority. Their divergence
is 0/621. Promotion therefore requires a normal fast-forward, never a force
push. There are 20 local and 26 remote branches at this checkpoint.

The fallback and serverless lines share plan-modernization ancestry and then
diverge. The fallback line contains the larger current product/steward tree.
The serverless post-split delta has 24 source-present paths: 12 already exact
in fallback, 11 different, and one absent. The historical agent line has 588
source-present paths not exact in fallback (394 absent and 194 different);
these are candidates, not automatic adoption.

An object-only merge-tree audit found 122 conflict paths between reconciliation
and fallback, 89 between reconciliation and serverless, and 123 between
reconciliation and the historical agent tip. Bulk merging or selecting one
whole tree would therefore be unsafe.

## Ownership and preservation boundary

- This task owns Masking Git/history, Masking worktrees, MaskFactory
  Plan/Tracker state, `F:\CodexRecovery`, MaskFactory storage artifacts, and
  Consumer protection.
- Main task `019fa6cc-eb76-74c1-8fd1-f062cec56dad` owns
  `C:\Comfy_UI_Main`, its worktrees, and `F:\Codex_Recovery`.
- `C:\w` is shared only by location; common-dir ownership controls every
  disposition.
- The dirty canonical Masking checkout remains a recovery source until every
  dirty and untracked path is classified and independently recoverable.
- Both non-equivalent VHDX backups remain no-touch.

Primary no-loss authority:
`F:\CodexRecovery\maskfactory_reconciliation_checkpoint_20260728T042648Z`,
registry digest
`903b960291b049ef26c4c36fa55d568158a0918763aea4a830fce5d1f11f2b0a`.

## Integration procedure

1. Fetch without pruning and recapture exact refs, worktrees, disk floor,
   active Git processes, and Git connectivity.
2. Publish namespaced rollback refs for the old `main` and any unpublished
   local authority. Record all product tips in a committed SHA ledger.
3. Create `codex/normalize-maskfactory-main-20260728` from the clean
   reconciliation authority.
4. Merge the fallback line while preserving both parent histories.
   Non-conflicting product additions are retained. Conflict cohorts are
   reviewed by domain:
   - safety, authority, tracker, and current operating controls;
   - package, build, workflow, and runtime definitions;
   - core mask generation/training/serving/product code;
   - autonomy/steward/bridge/Serverless code;
   - schemas/configuration/evidence contracts; and
   - tests and external-asset contracts.
5. Compare the 12 unresolved serverless post-split paths against the integrated
   tree. Adopt only current, contract-consistent behavior with focused tests.
6. Inventory historical-agent unique paths by product capability. Adopt
   non-superseded capability only with tests; otherwise record supersession or
   durable archival disposition.
7. Reconcile the protected canonical checkout by exact path/hash against the
   normalized tree and recovery checkpoint.
8. Validate from a clean environment:
   - package metadata and install;
   - syntax/import/static checks;
   - focused changed-domain tests;
   - complete collected product suite under an explicit asset contract;
   - tracker validate/report and generated-state consistency;
   - evidence reconstruction; and
   - `git fsck --full` plus connectivity.
9. Push the normalization branch. Reverify its remote OID, rollback ref, clean
   status, and test receipt.
10. Fast-forward `origin/main` to that exact OID without force. Re-fetch and
    prove local/remote/main/tree identity.

## Branch reduction procedure

After `main` promotion, classify every local and remote branch:

- `MERGED`: tip is an ancestor of validated `main`;
- `PATCH_EQUIVALENT`: content is present despite different ancestry;
- `SUPERSEDED_PRESERVED`: rejected work is retained by a namespaced archival
  ref and receipt;
- `ACTIVE_RECOVERY`: temporarily retained rollback authority; or
- `UNRESOLVED`: cannot be deleted.

Delete only `MERGED`, `PATCH_EQUIVALENT`, or fully receipt-backed
`SUPERSEDED_PRESERVED` branch names. Never delete a checked-out branch, an
unpublished tip, an unclassified dirty worktree, or a recovery ref still
needed by the final rollback gate. Finish with one branch inventory showing
why every surviving ref exists.

## Completion gate

Repository normalization is complete only when:

- `origin/main` equals the validated full-product integration OID;
- local and remote `main` are clean and Git-integrity checks pass;
- the dirty canonical checkout has no unclassified source/control bytes;
- all remaining branches have an explicit durable role;
- obsolete branch names and worktrees are retired only under receipts;
- Tracker/Plan/current-task documents agree with repository reality; and
- Main-task coordination has recorded the final Masking OID and boundary.
