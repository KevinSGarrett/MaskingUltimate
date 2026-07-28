# 29 - Local Repository, Directory, and Tracker Authority Convergence

## 1. Purpose

This specification closes the gap between a clean, tested Git `main` and a
physically coherent local project. A clean nested worktree, a recovery archive,
or a structurally valid tracker is not sufficient when useful work may still
exist in dirty checkouts, abandoned worktrees, recovery roots, standalone
repositories, runtime exports, or evidence folders.

This is a no-loss integration requirement. It does not authorize deleting
unique source, evidence, datasets, model/runtime storage, VHDX backups,
Consumer history, or another project's files.

## 2. Authorities and ownership

- `C:\Comfy_UI_Main_Masking` is the required physical canonical MaskFactory
  checkout and must end as a clean checkout of local/remote `main`.
- `Plan\Tracker\tracker.py` is the only writer for tracker item state.
- `Plan\`, `Plan\Items\`, and `Plan\Instructions\` define requirements and
  verification; generated tracker reports mirror tracker state.
- `C:\Comfy_UI_Main` and `F:\Codex_Recovery` are owned by the coordinated Main
  task. MaskFactory may inspect them only for read-only dependency accounting.
- Shared `C:\w` paths are owned by their resolved Git common directory or an
  explicit path receipt. `C:\w` is never a bulk-delete target.
- `F:\CodexRecovery`, MaskFactory Tier-A archives, the standalone Consumer
  repository, MaskFactory storage/runtime roots, and MaskFactory VHDX backups
  remain MaskFactory-owned.

## 3. Exhaustive path ledger

Every discovered meaningful path must have one ledger row containing:

1. exact path, owner, Git common directory when applicable, byte size, and
   SHA-256;
2. candidate commit/blob, current canonical commit/blob, and independent
   rollback location;
3. exactly one disposition:
   `ADOPT`, `ALREADY_PRESENT`, `SUPERSEDED`, `ARCHIVE_ONLY`,
   `GENERATED_RUNTIME_ONLY`, `FOREIGN_OWNED`, or
   `BLOCKED_REVIEW_REQUIRED`;
4. governing Plan/spec/Instruction;
5. affected Item IDs, dependencies, tracker status/evidence/limitations, and
   tests;
6. canonical location and restoration procedure.

Exact-byte preservation is not semantic adoption. Archive-only, superseded,
generated, and foreign-owned rows cannot advance implementation, runtime,
visual, product, or completion status.

## 4. Source and control reconciliation

Comparison must include tracked modifications, staged changes, untracked
source/control files, deleted paths, branch-only commits, standalone
repositories, and selected-source archives. Formatting/line-ending equality,
AST or parsed-data equality, and behaviorally stronger current authority must
be distinguished explicitly.

Plan, Item, Instruction, tracker, and operational-history differences require
the same review as executable source. Missing tracker history must be restored
without replaying stale item state. Obsolete handoffs remain historical
evidence and must not become active instructions.

Useful behavior is adopted through focused commits and tests. Superseded
behavior receives a reason and authority pointer. Unresolved contradictions
remain preserved and blocked; they are never bulk-merged.

## 5. Plan, Item, and tracker synchronization

For each adopted capability:

- update the governing Plan/Instruction;
- update the existing Item metadata or add a non-duplicative Item only when no
  current row covers the requirement;
- use `tracker.py rebuild` after Item metadata changes;
- use `tracker.py set` for status, progress, notes, evidence, and blockers;
- use `tracker.py report` and `tracker.py validate`;
- update dependency/DAG, test, evidence-locator, decision, and OPS authorities
  when affected.

Historical tracker events may be unioned into `CHANGELOG.jsonl` only after
proving that current item state and notes already contain their effects.
`tracker.json` is never hand-edited and stale state is never replayed.

## 6. Shared directory disposition

Each directory from the user's original list and each newly discovered direct
child of `C:\w` must be classified as canonical source, independent repository,
recovery authority, runtime/model/data storage, evidence collection,
foreign-owned, redundant verified copy, or exact empty shell.

Deletion or retirement requires immediate precondition revalidation, exact
target resolution, independent byte coverage for every unique file, owner
confirmation for shared paths, and a durable postcondition receipt. Empty
shells require recursive zero-file/zero-byte proof. Large storage is not
eligible merely because it is inconvenient or appears duplicated.

## 7. Physical canonical-root transition

The original dirty checkout may be replaced only after:

- the exhaustive ledger has no unresolved meaningful path;
- all adopted work is committed, tested, and remotely protected;
- all non-adopted bytes have verified independent recovery;
- active processes and Git locks are absent;
- local/remote `main`, refs, worktrees, and full/connectivity fsck pass;
- an exact rollback procedure and pre-transition receipt exist; and
- the coordinated Main task confirms no shared-path conflict.

The transition must leave `C:\Comfy_UI_Main_Masking` itself as the clean
canonical `main` checkout. A nested clean worktree plus a dirty canonical root
does not satisfy this specification.

## 8. Current second-phase authority

The 2026-07-28 live audit found 137 unique meaningful source/control files in
the protected dirty authority: 99 exact in clean `main`, 37 different, and one
absent from clean `main`. Eleven live tracked modifications are included; ten
overlap the 136-file checkpoint selection and `.codex-ops\CURRENT_TASK.md` is
the additional file.

The verified incremental checkpoint is:

`C:\MaskFactory_TierA_Backups\second_phase_preconsolidation_20260728T162424Z`

Registry SHA-256:

`b2882e7cd50a8bd5f560d85846e6409b754a585b5496dd746aab6cf1ac654197`

Shared `C:\w` measured 5,034,979,803 bytes at phase start. Its ownership and
disposition remain path-specific and jointly coordinated.

The physical-root transition completed without replacing the checkout:

- the nested clean-main worktree was removed through `git worktree remove`;
- 33,308 hash-verified files, 3,679 empty directories, and 28 separately
  classified opaque nested directories were retired only after rollback and
  ownership gates;
- the 11 tracked modifications rehashed exactly to the Tier-A tracked
  supplement and were restored only in the protected dirty branch;
- the physical root then switched normally to `main`, with zero status rows,
  one registered worktree, and local/remote equality at
  `f54519796a48920e59f529759a8c3687292ce34e`; and
- the old dirty commit remains exact at remote recovery ref
  `codex/recovery-maskfactory-20260728-61b4ffe`.

Main's coordinated shared-`C:\w` receipt records 5,654/5,654 checkpoint
readbacks, 84/84 non-equivalent candidate dispositions, exact retirement of
its nine assigned paths, and zero remaining direct children. After both owners
confirmed no dependency, the exact zero-file/zero-directory/non-reparse
`C:\w` shell was removed non-recursively under
`.codex-ops/EMPTY_SHARED_CW_ROOT_RETIREMENT_20260728T172928Z.json`. The Main
receipt is
`F:\Codex_Recovery\main_shared_cw_checkpoint_20260728T162954Z\
retirement_receipt.json`, SHA-256
`d4586b0608dace04eb30200429e3dee172c508d01ffc663cabdb821609a6625d`.

The Masking governing receipts are:

- `.codex-ops/PHYSICAL_CANONICAL_ROOT_CONVERGENCE_20260728T172153Z.json`;
- `.codex-ops/OPAQUE_NESTED_DIRECTORY_RETIREMENT_20260728T172153Z.json`; and
- `.codex-ops/STALE_GIT_TEMP_LOCK_RETIREMENT_20260728T172153Z.json`.

The opaque-directory receipt includes the late Main-owned
`tmp\comfy_commit_inspect` clone as a zero-product-credit recovery row: its
sole commit is ancestor-contained by Main, its physical path is absent, and
its semantic tree remains independently reconstructable. The receipt states
the limitation that no 45-row physical `.git`-file manifest was captured.

The coordinated Main repository closed clean local/remote `main` at
`ee2717ab4d8985182e73b0a79c131b2076443952`. Its final shared-`C:\w`
authority is `.codex-ops/SHARED_CW_SECOND_PHASE_FINAL_20260728T171508Z.json`,
SHA-256
`9a332e7fab8f0da346f2ca7cafa3152c12158fd8437e964083bb4bcf0c17a599`.

## 9. Terminal verification

This phase is complete only when:

- every meaningful file and original directory has a receipt-backed row;
- no useful Plan, Item, Instruction, tracker, source, test, or evidence change
  remains stranded;
- tracker state, changelog, reports, item metadata, and Plan authorities agree;
- the physical canonical root is clean `main`;
- local and remote `main` are equal;
- only explicitly retained recovery/foreign/runtime/data/evidence paths remain;
- focused and complete tests, clean build/install/import, credential/diff
  checks, tracker validation, and full/connectivity fsck pass; and
- rollback is independently reconstructable without conversational context.
