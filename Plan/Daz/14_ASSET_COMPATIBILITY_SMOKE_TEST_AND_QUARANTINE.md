# Asset Compatibility, Smoke Test, and Quarantine Specification

## 1. Purpose

Installed assets are untrusted until they prove they can load, combine, render, reproduce, and respect
the scene/mapping contracts. Qualification is automatic and asset-specific. A product containing ten
presets can have eight eligible assets and two quarantined assets.

## 2. Compatibility graph

The graph has typed nodes and edges:

### Nodes

- product;
- asset;
- figure generation/base topology;
- plugin/runtime;
- mapping bundle;
- simulation profile;
- render profile.

### Edges

```text
requires
compatible_with
incompatible_with
fits_to
applies_to
converts_via
changes_topology
uses_mapping
tested_with
supersedes
```

Every edge has source (`metadata`, `runtime_observed`, or `curated_override`), confidence, evidence hash,
and tested runtime. A `compatible_with` edge from metadata is provisional until runtime smoke passes.

## 3. Universal qualification sequence

1. Validate asset/product registry records.
2. Resolve all dependencies and required plugins.
3. Select the correct clean base fixture.
4. Launch a job-private DAZ scene.
5. Capture baseline scene graph and memory.
6. Load/apply the asset.
7. Capture resulting nodes, properties, geometry, materials, and log deltas.
8. Run type-specific tests.
9. Render a low-cost beauty preview, silhouette, instance ID, and relevant mapping pass.
10. Run validators.
11. Repeat once from a new process to check reproducibility.
12. Issue certificate, quarantine, or manual-classification-needed state.

## 4. Type-specific smoke tests

### Base figure

- loads into an empty scene;
- is a recognized adult figure generation;
- skeleton/bone vocabulary matches declared family;
- base topology fingerprint matches a supported mapping target;
- neutral pose and transforms are canonical;
- surfaces/materials resolve;
- renders without missing assets;
- does not execute unexpected scripts/dialogs.

### Character/body/head morph

- applies to the intended base;
- changed properties are enumerated;
- all directly and indirectly changed controller values are enumerated;
- values remain finite and within declared range;
- topology is unchanged unless explicitly mapped;
- joint centers/rig adjustments remain valid;
- neutral, arms-up, seated, and crouched stress poses render;
- no self-intersection above the coarse threshold caused solely by the morph.

### Skin/material

- applies to correct surfaces;
- all maps resolve inside registered content roots;
- shader is supported by selected beauty renderer;
- opacity/displacement/subsurface values are finite;
- no surface becomes unintentionally invisible;
- ID override pass can replace or tag materials without permanent mutation;
- representative light profiles render without NaNs/black output.

### Hair

- attaches/fits to intended figure;
- remains visible in render;
- alpha/transmission maps resolve;
- silhouette/alpha pass matches beauty coverage within tolerance;
- head/shoulder penetration remains below policy;
- approved extreme head/neck poses do not detach catastrophically;
- strand-based/dynamic hair is marked advanced and requires deterministic cache tests.

### Wardrobe

- fits correct figure and follow target;
- all expected pieces load;
- material/opacity maps resolve;
- neutral plus articulation stress poses are tested;
- geometry explosion, detached vertices, inverted normals, and extreme penetration block;
- clothing-territory transfer produces complete mapped coverage;
- layered garments have stable z-order;
- dynamic items bake reproducibly under the selected simulation profile.

### Pose

- applies to declared figure without changing shape/material unexpectedly;
- root translation/orientation behavior is classified;
- joint rotations are finite and within expanded anatomical limits;
- left/right hand and foot identity remains correct;
- ground/contact points are detected;
- self-intersection score is recorded;
- full-body, partial-body, and paired poses are normalized to a canonical representation.

### Expression

- changes only allowed head/face controls;
- does not activate age/character/body morphs unexpectedly;
- keeps eyes/mouth geometry finite;
- supports mild, medium, and strong bounded values;
- does not break head/ear/hair mapping.

### Anatomy/geograft

- follows intended base figure;
- replaces/hides base polygons as expected;
- topology/geograft fingerprint is stable;
- approved v2 mapping exists;
- seams have no gaps/overlaps beyond tolerance;
- material and part IDs remain exclusive;
- v1 fallback mapping is defined without emitting v2 IDs.

### Camera/light/environment/prop

- loads without replacing unrelated scene state unless classified as a full-scene preset;
- camera focal/perspective/DOF properties are readable and bounded;
- lights have finite intensity/color/transform and supported types;
- environments do not introduce undeclared people or mirrors in the initial lane;
- props have stable geometry/material IDs and an occlusion/support classification;
- no asset silently changes renderer, output path, dimensions, or tone mapping.

## 5. Compatibility combination tests

Individual eligibility is necessary but insufficient. The system tests representative combinations:

- character × body morph pack;
- character × skin material;
- body shape extremes × hair;
- body shape extremes × each wardrobe fit class;
- wardrobe × pose stress bucket;
- layered garment combinations;
- anatomy geograft × skin material;
- hair × headwear;
- pose × support surface;
- paired pose × both figure configurations;
- environment × light profile;
- camera profile × environment scale.

The registry stores tested ranges rather than claiming every Cartesian combination. Untested
combinations may run only in exploratory mode and must pass full scene validation before acceptance.

## 6. Quantitative checks

Initial thresholds are conservative and versioned:

| Check | Pilot threshold |
|---|---:|
| missing referenced files | 0 |
| unknown external content roots | 0 |
| NaN/Inf property or geometry values | 0 |
| empty expected render | 0 |
| figure outside frame in fixture | 0 |
| garment uncovered mapped pixels | ≤0.1% garment pixels |
| gross body/garment penetration | ≤1.0% visible garment pixels, asset-class adjusted |
| hair/body penetration | ≤2.0% visible hair pixels, with scalp attachment exemptions |
| repeated semantic-pass hash drift | 0 |
| unexpected dialog/fatal log | 0 |
| renderer/profile mutation | 0 |

Penetration metrics are diagnostic approximations. Contact-intended garments and hair roots use named
exemption zones; no global tolerance hides arbitrary failures.

## 7. Smoke certificate

```yaml
schema_version: 1.0.0
certificate_id: daz_smoke_<hex>
asset_id: daz_asset_<hex>
asset_sha256: <hash>
dependency_snapshot_sha256: <hash>
runtime_snapshot_sha256: <hash>
script_bundle_sha256: <hash>
fixture_ids: [g9_neutral, g9_arms_up, g9_seated]
checks:
  load: pass
  missing_files: pass
  geometry: pass
  render: pass
  mapping: pass
  repeatability: pass
eligible_generations: [genesis9]
eligible_scene_categories: [clothed, partial_clothing, unclothed]
limitations: []
created_at: <timestamp>
expires_on_change: true
```

Certificates are not time-expired by a calendar alone; they become stale when any bound input changes or
the periodic runtime review requires retest.

## 8. Quarantine taxonomy

```text
Q-ASSET-001 unknown_asset_type
Q-ASSET-002 missing_dependency
Q-ASSET-003 file_hash_conflict
Q-ASSET-004 unsupported_generation
Q-ASSET-005 required_plugin_missing
Q-ASSET-006 external_path_reference
Q-ASSET-007 missing_texture
Q-ASSET-008 load_error
Q-ASSET-009 unexpected_dialog
Q-ASSET-010 renderer_profile_mutation
Q-ASSET-011 topology_changed_unmapped
Q-ASSET-012 geometry_nan_or_explosion
Q-ASSET-013 excessive_intersection
Q-ASSET-014 fit_or_follow_failure
Q-ASSET-015 mapping_incomplete
Q-ASSET-016 alpha_mask_unreliable
Q-ASSET-017 simulation_nondeterministic
Q-ASSET-018 unsupported_character_configuration
Q-ASSET-019 anatomy_configuration_unknown
Q-ASSET-020 repeatability_failure
Q-ASSET-021 timeout_or_crash
Q-ASSET-022 duplicate_or_shadow_conflict
```

Each record names the exact asset/dependencies/runtime, scene fixture, log excerpt hash, output evidence,
first/last occurrence, retry count, and recommended action.

## 9. Retry and retest

- Transient GPU/process errors: one clean-process retry.
- Missing dependency: no retry until registry changes.
- Texture/external path: retry after content repair.
- Geometry/fit/mapping failure: retry only with a new asset-specific rule or mapping version.
- Nondeterministic simulation: three-seed/two-process investigation; otherwise exclude simulation path.
- Popup: no automated click; quarantine until the asset can run with a documented suppression or is
  excluded.
- Asset update: invalidate and retest automatically.

Repeated retries never convert failure into eligibility without a changed, recorded condition.

## 10. Quarantine isolation

Quarantined assets remain installed if removal would break other products, but the registry excludes
them from every eligible pool. Dependency propagation marks downstream assets `blocked_by_dependency`
without mislabeling them as independently broken. A scene referencing a newly quarantined asset cannot
be leased.

## 11. Qualification reports

Reports show:

- eligible rate by asset type/generation/product;
- failure counts by reason;
- slowest and highest-memory assets;
- wardrobe/hair penetration distributions;
- unresolved unknown types/age controls;
- compatibility edges added/removed;
- certificate invalidations since last scan;
- asset pools currently too small for coverage targets.

## 12. Acceptance

An asset is eligible only when its registry record, dependencies, runtime observation, type-specific
checks, required mapping, repeatability, and smoke certificate all pass. Eligibility is scoped: an asset
may be eligible for Genesis 9 static scenes but ineligible for dynamic simulation or another generation.
