# MaskFactory DAZ Synthetic-Data Subsystem — Blueprint Package Index

**Package status:** Ready for implementation
**Prepared for:** Kevin / MaskFactory
**Blueprint date:** 2026-07-14
**Blueprint root:** `C:\Comfy_UI_Main_Masking\Plan\Daz`
**DAZ operational-data root:** `F:\DAZ`
**Implementation target:** the live MaskFactory repository at `C:\Comfy_UI_Main_Masking`

## 1. What this package is

This package is the controlling design and implementation manual for adding an autonomous DAZ-based
synthetic-person generator to MaskFactory. It is intentionally more than a concept document. It defines
the operating controls, exact storage layout, asset registry, compatibility model, figure-to-ontology
mapping, scene-generation strategy, render passes, engineering validation, MaskFactory integration, training
curriculum, evaluation rules, operations, recovery, implementation work breakdown, tests, and final
acceptance criteria.

The subsystem's job is to create a broad, deterministic, geometry-labeled stream of adult human scenes
that improves MaskFactory's body-part, material, occlusion, left/right, and multi-person performance.
DAZ output is one training source. It is not a substitute for real-image evaluation or human-anchor
calibration, and it is never allowed to redefine MaskFactory's ontology or truth authority on its own.

## 2. Operating profile

Kevin has fixed the operating profile as **private, personal, local, noncommercial, and never
distributed**. Asset source/product records exist only for organization, reproducibility, dependency
resolution, updates, and backup.

## 3. Reading paths

### Kevin / project owner

Read, in order:

1. `01_PROJECT_INTAKE_SUMMARY.md`
2. `02_NON_TECHNICAL_BLUEPRINT.md`
3. `05_EXECUTIVE_SUMMARY.md`
4. `09_ACTIVATION_READINESS_CHECKLIST.md`
5. `10_PROJECT_REGISTERS.md`
6. `24_IMPLEMENTATION_ROADMAP_WBS.md`

### Implementing developer

Read all files, beginning with:

1. `01_PROJECT_INTAKE_SUMMARY.md`
2. `03_TECHNICAL_BLUEPRINT.md`
3. `04_COMBINED_MASTER_BLUEPRINT.md`
4. `06_DEVELOPER_HANDOFF.md`
5. detailed specifications `11` through `25`
6. `26_REQUIREMENTS_TRACEABILITY_MATRIX.md`
7. `28_TEST_MATRIX_AND_ACCEPTANCE_EVIDENCE.md`
8. `29_ACTIVATION_AND_OPERATIONS_RUNBOOK.md`

### Autonomous coding agent

Read:

1. `07_AI_AGENT_HANDOFF.md`
2. `01_PROJECT_INTAKE_SUMMARY.md`
3. `03_TECHNICAL_BLUEPRINT.md`
4. `24_IMPLEMENTATION_ROADMAP_WBS.md`
5. the detailed specification referenced by the active work item
6. `26_REQUIREMENTS_TRACEABILITY_MATRIX.md`
7. `28_TEST_MATRIX_AND_ACCEPTANCE_EVIDENCE.md`

## 4. Document inventory

| File | Purpose |
|---|---|
| `00_PACKAGE_INDEX.md` | Package map, status, reading paths, and precedence |
| `01_PROJECT_INTAKE_SUMMARY.md` | Confirmed facts, assumptions, constraints, conflicts, unknowns, and scope |
| `02_NON_TECHNICAL_BLUEPRINT.md` | Plain-language end-to-end operating model |
| `03_TECHNICAL_BLUEPRINT.md` | Target architecture, components, data flow, interfaces, and invariants |
| `04_COMBINED_MASTER_BLUEPRINT.md` | Integrated end-to-end build and operating sequence |
| `05_EXECUTIVE_SUMMARY.md` | Value, limitations, resource profile, decisions, and success measures |
| `06_DEVELOPER_HANDOFF.md` | Implementation boundaries, module targets, coding order, and handoff contract |
| `07_AI_AGENT_HANDOFF.md` | Fail-closed instructions for autonomous implementation agents |
| `08_QA_TESTING_PLAN.md` | Layered test strategy and release evidence |
| `09_ACTIVATION_READINESS_CHECKLIST.md` | Evidence checklist for technical, data, training, and operating readiness |
| `10_PROJECT_REGISTERS.md` | Decisions, assumptions, risks, dependencies, open questions, and RACI |
| `11_F_DAZ_FOLDER_AND_STORAGE_SPEC.md` | Exact `F:\DAZ` tree, retention, capacity, permissions, hashes, and backups |
| `12_OPERATING_PROFILE_AND_TECHNICAL_LINEAGE.md` | Private/local operating profile and reproducibility lineage |
| `13_ASSET_ACQUISITION_INSTALLATION_AND_CATALOG.md` | Purchase boundary, Install Manager setup, scanning, metadata, and catalog rules |
| `14_ASSET_COMPATIBILITY_SMOKE_TEST_AND_QUARANTINE.md` | Dependency graph, compatibility scoring, load/render tests, and quarantine |
| `15_FIGURE_TO_MASKFACTORY_ONTOLOGY_MAPPING.md` | Genesis surface/bone/polygon mapping to v1/v2 and clothing territory transfer |
| `16_CHARACTER_BODY_MATERIAL_HAIR_AND_WARDROBE_SPEC.md` | Controlled character diversity and compatibility constraints |
| `17_POSE_CONTACT_OCCLUSION_AND_MULTI_PERSON_CATALOG.md` | Pose taxonomy, interaction recipes, contact, overlap, and 1–4-person matrices |
| `18_CAMERA_LIGHTING_ENVIRONMENT_PROP_AND_DEGRADATION_SPEC.md` | Image-formation coverage and difficult visual conditions |
| `19_SCENE_SAMPLING_COVERAGE_AND_CURRICULUM.md` | Coverage axes, constrained sampling, deficit targeting, and curriculum |
| `20_DAZ_SCRIPTING_ORCHESTRATION_AND_WORKER_PROTOCOL.md` | DAZ Script/Windows worker architecture, queues, watchdog, retries, and replay |
| `21_RENDER_PASSES_ANNOTATION_AND_GEOMETRY_TRUTH.md` | RGB, ID, part, material, depth, normal, visibility, and relationship passes |
| `22_AUTOMATED_VALIDATION_QA_AND_REJECTION.md` | Fail-closed scene/package validation and repair/retry policy |
| `23_MASKFACTORY_INTEGRATION_SCHEMAS_CLI_AND_STATE.md` | Required schema, CLI, state, package, dataset, and pipeline integration |
| `24_IMPLEMENTATION_ROADMAP_WBS.md` | Phased work breakdown, dependencies, evidence, and rollback points |
| `25_TRAINING_DOMAIN_GAP_EVALUATION_AND_PROMOTION.md` | Synthetic mixing, weighting, real holdouts, ablations, and promotion criteria |
| `26_REQUIREMENTS_TRACEABILITY_MATRIX.md` | Requirement-to-design-to-test-to-evidence mapping |
| `27_OPERATIONS_CAPACITY_BACKUP_SECURITY_AND_COST.md` | Capacity, scheduling, monitoring, backup, security, and cost controls |
| `28_TEST_MATRIX_AND_ACCEPTANCE_EVIDENCE.md` | Concrete unit/integration/e2e/benchmark/failure test catalog |
| `29_ACTIVATION_AND_OPERATIONS_RUNBOOK.md` | Installation, pilot, launch, routine operation, pause, recovery, and rollback |
| `30_DATA_CONTRACTS_AND_EXAMPLE_MANIFESTS.md` | Normative draft schemas and complete JSON/YAML examples |
| `31_OFFICIAL_SOURCE_REGISTRY.md` | Official DAZ and MaskFactory sources and review dates |
| `32_F_DAZ_ASSET_PLACEMENT_AND_DIRECTORY_MANIFEST.md` | Materialized F-drive taxonomy and exact download-placement rules |
| `Asset_Manifest/00_package_index.md` | Normative asset manifest schemas, body taxonomy, templates, examples, AI ingestion manual, and implementation handoff |

## 5. Precedence and no-drift rules

1. MaskFactory's current approved amendments and live schemas win over older project prose.
2. This package defines the DAZ subsystem but does not silently amend unrelated MaskFactory behavior.
3. `body_parts_v1` remains the active ontology until the existing v2 activation requirements pass.
4. The DAZ subsystem must generate against the ontology version declared by each job; versions cannot
   mix within a scene, package, or dataset build.
5. DAZ synthetic labels enter as `weighted_pseudo_label`, with an orthogonal
   `synthetic_geometry_exact` source attribute, unless Kevin later adopts an explicit truth-contract
   amendment. They never count as `human_anchor_gold` or `autonomous_certified_gold`.
6. The current maximum synthetic share is 30% of a training set. Both the dataset builder and training
   launcher enforce the same limit.
7. Synthetic samples are train-only. No synthetic sample enters calibration, validation authority,
   `test_holdout`, `hard_case_holdout`, certificate fitting, threshold tuning, or final promotion truth.
8. Multi-person splits remain keyed by `image_id`; every instance in a scene stays in one partition.
9. The character scope is adult male and adult female DAZ figures, including clothed, partially
    clothed, and unclothed anatomy configurations requested for segmentation coverage.

## 6. Completion definition for this blueprint package

The documentation package is complete when every listed file exists, has no empty or deferred sections,
uses the same locked paths and authority rules, and passes the consistency checks in
`28_TEST_MATRIX_AND_ACCEPTANCE_EVIDENCE.md`. The DAZ subsystem itself is complete only after the
readiness evidence in `09_ACTIVATION_READINESS_CHECKLIST.md` and all Definition-of-Done criteria in
`24_IMPLEMENTATION_ROADMAP_WBS.md` are backed by real evidence.
