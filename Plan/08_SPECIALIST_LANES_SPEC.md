# Document 08: Specialist Lanes Specification

Hard regions get their own crops, models, prompting recipes, QA panels, and metrics. Each lane
plugs in between S07 and S09 and overrides the full-frame result for its parts.

---

## 1. Lane Common Contract
**In:** crop request from S05 (bbox, part set). **Out:** crop-space masks + `crop_to_full_transform.json`
+ lane confidence + `qa_panels\` zoom set. Reprojection nearest-neighbor; QC-018 round-trip check.
Crops: square, 1.6 × part bbox, resampled to 1024 (image Lanczos / masks nearest).

**AMENDED (doc 17 §5):** in a multi-person image, every lane below runs once per **promoted
instance**, on that instance's own crop — no lane's internal logic changes. Any co-subject
(another promoted instance, or a non-promoted background person) visible within a lane's crop is
`other_person_protected`, exactly as at the full-frame level; e.g. the hand lane's contact
handling (§2.7 below) extends naturally to interperson contact via the same z-order mechanism,
now also feeding the `interperson_contact_boundary` band (doc 02 §4, doc 17 §6) when the contact
is with a *different* instance rather than the same person's own body.

## 2. Hand / Finger Lane (parts 20–33 per side)
2.1 Crop per hand from wrist kp + DWPose hand kps.
2.2 MediaPipe HandLandmarker on crop → 21 landmarks + handedness score. Handedness is
    cross-checked against skeleton side (arm chain) — mismatch → QC-014 flag, skeleton wins.
2.3 Build per-finger polygons: each finger = quad strip along its 4 landmarks, width from local
    parsing/silhouette cross-section; palm/dorsum region = convex hull(MCPs + wrist) minus fingers.
2.4 SAM2 on the CROP (fresh embedding): per finger — box + 3 positives along finger line +
    **negatives in the inter-finger gaps** (midpoints between adjacent finger lines) + negatives on
    neighboring fingers; palm/hand_base similarly with finger negatives.
2.5 Gap ownership: inter-finger gap pixels → background or the part behind (from full-frame map);
    `left/right_finger_gap_regions` emitted as region bands for QA.
2.6 Merge handling: if adjacent finger masks overlap > 30% after refinement OR landmark confidence
    < 0.5 → do NOT split: label region `hand_base`, set those finger states
    `ambiguous_do_not_use`, set `fingers_merged_or_ambiguous=true`, emit `finger_occlusion_boundary`
    band, queue to failure_queue(finger_merge). Never guess splits (doc 02 §6.3).
2.7 Contact: hand-on-body → hand wins z-order (S09 rule a); contact band emitted.
2.8 Lane metrics: per-finger IoU/boundary-F tracked separately on the leaderboard; P5 trains the
    dedicated hand-crop segmenter (doc 12 §6.3) which replaces 2.3–2.4 drafting when it wins.

## 3. Chest / Breast / Clothing-Boundary Lane (parts 4,5,6 + materials 1,3,4,6,10,12)
3.1 Crop: clavicle-to-under-bust region × 1.4.
3.2 Landmark geometry: shoulder/neck/underarm points + torso width → breast ellipse seeds
    (front/¾ only; profile → single visible breast; back → lane skipped, states not_visible).
3.3 **Visible-truth rule (the lane's constitution):**
    - Skin visible → `left/right_breast` follows visible skin contour; material=skin.
    - Clothing covers → the breast PART boundary follows the fabric-defined visible contour;
      material says bra/top/etc. `*_breast_skin` (derived) is then empty — correct and honest.
    - The editable under-clothing region is `*_breast_projected_region` (projected_amodal):
      ellipse fit refined by clothing surface shading gradient (shape-from-shading lite: fit on
      luminance curvature within clothing region), clipped to torso. It is never exported as
      visible anatomy and never enters the PART map.
3.4 SAM2 crop refinement of: skin regions, each garment piece, strap lines (box prompts from S08
    thin-structure pass), inframammary/clothing boundary (`clothing_boundary_chest` band = 4 px
    edge band of material transition within chest/breast parts).
3.5 QA: QC-019 (breast part ∩ material=skin must equal breast_skin derived), QC-020 (projected
    region must NOT intersect material=skin claims beyond visible part), zoom panels mandatory.
3.6 Human review always at crop zoom for this lane (doc 11 SOP-4).

## 4. Hair / Face Lane (parts 1,2 + matting)
4.1 Crop: head bbox × 1.8 (hair can be huge — fall back to full frame if hair prior exceeds crop).
4.2 Sapiens hair/face classes + BiSeNet face-parsing (fallback/detail) → hair vs face vs scalp-skin.
4.3 Binary hair boundary = majority-opacity rule; SAM2 refine with negatives on face/background.
4.4 Matting add-on when hair ≥ 2% person bbox: trimap (±6 px) → ViTMatte → `matting\` files (doc 03 §7).
4.5 `face_protected` QA mask = face-parsing {eyes, mouth, nose, brows, jawline band} → `protected\` —
    body-part masks must not intrude (QC-013 protected-overlap).
4.6 Hairline zoom panel mandatory; hair-over-shoulder pixels belong to hair (z-order rule b) and
    shoulders get partially_visible.

## 5. 3D Body Prior Lane (DensePose sanity referee — no mask authoring)
Checks after fusion, before QA sign-off:
- Surface consistency: pixels labeled front-torso classes whose DensePose I says back surface
  (> 25% of part) → QC-024 fail (front/back confusion).
- L/R surface check: DensePose L/R surface majority vs label side → secondary signal into QC-014.
- Continuity: a limb part whose DensePose UV field is discontinuous across the mask (split
  surfaces) → occlusion likely missing → flag `occlusion_suspect`.
- Impossible adjacency: mask adjacency graph vs body topology (doc 09 §5) with DensePose evidence.
Optional v2 upgrade slot: SMPL-X fitting (PIXIE) for full 3D pose prior — interface reserved in
`lanes/prior3d.py`, not built in v1 (decision: DensePose sufficiency first).

## 6. Feet / Toes Lane (parts 42–47)
Crop per foot (ankle kp + 6 foot kps × 1.6). Foot_base vs toes split at metatarsophalangeal line
(from big-toe/heel kps + width profile). Footwear present (material 8/15) → foot skin states
not_visible/occluded, foot PART follows visible skin only (barefoot/sandals); shoe itself =
material footwear over `foot_base` part only if skin visible at edges — fully covered foot →
PART stays foot_base? **Decision:** fully-shod foot = PART foot_base with material=footwear
(the body part location is visible even if skin is not; `visible_body_skin` correctly excludes it).
Toes under closed shoes → `not_visible`. Sock = material 15, same PART logic.
Per-toe splitting deferred to ontology v2 (doc 02 §6.3).

## 7. Uncertainty & Disagreement Maps (all lanes)
Every lane emits per-pixel confidence; S09 writes `work\s09\disagreement.png` (0–255) =
1 − normalized top-2 candidate margin. Regions with disagreement > 0.5 covering > 3% of a part →
part flagged `model_disagreement_high` + `needs_human_review` + `ambiguous_boundary` note; CVAT
shows the heatmap as an extra layer so the human goes straight to the contested pixels.
