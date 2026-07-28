# DAZ Asset Manifest System

This package is the normative catalog contract for every DAZ product, archive, installed file, preset,
runtime component, property, morph, material, texture, geometry resource, pose, camera, light,
environment, prop, script, and generated compatibility record used by MaskFactory.

## Runtime locations

- Specification: `C:\Comfy_UI_Main_Masking\Plan\Daz\Asset_Manifest`
- Download classification: `F:\DAZ\02_installers\manual_packages\asset_dropzone`
- Native DAZ content library: `F:\DAZ\03_content\libraries\MaskFactory_DAZ_Library`
- Canonical manifests: `F:\DAZ\05_registry\manifests`
- Runtime inspection evidence: `F:\DAZ\05_registry\inspection`
- Mapping outputs: `F:\DAZ\07_mappings`

Downloaded archives are classified in the dropzone. Installed vendor files are never reorganized into
catalog folders; they retain their native `data`, `People`, `Runtime`, and support paths. The manifest
connects those physical locations to semantic categories.

## Package inventory and reading order

1. `01_manifest_system_blueprint.md` — architecture, identities, lifecycle, and invariants.
2. `02_field_dictionary.md` — complete field-level contract.
3. `schemas/asset_manifest.schema.json` — machine-validatable Draft 2020-12 schema.
4. `vocabularies/controlled_vocabularies.yaml` — closed values and extension rules.
5. `vocabularies/body_taxonomy.yaml` — major/sub/micro/nano body hierarchy and ontology links.
6. `templates/asset_manifest.template.yaml` — canonical authoring template.
7. `examples/comprehensive_asset.example.yaml` — representative populated record.
8. `10_ai_asset_ingestion_manual.md` — deterministic AI intake and enrichment procedure.
9. `11_validation_versioning_and_qa.md` — validation, deduplication, updates, and evidence.
10. `12_implementation_handoff.md` — database, scanner, API, index, and rollout contract.
11. `13_official_technical_sources.md` — authoritative DAZ technical references.
12. `tools/validate_manifest.py` — reusable schema, vocabulary, taxonomy, graph, path, and hash validator.

## Authority and precedence

The JSON Schema controls structure and cardinality. Controlled vocabularies control enumerated values.
The body taxonomy controls descriptive body-region identifiers. `configs/ontology.yaml` and the
MaskFactory ontology loader alone control active trainable labels. The template and example illustrate
the contract but cannot override it.

## Definition of done for one asset

An asset is catalog-complete only when its product/package/archive identity, every installed file,
logical DAZ URI, semantic classification, dependencies, runtime-created components, properties/sliders,
body-region associations, compatibility results, hashes, unresolved references, and inspection evidence
are recorded; the record validates; all referenced paths exist or are explicitly marked missing; and a
second scan produces no unexplained change.
