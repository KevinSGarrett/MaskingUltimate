# Document 02: Mask Ontology Specification
**Active mask_ontology_version: `body_parts_v1`** | **Approved inactive extension: `body_parts_v2` (doc 18)** | left/right = character perspective | atomic = visible-pixel-only

> **Authority-profile amendment (doc 24):** “human correction” in the legacy authorship column is
> the optional human/training-truth route. Core artifacts are authored by the governed autonomous
> candidate/fusion/repair transaction and receive production authority only through an exact-output
> operational certificate. Neither route may bypass the same structural ontology invariants.

---

## 1. Mask-Type Taxonomy (Resolves All Overlap Contradictions)

Every label has exactly one `mask_type`. This taxonomy is the core structural fix that makes the
ontology internally consistent: subsets and bands are no longer "atomic," so atomic exclusivity
can be enforced by construction.

| mask_type | Stored where | Overlap rule | Authored by |
|-----------|-------------|--------------|-------------|
| `atomic_exclusive` | PART map (indexed PNG) → generated binary PNGs | Zero overlap with other atomics (hard) | Governed pipeline transaction; optional human correction |
| `region_band` | `masks_regions\` binary PNGs | May overlap atomics; must stay inside person silhouette | Governed pipeline transaction; optional human correction |
| `derived_union` | `masks_derived\` binary PNGs | Overlap by definition | **Script only — never hand-authored** |
| `material` | MATERIAL map (indexed PNG) → generated binaries | Zero overlap within map | Governed pipeline transaction; optional human correction |
| `projected_amodal` | `projected\` binary PNGs | May overlap anything | Geometry engine; optional human correction; never visible-mask authority |
| `protected_qa` | PART map IDs 50–53 + `protected\` binaries | Exclusive within PART map | Governed pipeline transaction; optional human correction |

**Key consequences:**
- `left_hand` = union(hand_base + 5 fingers) → `derived_union`, generated.
- `left_foot` = union(foot_base + toes) → `derived_union`, generated.
- `abdomen_stomach` excludes `belly_button` pixels (carve-out); `abdomen_full` is the derived union.
- Joints (elbow/knee/wrist/ankle) are exclusive **carve-out bands** between limb segments (§6.2).
- `waist`, `spine_back_center`, scapulae, contact regions = `region_band` (inherently overlapping bands).
- `visible_body_skin`, `breast_skin` etc. = PART ∩ MATERIAL intersections, generated (§7).

## 2. Atomic Exclusive Registry — PART Map IDs (the master panoptic label map)

`label_map_part.png` (16-bit grayscale indexed) assigns every pixel exactly one ID below.
Binary gold PNGs are generated as `(part_map == ID) * 255`.

This table is the active v1 registry: 56 indexed PART records, IDs `0..55`, with background
already occupying ID 0. Document 18 appends IDs `56..65` for v2 without changing any row below;
the generated cross-version mirror is `Plan\OntologyV2\VERSIONED_REFERENCE.md`.

| ID | label | ID | label |
|----|-------|----|-------|
| 0 | background | 28 | left_middle_finger |
| 1 | hair | 29 | right_middle_finger |
| 2 | head_face | 30 | left_ring_finger |
| 3 | neck | 31 | right_ring_finger |
| 4 | chest_upper_torso | 32 | left_pinky |
| 5 | left_breast | 33 | right_pinky |
| 6 | right_breast | 34 | left_glute |
| 7 | abdomen_stomach | 35 | right_glute |
| 8 | belly_button | 36 | left_thigh |
| 9 | pelvic_region | 37 | right_thigh |
| 10 | left_hip | 38 | left_knee |
| 11 | right_hip | 39 | right_knee |
| 12 | left_shoulder | 40 | left_calf |
| 13 | right_shoulder | 41 | right_calf |
| 14 | left_upper_arm | 42 | left_ankle |
| 15 | right_upper_arm | 43 | right_ankle |
| 16 | left_elbow | 44 | left_foot_base |
| 17 | right_elbow | 45 | right_foot_base |
| 18 | left_forearm | 46 | left_toes |
| 19 | right_forearm | 47 | right_toes |
| 20 | left_wrist | 48 | back_upper_torso |
| 21 | right_wrist | 49 | back_lower_torso |
| 22 | left_hand_base | 50 | other_person |
| 23 | right_hand_base | 51 | occluding_object |
| 24 | left_thumb | 52 | support_surface |
| 25 | right_thumb | 53 | accessory_or_prop |
| 26 | left_index_finger | 54 | left_ear (optional, default merged into head_face) |
| 27 | right_index_finger | 55 | right_ear (optional, default merged into head_face) |

Notes:
- IDs 54–55 disabled by default (`configs\ontology.yaml: enable_ears: false`); reserved so IDs never shift.
- `hand_base` = palm + dorsum (back of hand) minus fingers. `foot_base` = foot minus toes.
- IDs 48–49 used only when the back is visible; front torso classes (4–9) and back classes never coexist on the same pixels — the fusion stage assigns whichever surface is actually visible (DensePose disambiguates, doc 08 §5).
- IDs 50–53 are `protected_qa` classes living inside the PART map so exclusivity vs body parts is structural.
- **AMENDED (doc 17 §6):** ID 50 (`other_person`) is scoped **per promoted instance**, not
  globally-once — it means "any human visible in *this instance's* crop who is not this
  instance," whether that other human is itself a separately-processed promoted instance or a
  non-promoted background person. No new PART ID; see doc 17 for the full multi-instance
  architecture.

## 3. MATERIAL Map Registry

`label_map_material.png` (8-bit indexed) is a **parallel layer** answering "what covers this pixel,"
independent of which body part it is. This two-map design is what lets the system express
`left_breast` (part) vs `left_breast_skin` (part ∩ skin) vs `chest_clothing_over_breast`
(part ∩ clothing) without subset masks fighting for the same pixels.

| ID | material label | ID | material label |
|----|----------------|----|----------------|
| 0 | none/background | 8 | footwear |
| 1 | skin | 9 | accessory |
| 2 | hair_material | 10 | strap |
| 3 | clothing_generic | 11 | waistband |
| 4 | bra | 12 | lace_or_sheer |
| 5 | underwear_bottom | 13 | other_person_material |
| 6 | top_garment | 14 | object_material |
| 7 | bottom_garment | 15 | glove_or_sock |

Rules:
- Material is labeled on the **person region only** (pixels where PART id ∈ 1–49); elsewhere material=0, except IDs 13–14 which mirror PART 50–53.
- `bra_left_cup` / `bra_right_cup` / `bra_straps` are generated: `bra ∩ left_breast`, `bra ∩ right_breast`, `strap ∩ chest/shoulder parts`.
- `lace_or_sheer` marks translucent fabric; pixels get material=12 AND the PART id of the body part visible through it; QA treats these as soft-boundary (doc 09 QC-021 exemption + optional trimap, doc 03 §7).

## 4. Region-Band Registry (non-exclusive bands, stored in `masks_regions\`)

| label | Definition (annotation guideline) |
|-------|-----------------------------------|
| waist | Horizontal band between lowest-rib line and iliac-crest line, full visible width; height = 12% of shoulder-to-hip keypoint distance |
| spine_back_center | Vertical band centered on spine line (back views), width = 10% of shoulder width |
| left_scapula_back / right_scapula_back | Shoulder-blade regions on back_upper_torso, seeded from DensePose back-surface UV patches |
| body_contact_region | Pixels where two body surfaces touch (hand-on-thigh, crossed legs); union of the boundary band, width = 8 px @1024 ref, scaled |
| left_body_contact_region / right_body_contact_region | Side-attributed subsets of body_contact_region by owning limb |
| overlap_occlusion_boundary | 6 px band (scaled) along every atomic↔atomic occlusion edge where z-order was applied |
| left_underarm / right_underarm | Axilla band where upper_arm meets side torso (enabled by config when needed) |
| left_side_torso / right_side_torso | Lateral torso strips (optional, config) |
| left_inner_thigh / right_inner_thigh / *_outer_thigh, *_shin_front | Optional finer bands (config; add only when failure mining shows need — doc 12 §8) |
| interperson_contact_boundary | **AMENDED (doc 17 §6):** pixels where two *different* promoted instances' bodies visibly touch or occlude each other, in a multi-person image; same 8 px @1024 ref scaling convention as `body_contact_region` |

## 5. Projected / Amodal Registry (stored in `projected\`; never visible-truth)

| label | Meaning |
|-------|---------|
| left_breast_projected_region / right_breast_projected_region | Geometric breast region estimated from torso landmarks + clothing surface — the editable region when clothing covers skin |
| left_chest_clothing_over_breast / right_chest_clothing_over_breast | material∈{3,4,6,10,12} ∩ breast projected region (generated) |
| amodal_<part> (e.g., amodal_left_forearm) | Full-extent estimate of a partially occluded part = visible atomic ∪ estimated hidden continuation (geometry engine) |
| inpaint_<part>_d<k>f<f> | Derived edit masks: gold dilated k px, feathered f px — see doc 03 §6 |

Contract (global): `visible_mask` = pixels actually visible (gold truth). `projected_region` =
estimated edit/anatomy region under clothing/occlusion. `amodal_region` = full-object estimate.
The three are separate files, separate manifest entries, separate QA tracks. No exceptions.

## 6. Boundary Definitions (Annotation Guidelines — the tie-breakers)

### 6.1 Torso front
- `neck`: jawline/hair boundary down to clavicle line (clavicle keypoints).
- `chest_upper_torso`: clavicle line to under-breast fold line, **excluding** breast regions (5/6).
- `left_breast`/`right_breast`: visible breast surface bounded by the natural contour and inframammary fold; when contour is ambiguous under tight clothing, the breast **part** boundary follows the visible fabric-defined contour (material still says clothing; skin claims nothing).
- `abdomen_stomach`: under-breast fold to iliac-crest line, excluding belly_button carve-out (belly_button = navel depression, typ. 12–40 px @1024).
- `pelvic_region`: iliac-crest/waistband line down to genital/inner-thigh junction, between hip classes.
- `left_hip`/`right_hip`: lateral pelvis from iliac crest to greater-trochanter line.

### 6.2 Joint carve-out bands (exclusive atomics)
Joint band = perpendicular band centered on the pose keypoint; **band height = 0.6 × local limb
width** measured at the keypoint (limb width from parsing mask cross-section). Limb segments
(upper_arm/forearm, thigh/calf) exclude the band. Wrist band = 0.5 ×; ankle = 0.6 ×. This makes
elbow/knee/wrist/ankle deterministic, exclusive, and reproducible.

### 6.3 Hands & feet
- `hand_base` starts at the distal wrist-band edge; fingers start at the MCP knuckle line (per-finger polygon from 21 hand landmarks); inter-finger gaps = background (or the occluded object/part behind).
- If fingers are pressed together and boundaries are truly indistinguishable → label the merged
  region `hand_base` + set finger states `ambiguous_do_not_use` + flag `fingers_merged_or_ambiguous: true` (doc 08 §2.6). Never guess finger splits.
- `toes` start at the metatarsophalangeal line; per-toe splitting is OUT of v1 atomic scope
  (all-toes region only). Document-18 v2 does not add per-toe IDs; any future split requires a
  separate evidence-backed append-only ontology change.

### 6.4 Hair / face / skin edges
- `hair` claims pixels where hair occludes face/body (z-order: hair in front). Wispy strand zone
  handled by matting exception (doc 03 §7); binary boundary = 50% opacity rule (pixel majority hair).
- `head_face` = face + ears (default) + scalp skin visible through hair partings.

### 6.5 Glutes & back
- `left_glute`/`right_glute`: gluteal fold to iliac crest, split at midline; visible in back/side/¾ views only.
- Front-vs-back torso assignment is decided by DensePose surface (I,U,V) majority vote (doc 08 §5); never label both for one pixel.

## 7. Derived Union Registry (script-generated, `masks_derived\`)

The list below is the active v1 registry. V2 preserves these formulas and adds the anatomy
surface unions in doc 18 §3 through inactive `configs\derived_v2.yaml` until activation.

both_breasts, breast_skin (=(5∪6)∩mat1), left_breast_skin, right_breast_skin,
left_hand, right_hand, both_hands, all_fingers, all_thumbs, all_index_fingers,
all_middle_fingers, all_ring_fingers, all_pinkies, left_foot, right_foot, both_feet, all_toes,
both_arms, both_upper_arms, both_forearms, both_glutes, both_thighs, both_knees, both_calves,
full_torso (4–11,48,49), full_arms (12–33), full_legs (34–47), abdomen_full (7∪8),
full_body_parts_visible (PART ids 1–49), person_full_visible (silhouette incl. hair+clothing on body),
visible_body_skin ((1–49)∩mat1 minus hair id1), clothing_visible (mat∈{3..8,10,11,12,15}),
bra_visible (mat4), panty_visible (mat5), bra_left_cup, bra_right_cup, bra_straps,
clothing_boundary_chest (edge band of mat∈{3,4,6} within chest/breast parts),
clothing_skin_boundary (global mat1↔clothing edge band, 4 px scaled),
clothing_bodypart_occlusion (clothing pixels inside amodal body estimates).

Generator: `maskfactory derive` — reads both maps + config `configs\derived.yaml` (formulas as
declarative expressions), writes PNGs + records formula string + input hashes in manifest.

## 8. Visibility States (per part, per image — manifest authority)

`visible | partially_visible | occluded | cropped_out | not_visible | ambiguous_do_not_use`

That is the active v1 vocabulary. V2 uses the separate schema and adds
`occluded_by_clothing | not_applicable | unreviewed_for_v2` under doc 18 §4; those values are
invalid in a v1 manifest and `unreviewed_for_v2` can never become negative supervision.

- `visible`: ≥90% of expected part area present (expected from amodal estimate).
- `partially_visible`: 10–90% present; mask contains only visible pixels.
- `occluded`: <10% visible due to object/body/clothing occlusion; no gold mask; projected/amodal may exist.
- `cropped_out`: outside frame (e.g., "mask claims foot but image cropped above ankle" → QC-016 auto-detects via pose completeness and blocks).
- `not_visible`: facing away (e.g., glutes in frontal view).
- `ambiguous_do_not_use`: annotator cannot decide honestly; excluded from training & metrics.

## 9. Ontology Versioning & Change Procedure

1. Labels are append-only; IDs are never renumbered or reused. Deprecation = status flag in `configs\ontology.yaml`.
2. Any change bumps `mask_ontology_version` (v1 → v1.1 additive; v2 breaking) and adds a migration note in `Plan\CHANGELOG_ONTOLOGY.md`.
3. Every manifest stores the ontology version it was authored under; training configs declare which versions they accept and how deprecated labels map.
4. Left/right convention, visible-only rule, and binary format are constitutional — they cannot change within body_parts_v*.
5. The approved `body_parts_v2` change is governed by doc 18 and
   `Plan\OntologyV2\IMPLEMENTATION_CHECKLIST.md`; generated v2 artifacts remain inactive until
   every activation gate passes and the active runtime/champions are switched together.

## 10. Canonical Machine-Readable Ontology

`configs\ontology.yaml` is the active v1 source of truth consumed by production code. The
append-only v2 candidate is generated separately at `configs\ontology_v2.yaml`; it is selected
only by explicit version-aware paths until activation. Every ontology carries every label with
{id, name, mask_type, map (part/material/none), side (left/right/center/na), parent_union,
enabled, expected_area_pct_range, max_components, exclusivity_group, swap_partner (for flip
augmentation), visibility_default}. The tables in this document are the human mirror of that file;
task MF-P1-03 (doc 14) generates the active YAML from these tables and asserts consistency in CI;
the v2 generator and `tools\generate_ontology_version_reference.py --check` independently prove
the 56-row prefix is unchanged and the nine additions are contiguous.
