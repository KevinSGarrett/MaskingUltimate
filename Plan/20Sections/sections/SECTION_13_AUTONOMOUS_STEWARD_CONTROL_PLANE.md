# Section 13 — Autonomous Steward, Routing, GPU Coordination, and Exception-Only Control

**Acceptance order:** 13 of 20  
**Mapped unresolved tracker items:** 3  
**Current states:** in_progress=2, open=1  
**Hard blockers in scope:** 1  
**Rows with explicit Kevin authority/input:** 0  
**Depends on:** Section 03, Section 10, Section 12  
**Enables:** Section 14, Section 15, Section 16, Section 20

## Goal

Finish the integrated tracker-selection-to-terminal-packet supervisor and durable RunPod queue so routine work no longer depends on per-step Codex handoffs or unsafe dual submission.

## Why this section exists

The control plane is advanced, but the remaining items still require the full integrated chain, typed escalation enforcement, and durable capacity-coordinated queue/recovery proof.

## Scope

- Integrate tracker selection, campaign construction, shared GPU lease guard, local/Serverless/OpenRouter route selection, patch/test/repair, reconciliation, and one terminal packet.
- Allow escalation only for enumerated security, destructive/external authority, contradictory truth, policy/schema change, ambiguity, repair exhaustion, or terminal adoption cases.
- Prove durable RunPod queue/checkpoint/crash recovery and serialization of incompatible large models.
- Prevent dual-submit, stale-owner, duplicate work, and leaked leases/reservations.

## Work packages

1. Wire the committed supervisor to the actual campaign controller and route adapters.
2. Persist request intent before submission and terminal state before adoption.
3. Implement restart reconciliation and no-progress/stall lane switching.
4. Apply typed exception matrix and reject convenience/bookkeeping handoffs.
5. Run CPU fake-runtime and bounded provisioned queue campaigns.

## Section-level testing

- Twenty-five-mission CPU fake-runtime E2E with one service lifetime and one packet.
- Local/Serverless/OpenRouter selection, fallback, no-dual-submit, and source-binding tests.
- Crash before submit, submitted-unknown, persisted terminal, stale owner, retry exhaustion, and restart recovery.
- Lease heartbeat/release and incompatible-model serialization/OOM tests.
- Escalation negative tests for convenience or bookkeeping handoffs.

## Integration tests with the rest of the project

- Section 14 can execute real campaigns from one owned controller.
- Section 15 service lifecycle can be supervised without leaked resources.
- Section 20 reconstructs route and lease evidence from durable ledgers.

## Definition of done and acceptance criteria

- [ ] Ordinary eligible work completes through one integrated supervisor chain.
- [ ] Only typed exceptions create Codex/user handoffs.
- [ ] RunPod queue and checkpoints survive crash/restart by sample/request ID.
- [ ] Zero duplicate submission and 100% owned lease/reservation release are demonstrated.
- [ ] All mapped tracker items are accepted.

## Required proof artifacts

- `supervisor_e2e_25_fake_runtime.json`
- `route_decision_ledger.jsonl`
- `typed_escalation_report.json`
- `runpod_queue_recovery_report.json`
- `lease_release_reconciliation.json`
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
| `MF-P6-18.01` | P6 | in_progress | 60 | No | No | Replace routine per-step/per-file/per-mask handoffs with an integrated tracker-selection→campaign-builder→guarded-runtime→patch/test/repair→reconciliation→one-packet supervisor chain |
| `MF-P6-18.02` | P6 | in_progress | 65 | Yes | No | Implement typed exception escalation only for security/credentials, destructive or external authority, contradictory truth, policy/schema change, unreconciled ambiguity, repair exhaustion, or terminal adoption |
| `MF-P7-08.02` | P7 | open | 0 | No | No | Prove durable RunPod queue, checkpoint, crash recovery, and capacity-coordinated provider/VLM bursts |

## Tracker-item exact verification text

### `MF-P6-18.01` — Micro-handoff elimination and autonomy telemetry

- **Current:** `in_progress` at 60%
- **Source:** `23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md` line 58
- **Requirement:** Replace routine per-step/per-file/per-mask handoffs with an integrated tracker-selection→campaign-builder→guarded-runtime→patch/test/repair→reconciliation→one-packet supervisor chain · Verify: a CPU fake-runtime 25-mission E2E and event logs prove one owned service lifetime, durable request intents, terminal accounting, one terminal packet, and no intermediate Codex dependency for ordinary successful work · Blocked by: MF-P6-16.04, MF-P6-17.04

### `MF-P6-18.02` — Micro-handoff elimination and autonomy telemetry

- **Current:** `in_progress` at 65%
- **Source:** `23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md` line 59
- **Requirement:** Implement typed exception escalation only for security/credentials, destructive or external authority, contradictory truth, policy/schema change, unreconciled ambiguity, repair exhaustion, or terminal adoption · Verify: escalation matrix rejects convenience and bookkeeping handoffs without hiding hard failures · Blocked by: MF-P6-18.01 · HARD BLOCKER

### `MF-P7-08.02` — P7

- **Current:** `open` at 0%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 40
- **Requirement:** Prove durable RunPod queue, checkpoint, crash recovery, and capacity-coordinated provider/VLM bursts · Verify: restart resumes by sample ID and incompatible large models serialize without OOM · Blocked by: MF-P4-12.01, MF-P7-08.01

