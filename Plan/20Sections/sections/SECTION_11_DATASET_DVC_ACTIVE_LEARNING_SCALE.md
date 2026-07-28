# Section 11 — Certified Dataset Build, DVC, Active Learning, and Scale

**Acceptance order:** 11 of 20  
**Mapped unresolved tracker items:** 13  
**Current states:** blocked=8, deferred=1, open=4  
**Hard blockers in scope:** 2  
**Rows with explicit Kevin authority/input:** 4  
**Depends on:** Section 05, Section 07, Section 10  
**Enables:** Section 12, Section 14, Section 17, Section 19

## Goal

Convert qualified truth into immutable, reproducible datasets; close the 100-certified sprint; scale coverage deliberately; and publish the residual real-data gap that governs later training and DAZ work.

## Why this section exists

Training and scale cannot be accepted while package counts mix truth tiers, DVC data is not frozen, coverage is incomplete, or hard-case/gap reports are not tied to immutable corpus and champion identities.

## Scope

- Close the 100-certified package sprint with human-anchor and autonomous-certified counts reported separately.
- Build and push `datasets/bodyparts@v1` through the governed DVC remote.
- Scale toward 300 and optional 500 certified packages with coverage-driven acquisition.
- Track touches, audits, residuals, changed pixels, and review time with valid denominators.
- Export qualified polygons/candidates into immutable weighted datasets.
- Run hard-case mining and publish the residual real-data gap report.
- Keep synthetic bootstrapping conditional, train-only, capped, and separately reported.

## Work packages

1. Reconcile package indexes, truth tiers, source groups, splits, and active certificates.
2. Create DVC dataset cards, fingerprints, remote receipts, and restore procedures.
3. Generate acquisition/mining plans from coverage and failures.
4. Execute the 100-package sprint and target coverage cells for scale.
5. Freeze the residual gap report against exact corpus/champion/failure hashes.

## Section-level testing

- Truth-tier count tests reject operational certificates, drafts, candidates, pseudo labels, and aliases.
- DVC clean-checkout pull/build/hash/restore test.
- Coverage matrix and minimum-cell tests with no easy-volume substitution.
- Image/source-family split leakage tests.
- Hard-case priority determinism and report-total reconciliation.
- Synthetic mix-cap, train-only, and source-origin enforcement tests.

## Integration tests with the rest of the project

- Section 12 consumes only exact dataset fingerprints and cards.
- Section 19 DAZ scale admission consumes the immutable residual-gap report.
- Section 20 can reconstruct every release dataset from DVC/manifest evidence.

## Definition of done and acceptance criteria

- [ ] The 100-certified sprint and P3 exit are accepted.
- [ ] A reproducible DVC dataset version exists and restores cleanly.
- [ ] Scale counts and coverage reports separate every truth tier.
- [ ] Hard-case mining and residual gap reports are complete and immutable.
- [ ] All mapped tracker items are complete or an explicitly conditional deferred item remains outside the core claim.

## Required proof artifacts

- `certified_package_reconciliation.json`
- `dataset_card_bodyparts_v1.json`
- `dvc_push_restore_receipt.json`
- `coverage_matrix.json`
- `human_labor_metrics.json`
- `hard_case_priority_report.json`
- `residual_real_data_gap_report.json`
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
| `MF-P3-07.01` | P3 | blocked | 0 | No | Yes | Residual/audit cadence uses SOP-2 (hands), SOP-3 (panels first), and SOP-4 (chest crop-zoom, projected separate) without requiring routine review of certificate-covered masks |
| `MF-P3-07.02` | P3 | blocked | 0 | No | No | Reach 100 certified packages with `human_anchor_train_count` and `autonomous_certified_gold_count` reported separately; pseudo-labels never count |
| `MF-P3-07.03` | P3 | blocked | 0 | No | Yes | Report human touches/100 images, audited fraction, residual-review fraction, changed pixels/100k, and review minutes as a secondary diagnostic |
| `MF-P3-07.04` | P3 | blocked | 0 | No | Yes | Begin fresh-day second-look sampling of hard-class human anchors and autonomous audits; formal mixed sampler lands P4-11 |
| `MF-P3-EXIT` | P3 | blocked | 0 | No | No | All lanes live · hard classes have panels/QCs · 100 certified packages reached with tier-separated counts · selective audit/residual labor reported · doc 14 §4 updated |
| `MF-P5-01.06` | P5 | open | 0 | No | No | Build `datasets\bodyparts@v1` · `dvc add` · `git tag dataset/bodyparts-v1` · `dvc push` to the governed local/persistent remote |
| `MF-P7-01.01` | P7 | blocked | 0 | No | Yes | Weekly acquisition driven by mining plans until **300 optional legacy training/scale certified packages** exist, counting only `human_anchor_train` plus exact `autonomous_certified_gold` packages carrying the required legacy statistical certificate; report both tiers separately and reject `operationally_certified_artifact`, bridge/operational certificates, drafts, candidates, pseudo labels, and any truth-tier alias |
| `MF-P7-01.02` | P7 | blocked | 0 | No | No | Verify coverage matrix ≥ 80% of view×pose cells at target (≥8/cell) and every attribute ≥ 40 — together with 01.01 this closes **D5** |
| `MF-P7-01.03` | P7 | blocked | 0 | No | No | Continue cadence toward the 500-package stretch target (G6) |
| `MF-P7-01.04` | P7 | deferred | 0 | No | No | (If used) Synthetic bootstrapping for stubborn deficit cells: scripted/3D-rendered images per doc 12 §9 · `source_origin: synthetic` · ≤ 30% mix cap · train-only · same QA battery |
| `MF-P5-11.01` | P5 | open | 0 | Yes | No | Export qualified polygons and machine-verified candidates into immutable weighted training datasets with exact source/remap/group seals |
| `MF-P5-11.08` | P5 | open | 0 | No | No | Implement hard-case mining over disagreement, rare/small anatomy, contact, cross-person leakage, occlusion, crop, laterality/front-back, wrong owner, boundary failure, repair exhaustion, and weak domain yield |
| `MF-P5-11.09` | P5 | open | 0 | Yes | No | Publish the immutable residual real-data gap report that names label/domain/risk/ownership/topology cells eligible for targeted DAZ generation |

## Tracker-item exact verification text

### `MF-P3-07.01` — 100-certified sprint + selective-review throughput

- **Current:** `blocked` at 0%
- **Source:** `04_ITEMS_P3_SPECIALIST_LANES.md` line 63
- **Requirement:** Residual/audit cadence uses SOP-2 (hands), SOP-3 (panels first), and SOP-4 (chest crop-zoom, projected separate) without requiring routine review of certificate-covered masks · Verify: review-task sample contains only residual/preselected-audit reasons
- **Current blocked reason:** NEEDS KEVIN: active SOP-2/3/4 cadence requires Kevin's manual CVAT correction work; specialist tooling and STATIC residual routing binder are implemented.

### `MF-P3-07.02` — 100-certified sprint + selective-review throughput

- **Current:** `blocked` at 0%
- **Source:** `04_ITEMS_P3_SPECIALIST_LANES.md` line 64
- **Requirement:** Reach 100 certified packages with `human_anchor_train_count` and `autonomous_certified_gold_count` reported separately; pseudo-labels never count · Verify: tracker/package index hashes reconcile exactly
- **Current blocked reason:** Certified count is 0. Reaching 100 may combine human-anchor train and autonomous-certified packages; Kevin is required only for source supply, anchor calibration, residuals, and audits.
- **Existing evidence to preserve/revalidate:** qa/live_verification/caa_truth_tier_gold_mapping_latest.json;qa/live_verification/gold_factory_runpod_admission_latest.json

### `MF-P3-07.03` — 100-certified sprint + selective-review throughput

- **Current:** `blocked` at 0%
- **Source:** `04_ITEMS_P3_SPECIALIST_LANES.md` line 65
- **Requirement:** Report human touches/100 images, audited fraction, residual-review fraction, changed pixels/100k, and review minutes as a secondary diagnostic · Verify: denominators and truth-tier breakdown are present
- **Current blocked reason:** NEEDS KEVIN: median review time requires real Kevin-entered review_tasks minutes across approved packages.

### `MF-P3-07.04` — 100-certified sprint + selective-review throughput

- **Current:** `blocked` at 0%
- **Source:** `04_ITEMS_P3_SPECIALIST_LANES.md` line 66
- **Requirement:** Begin fresh-day second-look sampling of hard-class human anchors and autonomous audits; formal mixed sampler lands P4-11 · Verify: sample selection precedes outcomes and records risk bucket
- **Current blocked reason:** NEEDS KEVIN: the fresh-day second-look habit is a human review activity reserved to Kevin.

### `MF-P3-EXIT` — Phase Exit Gate

- **Current:** `blocked` at 0%
- **Source:** `04_ITEMS_P3_SPECIALIST_LANES.md` line 69
- **Requirement:** All lanes live · hard classes have panels/QCs · 100 certified packages reached with tier-separated counts · selective audit/residual labor reported · doc 14 §4 updated
- **Current blocked reason:** P3 exit requires live specialist use, 100 tier-separated certified packages, and measured labor and quality evidence; the autonomous-certificate path is not calibrated yet.

### `MF-P5-01.06` — Dataset build v1 + DVC

- **Current:** `open` at 0%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 16
- **Requirement:** Build `datasets\bodyparts@v1` · `dvc add` · `git tag dataset/bodyparts-v1` · `dvc push` to the governed local/persistent remote

### `MF-P7-01.01` — Scale certified packages 300 → 500

- **Current:** `blocked` at 0%
- **Source:** `08_ITEMS_P7_SCALE_OPERATIONS.md` line 12
- **Requirement:** Weekly acquisition driven by mining plans until **300 optional legacy training/scale certified packages** exist, counting only `human_anchor_train` plus exact `autonomous_certified_gold` packages carrying the required legacy statistical certificate; report both tiers separately and reject `operationally_certified_artifact`, bridge/operational certificates, drafts, candidates, pseudo labels, and any truth-tier alias
- **Current blocked reason:** NEEDS KEVIN: governed source supply and initial human-anchor calibration are required; thereafter certificate-covered packages may advance the 300-certified cadence without routine manual approval.

### `MF-P7-01.02` — Scale certified packages 300 → 500

- **Current:** `blocked` at 0%
- **Source:** `08_ITEMS_P7_SCALE_OPERATIONS.md` line 13
- **Requirement:** Verify coverage matrix ≥ 80% of view×pose cells at target (≥8/cell) and every attribute ≥ 40 — together with 01.01 this closes **D5**
- **Current blocked reason:** D5 requires at least 300 certified training packages plus coverage of at least 80 percent; coverage authority comes from tier-separated certified packages and required human-anchor audits, not a collapsed gold count.

### `MF-P7-01.03` — Scale certified packages 300 → 500

- **Current:** `blocked` at 0%
- **Source:** `08_ITEMS_P7_SCALE_OPERATIONS.md` line 14
- **Requirement:** Continue cadence toward the 500-package stretch target (G6)
- **Current blocked reason:** The 500-certified stretch cadence requires continuing governed source supply and a functioning autonomous-certificate path; only residual and audit cases require Kevin.

### `MF-P7-01.04` — Scale certified packages 300 → 500

- **Current:** `deferred` at 0%
- **Source:** `08_ITEMS_P7_SCALE_OPERATIONS.md` line 15
- **Requirement:** (If used) Synthetic bootstrapping for stubborn deficit cells: scripted/3D-rendered images per doc 12 §9 · `source_origin: synthetic` · ≤ 30% mix cap · train-only · same QA battery

### `MF-P5-11.01` — P5

- **Current:** `open` at 0%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 27
- **Requirement:** Export qualified polygons and machine-verified candidates into immutable weighted training datasets with exact source/remap/group seals · Verify: unqualified, coarse-as-fine, reference, quarantined, and holdout records are rejected · Blocked by: MF-P0-18.06, MF-P4-12.08 · HARD BLOCKER

### `MF-P5-11.08` — P5

- **Current:** `open` at 0%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 34
- **Requirement:** Implement hard-case mining over disagreement, rare/small anatomy, contact, cross-person leakage, occlusion, crop, laterality/front-back, wrong owner, boundary failure, repair exhaustion, and weak domain yield · Verify: deterministic priority report covers every declared stratum and drives the next shard wave · Blocked by: MF-P4-12.09, MF-P5-11.07

### `MF-P5-11.09` — P5

- **Current:** `open` at 0%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 35
- **Requirement:** Publish the immutable residual real-data gap report that names label/domain/risk/ownership/topology cells eligible for targeted DAZ generation · Verify: report is hash-bound to corpus, champions, failure distributions, and coverage; easy-volume counts cannot satisfy a missing hard stratum · Blocked by: MF-P5-11.08 · HARD BLOCKER

