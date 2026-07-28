# Asset Acquisition, Installation, and Catalog Specification

## 1. Division of responsibility

Kevin acquires assets and approves spending. The subsystem does not shop, add items to carts, log in,
accept terms, or initiate paid downloads. Once files are installed or placed in a watched staging area,
everything from discovery through qualification can be autonomous.

## 2. Recommended initial asset portfolio

The first useful pilot should be intentionally small and varied, not a huge unqualified dump:

| Category | Pilot target | Expansion target |
|---|---:|---:|
| Genesis 9 base figures | required base set | one pinned base topology family |
| adult character presets | 12–20 | 100+ with dominance caps |
| body/head morph packs | 2–4 broad packs | diverse controlled packs |
| skin/material sets | 12–20 | 100+ across tone/age/material response |
| hair | 20 | 150+ styles/textures |
| wardrobe complete looks | 20 | 200+ garments/layers |
| poses | 200 unique | 5,000+ normalized poses |
| hand/foot pose subsets | 50 each | 500+ each |
| expressions | 30 | 300+ mild-to-strong |
| cameras | procedural first | asset presets optional |
| lights/HDRIs | 20 | 200+ controlled profiles |
| environments | 10 | 100+ indoor/outdoor |
| props/support surfaces | 30 | 300+ occlusion-relevant |
| approved anatomy/geografts | one per supported configuration | expand only with mappings |

Counts are asset-pool breadth, not required purchases. Free/bundled/user-created content can fill a
category if it passes the same technical tests.

## 3. Acquisition priorities

Prioritize assets that increase a known MaskFactory hard bucket:

1. broad pose libraries with hands/feet visible;
2. diverse adult body and skin variation;
3. hair silhouettes and hair/shoulder/face occlusion;
4. fitted, loose, layered, sheer/lace, glove/sock, and footwear boundaries;
5. chairs, floors, beds, rails, bags, and handheld props that create support/contact;
6. paired/group pose sets that can be normalized into reciprocal contact recipes;
7. environments and lights that diversify contrast and boundary conditions;
8. anatomy assets only when the target ontology/mapping work is ready.

Avoid buying many near-duplicate glamour presets, one-pose variants, or texture recolors before the
coverage report shows a need. Quantity without compatibility and coverage evidence creates storage and
bias, not useful diversity.

## 4. DAZ Install Manager setup

Configure a dedicated account profile or install path:

```text
Download To:
F:\DAZ\02_installers\dim_downloads

Install To:
F:\DAZ\03_content\libraries\MaskFactory_DAZ_Library
```

DAZ Studio's Content Directory Manager must map that same library for the `MaskFactoryDAZ` instance.
The automation instance should not search Kevin's unrelated DAZ libraries unless explicitly registered,
because untracked dependencies destroy reproducibility.

After configuration:

1. save a redacted settings export under `04_runtime\app_profiles\MaskFactoryDAZ`;
2. record the resolved content-directory list through `DzContentMgr`;
3. verify the library appears exactly once;
4. install one base product;
5. reconcile DIM install manifest, filesystem, and CMS product container;
6. uninstall/reinstall the pilot and verify registry transitions.

## 5. Manual package installation

For non-DIM packages:

1. place the untouched archive in `02_installers\manual_packages\incoming`;
2. hash the archive;
3. enumerate its members without extraction;
4. reject absolute paths, `..` traversal, executables/plugins not explicitly approved, and writes outside
   the content root;
5. extract to a job-private staging directory;
6. identify the correct content-root level (`data`, `People`, `Runtime`, etc.);
7. create an install manifest with source archive hash and destination file list;
8. atomically merge into the content library with conflict detection;
9. rescan and smoke-test;
10. retain or delete the archive according to storage policy.

Never resolve a file conflict by silently overwriting a different hash. Record whether the new package
is an update, duplicate, or conflict and require an explicit technical resolution.

## 6. Asset discovery sources

The scanner combines:

- DAZ Install Manager `ManifestFiles`/install manifests;
- DAZ CMS product containers and metadata;
- `DzAssetMgr` content types and compatibility information;
- `DzContentMgr` mapped roots and relative paths;
- filesystem enumeration of supported user-facing presets;
- runtime inspection after load;
- curated overrides for missing/bad metadata.

No single source is trusted alone. The registry records observations and reconciliation state.

## 7. Asset types

Closed initial taxonomy:

```text
figure_base
character_preset
head_morph
body_morph
combined_morph
age_morph
expression
pose_full_body
pose_partial_upper
pose_partial_lower
pose_hand_left
pose_hand_right
pose_foot
material_skin
material_eye
material_makeup
material_body_detail
hair_fitted
hair_prop
facial_hair
wardrobe_top
wardrobe_bottom
wardrobe_one_piece
wardrobe_underwear
wardrobe_swimwear
wardrobe_outerwear
wardrobe_glove
wardrobe_sock
wardrobe_footwear
wardrobe_headwear
accessory_wearable
anatomy_geograft
prop_handheld
prop_occluder
support_surface
environment_indoor
environment_outdoor
backdrop
camera_preset
light_preset
hdri
render_preset
simulation_preset
unknown
```

`unknown` never enters generation. New taxonomy values require schema and classifier tests.

## 8. Figure-generation compatibility

Every asset declares one or more:

```text
genesis9
genesis8_1_female
genesis8_1_male
genesis8_female
genesis8_male
generation_agnostic
unknown
```

Compatibility is based on metadata plus load-time verification. An asset marketed as “universal” is
not generation-agnostic until applied successfully to each target family. Pose converters and wardrobe
autofit are modeled as explicit transformation dependencies with their own version/hash and test result.

## 9. Asset registry record

Minimum fields:

```yaml
schema_version: 1.0.0
asset_id: daz_asset_<hex>
product_id: daz_product_<hex>
relative_path: People/Genesis 9/...
content_root_id: maskfactory_daz_library
file_sha256: <64 hex>
support_files_sha256: <aggregate hash>
asset_type: pose_full_body
content_type_raw: Preset/Pose
figure_generations: [genesis9]
compatibility_bases: [<normalized ids>]
dependencies: [daz_asset_...]
required_plugins: []
character_scope: adult_human
age_appearance_control: false
anatomy_related: false
scene_categories: [clothed, partial_clothing, unclothed]
technical_state: eligible
smoke_certificate_id: smoke_...
mapping_requirement: inherited_base | asset_specific | none
first_seen_at: <timestamp>
last_seen_at: <timestamp>
```

Product/source labels are metadata. Technical eligibility comes from hashes, dependencies,
classification, mapping requirements, and smoke results.

## 10. Runtime enrichment

Static metadata is enriched by a scripted inspection job that records:

- nodes created/modified;
- source asset URI for each node;
- skeleton/follow target;
- bone vocabulary;
- geometry vertex/facet/material/face-group counts;
- topology changes;
- material names/shader classes/opacity maps;
- morph/property names and groups changed;
- render visibility and simulation state;
- fitted target and autofit result;
- missing-file and log messages;
- unexpected dialogs/plugins;
- load time and memory/VRAM behavior.

The enrichment record is hash-bound to the asset and runtime.

## 11. Incremental scanning

1. Snapshot DIM manifests and content-root metadata.
2. Fast-scan file path, size, mtime, and file ID.
3. Hash only new/changed files; periodic full verification detects mtime spoof/drift.
4. Reconcile adds, deletes, changes, duplicates, and moves.
5. Invalidate affected smoke certificates, mappings, compatibility edges, recipes, and queued jobs.
6. Write the complete new registry to a temporary file/database.
7. Validate schema and graph integrity.
8. Atomically activate and preserve the prior snapshot.
9. Emit a human-readable diff.

## 12. Logical asset pools

The registry creates queryable pools, not copied folders:

- `g9_adult_base_figures`;
- `g9_adult_character_presets`;
- `g9_bounded_body_morphs`;
- `g9_age_appearance_profiles`;
- `g9_skin_materials_by_tone_band`;
- `g9_hair_by_length_texture_construction`;
- `g9_wardrobe_by_region_layer_fit`;
- `g9_poses_by_taxonomy`;
- `multi_person_pose_templates`;
- `lights_by_profile`;
- `environments_by_context_complexity`;
- `props_by_occlusion_support_role`.

Pool membership is generated from exact registry fields and versioned overrides.

## 13. Catalog reports

The daily/scan report includes:

- products/assets by type and generation;
- eligible/pending/quarantined/retired counts;
- missing dependencies and conflicts;
- unclassified assets;
- assets changed since last snapshot;
- coverage capabilities added/removed;
- adult-policy exceptions;
- disk usage by product/category;
- top asset families by recent scene selection;
- smoke certificates expiring or invalidated.

## 14. Completion criteria

Cataloging is complete for a snapshot when:

- every supported file is attached to one content root and stable asset ID;
- all duplicates/conflicts are explicit;
- every asset has a closed taxonomy value;
- every generation-specific asset has a compatibility decision;
- dependency graph resolves or the asset is ineligible;
- body, face, age-appearance, and anatomy-related controls are classified by technical function;
- eligible assets have current smoke certificates;
- rebuild yields the same canonical snapshot hash.
