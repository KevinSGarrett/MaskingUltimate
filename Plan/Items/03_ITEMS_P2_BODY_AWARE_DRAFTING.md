# ITEMS — Phase P2: Body-Aware Drafting (Weeks 2–4)

Goal: automatic drafts for all 56 parts from one command (D1) + first G2 measurement. Parent IDs from doc 14 §3.

## MF-P2-01 — S01 person detection + S02 silhouette (spec: 07 S01–S02)
- [ ] MF-P2-01.01 S01: YOLO11m person class conf ≥ 0.5 · primary = largest area × centeredness · other persons recorded for PART 50 · 0 persons → `rejected(no_person)` · >3 → `quarantined(multi_person_review)` · context crop = bbox × 1.25 clamped → `work\s01\`
- [ ] MF-P2-01.02 S02: BiRefNet fp16, long side 2048 (tiled beyond) · threshold 0.5 · keep largest component + components ≥ 1% person area touching it · paste to full canvas → `person_full_visible` candidate + confidence map · QC hook: silhouette/bbox area ratio ∈ [0.35, 0.95]
- [ ] MF-P2-01.03 Fixture set: 10 images with hand-truth bboxes + silhouettes · detection and silhouette IoU ≥ 0.95

## MF-P2-02 — S03 human parsing (spec: 07 S03)
- [ ] MF-P2-02.01 Sapiens-0.6B-seg bf16, input long-side 1024 (tile 1536 / 128 overlap) · argmax + per-class prob maps saved 8-bit
- [ ] MF-P2-02.02 SCHP-ATR always-run companion pass (clothing classes + cross-check)
- [ ] MF-P2-02.03 Author `configs\pipeline.yaml`: stage toggles · device · tile sizes · thresholds · `seed: 1337` · `io.workdir` · `gpu_cooldown_sec: 3` · `parsing_map` (Sapiens-28 + SCHP-ATR → ontology priors) · `pose_tags_rules` · fusion weights (sam2 .40 / sapiens .25 / geometry .15 / schp .10 / densepose .10) · `fusion.zorder_rules`
- [ ] MF-P2-02.04 OOM path: half-res retry → SCHP-only + `parsing_degraded: true`
- [ ] MF-P2-02.05 Remap unit tests green · Sapiens↔SCHP disagreement % logged per image

## MF-P2-03 — S04 pose + view/pose_tags (spec: 07 S04)
- [ ] MF-P2-03.01 DWPose via onnxruntime-gpu (yolox_l det + dw-ll_ucoco_384) → `pose133.json` with confidences (133 kp incl. 21×2 hands, 6 feet)
- [ ] MF-P2-03.02 View classifier: shoulder/hip geometry + nose visibility (+ DensePose back-ratio once S08.5 lands in P3) → {front, back, left/right_profile, left/right_3_4}
- [ ] MF-P2-03.03 pose_tags deterministic rules (arm elevation angles, hip-knee-ankle angles, overlap tests) per `pose_tags_rules`
- [ ] MF-P2-03.04 Degraded path: < 60% body kp above conf 0.3 → `pose_degraded: true` · parsing-only priors · auto careful-review tag
- [ ] MF-P2-03.05 20-image hand-tagged eval set · view + pose_tags ≥ 90% correct

## MF-P2-04 — S05 geometry engine (spec: 07 S05, 02 §6)
- [ ] MF-P2-04.01 Limb capsules per segment (upper_arm/forearm/thigh/calf): radius = median of 5 cross-section half-widths from parsing · clip ∩ silhouette ∩ parsing superset
- [ ] MF-P2-04.02 Joint bands perpendicular at elbow/knee/wrist/ankle kps · height = 0.6× local width (0.5× wrist) · carve out of adjoining segment priors
- [ ] MF-P2-04.03 Torso partition: clavicle line · under-breast fold (chest kp + torso-mask horizontal-profile minima) · iliac line · midline → chest/breast/abdomen/pelvis/hips polygons · belly_button carve-out · breast ellipse seeds from chest landmarks × torso width (front/¾ only)
- [ ] MF-P2-04.04 Hand/feet crop requests (bbox from wrist/ankle + kps × 1.6) → lane queue entries
- [ ] MF-P2-04.05 Hair prior = parsing hair class ∪ GDINO "hair" box
- [ ] MF-P2-04.06 Back-view classes (back/back-¾ only): back-torso waist split · scapula/spine bands seeded from DensePose UV (wired fully in P3-05)
- [ ] MF-P2-04.07 Author `configs\prompting.yaml` (per-part SAM2 point/box recipes + GDINO prompt list + box 0.30 / text 0.25) · emit `prompts.json`: positives = peak + 3–7 skeleton samples · negatives = neighbor peaks + background ring · box = prior bbox × 1.1
- [ ] MF-P2-04.08 Missing-keypoint fallback: parsing-only prior + `prior_quality: low`
- [ ] MF-P2-04.09 Unit tests: band height formula (0.6× / wrist 0.5×) · prompt plans render on a debug overlay

## MF-P2-05 — S06 GDINO assist + S07 SAM2 refinement (spec: 07 S06–S07)
- [ ] MF-P2-05.01 S06: GroundingDINO prompts {hair, bra, underwear, shoe, sock, glove, necklace, handheld object, chair/bed/surface} → `gdino_boxes.json` · code-level guarantee: GDINO output can never reach a map except through SAM2 + fusion (never a final mask)
- [ ] MF-P2-05.02 S07: one SAM2.1 hiera-large fp16 embedding per image · auto-fallback base-plus on OOM
- [ ] MF-P2-05.03 Per-part prompting (box + positives + negatives from prompts.json) · `multimask_output=True` · select argmax of 0.6·IoU(prior) + 0.4·predicted_iou
- [ ] MF-P2-05.04 One corrective iteration when selection vs prior disagreement > 8% area: +positives in prior-only zones near skeleton · −negatives in mask-only zones outside prior bbox
- [ ] MF-P2-05.05 Post-process: threshold logits at 0 · drop components < max(64 px², 0.02·part area) · fill holes < 0.5% part area · NO smoothing/anti-aliasing
- [ ] MF-P2-05.06 Joint bands cut geometrically from limb results (bands own their pixels)
- [ ] MF-P2-05.07 predicted_iou < 0.5 → `sam2_low_conf` · keep prior as draft · review flag
- [ ] MF-P2-05.08 Fixture run: 46 core (non-lane) parts drafted on the 10-fixture set

## MF-P2-06 — S09 consensus + z-order fusion v1 (spec: 07 S09, 05 §4)
- [ ] MF-P2-06.01 Evidence stack per part (SAM2, priors, parsing, later DensePose) → per-pixel candidate scores with configured weights · agreement bands: ≥0.85 quick-pass mark · 0.60–0.85 normal · <0.60 `model_disagreement_high`
- [ ] MF-P2-06.02 Z-order arbitration for contested pixels (both > 0.4): (a) hands/fingers in front of torso/thighs on wrist depth cue · (b) hair in front of face/neck/shoulders · (c) crossed limbs — uninterrupted contour wins front · (d) occluding_object beats body on closed-contour cover · ties → higher score · contested pixels → `overlap_occlusion_boundary` band + manifest `occlusion{}` (occluder owns pixels; occluded part → partially_visible)
- [ ] MF-P2-06.03 Structural exclusivity: argmax into 16-bit PART map · background = ¬silhouette
- [ ] MF-P2-06.04 MATERIAL map v1 from SCHP remap within silhouette (stopgap; upgraded by S08 in P3-02.09)
- [ ] MF-P2-06.05 Emit region bands (waist, contact, occlusion-boundary…) per doc 02 §4 formulas
- [ ] MF-P2-06.06 Write `work\s09\disagreement.png` = 1 − normalized top-2 margin (0–255)
- [ ] MF-P2-06.07 Determinism: seed 1337 + torch deterministic algorithms → two consecutive runs produce BYTE-IDENTICAL maps (G8 spot check)
- [ ] MF-P2-06.08 QC-011 exclusivity clean on all fixtures

## MF-P2-07 — Overlays, panels, semantic QCs (spec: 09 §2/§5/§6, 03 §8)
- [ ] MF-P2-07.01 Overlay renderer (per-label + all-parts) per viz.yaml · saved to `overlays\`
- [ ] MF-P2-07.02 5-tile boundary zoom panels for hard classes @2× part bbox, 512 tiles: [source crop | mask | overlay | contour | protected-overlap heat] → `qa_panels\`
- [ ] MF-P2-07.03 Implement QC-011 verify · QC-012 inside-silhouette ≤0.2% · QC-013 protected-overlap ≤0.5% + skin∩clothing=0 (BLOCK) · QC-014 L/R vote (skeleton chain + MediaPipe handedness now; DensePose third signal wired P3-05; disagreement = BLOCK) · QC-015 area sanity vs ontology ranges · QC-016 visibility-vs-frame (BLOCK)
- [ ] MF-P2-07.04 Implement QC-017 components limit · QC-018 crop round-trip ≥0.995 (exercised from P3) · QC-019 breast_skin identity (BLOCK) · QC-020 projected containment (BLOCK) · QC-021 hole ratio · QC-022 edge alignment · QC-023 visibility-state consistency · QC-024 front/back surface (activated P3-05)
- [ ] MF-P2-07.05 Author `configs\qa.yaml` (every threshold, severities, class-tier weights fingers/hair/chest ×2, qa_score formula) · metrics module: iou_vs_consensus, boundary_f_2px, hausdorff_95 (hard classes), hole_ratio, components, disagreement_score, protected/exclusive overlaps
- [ ] MF-P2-07.06 Seeded L/R-swap fixture → QC-014 BLOCKs it

## MF-P2-08 — 25-image draft→gold run + baseline (spec: 12 §10)
- [ ] MF-P2-08.01 Ingest + draft 25 images end-to-end, model-major batching (one heavy model resident at a time; runtime ≈2.5–3.5 min/img verified vs doc 07 budget table)
- [ ] MF-P2-08.02 Review/correct/approve in CVAT → ~30 total gold
- [ ] MF-P2-08.03 Create `runs\leaderboard.jsonl` · publish `draft_pipeline_full` row: draft-vs-gold per-part IoU + boundary-F on these packages
- [ ] MF-P2-08.04 Record G2 initial numbers in OPS_LOG · verify **D1**: one CLI command takes a new incoming image to drafts for all 56 atomics

## P2 Exit Gate
- [ ] MF-P2-EXIT Drafts measurably cut annotation minutes vs P1 baseline (G1 trend) · doc 14 §3 checkboxes updated
