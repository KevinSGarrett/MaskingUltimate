# Section 01 — Recovery Freeze, Authority, and Git/Tracker Reconciliation

**Acceptance order:** 1 of 20  
**Mapped unresolved tracker items:** 1  
**Current states:** open=1  
**Hard blockers in scope:** 1  
**Rows with explicit Kevin authority/input:** 0  
**Depends on:** None  
**Enables:** Section 02, Section 03

## Goal

Establish one indisputable source-of-truth baseline before any additional feature work, preserving every local, staged, untracked, GitHub, and accepted runtime artifact without destructive reconciliation.

## Why this section exists

The uploaded local snapshot, GitHub main, open pull requests, and accepted runtime branch history do not currently describe one source tree. Beginning implementation before resolving ownership would make every later test and completion claim ambiguous.

## Scope

- Freeze the current local directory, uploaded snapshot, Plan bundle, GitHub main, PR #1, PR #2, PRs #3–#7, and accepted Plan-27 evidence by exact hashes.
- Record local HEAD/branch, ancestry, ahead/behind state, tracked modifications, staged paths, untracked paths, generated evidence, user-owned files, and external runtime assets.
- Classify every path as identical, product-only required, autonomy-only required, superseded-with-proof, generated/reproducible, runtime evidence, user-owned/unrelated, or unresolved conflict.
- Select and document the canonical integration parent and target branch; prohibit reset, mass checkout, replacement worktree, or broad staging as a shortcut.
- Reconcile tracker authority: 906-item local tracker versus 393-item GitHub-main tracker, with one approved migration path and no status loss.

## Work packages

1. Create a read-only reconciliation manifest for every relevant source line and evidence root.
2. Create independent backups of the dirty local state, index state, and untracked source before any merge/cherry-pick.
3. Build a path-ownership matrix and conflict-resolution decision log.
4. Choose the canonical integration branch and record its exact parent commit/tree.
5. Define section branch/PR rules for Sections 2–20.

## Section-level testing

- Manifest completeness test: every captured path appears exactly once in the ownership matrix.
- Hash verification test against both uploaded archives and the live/local export.
- Git ancestry and PR-base test: every adopted commit has a traceable parent and no orphaned accepted runtime change.
- Negative test: a deleted, overwritten, duplicated, or unclassified path must fail the reconciliation validator.
- Secret/large-binary boundary scan before any artifact is committed.

## Integration tests with the rest of the project

- An independent reviewer can reconstruct which exact bytes feed Section 2 without relying on conversation state.
- Accepted MF-P6-19.01 and MF-P6-19.02 evidence remains addressable and unchanged.
- The selected target lineage can receive both the complete product code and accepted autonomy changes.

## Definition of done and acceptance criteria

- [ ] A signed/hash-bound source-line reconciliation packet exists.
- [ ] Every local/GitHub path has one ownership classification and zero unresolved conflict.
- [ ] The canonical integration parent, target branch, branch-protection workflow, and backup locations are fixed.
- [ ] No source, evidence, tracker history, or user-owned work has been silently discarded.
- [ ] MF-P6-20.01 is updated through the tracker CLI only after independent validation passes.

## Required proof artifacts

- `source_line_inventory.json`
- `path_ownership_matrix.csv`
- `git_ancestry_report.md`
- `conflict_decisions.jsonl`
- `backup_hash_manifest.tsv`
- `reconciliation_validation.junit.xml`
- `section_acceptance_receipt.json`

## Exit procedure

1. Run T0–T5 tests applicable to this section and preserve commands, exits, counts, environment, and hashes.
2. Verify every mapped tracker row against its own exact `Verify:` clause.
3. Produce and independently validate `section_acceptance_receipt.json`.
4. Exercise rollback/invalidation and verify zero leaked resources.
5. Update tracker rows through `Plan/Tracker/tracker.py`; regenerate dashboard/phase/profile reports.
6. Commit only section-scoped source/evidence locators and open the section PR.
7. Begin the next section only from the accepted commit.

## Mapped tracker items

| Item | Phase | Status | % | Hard blocker | Explicit user authority | Work remaining |
|---|---|---|---:|:---:|:---:|---|
| `MF-P6-20.01` | P6 | open | 0 | Yes | No | Inventory and reconcile the full-product and accepted autonomy source lines by exact commit/tree/path ownership, preserving unrelated staged, dirty, and untracked work |

## Tracker-item exact verification text

### `MF-P6-20.01` — Canonical product/autonomy source integration

- **Current:** `open` at 0%
- **Source:** `24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md` line 14
- **Requirement:** Inventory and reconcile the full-product and accepted autonomy source lines by exact commit/tree/path ownership, preserving unrelated staged, dirty, and untracked work · Verify: a complete path classification has no unexplained deletion, overwrite, reset, replacement worktree, or unresolved conflict · Blocked by: MF-P6-19.01, MF-P6-19.02 · HARD BLOCKER

