# ITEMS — Phase P3: Specialist Lanes (Weeks 4–6)

Goal: all hard-class lanes live, topology QCs on, 100 gold, median review ≤ 25 min (G1-P3). Parent IDs from doc 14 §4.

## MF-P3-01 — Crop contract + hand/finger lane (spec: 03 §5, 08 §1–2)
- [ ] MF-P3-01.01 Lane common contract module: square crop 1.6 × part bbox → 1024 (image Lanczos / masks NEAREST) · write `crops\crop_to_full_transform.json` · nearest reprojection · wire QC-018 (round-trip IoU ≥ 0.995, BLOCK)
- [ ] MF-P3-01.02 Hand crop per side from wrist kp + DWPose hand kps → `crops\left/right_hand_crop.png`
- [ ] MF-P3-01.03 MediaPipe HandLandmarker on crop → 21 landmarks + handedness · cross-check vs skeleton arm chain — mismatch → QC-014 flag, SKELETON WINS
- [ ] MF-P3-01.04 Per-finger quad strips along 4 landmarks (width from local parsing/silhouette cross-sections) · palm/dorsum = convex hull(MCPs + wrist) − fingers
- [ ] MF-P3-01.05 SAM2 on the CROP (fresh embedding): per finger box + 3 positives along finger line + NEGATIVES at inter-finger gap midpoints + negatives on neighboring fingers · hand_base with finger negatives
- [ ] MF-P3-01.06 Gap ownership: inter-finger pixels → background or behind-part from full-frame map · emit `left/right_finger_gap_regions` bands
- [ ] MF-P3-01.07 Merge rule: adjacent-finger overlap > 30% post-refine OR landmark conf < 0.5 → do NOT split: region = hand_base · finger states `ambiguous_do_not_use` · `fingers_merged_or_ambiguous: true` · emit `finger_occlusion_boundary` band · failure_queue(finger_merge)
- [ ] MF-P3-01.08 Contact handling: hand-on-body → hand wins z-order (rule a) · contact band emitted
- [ ] MF-P3-01.09 Tests: inter-finger gaps verifiably NOT filled on fixtures · paste-back IoU ≥ 0.995 · per-finger IoU/boundary-F rows land on the leaderboard

## MF-P3-02 — Chest/breast/clothing lane + S08 material parse (spec: 08 §3, 07 S08)
- [ ] MF-P3-02.01 S08 fuse: SCHP clothing classes + Sapiens skin/clothing + GDINO garment boxes → material regions · skin = Sapiens skin ∧ ¬clothing · bra/underwear only with evidence (SCHP class or GDINO box), else `clothing_generic`
- [ ] MF-P3-02.02 Thin-structure pass: skeletonize clothing · width < 4% torso width → strap (vertical-ish over shoulder, id 10) / waistband (horizontal at iliac line, id 11)
- [ ] MF-P3-02.03 Sheer detection: clothing region with skin-tone chroma similarity > 0.8 to adjacent skin → `lace_or_sheer` (12)
- [ ] MF-P3-02.04 SAM2 edge-refine every material region · glove/sock rule: hand/foot region ∧ clothing texture → material 15 (protects hand lane)
- [ ] MF-P3-02.05 Chest crop clavicle-to-under-bust × 1.4 · breast ellipse seeds from landmarks · profile → single visible breast · back view → lane skipped, breast states `not_visible`
- [ ] MF-P3-02.06 Visible-truth rule in code: skin visible → PART follows skin contour (material skin) · clothed → PART follows fabric-defined visible contour (material bra/top…) · `*_breast_skin` derived = PART ∩ material-skin (empty when fully clothed = CORRECT)
- [ ] MF-P3-02.07 Projected drafting: `*_breast_projected_region` ellipse refined by clothing-surface luminance-curvature (shape-from-shading lite), clipped to torso · lands ONLY in `projected\`, never the PART map
- [ ] MF-P3-02.08 Strap/inframammary SAM2 refinement + `clothing_boundary_chest` 4 px transition band · mandatory zoom panels
- [ ] MF-P3-02.09 Upgrade S09 to consume the S08 material map (replaces the P2 SCHP stopgap) · seeded clothed-breast fixture: breast_skin empty + projected drafted + QC-019/020 pass

## MF-P3-03 — Hair/face lane + matting (spec: 08 §4, 03 §7)
- [ ] MF-P3-03.01 Head crop × 1.8 with full-frame fallback when the hair prior exceeds the crop
- [ ] MF-P3-03.02 Sapiens hair/face + BiSeNet detail fallback → hair vs face vs scalp-skin · binary hair via majority-opacity rule · SAM2 refine with negatives on face/background
- [ ] MF-P3-03.03 Matting add-on when hair ≥ 2% person bbox: trimap ±6 px (scaled) → ViTMatte → `matting\hair_trimap.png` + `hair_alpha_matte.png` (+ binary copy) · same optional path for lace_or_sheer
- [ ] MF-P3-03.04 `face_protected` mask (eyes, mouth, nose, brows, jawline band) → `protected\` · QC-013 protected-overlap wired against it
- [ ] MF-P3-03.05 Hairline zoom panel mandatory · hair-over-shoulder pixels → hair (z-order b), shoulders → partially_visible

## MF-P3-04 — Feet/toes lane (spec: 08 §6)
- [ ] MF-P3-04.01 Foot crop per side (ankle kp + 6 foot kps × 1.6) · foot_base/toes split at metatarsophalangeal line (big-toe/heel kps + width profile)
- [ ] MF-P3-04.02 Footwear logic: fully-shod → PART foot_base + material footwear(8), toes `not_visible` · sock = material 15, same PART logic · barefoot/sandal → skin-following contours · `visible_body_skin` correctly excludes shod feet
- [ ] MF-P3-04.03 Shod-foot fixture verifies all of the above

## MF-P3-05 — DensePose 3D-prior referee (spec: 08 §5, 07 S08.5)
- [ ] MF-P3-05.01 S08.5 stage: detectron2 DensePose R50 → `work\s08_5\densepose_iuv.png` (I,U,V surface map)
- [ ] MF-P3-05.02 Front/back torso disambiguation votes into fusion · view-classifier back-ratio input now live (completes P2-03.02)
- [ ] MF-P3-05.03 QC-014 third signal live (skeleton + handedness + DensePose → full 2-of-3 vote) · QC-024 front/back surface check active
- [ ] MF-P3-05.04 UV-continuity check → `occlusion_suspect` flag · impossible-adjacency evidence feeds topology checks
- [ ] MF-P3-05.05 Front/back-confusion fixture fires QC-024 · L/R fixture confirms 2-of-3 behavior
- [ ] MF-P3-05.06 Confirm SMPL-X slot remains a stub interface in `lanes\prior3d.py` (v2 reservation — no build)

## MF-P3-06 — Topology QCs + disagreement + regression guard (spec: 09 §3–4)
- [ ] MF-P3-06.01 Adjacency-graph engine (3 px scaled dilation) · QC-025 chain integrity (wrist↔hand_base, elbow↔arm segments, knee↔thigh/calf, ankle↔calf/foot, toes↔foot_base, fingers↔hand_base, neck↔head) with occlusion exemption — the occluder mask must actually cover the gap band
- [ ] MF-P3-06.02 QC-026 finger containment (⊂ dilate(hand crop, 10 px)) + mandatory thumb↔hand_base adjacency
- [ ] MF-P3-06.03 QC-027 band geometry: bands intersect both limb segments · height within ±30% of formula
- [ ] MF-P3-06.04 QC-028 side coherence (left_* centroid chain vs skeleton; no lone part flipped across midline)
- [ ] MF-P3-06.05 QC-029 breast position: centroids in chest horizontal band · L/R order matches view (mirrored in back-¾ = fail)
- [ ] MF-P3-06.06 QC-031 disagreement > 0.5 over > 3% area → ROUTE · QC-032 sam2_low_conf WARN · QC-033 degraded-flags ROUTE
- [ ] MF-P3-06.07 QC-034 regression guard (BLOCK): IoU vs previous gold < 0.5 on re-process · gold v1-vs-v2 diff report renders
- [ ] MF-P3-06.08 Chain-break fixture is routed with the correct QC evidence attached

## MF-P3-07 — 100-gold sprint + throughput (spec: 11 §3–7)
- [ ] MF-P3-07.01 Annotation cadence with SOP-2 (hands), SOP-3 (panels first), SOP-4 (chest crop-zoom, projected in separate purple-label jobs) in active use
- [ ] MF-P3-07.02 Reach 100 `human_approved_gold` packages
- [ ] MF-P3-07.03 Median review time ≤ 25 min/image verified from review_tasks minutes (G1-P3)
- [ ] MF-P3-07.04 Begin informal second-look habit (fresh-day re-review of hard classes; formal sampler lands P4-06)

## P3 Exit Gate
- [ ] MF-P3-EXIT All lanes live · hard classes have panels + QCs · doc 14 §4 checkboxes updated
