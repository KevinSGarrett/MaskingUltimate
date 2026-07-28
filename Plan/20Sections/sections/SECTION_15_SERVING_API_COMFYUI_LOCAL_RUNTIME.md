# Section 15 — Serving API, Model Registry, Mode A/B ComfyUI Nodes, and Local Runtime

**Acceptance order:** 15 of 20  
**Mapped unresolved tracker items:** 11  
**Current states:** blocked=8, partially_complete=3  
**Hard blockers in scope:** 0  
**Rows with explicit Kevin authority/input:** 4  
**Depends on:** Section 06, Section 10, Section 12, Section 14  
**Enables:** Section 16, Section 17, Section 20

## Goal

Deliver the complete local MaskFactory serving and ComfyUI integration surface against promoted champions, with read-only package behavior, typed fallback, measured latency, unseen-input workflows, v2 compatibility, and rollback.

## Why this section exists

Health/models paths mostly exist, but `/predict`, champion residency, target latency, Mode A/Mode B workflows, and live unseen-image proof remain blocked until Section 12 champions and Section 14 acceptance evidence are available.

## Scope

- Complete FastAPI `/health`, `/models`, `/predict`, and `/refine` contracts.
- Load only exact champion roles; use SAM 3.1 first and SAM2.1 only as typed bounded fallback/rollback.
- Complete Mode A node pack and gold-hand workflow.
- Complete Mode B predict/inpaint workflows on never-seen inputs.
- Enforce read-only source-package behavior and output provenance.
- Measure cold/warm latency, VRAM, OOM, determinism, restart, and rollback for v1/v2 single/multi-person routes.

## Work packages

1. Bind service startup to exact model/config/ontology/runtime manifests.
2. Implement/repair prediction and refine paths, schemas, error states, and resource serialization.
3. Finalize workflows and node validation.
4. Execute live unseen single-person and bounded multi-person inputs.
5. Run CVAT migration/rollback assistance verification where required.

## Section-level testing

- API schema, multipart/base64/manifest, strict PNG, visibility/area/provenance, timeout, and error tests.
- Champion-only residency and typed fallback/rollback tests.
- Warm/cold latency and VRAM measurements under governed hardware.
- Mode A package read-only and output-directory mutation tests.
- Mode B never-seen predict/inpaint E2E, restart/retry/idempotency, and invalid input tests.
- Ontology v1/v2 compatibility and one-command rollback.

## Integration tests with the rest of the project

- Section 16 consumes stable Mode A/Mode B contracts.
- Section 17 exercises the same service with multi-person identity requirements.
- Section 20 pins exact API/node/workflow/package hashes.

## Required user/authority actions

- Supply/approve a genuinely never-seen governed image and perform any explicitly required interactive ComfyUI confirmation.

## Definition of done and acceptance criteria

- [ ] All required endpoints and nodes work against promoted champions.
- [ ] Latency/residency targets are measured and accepted or explicitly revised through authority—not hand-waved.
- [ ] Never-seen Mode B and gold-package Mode A workflows pass end to end.
- [ ] Read-only, fallback, restart, and rollback behaviors pass.
- [ ] P6 legacy exit and all mapped tracker items are accepted without claiming whole-project completion.

## Required proof artifacts

- `service_api_contract_receipt.json`
- `model_residency_manifest.json`
- `latency_vram_report.json`
- `mode_a_workflow_receipt.json`
- `mode_b_unseen_workflow_receipt.json`
- `read_only_audit.json`
- `service_rollback_receipt.json`
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
| `MF-P6-01.07` | P6 | blocked | 92 | No | Yes | Author `maskfactory_nodes\workflows\wf_inpaint_gold_hand.json` · runs end-to-end in ComfyUI (gold left_hand d8f4 inpaint chain) |
| `MF-P6-02.01` | P6 | blocked | 99 | No | Yes | `serve\api.py`: GET /health (versions, loaded models, VRAM) · GET /models (registry roles + champions) · POST /predict (multipart image + labels/return/inpaint params → base64 PNGs + manifest-lite JSON with per-label visibility guess, areas, provenance) · POST /refine (image + label + clicks → SAM2 single-part refine) |
| `MF-P6-02.03` | P6 | blocked | 99 | No | No | Model residency per doc 05 §5 schedule: champion body-part + hand specialist + clothing parser sequential slots · production `/refine` resolves the governed RunPod interactive role (SAM 3.1 first); SAM2.1 is loaded only for an explicitly typed bounded fallback/rollback |
| `MF-P6-02.05` | P6 | blocked | 85 | No | Yes | Latency measured: /predict warm ≤ 4 s all-labels · ≤ 2 s single-label · /refine ≤ 1.2 s/click · cold start ≤ 60 s |
| `MF-P6-03.02` | P6 | blocked | 98 | No | No | Author + verify `wf_bodypart_conditioned.json` (visible_body_skin − clothing_visible via Mask From Label Map → skin-only img2img) |
| `MF-P6-03.03` | P6 | blocked | 92 | No | Yes | Author + verify `wf_live_predict_inpaint.json` on a NEVER-SEEN image (LoadImage → Predict left_forearm → inpaint) — this run is the **D8** demonstration |
| `MF-P6-05.07` | P6 | blocked | 0 | No | No | Re-run latency/residency and Mode A/Mode B end-to-end tests |
| `MF-P6-06.03` | P6 | partially_complete | 90 | No | No | Select SAM 3.1 first on the RunPod production route; retain SAM2.1 only as a typed bounded fallback/benchmark/rollback and local `pth-sam2` only as optional CVAT assistance |
| `MF-P6-06.07` | P6 | partially_complete | 85 | No | No | Complete parallel CVAT upgrade migration/rollback and verify SAM2/SAM3 assistance against preserved task data |
| `MF-P6-06.08` | P6 | partially_complete | 80 | No | No | Run provider-neutral Mode B prediction/refine and Mode A package workflows on unseen single/multi-person inputs, measuring warm/cold latency, VRAM, OOM, determinism, provenance, and rollback |
| `MF-P6-EXIT` | P6 | blocked | 0 | No | No | **D8** demonstrated live for the optional legacy lane (Mode A + Mode B workflows) · doc 14 §7 checkboxes updated · This item does not define project-wide or `core_autonomous_runtime` completion; the required adopted bridge exit is `MF-P6-12.06` |

## Tracker-item exact verification text

### `MF-P6-01.07` — Node pack Mode A

- **Current:** `blocked` at 92%
- **Source:** `07_ITEMS_P6_COMFYUI_SERVING.md` line 16
- **Requirement:** Author `maskfactory_nodes\workflows\wf_inpaint_gold_hand.json` · runs end-to-end in ComfyUI (gold left_hand d8f4 inpaint chain)
- **Current blocked reason:** NEEDS KEVIN: end-to-end wf_inpaint_gold_hand verification requires a real human-anchor or autonomous-certified left-hand package plus interactive ComfyUI confirmation; no eligible package exists.

### `MF-P6-02.01` — FastAPI inference service

- **Current:** `blocked` at 99%
- **Source:** `07_ITEMS_P6_COMFYUI_SERVING.md` line 19
- **Requirement:** `serve\api.py`: GET /health (versions, loaded models, VRAM) · GET /models (registry roles + champions) · POST /predict (multipart image + labels/return/inpaint params → base64 PNGs + manifest-lite JSON with per-label visibility guess, areas, provenance) · POST /refine (image + label + clicks → SAM2 single-part refine)
- **Current blocked reason:** AWAITING_RUNTIME: Mode B /predict needs promoted champion_bodypart+champion_hand+champion_clothing. challenger_bodypart installed from CAA torso train; matrix-bundle promote + hand/clothing certification still missing. Force-register forbidden. Not NEEDS KEVIN.
- **Existing evidence to preserve/revalidate:** qa/live_verification/mode_b_champions_caa_mapping_20260721T090135Z.json;qa/live_verification/mode_b_champions_caa_mapping_latest.json;qa/live_verification/caa_truth_tier_gold_mapping_latest.json

### `MF-P6-02.03` — FastAPI inference service

- **Current:** `blocked` at 99%
- **Source:** `07_ITEMS_P6_COMFYUI_SERVING.md` line 21
- **Requirement:** Model residency per doc 05 §5 schedule: champion body-part + hand specialist + clothing parser sequential slots · production `/refine` resolves the governed RunPod interactive role (SAM 3.1 first); SAM2.1 is loaded only for an explicitly typed bounded fallback/rollback
- **Current blocked reason:** AWAITING_RUNTIME: sequential champion slots require trained promoted champion_bodypart/hand/clothing; champions=0. CAA truth_tier gold corpus ready; OpenMMLab train stack not ready on pod.
- **Existing evidence to preserve/revalidate:** qa/live_verification/mode_b_champions_caa_mapping_latest.json

### `MF-P6-02.05` — FastAPI inference service

- **Current:** `blocked` at 85%
- **Source:** `07_ITEMS_P6_COMFYUI_SERVING.md` line 23
- **Requirement:** Latency measured: /predict warm ≤ 4 s all-labels · ≤ 2 s single-label · /refine ≤ 1.2 s/click · cold start ≤ 60 s
- **Current blocked reason:** NEEDS KEVIN: /refine warm latency and the WSL serving boundary pass, but /predict latency targets require real trained champion_bodypart/champion_hand/champion_clothing roles from P5.
- **Existing evidence to preserve/revalidate:** qa/live_verification/provider_neutral_workflow_performance_contract_20260715.json plus historical qa/live_verification/serve_refine_cuda_20260712.json. Policy/test enforcement passes; real all-label and single-label champion /predict measurements remain unclaimed.

### `MF-P6-03.02` — Mode B node + shipped workflows

- **Current:** `blocked` at 98%
- **Source:** `07_ITEMS_P6_COMFYUI_SERVING.md` line 28
- **Requirement:** Author + verify `wf_bodypart_conditioned.json` (visible_body_skin − clothing_visible via Mask From Label Map → skin-only img2img)
- **Current blocked reason:** The graph and exact pixel-isolation behavior are live-verified on a non-gold in-review package. Final completion requires rerunning the shipped workflow against an eligible human-anchor or autonomous-certified package; Kevin is needed only if interactive confirmation is reserved.
- **Existing evidence to preserve/revalidate:** qa/live_verification/comfy_bodypart_conditioned_draft_smoke_20260713.json; prompt 9c0f34f6-d5f9-41b3-bd92-bfd4f7e9df2f; workflow hash 8237e3d43bbdb6618b66b8397380ac7f3e395c5d0ef92c57c8943b8c72839af1; 30 focused tests passed; Ruff/Black clean.

### `MF-P6-03.03` — Mode B node + shipped workflows

- **Current:** `blocked` at 92%
- **Source:** `07_ITEMS_P6_COMFYUI_SERVING.md` line 29
- **Requirement:** Author + verify `wf_live_predict_inpaint.json` on a NEVER-SEEN image (LoadImage → Predict left_forearm → inpaint) — this run is the **D8** demonstration
- **Current blocked reason:** NEEDS KEVIN: D8 never-seen-image workflow requires a new Kevin-supplied governed image, trained champion prediction, and Kevin's interactive ComfyUI run.

### `MF-P6-05.07` — Ontology-v2 registry, serving, and ComfyUI

- **Current:** `blocked` at 0%
- **Source:** `17_ITEMS_P6_MODERN_SERVING.md` line 17
- **Requirement:** Re-run latency/residency and Mode A/Mode B end-to-end tests · Verify: live evidence binds champion, ontology, runtime, input, output, latency, and VRAM hashes · Blocked by: v2 promoted champion and reviewed v2 package
- **Current blocked reason:** Live ontology-v2 Mode A/Mode B latency/residency evidence requires an activated v2 champion and reviewed v2 package.
- **Existing evidence to preserve/revalidate:** qa/live_verification/provider_neutral_workflow_performance_contract_20260715.json proves the pre-result evidence contract only; live v2 measurements remain absent.

### `MF-P6-06.03` — Provider-neutral runtime, truth provenance, and safe CVAT publication

- **Current:** `partially_complete` at 90%
- **Source:** `17_ITEMS_P6_MODERN_SERVING.md` line 22
- **Requirement:** Select SAM 3.1 first on the RunPod production route; retain SAM2.1 only as a typed bounded fallback/benchmark/rollback and local `pth-sam2` only as optional CVAT assistance · Verify: production selection rejects SAM2-first routes and fallback/rollback requires exact failure evidence · Blocked by: MF-P2-11.15
- **Existing evidence to preserve/revalidate:** Provider-neutral S07/S08 plus signed interactive transaction/rollback: qa/live_verification/provider_neutral_batch_interactive_runtime_20260715.json and qa/live_verification/interactive_provider_transaction_contract_20260715.json SHA-256 70f631c79fab23c5907ebf4fdb7d4711dfee9de13fad77e51a378c234af1963e. 189 focused and full 1653/1653 pass. Remaining 10%: official checkpoint, real benchmark winner, live production smoke/promotion, and observed rollback.

### `MF-P6-06.07` — Provider-neutral runtime, truth provenance, and safe CVAT publication

- **Current:** `partially_complete` at 85%
- **Source:** `17_ITEMS_P6_MODERN_SERVING.md` line 26
- **Requirement:** Complete parallel CVAT upgrade migration/rollback and verify SAM2/SAM3 assistance against preserved task data · Verify: live versioned smoke and rollback evidence pass · Blocked by: MF-P0-17.12 and installed SAM 3.1
- **Existing evidence to preserve/revalidate:** qa/live_verification/cvat_parallel_assistance_recovery_bundle_20260715.json; versions 2.24.0/2.69.0, identical 21 tasks/21 jobs/367 shapes, target SAM2 strict 256x256 mask SHA-256 48a57d6a... in 4.219s, target-only rollback and 18-service restart pass; 49 focused tests pass. SAM3.1 remains gated.

### `MF-P6-06.08` — Provider-neutral runtime, truth provenance, and safe CVAT publication

- **Current:** `partially_complete` at 80%
- **Source:** `17_ITEMS_P6_MODERN_SERVING.md` line 27
- **Requirement:** Run provider-neutral Mode B prediction/refine and Mode A package workflows on unseen single/multi-person inputs, measuring warm/cold latency, VRAM, OOM, determinism, provenance, and rollback · Verify: live evidence satisfies frozen performance contracts · Blocked by: promoted role champions and governed unseen sources
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: src/maskfactory/serve/static_contracts.py plus serving schemas, node-pack inventory, provenance/route enforcement, and six-case execution preflight are hash-bound. Evidence qa/live_verification/serving_static_contracts_20260719.json; live champion execution and rollback remain open.

### `MF-P6-EXIT` — Read-only enforcement audit

- **Current:** `blocked` at 0%
- **Source:** `07_ITEMS_P6_COMFYUI_SERVING.md` line 37
- **Requirement:** **D8** demonstrated live for the optional legacy lane (Mode A + Mode B workflows) · doc 14 §7 checkboxes updated · This item does not define project-wide or `core_autonomous_runtime` completion; the required adopted bridge exit is `MF-P6-12.06`
- **Current blocked reason:** D8 requires live Mode A and Mode B demonstrations after certified packages and trained promoted champions exist; Kevin is needed only for any explicitly reserved interactive confirmation.

