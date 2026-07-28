# `F:\DAZ` Folder and Storage Specification

## 1. Storage authority

`F:\DAZ` is the canonical root for every DAZ-specific asset, installer, runtime copy, registry,
mapping, scene recipe, render, annotation pass, package, cache, log, report, backup, and synthetic
dataset artifact. The MaskFactory repository on C stores code, schemas, small checked-in configuration,
tests, and documentation only.

Bulk files must not be duplicated onto C merely to satisfy an existing relative path. Integration uses
logical roots, controlled directory junctions only where unavoidable, or package adapters that read F
and emit registered references. A junction must be declared in the path registry and verified not to
escape `F:\DAZ`.

## 2. Exact top-level tree

```text
F:\DAZ\
  00_control\
    README.md
    root_identity.json
    operating_profile.json
    storage_policy.yaml
    path_registry.json
    maintenance.lock
  01_source_records\
    products\
    install_manifests\
    file_inventories\
    dependency_snapshots\
  02_installers\
    dim_downloads\
    manual_packages\
      _incoming_unsorted\
      _needs_classification\
      _ready_for_install\
      _installed_archives\
      _failed_install\
      asset_dropzone\
        genesis_9\
        genesis_8_1\
        genesis_8\
        generation_neutral\
        other_or_unknown\
    application_installers\
    plugin_installers\
    checksums\
  03_content\
    libraries\
      MaskFactory_DAZ_Library\
      MaskFactory_User_Library\
    cloud_cache_disabled\
    content_overrides\
  04_runtime\
    scripts\
      active\
      versions\
    app_profiles\
      MaskFactoryDAZ\
    render_profiles\
    plugin_inventory\
    runtime_snapshots\
  05_registry\
    live\
      daz_assets.sqlite
      asset_registry.json
      dependency_graph.json
      compatibility_graph.json
      product_registry.json
    snapshots\
    diffs\
    overrides\
    rebuild_evidence\
  06_asset_staging\
    discovered\
    inspect_pending\
    smoke_pending\
    mapping_pending\
    eligible\
    retired\
  07_mappings\
    genesis9\
      body_parts_v1\
      body_parts_v2\
    genesis8_1\
      body_parts_v1\
      body_parts_v2\
    genesis8\
      body_parts_v1\
      body_parts_v2\
    geografts\
    wardrobe_transfer\
    hair\
    golden_fixtures\
    revoked\
  08_asset_tests\
    jobs\
    previews\
    certificates\
    failures\
    quarantine\
    retest\
  09_generation\
    policies\
    coverage_demands\
    sampling_plans\
    recipe_templates\
    scene_recipes\
    family_manifests\
  10_queue\
    queue.sqlite
    pending\
    leased\
    running\
    retry\
    failed\
    complete\
    leases\
    heartbeats\
  11_scene_state\
    partial\
    assembled\
    snapshots\
    debug_duf\
    rejected\
  12_renders\
    pristine\
    derived\
    thumbnails\
    rejected\
  13_annotations\
    instance_id\
    part_id\
    material_id\
    protected_id\
    depth\
    normals\
    alpha\
    relationships\
    amodal_diagnostic\
    body_part_levels\
      01_major\
      02_sub\
      03_micro\
      04_nano\
  14_scene_packages\
    draft\
    validating\
    accepted\
    rejected\
    revoked\
  15_datasets\
    builds\
    cards\
    manifests\
    sample_weights\
    synthetic_diagnostics\
  16_maskfactory_exports\
    intake_ready\
    ingested\
    rejected\
    pointers\
  17_logs\
    worker\
    daz_studio\
    render\
    validation\
    scheduler\
    audit\
    incidents\
  18_reports\
    daily\
    weekly\
    coverage\
    assets\
    mappings\
    storage\
    training\
  19_cache\
    compiled_shaders\
    textures\
    simulations\
    geometry\
    thumbnails\
    decoder\
  20_tmp\
    worker\
    decode\
    package\
    downloads\
  21_backups\
    control\
    registries\
    mappings\
    recipes\
    package_metadata\
    restore_tests\
  22_dvc\
    cache\
    local_remote\
    locks\
  23_exports\
    reports_redacted\
    support_bundles_redacted\
  99_archive\
    runtime_versions\
    registry_snapshots\
    mappings\
    corpus_versions\
```

## 3. DAZ content-library rule

Do not manually reorganize files inside
`F:\DAZ\03_content\libraries\MaskFactory_DAZ_Library`. DAZ content uses internal relative paths and
metadata; moving individual `/data`, `/People`, `/Runtime`, texture, preset, or support files can break
dependencies. Asset type organization is a logical view in the registry, not a physical recopy of the
content library.

Manual download archives are placed intact under
`F:\DAZ\02_installers\manual_packages\asset_dropzone\<generation>\<primary-category>`. The installer
then extracts them into `MaskFactory_DAZ_Library` while preserving their internal paths. Content created
by Kevin or MaskFactory is written to `MaskFactory_User_Library` using DAZ-native relative paths.

The only allowed content-library writers are:

- DAZ Install Manager configured for this exact library;
- a recorded manual installer/extractor whose complete file list is captured before and after;
- an explicit content repair tool operating from a verified manifest.

The generation worker has read-only intent toward installed content. User-generated presets, mapping
materials, and debug scenes go to the runtime/mapping/scene areas, never into vendor product folders.

## 4. Directory semantics

### `00_control`

Contains the root UUID, schema versions, path registry, operating profile, storage thresholds, and the
maintenance lock. `root_identity.json` prevents accidentally pointing the worker at another `F:\DAZ`.
It stores a random root UUID, creation date, expected volume serial, and canonical path. A volume serial
change is a warning; a root UUID mismatch is a block.

### `01_source_records`

Stores product identifiers, install manifests, file inventories, and dependency snapshots needed for
inventory, update detection, and replay. Asset file hashes and stable product identifiers are the
technical authority.

### `02_installers`

Separates DAZ Install Manager downloads, manually obtained packages, application installers, and plugin
installers. Installer retention is configurable. Before deletion, the system records filename, size,
SHA-256, product/package ID, and whether the product can be redownloaded.

### `03_content`

Holds installed vendor content. `content_overrides` contains small local metadata corrections, never
modified vendor files. `cloud_cache_disabled` is a sentinel confirming the automation path does not
depend on DAZ Connect cloud retrieval during jobs.

### `04_runtime`

Holds deployed DAZ Script versions and application-instance profiles. `active` is an atomic pointer or
copy to one versioned script bundle. Every job records its script bundle hash; an in-place edit is
forbidden.

### `05_registry`

The SQLite registry is the operational index; snapshot JSON is the portable authority. Registry rebuild
from DIM manifests, filesystem hashes, CMS metadata, and overrides must produce a deterministic
snapshot. Databases use WAL, one writer, and read-only reporting connections.

### `06_asset_staging` and `08_asset_tests`

Staging directories contain references/manifests, not duplicate assets. Qualification state is recorded
in the registry. Test previews and logs are disposable only after their certificate, exact input hashes,
and failure evidence have been preserved.

### `07_mappings`

Mapping bundles are immutable and versioned. The active mapping is selected in configuration by mapping
ID/hash, not overwritten. Revoked mappings stay available for tracing historical packages.

### `09_generation` and `10_queue`

Plans and recipes are immutable inputs. Queue subdirectories are operational mirrors for inspection;
`queue.sqlite` plus per-job manifests are authoritative. A file may appear in only one live state.

### `11_scene_state`

`.duf` scenes are optional debugging/replay artifacts, not the primary scene description. Default
retention keeps `.duf` only for failures, mapping golden fixtures, selected audits, and samples whose
recipe cannot yet reproduce without a scene snapshot.

### `12_renders` and `13_annotations`

`pristine` contains beauty renders before degradation. `derived` contains deterministic transformed
variants. Annotation directories may be job-local behind the scenes; top-level names define data class
for retention and audits. Lossless indexed maps are never stored only inside a layered proprietary
format.

### `14_scene_packages`

An accepted package is immutable. Revocation moves logical state and writes a revocation record; it does
not rewrite historical evidence. Physical moves are optional and must preserve all relative paths or use
an index pointer.

### `15_datasets` and `16_maskfactory_exports`

Dataset builds are immutable and contain only training-eligible packaged renders, not DAZ source assets.
Exports use copied/linked RGB and maps plus manifests. Links are resolved and verified before any
portable operation.

### `19_cache` and `20_tmp`

Everything here is reconstructable. Cache keys include exact inputs/runtime. `20_tmp` can be purged only
when no live lease references it. Temporary files use `.partial` names and are never scanned as complete.

### `21_backups` and `22_dvc`

The local DVC remote is optional until MaskFactory adopts it. No cloud remote is created or used without
Kevin's spending approval. Backups prioritize control metadata, mappings, recipes, and package manifests;
bulk renders may use a separate retention tier.

## 5. Scene-directory contract

Each scene uses a shard to prevent huge directory fan-out:

```text
12_renders\pristine\ab\cd\scene_abcd1234ef567890\
13_annotations\part_id\ab\cd\scene_abcd1234ef567890\
14_scene_packages\accepted\ab\cd\scene_abcd1234ef567890\
```

Scene IDs are content-independent opaque identifiers such as `scene_<16 lowercase hex>`. Family IDs
group all pristine/derived variants of one geometry/camera arrangement. MaskFactory `image_id` is
derived deterministically from the accepted RGB parent hash using the existing intake convention.

## 6. Filename contract

- ASCII lowercase snake case for generated filenames.
- Vendor filenames are preserved inside the content library.
- No scene output includes a product or character marketing name.
- Frame zero is `f0000`; still images still use a frame token for future extensibility.
- Required render names:

```text
rgb_pristine_f0000.png
alpha_visible_f0000.png
instance_id_f0000.png
part_id_global_f0000.png
material_id_global_f0000.png
protected_id_f0000.png
depth_linear_f0000.exr
normal_camera_f0000.exr
relationships_f0000.json
scene_recipe.json
worker_result.json
scene_manifest.json
hashes.json
```

Per-instance decoded packages use `p0`, `p1`, `p2`, `p3` consistent with MaskFactory.

## 7. Capacity thresholds

At blueprint time F has approximately 361.6 GiB free. Initial explicit thresholds are:

| Threshold | Free space | Action |
|---|---:|---|
| healthy | ≥150 GiB | normal generation |
| soft | <150 GiB | stop new large plans; finish leased jobs; run retention plan |
| hard | <100 GiB | drain queue; no new render leases; preserve metadata |
| emergency | <60 GiB | terminate before next pass; prevent database/checkpoint writes; incident alert |

These are conservative pilot values. After 1,000 accepted scenes, calculate p50/p95 bytes per scene for
each render profile and replace thresholds only through a versioned storage-policy change. The worker
reserves estimated output space before leasing a job:

```text
required_reservation = max(profile_p95_bytes, profile_estimate_bytes) * 1.25
```

## 8. Retention classes

| Class | Contents | Default retention |
|---|---|---|
| R0 permanent | control, registry snapshots used by datasets, active/revoked mappings, dataset cards, accepted manifests/hashes | permanent |
| R1 reproducibility | scene recipes, worker results, selected `.duf`, runtime snapshots, product/asset snapshot IDs | permanent while any dependent model exists |
| R2 training source | accepted RGB and required annotation maps | through dependent dataset/model lifecycle plus rollback window |
| R3 diagnostics | depth, normals, extra canvases, debug panels | 90 days unless selected for golden/audit |
| R4 failures | failed recipes, logs, minimal previews | 30 days; permanent for novel incident signatures |
| R5 cache | shaders, texture cache, simulations, decoded intermediates | LRU; safe purge outside live leases |
| R6 temporary | partial renders and packaging scratch | purge after 24 hours if no live lease |
| R7 installers | downloaded packages | retain by storage policy; preserve checksums/manifest before purge |

Retention never deletes the only active mapping, registry snapshot, recipe, dataset manifest, or evidence
needed to reproduce a currently promoted model.

## 9. Backup plan

### Daily

- `00_control`, live registry plus snapshot, active mappings, queue metadata, accepted package manifests,
  and active configuration.

### Weekly

- all registry snapshots/diffs, mapping versions, recipe families, accepted recipes, runtime snapshots,
  dataset cards/manifests, and redacted reports.

### Corpus backup

Bulk RGB/maps are backed up by immutable dataset version rather than by ever-changing render folders.
If storage is insufficient for two complete local copies, record the limitation and keep the source
recipe plus assets/runtime/mapping identities; do not pretend replay is guaranteed if an asset version
can no longer be recovered.

### Restore test

Quarterly, restore to `F:\DAZ\21_backups\restore_tests\<timestamp>` and prove:

1. configuration loads;
2. registry snapshot validates;
3. mapping bundle validates;
4. one accepted scene package verifies;
5. one recipe semantic-pass replay matches;
6. dataset card/source hashes resolve.

## 10. Permissions and exclusions

- Kevin account: full control.
- DAZ worker identity: read content; read/write runtime job, queue, render, annotation, package, cache,
  temporary, and log locations.
- Training process: read accepted packages/datasets; no write to content or mappings.
- Reporting process: read snapshots and reports; no access to credentials.
- Git ignore and pre-commit scanning cover `F:\DAZ`, `.duf`, DAZ installer types, common texture/mesh
  extensions when outside approved test fixtures, and absolute private paths.

## 11. Storage acceptance tests

- root identity mismatch blocks;
- path traversal and junction escape block;
- two workers cannot hold the maintenance lock;
- soft/hard/emergency thresholds trigger exact actions;
- retention dry-run is deterministic and never proposes R0 deletion;
- live leases protect temporary data;
- backup restore passes from a clean target;
- rebuilding the registry does not depend on deleted cache;
- accepted package verification succeeds after directory sharding and archival.
