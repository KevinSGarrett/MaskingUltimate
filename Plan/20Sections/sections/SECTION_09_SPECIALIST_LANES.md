# Section 09 — Specialist Anatomy, Clothing, Hair, Pose, and Geometry Lanes

**Acceptance order:** 9 of 20  
**Mapped unresolved tracker items:** 9  
**Current states:** partially_complete=9  
**Hard blockers in scope:** 1  
**Rows with explicit Kevin authority/input:** 0  
**Depends on:** Section 06, Section 07, Section 08  
**Enables:** Section 10, Section 11, Section 12, Section 15, Section 17

## Goal

Finish and qualify role-specific specialist lanes for hard anatomy, boundaries, pose, geometry, clothing, accessories, repeated instances, and independent votes without allowing unmeasured model substitution.

## Why this section exists

The specialist architecture is largely present, but nine modernization/benchmark/evidence items remain partial and cannot be accepted until real role-specific holdout results and rollback evidence exist.

## Scope

- Integrate and evaluate SAM 3.1 candidates in every relevant specialist lane.
- Evaluate optional low-memory variants only as explicitly labeled experiments.
- Benchmark BiRefNet variants, ViTMatte, pose challengers, SAM 3D Body, DensePose, and MediaPipe vote value.
- Freeze hard-class/context non-inferiority margins before opening results.
- Publish overlays, disagreements, correction-pixel deltas, and review-time effects.

## Work packages

1. Create lane-specific benchmark manifests and hard-bucket datasets.
2. Run identical evidence through incumbent and challenger providers.
3. Perform vote-ablation and fallback/rollback tests.
4. Promote only measured winners with exact role/lifecycle records.
5. Update the specialist leaderboard/evidence package.

## Section-level testing

- Hand/finger, foot/toe, hair, clothing/skin, side, rear/front, contact, occlusion, crop, and crowd fixtures.
- Per-lane boundary, leakage, identity, laterality, latency, VRAM, OOM, determinism, and labor metrics.
- No-silent-substitution tests for official versus optional implementations.
- Promotion rejection tests for missing hard-bucket non-inferiority or rollback.
- Independent vote-ablation and geometry-to-image consistency tests.

## Integration tests with the rest of the project

- Section 10 visual panels identify the exact specialist candidate and person/label.
- Section 12 training can compare specialist challengers under the same frozen truth.
- Section 17 multi-person runtime preserves provider family and instance identity.

## Definition of done and acceptance criteria

- [ ] Every enabled specialist lane has a current measured role decision.
- [ ] All hard-class/context margins are frozen and satisfied or the route remains fallback/disabled.
- [ ] Evidence includes overlays, disagreements, labor impact, and rollback.
- [ ] All nine mapped tracker items are complete.

## Required proof artifacts

- `specialist_benchmark_manifest.json`
- `specialist_metrics.json`
- `vote_ablation_report.json`
- `specialist_role_decisions.json`
- `specialist_rollback_receipts/`
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
| `MF-P3-08.01` | P3 | partially_complete | 90 | No | No | Add SAM 3.1 discovery/refinement candidates to hand/finger, chest/pelvic, hair, feet/toes, clothing, accessory, and repeated-instance lanes |
| `MF-P3-08.02` | P3 | partially_complete | 95 | No | No | Evaluate SAM3-LiteText only as an optional lower-memory experiment and never a substitute for official SAM 3.1 |
| `MF-P3-08.03` | P3 | partially_complete | 80 | No | No | Benchmark BiRefNet Dynamic/HR/HR-matting against BiRefNet-general and ViTMatte for silhouette, hair edge, and matting roles |
| `MF-P3-08.04` | P3 | partially_complete | 80 | No | No | Benchmark RTMW-X/RTMO against DWPose for whole-body, hands/feet, rear, contact, occlusion, and crowded scenes |
| `MF-P3-08.05` | P3 | partially_complete | 80 | No | No | Benchmark SAM 3D Body against DensePose for geometry priors, contact/occlusion, rear/front, and multi-person identity |
| `MF-P3-08.06` | P3 | partially_complete | 80 | No | No | Keep MediaPipe Hands as an independent handedness/landmark vote and measure its incremental value |
| `MF-P3-08.08` | P3 | partially_complete | 90 | No | No | Define role-specific non-inferiority margins for every hard specialist class/context before opening benchmark results |
| `MF-P3-08.09` | P3 | partially_complete | 90 | Yes | No | Promote no specialist from model card/download/smoke alone; require measured winner, complete license/content/runtime hashes, reliable 8 GB operation or approved alternate runtime, and rollback |
| `MF-P3-08.10` | P3 | partially_complete | 75 | No | No | Publish specialist overlays, disagreements, correction-pixel deltas, and review-time impact to the leaderboard/evidence package |

## Tracker-item exact verification text

### `MF-P3-08.01` — Modern specialist integration and role-specific evidence

- **Current:** `partially_complete` at 90%
- **Source:** `14_ITEMS_P3_MODERN_SPECIALISTS.md` line 12
- **Requirement:** Add SAM 3.1 discovery/refinement candidates to hand/finger, chest/pelvic, hair, feet/toes, clothing, accessory, and repeated-instance lanes · Verify: each lane emits isolated strict candidates with exact provenance · Blocked by: MF-P2-11.03, MF-P2-11.04
- **Existing evidence to preserve/revalidate:** qa/live_verification/sam31_specialist_route_rejection_20260722.json SHA-256 9d4e29831836b1d7104b155b522980abbbb289112b4ce47d593d1cc055eabf2b; 99 focused production/SAM31 tests pass; Ruff, Black, JSON parse, and diff integrity pass. Live visual panel hash c3af40756d864d307e3ded06948beead0ae734610395af38ce61af1f5b96ac5e. Prior evidence remains in OPS_LOG and changelog.

### `MF-P3-08.02` — Modern specialist integration and role-specific evidence

- **Current:** `partially_complete` at 95%
- **Source:** `14_ITEMS_P3_MODERN_SPECIALISTS.md` line 13
- **Requirement:** Evaluate SAM3-LiteText only as an optional lower-memory experiment and never a substitute for official SAM 3.1 · Verify: registry state/role tests prevent silent substitution · Blocked by: governed optional installation
- **Existing evidence to preserve/revalidate:** qa/live_verification/sam3_litetext_reviewed_s02_20260715.json (file SHA-256 2fb9ecb8012eb89e8bf39a384fb2b576b8d0c84a5d588e66ac1ad7d3687660bf; manifest ff3b6244...); frozen policy f42edcfc... committed pre-result at 17728d61...; persisted masks 9214ef4b... and e49aa536...; 10 dedicated and 1616/1616 complete repository tests pass. Prior installation evidence remains qa/live_verification/sam3_litetext_installation_bundle_20260715.json. No official SAM3.1/lower-memory/noninferiority/gold/promotion claim.

### `MF-P3-08.03` — Modern specialist integration and role-specific evidence

- **Current:** `partially_complete` at 80%
- **Source:** `14_ITEMS_P3_MODERN_SPECIALISTS.md` line 14
- **Requirement:** Benchmark BiRefNet Dynamic/HR/HR-matting against BiRefNet-general and ViTMatte for silhouette, hair edge, and matting roles · Verify: frozen role-specific metrics include boundary quality, leakage, latency, VRAM, and determinism · Blocked by: MF-P2-11.08 and human-anchor holdout
- **Existing evidence to preserve/revalidate:** Frozen silhouette_variant_benchmark_v1 canonical SHA-256 04a13fef0de84b0db3895437163b33866ca1a553b916a5b1397681f84972ebab; exact five-provider/three-role/eight-route matrix across five hard contexts, pixel/boundary/leakage/correction/alpha/runtime denominators, role-specific incumbent fallback drills, schemas, recomputing CLI, named CI gate, and 29 dedicated/71 focused/1,309 full tests pass. Evidence qa/live_verification/silhouette_variant_benchmark_contract_20260715.json. Real image-disjoint human-anchor observations and reviewed auxiliary alpha references remain pending; no winner or promotion claimed.

### `MF-P3-08.04` — Modern specialist integration and role-specific evidence

- **Current:** `partially_complete` at 80%
- **Source:** `14_ITEMS_P3_MODERN_SPECIALISTS.md` line 15
- **Requirement:** Benchmark RTMW-X/RTMO against DWPose for whole-body, hands/feet, rear, contact, occlusion, and crowded scenes · Verify: per-joint/side/context metrics and fallback evidence are complete · Blocked by: MF-P2-11.06 and human-anchor holdout
- **Existing evidence to preserve/revalidate:** Frozen pose_variant_benchmark_v1 canonical SHA-256 3791ffe1f527a465d06d271aaca585fdf16253584667797a49b07adab10c8517; exact 133-joint RTMW-X and 14-joint RTMO measurement matrices across all seven required contexts, explicit PCK/side/identity/runtime denominators, DWPose fallback drills, schemas, recomputing CLI, named CI gate, and 23 dedicated/52 focused/1,280 full tests pass. Evidence qa/live_verification/pose_variant_benchmark_contract_20260715.json. Real image-disjoint human-anchor pose holdout observations remain pending; no winner or promotion claimed.

### `MF-P3-08.05` — Modern specialist integration and role-specific evidence

- **Current:** `partially_complete` at 80%
- **Source:** `14_ITEMS_P3_MODERN_SPECIALISTS.md` line 16
- **Requirement:** Benchmark SAM 3D Body against DensePose for geometry priors, contact/occlusion, rear/front, and multi-person identity · Verify: geometry-to-image consistency, bleed, side, latency, and OOM metrics are complete · Blocked by: MF-P2-11.07 and human-anchor holdout
- **Existing evidence to preserve/revalidate:** 2026-07-15: geometry_variant_benchmark_v1 canonical SHA-256 98810aa56d85381ec1f792edf6308f6f4bc1741304cccae312868716a6316aef binds nine contexts, exact artifact/runtime identities, projection/visibility/bleed/side/front-back/identity/QA denominators, latency/VRAM/OOM/determinism, 8 GiB gate, and DensePose fallback. Dedicated 30/30, focused 139/139, full 1445/1445 exit 0; Ruff/Black/CI YAML pass. Signed currency review d581b0d6fda7d26e99ecda00 verifies and remains honestly FAIL. qa/live_verification/geometry_variant_benchmark_contract_20260715.json.

### `MF-P3-08.06` — Modern specialist integration and role-specific evidence

- **Current:** `partially_complete` at 80%
- **Source:** `14_ITEMS_P3_MODERN_SPECIALISTS.md` line 17
- **Requirement:** Keep MediaPipe Hands as an independent handedness/landmark vote and measure its incremental value · Verify: vote-ablation benchmark and side-swap fixtures pass · Blocked by: human-anchor hand set
- **Existing evidence to preserve/revalidate:** qa/live_verification/mediapipe_vote_ablation_contract_20260715.json; frozen policy canonical SHA-256 8589e73549b26529505e4888e504cfe5024c1cb6c2bb21b2578ab71746e6f1c2; schemas, evaluator, one-command tool, named CI gate, 16/16 dedicated and 53/53 focused tests pass; full repository 1,240/1,240; Ruff and targeted Black clean. No real benchmark, promotion, serving, certificate, or gold claim.

### `MF-P3-08.08` — Modern specialist integration and role-specific evidence

- **Current:** `partially_complete` at 90%
- **Source:** `14_ITEMS_P3_MODERN_SPECIALISTS.md` line 19
- **Requirement:** Define role-specific non-inferiority margins for every hard specialist class/context before opening benchmark results · Verify: frozen benchmark manifest contains margins and cannot be edited post-results · Blocked by: MF-P2-11.13
- **Existing evidence to preserve/revalidate:** specialist_margins_v1 canonical SHA-256 605f79e0d4f8354a7a4d445a0a5725af829cd78b85e2e36f91b065576553a739; provider_benchmark_matrix_v1 canonical SHA-256 263c4472008b8def97a2d4dcc61fca587b123c7b3109b426e8f525a4eef4464d; qa/live_verification/sam31_production_shadow_orchestration_20260715.json SHA-256 c9ef811e69776bc41bad8a5c8964f615ef4d3de53852d409780bdc2490694df7. Remaining 10% is the actual image-disjoint human-anchor result binding.

### `MF-P3-08.09` — Modern specialist integration and role-specific evidence

- **Current:** `partially_complete` at 90%
- **Source:** `14_ITEMS_P3_MODERN_SPECIALISTS.md` line 20
- **Requirement:** Promote no specialist from model card/download/smoke alone; require measured winner, complete license/content/runtime hashes, reliable 8 GB operation or approved alternate runtime, and rollback · Verify: promotion negative fixtures reject every missing prerequisite · Blocked by: MF-P0-16.11, MF-P3-08.08 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** src/maskfactory/providers/promotion.py validates hash-bound specialist packets against benchmarked lifecycle, exact provenance hashes, resolved checkpoint license, frozen benchmark margins/results, deterministic resource reliability, and distinct rollback/restore evidence. Dedicated negative cases reject missing prerequisites, weak evidence, hard-bucket loss, runtime failure, and tampering.

### `MF-P3-08.10` — Modern specialist integration and role-specific evidence

- **Current:** `partially_complete` at 75%
- **Source:** `14_ITEMS_P3_MODERN_SPECIALISTS.md` line 21
- **Requirement:** Publish specialist overlays, disagreements, correction-pixel deltas, and review-time impact to the leaderboard/evidence package · Verify: evidence schema and frozen benchmark report cover every enabled lane · Blocked by: MF-P3-08.03 through MF-P3-08.06
- **Existing evidence to preserve/revalidate:** qa/live_verification/specialist_evidence_package_contract_20260715.json; all 9 frozen specialist roles are mandatory; 17/17 dedicated and 79/79 focused specialist/leaderboard tests pass; full repository 1,257/1,257; Ruff, targeted Black, CI YAML clean. No real all-lane report, promotion, serving, certificate, or gold authority claimed.

