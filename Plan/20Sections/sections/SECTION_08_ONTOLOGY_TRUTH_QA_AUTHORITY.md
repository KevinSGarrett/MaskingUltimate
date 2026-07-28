# Section 08 — Ontology, Truth-Tier, and Quantitative QA Authority

**Acceptance order:** 8 of 20  
**Mapped unresolved tracker items:** 1  
**Current states:** partially_complete=1  
**Hard blockers in scope:** 1  
**Rows with explicit Kevin authority/input:** 0  
**Depends on:** Section 04, Section 05, Section 06, Section 07  
**Enables:** Section 09, Section 10, Section 11, Section 12, Section 14, Section 15, Section 17, Section 18, Section 19, Section 20

## Goal

Turn the current candidate per-label/per-context QA registry into an empirically calibrated, immutable authority that resolves every enabled ontology label and fails closed on missing, stale, or globally collapsed rules.

## Why this section exists

The registry implementation is advanced, but it explicitly remains unqualified and therefore cannot authorize `autonomous_certified_gold` or the later campaign/release gates.

## Scope

- Validate ontology and truth-tier authority across all enabled labels and contexts.
- Populate empirical calibration and qualification-holdout evidence from governed human anchors.
- Calibrate presence, area, components/holes, ownership, overlap, laterality, hierarchy, boundary, fill/leakage, topology, transforms, duplicates, and recomposition metrics.
- Publish an immutable qualified registry version and bind the runtime QA-vector verifier to it.
- Retain v1/v2 activation separation; actual active ontology switch remains in Section 12.

## Work packages

1. Build calibration records with exact source/package/label/context/metric identity.
2. Run positive/negative, domain/risk/size/context coverage checks.
3. Freeze thresholds before qualification-holdout evaluation.
4. Publish qualified registry and exact compatibility/invalidation rules.
5. Bind package admission and certificate authority to the qualified version.

## Section-level testing

- Every enabled label resolves exactly; disabled/unknown/duplicate/missing contexts fail.
- Calibration/holdout leakage, after-the-fact policy editing, stale hashes, and incomplete metrics fail.
- Per-record QA-vector identity and final-mask-set binding tests.
- Global-rule collapse and threshold-drift negative tests.
- Single- and multi-person canaries verify ownership and zero cross-person bleed rules.

## Integration tests with the rest of the project

- Section 10 critic/certificate logic consumes the exact registry hash.
- Section 14 campaigns cannot promote masks without a current QA vector.
- Sections 15–17 propagate registry version and invalidation semantics.

## Definition of done and acceptance criteria

- [ ] A qualified immutable QA registry—not a candidate—exists.
- [ ] Every enabled label/context has empirical evidence and finite thresholds.
- [ ] Runtime/package admission uses the exact registry and fails closed on drift.
- [ ] MF-P4-12.11 is accepted with live canaries and negative tests.

## Required proof artifacts

- `qualified_qa_registry.json`
- `calibration_manifest.json`
- `qualification_holdout_report.json`
- `qa_vector_runtime_binding.json`
- `registry_negative_tests.junit.xml`
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
| `MF-P4-12.11` | P4 | partially_complete | 72 | Yes | No | Define, calibrate, freeze, and hash-bind the quantitative per-label/per-context QA registry covering presence, area references, components/holes, ownership/containment, protected/exclusive/cross-person overlap, laterality/front-back, parent-child and atomic-map rules, boundary metrics, fill/leakage/unsupported pixels, thin structures, topology, transforms, perturbations, duplicates, and complete-map recomposition |

## Tracker-item exact verification text

### `MF-P4-12.11` — P4

- **Current:** `partially_complete` at 72%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 24
- **Requirement:** Define, calibrate, freeze, and hash-bind the quantitative per-label/per-context QA registry covering presence, area references, components/holes, ownership/containment, protected/exclusive/cross-person overlap, laterality/front-back, parent-child and atomic-map rules, boundary metrics, fill/leakage/unsupported pixels, thin structures, topology, transforms, perturbations, duplicates, and complete-map recomposition · Verify: every enabled ontology label resolves exactly; unknown/missing contexts, incomplete metrics, global-rule collapse, threshold drift, or absent calibration fail closed; only a new immutable empirically qualified registry version can authorize `autonomous_certified_gold` · Blocked by: MF-P2-11.21 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** qa/live_verification/autonomous_gold_per_record_qa_admission_20260722.json SHA256 50a284c6306f8b8b60565b090be73ffa4bb1bdb6f2327b1c6df153f56c43c3e9; autonomous_gold_qa_threshold_calibration closed schema/compiler/frozen-policy fixtures: 26 focused tests PASS; Ruff, Black, schema validation, and diff integrity PASS.

