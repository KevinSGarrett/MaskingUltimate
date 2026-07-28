# Section 05 — Human-Anchor Gold Factory, CVAT Review, and Measured Baselines

**Acceptance order:** 5 of 20  
**Mapped unresolved tracker items:** 8  
**Current states:** blocked=8  
**Hard blockers in scope:** 0  
**Rows with explicit Kevin authority/input:** 8  
**Depends on:** Section 03, Section 04  
**Enables:** Section 06, Section 07, Section 08, Section 09, Section 10, Section 11, Section 12, Section 17, Section 19

## Goal

Create the minimum real human-authoritative gold and timing foundation that unlocks calibration, objective scoring, training, and headline claims.

## Why this section exists

The tracker currently reports zero human-anchor packages for several gates. No model, VLM, autonomous certificate, or synthetic source may substitute for the required human-authoritative baseline.

## Scope

- Complete SOP-1 annotation/correction for the first five governed images in CVAT.
- Package and verify all five as `human_approved_gold` with exact lineage.
- Record real operator minutes/image and changed-pixel/touch baselines.
- Expand to approximately 30 image-disjoint human-anchor packages with train/calibration/holdout partitions.
- Score the draft pipeline against corrected gold and publish the baseline leaderboard row.
- Run a package backup/restore-to-CVAT drill.

## Work packages

1. Complete the reserved CVAT jobs with all visible atomics, materials, attributes, ambiguity, laterality, and ownership.
2. Run package verification, strict PNG/schema/ontology/QC checks, and immutable package sealing.
3. Capture review-task timing and edit metrics from actual work—not estimates.
4. Freeze disjoint partitions and reviewer identities.
5. Restore one package from the backup tier to a clean temporary root and open it successfully in CVAT.

## Section-level testing

- CVAT export/import round-trip and package verification.
- Human-authority test: autonomous, pseudo, reference, and synthetic records cannot count as human anchors.
- Image-disjoint split and duplicate-group tests.
- Metric denominator tests for minutes, touches, changed pixels, and per-label scores.
- Backup hash, restore, `verify-package --root`, and CVAT usability test.

## Integration tests with the rest of the project

- Section 7 can compare drafts to immutable corrected truth.
- Section 8 can empirically calibrate the per-label/context QA registry.
- Section 10 can build the 20-anchor/40-panel and larger visual-evaluation corpora.
- Section 12 can freeze final human holdouts for promotion decisions.

## Required user/authority actions

- Perform the reserved SOP-1 CVAT annotation/correction decisions.
- Supply any additional governed originals needed to reach the real-image minimum.
- Record actual review time where the system cannot infer it authoritatively.

## Definition of done and acceptance criteria

- [ ] Five complete human-approved packages and approximately 30 partitioned anchors exist.
- [ ] Baseline operator time and edit metrics are measured and stored.
- [ ] Draft-vs-gold leaderboard input is reproducible.
- [ ] One package restore drill passes.
- [ ] P1 exit evidence is accepted and all mapped tracker items are complete.

## Required proof artifacts

- `human_anchor_manifest.json`
- `cvat_review_receipts/`
- `human_gold_package_index.json`
- `review_time_baseline.json`
- `draft_pipeline_baseline.json`
- `backup_restore_receipt.json`
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
| `MF-P1-08.02` | P1 | blocked | 0 | No | Yes | Annotate image 1 fully in CVAT per SOP-1 (all visible atomics, bands, materials, visibility attrs, honest ambiguity) |
| `MF-P1-08.03` | P1 | blocked | 0 | No | Yes | Annotate images 2–5 the same way |
| `MF-P1-08.04` | P1 | blocked | 58 | No | Yes | `package` + `verify-package` all 5 → `human_approved_gold` |
| `MF-P1-08.05` | P1 | blocked | 0 | No | Yes | Record baseline minutes/image in OPS_LOG (G1 baseline for the throughput trend) |
| `MF-P1-09.05` | P1 | blocked | 35 | No | Yes | Dry-run one restore: pull 1 package from B1 to temp → `verify-package --root` passes |
| `MF-P1-EXIT` | P1 | blocked | 0 | No | Yes | End-to-end demo recorded in OPS_LOG: incoming → CVAT → human-anchor gold with QA enforced · doc 14 §2 checkboxes updated |
| `MF-P2-08.02` | P2 | blocked | 0 | No | Yes | Review/correct the calibration subset in CVAT → approximately 30 human-anchor packages with explicit train/calibration/holdout partitions |
| `MF-P2-08.03` | P2 | blocked | 0 | No | Yes | Create `runs\leaderboard.jsonl` · publish `draft_pipeline_full` row: draft-vs-gold per-part IoU + boundary-F on these packages |

## Tracker-item exact verification text

### `MF-P1-08.02` — First 5 gold packages, hand-driven

- **Current:** `blocked` at 0%
- **Source:** `02_ITEMS_P1_GOLD_FACTORY_MVP.md` line 73
- **Requirement:** Annotate image 1 fully in CVAT per SOP-1 (all visible atomics, bands, materials, visibility attrs, honest ambiguity)
- **Current blocked reason:** NEEDS KEVIN: SOP-1 requires Kevin's actual CVAT correction/annotation clicks; the governed image-1 review package is ready in CVAT task/job 21, but human annotation authority cannot be substituted.

### `MF-P1-08.03` — First 5 gold packages, hand-driven

- **Current:** `blocked` at 0%
- **Source:** `02_ITEMS_P1_GOLD_FACTORY_MVP.md` line 74
- **Requirement:** Annotate images 2–5 the same way
- **Current blocked reason:** NEEDS KEVIN: images 2-5 are fully staged as governed CVAT tasks/jobs 22-25 and now require Kevin's manual SOP-1 annotation/correction clicks.

### `MF-P1-08.04` — First 5 gold packages, hand-driven

- **Current:** `blocked` at 58%
- **Source:** `02_ITEMS_P1_GOLD_FACTORY_MVP.md` line 75
- **Requirement:** `package` + `verify-package` all 5 → `human_approved_gold`
- **Current blocked reason:** NEEDS KEVIN: drafts remain HARD_QA_PASS_BOUNDED after bounded noise repairs (4 promoted) but VISUAL_QA_REVIEWED_WITH_DEFECTS; underfill/bleed/half-fill/garment ABSTAIN_BOUNDED; human_approved_gold still requires Kevin CVAT correction. Human-anchor train count remains 0.
- **Existing evidence to preserve/revalidate:** qa/live_verification/bounded_visual_residual_20260719.json sha256 ccf223c98874452b908aad03e8f339688ccfdc43d7ba548ee58be7eb5f4cf823; tests/test_visual_defect_abstention.py; src/maskfactory/autonomy/visual_defect_policy.py

### `MF-P1-08.05` — First 5 gold packages, hand-driven

- **Current:** `blocked` at 0%
- **Source:** `02_ITEMS_P1_GOLD_FACTORY_MVP.md` line 76
- **Requirement:** Record baseline minutes/image in OPS_LOG (G1 baseline for the throughput trend)
- **Current blocked reason:** NEEDS KEVIN: the real baseline minutes/image must come from Kevin's completed review_tasks; no operator time may be fabricated.

### `MF-P1-09.05` — First 5 gold packages, hand-driven

- **Current:** `blocked` at 35%
- **Source:** `02_ITEMS_P1_GOLD_FACTORY_MVP.md` line 83
- **Requirement:** Dry-run one restore: pull 1 package from B1 to temp → `verify-package --root` passes
- **Current blocked reason:** NEEDS KEVIN: no P1-08 human-anchor package or B1 mirror exists yet; the restore drill needs one corrected seed package first.

### `MF-P1-EXIT` — Phase Exit Gate

- **Current:** `blocked` at 0%
- **Source:** `02_ITEMS_P1_GOLD_FACTORY_MVP.md` line 86
- **Requirement:** End-to-end demo recorded in OPS_LOG: incoming → CVAT → human-anchor gold with QA enforced · doc 14 §2 checkboxes updated
- **Current blocked reason:** NEEDS KEVIN: P1 exit requires the incoming-to-CVAT-to-human-anchor demonstration and measured operator time from MF-P1-08.02 through MF-P1-08.05.

### `MF-P2-08.02` — 25-image draft→human-anchor run + baseline

- **Current:** `blocked` at 0%
- **Source:** `03_ITEMS_P2_BODY_AWARE_DRAFTING.md` line 70
- **Requirement:** Review/correct the calibration subset in CVAT → approximately 30 human-anchor packages with explicit train/calibration/holdout partitions
- **Current blocked reason:** NEEDS KEVIN: approximately 30 image-disjoint human-anchor packages require the reserved CVAT review and correction decisions; human-anchor count is 0.

### `MF-P2-08.03` — 25-image draft→human-anchor run + baseline

- **Current:** `blocked` at 0%
- **Source:** `03_ITEMS_P2_BODY_AWARE_DRAFTING.md` line 71
- **Requirement:** Create `runs\leaderboard.jsonl` · publish `draft_pipeline_full` row: draft-vs-gold per-part IoU + boundary-F on these packages
- **Current blocked reason:** NEEDS KEVIN: draft_pipeline_full scoring requires corrected image-disjoint human-anchor packages; no authoritative anchor holdout currently exists for IoU and boundary-F.

