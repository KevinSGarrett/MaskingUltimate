# Operating Profile and Technical Lineage

## 1. Purpose

This document defines two simple implementation facts:

1. the DAZ subsystem runs locally for Kevin's private personal project; and
2. generated scenes remain exactly reproducible through technical lineage records.

Technical lineage means asset IDs, file hashes, dependencies, mappings, random seeds, recipes, render
settings, and output hashes. It is a passive record used only for technical organization and replay.

## 2. Locked operating profile

~~~yaml
profile_id: private_personal_local_v1
execution_location: local_machine
commercial_deployment: false
public_hosting: false
distribution: false
automatic_asset_purchase: false
automatic_account_login: false
~~~

The worker is designed around this profile. It does not need marketplace, publishing, collaboration,
remote-dataset, or public-serving features.

## 3. Character scope

The scene generator supports the adult DAZ character configurations requested for MaskFactory:

- adult male figures;
- adult female figures;
- male/female body-shape and presentation variation;
- clothed, partially clothed, underwear, swimwear, and unclothed configurations;
- male and female anatomy geometry when installed and technically mapped;
- one through four characters in every configured male/female combination.

This is normal scene metadata used to select compatible geometry, mappings, and coverage targets.

## 4. Why technical lineage exists

Lineage enables the system to:

- reproduce any accepted scene from a seed and frozen inputs;
- identify the asset or mapping responsible for a rendering defect;
- resolve file and product dependencies;
- detect asset updates and invalidate stale technical certificates;
- measure how often a product, character, hair, wardrobe item, pose, or environment appears;
- remove samples derived from a defective mapping;
- rebuild a dataset snapshot and training run;
- keep source assets out of generated MaskFactory packages;
- compare renderer or driver versions without guessing.

## 5. Product record

Each locally installed product may have the following organization record:

~~~yaml
product_id: daz_product_<stable-id>
display_name: <local catalog name>
source_kind: daz_store | third_party | user_created | bundled
source_locator: <optional URL or local note>
installed_at: <timestamp>
install_manifest_sha256: <hash or null>
content_root_id: content_primary
file_count: <integer>
total_bytes: <integer>
product_fingerprint_sha256: <canonical inventory hash>
asset_ids: [<stable asset IDs>]
~~~

Only fields useful to local organization or replay are required. Credentials, payment details, serials,
account tokens, and order tokens are never stored.

## 6. Asset record

Every usable asset receives a stable technical record:

~~~yaml
asset_id: daz_asset_<stable-id>
product_id: daz_product_<stable-id>
asset_type: figure | morph | material | hair | wardrobe | anatomy | pose | expression | camera | light | environment | prop
logical_uri: <DAZ content URI>
relative_files: [<paths relative to registered content root>]
aggregate_sha256: <canonical asset hash>
figure_generations: [genesis9]
compatibility_bases: [<normalized IDs>]
dependency_asset_ids: [<stable IDs>]
required_plugins: []
scene_categories: [<ordinary technical categories>]
mapping_requirement: inherited_base | asset_specific | none
smoke_certificate_id: <certificate ID or null>
technical_state: discovered | indexed | eligible | incompatible | quarantined | missing
~~~

The record answers “what is this, where is it, what does it need, and does it work?” It does not answer
whether someone has approved its use.

## 7. Character configuration record

Every generated person has explicit construction metadata:

~~~yaml
person_id: p0
figure_asset_id: <asset ID>
character_preset_asset_id: <asset ID or null>
body_profile_id: <profile ID>
face_profile_id: <profile ID>
skin_material_asset_id: <asset ID>
hair_asset_id: <asset ID or null>
wardrobe_asset_ids: [<asset IDs>]
anatomy_configuration: adult_male | adult_female
anatomy_asset_ids: [<asset IDs>]
age_appearance_category: adult_21_29 | adult_30_44 | adult_45_64 | adult_65_plus
presentation_profile: <style profile ID>
morph_values: {<property URI>: <numeric value>}
pose_asset_id: <asset ID>
pose_adjustments: {<joint URI>: <numeric values>}
mapping_bundle_id: <mapping ID>
~~~

Age-appearance categories are ordinary diversity controls. Their purpose is to balance facial, body,
skin, posture, and hair variation across the adult character corpus.

## 8. Anatomy and wardrobe representation

Anatomy geometry and presentation are independent:

- anatomy configuration selects the compatible base geometry, geografts, and ontology mappings;
- presentation selects hair, cosmetics, styling, expression, and wardrobe;
- body profiles provide continuous shape diversity;
- wardrobe state records clothed, layered, partial, or unclothed scene construction;
- visible geometry determines visible labels;
- hidden anatomy is never inserted into visible training truth.

Male/female anatomy combinations for one through four people are coverage dimensions, just like pose,
camera angle, lighting, or clothing.

## 9. Scene lineage record

Every accepted scene records:

~~~yaml
scene_id: daz_scene_<uuid>
scene_family_id: <family ID>
recipe_schema_version: <version>
recipe_sha256: <hash>
master_seed: <integer>
named_random_streams: {<stream>: <derived seed>}
asset_registry_snapshot_id: <snapshot ID>
runtime_snapshot_id: <snapshot ID>
mapping_bundle_ids: [<mapping IDs>]
characters: [<character configuration records>]
camera: <resolved camera record>
lighting: <resolved lighting record>
environment: <resolved environment record>
props: [<resolved prop records>]
render_profile_id: <profile ID>
ontology_version: body_parts_v1 | body_parts_v2
output_hashes: {<relative file>: <sha256>}
created_at: <timestamp>
~~~

The final resolved record is authoritative. It stores actual applied values, not merely requested
presets.

## 10. Technical eligibility

An asset or scene is technically eligible when:

- referenced files exist and hashes match the active registry snapshot;
- dependencies and required plugins resolve;
- the asset is compatible with the selected figure generation;
- load, fit, pose, render, and error-log smoke checks pass;
- required topology or body-territory mappings exist;
- the full scene fits the camera and configured resource limits;
- synchronized annotation passes can be generated and validated;
- the output package passes pixel, identity, alignment, completeness, and replay checks.

These are engineering correctness conditions. Failure produces a reason-coded retry, exclusion, or
quarantine so broken assets cannot corrupt the corpus.

## 11. Local data handling

- Source assets, textures, installers, caches, and DAZ scene files remain under F:\DAZ.
- Git contains code, small schemas, configuration templates, and documentation only.
- Portable manifests use logical asset IDs rather than Kevin's username or absolute user paths.
- Exported RGB files have unnecessary EXIF and local-user metadata removed.
- Logs contain asset IDs and reason codes, not credentials or account details.
- Support bundles are explicitly assembled and redacted; nothing uploads automatically.
- Generated datasets and models remain local under the operating profile.

## 12. MaskFactory package lineage

The DAZ adapter adds structured lineage without changing MaskFactory truth semantics:

- source_origin is synthetic;
- truth tier is weighted_pseudo_label;
- synthetic geometry exactness is recorded as an orthogonal source attribute;
- split is train;
- sample weight is configured between 0.10 and 0.25;
- the active synthetic-share ceiling remains 30%;
- scene family and image identity keep all related instances in one split;
- synthetic packages never count as human-anchor or autonomous-certified gold.

## 13. Change propagation

When an input changes, the system invalidates only affected technical descendants:

| Changed input | Invalidated descendants |
|---|---|
| asset file/hash | asset smoke certificate, queued recipes using it, derived packages |
| dependency or plugin | dependent asset certificates and queued scenes |
| mapping bundle | packages and datasets using that mapping |
| DAZ/renderer/driver profile | reproducibility certificate; RGB comparison required |
| recipe schema | recipes requiring migration |
| ontology | label maps and packages for that ontology only |
| package schema | adapter output and dataset snapshots |

Historical files are retained by immutable snapshot ID until their retention policy expires.

## 14. Rebuild and replay requirements

A lineage implementation is complete only when:

1. registry rebuild from the same content roots yields the same canonical snapshot hash;
2. recipe generation from the same seed and snapshots yields byte-identical canonical JSON;
3. semantic passes replay byte-identically on the same pinned runtime;
4. RGB replay is byte-identical or falls within the explicitly versioned renderer tolerance;
5. every dataset row resolves to its scene, recipe, assets, mappings, runtime, and output hashes;
6. removing one asset or mapping can enumerate every affected package and model run.

## 15. Completion criteria

- The operating profile is represented once and reused by configuration.
- Technical lineage remains a passive reproducibility record and never controls activation.
- Source and asset records contain only fields required for local organization and reproducibility.
- Character scope and anatomy configuration are ordinary scene metadata.
- Every accepted package has complete, machine-resolvable technical lineage.
- Credential and payment fields are absent from schemas and logs.
- Asset, mapping, runtime, recipe, package, dataset, and model change propagation is tested.
