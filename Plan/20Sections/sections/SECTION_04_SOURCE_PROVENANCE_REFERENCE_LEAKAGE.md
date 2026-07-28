# Section 04 — Governed Source Ingestion, Provenance, Reference Corpus, and Leakage Control

**Acceptance order:** 4 of 20  
**Mapped unresolved tracker items:** 9  
**Current states:** blocked=2, in_progress=1, partially_complete=6  
**Hard blockers in scope:** 0  
**Rows with explicit Kevin authority/input:** 1  
**Depends on:** Section 03  
**Enables:** Section 05, Section 06, Section 07, Section 08, Section 09, Section 10, Section 11, Section 12, Section 17, Section 18, Section 19

## Goal

Create the governed real-image and external-supervision foundation needed for calibration, training, benchmarks, and later DAZ gap targeting without allowing references, prompts, boxes, or unqualified masks to become truth.

## Why this section exists

Many downstream blockers are not code defects; they are missing governed real sources, inconsistent local/RunPod inventories, unqualified external labels, or leakage-safe split evidence.

## Scope

- Build the real-image v2 authority pilot from MaskedWarehouse and governed reference-library retrieval.
- Qualify Civitai auxiliary specialists only through measured, image-disjoint human-anchor evidence.
- Finish MaskedWarehouse external-supervision package materialization, batch caps, and source/label ablations.
- Reconcile `F:\Reference_Images\Ultimate_Masking_Reference_Images` with the RunPod mirror by exact inventory and sampled hashes.
- Finish governed reference selection/materialization, contact sheets, drift reporting, and immutable benchmark versioning.
- Enforce provenance, ownership/consent/license, deduplication, near-duplicate grouping, source-family splits, and holdout exclusion.

## Work packages

1. Create one source registry spanning local, RunPod, MaskedWarehouse, Civitai, and approved external providers.
2. Assign each record a truth tier, permitted use, label scope, source family, split group, and immutable hash.
3. Build leakage and duplicate reports before any calibration/training split is frozen.
4. Materialize only qualified train-only packages with explicit weights and scope.
5. Publish the 20–30 image v2 authority pilot and signed ambiguity/SOP-change report.

## Section-level testing

- Negative tests: reference-only images, prompts, boxes, unqualified masks, or leaked holdout data receive zero pixel-truth authority.
- Hash/inventory reconciliation between local and RunPod reference roots.
- Source-family and near-duplicate split leakage tests.
- External-label batch-cap and certified-real-dominance tests.
- Immutable benchmark replacement/drift tests.
- License/allowed-use/provenance completeness checks.

## Integration tests with the rest of the project

- Section 5 can select governed images without reopening provenance questions.
- Sections 6–12 consume one stable source registry and split seal.
- DAZ Section 19 receives a residual-gap report based on real evidence rather than synthetic-first assumptions.

## Definition of done and acceptance criteria

- [ ] Every consumed image/annotation/reference has an immutable provenance and permitted-use record.
- [ ] Local and RunPod reference inventories reconcile or fail closed.
- [ ] External supervision is scope-limited, leakage-disjoint, and non-regressing.
- [ ] The v2 authority pilot is complete with exact decisions and timings.
- [ ] All mapped tracker items are complete without promoting reference data to gold.

## Required proof artifacts

- `source_registry.jsonl`
- `provenance_audit.json`
- `reference_inventory_seal.json`
- `leakage_duplicate_report.json`
- `external_supervision_qualification.json`
- `v2_authority_pilot_report.json`
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
| `MF-P1-12.09` | P1 | partially_complete | 78 | No | No | Build a 20–30 real-image authority pilot from `C:\Comfy_UI_Main\MaskedWarehouse` plus retrieval/coverage evidence from `F:\Reference_Images\Ultimate_Masking_Reference_Images` and their RunPod mirrors |
| `MF-P1-12.10` | P1 | blocked | 0 | No | No | Record autonomous pilot latency, ambiguity/abstention outcomes, correction loops, and guideline changes before scale processing |
| `MF-P2-09.09` | P2 | blocked | 0 | No | Yes | Benchmark baseline vs each enabled assist on ≥30 image-disjoint human-anchor instances; publish per-label IoU, boundary-F, false-positive rate, latency, correction-pixel/labor delta, and hard-bucket non-inferiority; promote only measured winners and retain one-command rollback |
| `MF-P9-13.06` | P9 | partially_complete | 92 | No | No | Materialize qualified train-only packages and dataset cards with source/label/weight composition |
| `MF-P9-13.07` | P9 | partially_complete | 80 | No | No | Enforce the combined external-label batch cap while keeping certified real supervision dominant |
| `MF-P9-13.08` | P9 | partially_complete | 82 | No | No | Run leakage-disjoint real ablations by source and mapped label scope against qualified external-labeled benchmarks and any available independent human-anchor holdout |
| `MF-P9-14.06` | P9 | partially_complete | 50 | No | No | Materialize selections with hash verification and contact sheets |
| `MF-P9-14.09` | P9 | partially_complete | 95 | No | No | Run recurring drift/coverage reports and immutable benchmark versioning |
| `MF-P9-14.10` | P9 | in_progress | 80 | No | No | Reconcile `F:\Reference_Images\Ultimate_Masking_Reference_Images` with RunPod `/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images` before remote retrieval/calibration |

## Tracker-item exact verification text

### `MF-P1-12.09` — Ontology-v2 optional CVAT and autonomous authority surface

- **Current:** `partially_complete` at 78%
- **Source:** `12_ITEMS_P1_ONTOLOGY_V2_AND_TRUTH.md` line 40
- **Requirement:** Build a 20–30 real-image authority pilot from `C:\Comfy_UI_Main\MaskedWarehouse` plus retrieval/coverage evidence from `F:\Reference_Images\Ultimate_Masking_Reference_Images` and their RunPod mirrors · Verify: hash-bound distinct-image manifest covers every v2 state/applicable class without synthetic positives or mandatory human anchors · Blocked by: MF-P1-10.07
- **Existing evidence to preserve/revalidate:** PARTIAL_PASS 2026-07-22 corrected v2 artifacts: configs/ontology_v2_authority_pilot.generated.json file sha256 f6d8e4220922d81083c61950facfdaed5eeae9a297e49c028eec0dbb39e18f82 / self seal 380745f9ce2f53a3b2741f9ff95b04d18b4897665157b2598df8828181c84628; configs/ontology_v2_resolution_workload.generated.json file sha256 a0479c9daf3282fb3792f6279cba0cc6a31569696adebb56312707cda5273ff2 / self seal 3f8d9eca7027da36cb551972a71da69ed9c1004881856219e331aa1aee877147. The 24-image pilot binds 90 non-authoritative coverage targets. The 90 queued work units require proposal generation, owner/candidate binding, canonical v2 target-contract materialization, hard QA, qualified independent visual review, bounded repair, semantic alignment, and immutable outcome. All remain authority none; zero complete. 92 focused/adjacent tests, Ruff, Black, source rehash, tracker validation, and diff integrity pass.

### `MF-P1-12.10` — Ontology-v2 optional CVAT and autonomous authority surface

- **Current:** `blocked` at 0%
- **Source:** `12_ITEMS_P1_ONTOLOGY_V2_AND_TRUTH.md` line 41
- **Requirement:** Record autonomous pilot latency, ambiguity/abstention outcomes, correction loops, and guideline changes before scale processing · Verify: signed pilot report links source hashes, authority records, decisions, timings, ambiguity outcomes, and SOP revision · Blocked by: MF-P1-12.09
- **Current blocked reason:** Blocked by MF-P1-12.09 autonomous per-record semantic/visual authority resolution and outcome evidence; no routine Kevin or CVAT action is required.

### `MF-P2-09.09` — Governed Civitai auxiliary specialists

- **Current:** `blocked` at 0%
- **Source:** `03_ITEMS_P2_BODY_AWARE_DRAFTING.md` line 83
- **Requirement:** Benchmark baseline vs each enabled assist on ≥30 image-disjoint human-anchor instances; publish per-label IoU, boundary-F, false-positive rate, latency, correction-pixel/labor delta, and hard-bucket non-inferiority; promote only measured winners and retain one-command rollback
- **Current blocked reason:** NEEDS KEVIN: the promotion benchmark requires at least 30 image-disjoint human-anchor instances and real correction-time records; structural gates exist but no performance certificate can yet be minted.

### `MF-P9-13.06` — Qualified MaskedWarehouse external supervision

- **Current:** `partially_complete` at 92%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 161
- **Requirement:** Materialize qualified train-only packages and dataset cards with source/label/weight composition · Verify: builder and launcher accept only gated rows · Blocked by: MF-P9-13.05
- **Existing evidence to preserve/revalidate:** qa/live_verification/external_supervision_package_population_canary_20260722.json self 60cba86d0ac9e086a580c6cc68ea5e2022637763ffb3661ceaf03d01f0aace2d; runtime report seal ee3d115149bff8652146e99eee5e8b9310b1df8e9ee08ea92b4436a70a0affb2; 3 real packages / 3 sources, 34 focused tests PASS, Ruff/Black PASS. training_batch_eligible=false until a real full composition passes the unchanged cap.

### `MF-P9-13.07` — Qualified MaskedWarehouse external supervision

- **Current:** `partially_complete` at 80%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 162
- **Requirement:** Enforce the combined external-label batch cap while keeping certified real supervision dominant · Verify: boundary and bypass tests pass · Blocked by: MF-P9-13.06
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: validate_external_batch_cap enforces maximum_combined_external_batch_fraction=0.35 and certified-real dominance/majority; wired into datasets/builder.py and training/launch.py with builder/launcher metric agreement; boundary (0.35) and bypass (>0.35) plus ungated refuse tests pass. Evidence: qa/live_verification/external_supervision_packages_batch_cap_static_20260719.json. Not PRODUCTION_EVIDENCE_PASS / live batch claim.

### `MF-P9-13.08` — Qualified MaskedWarehouse external supervision

- **Current:** `partially_complete` at 82%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 163
- **Requirement:** Run leakage-disjoint real ablations by source and mapped label scope against qualified external-labeled benchmarks and any available independent human-anchor holdout · Verify: only non-regressing sources/labels remain active and absence of optional human anchors does not block the external-source ablation · Blocked by: MF-P9-13.06
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: holdout ablation now wired through dataset builder + training launcher training authority. sample_truth propagates ablation_active/label_names; builder discovers holdout_ablation_report.json; launcher requires bound sealed report when ablation_active=true; schema external_supervision_holdout_ablation_report registered. Evidence: qa/live_verification/external_supervision_holdout_ablation_builder_launch_static_20260719.json. Not live holdout execution; frozen real human-anchor holdout still required for completion.

### `MF-P9-14.06` — Governed reference corpus, benchmark, and retrieval

- **Current:** `partially_complete` at 50%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 171
- **Requirement:** Materialize selections with hash verification and contact sheets · Verify: every output exists and matches its recorded SHA-256 · Blocked by: MF-P9-14.05
- **Existing evidence to preserve/revalidate:** Benchmark materialization remains 2,500/2,500 and 7,897,306,748 verified bytes with fingerprint 5e1bd31cbf1697f3e2dbe41dfe7c0e96f9064bda001739d5e05393f0d7dac401. Contact-sheet stage created 93/93, failed 0, totaling 49,258,640 bytes with aggregate fingerprint 92afaeef45789095f25074ac03cac18f501d149096ba33c624392d342422200a. Post-stage published SQLite snapshot quick-check passes at SHA-256 a6b3250251b1b0371eb85cb050fb24c20316ce07970d1786efec6889982e216b. Retrieval materialization remains 0/18,000 because it would cross the 150-GiB soft floor. 1,762/1,762 full tests pass. Evidence: qa/reports/reference_benchmark_materialization_20260716.json.

### `MF-P9-14.09` — Governed reference corpus, benchmark, and retrieval

- **Current:** `partially_complete` at 95%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 174
- **Requirement:** Run recurring drift/coverage reports and immutable benchmark versioning · Verify: update cannot silently replace a frozen benchmark · Blocked by: MF-P9-14.06 through MF-P9-14.08
- **Existing evidence to preserve/revalidate:** Frozen version benchmark_reference_v1_7b36cdbe3b8795a8dfe38d1c binds 2,500 independently rehashed files, content digest 7b36cdbe3b8795a8dfe38d1cbde013d6febce8ad6f06651060c504ca3300c1e1, manifest SHA-256 dc672223b823ce8265db61f8bc842a4e463486c5e3cbd52101d89a19f3d12600, and materialized fingerprint 5e1bd31cbf1697f3e2dbe41dfe7c0e96f9064bda001739d5e05393f0d7dac401. The active manifest is configured. First append-only drift report SHA-256 1ceed034a4879016e90b0368ccf2c6f070a152227c4b9c3f8d045ed17cebea75 passes with identical frozen/current digest, zero issues, zero coverage deltas, and 2,500 members. Weekly active learning emits future reports. 1,762/1,762 full tests pass. Evidence: qa/reports/reference_benchmark_versioning_20260716.json.

### `MF-P9-14.10` — Governed reference corpus, benchmark, and retrieval

- **Current:** `in_progress` at 80%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 175
- **Requirement:** Reconcile `F:\Reference_Images\Ultimate_Masking_Reference_Images` with RunPod `/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images` before remote retrieval/calibration · Verify: inventory seal, database/manifest hashes, and sampled source hashes match; drift fails before provider invocation · Blocked by: MF-P9-14.02
- **Existing evidence to preserve/revalidate:** qa/live_verification/runpod_persistence_binding_20260722.json and qa/live_verification/runpod_corpus_mirror_reconciliation_20260722.json: current pod RUNNING; 1 TiB persistent volume 13/13; exact remote snapshot hash 46f5fee69ef7acb0479c0c68c3fe07bedf351224f79f909a23bdf1ef5170a205; both required roots and top-level structures 10/10.

