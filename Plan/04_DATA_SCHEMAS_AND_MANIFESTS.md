# Document 04: Data Schemas & Manifests

All JSON is UTF-8, 2-space indent, schema-validated (jsonschema) in CI and at packager time.
Schemas live in `src\maskfactory\schemas\*.schema.json`; this doc is their normative definition.

---

## 1. `manifest.json` (per instance — THE authority)

Schema selection is versioned and fail-closed. `body_parts_v1` uses schema version `1.0.0` and
`manifest.schema.json`. `body_parts_v2` uses schema version `2.0.0` and
`manifest_v2.schema.json`, adds `reviewed_ontology_version`, per-label `review_authority`, the
doc-18 visibility states, and separate ambiguity-mask authority. Reindex, restore verification,
dataset export, CVAT pull, and packaging select the schema from `mask_ontology_version`; they do
not coerce one version into the other. The JSONC example below is the active v1 shape.

```jsonc
{
  "schema_version": "1.0.0",
  "image_id": "img_a3f9c2e17b04",
  "mask_ontology_version": "body_parts_v1",
  "left_right_convention": "character_perspective",
  "workflow_status": "drafted | auto_qa | vlm_qa | in_review | corrected | approved_gold | exported | deprecated",
  "workflow_updated_at": "2026-07-09T14:03:22Z",

  "source": {
    "source_file": "source.png",
    "source_sha256": "…64 hex…",
    "parent_source_sha256": "…64 hex of the original whole ingested image…",
    "source_width": 1664, "source_height": 2432,
    "source_origin": "generated | owned_photo | licensed | consented_subject",
    "origin_note": "ComfyUI run 2026-07-02 charA seed 8812",
    "ingested_at": "2026-07-09T14:03:22Z",
    "exif_stripped": true
  },

  // In instances\pN packages, source_sha256 authenticates that instance's source crop while
  // parent_source_sha256 is identical across every pN and is the image-level identity used by
  // SQLite reindex/recovery. For a legacy full-image package the hashes may be identical.
  // workflow_status is package-level authority; per-part statuses describe annotation state and
  // must not be overloaded to infer whether S10/S11/S12 has run.

  "person": {
    "primary_person_bbox": [x, y, w, h],
    "person_count": 1,
    "view": "front | back | left_profile | right_profile | left_3_4 | right_3_4",
    "pose_tags": ["arms_down", "standing"],            // from coverage vocabulary §5
    "estimated_person_height_px": 2210
  },

  // AMENDED (doc 17 §6): this manifest.json now lives at
  // instances\pN\manifest.json (one per promoted person; "person" block above describes
  // THIS instance only). A new sibling field is added:
  "interperson": [
    { "other_instance_id": "img_a3f9c2e17b04_p1", "relationship": "contact",
      "contact_band_file": "masks_regions/interperson_contact_boundary.png" }
  ],
  // A new small image_manifest.json (doc 17 §6) sits one level up, indexing every promoted
  // instance for the image — see doc 17 for its schema. Single-person images are unaffected
  // in substance: exactly one instance (p0), an empty interperson[] array.

  "parts": {                                            // one entry per ontology label (all types)
    "left_forearm": {
      "mask_type": "atomic_exclusive",
      "visibility": "visible",                          // doc 02 §8 enum
      "mask_file": "masks/left_forearm.png",            // null when no mask by rule
      "mask_sha256": "…", "mask_area_px": 48211,
      "mask_bbox": [x, y, w, h],
      "components": 1,
      "status": "draft_model_generated | human_corrected | human_approved_gold | rejected_needs_fix | deprecated",
      "annotated_on": "full | crop:left_hand_crop",
      "occlusion": { "occluded_by": ["right_hand_base"], "occludes": [], "layer": "back_layer" },
      "provenance": { "draft_source": "fusion_v1", "sam2_prompt_id": "p_0142", "human_edit": true },
      "notes": ""
    },
    "left_breast_projected_region": {
      "mask_type": "projected_amodal",
      "visibility": "n/a",
      "basis": "torso_landmarks+clothing_surface",
      "mask_file": "projected/left_breast_projected_region.png", "mask_sha256": "…",
      "status": "human_approved_gold"
    }
    // … every label, including explicit not_visible entries:
    // "left_toes": { "visibility": "cropped_out", "mask_file": null, "status": "n/a" }
  },

  "inpaint_derivatives": [
    { "label": "left_hand", "file": "inpaint/inpaint_left_hand_d8f4.png",
      "dilate_px": 8, "feather_px": 4, "ref_scale": 1024, "source_gold_sha256": "…" }
  ],

  "tooling": {
    "annotation_tool": "cvat", "annotation_tool_version": "2.24.0",
    "pipeline_version": "maskfactory 0.4.1+g8f21ac",
    "model_versions_used": { /* mirror of models used, from model_registry */ },
    "config_hashes": { "ontology.yaml": "…", "pipeline.yaml": "…" }
  },

  "review": {
    "reviewer": "kevin", "approved_at": "2026-07-11T02:11:09Z",
    "second_review": { "required": true, "reviewer": "kevin_day2", "result": "pass", "at": "…" },
    "review_time_sec": 940
  },

  "qa": { "qa_report_file": "qa_report.json", "qa_overall": "pass", "qa_score": 0.96 },
  "files": { "<relative_path>": "<sha256>", "…": "…" }     // full package hash map
}
```

Validation invariants (enforced by packager): every enabled ontology label appears in `parts`;
`visibility != visible/partially_visible` ⇒ `mask_file == null` for atomics; status
`human_approved_gold` requires `qa_overall == "pass"` and review block present.

For a v2-approved package, all 65 PART entries must carry complete v2 human-review authority,
the QA report must declare `ontology_version: body_parts_v2` and pass QC-V2-001..012, and every
file named by either a visible mask or ambiguity region must appear in the exhaustive `files{}`
hash map. Migrated-but-unreviewed packages stay `in_review` and are ineligible for v2 datasets.

## 2. `qa_report.json` (per image)

```jsonc
{
  "image_id": "img_a3f9c2e17b04", "run_id": "qa_20260709_1403_7f2a",
  "pipeline_version": "…", "created_at": "…",
  "checks": [
    { "id": "QC-001", "name": "dimensions_match_source", "scope": "package", "result": "pass" },
    { "id": "QC-011", "name": "atomic_exclusivity", "scope": "left_thigh|right_thigh",
      "result": "pass", "value": 0, "threshold": "<= 0 px" },
    { "id": "QC-014", "name": "left_right_pose_consistency", "scope": "left_hand_base",
      "result": "fail", "value": "handedness_mismatch", "action": "route_human", "evidence": "qa_panels/left_hand_lr.png" }
  ],
  "metrics_per_part": { "left_forearm": { "iou_vs_consensus": 0.94, "boundary_f_2px": 0.88,
      "hole_ratio": 0.001, "components": 1, "disagreement_score": 0.06 } },
  "consensus": { "method": "weighted_vote_v1", "sources": ["sapiens_seg","schp","sam2","geometry","densepose"] },
  "vlm_review": { "model": "qwen2.5-vl:7b-q4", "verdicts": [ /* doc 10 §4 objects */ ] },
  "overall": "pass | fail | needs_human", "score": 0.0
}
```

## 3. `models\model_registry.json`

```jsonc
{ "models": [ {
    "key": "sam2.1_hiera_large", "role": "boundary_refiner",
    "source_url": "https://…", "file": "models/sam2/sam2.1_hiera_large.pt",
    "sha256": "recorded_at_download", "version_tag": "sam2.1", "license": "Apache-2.0",
    "runtime": "torch2.7+cu128", "vram_note": "fp16 ok on 8GB @ ≤2048px",
    "downloaded_at": "…", "verified": true } ] }
```
Every checkpoint used anywhere MUST be registered here first; loader refuses unregistered paths.

## 4. `qa\failure_queue.jsonl` (append-only, one JSON object per line)

`{ "ts": "...", "image_id": "...", "failed_body_part": "left_index_finger",
"failure_reason": "finger_merge | lr_swap | boundary_bleed_clothing | hair_edge | occlusion_confusion | area_anomaly | topology | other",
"pose_angle": "left_3_4", "model_that_failed": "sam2_hand_lane",
"correction_needed": "manual_crop_repaint", "priority": 0.0-1.0, "resolved": false,
"resolution_pkg_version": null }`

Priority formula (doc 12 §7): `priority = 0.4*class_error_rate + 0.3*coverage_deficit + 0.2*downstream_use_weight + 0.1*recency`.

## 5. `qa\coverage_matrix.json`

Axes (vocabulary is closed; extend via ontology change procedure):
`view` × `pose` × `attributes`. Cells count approved gold images.
- view: front, back, left_profile, right_profile, left_3_4, right_3_4
- pose: arms_raised, arms_down, arms_crossed, seated_or_crouched, lying, walking, leg_overlap
- attributes (multi): hands_visible, feet_visible, hand_body_contact, hair_occlusion,
  clothing_boundary, bare_skin_dominant, tight_clothing, loose_clothing, back_visible,
  fingers_spread, fingers_merged, props_present
Target: every (view × pose) cell ≥ 8 images; every attribute ≥ 40 images before P5 training.
**AMENDED (doc 17 §8):** cells also carry an instance-count dimension —
`solo | duo | small_group` — so multi-person scenes get their own coverage targets rather than
being folded invisibly into single-person cells.
`maskfactory coverage report` renders the gap table and feeds active learning.

## 6. Pipeline State DB — `data\maskfactory.sqlite`

Tables:
- `images(image_id PK, source_sha256, status, current_stage, package_version, created_at, updated_at)`
  status enum: `ingested → drafted → auto_qa → vlm_qa → in_review → corrected → approved_gold → exported → deprecated | rejected | quarantined`
- `stage_runs(run_id PK, image_id, stage, started, ended, ok, error, config_hash, gpu_seconds)`
- `review_tasks(task_id PK, image_id, cvat_task_id, assignee, opened, closed, minutes)`
- `training_runs(run_id PK, model_key, dataset_version, started, ended, metrics_json, promoted)`
WAL mode; single-writer (orchestrator); read-only for dashboards. JSON manifests remain the
per-image authority; the DB is the queue/workflow index and is rebuildable from manifests
(`maskfactory reindex`).

## 7. `configs\` File Inventory

`ontology.yaml` (active v1 labels, doc 02 §10) • `ontology_v2.yaml`, `derived_v2.yaml`,
`viz_v2.yaml`, `anatomy_v2_qa.yaml`, `ontology_v2_operations.yaml` (explicit inactive-v2
authority, doc 18) • `pipeline.yaml` (stage toggles, device, tile sizes,
thresholds) • `prompting.yaml` (SAM2 point/box strategies per part) • `qa.yaml` (all QC
thresholds, doc 09) • `derived.yaml` (union formulas) • `inpaint.yaml` (dilate/feather per label)
• `viz.yaml` (colors, panel layout) • `training\*.yaml` (per-model fine-tune configs, doc 12)
• `vlm.yaml` (models, prompts version, routing) • `cvat.yaml` (URL, project ids, label mapping).
Every config carries `config_version`; hashes are stamped into manifests.
