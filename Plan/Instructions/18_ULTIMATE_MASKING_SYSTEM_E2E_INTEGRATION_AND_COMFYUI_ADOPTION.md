# Instruction 18 — Ultimate Masking System E2E Integration and ComfyUI Adoption

## Use this instruction when

Use this instruction for work that claims to integrate, release, adopt, or
complete the whole MaskFactory product. Continue using Instruction 16 for
self-hosted campaign operations and the phase-specific instructions for the
selected mask/model/QA item.

## Session roles

- MaskFactory builder:
  `019f91d1-ea20-7d81-83ff-03d393eaa1f5`.
- ComfyUI adopter:
  `019f9200-4805-7632-83d3-ee9ae614c603`.

MaskFactory owns development and qualification of the masking subsystem.
ComfyUI may continue unrelated work but keeps final masking deferred until it
receives and independently adopts the exact immutable MaskFactory release.

Frozen authority and campaign evidence contracts:

- `configs/self_hosted_autonomy_contract_freeze_v1.json`;
- `configs/self_hosted_autonomy_campaign_telemetry_v1.schema.json`; and
- `configs/self_hosted_autonomy_acceptance_v1.schema.json`.

## Start-of-cycle procedure

1. Read the live tracker and dependency closure.
2. Read the pursuing-goal message, Plan 27, Plan 28, Item 23, and Item 24.
3. Confirm exact branch/commit/tree and shared-checkout status.
4. Record path ownership before editing.
5. Preserve unrelated staged, dirty, and untracked work.
6. Check whether the intended action creates executable integration, a real
   request, an accepted artifact, or a terminal outcome.
7. If it does not, choose a higher-value unblocked lane unless the action fixes
   a blocking authority/test/evidence defect.

## Source convergence procedure

1. Inventory the full-product and autonomy lines by exact Git objects,
   including `refs/stash`, every stash worktree/index/untracked parent,
   reflog-only recovery state, and hook/tool caches that can keep a checkout
   physically dirty after branch/worktree cleanup.
2. Produce a path table: identical, required product-only, required
   autonomy-only, generated, evidence-only, superseded, user-owned, or conflict.
3. Take a scoped verified backup of overlapping paths.
4. Merge behavior intentionally; never resolve by wholesale replacement.
5. Preserve package metadata, runtime configs, schemas, CLIs, services, and
   tests.
6. Run focused tests after each bounded integration unit.
7. Do not create a new clone/worktree to evade the dirty shared checkout.
8. Do not mark `MF-P6-20.01` or `20.02` complete until the inventory and
   integrated tree are independently reviewable.

## Full-test procedure

Run tests in tiers:

1. JSON/schema/compile/format/secret/diff checks;
2. changed-path focused tests;
3. steward/routing/recovery/campaign tests;
4. mask/provider/ontology/hard-QA tests;
5. CLI/service/bridge integration tests;
6. clean-export install/import tests;
7. complete product collection and execution; and
8. required live bounded acceptance tests.

Record collected, passed, failed, skipped, blocked, and deselected counts.
Every skip must name its governed prerequisite. Missing checkpoints, datasets,
or services are not passes.

After two failures with the same root cause, stop successor churn and repair
the framework, dependency closure, or environment contract.

## Evidence procedure

For each completion-critical milestone, add one compact evidence-locator row
containing:

- tracker item and parent;
- source commit/tree;
- input/request/runtime/model/config hashes;
- output/artifact/validation/terminal/release hashes;
- exact evidence and recovery locations;
- reconstruction command;
- adoption decision;
- limitations and claims not made; and
- supersession link.

Verify the row against the live files. Historical Git objects may be recorded
as history but cannot satisfy current qualification without a current
source-bound receipt.

## Mask-safety integration procedure

Before mask promotion:

1. verify exact semantic resources;
2. run deterministic hard QA;
3. require provider agreement or explicitly governed adjudication;
4. require qualified primary and independent-family juror evidence;
5. enforce abstention for unavailable/unqualified/contradictory evidence;
6. ensure disagreement cannot map to pass;
7. preserve immutable parent and repair lineage; and
8. reconcile every campaign record.

Never use text-only reasoning, filenames, metadata, or static fixtures as
visual approval.

## Release procedure

Do not create the final release candidate until all direct blockers of
`MF-P6-22.01` are complete.

The release candidate must bind:

- source commit/tree;
- package/deployment hashes;
- dependency/runtime/model/config manifests;
- ontology/API/mode/provider compatibility;
- focused/full/live tests;
- campaign and visual evidence;
- evidence index;
- limitations;
- startup/health/shutdown;
- invalidation and rollback; and
- unique release identity.

Validate from a clean authorized environment. A mutable branch name or local
path is not a release identity.

## ComfyUI handoff and adoption procedure

1. Send one hash-bound adoption packet to the pinned ComfyUI session.
2. Require the ComfyUI session to acknowledge the exact release identity.
3. Apply no independent masking implementation as a substitute.
4. Run bounded live workflows for required modes and failure states.
5. Persist exact requests, masks, errors, state, and resource cleanup.
6. Test restart/replay, invalidation refusal, and rollback.
7. Return one terminal adoption disposition to the MaskFactory session.
8. Update tracker state only through `Plan/Tracker/tracker.py`.

Before this procedure passes, state explicitly that ComfyUI masking is
deferred pending MaskFactory release.

## Route and resource rules

All local GPU commands use `tools/run_with_shared_pod_gpu_lease.py`.
Serverless uses broker `decide`/`reserve`/`submit`/`reconcile` only.
OpenRouter uses one governed parent-namespaced Qwen-first advisory batch only
when useful. Never dual-submit, direct-call providers, start a second paid Pod,
preempt foreign work, or use Claude, Cursor, or EC2.

Route evidence receives product credit only when it is attached to a real
parent and the controller executes/validates the adopted result.

## Tracker rules

- Item metadata comes from the item files.
- Live status/evidence comes only from `tracker.py`.
- Preserve accepted `MF-P6-19.01` and `19.02`.
- `MF-P6-19.03` and `19.04` remain Plan-27 execution gates.
- Item 24 aggregates/integrates their evidence; it never reruns them.
- New Item-24 rows begin open and receive no retroactive credit from prose.
- A checked box, commit, unit suite, schema, manifest, or receipt is not enough
  unless the row's verify clause passes.

Required commands after authority/item changes:

```text
python Plan/Tracker/tracker.py rebuild
python Plan/Tracker/tracker.py validate
python Plan/Tracker/tracker.py report
```

## Completion language

Use:

- `SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE` until Plan 27 passes.
- `ULTIMATE_MASKING_SYSTEM_E2E_INCOMPLETE` until Item 24 and its dependency
  closure pass.

Do not say the project is complete because a subsystem, branch, campaign, or
test tier passed. Whole-product completion requires the integrated clean build,
full suite, reconstructable evidence, mask safety, immutable release, and
independent ComfyUI adoption.

## End-of-cycle handoff

Report:

- selected parent and dependency reason;
- exact source/path changes;
- tests and real runtime evidence;
- accepted artifacts and terminal outcomes;
- remaining blockers;
- resource/route state;
- tracker changes;
- Qwen/OpenRouter advisory units;
- Codex implementation/authority units; and
- whether ComfyUI masking remains deferred or has adopted an exact release.
