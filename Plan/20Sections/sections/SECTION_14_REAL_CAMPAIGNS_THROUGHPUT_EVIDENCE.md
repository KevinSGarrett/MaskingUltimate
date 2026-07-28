# Section 14 — Real Campaign Qualification, Evidence Reconstruction, and Throughput Acceptance

**Acceptance order:** 14 of 20  
**Mapped unresolved tracker items:** 8  
**Current states:** in_progress=2, open=5, partially_complete=1  
**Hard blockers in scope:** 6  
**Rows with explicit Kevin authority/input:** 0  
**Depends on:** Section 10, Section 11, Section 12, Section 13  
**Enables:** Section 15, Section 16, Section 17, Section 20

## Goal

Run the remaining real mask and mixed campaigns, measure autonomy and Codex reduction honestly, reconcile every terminal outcome, preserve previously accepted campaigns, and close the Plan-27 throughput gate.

## Why this section exists

MF-P6-19.01 and .02 are already accepted and must not be rerun. The remaining proof is the governed 100-mask campaign, three consecutive mixed campaigns, complete telemetry, evidence locator, and independent reconstruction from the canonical tree.

## Scope

- Preserve and reconstruct accepted 25-mission and interruption/fault evidence without duplicate rerun.
- Run one governed 100-mask campaign with exact visual/deterministic authority.
- Run three consecutive mixed campaigns meeting every Plan-27 SLO.
- Measure autonomous eligible-work percentage, handoffs/time, routes, GPU time, duplicate/recovery, repairs, outcomes, disagreement, reconciliation, and release.
- Publish a compact evidence locator and reconcile all 81,910 adopted records into terminal categories.
- Enforce ≥80% autonomous preparation, ≤1 routine handoff per campaign, ≥70% lower Codex use, zero duplicates, and 100% reconciliation/release.

## Work packages

1. Index accepted 19.01/19.02 evidence into the canonical locator.
2. Freeze 100-mask campaign inputs/splits and execute through the Section-13 controller.
3. Run three mixed campaigns with no threshold changes between them.
4. Reconcile ledgers, artifacts, visual decisions, repairs, terminal states, and resources.
5. Create one immutable acceptance/reconstruction/operating packet.

## Section-level testing

- Exact input/terminal count reconciliation and zero duplicate promotion.
- No hard-QA/visual bypass; unavailable/unqualified authority abstains.
- Telemetry denominator and ledger/artifact reconciliation tests.
- Independent replay/reconstruction of accepted 25-mission and new campaign packets.
- SLO fail-closed tests for missing/under-target autonomy, Codex, duplicate, reconciliation, or release measures.
- 81,910-record accounting with zero unknown records.

## Integration tests with the rest of the project

- Section 15 binds services to the same source/runtime/model identities used in campaigns.
- Section 16 adoption packet cites the exact campaign release evidence.
- Section 20 can reconstruct all acceptance-critical runtime milestones from the locator.

## Definition of done and acceptance criteria

- [ ] The 100-mask campaign is terminal with exact accounting.
- [ ] Three consecutive mixed campaigns meet every frozen SLO.
- [ ] Accepted 19.01/.02 evidence is preserved and reconstructable without rerun.
- [ ] The compact evidence locator is complete.
- [ ] All 81,910 records have one governed category and accepted outputs feed training/release evidence.
- [ ] The Plan-27 throughput gate and all mapped tracker items are accepted.

## Required proof artifacts

- `completion_evidence_locator.jsonl`
- `campaign_100_mask_packet.json`
- `mixed_campaign_1.json`
- `mixed_campaign_2.json`
- `mixed_campaign_3.json`
- `autonomy_telemetry_report.json`
- `record_81910_reconciliation.json`
- `plan27_acceptance_packet.json`
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
| `MF-P6-18.03` | P6 | in_progress | 85 | No | No | Measure autonomous eligible-work percentage, Codex handoffs/time, route use, GPU time, duplicate/recovery events, repair attempts, mask outcomes, critic disagreement, reconciliation, and release |
| `MF-P6-18.04` | P6 | in_progress | 80 | Yes | No | Enforce targets of ≥80% autonomous preparation, ≤1 routine Codex handoff per 25 missions or 100 masks, ≥70% lower Codex usage per accepted artifact, zero duplicates, and 100% reconciliation/release |
| `MF-P6-19.03` | P6 | open | 0 | Yes | No | Run one governed 100-mask campaign with deterministic subcampaign splits if required |
| `MF-P6-19.04` | P6 | open | 0 | Yes | No | Run three consecutive mixed campaigns meeting every Plan-27 SLO, publish the immutable acceptance/reconstruction/operating packet, update the tracker through its CLI, and close the throughput gate |
| `MF-P6-21.01` | P6 | open | 0 | Yes | No | Publish a compact committed evidence locator for every completion-critical accepted runtime, routing, campaign, visual, release, and adoption milestone |
| `MF-P6-21.04` | P6 | open | 0 | Yes | No | Reconstruct the accepted 25-mission/recovery evidence and the eventual 100-mask/three-mixed-campaign evidence from the canonical integrated tree |
| `MF-P7-07.05` | P7 | partially_complete | 95 | No | No | Track human touches per 100 images, audited fraction, residual-review fraction, manually changed pixels per 100,000 predicted pixels, zero-touch fraction, quality, and failure-rate bounds separately |
| `MF-P7-08.03` | P7 | open | 0 | Yes | No | Account all 81,910 adopted records as qualified input, candidate, repaired, abstained/rejected, quarantined, or holdout and bind accepted outputs into training/release/recovery evidence |

## Tracker-item exact verification text

### `MF-P6-18.03` — Micro-handoff elimination and autonomy telemetry

- **Current:** `in_progress` at 85%
- **Source:** `23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md` line 60
- **Requirement:** Measure autonomous eligible-work percentage, Codex handoffs/time, route use, GPU time, duplicate/recovery events, repair attempts, mask outcomes, critic disagreement, reconciliation, and release · Verify: closed telemetry reconciles ledger and artifacts exactly · Blocked by: MF-P6-14.02, MF-P6-15.04
- **Existing evidence to preserve/revalidate:** commits e84579e18, 1eba234f4; src/maskfactory/steward/campaign_reconciliation.py; tests/steward/test_campaign_reconciliation.py; full tests/steward wave 310 passed, 1 skipped

### `MF-P6-18.04` — Micro-handoff elimination and autonomy telemetry

- **Current:** `in_progress` at 80%
- **Source:** `23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md` line 61
- **Requirement:** Enforce targets of ≥80% autonomous preparation, ≤1 routine Codex handoff per 25 missions or 100 masks, ≥70% lower Codex usage per accepted artifact, zero duplicates, and 100% reconciliation/release · Verify: baseline and campaign reports fail closed on missing or under-target measures; this row consumes real campaign telemetry and cannot block the first 25-mission engineering campaign · Blocked by: MF-P6-18.02, MF-P6-18.03 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** commits 1519fcbf7, e33d6d456, 1eba234f4, dfbd1edaf; src/maskfactory/steward/campaign_reconciliation.py; tests/steward/test_campaign_reconciliation.py; full tests/steward 313 passed, 1 skipped

### `MF-P6-19.03` — Real campaigns and final throughput acceptance

- **Current:** `open` at 0%
- **Source:** `23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md` line 66
- **Requirement:** Run one governed 100-mask campaign with deterministic subcampaign splits if required · Verify: every input has a terminal outcome, exact visual evidence, zero hard-QA bypass, zero duplicate promotion, and measured Codex reduction · Blocked by: MF-P6-17.04, MF-P6-18.04 · HARD BLOCKER

### `MF-P6-19.04` — Real campaigns and final throughput acceptance

- **Current:** `open` at 0%
- **Source:** `23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md` line 67
- **Requirement:** Run three consecutive mixed campaigns meeting every Plan-27 SLO, publish the immutable acceptance/reconstruction/operating packet, update the tracker through its CLI, and close the throughput gate · Verify: independent replay validates exact commits, runtime/model/config hashes, real model-request and accepted-artifact counts, all campaign evidence, limitations, terminal reconciliation, safe GPU release, ≥80% autonomous preparation, and ≥70% Codex-usage reduction; commits/tests/schemas/receipts alone receive no runtime credit · Blocked by: MF-P6-19.01 through MF-P6-19.03 · HARD BLOCKER

### `MF-P6-21.01` — Evidence reconstruction and integrated mask safety

- **Current:** `open` at 0%
- **Source:** `24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md` line 20
- **Requirement:** Publish a compact committed evidence locator for every completion-critical accepted runtime, routing, campaign, visual, release, and adoption milestone · Verify: every entry binds tracker item, parent, source, input/runtime/output/terminal/release hashes, locations, replay command, limitations, and supersession without secrets or large artifacts · Blocked by: MF-P6-20.02 · HARD BLOCKER

### `MF-P6-21.04` — Evidence reconstruction and integrated mask safety

- **Current:** `open` at 0%
- **Source:** `24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md` line 23
- **Requirement:** Reconstruct the accepted 25-mission/recovery evidence and the eventual 100-mask/three-mixed-campaign evidence from the canonical integrated tree · Verify: independent replay matches exact counts, decisions, source/runtime identities, terminal reconciliation, and release without rerunning immutable accepted work · Blocked by: MF-P6-19.04, MF-P6-20.04, MF-P6-21.01 · HARD BLOCKER

### `MF-P7-07.05` — Recurring currency, certificate operations, and autonomous headline evidence

- **Current:** `partially_complete` at 95%
- **Source:** `18_ITEMS_P7_CURRENCY_OPERATIONS.md` line 23
- **Requirement:** Track human touches per 100 images, audited fraction, residual-review fraction, manually changed pixels per 100,000 predicted pixels, zero-touch fraction, quality, and failure-rate bounds separately · Verify: dashboard/report rejects missing denominators and conflation · Blocked by: live autonomous runs
- **Existing evidence to preserve/revalidate:** qa/live_verification/autonomy_metrics_v3_contract_20260715.json; strict autonomy_metrics_inputs v1 and autonomy_metrics v3 schemas; hash-bound CLI/dashboard; 40 dedicated, 73 currency+metrics, 134 autonomy, and full 1,335-test repository suite pass; Ruff/format/CI YAML clean; signed current-input review f819a91ee85d7e0bee6ecf6c verifies. Genuine autonomous cohort remains pending.

### `MF-P7-08.03` — P7

- **Current:** `open` at 0%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 41
- **Requirement:** Account all 81,910 adopted records as qualified input, candidate, repaired, abstained/rejected, quarantined, or holdout and bind accepted outputs into training/release/recovery evidence · Verify: signed reconciliation has zero unknown records and the frozen ComfyUI release path consumes the qualified result · Blocked by: MF-P4-12.08, MF-P5-11.03, MF-P7-08.02 · HARD BLOCKER

