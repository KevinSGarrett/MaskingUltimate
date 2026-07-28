# Section 07 — Single-Person Draft Pipeline and Deterministic Auto-QA

**Acceptance order:** 7 of 20  
**Mapped unresolved tracker items:** 3  
**Current states:** blocked=3  
**Hard blockers in scope:** 0  
**Rows with explicit Kevin authority/input:** 3  
**Depends on:** Section 05, Section 06  
**Enables:** Section 08, Section 09, Section 10, Section 11, Section 12, Section 15, Section 17

## Goal

Prove one deterministic command can take governed single-person images through complete indexed draft generation and objective comparison to human gold while reducing measured human work.

## Why this section exists

Most pipeline code exists, but the tracker still lacks the authoritative 25-image run, fresh-image D1 demonstration, corrected-reference metrics, and measured improvement over the Section-5 baseline.

## Scope

- Reach the governed 25-image calibration run using model-major batching.
- Run every active indexed PART draft with exact provenance and selected production ontology.
- Exercise deterministic auto-QA, retries, quarantine, and file-only stage handoff.
- Run one genuinely fresh incoming image through the literal CLI.
- Measure draft-vs-gold quality and human-work reduction against Section 5.

## Work packages

1. Supply/ingest the remaining governed originals.
2. Execute the canonical stage graph from clean inputs and record per-stage hashes/configs/durations.
3. Correct the evaluation subset through the human-anchor workflow where not already complete.
4. Publish D1/G2 and P2-exit evidence.
5. Verify cache invalidation and idempotent reruns.

## Section-level testing

- Fresh-image one-command E2E with byte- and manifest-level evidence.
- Same-input/same-config determinism and config-drift invalidation.
- Retry/quarantine/continue-on-error tests across a batch.
- All PART masks strict-format, ontology, ownership, containment, and complete-map checks.
- Paired quality/labor comparison versus Section-5 baseline with valid denominators.

## Integration tests with the rest of the project

- Outputs are accepted by Section-8 QA-vector evaluation and Section-10 visual panels.
- Stage outputs are packageable and reviewable in CVAT.
- Provider provenance from Section 6 remains intact through final draft manifests.

## Definition of done and acceptance criteria

- [ ] Twenty-five governed images complete the canonical draft path.
- [ ] One fresh image passes the D1 one-command demonstration.
- [ ] Draft-vs-gold quality and labor metrics are published.
- [ ] Measured work reduction has no quality regression.
- [ ] P2 exit and all mapped items are accepted.

## Required proof artifacts

- `draft25_input_manifest.json`
- `draft25_run_receipt.json`
- `fresh_image_D1_receipt.json`
- `draft_vs_gold_metrics.json`
- `human_work_reduction_report.json`
- `stage_hash_inventory.json`
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
| `MF-P2-08.01` | P2 | blocked | 88 | No | Yes | Ingest + draft 25 images end-to-end, model-major batching (one heavy model resident at a time; runtime ≈2.5–3.5 min/img verified vs doc 07 budget table) |
| `MF-P2-08.04` | P2 | blocked | 98 | No | Yes | Record G2 initial numbers in OPS_LOG · verify **D1**: one CLI command takes a new incoming image to every indexed PART draft in the selected production ontology (56 active v1; 65 after gated v2 activation) |
| `MF-P2-EXIT` | P2 | blocked | 0 | No | Yes | Drafts measurably reduce human touches, changed pixels, residual-review fraction, and review minutes versus the P1 human-anchor baseline without quality regression · doc 14 §3 checkboxes updated |

## Tracker-item exact verification text

### `MF-P2-08.01` — 25-image draft→human-anchor run + baseline

- **Current:** `blocked` at 88%
- **Source:** `03_ITEMS_P2_BODY_AWARE_DRAFTING.md` line 69
- **Requirement:** Ingest + draft 25 images end-to-end, model-major batching (one heavy model resident at a time; runtime ≈2.5–3.5 min/img verified vs doc 07 budget table)
- **Current blocked reason:** NEEDS KEVIN: three additional governed originals are required to reach the 25-source calibration count.
- **Existing evidence to preserve/revalidate:** 22/25 governed sources have complete S09.5/D1 contracts. Two confirmed-valid S02 resolutions are sealed and replayed without changing the model QC threshold; both recovered sources pass QC-035 and four D1 contracts independently verify 224 strict non-overlapping atomic masks. Evidence: qa/live_verification/s02_review_recovery_20260712.json.

### `MF-P2-08.04` — 25-image draft→human-anchor run + baseline

- **Current:** `blocked` at 98%
- **Source:** `03_ITEMS_P2_BODY_AWARE_DRAFTING.md` line 72
- **Requirement:** Record G2 initial numbers in OPS_LOG · verify **D1**: one CLI command takes a new incoming image to every indexed PART draft in the selected production ontology (56 active v1; 65 after gated v2 activation)
- **Current blocked reason:** NEEDS KEVIN: completion requires one genuinely fresh Kevin-supplied governed original through literal maskfactory draft plus corrected-reference G2 measurements.
- **Existing evidence to preserve/revalidate:** qa/live_verification/s09_d1_corpus_20260712.json records 29 verified contracts, 1,624 independently decoded strict binary PNGs, exact hash/non-overlap/coverage/PART-map reproduction, 18 QC-035-pass source manifests, and zero temporary-directory failures.

### `MF-P2-EXIT` — Phase Exit Gate

- **Current:** `blocked` at 0%
- **Source:** `03_ITEMS_P2_BODY_AWARE_DRAFTING.md` line 86
- **Requirement:** Drafts measurably reduce human touches, changed pixels, residual-review fraction, and review minutes versus the P1 human-anchor baseline without quality regression · doc 14 §3 checkboxes updated
- **Current blocked reason:** NEEDS KEVIN: P2 exit requires the P1 review-time baseline and P2 corrected-gold review minutes to prove a real G1 improvement.

