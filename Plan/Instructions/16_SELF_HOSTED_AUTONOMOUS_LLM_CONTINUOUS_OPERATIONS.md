# 16 — Self-Hosted Autonomous LLM Continuous Operations

## Read first

This instruction implements Plan 27. It supersedes any interpretation that
one safe bounded self-hosted review equals continuous autonomy.

For canonical product integration, full-suite proof, evidence reconstruction,
release, and ComfyUI adoption, also follow Plan 28 and Instruction 18.

The current honest state is
`SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE`. `MF-P6-19.01` now has one
accepted real 25-mission campaign and `MF-P6-19.02` has accepted
interruption/all-route reconciliation; neither may be recreated for more
credit. The top priority is the remaining executable evidence, not additional
control documents: satisfy the governed 100-mask campaign prerequisites, run
`MF-P6-19.03`, then run the three sustained mixed campaigns and final packet
in `MF-P6-19.04`. Do not start non-defect Plan/schema/hygiene work while those
real gates are available.

At session start:

1. read `Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md`;
2. run `python Plan/Tracker/tracker.py validate`;
3. run `python Plan/Tracker/tracker.py report`;
4. read the required-core and self-hosted-autonomy items in P6;
5. inspect durable mission, route, lease, and terminal state; and
6. resume the highest-value unblocked campaign without reissuing terminal or
   ambiguous work.

## Operating loop

1. **Select:** choose work from the tracker and dependency graph, not chat memory.
2. **Classify:** engineering, mask production/repair, visual QA, evidence,
   recovery, or CPU-safe planning.
3. **Batch:** group compatible work into a bounded 25-mission or 100-mask campaign.
4. **Persist:** write immutable campaign and mission intent before inference.
5. **Route:** local guarded GPU, broker-only Serverless, governed OpenRouter
   advisory, or CPU-safe work.
6. **Execute:** run the bounded worker inside its authority ceiling.
7. **Validate/repair:** run deterministic checks and bounded repair before escalation.
8. **Reconcile:** persist response, proposal, validation, terminal, and release
   receipts; resolve unknown outcomes before retry.
9. **Consolidate:** send one campaign packet to Codex.
10. **Continue:** immediately select the next unblocked campaign.

The completed initial integration target was:

`tracker selection → campaign construction → guarded engineering runtime →
patch/test/repair → terminal reconciliation → one Codex packet`.

The runtime controller processed those 25 missions under one owned Qwen/vLLM
lifetime with durable per-request intent and duplicate-safe recovery. Its
guarded CLI, shared-Pod lease invocation, supervisor wiring, and CPU
fake-runtime E2E are prerequisite evidence, not a reason to re-run the same
campaign.

`MF-P6-19.01` and `MF-P6-19.02` are complete. The selector must choose the
earliest dependency-ready prerequisite for `MF-P6-19.03` rather than reissue a
completed campaign. The 100-mask parent must preserve exact outcome, visual,
hard-QA, duplicate-promotion, route, reconciliation, and Codex-reduction
evidence; `MF-P6-19.04` remains incomplete until three consecutive real mixed
campaigns meet every target. A Serverless or OpenRouter result is counted only
when it is reconciled into that immutable parent campaign.

## Last-mile anti-spin rules

- A wave is productive only if it yields executable integration plus focused
  tests, or real terminal runtime evidence.
- Unit fixtures are `STATIC_PASS_CONTROL_PLANE_ONLY`; never use them alone to
  advance a runtime acceptance row.
- Bookkeeping and hygiene consume at most 10% of active effort unless a
  storage, security, authority, or recovery defect blocks execution.
- Do not create a successor packet without a receipt identifying a material
  immutable contract, prompt, schema, runtime/source binding, or
  representation change.
- Do not create a replacement clone/worktree to avoid reconciling the current
  checkout.
- On each heartbeat, record the production delta: executable integration,
  real requests, accepted artifacts, and terminal runtime outcomes. If all are
  zero, the next action is runtime integration or execution.
- Count real requests and accepted artifacts separately from commits, tests,
  schemas, manifests, and receipts.

## Local GPU rule

Every local RunPod GPU command must use
`tools/run_with_shared_pod_gpu_lease.py`, the coordination database
`/workspace/.maskfactory/shared_pod_coordination/shared_gpu_leases_v1.sqlite`,
and the protected token
`/tmp/maskfactory-019f91d1-ea20-7d81-83ff-03d393eaa1f5-shared-gpu-owner.token`.

The token stays mode `0600` and is never printed. The wrapper is mandatory,
but the lease alone is not sufficient: run a fresh Pod/GPU/process/queue/
runtime/model/storage/job preflight. Never preempt foreign work. Release in a
`finally` path. Do not hold the GPU while planning or waiting for review.

## Fallback rule

- **Serverless:** broker `decide` → `reserve` → `submit` → `reconcile`; never
  direct endpoint; never retry an unknown outcome before reconciliation.
- **OpenRouter:** governed manager only; Qwen-first; read-only advisory; never
  secrets, raw private data, execution, or final authority.
- **CPU:** continue useful deterministic work when neither inference route is
  eligible.
- **No dual submit:** one canonical mission, one active route.

Fallback capacity has a production bar. Serverless is used only for material
work of an eligible parent when local GPU admission is unavailable. On the
actual execution host, bind the canonical manager command, config, broker root
and ledger (not a separate jobs root), source/config hashes, and a non-secret
availability preflight before one
source-hash-bound successor. Historical terminal jobs and idle ledgers are not
current capacity. The one successor remains parent-bound through terminal
reconciliation; unknown state is never retried before reconciliation.

Use the canonical manager's provider-free `preflight` command before `decide`:
it requires explicit root and expected manager/config hashes, verifies the
authorized session plus matching config root and existing SQLite ledger, and
seals the exact host/command receipt without a broker write or provider call.
Retain this receipt in the parent contract; it does not reserve, submit, or
prove capacity by itself.

OpenRouter is one consolidated, sanitized, parent-namespaced structured
advisory batch per parent phase, with one active session and terminal-parent
suppression. The local controller performs and validates adopted work. Choose
the least-cost capable approved model; stronger or multimodal models require a
bounded escalation or bound visual/audio applicability record. Record model,
cost, input/output receipt hashes, parent binding, and terminal result; do not
send secrets, private raw data, or GPU payloads.

The legacy supervisor may be recovered only by its owner: pause intake,
reconcile to zero, perform controlled shutdown, verify old-process and child
submitter exit, then restart once with canonical paths and one Serverless plus
one OpenRouter worker. Admission rejection fails closed and never becomes a
retry job.

## Engineering worker authority

Allowed: bounded analysis, patches in isolation, focused tests, diagnosis,
repair proposals, evidence compaction, claim challenge, tracker-ready
recommendations.

Forbidden: credentials, direct cloud/provider wrappers, Git/GitHub final
actions, destructive filesystem operations, infrastructure changes, RunPod
lifecycle changes, final tracker completion, final mask approval, certificate
scope widening, or silent adoption.

## Mask and visual authority

The text steward does not approve masks. Mask campaigns require exact
source/label/owner/side/neighbor/protected-region binding; deterministic hard
QA; immutable parents and bounded distinct repair; exact evidence panels; a
qualified high-end primary visual critic; a qualified independent-family
juror; and terminal accept/repair/abstain/reject/quarantine evidence.

Any hard-QA failure vetoes visual confidence. Missing or unqualified critics
abstain. One failing record never stalls unrelated records.

## Handoff policy

Do not create separate routine handoffs for planning, patch generation, test
generation, each test result, each mask, and evidence compaction. Keep those
steps inside the durable campaign and emit one terminal packet.

Escalate early only for credentials or privileged external authority,
destructive/security-sensitive action, contradictory governed truth,
policy/schema/authority-lattice change, ambiguous completion that cannot be
reconciled, repeated bounded repair exhaustion, or terminal campaign adoption.

## Mandatory metrics and completion

Record eligible/completed/autonomous counts, Codex intervention and review
time, route/fallback reasons, inference/startup/idle GPU time, duplicate and
recovery events, patch/test repair attempts, mask outcomes, critic disagreement,
hard-QA vetoes, terminal reconciliation, resource release, real model requests,
accepted project artifacts, and bookkeeping/hygiene effort.

Validate every campaign against the frozen closed contract:

- `configs/self_hosted_autonomy_contract_freeze_v1.json`;
- `configs/self_hosted_autonomy_campaign_telemetry_v1.schema.json`; and
- `configs/self_hosted_autonomy_acceptance_v1.schema.json`.

Any unknown field, missing metric, duplicate item identity, or stale bound hash
is a typed contract failure and cannot be accepted by prose or conversation
memory.

Targets: at least 80% eligible work autonomously prepared; at most one routine
Codex handoff per 25 missions or 100 masks; at least 70% lower Codex usage per
accepted artifact; zero duplicate execution/promotion; 100% reconciliation and
local lease release.

Do not report completion until Plan 27 section 9 passes, including the real
25-mission and 100-mask campaigns, route and interruption drills, qualified
dual visual roles, three consecutive target-meeting campaigns, and an immutable
acceptance packet. Otherwise report:

`SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE`

Passing Plan 27 does not by itself complete the Ultimate Masking System.
Until the canonical integrated tree, clean full suite, evidence reconstruction,
mask-safety semantics, immutable release, and pinned ComfyUI adoption in
Plan 28 pass, also report:

`ULTIMATE_MASKING_SYSTEM_E2E_INCOMPLETE`
