# Section 02 — Canonical Integrated Source Tree and Repository Hygiene

**Acceptance order:** 2 of 20  
**Mapped unresolved tracker items:** 1  
**Current states:** open=1  
**Hard blockers in scope:** 1  
**Rows with explicit Kevin authority/input:** 0  
**Depends on:** Section 01  
**Enables:** Section 03

## Goal

Produce one complete, source-controlled tree containing the full MaskFactory product and the accepted autonomy/runtime implementation, with no dependency on stale pycache, another checkout, chat state, or untracked source.

## Why this section exists

The uploaded snapshot cannot currently collect tests because `maskfactory.models` source is absent, while compiled-cache paths appear in the captured untracked inventory. This is a concrete source-closure failure, not a feature-test failure.

## Scope

- Integrate product modules, steward/autonomy modules, CLI, services, nodes, configs, schemas, Plan authority, tests, packaging, and operating procedures.
- Recover or reimplement missing source such as `maskfactory.models` from authoritative commits/evidence—not from unverified bytecode.
- Classify vendored CVAT, generated files, runtime evidence, model metadata, and large assets; keep only appropriate source under Git.
- Remove import shadowing and editable-install dependence on any other checkout.
- Normalize repository layout, `.gitignore`, package-data declarations, and generated-file regeneration commands.

## Work packages

1. Apply the Section-1 ownership decisions path by path.
2. Restore all required source modules and package initializers.
3. Merge accepted Plan-27 supervisor, routing, lease, completion-firewall, and campaign code into the full product tree.
4. Track source/config/schema/test files; move transient runtime output out of source ownership.
5. Create a repository map and generated-artifact manifest.

## Section-level testing

- Enumerate every importable `maskfactory.*` module and import it from a clean interpreter with bytecode disabled.
- Run `compileall`, Ruff, Black/check, schema meta-validation, and package-data inventory.
- Delete all `__pycache__` and `.pyc` files, then repeat imports and focused tests.
- Negative test: importing from an external checkout or user site-packages must be detected and fail.
- Tree-content test: every required file from both source lines is present or has an approved supersession receipt.

## Integration tests with the rest of the project

- The full product CLI and steward CLI import from the same source root.
- Product tests can discover autonomy modules and autonomy tests can discover full-product modules.
- Plan/Tracker tooling operates against the same committed tree used by tests.

## Definition of done and acceptance criteria

- [ ] One clean Git worktree contains all required source and authority files.
- [ ] Zero required source files are untracked.
- [ ] Zero imports depend on stale compiled caches or another checkout.
- [ ] Repository scans show no secrets, model binaries, datasets, or inappropriate runtime evidence.
- [ ] MF-P6-20.02 is accepted with exact tree hash and path inventory.

## Required proof artifacts

- `canonical_tree_manifest.json`
- `required_path_reconciliation.json`
- `module_import_inventory.json`
- `generated_artifact_manifest.json`
- `repo_hygiene_scan.json`
- `clean_tree_hash.txt`
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
| `MF-P6-20.02` | P6 | open | 0 | Yes | No | Produce one canonical integrated source tree containing product code, autonomy/runtime code, package metadata, configs, schemas, CLIs, services, tests, and operating procedures |

## Tracker-item exact verification text

### `MF-P6-20.02` — Canonical product/autonomy source integration

- **Current:** `open` at 0%
- **Source:** `24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md` line 15
- **Requirement:** Produce one canonical integrated source tree containing product code, autonomy/runtime code, package metadata, configs, schemas, CLIs, services, tests, and operating procedures · Verify: clean diff/secret/schema/import/package checks prove both source lines' required behavior survives · Blocked by: MF-P6-20.01 · HARD BLOCKER

