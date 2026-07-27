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

### Unresolved mixed-parent controller binding

The present fallback dispatcher can advance Serverless and OpenRouter
concurrently only for different `mission_id` values. Its v1 work-item and
adapter identities bind `mission_id` and `session_id`, but do not yet bind an
explicit immutable `parent_campaign_id`, parent-contract hash, or child role.
Consequently, it cannot prove that a Serverless child and a consolidated
OpenRouter child are parts of the same parent outcome rather than unrelated
coexisting work. This is a structural implementation gap, not a reason to
relax the current legacy-recovery one-worker caps.

The campaign controller must add and test immutable parent/child binding,
per-parent child-role admission (one active child per role), terminal
suppression, cost and route ledger reconciliation, and a mixed-parent test
pair. The pair may permit one Serverless and one OpenRouter child below the
same parent only after each has a distinct immutable child identity and the
parent can reconcile both; it must never allow two children of the same role
or turn an admission rejection into a retry. Until this exists and is proved
with real parent work, `FALLBACK_CAPACITY_UNPROVEN` remains binding.

The RunPod browser is currently at an authorized-console sign-in page. No SSH
or Jupyter bypass is authorized. Consequently, local tests prove the control
plane, not the actual execution host or capacity.

## OpenRouter and legacy-daemon containment

OpenRouter remains governed, read-only advisory work. The shared manager's
one-active-session and terminal-parent guard is committed in ComfyUI commit
`a9be7460`; it permits one bounded parent-namespaced Qwen advisory, rejects a
second active child before provider work, and blocks a child under a terminal
consolidated parent. It cannot approve masks, replace strict VLM QA, or supply
Serverless capacity credit. Last reconciled state was zero active reservations
and zero reserved cost; no new reservation is authorized here.

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
