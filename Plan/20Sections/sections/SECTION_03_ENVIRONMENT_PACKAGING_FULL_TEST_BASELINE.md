# Section 03 — Reproducible Environment, Packaging, Clean Export, and Full Test Baseline

**Acceptance order:** 3 of 20  
**Mapped unresolved tracker items:** 4  
**Current states:** open=2, partially_complete=2  
**Hard blockers in scope:** 2  
**Rows with explicit Kevin authority/input:** 0  
**Depends on:** Section 02  
**Enables:** Section 04, Section 05, Section 06, Section 07, Section 08, Section 09, Section 10, Section 11, Section 12, Section 13, Section 14, Section 15, Section 16, Section 17, Section 18, Section 19, Section 20

## Goal

Make the canonical tree independently installable and testable on authorized Windows/WSL/RunPod environments, classify every external prerequisite honestly, and establish the first trustworthy full-product baseline.

## Why this section exists

The snapshot contains a green 916-outcome log, while Plan 28 records a 4,446-test full surface that did not pass. A fresh collection also fails in the export. Lower-tier or contaminated-environment success cannot substitute for a clean full-suite result.

## Scope

- Pin Python, package, CUDA/PyTorch, WSL, Windows, RunPod, CVAT, service, and toolchain versions.
- Build wheel/sdist and clean editable-install paths; verify entry points and package data.
- Classify all tests as hermetic, provisioned integration, or live acceptance with explicit asset/GPU/service prerequisites.
- Repair collection/runtime failures, completion-policy drift, missing modules, and hidden local-state dependencies.
- Prove persistent RunPod package durability, hash-bound sync, restore, and F-drive backup replication.
- Run static, focused, steward, product, service, integration, clean-export, and complete collected suites.

## Work packages

1. Create authoritative lockfiles and environment manifests for each supported runtime.
2. Add asset manifests with source, hash, license/allowed-use, path, acquisition authority, and skip/fail semantics.
3. Build a clean export and install into a new environment with user site-packages disabled.
4. Repair every unexplained test collection or runtime failure.
5. Create owned startup/health/shutdown scripts and prove zero leaked ports, leases, reservations, children, or GPU processes.

## Section-level testing

- Wheel/sdist build and install test in a clean environment.
- Full module import and CLI `--help`/doctor/schema/tracker validation.
- Complete product-suite collection count reconciliation; every test passes or is governed with a reproducible explicit prerequisite.
- Provisioned asset negative tests for missing, partial, corrupt, wrong-hash, or wrong-version assets.
- Clean restore after process/pod replacement and backup-replication verification.
- Owned service start/health/bounded route/shutdown/resource-leak test.

## Integration tests with the rest of the project

- The same release bytes run locally and on the selected RunPod storage/runtime path.
- Tests use the canonical source tree and exact lockfiles, not ambient packages.
- Tracker, evidence reconstruction, services, and CLI all operate in the clean export.

## Definition of done and acceptance criteria

- [ ] The complete test inventory is documented and reconciled.
- [ ] No unexplained collection/runtime failure remains.
- [ ] A clean export installs and passes required non-live suites independently.
- [ ] External prerequisites are explicit and cannot be reported as pass when absent.
- [ ] Persistent-storage restore and owned shutdown pass.
- [ ] MF-P0-EXIT, MF-P0-17.25, MF-P6-20.03, and MF-P6-20.04 are accepted with one reconstruction receipt.

## Required proof artifacts

- `environment_lock_manifest.json`
- `external_asset_contracts.json`
- `test_inventory.json`
- `full_suite_junit.xml`
- `clean_export_reconstruction_receipt.json`
- `service_lifecycle_evidence.json`
- `runpod_restore_receipt.json`
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
| `MF-P0-EXIT` | P0 | partially_complete | 85 | No | No | Doctor all green end-to-end · `env\` lockfiles + populated `model_registry.json` committed (D9 provable on paper) · phase checkboxes in doc 14 §1 updated |
| `MF-P0-17.25` | P0 | partially_complete | 85 | No | No | Prove production package durability on persistent RunPod storage independently from the F-drive backup tier |
| `MF-P6-20.03` | P6 | open | 0 | Yes | No | Classify and repair the complete product test baseline, including completion-policy drift and every external-asset dependency |
| `MF-P6-20.04` | P6 | open | 0 | Yes | No | Prove clean-export installation, exact-byte runtime closure, focused/integration/full-suite execution, bounded service health, and owned shutdown |

## Tracker-item exact verification text

### `MF-P0-EXIT` — Phase Exit Gate

- **Current:** `partially_complete` at 85%
- **Source:** `01_ITEMS_P0_ENVIRONMENT.md` line 89
- **Requirement:** Doctor all green end-to-end · `env\` lockfiles + populated `model_registry.json` committed (D9 provable on paper) · phase checkboxes in doc 14 §1 updated
- **Existing evidence to preserve/revalidate:** qa/live_verification/proof_tier_runtime_reprobe_20260719T1917.json

### `MF-P0-17.25` — Modern provider catalog, isolated runtimes, and installation evidence

- **Current:** `partially_complete` at 85%
- **Source:** `11_ITEMS_P0_MODERNIZATION_FOUNDATION.md` line 51
- **Requirement:** Prove production package durability on persistent RunPod storage independently from the F-drive backup tier · Verify: exact versioned package descriptor, resumable hash-bound sync, clean restore after process/pod replacement, F-drive backup replication, and missing/corrupt/partial-file rejection all pass without ephemeral-root or AWS authority · Blocked by: MF-P0-17.16 and an available persistent RunPod volume
- **Existing evidence to preserve/revalidate:** qa/live_verification/runpod_package_persistence_and_restore_20260722.json SHA256=0954318c66c5a5f97ea1a1da4774bdc8339564df0160f78e9ffb30de6541a9db; runtime_artifacts/runpod_package_persistence_20260722/{preflight,live_sync,live_sync_resume,live_sync_hardened_resume,live_sync_missing_repair,live_sync_corrupt_repair,live_sync_partial_repair}.json; qa/live_verification/dvc_packages_first_push_restore_20260722.json SHA256=6321e81bab426e4513a2b16fc1b5f456292cab21714588fd74be342906de1354

### `MF-P6-20.03` — Canonical product/autonomy source integration

- **Current:** `open` at 0%
- **Source:** `24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md` line 16
- **Requirement:** Classify and repair the complete product test baseline, including completion-policy drift and every external-asset dependency · Verify: each collected test is passing or has a governed explicit environment prerequisite that cannot be misreported as pass; no unexplained collection/runtime failure remains · Blocked by: MF-P6-20.02 · HARD BLOCKER

### `MF-P6-20.04` — Canonical product/autonomy source integration

- **Current:** `open` at 0%
- **Source:** `24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md` line 17
- **Requirement:** Prove clean-export installation, exact-byte runtime closure, focused/integration/full-suite execution, bounded service health, and owned shutdown · Verify: an independent reconstruction receipt binds source, environment, commands, results, processes, ports, and zero leaked resources · Blocked by: MF-P6-20.03 · HARD BLOCKER

