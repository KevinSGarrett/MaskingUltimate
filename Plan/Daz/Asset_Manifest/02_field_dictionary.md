# Exhaustive Field Dictionary

`schemas/asset_manifest.schema.json` is normative. This dictionary explains how to populate its groups.

## Header and identity

- `schema_version`: exact contract version; semantic version.
- `manifest_id`: immutable manifest identity, independent of revision.
- `manifest_revision`: monotonically increasing integer.
- `record_state`: lifecycle value from the controlled vocabulary.
- `created_at`, `updated_at`: UTC RFC 3339 timestamps.
- `created_by`, `updated_by`: agent/tool/human identifier, never a secret.
- `canonical_asset_id`: primary user-facing asset represented by the bundle.
- `supersedes`, `superseded_by`: revision/entity links, not filenames.

## Product, package, and acquisition record

`product` records store stable product ID, store/source name, store product ID/GUID, product title,
edition/version, creators, product page, acquired timestamp, local installer receipt/reference, declared
content types, descriptions, tags, and expected dependencies. `package` stores Install Manager GlobalID,
package name/version, platform, installer/archive filename, archive SHA-256/size, compression, download
classification path, extraction status, and every archive member. Product and package identity must not
be collapsed because one product can contain several packages.

## Location and file inventory

Each `files[]` record contains: stable file ID; package/archive member; content root ID; source archive
path; member path; installed relative and absolute path; canonical comparison path; DAZ logical URI/DSON
URL when present; role; extension; detected format/MIME/signature; SHA-256; size; timestamps; compression;
existence; primary/support/generated status; owner IDs; reference edges; duplicate cluster; and resolution
errors. Roles include user preset, asset definition, geometry, morph delta, UV, rig, material, shader,
texture channel, thumbnail, metadata, script, plugin, documentation, and unknown.

## Asset definition

Each `assets[]` record stores asset ID, source file, DSON asset ID/URI/type, internal name, label,
description, asset author/revision/modified date, DAZ content type/category/tags, compatibility base/filter,
generation, declared function, placement category, load mode, scene-selection requirements, and static
parse findings. `primary_class` is singular; `secondary_classes` may be multiple.

## Runtime components

`components[]` describes every created or modified node, figure, bone, object, geometry, shape, modifier,
material, renderer object, camera, light, environment, or simulation object. Store scene path, persistent
asset URI, label/name/type, parent and follow target, skeleton, visibility/selectability, transforms,
bounding box, vertex/edge/facet counts, UV sets, face groups, material slots, modifiers, topology signature,
created-versus-modified action, and source asset/file.

## Properties, sliders, and adjusters

`properties[]` is mandatory when runtime inspection exposes channels. Record property ID; owner component;
asset URI; internal name; display label; full property/group path; presentation/region; value type; units;
minimum, maximum, default, current, step/sensitivity; clamped/display-percent flags; hidden, locked, private,
keyable, animatable, user-property, auto-follow, and rig flags; morph subtype (`shape`, `expression`, `JCM`,
`MCM`, `corrective`, `HD`, `pose_control`, `material_control`, or other); formulas/controllers; inputs and
outputs; affected nodes/bones/materials/vertices; body associations; side; intended use; conflict group;
safe sampling range; and inspection evidence.

## Specialized capability profiles

- `geometry_profile`: topology hash, subdivision/HD, graft seams, hidden polygons, weight maps, UVs.
- `rig_profile`: skeleton, bones, aliases, rotation order/limits, IK, ERC/controller relationships.
- `material_profile`: material slots, shader, channels, texture files, color space, opacity/transparency.
- `morph_profile`: deltas, affected vertices, auto-follow, controller graph, compatible topology.
- `pose_profile`: full/partial region, bones/channels affected, contact intent, mirroring, root motion.
- `hair_profile`: fitted/prop, scalp base, bones, dForce, strand/mesh type, length and coverage.
- `wardrobe_profile`: garment class/layers, fit targets, covered body regions, dForce, adjustment morphs.
- `camera_profile`: projection, focal length, sensor, aperture, clipping, DOF, framing intent.
- `light_profile`: type, geometry, photometrics, color/temperature, shadow, renderer compatibility.
- `environment_profile`: indoor/outdoor/backdrop/HDRI, scale, floor/support, emissive elements.
- `prop_profile`: handheld/wearable/occluder/support role, attachment nodes, scale, contact regions.
- `simulation_profile`: engine, modifiers, collision targets, initialization and cache requirements.
- `script_profile`: entry point, arguments, menus, API dependencies, files touched, automation suitability.

Absent profiles are omitted. A profile may not be populated by filename guess alone.

## Body and ontology associations

Each association stores `taxon_id`, level, side, relationship (`targets`, `changes_shape`, `covers`,
`attaches_to`, `poses`, `occludes`, `textures`, `creates`, or `supports`), coverage fraction/range when
measurable, evidence method/reference, confidence, and review state. `maskfactory_mappings` additionally
store ontology version, label ID/name, mapping relationship, mapping status, and evidence. Many-to-many
links are expected.

## Dependency and compatibility graph

Every edge stores ID, source entity, target kind and locator, relation (`requires`, `recommends`,
`conflicts`, `supersedes`, `fits_to`, `autofits_to`, `loads_with`, `converted_from`, `uses_texture`, or
`controlled_by`), version constraint, required flag, resolution state, resolved target, detection method,
and evidence. Compatibility test results store figure, generation, renderer, application/plugin versions,
operation, seed/fixture, outcome, warnings/errors, timing, memory/VRAM, screenshots/logs, and certificate ID.

## Search, change, and evidence

`search` provides normalized tokens, synonyms, aliases, creators, product IDs, categories, body taxa,
generations, file extensions, and free-text summary. `technical_lineage` records tools and source evidence
that produced each revision. `conflicts`, `unknowns`, and `validation` preserve unresolved facts and all
schema/path/hash/reference/runtime checks. Never erase earlier inspection results; append and supersede.
