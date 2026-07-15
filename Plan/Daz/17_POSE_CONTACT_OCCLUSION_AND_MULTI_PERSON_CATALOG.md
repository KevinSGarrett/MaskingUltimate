# Pose, Contact, Occlusion, and Multi-Person Catalog

## 1. Purpose

Pose diversity must exercise every MaskFactory boundary, left/right relationship, contact pattern, and
multi-person ownership failure mode. The planner uses normalized pose descriptors so thousands of DAZ
presets do not become an opaque list of marketing names.

## 2. Pose representation

Each normalized pose record includes:

```text
pose_id and source asset
figure generation
root transform policy
bone rotations in canonical names
pose family and subfamily tags
support/contact requirements
hands/feet visibility expectation
self-occlusion tags
left/right asymmetry tags
camera-view suitability
joint-limit and intersection scores
paired/group slot definitions when applicable
```

Partial poses declare exactly which bones they own. The generator can compose upper/lower/hand/expression
poses only when ownership sets do not conflict or a declared priority resolves them.

## 3. Solo whole-body pose families

### Neutral and calibration

- anatomical neutral;
- relaxed standing;
- contrapposto left/right;
- feet together/apart;
- arms beside body, slightly abducted, and T/A-like mapping fixtures;
- front/back/profile calibration stances.

### Locomotion

- walking at multiple stride phases;
- running/jogging;
- stepping up/down;
- turning/pivoting;
- starting/stopping;
- leaning into motion;
- carrying an object while walking;
- asymmetric arm swing;
- tiptoe/heel-raised movement.

### Seated

- upright chair;
- relaxed/slouched;
- legs parallel/apart/crossed at knee/crossed at ankle;
- one knee raised;
- side-sit;
- floor sit: cross-legged, legs extended, one/both knees bent;
- stool/bench/edge sit;
- seated reaching/turning;
- seated hand-to-face/torso/leg contact.

### Crouching and kneeling

- shallow/deep squat;
- athletic crouch;
- one-knee kneel;
- both-knees kneel;
- lunge;
- crouched reach;
- kneeling upright/forward/side lean;
- hands supporting on knee/floor.

### Lying and reclining

- supine;
- prone;
- left/right side lying;
- curled/fetal-like adult pose;
- reclined on elbows;
- reclined on one arm;
- knees straight/bent/raised;
- arms overhead/across torso/alongside;
- supported by bed/couch/floor.

### Athletic, dance, and flexibility

- jump preparation/airborne/landing;
- balance on one leg;
- kick variants within joint limits;
- stretch/yoga-like standing, seated, kneeling, and floor poses;
- dance turns, extensions, and asymmetric lines;
- weightlifting/sport-generic stances with optional props;
- push-up/plank/crawl-like support;
- inversion only after framing/contact tests.

These are geometry/coverage categories, not activity recognition labels.

## 4. Torso orientation families

- upright neutral;
- flexion/extension;
- left/right lateral bend;
- left/right axial twist;
- twist plus bend;
- forward/back lean;
- shoulder elevation/depression;
- asymmetric shoulder rotation;
- pelvis tilt/rotation/translation;
- torso/hip counter-rotation.

Torso variation is crossed with camera view because front-facing root orientation does not guarantee a
front-visible torso after twisting.

## 5. Arm and hand pose families

### Arms

- down, forward, side, diagonal, overhead;
- elbows straight, mild, 90-degree, deeply flexed;
- arms crossed over chest/abdomen;
- hands behind back/head/neck;
- one arm across body;
- reaching toward camera/away/side/up/down;
- pushing/pulling/carrying;
- asymmetric combinations.

### Hand articulation

- relaxed open;
- fingers spread;
- closed fist;
- partial fist;
- flat palm;
- pointing;
- pinch-like thumb/index proximity;
- thumb opposition across palm;
- individual finger flexion/extension;
- fingers interleaved with self/other hand only in mapped contact recipes;
- hand holding cylindrical/box/handle/soft prop;
- palm toward/away/edge-on to camera.

### Hand-to-body self-contact targets

- face/head/hair;
- neck/shoulder;
- chest/upper torso;
- abdomen/waist/hip;
- opposite arm/elbow/wrist/hand;
- thigh/knee/calf/ankle/foot;
- back/glute where pose permits.

Every contact target records contacting surfaces, intended visible boundary, and allowed penetration
tolerance.

## 6. Leg and foot pose families

- feet parallel, turned in/out, staggered;
- legs together/apart;
- one leg forward/back/side;
- knees straight/mild/deep flexion;
- legs crossed standing/seated/lying;
- thigh-to-thigh and calf overlap;
- one foot raised;
- ankle plantar/dorsiflexion and inversion/eversion within range;
- toe point/flex where asset supports it;
- barefoot, footwear, and support contact;
- foreshortened leg toward camera.

## 7. Self-occlusion taxonomy

```text
arm_over_torso
forearm_over_face
hand_over_face
hand_over_chest
hand_over_pelvis
hand_over_leg
crossed_arms
crossed_legs
thigh_overlap
hair_over_face
hair_over_neck
hair_over_chest
hair_over_back
torso_twist_hides_far_arm
profile_hides_far_limbs
foreshortened_limb
prop_over_body
support_surface_over_body_boundary
crop_truncation
```

The scene manifest distinguishes geometrically occluded, cropped, and not-applicable states.

## 8. Multi-person anatomy-count matrix

Required configuration families:

| Count | Families |
|---:|---|
| 2 | MM, MF, FF |
| 3 | MMM, MMF, MFF, FFF |
| 4 | MMMM, MMMF, MMFF, MFFF, FFFF |

For every mixed family, each anatomy configuration must occupy foreground/background, left/right screen,
larger/smaller apparent scale, and p0/non-p0 roles over the corpus. Wardrobe and presentation vary
independently. Unclothed and clothed multi-person scenes use the same identity and pixel-ownership rules.

## 9. Multi-person spatial relationship families

### No contact

- separated side by side;
- front/back depth-separated;
- crossing paths;
- one seated, one standing;
- different heights/scales;
- one partially cropped;
- three/four-person row, arc, triangle, depth stack, and clustered group.

### Partial overlap without contact

- torso overlap;
- head/shoulder overlap;
- arm/torso overlap;
- crossed limbs at different depths;
- foreground person truncating background person;
- crowded composition with clear depth ordering.

### Contact and support

- hand-to-hand;
- hand-to-forearm/upper arm/shoulder/back/waist/hip/leg;
- arm around shoulder/torso;
- side-by-side embrace/contact;
- front/back embrace/contact;
- seated adjacent contact;
- one character supporting another's hand/arm/shoulder;
- group shoulder/arm contact;
- linked/crossed arms;
- shared prop contact;
- adult unclothed contact variants as ordinary anatomy/wardrobe scene configurations.

Contact recipes remain anatomical/geometry descriptions. They do not need narrative or erotic labels to
provide segmentation coverage.

## 10. Pair/group pose templates

A multi-person template is a coordinate system plus slot constraints:

```yaml
template_id: duo_side_embrace_001
slots:
  a:
    root_transform: ...
    pose_id: ...
    contact_sites: [right_hand, right_forearm]
  b:
    root_transform: ...
    pose_id: ...
    contact_sites: [left_shoulder, back_upper_torso]
relationships:
  - type: contact
    a_site: right_hand
    b_site: left_shoulder
    distance_mm: [0, 4]
    maximum_penetration_mm: 2
camera_clearance_requirements: ...
```

Character body-shape changes require a contact solver to adjust roots/limbs within bounded tolerances.
If constraints cannot be satisfied, the recipe is rejected or resampled; it is not forced through.

## 11. Contact solver

1. Load normalized slot poses.
2. Apply final body morphs.
3. Compute named contact-site transforms and surface targets.
4. Optimize root translation/rotation and permitted limb joints.
5. Penalize distance from intended contact, interpenetration, joint-limit deviation, foot/support drift,
   and camera-frame violations.
6. Require reciprocal surface proximity and compatible normals.
7. Re-evaluate after clothing/hair simulation.
8. Record final joint/root deltas and contact metrics.

The solver may alter only degrees of freedom declared by the template. Large deviations invalidate the
pose identity and must produce a new recipe tag.

## 12. Occlusion and front/back authority

For two visible persons at a pixel boundary:

- the rasterized instance ID determines visible owner;
- linear depth confirms front/back ordering in a boundary band;
- per-person hidden diagnostic renders identify what was occluded, but do not alter visible truth;
- relationship records use `occludes`, `occluded_by`, or `contact` and must be reciprocal;
- a contact boundary can contain alternating owners due to interlocked limbs; ownership remains
  pixel-exact, not one global person order.

## 13. Person ranking and promotion

The synthetic scene creates at most four intended promoted persons. Rank after rendering using the live
MaskFactory policy: prominence score, bbox/visible area, configured minimum area, deterministic tie-break,
and p0..pN assignment. Scene recipe slot names are not assumed to equal final p-indices. The mapping from
slot to p-index is stored.

If a person falls below minimum prominence unexpectedly:

- adjust camera in a bounded framing retry when the recipe requires promotion;
- otherwise reject/resample;
- never silently package fewer people than declared.

## 14. Multi-person coverage targets

Initial accepted core-corpus distribution:

| Count | Target share |
|---:|---:|
| 1 | 50% |
| 2 | 30% |
| 3 | 12% |
| 4 | 8% |

Within multi-person scenes:

- ≥30% no-contact separated;
- ≥30% overlap without contact;
- ≥40% contact/support, once templates are validated;
- ≥40% include meaningful limb crossing/identity difficulty;
- ≥20% include different apparent scales/depths;
- ≥20% include at least one cropped person while preserving minimum prominence.

Targets are phased: contact/trio/quartet shares stay zero until their technical validation suites pass.

## 15. Multi-person hard cases

- similar clothing/skin/hair between people;
- same character preset with different morph/material, capped to avoid duplicate identity confusion;
- crossed same-side and opposite-side limbs;
- foreground hand over background face/torso;
- long hair crossing another person's silhouette;
- shared loose garment/blanket-like occluder only after object ownership design;
- small background person behind large foreground person;
- partial heads/limbs at image edges;
- seated/standing mixed depth;
- three/four-person contact chains;
- near-symmetric arrangements that stress p-index stability.

## 16. Collision and penetration policy

Distinguish:

- intended contact;
- small cloth/body fit penetration in an exempt region;
- self-intersection;
- cross-person interpenetration;
- support-surface penetration;
- hidden non-visible intersection;
- catastrophic geometry overlap.

Visible cross-person interpenetration beyond template tolerance is a hard reject. Hidden intersections
are still recorded and capped because they can alter shadows/silhouettes. Contact is not simulated by
deep penetration.

## 17. Pose normalization and conversion

- Store canonical bone rotations after application.
- Normalize root translation separately from local pose.
- Identify generation-specific bone mappings.
- Pose converters are explicit dependencies and never assumed perfect.
- Converted poses require joint-limit, foot/hand, and silhouette smoke tests.
- Left/right mirrored variants are generated through a tested mirror transform with bone swaps, not a
  screen-space image flip.

## 18. Pose/scene rejection codes

```text
Q-POSE-001 joint_limit_exceeded
Q-POSE-002 invalid_property_value
Q-POSE-003 self_intersection_excessive
Q-POSE-004 support_contact_missing
Q-POSE-005 root_transform_unexpected
Q-POSE-006 hand_or_foot_articulation_invalid
Q-POSE-007 conversion_mismatch
Q-MULTI-001 intended_contact_unsatisfied
Q-MULTI-002 cross_person_interpenetration
Q-MULTI-003 person_below_prominence
Q-MULTI-004 instance_ownership_overlap
Q-MULTI-005 contact_nonreciprocal
Q-MULTI-006 slot_person_count_mismatch
Q-MULTI-007 identity_ambiguous_or_duplicate
Q-MULTI-008 camera_or_crop_contract_failed
```

## 19. Acceptance tests

- every pose family can produce a valid solo fixture;
- partial pose composition is deterministic;
- character-left/right remains correct in asymmetric poses;
- all declared contacts meet distance/normal/penetration constraints;
- all intended support points touch the support surface;
- global instance map is exclusive;
- per-instance other-person masks are exact;
- contact/occlusion records are reciprocal;
- all people/variants share one image-family split group;
- p0..pN assignment is deterministic from rendered prominence.
