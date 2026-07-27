# 27 — Self-Hosted Autonomous LLM Continuous Operations and Throughput

## 1. Purpose

This specification closes the gap between a safe bounded self-hosted LLM
steward and the intended product: a continuously operating autonomous system
that completes most eligible MaskFactory engineering, mask-production,
adjustment, QA, evidence, and recovery work without repeated Codex micro
handoffs.

The system is not complete merely because a model can answer one bounded
prompt, a steward state machine passes unit tests, or one reviewed mission
returns a valid proposal. Completion requires sustained, restart-safe,
measured project throughput with exception-only Codex intervention.

This document is an additive execution contract. It does not widen LLM/VLM
authority, weaken hard QA, permit direct cloud calls, create gold from text
reasoning, or override the completion-profile claim firewall in doc 24.

## 2. Required outcome

The finished system SHALL:

1. keep a CPU-safe supervisor continuously selecting useful unblocked work;
2. combine eligible work into bounded campaigns instead of issuing
   record-by-record or file-by-file review requests;
3. run self-hosted inference in atomic GPU work cells and release the shared
   GPU immediately after each cell;
4. route unavailable work through governed Serverless or OpenRouter paths
   without dual submission;
5. produce implementation patches, tests, mask adjustments, structured QA
   decisions, evidence packets, and tracker-ready proposals inside explicit
   authority ceilings;
6. recover after process, service, session, or host interruption without
   duplicate inference or duplicate artifact promotion;
7. escalate only typed exceptions or consolidated campaign decisions to
   Codex; and
8. prove the reduction in Codex usage and handoff frequency with measured
   campaign evidence.

The CPU supervisor is the always-on component. A GPU model is never kept
resident solely to look busy and the shared GPU is never held while the
system waits for more work, external authority, or Codex review.

## 3. Current foundation and remaining gap

The steward implementation, runtime contract, deterministic mission identity,
refusal behavior, routing controls, and durable recovery behavior are reusable
foundations.

`MF-P6-19.01` now has accepted real evidence for one 25-mission engineering
campaign under one owned Qwen/vLLM lifetime. `MF-P6-19.02` has accepted
interruption, ambiguity, stale-owner, all-route reconciliation, and release
evidence. These immutable gates SHALL be preserved and SHALL NOT be rerun for
additional credit.

They do not by themselves establish:

- qualified full 66-class/risk-domain visual authority;
- a governed 100-mask campaign;
- three consecutive target-meeting mixed campaigns;
- sustained mask-generation and repair throughput;
- completion of the original core serving/bridge rows;
- a clean integrated full-product source tree and complete test suite;
- independently reconstructable completion evidence; or
- final adoption by the pinned ComfyUI session.

The 2026-07-26 four-hour review was a historical snapshot before the accepted
25-mission run. Its percentages and test counts remain useful audit context but
are not current completion authority. Runtime truth SHALL be based on real
model requests, accepted project artifacts, terminal reconciliation, and
resource release. Whole-product truth SHALL additionally satisfy
`Plan/28_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION_AND_COMFYUI_ADOPTION.md`.

## 4. Components

### 4.1 CPU-safe campaign supervisor

Implement a repository-backed supervisor that can run without a GPU. It
SHALL:

- read the pursuing goal, tracker, item dependencies, blockers, authority
  ceilings, active jobs, and durable receipts;
- select the highest-value unblocked eligible work;
- group compatible work into campaigns;
- persist intent before launch;
- avoid work already terminal, active, queued, superseded, or ambiguous;
- continue CPU-safe work while GPU work is blocked;
- emit health, queue, campaign, and exception status; and
- stop only at a true authority boundary with no other unblocked lane.

The supervisor SHALL NOT infer completion from conversation memory.

The supervisor SHALL drive the complete executable chain:

`tracker selection → deterministic campaign construction → guarded local
self-hosted execution → patch/test/repair → terminal reconciliation → one
consolidated Codex packet`.

A packet aggregator or fallback dispatcher alone is not the campaign runtime.
Before the first real 25-mission acceptance run, the repository SHALL contain
a focused-tested 25-mission runtime controller, a guarded CLI launched through
the shared-Pod lease wrapper, supervisor integration, and a CPU fake-runtime
25-mission end-to-end proof. The real campaign SHALL then use one owned
Qwen/vLLM service lifetime for all eligible requests, with durable request
intents and duplicate-safe reconstruction.

### 4.2 Durable mission and campaign ledger

Every mission SHALL bind project and session identity; immutable mission and
campaign IDs; canonical input, prompt, policy, tool, and runtime hashes;
authority ceiling and allowed outputs; dependency and supersession identities;
selected route and reservation/lease evidence; run, response, proposal,
validation, acceptance, and terminal hashes; and recovery state.

Required states include at least:

`planned`, `intent_persisted`, `queued`, `admitted`, `running`,
`submitted_unknown`, `response_persisted`, `validated`, `accepted`,
`rejected`, `recovery_required`, `released`, and `terminal`.

The same canonical request identity SHALL never be reissued after an
unambiguous terminal response is persisted. An intent or run record without
a matching terminal response SHALL become `recovery_required`; it SHALL not
be resent until reconciliation proves that no terminal output exists.

### 4.3 Campaign builder

Campaigns SHALL group semantically compatible work so that model startup,
context loading, and Codex adoption are amortized. Default campaign bounds
are up to 25 engineering/steward missions or up to 100 mask records with a
common frozen policy and critic stack.

Campaign construction SHALL respect context limits, risk, data authority,
model capability, protected-region scope, and GPU-time caps. A campaign may
split deterministically, but it may not silently drop records.

### 4.4 Self-hosted engineering worker

For eligible engineering work, the self-hosted worker MAY:

- synthesize bounded repository packets;
- propose implementation diffs;
- generate or update focused tests;
- diagnose failures and propose a bounded repair;
- generate migration or recovery proposals;
- compact evidence;
- challenge unsupported completion claims; and
- prepare tracker-ready status/evidence proposals.

Implementation SHALL occur in an isolated worktree or patch staging area.
The worker SHALL never directly obtain Git/GitHub, credential, RunPod
lifecycle, infrastructure, destructive filesystem, security, final tracker
completion, or final adoption authority. Codex reviews one consolidated
campaign packet, not each intermediate thought or file.

### 4.5 Autonomous mask work cell

For eligible governed images, one campaign SHALL be able to:

1. resolve exact source, owner, side, label, neighbor, and protected-region
   resources;
2. generate multiple provider candidates;
3. run deterministic format, ontology, ownership, topology, protected-region,
   laterality, transform, and complete-map hard QA;
4. compare candidates and disagreement;
5. run bounded, hypothesis-distinct automatic repair;
6. render exact source/mask/overlay/contour/ownership panels;
7. obtain one qualified high-end primary visual critic and one qualified
   independent-family juror;
8. decide `accept`, `repair`, `abstain`, `reject`, or `quarantine`;
9. persist complete immutable evidence; and
10. continue unrelated records after a typed per-record failure.

A text-only steward cannot approve a visual mask. Visual acceptance requires
the frozen deterministic gates and qualified visual roles. A critic cannot
override hard QA or mint broader authority than its qualification.

### 4.6 Consolidated adoption boundary

Codex SHALL receive one campaign-level packet containing the exact source and
changed-path inventory, patch bundle and test results, all terminal outcomes,
unresolved exceptions, visual evidence indexes where applicable, authority
and claim limitations, tracker updates proposed rather than silently applied,
and an `ADOPT`, `PARTIALLY_ADOPT`, or `REJECT` recommendation.

Routine successful steps SHALL not create separate handoffs. Escalation is
limited to security or credential needs, destructive or external actions,
unresolved authority conflicts, contradictory truth, policy/schema changes,
ambiguous completion that cannot be reconciled, or a terminal campaign
decision.

## 5. Routing and resource policy

### 5.1 Local RunPod route

Every local GPU command SHALL be launched through
`tools/run_with_shared_pod_gpu_lease.py`. The authoritative FIFO coordination
database is:

`/workspace/.maskfactory/shared_pod_coordination/shared_gpu_leases_v1.sqlite`

The MaskFactory owner token is:

`/tmp/maskfactory-019f91d1-ea20-7d81-83ff-03d393eaa1f5-shared-gpu-owner.token`

It SHALL remain mode `0600`. Local admission additionally requires a fresh
Pod, GPU, process, queue, runtime, model, storage, and job-identity preflight.
Never kill or preempt another session's process. Release the lease in a
`finally` path after the atomic work cell.

### 5.2 Serverless fallback

When local GPU admission is unavailable, use only the shared broker's
`decide` → `reserve` → `submit` → `reconcile` flow. Preserve shared budget,
rolling-window, endpoint, concurrency, immutable payload, and no-duplicate
controls. An unknown submission outcome must reconcile before any retry.
Never call the endpoint directly.

### 5.3 OpenRouter fallback

OpenRouter is bounded read-only advisory reasoning only. Use:

`C:\Comfy_UI_Main\Plan\07_IMPLEMENTATION\scripts\manage_openrouter_reasoning_fallback.py`

and its governed `decide` → `reserve` → `submit` flow. The routine model is
`qwen/qwen3-coder-next`; `qwen/qwen3-coder` is allowed only for a materially
difficult bounded escalation. Never bypass the manager, exceed shared daily
limits, send secrets/private raw data, or treat advisory output as execution
or final authority.

### 5.3.1 Parent-owned fallback capacity

Fallback capacity is not proven by fixture tests, historical terminal rows, or
an idle broker ledger. When local GPU admission is unavailable and an eligible
parent campaign has material work, the controller SHALL evaluate the canonical
Serverless route instead of waiting or creating detached activity. Before a
new Serverless successor, the actual execution host must record the exact
manager command, config, broker root, and canonical ledger (there is no
separate jobs root), plus source/config hashes,
and a non-secret availability preflight. Only then may it issue one immutable,
parent-bound broker sequence. The successor must produce a native-box-ready
terminal result and a parent receipt; unknown state is reconciled, never
reissued.

The canonical manager's provider-free `preflight` command requires an explicit
broker root and expected manager/config SHA-256 values. It fails closed unless
the root matches `durability.runpod_root`, the existing SQLite ledger is valid,
the session is authorized, and both deployed bytes match the parent contract.
Its sealed receipt records the exact executable/config/root/ledger and
canonical `decide` argv without writing the broker or calling a provider. That
receipt is a prerequisite to, never a substitute for, `decide` and the
subsequent terminal parent work.

For a parent phase that needs external reasoning, the controller may issue one
sanitized, structured, parent-namespaced OpenRouter advisory batch through the
governed manager. It must remain one-active-session, suppress additional child
advisories after the terminal parent record, and be reconciled before a new
batch. The controller, not the advisory, executes the adopted patch/test/QA
work and records the resulting local evidence. Select the least-cost capable
approved model for ordinary work, use a stronger model only for a bounded
material escalation, and use a multimodal model only when its bound visual or
audio evidence makes it applicable. Record the model, cost, input/output
receipt hashes, parent binding, and terminal outcome. Never send secrets,
private raw data, or GPU payloads.

The legacy externally owned supervisor may be recovered only by its owner:
pause intake, reconcile active work to zero, perform a controlled shutdown,
confirm the old process and child submitters are gone, then start exactly one
canonical supervisor with one Serverless worker and one OpenRouter worker.
Admission rejections are terminal for that parent and must not become retry
jobs. Acceptance requires meaningful parent-owned fallback work, not
micro-handoffs, and at least one mixed campaign where the local and child
routes are reconciled as one parent campaign.

### 5.4 CPU-safe route

If no inference route is eligible, the supervisor SHALL continue useful
CPU-safe work: inventory, deterministic QA, packet construction, test
execution, evidence reconciliation, dependency analysis, or planning. Route
unavailability is not permission to idle.

### 5.5 No dual submission

A canonical mission may have only one active execution route. Before changing
routes, the system SHALL release or terminally reconcile the prior
reservation, lease, queue entry, or submission. Tests SHALL cover local to
Serverless, Serverless unknown, OpenRouter rejection, restart, and concurrent
session races.

### 5.6 Local storage, worktree, and session continuity

The continuous system SHALL reuse the two pinned main-session heartbeat
threads. Recurring project work MUST NOT use standalone cron jobs that create
a new Codex task/session on every run.

Before creating a local worktree, clone, backup, or evidence allocation, run:

`python tools/check_local_storage_guard.py --kind <kind> --expected-bytes <bytes>`

The v1 policy is `configs/local_workspace_hygiene_v1.json`.

- New local allocations fail closed when they would leave less than 50 GiB
  free on `C:`.
- A warning remains active below 75 GiB.
- Full-repository bundles are prohibited. Use a verified compact recovery
  checkpoint containing binary patches, selected untracked
  source/configuration, hashes, and remote commit proof.
- Large runtime artifacts belong under
  `/workspace/maskfactory/runtime_artifacts`; local storage retains compact
  manifests and receipts.
- Google Drive is not an available fallback until a live destination probe and
  byte/hash round trip pass.
- The compact-manifest destination `MaskFactory_Recovery_Manifests` passed that
  round trip on 2026-07-26. Its scope is receipts/manifests only; large runtime
  artifacts remain Pod-resident.
- Worktrees may be retired only when clean, remote-contained, unreferenced by
  a process, not the main checkout, and free of unresolved reparse points.
- A failed or partial retirement is preserved and investigated; force deletion
  across a junction/reparse point is forbidden.
- A replacement clone or worktree MUST NOT be created to avoid reconciling an
  existing dirty checkout. Ownership is resolved path-by-path in the current
  checkout; a new isolated tree is permitted only for an actual campaign
  execution need after the storage guard admits it.

## 6. Handoff-suppression policy

The default operating unit is a campaign, not a micro task.

- Target no more than one Codex decision packet per 25 eligible engineering
  missions.
- Target no more than one Codex decision packet per 100 compatible mask
  records.
- Intermediate worker outputs remain inside the campaign ledger unless a
  section 4.6 escalation fires.
- Validation failures trigger bounded internal repair where authorized.
- Do not ask Codex to approve a plan, then a patch, then each test, then each
  mask when those steps can be safely contained in one campaign.

These targets never suppress a hard-QA failure, security issue, contradictory
truth, or required authority decision.

### 6.1 Last-mile anti-spin gate

With the first real 25-mission campaign terminal and accepted, non-defect Plan,
schema, dashboard, receipt-format, and hygiene churn remains frozen while a
real dependency-ready execution or integration lane exists. A new wave counts
as progress only when it delivers at least one of:

1. executable integration plus focused tests that closes a direct dependency
   of the next real campaign; or
2. real terminal runtime evidence containing model requests or accepted
   project artifacts.

Static fixtures and unit tests are reported as
`STATIC_PASS_CONTROL_PLANE_ONLY`; they cannot complete a runtime acceptance
row. Bookkeeping and hygiene may consume at most 10% of active effort unless a
storage, security, authority, or recovery defect makes it temporarily
blocking. A successor packet is forbidden unless its receipt identifies a
material canonical change to the immutable contract, prompt, schema, runtime
binding, source binding, or representation. Reformatting, nonce changes, and
unchanged revalidation are not material changes.

Every heartbeat SHALL compute a production delta since its previous cycle:
executable integration added, real model requests attempted/accepted, accepted
artifacts, and newly terminal runtime outcomes. A zero production delta forces
the next action to be runtime integration or execution, not additional
bookkeeping.

The accepted first real 25-mission engineering campaign is the
production-evidence source for later telemetry and sustained-acceptance rows.
Those later rows SHALL consume its immutable packet without recreating it.
Tracker selection now prioritizes the earliest real dependency of the
100-mask campaign, the sustained mixed campaigns, or Plan-28 whole-product
integration.

### 6.1.1 Applied campaign state (2026-07-26)

`MF-P6-19.01` and `MF-P6-19.02` have terminal accepted evidence. The
anti-spin rule therefore prohibits recreating their unchanged contracts,
packets, or fault drills. The current production delta must instead advance an
earliest dependency-ready prerequisite of `MF-P6-19.03`, its governed 100-mask
parent campaign, or the three sustained mixed campaigns and immutable final
packet required by `MF-P6-19.04`. A Serverless or OpenRouter child route is
evidence only after idempotent reconciliation into that parent; it cannot
independently advance throughput acceptance.

## 7. Telemetry and success measures

For every campaign, measure eligible and completed mission count, autonomous
completion percentage, Codex interventions and review time, model startup and
inference time, idle GPU time, route and fallback reasons, duplicate and
recovery events, patch/test repair attempts, mask outcomes, hard-QA and critic
disagreement rates, artifacts per GPU-hour, terminal reconciliation, and
lease release.

The closed v1 contract is frozen by:

- `configs/self_hosted_autonomy_contract_freeze_v1.json`;
- `configs/self_hosted_autonomy_campaign_telemetry_v1.schema.json`; and
- `configs/self_hosted_autonomy_acceptance_v1.schema.json`.

Telemetry and acceptance artifacts SHALL validate against those exact schema
bytes. The freeze registry binds Plans 27–28, Instructions 16 and 18, the
pursuing-goal message, P6 item clusters 23–24, and both schemas by SHA-256.
Unknown fields, duplicate item identities, missing measures, and stale
authority or schema hashes fail closed.

Required sustained targets:

1. at least 80% of eligible work reaches a validated adoption packet without
   intermediate Codex intervention;
2. no more than one routine Codex handoff per 25 engineering missions or 100
   compatible mask records;
3. at least 70% reduction in Codex desktop usage per accepted artifact against
   the frozen pre-campaign baseline;
4. zero duplicate inference submissions or duplicate promoted artifacts;
5. 100% terminal reconciliation for admitted missions;
6. 100% shared-GPU lease release after terminal local work cells; and
7. zero hard-QA, visual-authority, credential, or infrastructure-authority
   bypasses;
8. zero recurring standalone Codex task/session creation for the two project
   supervisors; and
9. zero local allocation admitted below the storage floor or via a prohibited
   full-repository bundle;
10. real model request count and accepted project artifact count are reported
    separately from commits, tests, schemas, manifests, and receipts; and
11. bookkeeping/hygiene effort remains at or below 10% outside a documented
    blocking defect.

## 8. Implementation sequence

1. Restore and validate the Plan/Items/Tracker/Instructions authority pack.
2. Freeze this spec, item cluster, instruction, pursuing-goal message, and
   telemetry schema.
3. Implement the CPU supervisor and durable campaign ledger.
4. Implement tracker/DAG selection and deterministic batching.
5. Integrate guarded local, broker-only Serverless, governed OpenRouter, and
   CPU-safe routing with no-dual-submit recovery.
6. Integrate isolated engineering patch/test/repair campaigns.
7. Integrate mask candidate, hard-QA, repair, panel, and dual-critic campaigns.
8. Replace routine micro handoffs with campaign-level adoption.
9. Commit and focused-test the 25-mission runtime controller with one owned
   model lifetime, durable request intents, duplicate prevention,
   reconstruction, and release.
10. Add the guarded runtime CLI and wire it into the supervisor's tracker
    selection, builder, execution, reconciliation, and consolidation chain.
11. Run a CPU fake-runtime 25-mission end-to-end campaign proving restart,
    terminal accounting, and one-packet behavior.
12. Run one real 25-mission engineering campaign. After steps 9–11 are
    verified, selection prioritizes this execution before later acceptance rows
    that consume its telemetry; the guarded runtime remains responsible for
    rejecting a missing or stale prerequisite receipt.
13. Run restart, ambiguous-completion, stale-owner, and route fault drills.
14. Run one governed 100-mask campaign with full outcome accounting.
15. Repeat three mixed campaigns while meeting every sustained target.
16. Reconcile the accepted autonomy/runtime and full-product source lines,
    repair and pass the clean full-product suite, and publish the compact
    evidence locator required by Plan 28.
17. Assemble one immutable MaskFactory release and have the pinned ComfyUI
    session independently adopt, exercise, restart, invalidate, and roll it
    back.

## 9. End-to-end acceptance

This track is complete only when one immutable acceptance bundle proves exact
committed supervisor/runtime/config/schema bytes; clean reconstruction and
operating procedures; 25 real project engineering missions processed as one
campaign under one owned model-service lifetime; 100 governed masks processed as one compatible campaign or
deterministically bounded subcampaigns; all route and recovery fault tests;
autonomous patch/test/repair and consolidated Codex adoption; qualified visual
primary and independent-family juror behavior; all section 7 targets for three
consecutive campaigns; safe release/reconciliation; and exact tracker evidence
with limitations and no overclaim. Unit-test count, commit count, schemas,
receipts, and packet construction are supporting evidence only; they do not
substitute for the required real requests and accepted artifacts.

Until this bundle passes, the honest state is:

`SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE`

This throughput claim is necessary but not sufficient for the entire product.
Until Plan 28 and Item 24 also pass, the whole-product state is:

`ULTIMATE_MASKING_SYSTEM_E2E_INCOMPLETE`
