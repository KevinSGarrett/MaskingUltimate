# Document 07: Pipeline Stage Specifications (S00–S15)

Contract format per stage: **In** (files/state) → **Out** (files/state) → **Algorithm** →
**Failure handling**. All thresholds referenced here have concrete defaults in
`configs\pipeline.yaml`; values shown are those defaults. All coordinates full-res unless noted.

---

## S00 — Intake & Registration
**In:** any image dropped in `data\incoming\` (png/jpg/webp).
**Out:** `data\images\<image_id>\source.png(.jpg)`, manifest skeleton, SQLite row `status=ingested`.
**Algorithm:**
1. SHA-256 → `image_id = img_<hash[:12]>`; duplicate hash → skip + log.
2. Decode; reject if min side < 512 px (`intake.min_side`) or corrupt.
3. Strip EXIF/metadata (privacy + reproducibility); PNG kept lossless, JPG copied byte-exact with
   metadata stripped (masks are PNG regardless).
4. Record `source_origin` from drop subfolder (`incoming\generated\`, `incoming\owned\`,
   `incoming\licensed\`, `incoming\consented\`) — files in `incoming\` root are quarantined until
   sorted (governance, doc 01 §7).
5. Age-safety gate: images flagged by the safety screen (person detector + doc 10 §7 VLM screen
   for apparent-minor content) → `quarantined`, excluded, logged. Hard rule, not configurable.
**Fail:** decode error → `rejected`.

## S01 — Person Detection & Context Crops
**In:** source. **Out:** `work\s01\person_bbox.json` (all persons, scores, ranks), one promoted
context crop per instance `work\s01\p<N>\person_ctx.png` (bbox × 1.25 pad, clamped).
**Algorithm — AMENDED, doc 17 §4:** YOLO11m person class, conf ≥ 0.5; score every detection by
area × centeredness (unchanged metric). Apply prominence floor `instance_min_area_pct` (4% of
frame); rank the rest; **promote** the top `max_instances_per_image` (default 4) as
`person_index` 0..N-1, descending score, left-to-right tie-break. Non-promoted persons above the
floor become `other_person_protected` background for every promoted instance's own run (doc 02
PART id 50, scoped per-instance). Zero persons passing the floor → `rejected(no_person)`. Total
raw detections > `crowd_scene_threshold` (default 8) → whole image `quarantined
(crowd_scene_out_of_scope)`, no partial promotion. Full policy, including the deterministic
tie-break and the per-instance execution loop this feeds (S02–S09 run once per promoted
instance, plus new S09.5 reconciliation before S10): doc 17 §4–§5.

## S02 — Full-Person Silhouette
**In:** person_ctx. **Out:** `work\s02\person_full_visible.png` (binary, full-res), confidence map.
**Algorithm:** BiRefNet fp16 on ctx crop (long side 2048, tiled if larger); threshold 0.5 → binary;
keep largest component + any component ≥ 1% person area touching it; paste back to full canvas.
This mask = candidate `person_full_visible` (silhouette incl. hair + worn clothing) and the
universe for material labeling. **QC hook:** silhouette area vs bbox area ∈ [0.35, 0.95].

## S03 — Human Parsing (semantic prior)
**In:** person_ctx. **Out:** `work\s03\sapiens_28.png` (indexed), `work\s03\schp_atr.png`, per-class confidence.
**Algorithm:** Sapiens-0.6B-seg bf16, input long-side 1024 (tile 1536/128 overlap if needed);
argmax + per-class prob maps (saved 8-bit). SCHP-ATR run always (cheap) — provides clothing
classes + cross-check. Class-name → ontology mapping table lives in `configs\pipeline.yaml
(parsing_map)`, e.g. Sapiens `left_lower_arm`→forearm prior, `torso`→front-torso superset.
**Fail:** OOM → half-res retry → fallback SCHP-only with `parsing_degraded=true` flag.

## S04 — Whole-Body Pose + Hand Landmarks
**In:** person_ctx (+S01 bbox). **Out:** `work\s04\pose133.json` (COCO-WholeBody 133 kp with conf),
`work\s04\hands\{left,right}_landmarks.json` (21 kp each, MediaPipe on S05 hand crops later — two-pass),
`view` + `pose_tags` classification.
**Algorithm:** DWPose (yolox_l det + dw-ll_ucoco_384) via onnxruntime-gpu. View classification:
shoulder/hip keypoint geometry + nose visibility + DensePose back-ratio (after S08.5) →
{front, back, profiles, ¾}; pose_tags rules (arm elevation angles, hip-knee-ankle angles, overlap
tests) — deterministic rule table in `pipeline.yaml (pose_tags_rules)`.
**Fail:** <60% body kp above conf 0.3 → `pose_degraded=true`; geometry engine falls back to
parsing-only priors; image auto-tagged for careful review.
**AMENDED (doc 17 §5):** in a multi-person image, S03 and S04 must identify which detected human
each parsing/pose result belongs to (bbox/silhouette match against this instance's own defining
bbox) and suppress any result belonging to a different person before it can leak into this
instance's priors — the one place real disambiguation work is needed beyond "run it again per
instance." Everywhere else in S02–S09, no internal logic changes (doc 17 §5).

## S05 — Geometry Engine (per-part candidate priors)
**In:** pose133, parsing, silhouette. **Out:** `work\s05\prior_<label>.png` (soft 0–255) +
`work\s05\prompts.json` (SAM2 prompt plan per part).
**Algorithm (the heart of body-aware drafting):**
1. **Limb capsules:** for each limb segment (upper_arm, forearm, thigh, calf) build a capsule
   between its two keypoints; radius = local limb half-width sampled from parsing mask
   cross-sections at 5 stations (median). Clip capsule ∩ silhouette ∩ parsing-superset.
2. **Joint bands:** perpendicular bands at elbow/knee/wrist/ankle keypoints, height = 0.6×
   (0.5× wrist) local width (doc 02 §6.2); subtract from adjoining segment priors (carve-out).
3. **Torso partition:** clavicle line, under-breast fold estimate (chest kp + Sapiens torso mask
   horizontal profile minima), iliac line, midline → chest/breast boxes/abdomen/pelvis/hips
   candidate polygons; breasts seeded as ellipses from chest landmarks scaled by torso width
   (front/¾ views only).
4. **Hands/feet:** bbox from wrist/ankle + hand/foot kps × 1.6 → crop lane requests (doc 08).
5. **Hair:** parsing hair class ∪ GroundingDINO "hair" box (S06) → prior.
6. **Back classes:** if view ∈ {back, back-¾}: back torso split at waist line; scapula/spine bands
   from DensePose UV (doc 08 §5).
7. Every prior stored as soft map; `prompts.json` derives per-part SAM2 prompts: positive points =
   peak + skeleton-line samples (3–7 pts), negative points = neighbor-part peaks + background ring,
   box = prior bbox × 1.1. Prompt recipes per part class in `configs\prompting.yaml`.
**Fail:** missing kp for a part → prior from parsing only, `prior_quality=low` recorded.

## S06 — Open-Vocab Assist (boxes only)
**In:** person_ctx. **Out:** `work\s06\gdino_boxes.json`.
**Algorithm:** GroundingDINO prompts: "hair", "bra", "underwear", "shoe", "sock", "glove",
"necklace", "handheld object", "chair/bed/surface" (list in `prompting.yaml`), box_thresh 0.30,
text_thresh 0.25. Boxes feed S05 priors (hair) + S08 material seeds + PART 51–53 candidates.
**Hard rule:** GDINO output is never a final mask and never overrides pose/parsing on body parts.

## S07 — SAM2 Refinement (full-frame lane)
**In:** person_ctx, `prompts.json`. **Out:** `work\s07\sam2_<label>.png` + per-mask predicted IoU.
**Algorithm:**
1. Build SAM2.1 image embedding once per image (hiera-large fp16; auto-fallback base-plus on OOM).
2. For each part (full-frame lane = all except hand/foot/chest/hair crop-lane parts): prompt with
   box + positives + negatives from S05; `multimask_output=True`; select candidate maximizing
   `0.6·IoU(prior) + 0.4·predicted_iou`; one refinement iteration: add corrective points where
   selection disagrees with prior >8% area (positive in prior-only zones near skeleton, negative
   in mask-only zones outside prior bbox).
3. Post: threshold logits at 0, remove components < max(64 px², 0.02·part area), fill holes
   < 0.5% part area, **no smoothing/AA**.
4. Joint bands are cut from limb results geometrically (bands own their pixels).
**Fail:** predicted_iou < 0.5 → mark `sam2_low_conf`, keep prior as draft, flag for review.

## S08 — Clothing / Material Parse
**In:** person_ctx, S03 outputs, S06 boxes. **Out:** `work\s08\material_draft.png` (indexed per doc 02 §3).
**Algorithm:** fuse SCHP-ATR clothing classes + Sapiens clothing/skin classes + GDINO garment
boxes → material regions; skin = Sapiens skin ∧ ¬clothing; bra/underwear only when evidence
(SCHP class or GDINO box) — else `clothing_generic`; straps/waistband = thin-structure pass:
skeletonize clothing regions, width < 4% torso width → strap/waistband by orientation
(vertical-ish over shoulder = strap 10; horizontal at iliac line = waistband 11); sheer detection:
clothing region where skin-tone chroma similarity to adjacent skin > 0.8 → lace_or_sheer 12.
SAM2 edge-refine each material region (same recipe as S07). Glove/sock: hand/foot region ∧
clothing-texture → 15 (protects hand lane from labeling fabric as skin).

## S08.5 — DensePose Surface Prior
**In:** person_ctx. **Out:** `work\s08_5\densepose_iuv.png`.
Runs detectron2 DensePose R50; provides (I,U,V): body-surface part index + coordinates. Used by:
front/back torso disambiguation (majority surface per torso pixel), L/R sanity (QC-014 secondary
signal), scapula/spine band seeding, impossible-assignment detection (doc 08 §5).

## S09 — Consensus + Z-Order Fusion → Master Maps
**In:** everything above. **Out:** `label_map_part.png`, `label_map_material.png`,
`work\s09\disagreement.png`, consensus scores per part.
**Algorithm:**
1. Stack per-part evidence (S07 masks, priors, parsing, DensePose votes) → per-pixel candidate
   scores per PART id (weights doc 05 §4).
2. **Z-order arbitration** for contested pixels (two parts both score > 0.4):
   depth ranking rules (`fusion.zorder_rules`): (a) hands/fingers in front of torso/thighs when
   wrist kp depth-cue (kp ordering + occlusion edge direction) says so; (b) hair in front of
   face/neck/shoulders; (c) crossed limbs → limb whose boundary contour is uninterrupted wins
   front; (d) occluding_object (51) beats body when GDINO+SAM2 object mask covers with closed
   contour; ties → higher consensus score wins + pixel added to `overlap_occlusion_boundary` band
   and `occlusion{}` recorded in manifest (occluding_part owns pixels — hand over abdomen: hand
   wins, abdomen visibility → partially_visible).
3. Enforce exclusivity structurally (argmax into 16-bit map); background = ¬silhouette.
4. Material map analogous from S08 within silhouette.
5. Emit region bands (waist, contact, occlusion boundary…) per doc 02 §4 formulas.
6. `maskfactory export-binaries` + `derive` (unions) + geometry-engine projected regions →
   package draft complete; SQLite `status=drafted`.
**Determinism:** all seeds fixed (`pipeline.seed=1337`), torch deterministic algorithms on →
same inputs = byte-identical maps (Goal G8).

## S09.5 — Instance Reconciliation (NEW, doc 17 §5 — multi-person images only)
**In:** every promoted instance's completed S09 output for this image. **Out:**
`image_manifest.json` (preliminary), `interperson_contact_boundary` bands injected into each
involved instance's own `masks_regions\`.
**Algorithm:** runs once per image, after all promoted instances finish S09, before any
instance's S10. Checks cross-instance silhouette-overlap (catches one real person falsely split
into two instances, feeds QC-035); computes and reciprocally injects interperson contact/
occlusion bands (feeds QC-036/037). Single-person images skip this stage trivially (nothing to
reconcile). Full spec: doc 17 §5, §7.

## S10 — Auto-QA Battery
Runs all checks in doc 09 → `qa_report.json`; routes: all-pass → S11; format fail → auto-fix
attempt (regenerate from maps) else `rejected_needs_fix`; semantic fail → review flags. Status → `auto_qa`.

## S11 — VLM QA
Doc 10. Builds review panels, queries local VLM per hard part + whole-image sanity, writes
verdicts into qa_report, adjusts routing (agree → quick-pass queue; disagree → careful queue).
Status → `vlm_qa`.

## S12 — Human Review (CVAT)
Doc 11. `maskfactory cvat push` uploads image + draft masks as pre-annotations; human corrects with
SAM2 interactor; `cvat pull` retrieves; re-fuse (S09 on corrected inputs) → re-QA (S10 minimal set)
→ approval statuses set. Status → `in_review`/`corrected`.

## S13 — Gold Export & Packaging
Regenerate all binaries/derived/inpaint from final maps; build overlays + qa_panels; write final
manifest (hashes, review block); `verify-package`; status → `approved_gold`; DVC add.

## S14 — Dataset Build
Doc 12 §1–4: splits assignment (hash-stable), COCO/RLE + indexed-map dataset exports per trainer,
coverage matrix update, DVC commit `datasets/<version>`. Status → `exported`.

## S15 — Active Learning Loop
Doc 12 §7–8: harvest failure_queue + human-edit diffs (draft vs gold per-part IoU deltas) →
priority-ranked "what to shoot/generate next" report + hard-case holdout admission.

---

## Stage Runtime Budget (8 GB laptop, 1664×2432 typical, defaults)

| Stage | Budget | Stage | Budget |
|-------|--------|-------|--------|
| S00 | <1 s | S07 | 20–40 s (all parts, one embedding) |
| S01 | 1 s | S08(+.5) | 12 s |
| S02 | 6 s | S09 | 8 s CPU |
| S03 | 10 s | S10 | 10 s CPU-parallel |
| S04 | 4 s | S11 | 30–60 s (VLM slot) |
| S05 | 3 s CPU | S13 | 15 s |
| S06 | 4 s | **Total automated** | **≈ 2.5–3.5 min/image** |

Batch mode runs model-major (doc 05 §5) → ~40–60 img/hr automated throughput on this GPU.
