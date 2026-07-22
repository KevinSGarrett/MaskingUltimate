# ULTIMATE MASKING SYSTEM — MASTER TECHNICAL BLUEPRINT
## Document 00: Master Index & Reading Guide

**Project codename:** MaskFactory
**Project root:** `C:\Comfy_UI_Main_Masking\`
**Plan pack location:** `C:\Comfy_UI_Main_Masking\Plan\`
**Blueprint version:** 1.2.0
**Ontology versions:** active `body_parts_v1` (56 PART IDs `0..55`); approved but inactive `body_parts_v2` (66 PART IDs `0..65`, doc 18)
**Date:** 2026-07-09
**Owner:** Kevin (Scentiment / solo dev)
**Target hardware (verified):** NVIDIA GeForce RTX 5060 Laptop GPU, 8 GB VRAM, driver 592.01 (Blackwell / sm_120)

---

## 1. What This Pack Is

This is the complete end-to-end technical blueprint, project plan, and instruction manual for
building the **Ultimate Masking System**: a production-grade, autonomous-first, selectively abstaining
body-part mask factory that produces pixel-perfect binary PNG masks for every visible body part
of a character in an image, with specialist handling for hands/fingers, chest/clothing
boundaries, hair, feet/toes, occlusion, and clothing — and which ultimately trains its own
custom fine-tuned segmentation models and integrates directly into ComfyUI.

Every decision has been made. There are no open questions. A developer (or AI coding agent)
can build the entire system from these 26 documents without asking a single design question.

---

## 2. Document Map (Read In This Order)

| # | File | Contents |
|---|------|----------|
| 00 | 00_MASTER_INDEX.md | This file. Map, conventions, definitions of done |
| 01 | 01_PROJECT_CHARTER_AND_SCOPE.md | Mission, goals, scope, principles, success criteria, data governance |
| 02 | 02_MASK_ONTOLOGY_SPEC.md | Complete label registry, IDs, mask-type taxonomy, left/right rules, visibility states, exclusivity & z-order contract |
| 03 | 03_GOLD_MASK_FORMAT_SPEC.md | Binary PNG spec, package layout, naming, panoptic PART map + MATERIAL map, gold-vs-inpaint separation, hair matting exception |
| 04 | 04_DATA_SCHEMAS_AND_MANIFESTS.md | Full JSON schemas: manifest, QA report, model registry, failure queue, coverage matrix, state DB |
| 05 | 05_SYSTEM_ARCHITECTURE.md | Component architecture, dataflow, consensus engine design, module boundaries, repo layout |
| 06 | 06_ENVIRONMENT_AND_INSTALLATION.md | Hardware plan, WSL2/Docker, exact env builds, every model checkpoint, CVAT deployment, reproducibility pinning |
| 07 | 07_PIPELINE_STAGE_SPECS.md | Stages S00–S15 with I/O contracts, algorithms, prompting strategy, pseudocode |
| 08 | 08_SPECIALIST_LANES_SPEC.md | Hand/finger lane, chest/clothing lane, hair/face lane, feet/toes lane, 3D body prior lane |
| 09 | 09_AUTO_QA_VALIDATION_SPEC.md | All automatic checks (QC-001…QC-034), metrics, thresholds, topology/skeleton rules |
| 10 | 10_LLM_VLM_QA_LAYER.md | Local VLM setup, exact prompts, verdict schema, routing logic, cloud-LLM boundaries |
| 11 | 11_HUMAN_REVIEW_WORKFLOW.md | CVAT project config, SOPs, statuses, hotkeys, second review, throughput model |
| 12 | 12_DATASET_TRAINING_ACTIVE_LEARNING.md | Splits, coverage matrix, DVC versioning, fine-tune specs for all 5 models, leaderboard, synthetic data |
| 13 | 13_COMFYUI_INTEGRATION.md | Custom node pack, inpaint mask derivation, runtime inference service |
| 14 | 14_IMPLEMENTATION_ROADMAP_WBS.md | Phases P0–P7, every task with ID, deliverable, and acceptance criteria |
| 15 | 15_RISKS_OPERATIONS_RUNBOOK.md | Risk register, daily operations, troubleshooting, backup policy, glossary |
| 16 | 16_EXTERNAL_FOUNDATION_BOOTSTRAP.md | Existing model, workflow, and dataset bootstrap plan for Sapiens, SCHP, DensePose, DWPose, SAM2, Civitai, and public parsing datasets |
| 17 | 17_MULTI_PERSON_MULTI_CHARACTER_MASKING_SPEC.md | Multi-instance masking: person promotion/ranking, per-instance package layout, interperson occlusion, new QA checks, split-integrity rule, Phase P8 |
| 18 | 18_ADULT_ANATOMY_ONTOLOGY_V2_SPEC.md | Approved body_parts_v2 extension for observable adult anatomy, clothed/nude visibility semantics, v1 migration, QA, CVAT, training, serving, and ComfyUI |
| 19 | 19_MULTI_PROVIDER_TEACHER_AND_CONTINUOUS_IMPROVEMENT_SPEC.md | Governed local-Qwen + Gemini + OpenAI + Anthropic shadow teachers, correction tools, <$20/day budget circuit breaker, frozen evaluation, and human-gold-only improvement loop |
| 20 | 20_PROGRESSIVE_AUTONOMOUS_MASK_FACTORY_SPEC.md | Candidate tournaments, correction rounds, machine-verified masks, label/context-specific 95%-confidence certificates, random audits, drift revocation, and calibrated autonomous acceptance |
| 21 | 21_AUTONOMOUS_REPAIR_EXECUTION_SPEC.md | ROI-bound reconstruction, exact-candidate four-reviewer convergence, transactional label repair, reversible CVAT publication, and rollback |
| 22 | 22_TECHNOLOGY_CURRENCY_AND_MODEL_CHALLENGE_SPEC.md | Active-registry governance, provider/model lifecycle states, license/content activation, non-collapsing truth metrics, certification statistics, challenger non-inferiority, and currency review |
| 23 | 23_EXTERNAL_SUPERVISION_REFERENCE_DAZ_AND_MINIMAL_REVIEW_SPEC.md | Qualified external-label supervision, the disjoint 83k benchmark/retrieval corpus, exact DAZ synthetic truth, near-perfect selective-autonomy targets, and binary owner decisions |
| 24 | 24_AUTONOMOUS_CORE_COMPLETION_AND_COMFYUI_BRIDGE.md | Required human-free completion profile, exact-output operational authority, MaskFactory↔ComfyUI runtime/release bridge, optional claim profiles, and recovery qualification |
| 25 | 25_SELF_HOSTED_VISUAL_AUTHORITY_AND_RUNPOD_MIGRATION_SPEC.md | Evidence-qualified visual critics, multi-proposal disagreement/repair, positive-control calibration, persistent RunPod execution, and optional read-only legacy-source recovery |
| 26 | 26_ADULT_CORPUS_AUTONOMOUS_BATCH_INGESTION_SPEC.md | Adopted 16-dataset adult-corpus registry, lane-separated external supervision, resumable 256-record processing, strict per-record QA, RunPod synchronization, training, and release integration |

---

## 3. Global Conventions (Apply Everywhere)

1. **Left/right = character's perspective**, never the viewer's. Enforced by pose handedness (QC-014).
2. **Gold truth = 1-channel binary PNG**, values {0, 255}, exact source dimensions, no anti-aliasing, no alpha, no JPG. Ever.
3. **Atomic masks are visible-pixel-only.** Hidden anatomy is never labeled as visible; it becomes a `projected_amodal` region (separate directory, separate truth class).
4. **Derived/union masks are generated by script, never hand-authored.**
5. **A missing mask means nothing.** Visibility state in `manifest.json` is the only authority. Active v1 uses `visible | partially_visible | occluded | cropped_out | not_visible | ambiguous_do_not_use`; v2 adds the exact doc-18 states without changing v1.
6. **Gold masks are never dilated, feathered, or blurred.** Inpaint masks are derived copies with recorded dilation settings.
7. **Every artifact is hashed (SHA-256) and every model/tool version is recorded** in the image manifest and the model registry.
8. **Nothing becomes certified truth until it passes the auto-QA battery and either governed human review or the active autonomous certificate contract.** Neither path overrides format, overlap, provenance, drift, or other hard failures.
9. All pipeline code lives in `src\maskfactory\`, all knobs in `configs\*.yaml`, no magic numbers in code.
10. Paths in docs use Windows form `C:\Comfy_UI_Main_Masking\...`; inside WSL2 the same tree is `/mnt/c/Comfy_UI_Main_Masking/...`.

---

## 4. Definition of Done (System Level)

**Completion-profile authority (doc 24):** the checklist below is retained as the legacy portfolio/
research DoD and evidence map. The required product finish line is the independently computed
`core_autonomous_runtime` profile. Human-anchor masks, CVAT correction, blinded human review,
minimum package volume, full-library download, DAZ work, and long DAZ soak belong only to the optional
`independent_real_accuracy` or post-core `scale_daz_maturity` profiles. An unchecked D/G item does not
block core unless its exact tracker item is also assigned to core in
`Plan\Tracker\completion_track_registry.json`.

The legacy portfolio/research profile is complete when all of the following are true:

- [ ] D1. A new image dropped into `data\incoming\` can be processed with one CLI command to draft every indexed PART in the selected production ontology: 56 for active `body_parts_v1`, and 65 after `body_parts_v2` is formally activated.
- [ ] D2. Both residual draft→human-corrected truth in CVAT and certificate-covered autonomous truth produce authority-explicit packages that pass 100% of format and provenance checks.
- [ ] D3. Auto-QA battery (34 checks) runs on every package and blocks bad gold automatically.
- [ ] D4. VLM QA reviews overlays and routes agree/disagree cases correctly on a 20-image validation set.
- [ ] D5. ≥300 optional legacy training/scale packages exist in `human_anchor_train` or exact `autonomous_certified_gold` with the required statistical certificate, full manifests, hashes, separately reported truth tiers, and coverage matrix ≥80% cell coverage; `operationally_certified_artifact`, bridge/operational certificates, pseudo labels, drafts, and candidates never satisfy this count.
- [ ] D6. Custom fine-tuned body-part model beats the SAM2+priors draft pipeline on the frozen test holdout for mean per-part IoU and boundary F-score, per the leaderboard.
- [ ] D7. Hand/finger specialist model achieves finger-class mean IoU ≥ 0.70 on hand-crop holdout.
- [ ] D8. ComfyUI node pack loads gold/predicted masks and produces derived inpaint masks inside a workflow.
- [ ] D9. Full environment is reproducible from `env\` lockfiles + `models\model_registry.json` on a clean machine.
- [ ] D10. Runbook operations (backup, retrain, failure mining) each executed successfully at least once.
- [ ] D11. A photo containing 2 to `max_instances_per_image` people produces correctly-instanced, non-cross-bleeding, QA-passing gold packages for every promoted person, with interperson contact/occlusion correctly and reciprocally handled (doc 17).

---

## 5. How To Use This Pack

- **Starting (or resuming) autonomous building in a fresh AI session:** paste `C:\Comfy_UI_Main_Masking\KICKOFF_PROMPT.md`'s content as the first message. Reusable at any point in the project's life, not just day one. The dashboard's required core profile takes priority over optional portfolio percentage.
- **Building it yourself / with an AI coding agent:** follow 14 (Roadmap) task-by-task; each task references the spec doc that governs it.
- **Annotating:** doc 11 is the operator manual.
- **Debugging bad masks:** doc 09 (which check fired) → doc 07 (which stage produced it) → doc 15 (troubleshooting table).
- **Bootstrapping from existing tools/datasets:** doc 16 → `Plan\Civitai\README.md` → instructions 09 → items `MF-P0-09.*` through `MF-P0-12.*`.
- **Multi-person / multi-character images:** doc 17 (full spec) → items `Plan\Items\10_ITEMS_P8_MULTI_PERSON_MASKING.md` (Phase P8, builds after the single-person system is proven).
- **Adding a new label later:** doc 02 §9 (ontology change procedure). Never edit labels ad hoc.
- **Adult-anatomy ontology v2:** doc 18 plus `Plan\OntologyV2\IMPLEMENTATION_CHECKLIST.md`; the active v1 map must not change until the migration gate passes.
- **Self-hosted visual authority and RunPod persistence:** doc 25 plus Instructions 13–14; model names never outrank measured positive-and-negative calibration evidence. AWS is retired from active operation and appears only in narrowly scoped read-only legacy-source recovery.
