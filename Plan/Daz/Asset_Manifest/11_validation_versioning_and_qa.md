# Validation, Versioning, Deduplication, and QA

## Validation layers

1. **Serialization:** UTF-8 YAML parses; timestamps, IDs, hashes, and numeric types are canonical.
2. **Schema:** Draft 2020-12 validation passes with no ignored unknown fields.
3. **Vocabulary:** class, role, state, relationship, side, method, generation, and subtype values exist.
4. **Taxonomy:** each taxon exists, declared level equals taxonomy level, parents are acyclic, and sides agree.
5. **Referential integrity:** every product/package/file/asset/component/property/dependency ID reference
   resolves exactly once; IDs are unique across the manifest.
6. **Filesystem:** declared present files remain within their content root, exist, match size and SHA-256,
   and case normalization does not create collisions.
7. **DSON:** all resolvable URLs resolve; unresolved references are enumerated; source-to-support graph closes.
8. **Runtime:** before/after snapshots are comparable, selection fixture is recorded, and change attribution
   does not include residue from another asset.
9. **Semantic:** primary class is singular, dropzone path exists, body evidence supports associations, and
   ontology label IDs/names match the declared version.
10. **Operational:** rescan is idempotent, update is atomic, old revision is retained, indexes match manifests.

## Severity

Errors block `qualified`: schema failure, duplicate ID, wrong/missing required hash, escaping path, corrupt
archive, unresolved required dependency, incompatible figure, load/render failure, or invalid ontology
label. Warnings preserve usability but require visibility: optional dependency missing, weak semantic
inference, unused files, cosmetic render warning, or untested secondary renderer.

## Version and update policy

- Manifest schema uses semantic versions. Additive optional fields are minor; changed meaning/requiredness
  is major; documentation-only corrections are patch.
- Product/package/file/asset versions are independent from schema versions.
- A source update is scanned as a new package/archive. Diff added, removed, changed, and moved files by
  hashes and logical URIs. Never edit history to make an update appear like the original.
- Revisions are immutable snapshots. The current pointer changes only after full validation succeeds.
- Retirement preserves all records and records replacement, reason, timestamp, and last known locations.

## Deduplication

Exact duplicate means identical SHA-256 bytes. Semantic duplicate means different bytes but the same
resolved asset URI/function and requires runtime confirmation. Filename equality is only a candidate.
Keep package membership for every occurrence. Do not delete duplicates automatically; select a canonical
occurrence by active package version and content-root priority while retaining links to all occurrences.

## Minimum test matrix per function

| Function | Required fixture and checks |
|---|---|
| figure/character | clean load, node/rig/geometry inventory, materials, neutral render |
| morph/slider | correct figure, limits/default, probe values, geometry diff, controller graph |
| material/texture | correct surfaces, all channel files resolve, render, opacity/transmission check |
| hair/wardrobe | fit/follow, adjustment properties, pose range, collision/dForce if declared, render |
| pose/expression | exact changed bones/properties, left/right, restore default, range violation check |
| camera/light/environment | property diff, renderer compatibility, deterministic reference render |
| prop/accessory/geograft | created nodes, attachment, scale, geometry/materials, seam/contact behavior |
| script/plugin/tool | entry point, arguments, application/plugin dependency, side-effect diff, exit status |

## Acceptance evidence

For each qualified asset retain archive inventory, install diff, static parse output, CMS query output when
available, runtime before/after/diff, DAZ log excerpt, dependency resolution, smoke render, simulation log
when applicable, validator report, and second-scan diff. Evidence filenames are content-addressed; manifest
references are relative to the asset inspection directory.

## Corpus-level audits

Nightly: changed/missing file hashes, broken references, ID uniqueness, index drift. Weekly: rescan a rotating
sample, rerun runtime smokes for changed application/plugins, measure unknown fields and weak inference.
After DAZ/application/plugin or ontology changes: invalidate affected certificates, schedule targeted
reinspection, and do not rewrite unaffected records.
