# Section 06 — Provider Runtime Catalog, Model Installation, and Role Qualification

**Acceptance order:** 6 of 20  
**Mapped unresolved tracker items:** 8  
**Current states:** in_progress=2, open=1, partially_complete=5  
**Hard blockers in scope:** 1  
**Rows with explicit Kevin authority/input:** 0  
**Depends on:** Section 03, Section 04, Section 05  
**Enables:** Section 07, Section 08, Section 09, Section 10, Section 12, Section 15, Section 17, Section 18

## Goal

Make every active discovery, segmentation, pose, geometry, boundary, and challenger provider reproducible, isolated, benchmarkable, and rollback-safe.

## Why this section exists

Current provider integrations are mostly implemented but several remain partial because governed installations, isolated runtimes, real holdout benchmarks, and promotion certificates are incomplete.

## Scope

- Preserve the proven PyTorch core while isolating incompatible SAM 3.1, SAM 3D Body, Qwen3-VL, RF-DETR, EoMT/DINOv3, pose, geometry, and PDFNet-equivalent stacks.
- Finish SAM 3.1 refinement, SAM 3D Body geometry, EoMT/DINOv3 challenger, and fine-boundary challenger integrations.
- Build the frozen provider benchmark matrix on identical images/prompts/hardware/truth.
- Measure quality, hard-bucket errors, labor, latency, VRAM, OOM/crash, and determinism.
- Promote winners by role only; prove exact one-command rollback.

## Work packages

1. Create per-provider environment lock and model/checkpoint manifests.
2. Run smoke and negative fixtures for prompts, coordinates, polarity, provenance, output format, and ontology scope.
3. Execute the frozen benchmark matrix against Section-5 human anchors.
4. Predeclare role-specific primary metrics and non-inferiority margins.
5. Issue provider qualification/rollback certificates.

## Section-level testing

- Clean environment install and model-hash validation per provider.
- Coordinate/frame/identity, prompt polarity, PNG, containment, and provenance tests.
- OOM/fallback/timeout/isolation tests; incompatible large models must serialize.
- Frozen benchmark repeatability and complete finite metric checks.
- Negative promotion tests for missing license, hash, benchmark, hard-bucket, 8-GB/approved-runtime, or rollback evidence.

## Integration tests with the rest of the project

- Section 7 can select providers through stable interfaces, not direct model imports.
- Section 9 specialist lanes receive measured role candidates.
- Section 15 serving resolves exact promoted roles and typed fallbacks.

## Definition of done and acceptance criteria

- [ ] Every active provider has a reproducible environment, exact model identity, smoke, benchmark status, and rollback path.
- [ ] The provider benchmark matrix is complete and image-disjoint.
- [ ] No provider is promoted from a model card/download/smoke alone.
- [ ] Role winners and bounded fallbacks are recorded transactionally.
- [ ] All mapped tracker items are complete.

## Required proof artifacts

- `provider_catalog.json`
- `provider_environment_locks/`
- `model_hash_manifest.json`
- `provider_benchmark_matrix.json`
- `provider_qualification_certificates/`
- `rollback_receipts/`
- `section_acceptance_receipt.json`

## Exit procedure

1. Run T0–T5 tests applicable to this section and preserve commands, exits, counts, environment, and hashes.
2. Verify every mapped tracker row against its own exact `Verify:` clause.
3. Produce and independently validate `section_acceptance_receipt.json`.
4. Exercise rollback/invalidation and verify zero leaked resources.
5. Update tracker rows through `Plan/Tracker/tracker.py`; regenerate dashboard/phase/profile reports.
6. Commit only section-scoped source/evidence locators and open the section PR.
7. Begin the next section only from the accepted commit.

## Mapped tracker items

| Item | Phase | Status | % | Hard blocker | Explicit user authority | Work remaining |
|---|---|---|---:|:---:|:---:|---|
| `MF-P0-17.13` | P0 | partially_complete | 97 | No | No | Keep the proven PyTorch 2.11/cu128 core and isolate incompatible SAM 3.1, Qwen3-VL, RF-DETR, EoMT/DINOv3, pose, and geometry stacks |
| `MF-P2-11.04` | P2 | partially_complete | 98 | No | No | Integrate SAM 3.1 point/box/mask refinement and repair proposals behind `InteractiveSegmenter` |
| `MF-P2-11.07` | P2 | in_progress | 90 | No | No | Integrate SAM 3D Body behind `GeometryProvider` while retaining DensePose fallback |
| `MF-P2-11.10` | P2 | in_progress | 90 | No | No | Integrate EoMT/DINOv3 as a trainable challenger contract while retaining SegFormer/Mask2Former baselines |
| `MF-P2-11.13` | P2 | partially_complete | 75 | No | No | Build the frozen SAM/provider benchmark matrix covering SAM2.1, SAM3.1, hybrid discovery/refinement, RF-DETR routes, SAM 3D Body, BiRefNet, and pose variants |
| `MF-P2-11.14` | P2 | partially_complete | 75 | No | No | Measure per-label IoU, boundary-F, small-part/instance recall, bleed, side/front-back errors, anatomy/clothing confusion, hallucinations, QA failures, correction pixels, audit time, VRAM, latency, crash/OOM, and determinism |
| `MF-P2-11.15` | P2 | partially_complete | 95 | Yes | No | Promote winners by role only after primary win/labor reduction plus every hard-label/high-risk non-inferiority margin, then prove one-command rollback |
| `MF-P2-11.18` | P2 | open | 0 | No | No | Integrate PDFNet or its qualified equivalent as an independent fine-boundary challenger |

## Tracker-item exact verification text

### `MF-P0-17.13` — Modern provider catalog, isolated runtimes, and installation evidence

- **Current:** `partially_complete` at 97%
- **Source:** `11_ITEMS_P0_MODERNIZATION_FOUNDATION.md` line 39
- **Requirement:** Keep the proven PyTorch 2.11/cu128 core and isolate incompatible SAM 3.1, Qwen3-VL, RF-DETR, EoMT/DINOv3, pose, and geometry stacks · Verify: lockfiles and cross-runtime smoke matrix prove reproducibility · Blocked by: each provider installation
- **Existing evidence to preserve/revalidate:** env/provider_runtime_matrix.json canonical SHA-256 b6cf5e25a5f98dd421b71998c976b7a6a5e8956fa5dbf4dffb6dd8e4287090ef; ten provider runtimes, eight qualified, two exact pending, zero human gates, twenty-two exact artifacts. MatAnyone2 static and temporal routes are live-qualified; SAM 3.1 point refinement and SAM 3D Body byte-exact repeatability remain honestly pending. Evidence: qa/live_verification/matanyone2_runpod_capability_20260722.json, qa/live_verification/sam2matting_runpod_runtime_20260722.json, qa/live_verification/sam31_runpod_runtime_smoke_20260722.json, qa/live_verification/sam3d_body_runpod_runtime_smoke_20260722.json.

### `MF-P2-11.04` — Provider-neutral discovery, segmentation, pose, and geometry architecture

- **Current:** `partially_complete` at 98%
- **Source:** `13_ITEMS_P2_PROVIDER_MODERNIZATION.md` line 24
- **Requirement:** Integrate SAM 3.1 point/box/mask refinement and repair proposals behind `InteractiveSegmenter` · Verify: prompt polarity, geometry, strict PNG, hash, and containment tests pass · Blocked by: MF-P0-17.04, MF-P2-11.01
- **Existing evidence to preserve/revalidate:** qa/live_verification/sam31_repair_orchestration_20260715.json; qa/live_verification/sam31_official_provider_runtime_contract_20260717.json; qa/live_verification/host_side_shadow_tournament_registration_20260719.json SHA-256 1d896f7ea4e37c10a98be4bfbffa2bd3d390a9ac50e04fc648be6436a9829d56; qa/live_verification/runpod_sam31_provider_canary_failclosed_20260723.json; qa/live_verification/runpod_sam31_discovery_ownership_abstain_20260723.json file SHA-256 2988ec5993288b64f953c89a107de7d2c458c20397b00660c53a4f50334b4c9d; qa/live_verification/runpod_sam31_visual_text_box_hard_qc_pass_20260723.json file SHA-256 08ce61e2678479e8d1a62e44548e2dff336c34de4d5dab1a8ac4d7f713f18979; qa/live_verification/runpod_sam31_runtime_lock_reconciliation_20260723.json self SHA-256 d5fbc1db6d5ff7c507ec5c5edb1f19366d2e3ef64373fde2fb9d26f905fc02cb

### `MF-P2-11.07` — Provider-neutral discovery, segmentation, pose, and geometry architecture

- **Current:** `in_progress` at 90%
- **Source:** `13_ITEMS_P2_PROVIDER_MODERNIZATION.md` line 27
- **Requirement:** Integrate SAM 3D Body behind `GeometryProvider` while retaining DensePose fallback · Verify: coordinate/frame/identity mapping, OOM fallback, and provenance tests pass · Blocked by: governed SAM 3D Body installation
- **Existing evidence to preserve/revalidate:** qa/live_verification/sam3d_body_runpod_runtime_smoke_20260722.json SHA-256 cce59137fde35dd0ef8ae25813ce56807c4f1f9a748659d29338691397cc8a26; env/sam3d_body_runtime.lock.json; env/sam3d_body_runtime.requirements.lock.txt; 10 runner tests and 35 runtime-matrix/fallback tests pass; Ruff/Black/diff checks clean.

### `MF-P2-11.10` — Provider-neutral discovery, segmentation, pose, and geometry architecture

- **Current:** `in_progress` at 90%
- **Source:** `13_ITEMS_P2_PROVIDER_MODERNIZATION.md` line 30
- **Requirement:** Integrate EoMT/DINOv3 as a trainable challenger contract while retaining SegFormer/Mask2Former baselines · Verify: exact ontology vocabulary, checkpoint/config hashes, and isolated runtime contract pass · Blocked by: governed EoMT/DINOv3 environment
- **Existing evidence to preserve/revalidate:** env/eomt_dinov3_runtime.lock.json binds revision 602edaa, exact 93,450,628-byte safetensors/config/preprocessor hashes, Transformers 5.13/cu128 runtime, 65-class ontology hash, training config, smoke, contract, and tests. qa/live_verification/eomt_dinov3_runtime_20260715.json proves deterministic two-run adult-bus CUDA panoptic inference, 700,448,768-byte peak reserved, and 0.039196s warm latency. Contract tests discard the COCO-133 head, require a random 65-class body_parts_v2 head, reject vocabulary/snapshot/authority drift, preserve SegFormer/Mask2Former, and deny pretrained gold authority. Full suite 1095/1095; Ruff clean.

### `MF-P2-11.13` — Provider-neutral discovery, segmentation, pose, and geometry architecture

- **Current:** `partially_complete` at 75%
- **Source:** `13_ITEMS_P2_PROVIDER_MODERNIZATION.md` line 33
- **Requirement:** Build the frozen SAM/provider benchmark matrix covering SAM2.1, SAM3.1, hybrid discovery/refinement, RF-DETR routes, SAM 3D Body, BiRefNet, and pose variants · Verify: identical images/prompts/hardware/QA/truth and immutable matrix manifest · Blocked by: required challenger installations and human-anchor holdout
- **Existing evidence to preserve/revalidate:** qa/governance/benchmark_matrices/provider_benchmark_matrix_v1.json canonical SHA-256 263c4472008b8def97a2d4dcc61fca587b123c7b3109b426e8f525a4eef4464d; qa/live_verification/sam31_production_shadow_orchestration_20260715.json SHA-256 c9ef811e69776bc41bad8a5c8964f615ef4d3de53852d409780bdc2490694df7; aggregate/transaction 62/62 and complete repository 1659/1659 pass. Real human-anchor matrix remains pending.

### `MF-P2-11.14` — Provider-neutral discovery, segmentation, pose, and geometry architecture

- **Current:** `partially_complete` at 75%
- **Source:** `13_ITEMS_P2_PROVIDER_MODERNIZATION.md` line 34
- **Requirement:** Measure per-label IoU, boundary-F, small-part/instance recall, bleed, side/front-back errors, anatomy/clothing confusion, hallucinations, QA failures, correction pixels, audit time, VRAM, latency, crash/OOM, and determinism · Verify: every matrix row has complete finite metrics and artifact hashes · Blocked by: MF-P2-11.13
- **Existing evidence to preserve/revalidate:** qa/live_verification/provider_benchmark_matrix_metrics_contract_20260715.json; dedicated 19/19; focused matrix/specialist/currency 196/196; full repository 1,527/1,527; Ruff/Black/CI/schema checks pass. No synthetic result is claimed as performance evidence.

### `MF-P2-11.15` — Provider-neutral discovery, segmentation, pose, and geometry architecture

- **Current:** `partially_complete` at 95%
- **Source:** `13_ITEMS_P2_PROVIDER_MODERNIZATION.md` line 35
- **Requirement:** Promote winners by role only after primary win/labor reduction plus every hard-label/high-risk non-inferiority margin, then prove one-command rollback · Verify: signed benchmark certificate and rollback evidence pass governance · Blocked by: MF-P2-11.14, MF-P5-10.09 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** All implemented role mutations now require signed matrix-bound evidence and hash-sealed smoke-first transactions, including interactive provider selection across all three authoritative files. qa/live_verification/interactive_provider_transaction_contract_20260715.json SHA-256 70f631c79fab23c5907ebf4fdb7d4711dfee9de13fad77e51a378c234af1963e; 189 focused and full 1653/1653 pass. Remaining 5%: real image-disjoint human-anchor winner certificate and observed live promotion/rollback.

### `MF-P2-11.18` — Provider-neutral discovery, segmentation, pose, and geometry architecture

- **Current:** `open` at 0%
- **Source:** `13_ITEMS_P2_PROVIDER_MODERNIZATION.md` line 38
- **Requirement:** Integrate PDFNet or its qualified equivalent as an independent fine-boundary challenger · Verify: exact checkpoint/runtime evidence and boundary-focused fixtures pass without truth promotion · Blocked by: MF-P2-11.01 and governed installation

