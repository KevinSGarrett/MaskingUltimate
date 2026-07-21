# Combined Master Blueprint

## 1. Program objective

Build a fully controlled, deterministic, coverage-driven DAZ scene factory that can operate unattended
after Kevin acquires and installs assets. It must transform installed adult-human content into
strictly validated RGB-plus-annotation packages, integrate them into MaskFactory as train-only weighted
pseudo-labels, and prove any benefit on untouched real human-anchor holdouts before a model can be
promoted.

## 2. Program phases at a glance

| Phase | Outcome | Hard exit condition |
|---|---|---|
| D0 Profile | frozen private/local operating and acquisition profile | profile/config assertions pass |
| D1 Storage/runtime | `F:\DAZ` tree, pinned DAZ runtime, isolated worker | doctor and backup/restore pass |
| D2 Asset registry | product/file/dependency inventory | schema-valid registry and negative fixtures |
| D3 Asset qualification | eligible asset pools | load/fit/render smoke certificates |
| D4 Figure mapping | validated Genesis 9 v1 mapping | golden fixtures and pixel checks pass |
| D5 Scene engine | deterministic solo recipes and assembly | 100-scene replayable pilot |
| D6 Annotation engine | synchronized RGB and exact maps | all pass validators and edge fixtures pass |
| D7 Multi-person | controlled 2–4-person scenes | QC-035/036 analogues and identity tests pass |
| D8 Diversity scale | coverage-driven broad corpus | target matrix and asset-dominance checks pass |
| D9 MaskFactory integration | schema-valid synthetic packages | S00/package/dataset CI passes |
| D10 Training experiment | matched real-only vs mixed ablation | 30% cap and real-holdout evaluation pass |
| D11 Activation | unattended scheduled generation | runbook, incident, rollback, and acceptance pass |
| D12 Expansion | v2, G8/8.1, complex hair/cloth/props | separate mapping and promotion requirements |

## 3. Phase D0 — freeze the operating profile

1. Record `private_personal_noncommercial`, local-only operation, and `distribution_allowed: false`.
2. Record that asset acquisition and any spending remain Kevin-controlled.
3. Record that generation, mask creation, dataset construction, training, and local evaluation may run
   autonomously after assets are installed and technically qualified.
4. Prohibit public hosting, dataset/model distribution, commercial deployment, and automatic purchase.
5. Add configuration and tests proving those boundaries cannot drift accidentally.

## 4. Phase D1 — establish the controlled environment

1. Create the exact `F:\DAZ` structure in document 11.
2. Configure DAZ Install Manager downloads to `F:\DAZ\02_installers\dim_downloads` and content to
   `F:\DAZ\03_content\libraries\MaskFactory_DAZ_Library`.
3. Map only registered content roots into the dedicated DAZ automation instance.
4. Pin DAZ Studio version, install source, executable hash, plugin inventory, renderer, NVIDIA driver,
   and runtime settings.
5. Create an isolated application instance named `MaskFactoryDAZ` with no default scene, no prompts,
   fixed render directories, fixed content roots, and offline generation defaults.
6. Deploy the script bundle by hash and run a no-content hello-world job.
7. Implement a machine GPU lease shared with MaskFactory. DAZ must wait rather than compete with
   training or inference.
8. Measure F-drive throughput/free space and configure soft/hard capacity thresholds.
9. Run backup and restore of configuration, registry, mappings, and one synthetic fixture.

## 5. Phase D2 — build the asset registry

1. Parse DIM install manifests and enumerate CMS products and content roots.
2. Hash user-facing asset files and supporting dependencies.
3. Create stable product and asset IDs independent of filenames.
4. Classify asset type, content type, figure generation, compatibility bases, dependencies, vendor/PA,
   product page, install date, version, and source evidence.
5. Add operating metadata: source/product identity, allowed-use evidence, distribution false,
   permitted local operation, scan date, and registry version.
6. Detect missing, duplicate, shadowed, modified, and orphan files.
7. Require curated overrides where metadata is insufficient. An override is explicit, reviewed, and
   hash-bound; it is not a free-text bypass.
8. Generate an immutable registry snapshot before every dataset freeze.

## 6. Phase D3 — qualify assets automatically

Each candidate asset is tested in a job-private clean scene:

1. load the required base figure;
2. load or apply the candidate;
3. verify dependencies and texture resolution;
4. inspect scene nodes, types, skeleton/follow target, geometry, surfaces, and asset sources;
5. apply representative neutral and stress poses;
6. fit clothing/hair and run permitted simulation profiles;
7. render a low-cost preview and relevant ID pass;
8. check logs for prompts, missing files, load errors, NaNs, renderer fallback, or unsupported plugins;
9. compare geometry/asset fingerprints with declared compatibility;
10. issue a time-limited smoke certificate or quarantine with a machine-readable reason.

Any asset update invalidates its certificate and all compatibility combinations that depend on it.

## 7. Phase D4 — map Genesis 9 to MaskFactory

1. Freeze the unmodified Genesis 9 base topology fingerprint.
2. Enumerate facets, face groups, material groups, bones, weight information available through the API,
   UV sets, and relevant surface names.
3. Seed a coarse anatomical territory map from surfaces and bone influence.
4. Refine polygon boundaries to every v1 atomic label, including fingers, ears, torso split, breasts,
   pelvis, glutes, knees, wrists, ankles, and feet/toes.
5. Create protected/object/material mappings separately.
6. Render canonical front/back/profile/three-quarter and articulation fixtures.
7. Verify exclusivity, full visible coverage, left/right character perspective, boundary continuity, and
   invariance under approved morph and pose ranges.
8. Freeze a v1 mapping bundle. Build v2 as a separate append-only bundle only after v2 pipeline requirements
   can consume it.
9. Define geograft composition rules and require separate mappings for topology-changing anatomy assets.

## 8. Phase D5 — implement deterministic scene generation

1. Convert MaskFactory coverage deficits into a demand vector.
2. Select a scene recipe family before individual assets.
3. Select compatible assets using allowlists, dependency constraints, recent-use penalties, and
   underrepresented coverage reward.
4. Generate bounded body morphs in correlated spaces rather than independent extremes.
5. Apply the requested adult age-appearance category and compatible body/face variation profile.
6. Apply skin, hair, wardrobe, pose, expression, camera, light, environment, and prop choices.
7. Resolve placement, ground/support contact, framing, collision thresholds, and person prominence.
8. Save the final explicit recipe and scene graph summary.
9. Reject recipes that cannot meet constraints before spending render time.

## 9. Phase D6 — render synchronized truth

For every pristine RGB frame, generate the complete required pass set in document 21. At minimum:

- RGB beauty;
- alpha/person-visible silhouette;
- person-instance ID;
- MaskFactory part ID per person;
- MaskFactory material ID per person;
- object/protected/support IDs;
- linear depth;
- camera-space/world-space normals as diagnostics;
- contact/occlusion relationship metadata;
- visibility counts per person and part;
- optional full-geometry/amodal diagnostic passes in a barred directory.

Label passes use exact IDs, no tone mapping, no denoising, no motion blur, no depth of field, no color
management transformations, and no lossy format. RGB may use realistic render features. All passes use
the same camera, resolution, frame, geometry state, and scene hash.

## 10. Phase D7 — add multi-person scenes

1. Start with separated duos, then depth overlap, contact, trios, and quartets.
2. Assign stable `p0..pN` by the same prominence ranking contract used by MaskFactory.
3. Render one global instance map and one per-instance package view.
4. From each instance's perspective, every other person is protected `other_person` material/part.
5. Compute reciprocal contact and occlusion records from depth and visible boundaries.
6. Ensure no pixel belongs to two promoted instance silhouettes.
7. Group every instance and derived image variant under one `image_id` for dataset splitting.
8. Reject ambiguous reflections, duplicated instances, severe interpenetration, or unsatisfied contact
   recipes.

## 11. Phase D8 — scale breadth without creating bias

The scheduler uses the matrix in documents 16–19. It tracks marginal and pairwise coverage, not merely
scene count. It enforces:

- minimum coverage for body type, adult age band, skin tone, hair, wardrobe, pose, view, camera, light,
  background, visibility, truncation, instance count, anatomy configuration, and interaction;
- pairwise targets for high-risk combinations such as dark skin × hard backlight, long hair × shoulder
  occlusion, hands × body contact, loose clothing × side view, small anatomy × partial visibility,
  multi-person × crossing limbs, and extreme focal length × truncation;
- maximum contribution caps per product, character, texture, hair asset, garment, pose pack, environment,
  and recipe family;
- holdback of some assets and recipe families for synthetic diagnostic sets, while never using those
  diagnostics as real promotion authority.

## 12. Phase D9 — integrate with MaskFactory

1. Version the manifest schemas to support `source_origin: synthetic` and a structured synthetic block.
2. Preserve truth tier as `weighted_pseudo_label`, train partition, configured weight 0.10–0.25.
3. Add the `synthetic_geometry_exact` source attribute without changing certified-gold formulas.
4. Add a DAZ intake adapter that validates the scene package before writing any MaskFactory package.
5. Run strict PNG/map validators and all applicable QC, including multi-person checks.
6. Freeze accepted packages and include complete source/mapping/runtime hashes.
7. Extend coverage reporting with DAZ axes while keeping certified-human coverage separate.
8. Enforce synthetic train-only and maximum 30% at dataset build and training launch.
9. Store bulk data under F and use registered pointers/links without copying DAZ source assets.

## 13. Phase D10 — train and evaluate honestly

Create matched experiments:

- real/certified data only;
- same base plus 10% DAZ;
- same base plus 20% DAZ;
- same base plus 30% DAZ;
- targeted DAZ only for selected hard buckets;
- asset-family and render-style holdout ablations;
- optional other-synthetic-source mixtures.

All candidates use the same real training authority, seeds, schedules, model families, and untouched
real human-anchor holdouts. Promotion requires a material primary win, per-hard-label non-inferiority,
no cross-person/left-right/protected-region regression, stable runtime, complete technical lineage, and tested
rollback. A candidate whose benefit exists only on synthetic diagnostics is rejected.

## 14. Phase D11 — activate unattended operation

Activation requires:

- all technical readiness checks complete;
- seven-day pilot with no unresolved prompt or corrupt package;
- deterministic replay sample;
- capacity and retention proof;
- backup/restore and registry rebuild proof;
- pause/resume, lease expiry, crash, disk-full, GPU contention, and asset-update tests;
- alerts and daily summary;
- one-command disable of DAZ ingestion and one-command rollback of any DAZ-trained model;
- Kevin-approved recurring schedule and resource limits.

## 15. Phase D12 — controlled expansion

Genesis 8/8.1, v2 anatomy, strand-based hair, dynamic cloth, mirrors, transparency, special geografts,
unusual cameras, or higher person counts each enter as a challenger capability. They require their own
mapping, compatibility, QA, throughput, ablation, and rollback evidence. “It loads” is never enough.
