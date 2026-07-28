# Section 16 — Cross-Project Comfy_UI_Main Bridge, Adoption Semantics, Feedback, and Recovery

**Acceptance order:** 16 of 20  
**Mapped unresolved tracker items:** 13  
**Current states:** blocked=13  
**Hard blockers in scope:** 3  
**Rows with explicit Kevin authority/input:** 0  
**Depends on:** Section 14, Section 15  
**Enables:** Section 20

## Goal

Complete the external consumer adapter and two-way release/adoption/feedback/recovery contract between MaskFactory and `C:\Comfy_UI_Main` without allowing dirty bytes, unsigned packages, or ambiguous receipts to confer authority.

## Why this section exists

All 13 mapped bridge/qualification items are blocked. Local MaskFactory nodes are not the same as a pinned external Main adoption, and the project cannot be complete until the consumer verifies the exact immutable producer release.

## Scope

- Implement the external Main adapter for Mode A packages and Mode B service calls.
- Implement signed release/adoption receipts, arbitration, invalidation, revocation, and compatibility checks.
- Implement feedback, repair requests, durable journal, idempotency, restart recovery, and failure controls.
- Run single-person and multi-person vertical slices in both modes.
- Run cross-project qualification and release/adoption handoff against pinned commits and exact packages.

## Work packages

1. Freeze producer/consumer API, package, ontology, provider, error, timeout, and authority contracts.
2. Implement Main-side verification before any mask consumption.
3. Persist request/adoption/feedback/recovery state in both projects.
4. Test invalid, stale, revoked, incompatible, partial, duplicate, and ambiguous receipts.
5. Produce the core bridge release handoff required by MF-P6-12.06.

## Section-level testing

- Mode A exact package read, verify, consume, feedback, invalidation, and restart tests.
- Mode B health/predict/refine, timeout/retry/idempotency, service restart, and rollback tests.
- Receipt signature/hash/canonicalization/arbitration negative fixtures.
- Journal crash/replay, duplicate request, stale terminal, partial write, and ambiguity tests.
- Single- and multi-person cross-project qualification with exact source/mask/metadata/error hashes.

## Integration tests with the rest of the project

- The Main consumer accepts only the Section-15 contract and Section-14 evidence-bound producer release.
- Feedback returns to MaskFactory without mutating frozen packages.
- Section 20 can pin both producer and consumer commits and replay adoption.

## Definition of done and acceptance criteria

- [ ] The external Main adapter exists and is source-controlled in the correct repository/session.
- [ ] Mode A and Mode B vertical slices pass with signed receipts.
- [ ] Feedback, journal, invalidation, restart, and rollback are durable and idempotent.
- [ ] Cross-project qualification passes and MF-P6-12.06 is accepted.
- [ ] All 13 mapped tracker items are complete.

## Required proof artifacts

- `bridge_contract_freeze.json`
- `main_adapter_test_receipt.json`
- `mode_a_cross_project_receipt.json`
- `mode_b_cross_project_receipt.json`
- `feedback_journal_recovery_report.json`
- `cross_project_qualification_packet.json`
- `core_bridge_handoff_receipt.json`
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
| `MF-P6-11.01` | P6 | blocked | 88 | No | No | Implement the external main-controller `MaskFactoryAdapter` boundary so durable orchestration never depends on ComfyUI node IDs or MaskFactory internal paths |
| `MF-P6-11.02` | P6 | blocked | 88 | Yes | No | Implement Mode A immutable package reads with source/package/mask/revocation/instance/ontology/transform validation and no write path; cap raw manifest/status/reference evidence at noncertified and require a separate active exact operational wrapper for production use |
| `MF-P6-11.03` | P6 | blocked | 79 | No | No | Implement Mode B localhost health/capability/predict/refine client with timeouts, closed responses, request hashing, and draft-only default authority |
| `MF-P6-11.04` | P6 | blocked | 80 | No | No | Normalize and arbitrate eligible Mode A and Mode B receipts by exact scope, authority, QA, freshness, preservation risk, and cost; never compare incompatible latents or silently weaken requirements |
| `MF-P6-11.05` | P6 | blocked | 88 | No | No | Implement authenticated, replay-protected downstream repair/quality feedback bound to exact parent receipt/release/capability/policy/certificate/source/owner/transform/QA/protected state and hypothesis budget that MaskFactory may validate, reject, mine, or use to create a new candidate without mutating frozen packages/certificates or creating truth |
| `MF-P6-11.06` | P6 | blocked | 90 | No | No | Implement trusted-signed/checkpointed append-only bridge journaling, idempotency, and a closed durable state machine across admit, route, lease, submit-known/unknown, reconcile, result, validate, cache/decision, feedback, adoption, invalidation, retry/repair, recovery, and rollback |
| `MF-P6-11.07` | P6 | blocked | 84 | Yes | No | Add bounded transient retries, circuit breaker, deadline/resource enforcement, scoped DAG blocking, and explicit no-silent-fallback behavior |
| `MF-P6-11.08` | P6 | blocked | 86 | No | No | Add receipt-last atomic commit, restart recovery with `outcome_unknown` reconciliation before retry, health/capability/revocation-at-decision evidence, cache freshness, and service/node-pack drift detection; frozen v1 GPU-lease fields are telemetry-only compatibility and can never gate recovery |
| `MF-P6-12.02` | P6 | blocked | 84 | No | No | Run the single-person Mode A vertical slice from adopted package/certificate through adapter binding into a downstream ComfyUI inpaint/edit pass |
| `MF-P6-12.03` | P6 | blocked | 80 | No | No | Run the overlapping/contact two-person Mode A vertical slice with distinct character instances, skeleton/ownership masks, protected regions, and transform chains |
| `MF-P6-12.04` | P6 | blocked | 86 | No | No | Run Mode B health/predict/refine as draft, prove service-down behavior, and when eligible pass an exact original prediction through a subsequent independent operational-certification transaction |
| `MF-P6-12.05` | P6 | blocked | 83 | Yes | No | Execute the cross-project compatibility, trust/canonicalization, encoded/pixel identity, image/video-time, ownership, authority/training-truth firewall, executable geometry, idempotency, signed-journal, outage, submitted-unknown restart, cache, invalidation, rollback, and no-silent-fallback qualification matrix |
| `MF-P6-12.06` | P6 | blocked | 78 | No | No | Publish the final MaskFactory release and main-project adoption/handoff receipts, regenerate tracker reports, and close only `core_autonomous_runtime` when its exact gates pass |

## Tracker-item exact verification text

### `MF-P6-11.01` — Mode A/Mode B runtime adapter, feedback, and recovery

- **Current:** `blocked` at 88%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 46
- **Requirement:** Implement the external main-controller `MaskFactoryAdapter` boundary so durable orchestration never depends on ComfyUI node IDs or MaskFactory internal paths · Verify: adapter interface tests use only adopted contracts and reject direct dirty-worktree/internal-module coupling · Blocked by: MF-P6-10.05
- **Current blocked reason:** AWAITING_MAIN/STATIC_PASS: external sibling consumer proves contracts-only boundary from outside the producer tree; no real Comfy_UI_Main-signed adapter execution.
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: tests/test_external_adapter_conformance.py + fixture_main harness (main_adoption_complete=false). Not PRODUCTION_EVIDENCE_PASS.

### `MF-P6-11.02` — Mode A/Mode B runtime adapter, feedback, and recovery

- **Current:** `blocked` at 88%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 47
- **Requirement:** Implement Mode A immutable package reads with source/package/mask/revocation/instance/ontology/transform validation and no write path; cap raw manifest/status/reference evidence at noncertified and require a separate active exact operational wrapper for production use · Verify: valid wrapper-certified single-/multi-person reads pass while raw-status escalation, path escape, hash drift, stale/out-of-scope wrapper, wrong owner, and mutation attempts fail · Blocked by: MF-P6-09.05, MF-P6-11.01 · HARD BLOCKER
- **Current blocked reason:** DEPENDENCY/CROSS-PROJECT/STATIC_PASS: MF-P6-11.01 incomplete. Additive Mode A immutable package-read evidence is fixture-verified (STATIC_PASS). No accepted production adopted-package/exact operational-wrapper authority (not fabricated).
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: tests/test_mode_a_package_read.py + fixture_main. Not PRODUCTION_EVIDENCE_PASS.

### `MF-P6-11.03` — Mode A/Mode B runtime adapter, feedback, and recovery

- **Current:** `blocked` at 79%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 48
- **Requirement:** Implement Mode B localhost health/capability/predict/refine client with timeouts, closed responses, request hashing, and draft-only default authority · Verify: unavailable/malformed/timeout/unsupported-label cases return typed errors and raw predictions cannot satisfy promotion · Blocked by: MF-P6-09.06, MF-P6-11.01
- **Current blocked reason:** AWAITING_MAIN/STATIC_PASS: external adapter proves draft-only + typed service-unavailable errors; no live Mode B transaction from real Main.
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: tests/test_mode_b_localhost_client.py + fixture_main. Not RUNTIME_PASS_BOUNDED live predict / PRODUCTION_EVIDENCE_PASS.

### `MF-P6-11.04` — Mode A/Mode B runtime adapter, feedback, and recovery

- **Current:** `blocked` at 80%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 49
- **Requirement:** Normalize and arbitrate eligible Mode A and Mode B receipts by exact scope, authority, QA, freshness, preservation risk, and cost; never compare incompatible latents or silently weaken requirements · Verify: Mode A authority wins over an uncertified draft and close/ambiguous alternatives branch or abstain deterministically · Blocked by: MF-P6-11.02, MF-P6-11.03
- **Current blocked reason:** AWAITING_MAIN/STATIC_PASS (unchanged): 2026-07-20 isolated-consumer DoD-climb wave #2 added a real-machinery receipt-arbitration DoD matrix (normalize_and_arbitrate_receipts + build_receipt_arbitration_conformance_evidence + validator): wrapper-certified Mode A dominates uncertified Mode B draft, close-alternatives branch, three-way abstain, Main silent-weakening refusal, high-risk/authority-floor abstain. Producer+isolated-consumer only; MF-P6-11.02/11.03 still incomplete; no Main-signed arbitration decision. Evidence: qa/live_verification/isolated_consumer_dod_climb2_20260720.json
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: tests/test_receipt_arbitration_conformance.py + fixture_main. Not PRODUCTION_EVIDENCE_PASS.

### `MF-P6-11.05` — Mode A/Mode B runtime adapter, feedback, and recovery

- **Current:** `blocked` at 88%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 50
- **Requirement:** Implement authenticated, replay-protected downstream repair/quality feedback bound to exact parent receipt/release/capability/policy/certificate/source/owner/transform/QA/protected state and hypothesis budget that MaskFactory may validate, reject, mine, or use to create a new candidate without mutating frozen packages/certificates or creating truth · Verify: duplicate-hypothesis, no-progress, cap, replay, forgery, stale-parent, unauthorized-write, and conflicting-observation tests pass · Blocked by: MF-P6-11.01
- **Current blocked reason:** DEPENDENCY/STATIC_PASS: MF-P6-11.01 incomplete. Additive authenticated feedback intake ledger fixture-verified (STATIC_PASS). No production Main feedback authority fabricated.
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: tests/test_bridge_feedback_intake.py + fixture_main. Not PRODUCTION_EVIDENCE_PASS.

### `MF-P6-11.06` — Mode A/Mode B runtime adapter, feedback, and recovery

- **Current:** `blocked` at 90%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 51
- **Requirement:** Implement trusted-signed/checkpointed append-only bridge journaling, idempotency, and a closed durable state machine across admit, route, lease, submit-known/unknown, reconcile, result, validate, cache/decision, feedback, adoption, invalidation, retry/repair, recovery, and rollback · Verify: same-key/same-body replay is safe, same-key/different-body and illegal transition fail, fork/delete/reorder is detected, and interruption reconstructs exact state · Blocked by: MF-P6-10.06, MF-P6-11.01
- **Current blocked reason:** DEPENDENCY/STATIC_PASS: awaiting real Main durable journal store; isolated sibling consumer adds external replay-idempotency + signed-checkpoint coverage.
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: tests/test_bridge_journal.py + fixture_main. Not PRODUCTION_EVIDENCE_PASS.

### `MF-P6-11.07` — Mode A/Mode B runtime adapter, feedback, and recovery

- **Current:** `blocked` at 84%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 52
- **Requirement:** Add bounded transient retries, circuit breaker, deadline/resource enforcement, scoped DAG blocking, and explicit no-silent-fallback behavior · Verify: outage/OOM/timeout/incompatible-authority fault injection blocks only dependent work where safe and never substitutes an empty/wrong/weaker mask · Blocked by: MF-P6-09.06, MF-P6-11.03, MF-P6-11.06 · HARD BLOCKER
- **Current blocked reason:** HARD BLOCKER/AWAITING_MAIN: failure-control circuit exercised by external isolated consumer; real Main outage/OOM/timeout recovery receipts still required.
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: tests/test_bridge_failure_control.py + fixture_main. Not RUNTIME_PASS_BOUNDED / PRODUCTION_EVIDENCE_PASS.

### `MF-P6-11.08` — Mode A/Mode B runtime adapter, feedback, and recovery

- **Current:** `blocked` at 86%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 53
- **Requirement:** Add receipt-last atomic commit, restart recovery with `outcome_unknown` reconciliation before retry, health/capability/revocation-at-decision evidence, cache freshness, and service/node-pack drift detection; frozen v1 GPU-lease fields are telemetry-only compatibility and can never gate recovery · Verify: kill at every durable boundary, submitted-unknown, stale pack, changed capability, legacy GPU-lease contention markers, and rollback drills recover without duplicate execution, refusal, orphan promotion, or authority drift · Blocked by: MF-P6-10.07, MF-P6-11.06, MF-P6-11.07
- **Current blocked reason:** AWAITING_MAIN/STATIC_PASS (unchanged): 2026-07-20 isolated-consumer DoD-climb wave #2 added a real-machinery receipt-last recovery DoD matrix (build_recovery_evidence / simulate_kill_at_boundary + validator): full-chain commit-ready, kill at all 15 durable boundaries fail-closed without drift, receipt-before-artifacts / unresolved-digest / orphan-promotion+authority-drift / foreign-lease-cleanup / duplicate-resubmit refusals. Producer+isolated-consumer only; MF-P6-11.06/11.07 still incomplete; awaiting Main restart store + live unknown-outcome reconciler. Evidence: qa/live_verification/isolated_consumer_dod_climb2_20260720.json
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: tests/test_bridge_recovery.py + fixture_main. Not PRODUCTION_EVIDENCE_PASS.

### `MF-P6-12.02` — Cross-project qualification, evidence, handoff, and core release

- **Current:** `blocked` at 84%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 57
- **Requirement:** Run the single-person Mode A vertical slice from adopted package/certificate through adapter binding into a downstream ComfyUI inpaint/edit pass · Verify: source/character/person/mask/transform/workflow/result/history hashes and authority decision are complete · Blocked by: MF-P6-11.02, MF-P6-12.01
- **Current blocked reason:** CROSS-PROJECT/DEPENDENCY/STATIC_PASS: MF-P6-11.02 incomplete; Main/ComfyUI execution receipts absent. Producer Mode A vertical-slice fixture = STATIC_PASS only. No pinned Main adapter execution or ComfyUI inpaint/edit result/history hashes.
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: tests/test_mode_a_vertical_slice.py + fixture_main (mf_p6_12_02_complete=false). Not PRODUCTION_EVIDENCE_PASS.

### `MF-P6-12.03` — Cross-project qualification, evidence, handoff, and core release

- **Current:** `blocked` at 80%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 58
- **Requirement:** Run the overlapping/contact two-person Mode A vertical slice with distinct character instances, skeleton/ownership masks, protected regions, and transform chains · Verify: wrong-person/cross-instance seeded faults block and accepted outputs have zero ownership ambiguity · Blocked by: MF-P6-12.02
- **Current blocked reason:** CROSS-PROJECT/DEPENDENCY/STATIC_PASS: MF-P6-12.02 incomplete. Producer duo fixture = STATIC_PASS only. No adopted package + Main/ComfyUI two-person execution evidence.
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: tests/test_multi_person_mode_a_vertical_slice.py + fixture_main. Not PRODUCTION_EVIDENCE_PASS.

### `MF-P6-12.04` — Cross-project qualification, evidence, handoff, and core release

- **Current:** `blocked` at 86%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 59
- **Requirement:** Run Mode B health/predict/refine as draft, prove service-down behavior, and when eligible pass an exact original prediction through a subsequent independent operational-certification transaction · Verify: a draft cannot self-promote, refinement/derived descendants cannot inflate parent authority, and certified/abstained branches preserve complete evidence · Blocked by: MF-P6-08.08, MF-P6-11.03, MF-P6-11.07
- **Current blocked reason:** LIVE/CROSS-PROJECT + POLICY: /health+/models RUNTIME_PASS_BOUNDED (champions=0). Predict AWAITING_RUNTIME: no temporary draft/incumbent serving role — serving predictor may load champion_* only; create_production_runtime leaves predictor unconfigured until complete measured champion set; HTTP 503 champion prediction provider is not configured. Force-register forbidden (would invent champion win). Refine AWAITING_RUNTIME (prior on-demand load timeout). MF-P6-11.03/11.07 incomplete. claim_boundary.mf_p6_12_04_complete=false. Evidence: mode_b_predict_draft_provider_policy_blocker_20260719.json
- **Existing evidence to preserve/revalidate:** qa/live_verification/proof_tier_runtime_reprobe_20260719T1917.json

### `MF-P6-12.05` — Cross-project qualification, evidence, handoff, and core release

- **Current:** `blocked` at 83%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 60
- **Requirement:** Execute the cross-project compatibility, trust/canonicalization, encoded/pixel identity, image/video-time, ownership, authority/training-truth firewall, executable geometry, idempotency, signed-journal, outage, submitted-unknown restart, cache, invalidation, rollback, and no-silent-fallback qualification matrix · Verify: trusted-signed/hash-bound bundle verifies actual bytes and binds both commits and every release/capability/requirements/adoption/test/artifact identity · Blocked by: MF-P6-12.01 through MF-P6-12.04 · HARD BLOCKER
- **Current blocked reason:** HARD BLOCKER/AWAITING_MAIN: cross-project qualification run by external isolated consumer yields honest producer_partial; real Main-signed qualification bundle still required.
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: tests/test_cross_project_qualification.py producer_partial. No trusted signed production qualification bundle.

### `MF-P6-12.06` — Cross-project qualification, evidence, handoff, and core release

- **Current:** `blocked` at 78%
- **Source:** `21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md` line 61
- **Requirement:** Publish the final MaskFactory release and main-project adoption/handoff receipts, regenerate tracker reports, and close only `core_autonomous_runtime` when its exact gates pass · Verify: both projects pin the same hashes, optional profiles retain independent status, and a fresh session can resume from artifacts alone · Blocked by: MF-P6-07.07, MF-P6-12.05
- **Current blocked reason:** HARD BLOCKER/STATIC_PASS: MF-P6-12.05 unresolved. Final-release handoff fixtures only; no final producer runtime release, Main adoption receipt, or met core_autonomous_runtime.
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: tests/test_bridge_final_release_handoff.py. production_core_close_authorized=false.

