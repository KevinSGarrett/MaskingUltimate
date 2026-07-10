# Document 12: Dataset, Training & Active Learning

This doc turns approved gold packages into versioned datasets, fine-tunes the five specialist
models, and closes the loop: every correction becomes training data, every failure becomes the
next acquisition target. Trainer of record: **MMSegmentation** (doc 06 §6); detectron2 only for
DensePose. All training configs live in `configs\training\*.yaml`; all runs log to `runs\`.

---

## 1. Splits (Hash-Stable, Leak-Proof)

- Assignment is deterministic from the image, never random per build:
  `bucket = int(sha256(image_id)[:8], 16) % 100` → **train 0–69 (70%), val 70–84 (15%),
  test_holdout 85–99 (15%)**. Same image lands in the same split forever, across every dataset
  version — no leakage when the dataset grows.
- **hard_case_holdout** is a fourth, manually curated set (`datasets\hard_case_holdout.txt` of
  image_ids): images promoted from failure_queue as "hardest of class" (target 30–50). Overrides
  the hash split; NEVER trains, NEVER tunes hyperparameters; scored on the leaderboard only.
- Near-duplicate guard: at S00 a perceptual hash (pHash, 64-bit) is stored; dataset builder
  refuses to place images with Hamming distance ≤ 6 in different splits (the later one follows
  the earlier one's split) — prevents twin-image leakage from bursts/variants.
- Synthetic images (§9) are train-only by rule; builder rejects synthetic in val/test.
- `test_holdout` and `hard_case_holdout` metrics are reported only by `maskfactory leaderboard`;
  training code has no read path to them (enforced by builder writing them to a separate,
  read-only export the trainers never receive).
- **AMENDED (doc 17 §8) — multi-person split integrity, CRITICAL:** the bucket formula above is
  keyed on `image_id`, **never** on a per-instance id — this was already correct by construction
  once multi-instance packages exist (`instances\p0\`, `instances\p1\`, ... all share one
  `image_id`), so every promoted instance from the same source image lands in the same split
  automatically. **Do not "improve" this to bucket on instance id** — that would leak shared
  background/lighting/context across the train/test boundary. A dedicated CI test asserts no
  `image_id` has instances split across partitions, the same enforcement style as the
  flip/swap_partner test in §4 below.

## 2. Coverage Matrix Usage (What To Shoot/Collect Next)

- `qa\coverage_matrix.json` (doc 04 §5) counts approved gold per view × pose × attribute cell.
  Targets: **≥ 8 approved images per view×pose cell, ≥ 40 per attribute** (leg_overlap,
  hand_body_contact, hair_occlusion, clothing_boundary, feet_visible, hands_visible …).
- `maskfactory coverage report` prints a heat table + the ranked deficit list
  (`deficit = target − count`, normalized). This list is a direct input to the active-learning
  priority formula (§7) and to the weekly acquisition plan: the top-10 deficit cells define what
  images to generate/collect next.
- D5 gate reads this file: ≥ 80% of cells at target before the system is "done" at 300 gold.

## 3. Dataset Build & DVC Versioning

`maskfactory dataset build --name bodyparts --ontology body_parts_v1` produces
`datasets\bodyparts@vN\` (N auto-increments):

```
datasets\bodyparts@vN\
  dataset_card.md            # counts per split/class/cell, ontology version, build cmd, git sha
  train.txt / val.txt        # image_id lists (test/hard exports live in holdout\, see §1)
  part_seg\                  # label_map_part.png copies + images (MMSeg custom-dataset layout)
  material_seg\              # label_map_material.png variant
  hand_crops\                # crop contract crops (doc 03 §5) + hand-class label maps
  matting\                   # hair trimap/matte pairs
  projected\                 # projected-region label maps (optional model, §6.5)
  coco\annotations.json      # COCO-RLE per binary mask (interoperability evidence)
  holdout\                   # test + hard_case exports (read-only flag set)
```

- Only `human_approved_gold` packages are eligible; builder re-runs `verify-package` on each and
  hard-fails the build on any hash/format mismatch (a dataset can never contain unverified gold).
- Versioning: `dvc add datasets\bodyparts@vN && git tag dataset/bodyparts-vN`; remote is S3
  `maskfactory-dvc-dev` (dev acct 548846591581, doc 06 §6). `dvc push` after every build.
  Rebuilding vN from the same package set is byte-identical (G8: sorted inputs, seed 1337,
  zip timestamps zeroed).
- Every training run records `dataset@vN` + its DVC md5 in `runs\<run_id>\run.json` — a metric is
  meaningless without the dataset version it was measured on.

## 4. Augmentation Policy (Ontology-Aware — This Is Where Datasets Get Corrupted)

| Aug | Allowed | Rule |
|-----|---------|------|
| Horizontal flip | YES (p=0.5) | **MUST remap every left/right ID via `swap_partner` from ontology.yaml** (left_hand↔right_hand, all 26 sided parts, sided materials/straps). A flip without remap is a silent L/R poisoning of the whole dataset — the flip transform unit test (fixture image, asserted swapped map) is a CI blocker (MF-P5-02). |
| RandomResizedCrop → 512×512 | YES | Scale 0.5–2.0; class-aware sampling: 40% of crops are forced to contain a rare-class pixel (fingers, toes, belly_button, straps) — otherwise 512-crops almost never see them. |
| Color jitter / photometric | YES | brightness/contrast/saturation ±0.25, hue ±0.05; never applied to label maps. |
| Small rotation ±15° | YES | Nearest-neighbor for labels; border pixels → 255 ignore_index. |
| Vertical flip | NO | Breaks up/down anatomy priors. |
| Elastic/perspective warps | NO | Destroys boundary truth and joint-band geometry the QA layer depends on. |
| MixUp/CutMix | NO | Nonsensical for exclusive panoptic part maps. |

Ignore index = 255 everywhere (uncertainty zones from `ambiguous_do_not_use` parts are burned to
255 in training maps so the model is never penalized on honest unknowns).

## 5. Training Infrastructure (8 GB Local + Optional AWS Burst)

- Local: WSL2 conda env `maskfactory`, PyTorch ≥ 2.7 cu128 (sm_120), MMSegmentation. AMP (bf16)
  mandatory; crop 512; per-GPU batch 2 + gradient accumulation 8 (effective 16); checkpointing
  (activation ckpt) on for Swin backbones. The training slot **claims the whole GPU** — the
  orchestrator lock (`runs\gpu.lock`, doc 05 §5) refuses concurrent pipeline/serving runs.
- Thermals: laptop cooldown policy (doc 06 pitfall 6) — trainer sleeps 60 s every 30 min if GPU
  temp > 87 °C (nvidia-smi poll); expect ~1.5–3 h per 10k iters locally.
- AWS burst (optional, decision pre-made): g6e.xlarge (L40S 48 GB) **spot** in dev acct
  548846591581, AMI = Deep Learning PyTorch; sync code via git, data via `dvc pull`, artifacts
  back via `dvc push` + `runs\` rsync. Use only for Mask2Former-Swin-L experiments or when local
  wall-clock blocks the weekly cadence. Terminate rule: instance dies with the run (no idle GPUs).
- Determinism: seed 1337, `cudnn.deterministic=true` for release runs (speed runs may relax; the
  leaderboard entry records which).
- Every run: `runs\<run_id>\{run.json, config.yaml, git_sha, dataset_ref, ckpts\, tb\, eval\}`;
  `run_id = r_<utc>_<model>_<datasetvN>`.

## 6. The Five Fine-Tuned Models (Specs & Gates)

### 6.1 Body-part segmenter (primary)
- Task: 57-class semantic seg (56 PART IDs + background) on `label_map_part.png`.
- Arch A (default): **SegFormer-B3**, ImageNet-pretrained, 512 crops — fits 8 GB comfortably.
- Arch B (challenger): **Mask2Former-SwinB** (local, ckpt-activated) or Swin-L (AWS burst only).
- Schedule: AdamW lr 6e-5 poly 1.0, 40k iters (≈300 gold) / 80k (≈500), warmup 1.5k; loss CE +
  Dice (Mask2Former: its native matcher losses); class weights ∝ 1/√pixel_freq, capped ×8.
- Eval: per-part IoU + boundary-F@2px on val each 4k iters; final on test_holdout + hard_case.
- Promotion gate (→ replaces S03/S09 drafting priors as `custom_bodypart` consensus source at
  weight 0.45): beats the full draft pipeline on frozen test_holdout in BOTH mean per-part IoU
  and mean boundary-F, with no tracked hard class (fingers, toes, chest boundary, hairline)
  regressing > 2 pts. This gate == **D6/G7**.

### 6.2 Clothing / material parser
- Task: 16-class seg on `label_map_material.png`; arch SegFormer-B2, 512 crops, 30k iters.
- Extra positive sampling on thin classes (strap, waistband, lace_or_sheer ×4 crop weight).
- Gate: beats SCHP-ATR remap + S08 heuristics on material mIoU AND strap/waistband IoU ≥ 0.55;
  on win, becomes S08 primary (SCHP demoted to fallback).

### 6.3 Hand-crop specialist (the D7 model)
- Task: 14-class seg on crop-contract hand crops (doc 03 §5): bg, hand_base_L/R, 10 fingers,
  finger_occlusion_boundary band. Trained ONLY on 1024-px hand crops (multi-scale 0.75–1.25).
- Arch: SegFormer-B2 @ 768 crop window, 25k iters; heavy rare-class sampling (every crop
  contains fingers by construction); flip remaps finger sides via swap_partner.
- Gate: **finger-class mean IoU ≥ 0.70 on the hand-crop test holdout (= D7)** and merged-finger
  false-split rate < 2% (audited on the seeded ambiguous set). On win, replaces lane steps
  2.3–2.4 (doc 08 §2.8) as the crop drafter; SAM2 remains the interactive editor.
- Round-trip: predictions are pasted back through `crop_to_full_transform.json`; the ≥ 0.995
  paste IoU check (QC of doc 03 §5) applies to model outputs too.

### 6.4 Hair / face matting & parsing
- Hair: fine-tune **ViTMatte** on `matting\` (trimap+matte pairs) once ≥ 80 hair-prominent golds
  exist; gate = hair boundary-F@2px ≥ 0.65 on val AND matte MSE improves ≥ 15% vs stock ViTMatte.
  Binary gold stays authoritative; the matte is auxiliary (doc 03 §7).
- Face: stock BiSeNet face-parsing is kept unless failure mining shows face_protected leaks;
  then a 6-class face guard head is added to 6.1 (decision deferred by data, not by design).

### 6.5 Breast projected-region model (optional, phase-gated)
- Task: 5-class seg on the `projected\` layer (bg, L/R breast_projected, L/R chest_clothing
  region); trains only on second-reviewed projected labels (doc 11 §6 mandatory for this class).
- Arch SegFormer-B1, 20k iters. Output is **never truth** — it lands in `projected\` with
  provenance `model:breastproj@<run>` and is always human-editable (purple-label CVAT jobs).
- Build trigger: ≥ 120 approved projected labels AND chest-lane failure rate still > 10%;
  otherwise the geometry-engine estimate (doc 08 §3) remains the drafter. Gate: projected-region
  IoU vs human ≥ 0.75 on its holdout.

## 7. Active Learning Loop (S15 — Runs Weekly)

1. Ingest `qa\failure_queue.jsonl` + second-review fails + VLM-fail-but-human-pass disagreements.
2. Score every open item:
   `priority = 0.4*class_error_rate + 0.3*coverage_deficit + 0.2*downstream_use_weight + 0.1*recency`
   (class_error_rate from leaderboard per-class trend; coverage_deficit from §2; use_weight from
   `configs\training\use_weights.yaml` — hands/chest 1.0, feet 0.8, bands 0.5; recency = exp
   decay 14 d).
3. Emit `qa\reports\acquisition_plan_<date>.md`: top-20 items → concrete actions (collect N
   images of cell X / re-annotate ids / promote id to hard_case_holdout / add label per §8).
4. Retrain trigger (any): +50 new approved gold since champion's dataset · any tracked class
   error ↑ > 5 pts for 2 weeks · ontology version change. Trigger opens a P5 task automatically.
5. Curriculum note: new gold from failure mining enters train immediately (next dataset build);
   holdouts stay frozen — improvement is measured against an unmoving bar.

## 8. Failure-Driven Label Additions (Controlled Ontology Growth)

Optional finer labels (left/right inner_thigh, outer_thigh, shin_front, side_torso, underarm
already banded; per-toe splits) are added ONLY via the ontology change procedure (doc 02 §9) and
ONLY when justified: **≥ 10 distinct failure_queue items in 30 days traced to that missing
boundary**, plus a written boundary definition and a swap_partner entry. Adding a label spawns:
map ID assignment from the reserved range, CVAT label push, back-annotation plan for existing
gold (or explicit `not_annotated_in_v1` state), and a dataset major-version bump. Never add
labels speculatively — every label is a permanent annotation tax.

## 9. Synthetic Data Bootstrapping

- Sources: controlled generated images where geometry is scripted, or 3D renders (SMPL-X poses)
  where labels are exact by construction. Marked `source_origin: synthetic` at intake; stored
  under `data\images\synthetic\`.
- Use: rare poses/cells (coverage deficits), finger/toe close-ups, occlusion drills. Mixing cap:
  **≤ 30% of any training set**; ratio recorded on the dataset card. Train-only (§1). A model
  whose win depends on synthetic mix > 30% is not promotable.
- QA: synthetic packages run the same battery (they are cheap gold, not exempt gold).

## 10. Model Leaderboard (`training\leaderboard.py`)

- Storage: `runs\leaderboard.jsonl`; one row per (candidate × dataset holdout):
  `{run_id, model_family, ckpt_sha, dataset_ref, split, mean_iou, mean_boundary_f,
  per_class: {label: {iou, bf}}, group_scores: {fingers, toes, chest_boundary, hairline,
  bands}, latency_ms_1024, vram_gb, seeds, notes}`.
- Standing baselines (always present, re-scored per dataset version): `sam2_only`,
  `sam2_pose`, `sam2_parsing`, `draft_pipeline_full` (the S00–S09 stack), plus every fine-tune.
- **Scoring is per body part, never total-IoU-only** — fingers and chest boundaries have their
  own group rows and their own regression rules (§6.1 gate).
- `maskfactory leaderboard --compare <run_a> <run_b>` prints the per-class delta table; the
  champion pointer lives in `models\model_registry.json` (`role: champion_bodypart`, etc.) and
  is the only thing S03/S07/serving read — promotion = one registry edit, instantly reversible.
- Human ceiling row: IAA IoU from doc 11 §6 is plotted as the reference line; a model within
  2 pts of human agreement on a class is considered saturated (stop chasing, mine elsewhere).
- **AMENDED (doc 17 §8):** per-part IoU/boundary-F is also reported broken out by instance
  context — `solo | duo | small_group` — alongside the pooled score, since a model may perform
  differently on crops containing nearby `other_person_protected` regions and contact bands than
  on clean single-person crops. Both views land in `runs\leaderboard.jsonl`; the pooled score
  remains the primary number for D6/G7 comparability against pre-multi-person baselines.
