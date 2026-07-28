# Section 12 — Custom Training, Leaderboard, Champion Promotion, and Ontology-v2 Activation

**Acceptance order:** 12 of 20  
**Mapped unresolved tracker items:** 34  
**Current states:** blocked=19, deferred=2, open=7, partially_complete=6  
**Hard blockers in scope:** 7  
**Rows with explicit Kevin authority/input:** 8  
**Depends on:** Section 06, Section 08, Section 10, Section 11  
**Enables:** Section 13, Section 14, Section 15, Section 16, Section 17, Section 19, Section 20

## Goal

Train and objectively select body, clothing, hand, anatomy-aware, and optional challengers; promote only image-disjoint human-holdout winners; prove rollback; and activate ontology v2 atomically only after every gate passes.

## Why this section exists

Serving and final integration are blocked because champion roles are absent. Static configs and partial training contracts are not enough; the project needs real checkpoints, frozen evaluations, transactional promotion, and v1 rollback.

## Scope

- Train/evaluate SegFormer, Mask2Former, clothing/material, hand, EoMT/DINOv3, anatomy-aware cascade, and qualified optional models.
- Build leakage-safe representation pretraining and governed teacher-student iterations.
- Write complete leaderboard rows with per-class, boundary, hard-bucket, labor, uncertainty, and human-ceiling evidence.
- Promote exact champion roles transactionally and prove one-command rollback.
- Run post-swap regression and remeasure G1/G2/G3.
- Complete v2 dataset/class evidence, activation bundle, active derived config, serving/workflow compatibility, and v1 rollback.
- Open the temporal video lane only after a qualified still-image champion.

## Work packages

1. Freeze data, splits, configs, seeds, objectives, and non-inferiority margins before training.
2. Execute training directly on governed RunPod storage with checkpoint/output hashes.
3. Evaluate every challenger on untouched human-anchor holdouts and hard-case holdouts.
4. Update model registry champion pointers and lifecycle history transactionally.
5. Run serving and pipeline smokes in both promoted and rolled-back states.
6. Assemble and execute the ontology-v2 activation/rollback bundle.

## Section-level testing

- Reproducible run-manifest and checkpoint-hash tests.
- Frozen holdout, leakage, source-family balance, label-scope, and batch-composition tests.
- Promotion gates for primary win/labor objective plus every hard-label/high-risk non-inferiority margin.
- Negative tests reject autonomous/pseudo truth as final promotion authority.
- Transactional role promotion/demotion, service reload, and one-command rollback.
- Ontology/config/registry/workflow atomic agreement and v1 rollback smoke.
- Post-swap QC regression and latency/VRAM measurements.

## Integration tests with the rest of the project

- Section 15 `/predict` loads only exact champions.
- Section 14 mask campaigns bind champion/provider identities.
- Section 17 multi-person routing uses the promoted roles and rollback policy.
- Section 20 release includes exact checkpoint/config/runtime identities.

## Required user/authority actions

- Provide/approve sufficient final human-anchor holdout and v2 class evidence where the tracker explicitly requires human authority.

## Definition of done and acceptance criteria

- [ ] Real trained champions exist for required roles and beat incumbents under frozen gates.
- [ ] Leaderboard rows are complete, tier-separated, and human-holdout authoritative.
- [ ] Promotion and rollback work both directions without corrupting history.
- [ ] Ontology v2 activates atomically only if every required gate passes; v1 rollback remains valid.
- [ ] P5 exit and all mapped tracker items are complete, except truly conditional optional models that remain explicitly outside the accepted claim.

## Required proof artifacts

- `training_run_manifests/`
- `leaderboard_frozen.jsonl`
- `champion_promotion_receipts/`
- `champion_rollback_receipts/`
- `post_swap_regression.json`
- `ontology_v2_activation_bundle.json`
- `ontology_v1_rollback_receipt.json`
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
| `MF-P1-10.05` | P1 | partially_complete | 90 | No | No | Add all v2 derived formulas and regenerate the active `configs/derived.yaml` only at activation |
| `MF-P5-03.02` | P5 | blocked | 75 | No | No | Train SegFormer-B3 directly on RunPod · eval per-part IoU + boundary-F on val every 4k |
| `MF-P5-03.03` | P5 | partially_complete | 65 | No | No | Challenger: Mask2Former-SwinB config + run (activation checkpointing) — optional Swin-L only on a capacity-qualified RunPod tier (05-08.03) |
| `MF-P5-03.04` | P5 | blocked | 0 | No | No | Final eval on frozen test_holdout + hard_case_holdout → leaderboard rows with full per-class + group scores |
| `MF-P5-04.02` | P5 | blocked | 70 | No | No | Train + eval · GATE: beats SCHP+S08 heuristics on material mIoU AND strap/waistband IoU ≥ 0.55 |
| `MF-P5-05.03` | P5 | blocked | 0 | No | No | Train + eval on the hand-crop holdout |
| `MF-P5-05.04` | P5 | blocked | 70 | Yes | Yes | GATE (**D7**): finger-class mean IoU ≥ 0.70 AND merged-finger false-split rate < 2% |
| `MF-P5-05.05` | P5 | blocked | 98 | No | Yes | On win: replace lane steps 2.3–2.4 as crop drafter (SAM2 stays the interactive editor) · model outputs pass QC-018 paste-back ≥ 0.995 |
| `MF-P5-06.01` | P5 | blocked | 90 | No | No | `training\leaderboard.py` full schema writer · standing baselines auto-scored per dataset version: sam2_only · sam2_pose · sam2_parsing · draft_pipeline_full |
| `MF-P5-06.03` | P5 | blocked | 92 | No | No | Champion pointers in `models\model_registry.json` (`role: champion_bodypart` etc.) · all loaders/serving read champions ONLY |
| `MF-P5-07.02` | P5 | blocked | 70 | Yes | Yes | Verify **D6/G7**: champion beats draft_pipeline_full on frozen test_holdout in BOTH mean per-part IoU and boundary-F, with NO tracked hard class regressing > 2 pts |
| `MF-P5-07.03` | P5 | blocked | 0 | No | Yes | Remeasure G1 (target trend ≤ 12 min/img) + publish G2/G3 numbers |
| `MF-P5-07.04` | P5 | blocked | 0 | No | Yes | QC-034 regression sweep on a re-processed sample after the swap — clean |
| `MF-P5-08.01` | P5 | deferred | 0 | No | No | (Trigger: ≥80 hair-prominent certified training packages with required human-anchor holdout) ViTMatte fine-tune · GATE: hair boundary-F ≥0.65 AND matte MSE −15% vs stock |
| `MF-P5-08.02` | P5 | deferred | 0 | No | No | (Trigger: ≥ 120 approved projected labels AND chest-lane fail rate > 10%) breastproj SegFormer-B1 · GATE: projected IoU ≥ 0.75 · outputs provenance-tagged `model:breastproj@<run>`, purple-editable, never truth |
| `MF-P5-08.03` | P5 | open | 0 | No | No | (Optional) RunPod scale runbook executed once: validate persistent inputs · train directly on the selected pod · persist/hash outputs and evidence |
| `MF-P5-09.08` | P5 | blocked | 0 | No | Yes | Reach 50–100 clear positive instances per appended class before production claims |
| `MF-P5-09.09` | P5 | blocked | 0 | No | No | Publish per-class IoU, boundary-F, recall, clothed false positives, and side-swap rates |
| `MF-P5-09.10` | P5 | blocked | 0 | Yes | No | Refuse promotion when any appended class lacks evidence or systematically fires on clothing |
| `MF-P5-10.07` | P5 | partially_complete | 75 | No | No | Train/evaluate EoMT/DINOv3 alongside SegFormer and Mask2Former under identical frozen data, ontology, hardware, QA, and measurement code |
| `MF-P5-10.08` | P5 | partially_complete | 90 | No | No | Define role-specific primary metric/labor objective and predeclare non-inferiority margins for every hard label/high-risk bucket before results |
| `MF-P5-10.11` | P5 | partially_complete | 90 | Yes | No | Promote winner and demote incumbent to benchmarked transactionally; prove one-command rollback restores role/lifecycle and serving |
| `MF-P5-10.12` | P5 | blocked | 40 | No | Yes | Evaluate final promotions only against image-disjoint human-anchor holdout and publish tier-separated leaderboard rows, human ceiling, labor metrics, and uncertainty |
| `MF-P5-EXIT` | P5 | blocked | 0 | No | Yes | Custom models are the drafters · leaderboard is the arbiter · **D6 + D7** checked with evidence rows · doc 14 §6 checkboxes updated |
| `MF-P5-11.03` | P5 | open | 0 | No | No | Train and benchmark anatomy-aware challengers, then promote only measured winners through existing champion policy |
| `MF-P5-11.04` | P5 | open | 0 | Yes | No | Build the real-supervision foundation with source-family-balanced sampling, per-source/per-label reliability weights, coarse-versus-fine losses, and rare-class coverage |
| `MF-P5-11.05` | P5 | open | 0 | No | No | Implement and benchmark the hierarchical cascade for person/character discovery, ownership/occlusion, silhouette, coarse anatomy, atomic specialists, boundary refinement, and complete-map consistency |
| `MF-P5-11.06` | P5 | open | 0 | No | No | Run leakage-safe self-supervised or masked-image representation pretraining over eligible `F:\Reference_Images` and reference-only MaskedWarehouse partitions without pixel-label invention |
| `MF-P5-11.07` | P5 | open | 0 | Yes | No | Run proposal expansion and iterative teacher-student retraining with immutable weighted mixtures: certified truth highest, qualified polygons/RLE medium, eligible machine candidates lower, and boxes/prompts/actions/references/unqualified proposals zero pixel-loss weight |
| `MF-P5-11.10` | P5 | open | 0 | No | No | After a qualified still-image champion, implement the temporal video lane with keyframes, bidirectional propagation, correspondence/flow consistency, persistent ownership, cut/occlusion/re-entry recovery, uncertain-frame re-segmentation, and per-frame immutable evidence; keep audio as context-only metadata |
| `MF-P7-02.02` | P7 | blocked | 35 | No | No | Execute ≥ 1 trigger-driven retrain end-to-end (build @vN+1 → train → leaderboard → promote/reject) · champion history visible in registry |
| `MF-P7-06.05` | P7 | blocked | 0 | No | No | Run full tests, drift/schema checks, seeded QA, migration/rollback, CVAT pilot, dataset/training, leaderboard, serving, and ComfyUI evidence |
| `MF-P7-06.06` | P7 | blocked | 0 | Yes | No | Switch active ontology/champions to `body_parts_v2` only after every v2 item/evidence gate passes and record atomic activation/rollback |
| `MF-P7-07.06` | P7 | partially_complete | 75 | No | No | Demonstrate trigger-driven retraining with new fingerprint, compatibility-scoped evidence reuse, recertification/abstention, role promotion/rejection, and rollback |

## Tracker-item exact verification text

### `MF-P1-10.05` — Ontology-v2 generator and machine authority

- **Current:** `partially_complete` at 90%
- **Source:** `12_ITEMS_P1_ONTOLOGY_V2_AND_TRUTH.md` line 15
- **Requirement:** Add all v2 derived formulas and regenerate the active `configs/derived.yaml` only at activation · Verify: inactive `derived_v2.yaml` is drift-clean before activation and active derived output changes atomically with the ontology switch · Blocked by: MF-P7-06.06
- **Existing evidence to preserve/revalidate:** Inactive body_parts_v2 authority remains generator-drift-clean; STATIC inactive-path gates sealed in qa/live_verification/ontology_v2_inactive_path_gates_static_20260719.json. Remaining 10% is real MF-P7-06.06 activation/rollback; no production activation claimed.

### `MF-P5-03.02` — Train 6.1 body-part segmenter

- **Current:** `blocked` at 75%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 28
- **Requirement:** Train SegFormer-B3 directly on RunPod · eval per-part IoU + boundary-F on val every 4k
- **Current blocked reason:** The real SegFormer-B3 run requires bodyparts@v1 with at least 200 certified training packages; CUDA and OpenMMLab are ready, but certified count is 0 and initial human-anchor calibration still needs Kevin.

### `MF-P5-03.03` — Train 6.1 body-part segmenter

- **Current:** `partially_complete` at 65%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 29
- **Requirement:** Challenger: Mask2Former-SwinB config + run (activation checkpointing) — optional Swin-L only on a capacity-qualified RunPod tier (05-08.03)
- **Existing evidence to preserve/revalidate:** qa/live_verification/bodypart_class_contract_20260712.json proves corrected SegFormer and Mask2Former configs plus drift refusal. Mask2Former compiler structure remains focused-test covered; no run/checkpoint is claimed.

### `MF-P5-03.04` — Train 6.1 body-part segmenter

- **Current:** `blocked` at 0%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 30
- **Requirement:** Final eval on frozen test_holdout + hard_case_holdout → leaderboard rows with full per-class + group scores
- **Current blocked reason:** Final frozen-holdout evaluation requires trained challengers and an image-disjoint human-anchor holdout; neither exists.

### `MF-P5-04.02` — Train 6.2 clothing/material parser

- **Current:** `blocked` at 70%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 35
- **Requirement:** Train + eval · GATE: beats SCHP+S08 heuristics on material mIoU AND strap/waistband IoU ≥ 0.55
- **Current blocked reason:** The clothing run and measured material, strap, and waistband gate require a frozen certified-training dataset plus image-disjoint human-anchor holdout; neither exists yet.

### `MF-P5-05.03` — Train 6.2 clothing/material parser

- **Current:** `blocked` at 0%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 41
- **Requirement:** Train + eval on the hand-crop holdout
- **Current blocked reason:** Hand-crop training requires eligible certified-training crops and evaluation requires image-disjoint human-anchor hand holdouts; the CUDA runtime is ready but those data do not exist.

### `MF-P5-05.04` — Train 6.2 clothing/material parser

- **Current:** `blocked` at 70%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 42
- **Requirement:** GATE (**D7**): finger-class mean IoU ≥ 0.70 AND merged-finger false-split rate < 2%
- **Current blocked reason:** NEEDS KEVIN: D7 is a measured trained-model gate requiring image-disjoint human-anchor hand holdout authority and a completed hand training run; synthetic, candidate, and pseudo-label truth are ineligible.

### `MF-P5-05.05` — Train 6.2 clothing/material parser

- **Current:** `blocked` at 98%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 43
- **Requirement:** On win: replace lane steps 2.3–2.4 as crop drafter (SAM2 stays the interactive editor) · model outputs pass QC-018 paste-back ≥ 0.995
- **Current blocked reason:** NEEDS KEVIN: the production lane swap can occur only after a real D7-winning hand checkpoint exists; implementation is ready but no winner exists.
- **Existing evidence to preserve/revalidate:** qa/live_verification/champion_hand_production_integration_20260712.json; 91 focused tests; full suite split 281+376=657; Ruff/format clean

### `MF-P5-06.01` — Leaderboard + promotion mechanics

- **Current:** `blocked` at 90%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 46
- **Requirement:** `training\leaderboard.py` full schema writer · standing baselines auto-scored per dataset version: sam2_only · sam2_pose · sam2_parsing · draft_pipeline_full
- **Current blocked reason:** Leaderboard schema and baseline orchestration exist; measured standing baseline rows require real image-disjoint human-anchor holdouts and completed runs.

### `MF-P5-06.03` — Leaderboard + promotion mechanics

- **Current:** `blocked` at 92%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 48
- **Requirement:** Champion pointers in `models\model_registry.json` (`role: champion_bodypart` etc.) · all loaders/serving read champions ONLY
- **Current blocked reason:** AWAITING_RUNTIME: champion_* registry pointers implemented; live promote blocked until MMSeg train+matrix bundle from CAA/serve_eligible corpus (training-doctor not ready; no challenger_bodypart candidate).
- **Existing evidence to preserve/revalidate:** qa/live_verification/mode_b_champions_caa_mapping_latest.json;qa/live_verification/caa_truth_tier_gold_mapping_latest.json

### `MF-P5-07.02` — Champion into the pipeline

- **Current:** `blocked` at 70%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 54
- **Requirement:** Verify **D6/G7**: champion beats draft_pipeline_full on frozen test_holdout in BOTH mean per-part IoU and boundary-F, with NO tracked hard class regressing > 2 pts
- **Current blocked reason:** NEEDS KEVIN: D6 and G7 require real champion and draft_pipeline_full rows on image-disjoint human-anchor holdouts; those data and trained models do not exist.

### `MF-P5-07.03` — Champion into the pipeline

- **Current:** `blocked` at 0%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 55
- **Requirement:** Remeasure G1 (target trend ≤ 12 min/img) + publish G2/G3 numbers
- **Current blocked reason:** NEEDS KEVIN: G1 remeasurement requires Kevin's real review-task minutes; G2/G3 require corrected gold and trained-model metrics.

### `MF-P5-07.04` — Champion into the pipeline

- **Current:** `blocked` at 0%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 56
- **Requirement:** QC-034 regression sweep on a re-processed sample after the swap — clean
- **Current blocked reason:** NEEDS KEVIN: QC-034 post-swap regression requires an actually promoted champion and reprocessed approved sample.

### `MF-P5-08.01` — Conditional / optional models

- **Current:** `deferred` at 0%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 59
- **Requirement:** (Trigger: ≥80 hair-prominent certified training packages with required human-anchor holdout) ViTMatte fine-tune · GATE: hair boundary-F ≥0.65 AND matte MSE −15% vs stock

### `MF-P5-08.02` — Conditional / optional models

- **Current:** `deferred` at 0%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 60
- **Requirement:** (Trigger: ≥ 120 approved projected labels AND chest-lane fail rate > 10%) breastproj SegFormer-B1 · GATE: projected IoU ≥ 0.75 · outputs provenance-tagged `model:breastproj@<run>`, purple-editable, never truth

### `MF-P5-08.03` — Conditional / optional models

- **Current:** `open` at 0%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 61
- **Requirement:** (Optional) RunPod scale runbook executed once: validate persistent inputs · train directly on the selected pod · persist/hash outputs and evidence

### `MF-P5-09.08` — Ontology-v2 dataset and training

- **Current:** `blocked` at 0%
- **Source:** `16_ITEMS_P5_CERTIFIED_TRAINING.md` line 18
- **Requirement:** Reach 50–100 clear positive instances per appended class before production claims · Verify: immutable inventory report meets every per-class floor · Blocked by: NEEDS KEVIN: sufficient reviewed source evidence
- **Current blocked reason:** NEEDS KEVIN: reviewed v2 sources do not yet provide 50–100 clear positive instances for every appended class.

### `MF-P5-09.09` — Ontology-v2 dataset and training

- **Current:** `blocked` at 0%
- **Source:** `16_ITEMS_P5_CERTIFIED_TRAINING.md` line 19
- **Requirement:** Publish per-class IoU, boundary-F, recall, clothed false positives, and side-swap rates · Verify: every appended class and required context has finite holdout evidence · Blocked by: MF-P5-09.07, MF-P5-09.08
- **Current blocked reason:** Per-class v2 holdout metrics cannot be published until MF-P5-09.08 reaches the real reviewed inventory floors and frozen positive/clothed-negative holdouts exist.

### `MF-P5-09.10` — Ontology-v2 dataset and training

- **Current:** `blocked` at 0%
- **Source:** `16_ITEMS_P5_CERTIFIED_TRAINING.md` line 20
- **Requirement:** Refuse promotion when any appended class lacks evidence or systematically fires on clothing · Verify: negative promotion fixtures and real holdout gate pass · Blocked by: MF-P5-09.09 · HARD BLOCKER
- **Current blocked reason:** The v2 promotion gate cannot pass until MF-P5-09.09 publishes complete real per-class and clothed-negative evidence.

### `MF-P5-10.07` — Truth-tier dataset weights, certified gates, and challenger promotion

- **Current:** `partially_complete` at 75%
- **Source:** `16_ITEMS_P5_CERTIFIED_TRAINING.md` line 29
- **Requirement:** Train/evaluate EoMT/DINOv3 alongside SegFormer and Mask2Former under identical frozen data, ontology, hardware, QA, and measurement code · Verify: complete immutable run records and comparable metrics exist · Blocked by: MF-P0-17.10, MF-P5-10.05
- **Existing evidence to preserve/revalidate:** qa/live_verification/custom_segmenter_training_tournament_contract_20260715.json

### `MF-P5-10.08` — Truth-tier dataset weights, certified gates, and challenger promotion

- **Current:** `partially_complete` at 90%
- **Source:** `16_ITEMS_P5_CERTIFIED_TRAINING.md` line 30
- **Requirement:** Define role-specific primary metric/labor objective and predeclare non-inferiority margins for every hard label/high-risk bucket before results · Verify: benchmark manifest hash predates metric output · Blocked by: frozen human-anchor holdout
- **Existing evidence to preserve/revalidate:** 2026-07-15: custom_segmenter_noninferiority_v1 frozen before results at SHA-256 04adf71f05d0bbf160cb63ed9830f3e0d8a383617aeff4c09ccd6efcb09b05be. Six governing source hashes bind 26 hard labels, 17 high-risk contexts, 12 zero-regression families, 158 expanded buckets, primary macro-IoU >=0.005 and labor reduction >=0.05. Dedicated/focused/full tests pass; qa/live_verification/custom_segmenter_promotion_policy_20260715.json.

### `MF-P5-10.11` — Truth-tier dataset weights, certified gates, and challenger promotion

- **Current:** `partially_complete` at 90%
- **Source:** `16_ITEMS_P5_CERTIFIED_TRAINING.md` line 33
- **Requirement:** Promote winner and demote incumbent to benchmarked transactionally; prove one-command rollback restores role/lifecycle and serving · Verify: registry history and runtime smoke pass both directions · Blocked by: MF-P5-10.10 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** Strict matrix-bound, smoke-first promotion and rollback control planes cover body-part, hand, clothing, and interactive roles. Interactive evidence: qa/live_verification/interactive_provider_transaction_contract_20260715.json SHA-256 70f631c79fab23c5907ebf4fdb7d4711dfee9de13fad77e51a378c234af1963e; full 1653/1653. Remaining 10%: first real image-disjoint human-anchor winner and observed live promotion/rollback; no live role change claimed.

### `MF-P5-10.12` — Truth-tier dataset weights, certified gates, and challenger promotion

- **Current:** `blocked` at 40%
- **Source:** `16_ITEMS_P5_CERTIFIED_TRAINING.md` line 34
- **Requirement:** Evaluate final promotions only against image-disjoint human-anchor holdout and publish tier-separated leaderboard rows, human ceiling, labor metrics, and uncertainty · Verify: leaderboard rejects autonomous/pseudo truth as final authority · Blocked by: NEEDS KEVIN: sufficient final human-anchor holdout and completed training runs
- **Current blocked reason:** NEEDS KEVIN: a sufficient image-disjoint final human-anchor holdout and completed governed training runs do not yet exist.
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: qa/live_verification/training_static_gates_20260719.json file sha256 8e1eaac023ce2b0db199102c7bb7a0af32b875c2ab2b4fe362cd67c642380770; seal_sha256 f49fadafedc8abcd608de954d8f9832c01bd5a2b7da9a7c80d738042a377d340. final_holdout requires human_anchor_gold + holdout split + evaluation_manifest_sha256; autonomous/pseudo/machine rejected. certified_training_package_count=0; no D6/D7/champion/live holdout rows.

### `MF-P5-EXIT` — Phase Exit Gate

- **Current:** `blocked` at 0%
- **Source:** `06_ITEMS_P5_TRAINING.md` line 64
- **Requirement:** Custom models are the drafters · leaderboard is the arbiter · **D6 + D7** checked with evidence rows · doc 14 §6 checkboxes updated
- **Current blocked reason:** NEEDS KEVIN: P5 exit requires approved training data, real trained champions, and measured D6/D7 leaderboard wins.

### `MF-P5-11.03` — P5

- **Current:** `open` at 0%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 29
- **Requirement:** Train and benchmark anatomy-aware challengers, then promote only measured winners through existing champion policy · Verify: per-class/boundary/false-positive/hard-bucket results bind exact corpus and checkpoint seals · Blocked by: MF-P5-11.01, MF-P5-11.02

### `MF-P5-11.04` — P5

- **Current:** `open` at 0%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 30
- **Requirement:** Build the real-supervision foundation with source-family-balanced sampling, per-source/per-label reliability weights, coarse-versus-fine losses, and rare-class coverage · Verify: batch-composition report proves no dataset/correlated family dominates and every consumed label stays within source scope · Blocked by: MF-P5-11.01, MF-P5-11.02 · HARD BLOCKER

### `MF-P5-11.05` — P5

- **Current:** `open` at 0%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 31
- **Requirement:** Implement and benchmark the hierarchical cascade for person/character discovery, ownership/occlusion, silhouette, coarse anatomy, atomic specialists, boundary refinement, and complete-map consistency · Verify: role-isolation, protected-neighbor, ownership, recomposition, and per-label frozen-holdout tests pass · Blocked by: MF-P5-11.04

### `MF-P5-11.06` — P5

- **Current:** `open` at 0%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 32
- **Requirement:** Run leakage-safe self-supervised or masked-image representation pretraining over eligible `F:\Reference_Images` and reference-only MaskedWarehouse partitions without pixel-label invention · Verify: exact manifest excludes benchmark/calibration/validation/test/holdout groups and downstream ablation binds the encoder/checkpoint/data seals · Blocked by: MF-P0-18.05, MF-P9-14.07

### `MF-P5-11.07` — P5

- **Current:** `open` at 0%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 33
- **Requirement:** Run proposal expansion and iterative teacher-student retraining with immutable weighted mixtures: certified truth highest, qualified polygons/RLE medium, eligible machine candidates lower, and boxes/prompts/actions/references/unqualified proposals zero pixel-loss weight · Verify: parent authority never changes and only a leakage-disjoint non-regressing student may promote · Blocked by: MF-P4-12.03 through MF-P4-12.08, MF-P5-11.04 through MF-P5-11.06 · HARD BLOCKER

### `MF-P5-11.10` — P5

- **Current:** `open` at 0%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 36
- **Requirement:** After a qualified still-image champion, implement the temporal video lane with keyframes, bidirectional propagation, correspondence/flow consistency, persistent ownership, cut/occlusion/re-entry recovery, uncertain-frame re-segmentation, and per-frame immutable evidence; keep audio as context-only metadata · Verify: clip fixtures and real bounded canary prove zero identity transfer, no hidden hard-QC failure, and exact frame/clip lineage · Blocked by: MF-P5-11.03, MF-P5-11.05

### `MF-P7-02.02` — Retrain cadence live

- **Current:** `blocked` at 35%
- **Source:** `08_ITEMS_P7_SCALE_OPERATIONS.md` line 19
- **Requirement:** Execute ≥ 1 trigger-driven retrain end-to-end (build @vN+1 → train → leaderboard → promote/reject) · champion history visible in registry
- **Current blocked reason:** Trigger-driven retraining requires a frozen eligible certified dataset, a real trigger, evaluation on human-anchor holdout, and a completed run; CUDA is ready but these inputs do not exist.

### `MF-P7-06.05` — Ontology-v2 operations and activation

- **Current:** `blocked` at 0%
- **Source:** `18_ITEMS_P7_CURRENCY_OPERATIONS.md` line 15
- **Requirement:** Run full tests, drift/schema checks, seeded QA, migration/rollback, CVAT pilot, dataset/training, leaderboard, serving, and ComfyUI evidence · Verify: one activation bundle indexes every required artifact/result and all gates pass · Blocked by: MF-P1-12.09, MF-P4-09.07, MF-P5-09.10, MF-P6-05.07
- **Current blocked reason:** The ontology-v2 activation bundle is blocked by the real CVAT pilot, calibration gate, trained-model holdout gate, and live serving evidence.

### `MF-P7-06.06` — Ontology-v2 operations and activation

- **Current:** `blocked` at 0%
- **Source:** `18_ITEMS_P7_CURRENCY_OPERATIONS.md` line 16
- **Requirement:** Switch active ontology/champions to `body_parts_v2` only after every v2 item/evidence gate passes and record atomic activation/rollback · Verify: active registry/config/workflows agree on v2, live smoke passes, and one-command v1 rollback remains valid · Blocked by: MF-P7-06.05 · HARD BLOCKER
- **Current blocked reason:** Active ontology must remain v1 until the complete MF-P7-06.05 activation bundle passes; no partial activation is permitted.

### `MF-P7-07.06` — Recurring currency, certificate operations, and autonomous headline evidence

- **Current:** `partially_complete` at 75%
- **Source:** `18_ITEMS_P7_CURRENCY_OPERATIONS.md` line 24
- **Requirement:** Demonstrate trigger-driven retraining with new fingerprint, compatibility-scoped evidence reuse, recertification/abstention, role promotion/rejection, and rollback · Verify: immutable end-to-end operations report passes · Blocked by: certified training corpus and audit trigger
- **Existing evidence to preserve/revalidate:** qa/live_verification/retraining_operations_contract_20260715.json; 24 dedicated and 98 focused tests pass; full repository 1376/1376 exit 0

