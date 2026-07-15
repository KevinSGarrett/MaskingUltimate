# Manifest System Blueprint

## 1. Purpose

The catalog must answer, without opening DAZ Studio: what was downloaded; which product and package it
belongs to; where every member and installed file is; what each file does; which user-facing assets it
defines; what a preset creates or changes; every slider/adjuster it exposes; what geometry, rig,
materials, textures, poses, cameras, lights, or scripts it affects; which body regions it concerns at
major, sub, micro, and nano resolution; what it depends on; which figures it supports; whether it loads,
fits, simulates, and renders; and how it maps to the current MaskFactory ontology.

## 2. Normalized entity model

One YAML manifest is an auditable bundle containing linked entities:

| Entity | Meaning | Stable identity basis |
|---|---|---|
| product | Commercial/free product concept | store + store product ID, else source URL/name hash |
| package | One downloadable installer/archive | product ID + package/global ID + archive hash |
| archive_member | A path inside an archive | package ID + normalized member path + content hash |
| installed_file | A materialized file in a content root | content-root ID + relative path + content hash |
| asset | A user-loadable DUF/DSF/preset/script/resource | installed-file ID + DSON asset URI or file locator |
| component | Node/object/geometry/shape/modifier/material created or changed | asset ID + runtime locator |
| property | Slider, adjuster, switch, channel, controller, or morph | component ID + property asset URI/path |
| body_association | Semantic effect on an anatomical region | entity ID + body taxon + relationship |
| dependency | Required/recommended/conflicting product, file, plugin, or figure | source + target + constraint |
| inspection | Immutable discovery/load/render/simulation observation | entity + tool version + timestamp + evidence hash |

Entities are embedded for portability but each has its own stable ID. Implementations may normalize them
into database tables without changing meaning.

## 3. Identity rules

- IDs are lowercase ASCII and immutable after publication.
- Prefixes are `prd_`, `pkg_`, `arc_`, `fil_`, `ast_`, `cmp_`, `prp_`, `dep_`, and `ins_`.
- Prefer an authoritative DAZ GUID or asset URI. Otherwise derive SHA-256 over the documented canonical
  identity tuple and use the first 24 hexadecimal characters.
- Rename/move events create a new location occurrence, not a new content identity when SHA-256 is equal.
- Changed bytes create a new file revision linked through `supersedes`/`superseded_by`.
- Never use a display name, filename alone, or array position as identity.

## 4. Four independent classification axes

1. **Asset function:** figure, morph, material, hair, wardrobe, pose, expression, camera, light,
   environment, prop, scene, render setting, simulation resource, script/plugin, compatibility tool,
   documentation/support, or unknown.
2. **Placement taxonomy:** exact relative directory below the appropriate generation root in the 401-path
   asset dropzone. This classifies the intact downloaded package only.
3. **Body taxonomy:** zero or more stable `body.*` identifiers at major/sub/micro/nano level, with side,
   effect, coverage, confidence, and evidence.
4. **Mask ontology mapping:** zero or more versioned MaskFactory label references with relationship
   (`exact`, `contains`, `contained_by`, `overlaps`, `derived`, or `none`). Body taxonomy never creates a
   trainable class by implication.

## 5. Manifest lifecycle

`discovered -> hashed -> classified -> installed -> static_inspected -> runtime_inspected ->
qualified`, with `quarantined`, `incomplete`, `superseded`, and `retired` side states. A state transition
requires an inspection record. Unknown values remain `unknown`; they are not guessed.

## 6. Source layers and precedence

For conflicting facts, retain every observation and resolve the canonical field by this order:

1. Runtime DAZ Studio API observation of the loaded asset.
2. Parsed DSON/DUF/DSF content and resolved DAZ URI graph.
3. Install Manager `Manifest.dsx` and package metadata.
4. DAZ CMS product/content/category/compatibility metadata.
5. Archive structure and filename inference.
6. Human- or AI-entered description.

Lower-priority disagreement is recorded in `conflicts`; it is never silently discarded.

## 7. Core invariants

- One archive member and one installed occurrence are distinct records even if bytes match.
- All paths store root ID plus normalized relative path; absolute paths are cached conveniences.
- Windows paths use backslashes in display fields; canonical comparison uses case-folded `/` separators.
- Every file has SHA-256, byte size, extension, role, existence state, and owning package/product.
- Every property has its owner, locator, type, group, limits, default, flags, controller relationships,
  and semantic effects.
- Every inferred fact records method, evidence reference, confidence, and review state.
- Passwords, purchase tokens, account cookies, and executable secrets are never stored.
- A manifest may describe unclothed anatomy, anatomical geografts, and corresponding body regions using
  the same neutral technical structure as any other asset.
