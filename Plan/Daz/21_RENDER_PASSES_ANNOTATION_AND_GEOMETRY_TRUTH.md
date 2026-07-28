# Render Passes, Annotation, and Geometry Truth

## 1. Objective

For every frozen DAZ scene, produce one photographic-style RGB image and a synchronized set of
machine-exact annotation products. Every product must describe the same evaluated geometry, transforms,
camera, crop, visibility state, and frame. Annotation passes are authoritative only for visible
synthetic pixels and the declared ontology version.

## 2. Immutable scene-state rule

The worker completes scene assembly, simulation, subdivision selection, smoothing, geograft attachment,
camera framing, and geometry evaluation before any output begins. It then computes a
`scene_state_sha256` from:

- node hierarchy and stable node IDs;
- geometry/topology fingerprints;
- final world transforms and joint values;
- final morph/controller values;
- material assignments and opacity parameters;
- camera matrices, focal settings, resolution, crop, and pixel aspect;
- light/environment state;
- visibility flags;
- renderer and pass-profile versions.

Every pass repeats this hash in its sidecar. Any scene mutation between passes invalidates the complete
render set.

## 3. Required output profiles

| Profile | Outputs | Use |
|---|---|---|
| `engineering_minimal` | preview RGB, instance, PART, MATERIAL | asset/mapping smoke |
| `training_standard` | pristine RGB, instance, PART, MATERIAL, protected, depth, normals, alpha | normal corpus |
| `training_relationship` | standard plus contact, front-owner, boundary pairs | multi-person/contact corpus |
| `diagnostic_full` | relationship plus surface, facet, node, mapping confidence, amodal geometry | mapping/debug only |
| `rgb_variant` | derived RGB only, linked to one unchanged semantic set | domain randomization |

A derived RGB variant never causes semantic passes to be rerendered unless geometry, visibility, crop,
or camera changes.

## 4. Output contract

| Output | Encoding | Background | Train eligible |
|---|---|---:|---|
| RGB pristine | lossless RGB PNG or EXR | rendered environment | yes |
| person instance | 16-bit single-channel PNG | 0 | yes |
| PART ID | 16-bit single-channel PNG | 0 | yes |
| MATERIAL ID | 16-bit single-channel PNG | 0 | yes |
| protected/other ownership | 16-bit single-channel PNG | 0 | yes |
| coverage alpha | 16-bit linear PNG | 0 | boundary support |
| depth | 32-bit float EXR | +Inf or declared sentinel | diagnostic/input optional |
| camera-space normal | float EXR | 0,0,0 | diagnostic/input optional |
| front-owner ID | 16-bit PNG | 0 | relationship training optional |
| contact pair raster | packed 32-bit or two 16-bit channels | 0 | relationship training optional |
| surface/facet/node IDs | integer EXR or lossless packed PNG | 0 | diagnostic only |
| amodal geometry | separate diagnostic tree | 0 | no |

All integer maps use exact nearest-neighbor decoding. JPEG, palette quantization, color management,
tone mapping, denoising, bloom, motion blur, depth of field, and lossy resizing are prohibited on ID
products.

## 5. ID namespaces

### 5.1 Person instances

- 0 is background.
- 1 maps to p0, 2 to p1, 3 to p2, and 4 to p3.
- p-index assignment follows MaskFactory prominence after the final camera is known.
- The recipe stores construction order separately from promoted p-index.
- Hair, anatomy geografts, and worn garments inherit the owning person's instance ID.

### 5.2 PART

- PART uses the active MaskFactory ontology IDs exactly.
- A v1 render accepts IDs 0–55 only.
- A v2 render accepts IDs 0–65 only and is produced only by an explicitly v2 job.
- Background is 0 only where 0 is the canonical background value; body labels use their canonical
  indexed values without local remapping.
- The decoder uses the canonical ontology snapshot recorded by hash.

### 5.3 MATERIAL

MATERIAL is orthogonal to PART. Initial closed classes are:

| ID | Class |
|---:|---|
| 0 | background |
| 1 | visible skin |
| 2 | hair/facial hair |
| 3 | clothing fabric |
| 4 | footwear |
| 5 | accessory/jewelry |
| 6 | anatomy geograft visible skin |
| 7 | prop/support |
| 8 | transparent or mixed-coverage material |

The final implementation must reconcile these draft values with MaskFactory's active material schema
and freeze one versioned table; it must not duplicate a conflicting list.

## 6. Exact indexed-pass strategy

Preferred strategy:

1. retain the frozen beauty scene;
2. save original material/visibility assignments in memory;
3. assign emission/unlit ID shaders or renderer-supported material-ID values;
4. disable environment contribution, reflections, shadows, transmission, tone mapping, denoising, and
   post effects for the indexed pass;
5. render at the exact target camera and dimensions;
6. restore and verify the original scene state;
7. decode IDs and compare declared versus observed values.

If Iray cannot guarantee exact integer output for a pass, use a dedicated scriptable raster route or
multi-pass binary visibility renders. The selected route must pass exhaustive ID-codec fixtures before
corpus use.

## 7. Boundary and antialiasing convention

Beauty RGB may use normal antialiasing. Indexed maps use either:

- exact single-sample pixel-center ownership; or
- supersampled coverage followed by deterministic ownership selection.

The chosen global convention records:

- sample grid;
- alpha threshold;
- tie-break rule;
- transparent-surface handling;
- downsample filter;
- edge uncertainty radius.

Recommended training export is one hard integer map plus a 16-bit coverage-alpha map. Hard ownership is
selected by maximum visible coverage; ties use frontmost depth, then stable node ID. No blended label
colors appear in the hard map.

## 8. Person and geometry ownership

Each renderable facet belongs to exactly one scene node and, where applicable, one promoted person.
Ownership resolution order:

1. base figure ownership;
2. attached anatomy/geograft ownership;
3. fitted wardrobe ownership;
4. parented hair/accessory ownership;
5. explicitly assigned prop/support ownership;
6. background/environment.

Unowned visible geometry is a validation error. A visible pixel cannot be assigned to two promoted
people.

## 9. PART mapping rules

- Base-figure facets use the frozen topology mapping bundle.
- Geografts use their composition mapping and replace covered base facets where applicable.
- Hair uses the ontology's hair territory and the owning instance.
- Clothing uses visible body-territory transfer: the garment surface receives the anatomical territory
  that it visibly covers while MATERIAL remains clothing.
- Accessories follow the configured protected/accessory contract and do not invent anatomy.
- Props and support surfaces are not body PART pixels.
- Hidden body geometry never leaks through a visible garment, person, hair strand, or opaque prop.

## 10. Clothing territory transfer

The mapping compiler may combine:

- garment rig-weight dominance;
- nearest valid body surface in posed space;
- ray projection along garment inward normals;
- UV or template correspondence;
- manually frozen asset overrides;
- region continuity regularization.

At render time, each garment facet already has a frozen PART territory. Per-pixel nearest-body guessing
is not allowed because it changes under contact and can jump to another person. Layered garments use
only the front visible layer; covered layers remain absent from visible truth.

## 11. Hair and transparency

Hair assets are classified as polygonal, transmapped cards, strand-based, fibermesh, or mixed.

- Polygonal/fibermesh hair follows ordinary depth visibility.
- Transmapped cards use evaluated opacity, not the card rectangle.
- Strand hair uses renderer coverage or an equivalent exact opacity pass.
- Alpha below the configured visibility threshold is background.
- Mixed pixels retain coverage alpha and one deterministic hard owner.
- Hair casting a shadow does not make the shadow pixel hair.
- Facial hair belongs to hair MATERIAL and the ontology territory defined by the active mapping.

Each hair certificate records its supported renderer/pass route and alpha threshold.

## 12. Anatomy configurations

Adult male and adult female anatomy are normal mapped geometry configurations. For every visible
anatomy pixel:

- the owning person instance is explicit;
- the active ontology determines the PART ID;
- MATERIAL records visible skin/anatomy material;
- base/geograft overlap uses the composition map;
- v1 output never emits v2-only atomic IDs;
- hidden anatomy remains absent from visible maps;
- clothed coverage follows the visible garment surface.

## 13. Depth and normals

Depth is linear camera-space distance in meters or centimeters with the unit declared. It must not use
device-depth nonlinear encoding. Normals are camera-space, right-handed, unit-length vectors after all
deformation and subdivision. Both record:

- coordinate convention;
- unit and background sentinel;
- near/far clip;
- subdivision level;
- camera matrices;
- finite-value statistics.

Depth discontinuities are compared with instance and PART boundaries during QA.

## 14. Visibility and amodal diagnostics

Visible truth is derived from the final z-resolved image. Optional amodal outputs may record complete
geometric extent or occluded facets, but they live under `13_annotations\amodal_diagnostic`, carry
`train_eligible: false`, and are absent from normal training exports. Amodal data is useful for:

- measuring how much of each body region is visible;
- choosing occlusion difficulty;
- diagnosing pose/camera failures;
- computing front/back relationships;
- targeting scenes where rare labels become visible.

## 15. Contact and occlusion relationships

The geometry analyzer emits per-person and per-pair records:

~~~yaml
pair: [p0, p1]
minimum_surface_distance_mm: 0.4
contact: true
contact_regions:
  - {a_part: left_hand, b_part: torso_front, area_mm2: 420}
visible_boundary_pixels: 1830
front_owner_counts: {p0: 1200, p1: 630}
occlusion_direction: mixed
depth_order_confidence: 0.98
~~~

Contact is a 3D distance/penetration decision; visual overlap without surface proximity is occlusion,
not contact. Relationship rasters are derived from stable instance IDs and depth, never from RGB
inference.

## 16. Multi-person package derivation

One scene produces:

- a shared RGB and shared indexed pass set;
- one scene manifest;
- one promoted-person view per p-index;
- per-instance binary masks derived from the shared instance map;
- per-person PART/MATERIAL maps masked by ownership;
- other-person/protected masks derived from all non-target instances;
- one common `image_id` and `scene_family_id`.

Per-person derivation is deterministic and cannot rerender or change shared geometry.

## 17. Derived RGB variants

Allowed post-render variants include versioned compression, sensor noise, color response, white balance,
gamma, resize, crop, and blur only when:

- the geometric transform is applied identically to every associated hard/coverage map;
- lossy effects are applied to RGB only;
- the pristine parent remains addressable;
- variant family grouping prevents split leakage;
- transforms and seeds are fully recorded.

Geometry-changing edits, generative replacement, background removal, or independent RGB warping require
a new source/annotation design and are outside this pass contract.

## 18. Scene output layout

~~~text
scene_<id>\
  manifest.json
  recipe.json
  runtime_snapshot.json
  scene_state.json
  rgb\pristine.png
  rgb\variants\<variant-id>.png
  ids\instance_u16.png
  ids\part_u16.png
  ids\material_u16.png
  ids\protected_u16.png
  coverage\alpha_u16.png
  geometry\depth.exr
  geometry\normals.exr
  relationships\pairs.json
  relationships\front_owner_u16.png
  diagnostic\surface_id.*
  diagnostic\facet_id.*
  diagnostic\amodal\*
  evidence\pass_hashes.json
  evidence\decoder_report.json
~~~

## 19. Pass validation summary

Before acceptance:

- every mandatory file exists and hashes;
- dimensions, camera, crop, and scene-state hashes agree;
- decoded values are a subset of declared tables;
- all visible person pixels have one instance, PART, and MATERIAL owner;
- all target instances are nonempty and meet configured prominence/visibility;
- instance masks are mutually exclusive;
- RGB alpha/geometry silhouette and annotation edges align;
- depth and normals are finite where expected;
- relationship records agree with instance/depth geometry;
- repeated semantic render is byte-identical;
- no diagnostic/amodal file is marked train eligible.

## 20. Completion evidence

The render subsystem is complete when golden fixtures cover base skin, every major PART boundary,
male/female anatomy, tight/loose/layered clothing, each hair construction, transparent edges, props,
support contact, and one through four people; every fixture replays; and corrupted/aliased/misaligned
passes are detected by seeded negative tests.
