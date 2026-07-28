# Figure-to-MaskFactory Ontology Mapping Specification

## 1. Objective

Convert the visible rendered surface of each supported adult DAZ figure configuration into exact
MaskFactory PART, MATERIAL, protected-region, instance, and relationship annotations. Mapping is a
one-time, versioned engineering task per stable base topology plus explicit extensions for geografts,
hair, wardrobe, and topology-changing assets.

## 2. Mapping authority

The canonical MaskFactory ontology loader is the only label-name/ID authority. The mapping build process
loads `configs\ontology.yaml` or `configs\ontology_v2.yaml`, exports a frozen job mapping, and binds its
SHA-256. DAZ Script consumes that generated table. It never keeps an independent handwritten list of
IDs.

## 3. Supported maps

### PART map

One indexed visible-territory label per promoted-person pixel. For a clothed pixel, PART means the body
region represented by the visible garment surface; MATERIAL separately says clothing. It does not mean
the hidden skin is visible.

### MATERIAL map

One indexed material class per promoted-person silhouette pixel, using MaskFactory's material ontology:
skin, hair, clothing categories, underwear, footwear, straps, waistband, lace/sheer, glove/sock, and
other-person/object classes.

### Instance map

Background 0; promoted persons use 1–4 corresponding to p0–p3 after ranking. No visible pixel has two
owners.

### Protected map

Per-instance output for `other_person`, `occluding_object`, `support_surface`, and `accessory_or_prop`.
These labels do not enter the target person's atomic visible PART coverage.

### Diagnostic maps

Depth, normals, UV/surface ID, facet ID, bone influence, contact, and amodal geometry. Diagnostic maps
cannot silently become visible training truth.

## 4. Base mapping bundle identity

A mapping ID is keyed by:

```text
figure_generation
base_figure_asset_id and hash
base_geometry vertex/facet count and ordered topology hash
face-group/material-group hash
UV-set identity hash
skeleton/bone vocabulary hash
subdivision/cage policy
geograft composition set
MaskFactory ontology version/hash
mapping algorithm version/hash
manual override hash
golden-fixture set hash
```

A mismatch in any topology-defining field blocks reuse. Cosmetic material or morph changes may inherit
only if runtime inspection proves topology identity.

## 5. v1 indexed PART mapping

The Genesis 9 v1 bundle must cover:

```text
0 background
1 hair
2 head_face
3 neck
4 chest_upper_torso
5 left_breast
6 right_breast
7 abdomen_stomach
8 belly_button
9 pelvic_region
10 left_hip
11 right_hip
12 left_shoulder
13 right_shoulder
14 left_upper_arm
15 right_upper_arm
16 left_elbow
17 right_elbow
18 left_forearm
19 right_forearm
20 left_wrist
21 right_wrist
22 left_hand_base
23 right_hand_base
24 left_thumb
25 right_thumb
26 left_index_finger
27 right_index_finger
28 left_middle_finger
29 right_middle_finger
30 left_ring_finger
31 right_ring_finger
32 left_pinky
33 right_pinky
34 left_glute
35 right_glute
36 left_thigh
37 right_thigh
38 left_knee
39 right_knee
40 left_calf
41 right_calf
42 left_ankle
43 right_ankle
44 left_foot_base
45 right_foot_base
46 left_toes
47 right_toes
48 back_upper_torso
49 back_lower_torso
50 other_person
51 occluding_object
52 support_surface
53 accessory_or_prop
54 left_ear
55 right_ear
```

IDs 50–53 are protected categories, not ordinary polygons on the target body.

## 6. v2 append-only mapping

The separate v2 bundle preserves IDs 0–55 and adds:

```text
56 left_areola
57 right_areola
58 left_nipple
59 right_nipple
60 vulva
61 penis_shaft
62 glans_penis
63 left_scrotal_region
64 right_scrotal_region
```

Rules:

- mappings are visible-surface only;
- areola excludes nipple;
- breast atomics carve out same-side areola/nipple;
- pelvic region carves out visible IDs 60–65;
- shaft and glans are exclusive;
- scrotal regions split by character-left/right external surface;
- geografts/base hidden polygons are composited before label rendering;
- anatomy not present in a synthetic configuration uses explicit
  `synthetic_configuration_not_applicable`, not a fabricated human review;
- the package remains weighted synthetic supervision and cannot claim v2 human review authority.

## 7. Mapping construction method

### Step 1: freeze base geometry

Load a clean unmorphed base figure at subdivision/cage settings used for ID rendering. Export an ordered
facet inventory, material groups, face groups, UV sets, skeleton, and bone influence information. Hash
the canonical representation.

### Step 2: create coarse regions

Seed regions from:

- material/surface names;
- dominant bone weights and bone hierarchy;
- UV/body-surface partitions;
- geodesic distance from anatomical landmarks;
- bilateral symmetry plane;
- curated landmark vertices and boundary loops.

No one signal is sufficient. Bone influence alone produces poor joint boundaries; surface names alone
are too coarse.

### Step 3: refine atomic boundaries

Create frozen polygon sets and boundary loops for each atomic. Boundary rules follow the MaskFactory
ontology, not DAZ material seams. Important decisions:

- shoulder vs upper arm at the joint/torso transition;
- upper arm/elbow/forearm/wrist bands;
- palm/hand base vs each digit;
- chest vs breast and abdomen;
- front vs back torso using side seam/bilateral landmarks;
- hip/glute/thigh/pelvis carve-outs;
- knee/calf/ankle/foot/toes;
- head/face, ears, neck, hair;
- v2 visible anatomy carve-outs.

### Step 4: validate symmetry and sides

Character-left/right is defined in figure coordinates and bone identity, never screen position. Mirrored
camera views do not swap semantic IDs. Horizontal training augmentation performs the existing
swap-partner remap later.

### Step 5: serialize mapping

Store compact facet ranges/bitsets plus landmark/boundary metadata. Human-readable reports list area,
adjacency, neighbors, symmetry partner, and expected bones/surfaces per label.

### Step 6: render golden fixtures

Render neutral, articulated, close-up, back, profile, three-quarter, extreme-but-approved morph, and
occlusion fixtures. Verify pixel and topology properties.

## 8. Mapping bundle format

```yaml
schema_version: 1.0.0
mapping_id: daz_map_g9_body_parts_v1_0001
figure_generation: genesis9
base_figure_asset_id: daz_asset_...
topology_fingerprint_sha256: ...
ontology_version: body_parts_v1
ontology_sha256: ...
subdivision_policy: id_pass_base_cage
coordinate_convention: daz_world_character_left_right
labels:
  left_forearm:
    ontology_id: 18
    facet_selection_file: selections/left_forearm.bin
    source_bones: [l_forearm]
    boundary_loops: [left_elbow_distal, left_wrist_proximal]
    swap_partner: right_forearm
  # every mapped atomic
geografts: []
validation:
  golden_fixture_set_sha256: ...
  report_sha256: ...
  status: approved
created_at: ...
```

## 9. Morph inheritance

Morphs may inherit the mapping when:

- base facet count/order and face groups are unchanged;
- the figure uses the same topology fingerprint;
- no geometry shell/geograft changes visible ownership unexpectedly;
- boundary distortion remains within golden-fixture limits;
- joint/side/bone identities remain stable.

HD subdivision can be used for beauty renders, while exact ID passes use a stable base-cage mapping
projected through the same deformation. If subdivision introduces silhouette detail, the ID renderer
must rasterize the deformed subdivided surface while carrying parent-facet IDs; using a lower-resolution
silhouette that does not align with RGB is forbidden.

## 10. Geograft composition

For each geograft:

1. record base polygons hidden/replaced;
2. fingerprint graft topology/materials;
3. map graft facets to PART/MATERIAL IDs;
4. verify seam adjacency and no overlap/gap;
5. define v1 behavior and v2 behavior separately;
6. render neutral and articulated seam fixtures;
7. bind the graft mapping to exact base and graft hashes.

Unknown grafts cannot inherit by proximity alone in production. The system may propose a draft mapping,
but it stays `mapping_pending` until automated golden checks and any required one-time technical review
are complete.

## 11. Hair mapping

Hair is PART `hair` and MATERIAL `hair_material`. Scalp-cap, card, strand, facial-hair, brow/lash, and
body-hair assets are classified separately. Initial production support:

- polygon/card hair with stable opacity maps;
- fitted/parented hair with a validated alpha pass;
- facial hair mapped to hair without overwriting head/face ownership outside visible hair pixels.

Per-pixel opacity convention follows MaskFactory's 50% rule:

- coverage/opacity ≥0.5: hair owns the binary pixel;
- coverage/opacity <0.5: underlying visible surface owns it;
- an optional continuous alpha matte is stored separately.

Beauty antialiasing does not decide indexed truth. Truth comes from deterministic coverage sampling at
the same resolution with a documented threshold.

## 12. Wardrobe territory transfer

Visible garment pixels need a PART territory and a clothing MATERIAL. Territory is assigned using a
priority cascade:

1. asset-specific frozen territory map if present;
2. garment vertex skin weights/follow bones;
3. nearest corresponding deformed base-body surface with normal and distance constraints;
4. UV/cage transfer for supported fitted garments;
5. region-level curated override;
6. quarantine if unresolved.

For each garment vertex/facet, store a body-territory ID. At render time, interpolate only categorical
IDs through a stable facet ownership rule; do not blend IDs. Boundary pixels use exact raster ownership.

### Loose garments

Nearest-body projection can fail on skirts, coats, wide sleeves, and hanging fabric. Use garment pattern
pieces, rig bones, attachment regions, and geodesic continuity. A skirt may map to pelvis/hips/thigh
territories according to panel position, but must not fabricate separate left/right legs where the cloth
surface has no defensible association. Ambiguous zones become ignore 255 or the garment is excluded from
PART training while remaining usable for silhouette/material training.

### Layered garments

Only the frontmost visible garment owns MATERIAL pixels. PART territory is inherited from that garment.
Hidden garments and skin do not appear in visible maps. A separate layer stack may be stored for
diagnostics.

## 13. Accessories and props

- Wearable accessories covering the target person are `accessory_or_prop` in protected PART and
  `accessory` in MATERIAL unless the active ontology defines a body-territory treatment.
- Gloves/socks use body territories for PART and `glove_or_sock` for MATERIAL.
- Footwear uses foot/toe/ankle territory according to the mapped garment, MATERIAL `footwear`.
- Handheld props, furniture, and foreground objects are protected objects, never assigned to a body part.

## 14. Visible versus hidden anatomy

Visible PART truth is produced from the final beauty-visible geometry with all occluders present. To
compute diagnostics, the system may render:

- target alone;
- target without clothing;
- each person without other people;
- depth-peeled or full-geometry passes.

Those outputs live under `amodal_diagnostic`, carry `training_eligible: false`, and cannot satisfy
visible-mask QA, package acceptance, gold, or final metrics. Their purpose is occlusion reasoning,
relationship metadata, and future research.

## 15. Golden fixture suite

Minimum base fixtures:

- front/back/left/right profile/left/right three-quarter;
- arms down, arms overhead, arms crossed, elbow flexion, wrist rotation;
- fingers spread, fist, pinch-like contact, fingers partially occluded;
- standing, walking stride, seated, crouched, kneeling, prone/supine/side lying;
- hip/knee/ankle flexion and crossed legs;
- high/low body-shape extremes within policy;
- bald and hair-occluded head/shoulder;
- tight top/bottom, loose top/bottom, dress/skirt, gloves/socks/footwear, layered outfit;
- v2 front/back/profile close-ups for every applicable anatomy atomic;
- duo overlap/contact for other-person protection.

## 16. Mapping QA

Hard checks:

- unknown or unmapped visible person pixels = 0;
- atomic overlap pixels = 0;
- wrong ontology IDs = 0;
- left/right seeded swap defects all detected;
- derived union formulas reconstruct expected surface exactly;
- base silhouette equals union of visible target PART pixels, excluding protected occluders by contract;
- MATERIAL coverage equals target silhouette where not protected;
- v2 carve-outs are exact;
- mapping bundle/runtime/topology hashes match;
- repeated semantic passes are hash-identical.

Soft/route checks:

- area distributions by view/pose;
- boundary curvature and component counts;
- garment territory projection distance;
- hair alpha fringe;
- joint-boundary continuity under articulation.

## 17. Revocation

If a semantic mapping defect is found:

1. revoke the mapping bundle;
2. stop leasing dependent recipes;
3. identify every scene/package/dataset/model by mapping hash;
4. quarantine affected packages;
5. invalidate dataset builds and training candidates as required;
6. create a corrected mapping version;
7. rerender/revalidate from recipes;
8. never rewrite historical manifests to pretend the old mapping was correct.
