# Automated Validation, QA, and Rejection

## 1. Acceptance philosophy

Synthetic geometry makes exact labels possible only when scene construction, semantic mapping, render
passes, decoding, and packaging are all correct. The validator therefore attempts to disprove each
sample. Throughput never converts an unknown or failed technical check into acceptance.

## 2. Validation layers

| Layer | Scope | Typical disposition |
|---|---|---|
| V0 contract | schema, versions, required fields | reject recipe/package |
| V1 asset | hashes, dependencies, compatibility certificates | hold or quarantine asset |
| V2 recipe | deterministic choices, ranges, resolvability | reject/regenerate |
| V3 assembly | scene nodes, transforms, fit, framing | bounded repair/reject |
| V4 geometry | topology, intersections, contact, visibility | repair/reject/quarantine combination |
| V5 render | runtime result, pass set, dimensions, hashes | rerender/reject |
| V6 semantic | instance/PART/MATERIAL/protected authority | reject/quarantine mapping |
| V7 multi-person | identity, exclusivity, relationship consistency | reject |
| V8 package | file map, lineage, MaskFactory contract | reject |
| V9 corpus | duplication, dominance, coverage, partition | exclude/rebalance |

V0–V8 apply per scene. V9 applies before dataset freeze.

## 3. Result model

Every check returns:

~~~yaml
validator_id: DAZ-V6-014
validator_version: 1.2.0
entity_id: daz_scene_<id>
status: pass | fail | warn | not_applicable
reason_code: <closed code>
metric: <name or null>
observed: <number/object/null>
expected: <constraint>
evidence_paths: [<relative paths>]
retryability: none | same_recipe | adjusted_recipe | asset_retest
affected_asset_ids: []
affected_mapping_ids: []
~~~

Warnings are informative and never stand in for required passes. A package declares its required
validator set by version.

## 4. Recipe validation

Check before DAZ launch:

- schema version and canonical JSON;
- ontology and render profile are known;
- master and named-stream seeds exist;
- every referenced asset resolves in the same registry snapshot;
- figure/pose/morph/material/hair/wardrobe/anatomy compatibility edges exist;
- every required mapping bundle resolves;
- final numeric ranges and joint values are finite;
- character count is 1–4 and configuration matrix is valid;
- scene-family and variant IDs are present;
- expected storage/GPU profile fits current limits;
- no unknown keys silently alter behavior.

Invalid recipes are not automatically “fixed” by deleting unknown fields. The planner regenerates from a
valid demand.

## 5. Scene-assembly validation

After DAZ evaluates the scene:

- the default scene is empty before loading;
- expected figures and attachments exist exactly once;
- no unexpected renderable nodes remain;
- asset readback IDs match the recipe;
- morph/controller and joint readbacks match resolved values;
- auto-follow and controller side effects are enumerated;
- all required textures resolve;
- geometry and transforms are finite;
- figure scale, world bounds, and support contacts are plausible;
- camera sees the intended people;
- p-index prominence can be calculated;
- runtime warnings/errors match a closed accepted list.

## 6. Geometry checks

### 6.1 Topology

- base and geograft fingerprints match mapping keys;
- subdivision and smoothing follow the pass profile;
- facet counts and material groups remain expected;
- no NaN/Inf vertex exists;
- no unrecognized topology-changing modifier is active.

### 6.2 Collision and penetration

Use broad-phase bounding volumes followed by triangle or signed-distance checks for relevant pairs.
Report penetration volume/depth by:

- self body/body;
- hair/body;
- garment/body;
- garment/garment;
- person/person;
- person/prop/support.

Configured intentional contact uses a small allowed tolerance; large penetration, inverted cloth,
exploded geometry, or body parts passing through another person rejects the scene.

### 6.3 Framing

Compare target and observed:

- number of visible people;
- person area and prominence;
- full/three-quarter/portrait/close framing;
- intended crop/truncation regions;
- body-region visibility;
- off-frame percentage;
- camera clipping;
- horizon/support alignment where relevant.

## 7. Render integrity

- worker terminal record exists and is written after outputs;
- process exit and terminal status agree;
- pass file count and byte size are plausible;
- every file decodes in the declared format;
- no renderer fallback occurred;
- camera, dimensions, crop, and scene-state hashes agree;
- RGB is not blank, solid error color, checkerboard, or missing-texture output;
- exposure/luminance and saturation fall inside broad profile-specific bounds;
- semantic replay hash matches;
- partial directories never enter accepted storage.

## 8. Pixel-level semantic checks

Let I be instance, P PART, M MATERIAL, R protected, and A coverage alpha.

Required invariants:

- I=0 implies no promoted-person P/M ownership.
- I>0 implies exactly one declared promoted person.
- Every I>0 hard pixel has one allowed P and M.
- Values outside the active code tables are zero-count.
- Per-person masks are pairwise disjoint.
- Union of per-person masks equals I>0.
- P/M values follow per-asset mapping applicability.
- Hair MATERIAL pixels use owning instance and allowed hair PART behavior.
- Clothing MATERIAL pixels have valid transferred PART territory.
- Protected and target ownership follow the per-instance package view.
- Hard-edge pixels have corresponding A coverage under the configured tolerance.

Every invariant is implemented as a vectorized full-image check, not a random sample.

## 9. Boundary alignment

Compare RGB/alpha/ID silhouettes using:

- distance-transform edge discrepancy;
- boundary precision/recall within 1, 2, and 3 pixels;
- transparent-edge coverage error;
- depth-discontinuity agreement;
- connected-component correspondence;
- targeted crop inspection for thin structures.

Thresholds are calibrated from known-correct render fixtures. They are pass-profile-specific and never
relaxed merely to accept more scenes.

## 10. Semantic plausibility

Exact colors can still encode a wrong semantic mapping. Therefore:

- mapped PARTs must be connected or have expected component bounds;
- left/right regions must agree with skeleton ownership under all camera views;
- parent/descendant body-region adjacency must follow the ontology graph;
- fingers/toes must connect to their correct hand/foot;
- torso/front/back transitions must agree with mapped orientation;
- body territory on garments must remain locally continuous;
- v2 unions reconstructed from atomics must match the declared derived regions;
- per-label pixel areas must be plausible for the pose/visibility metadata.

Golden fixtures and deliberate mapping swaps prove these checks detect semantic errors.

## 11. Multi-person validation

- promoted count equals visible expected count;
- every p-index has one nonempty connected ownership set, allowing legitimate separated hair/clothing
  components;
- no visible pixel belongs to two people;
- prominent ordering is deterministic;
- contact pairs are reciprocal;
- occlusion order agrees with depth around shared boundaries;
- crossed limbs preserve skeleton-derived owner;
- target/other-person views exactly complement each other;
- shared RGB and pass hashes are identical across derived person packages;
- every scene-derived item uses the same image/split group.

These checks mirror MaskFactory QC-035/QC-036 intent for synthetic packages.

## 12. Duplicate and dominance checks

At package/corpus level calculate:

- exact RGB/pass hash duplicates;
- pHash and embedding near duplicates;
- repeated scene recipe families;
- asset/preset/outfit/environment frequency;
- pose-vector and camera-vector proximity;
- background and lighting repetition;
- character “look” fingerprint repetition.

Exact semantic duplicates with only irrelevant metadata changes retain one representative. RGB
degradation variants stay grouped and are capped per pristine parent.

## 13. Bounded autonomous repair

Allowed repair attempts are deterministic and reason-specific:

| Failure | Repair |
|---|---|
| subject slightly outside frame | recenter/adjust distance within recipe bounds |
| camera clip | adjust near/far plane |
| minor ground offset | support-contact translation |
| minor garment settle issue | rerun pinned simulation/cache once |
| mild hair/garment penetration | configured smoothing/fit adjustment |
| unintended near-contact | small placement separation |
| transient render failure | clean-worker rerender |
| coverage deficit after rejection | resample a new compatible asset/pose |

Repair produces a new recipe revision, records the parent and delta, and reruns every downstream check.
It cannot change ontology, mapping, label tables, truth tier, training weight, or required validators.

## 14. Non-repairable failures

Reject immediately for:

- unknown IDs or ID aliasing;
- missing/incompatible mapping;
- topology fingerprint mismatch;
- cross-person ownership ambiguity;
- geometry/pass camera mismatch;
- unexplained missing person or body region;
- hidden geometry labeled visible;
- nondeterministic semantic replay;
- corrupted/incomplete outputs;
- unresolved asset dependency;
- package hash mismatch.

Repeated asset-specific failure moves the asset or combination to technical quarantine.

## 15. Retry budgets

Default maximums:

| Retry class | Maximum |
|---|---:|
| same-recipe clean rerender | 1 |
| deterministic camera/support correction | 2 |
| cloth/hair settle | 1 |
| asset-combination replacement | 3 |
| full recipe regeneration for one demand | 5 |

Budgets are per demand and reason family. Exhaustion yields an honest coverage deficit rather than an
infinite queue.

## 16. Rejection and quarantine codes

~~~text
RECIPE_*       invalid/unresolvable deterministic input
ASSEMBLY_*     missing/unexpected node or readback mismatch
GEOMETRY_*     topology, NaN, collision, fit, framing
RENDER_*       process, renderer, file, scene-state mismatch
ID_*           codec, unknown value, ownership, completeness
SEMANTIC_*     ontology, left/right, adjacency, mapping
MULTI_*        p-index, exclusivity, contact, bleed
PACKAGE_*      schema, hash, lineage, split, truth contract
RESOURCE_*     disk, GPU, timeout, drive availability
ASSET_*        dependency, compatibility, repeatability
~~~

Each code has one documented owner, retry class, severity, and evidence set.

## 17. Acceptance certificate

An accepted scene certificate includes:

- scene/package/recipe/registry/runtime/mapping hashes;
- validator-set version;
- full pass/fail/warn counts;
- every measured threshold and observed value;
- repair history;
- semantic replay hash;
- package file-map hash;
- creation timestamp and worker identity;
- train eligibility and source-lineage declaration.

Acceptance is valid only for the bound hashes. Any mapped input change creates a new certificate.

## 18. Sampling feedback

The validator feeds structured outcomes to the planner:

- failure rate by asset and combination;
- rejection cost by scene family;
- label visibility actually achieved;
- underfilled target cells;
- common geometry/camera failure regions;
- asset-specific restrictions learned from evidence.

This feedback changes future selection probability but never edits historical recipes.

## 19. QA dashboards

Report:

- accepted/rejected/retried/quarantined by reason;
- first-pass and eventual acceptance;
- semantic error counts (target is zero accepted);
- boundary metrics by asset/hair/wardrobe/render profile;
- multi-person identity metrics;
- replay pass rate;
- time and storage spent on rejected scenes;
- top failing assets and combinations;
- coverage gained per render-hour and GiB.

## 20. Completion criteria

- Every validator has positive, boundary, and seeded negative fixtures.
- Full-image semantic invariants run on every accepted scene.
- Repair is deterministic, bounded, lineage-linked, and followed by full revalidation.
- Quarantine can be reproduced, explained, retested, and cleared by new evidence.
- One hundred accepted pilot scenes pass a second independent verification run.
- Deliberate ID alias, left/right swap, cross-person bleed, pass misalignment, hidden-label leak,
  topology drift, and partial-output defects are all detected.
