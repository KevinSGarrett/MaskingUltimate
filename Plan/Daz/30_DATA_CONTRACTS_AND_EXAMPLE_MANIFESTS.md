# Data Contracts and Example Manifests

## 1. Contract rules

- JSON is UTF-8, canonicalized with sorted keys and stable numeric serialization before hashing.
- Timestamps use UTC RFC 3339.
- Paths are relative to a registered logical root; no user-specific absolute path appears in portable
  records.
- IDs are stable opaque strings; display names never act as keys.
- Every schema has semantic version and schema URI.
- Unknown fields are rejected unless a schema explicitly defines an extension object.
- Frozen records are immutable; changes create a new ID/version/hash.
- Hashes are lowercase SHA-256 of bytes or a documented canonical logical structure.

## 2. Asset registry record

~~~json
{
  "schema_version": "1.0.0",
  "asset_id": "daz_asset_7f3a",
  "product_id": "daz_product_10422",
  "display_name": "Example G9 Pose 01",
  "asset_type": "pose",
  "logical_uri": "/People/Genesis 9/Poses/Example/Pose 01.duf",
  "content_root_id": "content_primary",
  "relative_files": [
    "People/Genesis 9/Poses/Example/Pose 01.duf",
    "Runtime/Support/Example.dsx"
  ],
  "aggregate_sha256": "<sha256>",
  "figure_generations": ["genesis9"],
  "compatibility_bases": ["genesis9_base"],
  "dependency_asset_ids": ["daz_asset_g9base"],
  "required_plugins": [],
  "scene_categories": ["solo", "multi_person"],
  "mapping_requirement": "none",
  "technical_state": "eligible",
  "smoke_certificate_id": "daz_smoke_88c1",
  "first_seen_at": "2026-07-14T12:00:00Z",
  "last_seen_at": "2026-07-14T12:00:00Z"
}
~~~

## 3. Registry snapshot

~~~json
{
  "schema_version": "1.0.0",
  "snapshot_id": "daz_registry_20260714_001",
  "created_at": "2026-07-14T12:05:00Z",
  "content_roots": [
    {
      "root_id": "content_primary",
      "logical_path": "F_DAZ/03_content/libraries/MaskFactory_DAZ_Library",
      "root_identity": "<uuid>"
    }
  ],
  "product_count": 120,
  "asset_count": 4821,
  "eligible_asset_count": 3902,
  "product_inventory_sha256": "<sha256>",
  "asset_inventory_sha256": "<sha256>",
  "dependency_graph_sha256": "<sha256>",
  "compatibility_graph_sha256": "<sha256>",
  "snapshot_sha256": "<sha256>"
}
~~~

## 4. Mapping bundle

~~~json
{
  "schema_version": "1.0.0",
  "mapping_id": "map_g9_v1_0001",
  "status": "frozen",
  "figure_generation": "genesis9",
  "base_asset_id": "daz_asset_g9base",
  "topology_fingerprint": {
    "vertex_count": 0,
    "facet_count": 0,
    "facet_order_sha256": "<sha256>",
    "surface_groups_sha256": "<sha256>",
    "uv_sets_sha256": "<sha256>",
    "skeleton_sha256": "<sha256>"
  },
  "ontology": {
    "name": "body_parts_v1",
    "snapshot_sha256": "<sha256>",
    "allowed_min_id": 0,
    "allowed_max_id": 55
  },
  "facet_part_table_path": "07_mappings/genesis9/body_parts_v1/map_g9_v1_0001/facet_part.u16",
  "facet_material_table_path": "07_mappings/genesis9/body_parts_v1/map_g9_v1_0001/facet_material.u16",
  "geograft_compositions": ["map_g9_male_anatomy_v1", "map_g9_female_anatomy_v1"],
  "validation_report_sha256": "<sha256>",
  "bundle_sha256": "<sha256>"
}
~~~

## 5. Scene recipe

~~~json
{
  "schema_version": "1.0.0",
  "scene_id": "daz_scene_01J2EXAMPLE",
  "scene_family_id": "daz_family_01J2EXAMPLE",
  "master_seed": 72599183,
  "named_random_streams": {
    "characters": 111,
    "poses": 222,
    "placement": 333,
    "camera": 444,
    "lighting": 555,
    "environment": 666,
    "render": 777
  },
  "registry_snapshot_id": "daz_registry_20260714_001",
  "runtime_snapshot_id": "daz_runtime_20260714_001",
  "script_bundle_sha256": "<sha256>",
  "ontology": {
    "name": "body_parts_v1",
    "snapshot_sha256": "<sha256>"
  },
  "render_profile_id": "training_relationship_1024_v1",
  "coverage_demand_ids": ["cov_duo_mf_hand_contact_profile"],
  "characters": [
    {
      "construction_id": "c0",
      "requested_promoted_id": null,
      "figure_asset_id": "daz_asset_g9base",
      "character_preset_asset_id": "daz_asset_charA",
      "body_profile_id": "body_profile_0042",
      "face_profile_id": "face_profile_0107",
      "age_appearance_category": "adult_30_44",
      "anatomy_configuration": "adult_male",
      "anatomy_asset_ids": ["daz_asset_male_anatomy"],
      "skin_material_asset_id": "daz_asset_skinA",
      "hair_asset_id": "daz_asset_hairA",
      "wardrobe_asset_ids": ["daz_asset_topA", "daz_asset_pantsA"],
      "morph_values": {
        "prop://body/height": 0.16,
        "prop://body/muscularity": 0.31
      },
      "pose_asset_id": "daz_asset_poseA",
      "pose_adjustments": {},
      "mapping_bundle_ids": ["map_g9_v1_0001", "map_g9_male_anatomy_v1"],
      "world_transform": {
        "translation_cm": [-18.0, 0.0, 2.0],
        "rotation_deg": [0.0, 12.0, 0.0],
        "scale": 1.0
      }
    },
    {
      "construction_id": "c1",
      "requested_promoted_id": null,
      "figure_asset_id": "daz_asset_g9base",
      "character_preset_asset_id": "daz_asset_charB",
      "body_profile_id": "body_profile_0088",
      "face_profile_id": "face_profile_0031",
      "age_appearance_category": "adult_45_64",
      "anatomy_configuration": "adult_female",
      "anatomy_asset_ids": ["daz_asset_female_anatomy"],
      "skin_material_asset_id": "daz_asset_skinB",
      "hair_asset_id": "daz_asset_hairB",
      "wardrobe_asset_ids": ["daz_asset_dressB"],
      "morph_values": {
        "prop://body/height": -0.08,
        "prop://body/weight": 0.22
      },
      "pose_asset_id": "daz_asset_poseB",
      "pose_adjustments": {},
      "mapping_bundle_ids": ["map_g9_v1_0001", "map_g9_female_anatomy_v1"],
      "world_transform": {
        "translation_cm": [15.0, 0.0, 0.0],
        "rotation_deg": [0.0, -10.0, 0.0],
        "scale": 1.0
      }
    }
  ],
  "relationship_template": {
    "type": "hand_to_forearm_contact",
    "participants": ["c0", "c1"],
    "target_parts": ["left_hand", "right_forearm"],
    "target_contact_distance_mm": 1.0
  },
  "camera": {
    "projection": "perspective",
    "focal_length_mm": 55.0,
    "position_cm": [0.0, 155.0, 430.0],
    "target_cm": [0.0, 105.0, 0.0],
    "roll_deg": 0.0,
    "resolution": [1024, 1024],
    "crop": [0, 0, 1024, 1024]
  },
  "lighting": {
    "profile_id": "studio_soft_three_point_v2",
    "parameter_seed": 555
  },
  "environment": {
    "asset_id": "daz_asset_studioA",
    "background_profile": "mid_neutral"
  },
  "props": [],
  "recipe_sha256": "<sha256>"
}
~~~

## 6. Worker result

~~~json
{
  "schema_version": "1.0.0",
  "job_id": "daz_job_01J2",
  "scene_id": "daz_scene_01J2EXAMPLE",
  "attempt": 1,
  "status": "success",
  "started_at": "2026-07-14T13:00:00Z",
  "completed_at": "2026-07-14T13:03:42Z",
  "runtime_snapshot_id": "daz_runtime_20260714_001",
  "script_bundle_sha256": "<sha256>",
  "scene_state_sha256": "<sha256>",
  "promoted_index_map": {"c1": "p0", "c0": "p1"},
  "stages": [
    {"name": "assemble", "seconds": 18.2},
    {"name": "geometry", "seconds": 4.4},
    {"name": "rgb", "seconds": 126.1},
    {"name": "semantic_passes", "seconds": 41.8}
  ],
  "outputs": [
    {"role": "rgb_pristine", "path": "rgb/pristine.png", "sha256": "<sha256>", "bytes": 0},
    {"role": "instance", "path": "ids/instance_u16.png", "sha256": "<sha256>", "bytes": 0},
    {"role": "part", "path": "ids/part_u16.png", "sha256": "<sha256>", "bytes": 0},
    {"role": "material", "path": "ids/material_u16.png", "sha256": "<sha256>", "bytes": 0}
  ],
  "daz_log_sha256": "<sha256>",
  "result_sha256": "<sha256>"
}
~~~

## 7. Validation result and scene certificate

~~~json
{
  "schema_version": "1.0.0",
  "certificate_id": "daz_accept_01J2",
  "scene_id": "daz_scene_01J2EXAMPLE",
  "status": "accepted",
  "bound_hashes": {
    "recipe": "<sha256>",
    "registry": "<sha256>",
    "runtime": "<sha256>",
    "mapping_set": "<sha256>",
    "scene_state": "<sha256>",
    "output_file_map": "<sha256>"
  },
  "validator_set": "daz_validators_1.0.0",
  "result_counts": {"pass": 128, "warn": 2, "fail": 0, "not_applicable": 9},
  "repairs": [],
  "metrics": {
    "unknown_id_pixels": 0,
    "ownership_overlap_pixels": 0,
    "unowned_person_pixels": 0,
    "boundary_f_1px": 0.998,
    "semantic_replay_exact": true
  },
  "report_path": "evidence/validation_report.json",
  "report_sha256": "<sha256>",
  "created_at": "2026-07-14T13:05:00Z"
}
~~~

## 8. MaskFactory synthetic package manifest

~~~json
{
  "schema_version": "maskfactory_instance_synthetic_1.0.0",
  "package_id": "mf_daz_01J2_p0",
  "image_id": "daz_scene_01J2EXAMPLE",
  "scene_id": "daz_scene_01J2EXAMPLE",
  "scene_family_id": "daz_family_01J2EXAMPLE",
  "promoted_person_id": "p0",
  "source_origin": "synthetic",
  "annotation_authority": "geometry_render",
  "truth_tier": "weighted_pseudo_label",
  "truth_partition": "train",
  "train_eligible": true,
  "evaluation_eligible": false,
  "training_loss_weight": 0.2,
  "source_attributes": ["synthetic_geometry_exact", "visible_pixel_truth"],
  "ontology": {"name": "body_parts_v1", "snapshot_sha256": "<sha256>"},
  "synthetic_lineage": {
    "generator": "daz_studio",
    "scene_id": "daz_scene_01J2EXAMPLE",
    "recipe_sha256": "<sha256>",
    "registry_snapshot_sha256": "<sha256>",
    "runtime_snapshot_sha256": "<sha256>",
    "script_bundle_sha256": "<sha256>",
    "mapping_set_sha256": "<sha256>",
    "pass_profile_id": "training_relationship_1024_v1",
    "scene_certificate_sha256": "<sha256>",
    "visible_only": true,
    "amodal_train_eligible": false,
    "counts_as_human_anchor_gold": false,
    "counts_as_autonomous_certified_gold": false
  },
  "files": {
    "source_rgb": {"path": "source_rgb.png", "sha256": "<sha256>"},
    "full_body": {"path": "full_body.png", "sha256": "<sha256>"},
    "indexed_part": {"path": "indexed_part.png", "sha256": "<sha256>"},
    "material": {"path": "material.png", "sha256": "<sha256>"},
    "other_person": {"path": "other_person.png", "sha256": "<sha256>"},
    "protected": {"path": "protected.png", "sha256": "<sha256>"},
    "qa_report": {"path": "qa_report.json", "sha256": "<sha256>"}
  },
  "package_sha256": "<sha256>"
}
~~~

## 9. Dataset row

~~~json
{
  "sample_id": "mf_daz_01J2_p0",
  "package_id": "mf_daz_01J2_p0",
  "image_id": "daz_scene_01J2EXAMPLE",
  "group_id": "daz_family_01J2EXAMPLE",
  "split": "train",
  "truth_tier": "weighted_pseudo_label",
  "source_origin": "synthetic",
  "sample_weight": 0.2,
  "ontology": "body_parts_v1",
  "person_count": 2,
  "promoted_person_id": "p0",
  "dataset_eligible": true
}
~~~

## 10. Coverage demand

~~~yaml
schema_version: 1.0.0
demand_id: cov_duo_mf_hand_contact_profile
priority: 0.92
target_accepted_scenes: 500
current_accepted_scenes: 144
constraints:
  person_count: 2
  anatomy_combinations: [MF]
  pose_family: standing_contact
  contact_type: hand_to_forearm
  view: [left_profile, right_profile]
  hair_occlusion: [none, partial]
  wardrobe_state: [fitted, loose, unclothed]
  active_ontology: body_parts_v1
selection_caps:
  max_one_pose_asset_share: 0.005
  max_one_character_share: 0.03
~~~

## 11. Event

~~~json
{
  "event_schema": "daz_event_1.0.0",
  "event_id": "evt_01J2",
  "timestamp": "2026-07-14T13:05:00Z",
  "event_type": "scene.accepted",
  "entity_type": "scene",
  "entity_id": "daz_scene_01J2EXAMPLE",
  "job_id": "daz_job_01J2",
  "attempt": 1,
  "data": {
    "certificate_id": "daz_accept_01J2",
    "output_file_map_sha256": "<sha256>"
  }
}
~~~

## 12. Rejection record

~~~json
{
  "schema_version": "1.0.0",
  "entity_id": "daz_scene_failed",
  "disposition": "rejected",
  "reason_code": "MULTI_CROSS_INSTANCE_BLEED",
  "retryability": "adjusted_recipe",
  "observed": {"overlap_pixels": 42},
  "expected": {"overlap_pixels": 0},
  "attempt": 2,
  "max_attempts": 3,
  "affected_asset_ids": [],
  "affected_mapping_ids": ["map_g9_v1_0001"],
  "evidence_paths": ["evidence/overlap_pixels.png", "evidence/validation_report.json"],
  "record_sha256": "<sha256>"
}
~~~

## 13. Schema cross-field invariants

- `source_origin=synthetic` requires `synthetic_lineage`.
- Synthetic requires `truth_tier=weighted_pseudo_label` and `split=train`.
- Synthetic weight is 0.10–0.25 inclusive.
- `body_parts_v1` permits no ID above 55.
- `body_parts_v2` binds to a v2 mapping and permits no ID above 64.
- Every character mapping bundle matches its figure/anatomy topology.
- Worker result scene/recipe/runtime hashes equal the recipe and package.
- Accepted certificate contains zero failed required validators.
- Package files exactly equal its file map.
- All person packages from one scene share image/group/source hashes.
- Amodal diagnostic paths cannot appear as training mask roles.

## 14. Versioning and migrations

- Major: incompatible meaning or required structure.
- Minor: backward-compatible optional capability.
- Patch: clarification or validator bug with unchanged record meaning.
- Migrations are explicit commands, produce new files/IDs, and retain source.
- A migration report includes input/output hashes and field-level changes.
- No migration invents a review identity or changes truth authority.

## 15. Contract completion

Implementation is complete when JSON Schema or equivalent typed definitions exist for every record in
this document, cross-field invariants have positive/negative fixtures, canonical hashing is stable
across process restarts, and examples validate after replacing placeholder hashes/counts with fixture
values.
