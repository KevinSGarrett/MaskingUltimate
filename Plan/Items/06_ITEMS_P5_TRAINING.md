# ITEMS — Phase P5: Custom Model Training (entry gate: ≥200 certified training packages)

**Completion-profile scope:** the package-volume entry gate, custom training, and human-anchor holdout
comparisons in this file belong to optional `independent_real_accuracy` and post-core
`scale_daz_maturity`. They are not entry gates for the partial-library, capability-snapshot-driven
`core_autonomous_runtime` route defined by doc 24.

Goal: D6 (champion beats draft pipeline on frozen holdout) + D7 (finger mIoU ≥ 0.70). Parent IDs from doc 14 §6.

## MF-P5-01 — Dataset build v1 + DVC (spec: 12 §1/§3)
- [ ] MF-P5-01.01 `datasets\splits.py`: bucket = int(sha256(image_id)[:8],16) % 100 → train 0–69 / val 70–84 / test 85–99 · pHash near-dup guard (Hamming ≤ 6 → follow earlier image's split) · synthetic → train-only enforced · `datasets\hard_case_holdout.txt` override list honored, never trains/tunes
- [ ] MF-P5-01.02 `datasets\builder.py`: full layout — dataset_card.md, train/val id lists, part_seg\, material_seg\, hand_crops\, matting\, projected\, coco\annotations.json (RLE), holdout\ (read-only export)
- [ ] MF-P5-01.03 Pre-flight: `verify-package` on every eligible package · any hash/format mismatch hard-fails the build
- [ ] MF-P5-01.04 Byte-identical rebuild test (sorted inputs, seed 1337, zeroed zip timestamps) — G8 for datasets
- [ ] MF-P5-01.05 Holdout isolation: trainers receive no read path to holdout\ · enforcement test proves it
- [ ] MF-P5-01.06 Build `datasets\bodyparts@v1` · `dvc add` · `git tag dataset/bodyparts-v1` · `dvc push` to the governed local/persistent remote
- [ ] MF-P5-01.07 Dataset card audit: counts per split/class/cell · ontology version · build cmd + git sha · synthetic ratio recorded

## MF-P5-02 — Augmentation pipeline (spec: 12 §4) — CI BLOCKER
- [ ] MF-P5-02.01 MMSeg custom dataset class + transform stack · ignore_index 255 (ambiguous_do_not_use zones burned to 255)
- [ ] MF-P5-02.02 Horizontal flip p=0.5 WITH swap_partner ID remap for all sided PART + MATERIAL labels · fixture-asserted unit test wired as a CI BLOCKER for all training merges
- [ ] MF-P5-02.03 RandomResizedCrop → 512², scale 0.5–2.0 · 40% of crops forced to contain a rare-class pixel (fingers/toes/belly_button/straps) · sampling rate measured and logged
- [ ] MF-P5-02.04 Photometric jitter (b/c/s ±0.25, hue ±0.05; labels untouched) · rotation ±15° nearest with border → 255
- [ ] MF-P5-02.05 Banned-aug guard: configs reject vflip / elastic / perspective / MixUp / CutMix

## MF-P5-03 — Train 6.1 body-part segmenter (spec: 12 §5/§6.1)
- [ ] MF-P5-03.01 Author `configs\training\bodypart_segformer_b3.yaml`: 56-class v1 (IDs 0..55 including background; v2 is 66-class per doc 18) · 512 crops · AdamW 6e-5 poly 1.0 · 40k iters (80k @500 gold) · warmup 1.5k · CE+Dice · class weights ∝ 1/√pixel_freq cap ×8 · bf16 AMP · batch 2 × grad-accum 8
- [ ] MF-P5-03.02 Train SegFormer-B3 under `runs\gpu.lock` · eval per-part IoU + boundary-F on val every 4k · thermal cooldown (sleep 60 s @ >87 °C) verified during a long run
- [ ] MF-P5-03.03 Challenger: Mask2Former-SwinB config + run (activation checkpointing) — optional Swin-L only on a capacity-qualified RunPod tier (05-08.03)
- [ ] MF-P5-03.04 Final eval on frozen test_holdout + hard_case_holdout → leaderboard rows with full per-class + group scores
- [ ] MF-P5-03.05 Every run logged to `runs\<run_id>\` {run.json, config, git_sha, dataset_ref + DVC md5, ckpts, tb, eval}

## MF-P5-04 — Train 6.2 clothing/material parser (spec: 12 §6.2)
- [ ] MF-P5-04.01 Author `configs\training\clothing_segformer_b2.yaml`: 16-class · thin classes (strap/waistband/lace) ×4 crop weight · 30k iters
- [ ] MF-P5-04.02 Train + eval · GATE: beats SCHP+S08 heuristics on material mIoU AND strap/waistband IoU ≥ 0.55
- [ ] MF-P5-04.03 On win: promote to S08 primary (SCHP demoted to fallback) via registry role edit

## MF-P5-05 — Train 6.3 hand-crop specialist (spec: 12 §6.3) — the D7 model
- [ ] MF-P5-05.01 Author `configs\training\hand_segformer_b2.yaml`: 14-class (bg, hand_base L/R, 10 fingers, finger_occlusion_boundary) · 768 window on 1024 crops · multi-scale 0.75–1.25 · 25k iters · finger swap_partner remap in flips
- [ ] MF-P5-05.02 Build the seeded ambiguous-hand audit set (merged-finger cases with known truth) for the false-split metric
- [ ] MF-P5-05.03 Train + eval on the hand-crop holdout
- [ ] MF-P5-05.04 GATE (**D7**): finger-class mean IoU ≥ 0.70 AND merged-finger false-split rate < 2%
- [ ] MF-P5-05.05 On win: replace lane steps 2.3–2.4 as crop drafter (SAM2 stays the interactive editor) · model outputs pass QC-018 paste-back ≥ 0.995

## MF-P5-06 — Leaderboard + promotion mechanics (spec: 12 §10)
- [ ] MF-P5-06.01 `training\leaderboard.py` full schema writer · standing baselines auto-scored per dataset version: sam2_only · sam2_pose · sam2_parsing · draft_pipeline_full
- [ ] MF-P5-06.02 `maskfactory leaderboard --compare <a> <b>` per-class delta table (group rows: fingers, toes, chest_boundary, hairline, bands)
- [ ] MF-P5-06.03 Champion pointers in `models\model_registry.json` (`role: champion_bodypart` etc.) · all loaders/serving read champions ONLY
- [ ] MF-P5-06.04 Demonstrate promotion AND instant rollback — one registry edit each way
- [ ] MF-P5-06.05 Human-ceiling row from IAA plotted · saturation rule noted (within 2 pts of human → stop chasing, mine elsewhere)

## MF-P5-07 — Champion into the pipeline (spec: 12 §6.1/§7)
- [ ] MF-P5-07.01 S03/S09 consume `custom_bodypart` as a consensus source at weight 0.45 (fusion-weights update path in pipeline.yaml)
- [ ] MF-P5-07.02 Verify **D6/G7**: champion beats draft_pipeline_full on frozen test_holdout in BOTH mean per-part IoU and boundary-F, with NO tracked hard class regressing > 2 pts
- [ ] MF-P5-07.03 Remeasure G1 (target trend ≤ 12 min/img) + publish G2/G3 numbers
- [ ] MF-P5-07.04 QC-034 regression sweep on a re-processed sample after the swap — clean

## MF-P5-08 — Conditional / optional models (spec: 12 §6.4–6.5/§5)
- [ ] MF-P5-08.01 (Trigger: ≥80 hair-prominent certified training packages with required human-anchor holdout) ViTMatte fine-tune · GATE: hair boundary-F ≥0.65 AND matte MSE −15% vs stock
- [ ] MF-P5-08.02 (Trigger: ≥ 120 approved projected labels AND chest-lane fail rate > 10%) breastproj SegFormer-B1 · GATE: projected IoU ≥ 0.75 · outputs provenance-tagged `model:breastproj@<run>`, purple-editable, never truth
- [ ] MF-P5-08.03 (Optional) governed RunPod scale runbook executed once: validate persistent inputs · acquire/heartbeat SharedRunPodCoordinator v2 lease · train · persist/hash outputs and evidence · contain owned process · release lease

## P5 Exit Gate
- [ ] MF-P5-EXIT Custom models are the drafters · leaderboard is the arbiter · **D6 + D7** checked with evidence rows · doc 14 §6 checkboxes updated
