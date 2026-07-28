# MaskingUltimate — 20-Section End-to-End Completion Plan

This package divides **all 285 unresolved tracker items** into exactly 20 dependency-ordered acceptance sections. Every unresolved item appears once and only once in `ITEM_COVERAGE_MAP.md` / `.json`.

> **Snapshot/status rule:** item membership and dependency ordering in this
> package are frozen to `SECTION_MANIFEST.json` source snapshot
> `2c04e1a7f5adf5f6948af01423f67a867206e8c2`. Status and percentage columns
> in the coverage map and section work packets are historical snapshot fields,
> not live task authority. Always resolve current state through
> `Plan/Tracker/tracker.py`. As of the accepted 2026-07-28 control release,
> `MF-P6-20.01`, `.02`, and `.03` are complete at 100%; `MF-P6-20.04`
> remains partially complete at 65%. The frozen mapping must not be mistaken
> for a reason to reopen accepted work or grant successor completion credit.

## Required execution sequence

| # | Section | Tracker items | Direct dependencies | Primary acceptance result |
|---:|---|---:|---|---|
| 01 | [Recovery Freeze, Authority, and Git/Tracker Reconciliation](sections/SECTION_01_AUTHORITY_GIT_TRACKER_RECONCILIATION.md) | 1 | None | Establish one indisputable source-of-truth baseline before any additional feature work, preserving every local, staged, untracked, GitHub, and accepted runtime artifact without destructive reconciliation. |
| 02 | [Canonical Integrated Source Tree and Repository Hygiene](sections/SECTION_02_CANONICAL_INTEGRATED_SOURCE_TREE.md) | 1 | 01 | Produce one complete, source-controlled tree containing the full MaskFactory product and the accepted autonomy/runtime implementation, with no dependency on stale pycache, another checkout, chat state, or untracked source. |
| 03 | [Reproducible Environment, Packaging, Clean Export, and Full Test Baseline](sections/SECTION_03_ENVIRONMENT_PACKAGING_FULL_TEST_BASELINE.md) | 4 | 02 | Make the canonical tree independently installable and testable on authorized Windows/WSL/RunPod environments, classify every external prerequisite honestly, and establish the first trustworthy full-product baseline. |
| 04 | [Governed Source Ingestion, Provenance, Reference Corpus, and Leakage Control](sections/SECTION_04_SOURCE_PROVENANCE_REFERENCE_LEAKAGE.md) | 9 | 03 | Create the governed real-image and external-supervision foundation needed for calibration, training, benchmarks, and later DAZ gap targeting without allowing references, prompts, boxes, or unqualified masks to become truth. |
| 05 | [Human-Anchor Gold Factory, CVAT Review, and Measured Baselines](sections/SECTION_05_HUMAN_ANCHOR_GOLD_CVAT_BASELINES.md) | 8 | 03, 04 | Create the minimum real human-authoritative gold and timing foundation that unlocks calibration, objective scoring, training, and headline claims. |
| 06 | [Provider Runtime Catalog, Model Installation, and Role Qualification](sections/SECTION_06_PROVIDER_RUNTIME_ROLE_QUALIFICATION.md) | 8 | 03, 04, 05 | Make every active discovery, segmentation, pose, geometry, boundary, and challenger provider reproducible, isolated, benchmarkable, and rollback-safe. |
| 07 | [Single-Person Draft Pipeline and Deterministic Auto-QA](sections/SECTION_07_SINGLE_PERSON_DRAFT_PIPELINE.md) | 3 | 05, 06 | Prove one deterministic command can take governed single-person images through complete indexed draft generation and objective comparison to human gold while reducing measured human work. |
| 08 | [Ontology, Truth-Tier, and Quantitative QA Authority](sections/SECTION_08_ONTOLOGY_TRUTH_QA_AUTHORITY.md) | 1 | 04, 05, 06, 07 | Turn the current candidate per-label/per-context QA registry into an empirically calibrated, immutable authority that resolves every enabled ontology label and fails closed on missing, stale, or globally collapsed rules. |
| 09 | [Specialist Anatomy, Clothing, Hair, Pose, and Geometry Lanes](sections/SECTION_09_SPECIALIST_LANES.md) | 9 | 06, 07, 08 | Finish and qualify role-specific specialist lanes for hard anatomy, boundaries, pose, geometry, clothing, accessories, repeated instances, and independent votes without allowing unmeasured model substitution. |
| 10 | [Visual Critic Committee, Repair, Certification, Revocation, and 66-Class Safety](sections/SECTION_10_VISUAL_CRITIC_REPAIR_CERTIFICATION.md) | 35 | 05, 08, 09 | Establish qualified primary and independent-family visual authority, fail-closed disagreement, bounded repair, exact terminal accounting, and real certificate/revocation behavior across every active class and risk stratum. |
| 11 | [Certified Dataset Build, DVC, Active Learning, and Scale](sections/SECTION_11_DATASET_DVC_ACTIVE_LEARNING_SCALE.md) | 13 | 05, 07, 10 | Convert qualified truth into immutable, reproducible datasets; close the 100-certified sprint; scale coverage deliberately; and publish the residual real-data gap that governs later training and DAZ work. |
| 12 | [Custom Training, Leaderboard, Champion Promotion, and Ontology-v2 Activation](sections/SECTION_12_TRAINING_CHAMPIONS_V2_ACTIVATION.md) | 34 | 06, 08, 10, 11 | Train and objectively select body, clothing, hand, anatomy-aware, and optional challengers; promote only image-disjoint human-holdout winners; prove rollback; and activate ontology v2 atomically only after every gate passes. |
| 13 | [Autonomous Steward, Routing, GPU Coordination, and Exception-Only Control](sections/SECTION_13_AUTONOMOUS_STEWARD_CONTROL_PLANE.md) | 3 | 03, 10, 12 | Finish the integrated tracker-selection-to-terminal-packet supervisor and durable RunPod queue so routine work no longer depends on per-step Codex handoffs or unsafe dual submission. |
| 14 | [Real Campaign Qualification, Evidence Reconstruction, and Throughput Acceptance](sections/SECTION_14_REAL_CAMPAIGNS_THROUGHPUT_EVIDENCE.md) | 8 | 10, 11, 12, 13 | Run the remaining real mask and mixed campaigns, measure autonomy and Codex reduction honestly, reconcile every terminal outcome, preserve previously accepted campaigns, and close the Plan-27 throughput gate. |
| 15 | [Serving API, Model Registry, Mode A/B ComfyUI Nodes, and Local Runtime](sections/SECTION_15_SERVING_API_COMFYUI_LOCAL_RUNTIME.md) | 11 | 06, 10, 12, 14 | Deliver the complete local MaskFactory serving and ComfyUI integration surface against promoted champions, with read-only package behavior, typed fallback, measured latency, unseen-input workflows, v2 compatibility, and rollback. |
| 16 | [Cross-Project Comfy_UI_Main Bridge, Adoption Semantics, Feedback, and Recovery](sections/SECTION_16_CROSS_PROJECT_MAIN_BRIDGE.md) | 13 | 14, 15 | Complete the external consumer adapter and two-way release/adoption/feedback/recovery contract between MaskFactory and `C:\Comfy_UI_Main` without allowing dirty bytes, unsigned packages, or ambiguous receipts to confer authority. |
| 17 | [Real Multi-Person and Multi-Character Masking](sections/SECTION_17_REAL_MULTI_PERSON_MASKING.md) | 10 | 10, 12, 15 | Prove the activated system on 10–20 governed real 2–4-person images with exact instance ownership, certificate-covered acceptance, residual routing, blinded audits, zero cross-instance bleed, and rollback. |
| 18 | [DAZ Runtime, Assets, Genesis 9 Mapping, Deterministic Scenes, and Exact Passes](sections/SECTION_18_DAZ_FOUNDATION_EXACT_TRUTH.md) | 65 | 03, 04, 08, 17 | Move the DAZ subsystem from mostly static/contract evidence to real, reproducible DAZ execution that produces exact single- and multi-person synthetic truth packages with deterministic mapping, render passes, validators, and pilots. |
| 19 | [DAZ Corpus Scale, Training Mixtures, Operations, Currency, and Near-Perfect Targets](sections/SECTION_19_DAZ_SCALE_MIXTURES_OPERATIONS_TARGETS.md) | 43 | 11, 12, 17, 18 | Use DAZ only where the immutable real-data residual-gap report justifies it, prove matched real-only versus mixture value, run resilient unattended operations, maintain current model/assets, and measure optional near-perfect/headline outcomes honestly. |
| 20 | [Immutable Release, Pinned ComfyUI Adoption, Final E2E Proof, Rollback, and Tracker Closure](sections/SECTION_20_IMMUTABLE_RELEASE_FINAL_ADOPTION_CLOSURE.md) | 6 | 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19 | Assemble one immutable MaskFactory release, pin it into the external ComfyUI project, run live accept/failure/abstain/restart/invalidation/rollback scenarios, independently reconstruct the whole system, and close only claims whose exact gates passed. |


## How to use the package

1. Read `00_REVIEW_FINDINGS.md` and `00_GLOBAL_ACCEPTANCE_STANDARD.md`.
2. Start Section 01 only. Create its branch and evidence root from the frozen state.
3. Use the section's mapped tracker table as the exact scope boundary.
4. Produce all required proof artifacts and a `section_acceptance_receipt.json`.
5. Independently review and accept/reject the section.
6. Update tracker state through the tracker CLI, regenerate reports, and commit the accepted receipt.
7. Begin the next section from that accepted commit.

Long-lead inputs may be staged early, but acceptance cannot leapfrog dependencies. The main intentional overlaps are human CVAT work for Section 05, governed asset transfer for Sections 04/06/18, and external Main coordination for Section 16.

## Core release path

Sections 01–17 contain the core product path. Sections 18–19 contain the DAZ/scale and optional independent-accuracy profiles. A core release checkpoint may be issued without overclaiming those optional profiles, but **the entire-project completion requested here is not achieved until Sections 18, 19, and 20 are also accepted**. Section 20 preserves separate profile claims while producing the final whole-project disposition.

## Files in this package

- `00_REVIEW_FINDINGS.md` — verified state and major defects.
- `00_GLOBAL_ACCEPTANCE_STANDARD.md` — universal test, evidence, Git, and DoD rules.
- `sections/SECTION_01...SECTION_20...md` — executable work packets.
- `ITEM_COVERAGE_MAP.md` and `.json` — proof that all 285 unresolved tracker rows are assigned once.
- `SECTION_MANIFEST.json` — machine-readable dependency graph and acceptance metadata.
- `SECTION_ACCEPTANCE_RECEIPT_TEMPLATE.json` — required final receipt structure.
- `USER_AUTHORITY_ACTIONS.md` — consolidated human/source actions that automation cannot fabricate.
