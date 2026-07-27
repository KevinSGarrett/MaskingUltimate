# Self-hosted autonomy fallback corrective audit — current sequence

**Authoritative as of:** 2026-07-27 UTC
**Scope:** MaskFactory session `019f91d1-ea20-7d81-83ff-03d393eaa1f5` and its
shared ComfyUI fallback boundary. This audit supersedes earlier historical
snapshots in this file; those snapshots must not be used to select work,
restart a daemon, or claim throughput.

## Executive state

The system has meaningful, independently checked implementation progress, but
it is **not** an end-to-end autonomous workforce yet. The only valid overall
status is `SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE`.

`MF-P6-19.01` and `MF-P6-19.02` are accepted, terminal evidence. They must not
be rerun. `MF-P4-11.23` remains `in_progress` at 20 percent; its current
visual-reference and 66-class records are screening evidence only, with zero
qualified mask truth, qualified primary critic, independent-family juror, or
promotion eligibility. `MF-P6-19.03` and `MF-P6-19.04` remain open.

Fallback capacity is explicitly `FALLBACK_CAPACITY_UNPROVEN`. Historical V12 is
semantic-positive reference evidence only, not a new capacity result. A real
locally-unavailable parent campaign must complete one source-and-parent-bound
child route and terminal reconciliation before capacity can be credited.

## Accepted evidence — do not recreate

### MF-P6-20.01 source-integration baseline — evidence only

Commit `ff5d0e949346fecfa3868e5b63751642e1c9d6a2` adds exactly four owned
inventory paths and no tracker, authority, provider, route, or GPU mutation.
Its durable artifact is
`qa/live_verification/mf_p6_20_01_canonical_source_inventory_20260727.json`
(1,277,971 bytes; raw SHA-256
`8f13f384c495b8c1131a8a4ae542a5166f2026c30e82706ea916fe81d944bb76`; canonical
zero-self SHA-256
`0bbc2af0d842eb54e85291787313cb01074c9c38c899ae5d0d74834a9b1ff429`). It
compares full-product candidate `7d66ca27781d899a43eb644c0378bcf1478045a7`
(1,596 paths) with autonomy `0d2efa6ff2b9a35b064d33bedbbdcab06517a685`
(105 paths) and the preserved dirty-worktree union (1,819 paths).

Replay is object-equal and the focused inventory/continuous-contract wave
passed 13 tests, Ruff, compileall, diff, and secret checks. Classification is
1,554 full-only, 63 autonomy-only, 25 divergent, 17 identical, and 160
worktree-only paths. Crucially, 1,731 paths remain unresolved. The artifact
sets `completion_credit_claimed=false`; therefore `MF-P6-20.01` remains open
until each conflict is resolved or superseded with behavior and evidence. The
baseline prohibits a wholesale merge, reset, or replacement worktree while that
work proceeds.

Production delta `cc3f1fe9d2d44677b0b2261f04211b8fd35c8190` resolves exactly
three steward paths (`src/maskfactory/steward/__init__.py`, `core.py`, and
`runtime.py`) as `resolved_behavioral_autonomy_superset`. Its closed-schema
receipt binds full-product/autonomy Git objects, current worktree SHA-256, and
byte-identical candidate test blobs:
`qa/live_verification/mf_p6_20_01_source_resolution_steward_core_20260727.json`
(raw `27024c2c50de49997db5112711bfb83fec775b8c2a42fd5ee8443453a5fc0fd6`, self
`7a4b17a3ca7ef51c05e4003f269a14e2cf67a5c66af238bb7282226f51338f10`). The
updated inventory is raw
`f98eadb84642b9e9c3d6c12d96a776dc5ba563e784acdc45225ae12376f3af98`, self
`7574f1f2b5846626ab6a834838b97f67c9a4aacb6232eeb6dad6a79bd90d5c33`, reducing
unresolved paths from 1,731 to 1,728. Candidate-identical core/runtime
regressions passed 23 tests; the relevant wave passed 37, with public-import,
replay, Ruff, compile, diff, secret, and tracker validation clean. This is a
bounded reconciliation, not `MF-P6-20.01` completion or route capacity credit.

- `MF-P6-19.01`: 25 completed / 0 failed engineering missions, one service
  generation, 50 real replay requests and unique responses, 25 accepted
  canonical proposals and releases, no request-binding mismatch. The immutable
  adoption packet is
  `/workspace/maskfactory/runtime_artifacts/self_hosted_llm_engineering_campaign_25_v2/campaign_inbox/engineering-campaign-d15a6b871cff0d0b7cba/runtime_adoption_packet_20260726T233000Z/engineering_campaign_runtime_packet.json`
  (raw `ac15d7a995b234cb52c7a2a6ba66733d220dda76836cbb2d4b36a7aa80b16d40`,
  self `ed811efaeaba1cf5c3e4c037dfd4cf56d3071eb3778a6589c4d7f0e341d64f90`).
  The scoped decision is `ADOPT` for this item only.
- `MF-P6-19.02`: persisted-terminal adoption/no-reissue and all-route recovery
  are proven by the actual-child interruption receipt (raw
  `10368c1eb64c1b02dd7dca8e6ef570da3971342a08467d3fd7c26bbd5da5c8ea`, self
  `0ec2e01aceb1d5cff3678680882294da93120d607b7c9fbd120bd63c575002ea`) and
  the all-route receipt (raw
  `69984ecac0c7c3cd20f1b04d05fecdf51fbc45a144c0b8973716866cbc5db0a5`, self
  `44fce90f6a7f6bdaf4a70913771d9089e7798c2af9cb5bcb995583e17c6fa61f`).
- V7–V11 Serverless outputs are terminal and unusable
  (`native_box_runtime_ready=false`); they are DNR. V12 is retained history
  with `native_box_runtime_ready=true`, but supplies no current capacity credit.

## Canonical fallback contract

The canonical Serverless manager is
`tools/manage_runpod_serverless_overflow.py` at commit
`9180e120fc1b9a54e9af2cd081a8bd64881019de`. It contains a provider-free,
no-broker-write `preflight` command. Its current manager SHA-256 is
`5f373471d3b0ca9e9b03402a9a6a3f4b26a4cedc3599ca90414f1d7b3e8623e3`; the
configuration SHA-256 is
`296da38c7b4fb1a689cdb4353a70cb3dab8f5bd5fa19a2b7490748f3639a906c`.

The exact non-Windows execution-host mapping is:

```text
python3 /mnt/c/Comfy_UI_Main_Masking/tools/manage_runpod_serverless_overflow.py
  --config /mnt/c/Comfy_UI_Main_Masking/configs/runpod_serverless_overflow.yaml
  --root /workspace/.maskfactory/serverless_overflow
```

That root owns `/workspace/.maskfactory/serverless_overflow/overflow.sqlite`;
there is no separate jobs root. The post-login, provider-free preflight is:

```text
python3 /mnt/c/Comfy_UI_Main_Masking/tools/manage_runpod_serverless_overflow.py --config /mnt/c/Comfy_UI_Main_Masking/configs/runpod_serverless_overflow.yaml --root /workspace/.maskfactory/serverless_overflow preflight --session-id 019f91d1-ea20-7d81-83ff-03d393eaa1f5 --expected-manager-sha256 5f373471d3b0ca9e9b03402a9a6a3f4b26a4cedc3599ca90414f1d7b3e8623e3 --expected-config-sha256 296da38c7b4fb1a689cdb4353a70cb3dab8f5bd5fa19a2b7490748f3639a906c
```

It must produce a retained self-hashed host/path/ledger availability receipt.
Only then, for one eligible immutable parent, may the controller perform
`decide -> reserve -> submit -> reconcile`. No direct endpoint call, duplicate
submission, V7–V11 reissue, detached child job, or retry after an ambiguous
outcome is permitted.

### Mixed-parent controller binding — implemented control plane, no capacity credit

Commit `e4793cca1b1ec4c1ccb6c993464d61debbb6ec16` implements the missing
immutable parent/child boundary without changing the accepted canonical
mission route replay state machine. V2 work items and advisory requests bind
64-hex `parent_campaign_id`, parent-contract hash, declared child roles, and
one derived child mission ID per role. A parent ledger in the same SQLite file
enforces `UNIQUE(parent_campaign_id, child_role)` and unique child mission
attachment under `BEGIN IMMEDIATE`; both metadata schema keys now bootstrap
atomically. Existing canonical missions cannot be retroactively attached.

A mixed parent may have exactly one `serverless_execution` child and one
`consolidated_advisory` child; each has its own immutable identity and route.
No second child of either role can enter, terminal `unavailable` cannot reopen
the role, outcome-unknown vetoes parent closure, and terminal reconciliation
requires a result hash. A manager-proven OpenRouter failure now seals its
terminal receipt before token release, avoiding heartbeat rediscovery. Legacy
unbound work items, requests, and prepared workloads are preserved but
non-executable.

The shared manager contract is CUI commit `4a1e3420`: new reserves require
`--parent-campaign-id`, `--parent-contract-sha256`, and `--child-role`; reserve,
submit, inspection, and reconciliation receipts carry and validate the
canonical `comfyui.openrouter_parent_binding.v1` digest. Commit `0e805e63`
adds policy-admitted capability tiers while retaining governed model admission.
Commit `dcb7719f` (with control record `f6b9ca46`) seals a reviewed global
manager cap of four active reservations by default, configurable only through
reviewed policy in the range 1–16. The existing one-active and terminal
suppression rules still apply per explicit immutable parent+contract, and a
fifth distinct parent fails closed. The current shared manager SHA-256 is
`791de44113a74257b3baeda3ee3a56f7306b932d5e4b49beee2d7855837145ac` at that
capacity checkpoint. Commit `b9008a5c` then fixes a real five-contender CPU
lock-sentinel publication race: the fully written sentinel is fsynced and
atomically published before any contender can observe it, yielding exactly four
durable reservations and a fifth capacity rejection rather than a transient
lock failure. Control record `b03ba777` binds that repair. The current manager
SHA-256 is `a62ac97c555d63b268f402369d96308ab747a17c478b6833ec3a8e7c607c94b7`;
the focused OpenRouter/Serverless-validator suite has 63 passing tests plus
Ruff/compileall. Read-only manager ledger status remains `0/4`.

`MASKFACTORY_ADAPTER_SEALED`: MaskFactory's `GovernedOpenRouterAdvisory` v2
constructs the exact manager reserve argv and validates manager
reserve/submit/inspect/reconcile parent-binding receipts against that sealed
contract. Its controller-side parent/child ledger mechanics and adapter are
therefore independently proved. The local rerun passed 46
parent-binding/producer/advisory tests and 31 supervisor/broker tests, with
Ruff, compileall, and diff checks clean.

`CROSS_CONTROLLER_INTEGRATION_OPEN`: CUI's separate primary-controller tip
`dd93e09c` does not yet build and consume that binding. The two systems cannot
yet be treated as one end-to-end controller, and no test has exercised a real
same-parent provider run across that boundary.

`MISSION_SIZE_GATE_OPEN`: the current controller guard can classify a
one-second unit as an outcome-sized mission, while existing test fixtures use
inconsistent 600/900-second contracts. Terminal labels and parent identity do
not establish meaningful autonomous work. The integrated controller must
enforce and negatively test a policy-bound minimum mission-size/capability-work
threshold before admitting a paid or advisory child; otherwise a correctly
bound route could still recreate a micro-handoff loop.

`ROLE_BUDGET_GATE_OPEN`: the in-progress sizing implementation has a
hash-bound 30–90-minute phase plan and milestone requirement, but its primary
child ledger declares roles without yet binding each role to an immutable
payload/contract. A different payload could therefore reuse a role under the
same parent. The ledger must reject duplicate or replacement role use and prove
that result with negative tests before a parent can receive route capacity.

`CANONICAL_CALLER_PATH_GATE_OPEN`: the in-progress primary adapter canonicalizes
the OpenRouter command shape but currently accepts any local file named
`manage_openrouter_reasoning_fallback.py`. A same-basename substitute would
defeat the governed-manager boundary. Before production invocation, it must
resolve and bind the exact repository manager and policy paths (with their
contract hashes) and negatively reject a counterfeit basename.

`POLICY_LINEAGE_GATE_OPEN`: the current combined controller suite has 125
passing tests but nine manager cases require a governed work kind absent from
the primary branch's older policy. The two policy identities cannot silently
diverge. The controller must consume one exact reviewed policy contract and
hash, with explicit work-kind admission tests; neither weakening the tests nor
unreviewed expansion of admissibility is an acceptable repair.

`SERVERLESS_SUCCESSOR_GUARD_OPEN`: CUI's primary Serverless path still pins an
obsolete manager hash and its validator treats a provider-free `decide` probe
as authority to create a successor. That is unsafe reissue semantics. The
old primary binding is
`a1fca642ab78b4ceaf12a6c2f90abef061fce400a0a799a788bc9c2017d22e4f`; CUI
control record `0d653ae2` marks it ineligible. The current corrective manager
binding is
`5f373471d3b0ca9e9b03402a9a6a3f4b26a4cedc3599ca90414f1d7b3e8623e3`, and its
`decide` is explicitly non-authorizing. The primary controller must consume
that canonical manager/config/root binding, seal an actual-host preflight
receipt, and attach one immutable source-hash parent contract before it may
create a successor identity. Negative tests must prove that a stale hash, an
unmounted host, or a successful `decide` alone cannot authorize submission or
replacement. This record is defect evidence only, not a controller repair.

This does not permit a successor from `decide` alone, relax the legacy
owner-recovery 1/1 worker caps, execute a provider job, or grant
`FALLBACK_CAPACITY_UNPROVEN` any credit. `NO_CAPACITY_CREDIT` remains binding
until the CUI primary controller consumes the exact CUI manager contract and
the mission-size, role-budget, canonical-caller, and policy-lineage gates
reject unsafe work, and the Serverless successor guard is sealed, then one
real parent retains host preflight, completes its source-hash-bound child work,
applies/tests/QAs its result, and reconciles both children to terminal state.

The RunPod browser is currently at an authorized-console sign-in page. No SSH
or Jupyter bypass is authorized. Consequently, local tests prove the control
plane, not the actual execution host or capacity.

## OpenRouter and legacy-daemon containment

OpenRouter remains governed, read-only advisory work. ComfyUI commit
`a9be7460` remains the conservative legacy containment guard for callers that
cannot supply a parent contract. For new work, commit `4a1e3420` supersedes
that coarse session-only identity with the all-or-nothing immutable
parent/contract/role binding described above: one active child for a given
parent+contract, terminal suppression until a new contract hash, and receipt
verification across reserve, submit, inspection, and reconciliation. The
MaskFactory adapter supplies that exact binding; until the separate CUI primary
controller does too, it cannot issue new OpenRouter child work. Any admission
rejection is terminal containment, never a retry job.

Neither guard can approve masks, replace strict VLM QA, or provide Serverless
capacity credit. The last reconciled shared-manager state was zero active
reservations and zero reserved cost; this task is not authorized to create a
new reservation.

At the latest local observation, externally owned PID `52556` is still running
the obsolete fallback supervisor with a disposable-worktree Serverless manager,
a non-canonical Windows broker root, and four workers for both fallback
routes. It is not a valid controller and must **not** be killed or restarted
from this task. Its owner alone must: pause intake; reconcile/drain existing
ledger state; ensure admission rejections never create retries; perform
controlled shutdown; verify parent exit and no child submitters; then restart
once, using canonical default Serverless source/config/root and one worker per
route. Until that happens, it is a containment risk, not evidence of work.

The owner has now independently completed the read-only pre-shutdown drain
audit. PID `52556` remains live and orphaned (recorded parent `4960` absent),
with only `conhost.exe` as its direct child; it received no signal. Supervisor
health is `healthy` / `cpu_safe` with `gpu_held=false`, queue count is zero,
campaign and throughput are idle, and both `openrouter_advisory` and
`serverless_overflow` route queues are zero. A read-only query found no active
canonical-route attempts or missions. The authoritative OpenRouter ledger has
zero `RESERVED`, `SUBMITTING`, or `SUBMITTED` entries (194987 bytes, SHA-256
`97bf60a19095b0739b4be74dceaa23bffc641b795fd054d93c52cefdb892a84b`). The
manager status command was deliberately not used because it acquires a write
lock. This is a precondition for, not completion of, owner-led shutdown: the
owner must still perform controlled exit and verify that PID `52556` and its
child are gone before any canonical restart.

Only the MaskFactory and ComfyUI source-task heartbeats remain active. All
standalone fallback supervisor/delivery and shared OpenRouter cron loops remain
paused.

## Visual and telemetry gates

- The current visual-reference receipt is
  `qa/live_verification/mf_p4_11_23_visual_reference_readiness_20260727.json`
  (raw `a0d23229f76737470edf0321d877bc39fe3c9f56b10e0fa4042bdaca2a8ab9c2`,
  self `65cc4159b08e0bd83df9057df675f2cd86895097ed8be068920fe91879c4490e`).
  Direct inspection exposed metadata false positives; it permits screening,
  not candidate selection or qualification.
- The exact 66-class matrix is
  `qa/live_verification/mf_p4_11_23_visual_66_class_gap_matrix_20260727.json`
  (raw `fd9d120aee21f24be1d4e511d2469b7b88dcdeaef9b60ac129898b0dc9e650e2`,
  self `0216c77a60e43098010751bba9b7fcccf51584d066d7fac7a81074efefe6153f`).
  It records IDs 0–65 with 61 coarse hints, 14 external mappings, 13
  calibration-only classes, and zero qualified truth/critic/promotion classes.
- Telemetry deploy closure is repaired in `a18bf88b0`; one clean authorized
  host bundle build is still pending after console reauthentication. No
  `MF-P6-18.03` evidence or 100-mask credit follows from the repair alone.

## Required execution order

1. Preserve accepted `19.01`, `19.02`, and V12; do not rerun or duplicate.
2. Owner drains and replaces the obsolete supervisor exactly once, if and when
   it is safe; all retry-on-admission logic remains disabled.
3. After authorized console reauthentication, retain the canonical no-write
   host preflight receipt. Run the repaired one-manifest telemetry build once;
   retain its terminal bundle or typed failure.
4. When a real eligible parent is locally unavailable, execute exactly one
   source-and-parent-bound fallback sequence through the broker and reconcile
   it. OpenRouter, if needed, is at most one governed advisory batch for that
   same parent.
5. Build qualified real-image visual truth and independent strict critics for
   the 66-class/risk matrix, then run the governed 100-mask campaign
   (`19.03`) with exact outcome, visual, QA, promotion, and cost accounting.
6. Run the three consecutive mixed campaigns and immutable final operating
   packet required for `19.04`. Only then evaluate overall completion.

## Control-plane verification

- `python Plan/Tracker/tracker.py validate`: no structural problems; 894
  non-orphaned items and 42 unresolved hard blockers at last check.
- `python -m pytest tests/steward/test_continuous_contract.py -q`: 10 passed.
- `validate_freeze_registry(Path('.'))`: no problems. Current freezes are
  Plan 27 `5b4cbf7de284f20c6c10f9575b3919c8d3ac9e34498f523d5f330cc563a3604f`,
  Instruction 16 `8cbba015ff84c836975d4a2ca03349d095ab8bb99c21a509e3efe2650b8d371b`,
  registry self `db81e6b4717e82026490c8a6780712f3867fe1ca527e950e20a9889267cd6a79`.
- Local storage guard is clear; Ollama loopback is reachable, while the local
  Docker CLI is absent. This is a runtime snapshot only, not strict-VLM
  qualification or a production claim.

## Recovery checkpoint

Before this consolidation, the prior audit and scoped state were copied and
hash-verified at
`.codex-ops/backups/audit_sequence_consolidation_20260727T010900Z` with
manifest SHA-256
`d6257a99d9040d2d1f1b494094f39d054767d74125142126f2fe6028a31816d5`.
