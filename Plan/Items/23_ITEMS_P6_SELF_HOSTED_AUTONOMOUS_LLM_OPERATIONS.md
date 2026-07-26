# ITEMS — P6 Self-Hosted Autonomous LLM Continuous Operations (doc 27)

Goal: turn the accepted bounded steward foundation into a continuous,
campaign-based autonomous MaskFactory workforce that reduces Codex usage and
micro handoffs while preserving exact authority, visual QA, resource, and
recovery controls.

Frozen v1 authority and evidence contracts:
`configs/self_hosted_autonomy_contract_freeze_v1.json`,
`configs/self_hosted_autonomy_campaign_telemetry_v1.schema.json`, and
`configs/self_hosted_autonomy_acceptance_v1.schema.json`.

## MF-P6-13 — Authority restoration and completion contract (spec: 27 §§1–3)
- [x] MF-P6-13.01 Restore the committed Plan/Items/Tracker/Instructions authority pack into the active branch without overwriting newer local authority files · Verify: source-commit receipt lists every restored path and exact source/local blob equality; tracker validates and reports · Blocked by: none · HARD BLOCKER
- [x] MF-P6-13.02 Freeze Plan 27, Instruction 16, the pursuing-goal message, this item cluster, and a closed telemetry/acceptance schema · Verify: cross-reference, schema, duplicate-ID, and stale-hash tests pass · Blocked by: MF-P6-13.01 · HARD BLOCKER
- [x] MF-P6-13.03 Version the completion registry so sustained self-hosted autonomy gates required core completion without invalidating preserved prior evidence · Verify: migration and claim-firewall tests distinguish old bounded-steward evidence from the new throughput gate · Blocked by: MF-P6-13.02 · HARD BLOCKER
- [x] MF-P6-13.04 Make the pursuing-goal selector prioritize the next unblocked Plan-27 dependency over micro reviews or bookkeeping-only loops · Verify: deterministic selection fixtures choose useful campaigns and continue CPU-safe work when inference is unavailable · Blocked by: MF-P6-13.02

## MF-P6-14 — CPU supervisor, durable ledger, and campaign batching (spec: 27 §4.1–4.3)
- [x] MF-P6-14.01 Implement an always-on CPU-safe supervisor with health, queue, campaign, exception, and shutdown contracts · Verify: clean startup/restart/shutdown and stale-owner tests pass without GPU use · Blocked by: MF-P6-13.02 · HARD BLOCKER
- [x] MF-P6-14.02 Implement immutable mission/campaign identity and the durable state machine through terminal/released states · Verify: same-digest replay, different-body collision, illegal transition, stale PID/token, and persistence tests fail closed · Blocked by: MF-P6-14.01 · HARD BLOCKER
- [x] MF-P6-14.03 Implement tracker/DAG work selection and deterministic 25-mission/100-mask batching with zero dropped or duplicated work · Verify: dependency, blocker, supersession, context-cap, split, and accounting fixtures pass · Blocked by: MF-P6-13.04, MF-P6-14.02
- [x] MF-P6-14.04 Implement restart and ambiguous-completion reconciliation that adopts persisted terminal responses and blocks resend for unresolved intent/run evidence · Verify: actual interrupted-process drills prove no model reissue or duplicate promotion · Blocked by: MF-P6-14.02 · HARD BLOCKER

Operational prerequisite for every remaining item: apply Plan 27 section 5.6 and
Instruction 17. A blocked local allocation does not block CPU-safe progress,
and no campaign may create standalone cron sessions or full-repository backups.
Until `MF-P6-19.01` has a real terminal campaign, apply Plan 27 section 6.1:
static fixtures are `STATIC_PASS_CONTROL_PLANE_ONLY`, bookkeeping/hygiene is at
most 10% outside a blocking defect, no replacement clone/worktree may evade
checkout reconciliation, and every wave must deliver executable integration
plus focused tests or real terminal runtime evidence.

## MF-P6-15 — Shared GPU and governed fallback routing (spec: 27 §5)
- [ ] MF-P6-15.01 Route every local GPU command through `tools/run_with_shared_pod_gpu_lease.py` with fresh Pod/GPU/process/queue/runtime/model/storage/job preflight and finally-path release · Verify: FIFO contention, foreign work, token-mode, stale lease, crash, and release drills pass · Blocked by: MF-P6-14.02 · HARD BLOCKER
- [ ] MF-P6-15.02 Integrate broker-only Serverless decide/reserve/submit/reconcile with immutable payload, budget, concurrency, and unknown-outcome protection · Verify: rejected, capped, submitted-unknown, timeout, terminal, and duplicate fixtures pass without direct endpoint use · Blocked by: MF-P6-14.02 · HARD BLOCKER
- [ ] MF-P6-15.03 Integrate governed Qwen-first OpenRouter advisory and useful CPU-safe fallback without granting execution or final authority · Verify: ineligible/rejected/capped/secret/tool-authority tests continue safely and never bypass the manager · Blocked by: MF-P6-14.01
- [ ] MF-P6-15.04 Enforce one active route per canonical mission and release/reconcile before route change · Verify: local→Serverless, Serverless-unknown, OpenRouter rejection, restart, and concurrent-session race tests prove zero dual submission · Blocked by: MF-P6-15.01 through MF-P6-15.03 · HARD BLOCKER

## MF-P6-16 — Autonomous engineering patch/test/repair campaigns (spec: 27 §4.4, §4.6)
- [ ] MF-P6-16.01 Build minimal hash-bound repository packets and isolated patch workspaces for eligible tracker work · Verify: scope, secret, untracked-user-work, path-escape, and stale-source tests pass · Blocked by: MF-P6-14.03
- [ ] MF-P6-16.02 Execute bounded patch→focused-test→diagnose→repair loops and persist every proposal/result hash · Verify: success, deterministic failure, repair exhaustion, timeout, and no-progress fixtures terminate honestly · Blocked by: MF-P6-16.01 · HARD BLOCKER
- [ ] MF-P6-16.03 Enforce worker refusal of credentials, unauthorized tools, Git/GitHub, destructive actions, infrastructure, RunPod lifecycle, final tracker, and final adoption authority · Verify: adversarial prompts and malformed tool contracts cannot widen authority · Blocked by: MF-P6-16.01 · HARD BLOCKER
- [ ] MF-P6-16.04 Produce one consolidated ADOPT/PARTIALLY_ADOPT/REJECT packet per campaign with exact paths, hashes, tests, limitations, exceptions, and tracker-ready proposals · Verify: missing, duplicate, unsupported, or overclaiming packets fail validation · Blocked by: MF-P6-16.02, MF-P6-16.03

## MF-P6-17 — Autonomous mask generation, adjustment, visual QA, and outcomes (spec: 27 §4.5)
- [ ] MF-P6-17.01 Build campaign inputs with exact source/label/owner/side/neighbor/protected-region bindings and multiple provider candidates · Verify: missing or ambiguous semantic resources abstain before defect generation or inference · Blocked by: MF-P6-14.03, existing MF-P4-12.11 · HARD BLOCKER
- [ ] MF-P6-17.02 Run deterministic hard QA, disagreement, bounded hypothesis-distinct repair, no-progress termination, and immutable parent preservation · Verify: seeded format/ontology/ownership/laterality/topology/protected-region/complete-map faults veto and unrelated records continue · Blocked by: MF-P6-17.01 · HARD BLOCKER
- [ ] MF-P6-17.03 Run exact evidence panels through a qualified high-end primary visual critic and qualified independent-family juror; text-only or correlated critics cannot approve · Verify: positive/negative calibration, disagreement, unavailable, malformed, timeout, and hard-QA-override fixtures fail closed · Blocked by: MF-P6-17.02, existing MF-P4-11.23 · HARD BLOCKER
- [ ] MF-P6-17.04 Persist terminal accept/repair/abstain/reject/quarantine outcomes and complete accounting for every mask record · Verify: 100-record campaign reconciles all inputs, outputs, evidence, repairs, critic decisions, and authority limitations with zero loss or duplicate promotion · Blocked by: MF-P6-17.03 · HARD BLOCKER

## MF-P6-18 — Micro-handoff elimination and autonomy telemetry (spec: 27 §§6–7)
- [ ] MF-P6-18.01 Replace routine per-step/per-file/per-mask handoffs with an integrated tracker-selection→campaign-builder→guarded-runtime→patch/test/repair→reconciliation→one-packet supervisor chain · Verify: a CPU fake-runtime 25-mission E2E and event logs prove one owned service lifetime, durable request intents, terminal accounting, one terminal packet, and no intermediate Codex dependency for ordinary successful work · Blocked by: MF-P6-16.04, MF-P6-17.04
- [ ] MF-P6-18.02 Implement typed exception escalation only for security/credentials, destructive or external authority, contradictory truth, policy/schema change, unreconciled ambiguity, repair exhaustion, or terminal adoption · Verify: escalation matrix rejects convenience and bookkeeping handoffs without hiding hard failures · Blocked by: MF-P6-18.01 · HARD BLOCKER
- [ ] MF-P6-18.03 Measure autonomous eligible-work percentage, Codex handoffs/time, route use, GPU time, duplicate/recovery events, repair attempts, mask outcomes, critic disagreement, reconciliation, and release · Verify: closed telemetry reconciles ledger and artifacts exactly · Blocked by: MF-P6-14.02, MF-P6-15.04
- [ ] MF-P6-18.04 Enforce targets of ≥80% autonomous preparation, ≤1 routine Codex handoff per 25 missions or 100 masks, ≥70% lower Codex usage per accepted artifact, zero duplicates, and 100% reconciliation/release · Verify: baseline and campaign reports fail closed on missing or under-target measures; this row consumes real campaign telemetry and cannot block the first 25-mission engineering campaign · Blocked by: MF-P6-18.02, MF-P6-18.03 · HARD BLOCKER

## MF-P6-19 — Real campaigns and final throughput acceptance (spec: 27 §§8–9)
- [ ] MF-P6-19.01 Run one real 25-mission MaskFactory engineering campaign through selection, self-hosted work, patch/test/repair, consolidated adoption, tracker proposal, and release · Verify: the committed focused-tested runtime controller, guarded CLI, supervisor wiring, and CPU fake-runtime E2E precede the run; one owned Qwen/vLLM lifetime processes the eligible requests; one immutable packet binds all 25 terminal outcomes, exact real-request/accepted-artifact counts, reconciliation/release, and no routine intermediate Codex handoff; later telemetry/acceptance rows consume this campaign's evidence and do not block it · Blocked by: MF-P6-15.04, MF-P6-16.04 · HARD BLOCKER
- [ ] MF-P6-19.02 Run process/service/session interruption, persisted-terminal adoption, unresolved-ambiguity, stale-owner, and all-route fault drills · Verify: reconstruction preserves accepted output, blocks unsafe resend, and leaves no active lease/reservation/job · Blocked by: MF-P6-14.04, MF-P6-15.04 · HARD BLOCKER
- [ ] MF-P6-19.03 Run one governed 100-mask campaign with deterministic subcampaign splits if required · Verify: every input has a terminal outcome, exact visual evidence, zero hard-QA bypass, zero duplicate promotion, and measured Codex reduction · Blocked by: MF-P6-17.04, MF-P6-18.04 · HARD BLOCKER
- [ ] MF-P6-19.04 Run three consecutive mixed campaigns meeting every Plan-27 SLO, publish the immutable acceptance/reconstruction/operating packet, update the tracker through its CLI, and close the throughput gate · Verify: independent replay validates exact commits, runtime/model/config hashes, real model-request and accepted-artifact counts, all campaign evidence, limitations, terminal reconciliation, safe GPU release, ≥80% autonomous preparation, and ≥70% Codex-usage reduction; commits/tests/schemas/receipts alone receive no runtime credit · Blocked by: MF-P6-19.01 through MF-P6-19.03 · HARD BLOCKER
