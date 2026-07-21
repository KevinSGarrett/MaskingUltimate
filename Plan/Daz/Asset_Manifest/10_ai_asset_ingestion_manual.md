# AI Asset Ingestion and Cataloging Manual

This is the mandatory procedure for any AI or automation adding a DAZ download. Never infer completion
from a filename, never flatten a vendor package, and never overwrite an older manifest revision.

## Phase A — isolate and inventory

1. Create an intake job ID and an evidence directory. Work on one immutable archive hash at a time.
2. Hash the untouched archive with SHA-256; record bytes, filename, timestamps, compression, source/product
   identifiers available locally, and collision with known hashes.
3. List every archive member without executing scripts or loading plugins. Normalize paths for comparison,
   reject traversal/absolute members, and record original spelling.
4. Parse `Manifest.dsx`, supplement metadata, thumbnails, and directory conventions. Record raw values.
5. Detect likely generation and primary asset class using multiple signals: metadata, `People/...` path,
   `data/...` references, DSON type, compatibility base, and product description. Confidence below 0.80 or
   conflicting generations goes to `other_or_unknown`; do not guess.
6. Choose the deepest matching existing directory beneath
   `asset_dropzone/<generation>/`. A multi-purpose product is stored intact in one primary directory and
   receives secondary classes in the manifest. Never duplicate the archive into several categories.
7. Move/copy placement is outside a catalog-only dry run. When placement is authorized, verify the hash
   after the operation and record the old and new location.

## Phase B — install without reorganizing

1. Snapshot the native content root by normalized relative path, size, mtime, and SHA-256.
2. Install into `F:\DAZ\03_content\libraries\MaskFactory_DAZ_Library` using the package's native paths.
3. Snapshot again. The set difference is the candidate installed-file inventory; hash all new/changed
   files. Never relocate `data`, `People`, `Runtime`, texture, metadata, or script members by category.
4. Join archive members to installed files by normalized suffix, hash, size, and package manifest. Preserve
   one-to-many and unresolved joins. Equal hashes form a duplicate cluster, not automatic deletion.
5. Assign file roles by parsed content/signature first and path/extension second. `.duf` can be many asset
   types; extension alone is insufficient.

## Phase C — static enrichment

1. Decode JSON or zlib-compressed DSON safely. Record file version and `asset_info`.
2. Enumerate every asset library entry and scene entry, retaining IDs, URLs, names, labels, types, parents,
   formulas, modifiers, geometry, UV, material, image, and channel references.
3. Build the outbound reference graph; resolve DSON URLs against content roots. Record missing, ambiguous,
   case-mismatched, and external references individually.
4. Query DAZ CMS/asset manager when available for product GUID/name, artists, descriptions, content types,
   categories, compatibility bases/filters, and file-to-product membership. Preserve raw CMS fields.
5. Create one `asset` record per loadable preset/definition, not merely one per product.

## Phase D — runtime differential inspection

Use a clean DAZ Studio process and a known fixture for each supported figure generation.

1. Record application, plugin, renderer, content-root, and inspector versions.
2. Save a complete pre-load scene snapshot: nodes, objects, geometry, shapes, modifiers, materials,
   properties, skeletons, selection, render settings, and file references.
3. Load or apply exactly one user-facing asset with the required selection context. Capture dialogs, log
   lines, duration, memory, missing files, and error state.
4. Save an equivalent post-load snapshot and compute created/modified/removed/reference-only components.
5. For every property, enumerate its asset URI, name/label/group/presentation/region, type, limits,
   default/current/sensitivity, all flags, controllers/formulas, and affected entities. Reset the scene
   between assets so one product cannot contaminate another result.
6. For morphs, sample default and bounded probe values, compare geometry/topology/bounds, enumerate affected
   vertices where accessible, and determine safe sampling range. Never test beyond declared limits in the
   autonomous corpus until a separate stress test passes.
7. For materials, diff every surface/channel/image; for poses, diff every bone/channel; for wardrobe/hair,
   test fit/follow target, adjustment morphs, materials, collision and simulation; for cameras/lights,
   diff physical/render properties; for scripts, record arguments, scene/files/settings changed.
8. Perform a tiny deterministic render and, where applicable, simulation smoke test. Save logs and images
   by content hash. Unattended dialogs, missing dependencies, corrupt geometry, or unexplained changes make
   the qualification result fail or warn; they do not erase the catalog record.

## Phase E — semantic and body classification

1. Select one primary asset class and all factual secondary classes.
2. Associate every component/property with the narrowest supported body taxon plus its ancestors. State the
   relationship: a breast morph `changes_shape`; a bra `covers`; a hand pose `poses`; hair `attaches_to`
   scalp and may `occlude` face/neck.
3. Use `runtime_api`/geometry evidence whenever possible. Name-only mappings are `machine_inferred` and
   confidence-capped at 0.79.
4. Record left/right only when the actual asset, property, bone, polygon group, or runtime change proves it.
5. Add MaskFactory ontology mapping separately. A nano taxon without an active label is
   `descriptive_only`, not a new class. Record v2 labels as `inactive_future` until the project activates v2.

## Phase F — finalize and publish

1. Resolve all internal IDs and references; regenerate search tokens from canonical data.
2. Validate schema, vocabulary, taxonomy, uniqueness, reference integrity, paths, hashes, and evidence.
3. Re-run the scan. The second scan must be idempotent except for timestamps and appended inspection IDs.
4. Write the canonical YAML to `F:\DAZ\05_registry\manifests\assets\<asset_id>.yaml` atomically, retain the
   prior revision, update product/package/file indexes, and write a content-hashed snapshot.
5. Set `qualified` only when install, dependency, load, runtime-diff, render, and required simulation checks
   pass. Otherwise set the truthful state and continue cataloging other assets.

## Category examples

- A G9 body slider pack: `genesis_9/01_body_modifiers_and_morphs/<deepest-region>`.
- A fitted hairstyle: `genesis_9/03_hair/<deepest-style/function>`.
- A garment: `genesis_9/04_clothing_and_wardrobe/<garment-class>`.
- A multi-purpose character bundle: primary directory is the bundle's dominant loadable function; record
  character, morph, material, hair, and wardrobe child assets separately.
- A pose usable across generations: use `generation_neutral` only after runtime tests prove that claim.

## Stop conditions

Stop mutation, preserve evidence, and mark incomplete when archive identity changes during processing,
path traversal is found, installation target is outside the declared library, a required dependency is
ambiguous, DAZ presents an unattended decision dialog, or a post-install hash cannot be reconciled.
