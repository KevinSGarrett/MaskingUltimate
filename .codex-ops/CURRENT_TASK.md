# Current Task

Task ID: MASKFACTORY-SELF-HOSTED-AUTONOMY-E2E-20260726
Updated UTC: 2026-07-26T21:30:58Z

## Objective

Finish the MaskFactory self-hosted autonomous LLM continuous-operations
system so it performs most eligible engineering, patch/test/repair, mask
adjustment, deterministic QA, visual-review orchestration, evidence, recovery,
and campaign work with exception-only consolidated Codex handoffs.

Binding authorities:

- `Plan/27_SELF_HOSTED_AUTONOMOUS_LLM_CONTINUOUS_OPERATIONS_SPEC.md`
- `Plan/Items/23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md`
- `Plan/Instructions/16_SELF_HOSTED_AUTONOMOUS_LLM_CONTINUOUS_OPERATIONS.md`
- `Plan/SELF_HOSTED_AUTONOMOUS_LLM_PURSUING_GOAL_MESSAGE.md`
- `Plan/Tracker/tracker.py`

## Acceptance criteria

- The CPU-safe supervisor and durable mission/campaign ledger are committed,
  reconstructable, and restart-safe.
- Compatible work is batched into 25-mission or 100-mask campaigns rather than
  routine micro handoffs.
- Local GPU work uses the mandatory shared-Pod lease wrapper and releases after
  each atomic work cell.
- Serverless uses broker decide/reserve/submit/reconcile only; OpenRouter uses
  the governed Qwen-first advisory manager only; no dual submission occurs.
- Engineering patch/test/repair campaigns and mask hard-QA/repair/dual-critic
  campaigns produce one consolidated Codex adoption packet.
- At least 80% of eligible work is autonomously prepared, routine handoffs are
  at most one per 25 missions or 100 masks, and Codex usage per accepted
  artifact falls at least 70% from baseline.
- Duplicate execution/promotion is zero; terminal reconciliation and local
  lease release are 100%.
- One real 25-mission campaign, one governed 100-mask campaign, interruption
  and routing drills, and three consecutive target-meeting mixed campaigns
  pass before completion is claimed.
- Before the real 25-mission campaign, the committed runtime controller,
  guarded CLI, supervisor wiring, and CPU fake-runtime 25-mission E2E pass.
- The real engineering campaign uses one owned Qwen/vLLM lifetime with durable
  request intents, no duplicate reissue, exact terminal accounting, and one
  consolidated packet.
- Runtime acceptance counts real model requests and accepted artifacts;
  commits, tests, schemas, manifests, receipts, and static fixtures are
  supporting evidence only.
- Recurring continuation reuses the two pinned main-session heartbeat threads;
  no standalone cron task may create repeated project sessions.
- Local worktree/backup allocation passes the configured disk guard; repeated
  full-repository bundles are prohibited.

## Allowed paths

- `.codex-ops/`
- `Plan/`
- `src/maskfactory/steward/`
- `tests/steward/`
- `tools/` paths explicitly required by Plan 27
- `configs/` schemas/configs explicitly required by Plan 27
- namespaced `runtime_artifacts/self_hosted_llm_*` evidence

## Forbidden/out-of-scope paths

- Primary session data, Codex authentication material, secrets, and credentials.
- Unrelated dirty user work and unrelated runtime asset trees.
- Direct RunPod GPU launch outside `tools/run_with_shared_pod_gpu_lease.py`.
- Direct Serverless endpoint or OpenRouter/provider calls.
- Claude, Cursor, EC2, foreign-process preemption, destructive infrastructure,
  or a second paid Pod.
- Text-only mask approval or weakened hard/visual QA.
- Final Git/GitHub, infrastructure, tracker-completion, mask-authority, or
  adoption authority delegated to the self-hosted worker.

## Required commands/tests

- `python Plan/Tracker/tracker.py validate`
- `python Plan/Tracker/tracker.py report`
- focused steward, campaign-ledger, routing, recovery, patch/test, mask-QA,
  telemetry, and schema tests
- clean reconstruction and exact-byte runtime checks
- real 25-mission and governed 100-mask acceptance campaigns

## Stop conditions

- Missing verified backup for overlapping changes.
- Ambiguous destructive operation or unresolved credential/security authority.
- Contradictory governed truth or unreconciled ambiguous completion.
- No eligible inference route only blocks that mission; continue CPU-safe work.
- Do not stop the pursuing goal while any other Plan-27 lane is unblocked.

## First next action

`MF-P6-13.01` through `MF-P6-16.04`, plus `MF-P6-17.01` and
`MF-P6-17.02`, are tracker-complete. Finish the 25-mission engineering runtime
controller and focused tests, add its guarded CLI, wire it into the supervisor,
and run the CPU fake-runtime 25-mission E2E. Then run `MF-P6-19.01` as one real
25-mission Qwen campaign before any non-defect Plan/schema/hygiene wave.
Continue `MF-P6-17.03`/`17.04` into the governed 100-mask campaign, then close
the measured sustained acceptance rows under `MF-P6-18` and `MF-P6-19`.

Every heartbeat records executable-integration, real-request,
accepted-artifact, and terminal-runtime deltas. A zero production delta forces
the next action to runtime integration/execution. Static fixtures are
`STATIC_PASS_CONTROL_PLANE_ONLY`; bookkeeping/hygiene is capped at 10% outside
a blocking defect; successor packets require a material immutable change; and
replacement clones/worktrees cannot substitute for checkout reconciliation.

Tracker/selector authority reconciliation: after the verified controller,
guarded CLI, supervisor, and CPU fake-runtime E2E foundation, select
`MF-P6-19.01` ahead of later mask/telemetry/acceptance rows. `MF-P6-18.04`
consumes the first campaign's telemetry and does not block it; this scheduling
rule does not mark any runtime or throughput acceptance row complete.

## Authority-reconciliation checkpoint

- Path:
  `C:\Comfy_UI_Main_Masking\.codex-ops\backups\self_hosted_authority_reconcile_20260726T220918Z`
- Manifest SHA-256:
  `68a8a6a5e203f08705895ceb37554ecbb32f1355bfd8bda8b07bdb3dfca85df2`
- Integrity: all 18 scoped authority, selector, tracker, and heartbeat entries
  re-hashed successfully before the dependency/priority reconciliation.
- Scope: `MF-P6-19.01` now has only its direct routing/engineering dependency
  gates. Later telemetry and acceptance rows consume the first real campaign's
  evidence; they remain incomplete and the guarded runtime remains the
  prerequisite authority.

## Verified rollback checkpoint

- Pod path: `/workspace/maskfactory/runtime_artifacts/session_backups/self_hosted_continuous_ops_before_change_20260726T060856Z`
- `SHA256SUMS` SHA-256: `062ca2f37ea2f23f14d4c363750267fecc15c5787cd727aa8f1014c174042fb5`
- Integrity: every listed file returned `OK`; Git HEAD, branch, dirty status,
  binary worktree/index patches, HEAD bundle, relevant untracked-path list,
  and overlapping source/test/Plan/config snapshot are included.

## Local recovery and hygiene checkpoint

- Path: `F:\CodexRecovery\maskfactory_recovery_20260726T145600Z`
- Manifest SHA-256:
  `7d4d26ae7ac1ce3e2e5d14501a8e3d386404636c19ef584065bbf923e0a77cda`
- Integrity: 364 files verified; 350 untracked source/configuration files,
  binary worktree/index patches, refs/HEAD/status, six automation definitions,
  and the available main-session raw record.
- Storage recovery: removed only the redundant 24.0 GiB raw-Git archive after
  proving its HEAD exists locally and on multiple remote branches; its small
  HEAD/status/manifest evidence remains.
- Session recovery: three standalone cron automations are paused; the two
  pinned 10-minute heartbeats remain active and target the exact main threads.
- Local guard: `configs/local_workspace_hygiene_v1.json`,
  `src/maskfactory/steward/storage_guard.py`, and
  `tools/check_local_storage_guard.py`.
- Final recorded free space: 84.119 GiB, above both the 50 GiB allocation
  floor and 75 GiB warning threshold.
- Recovery receipt:
  `qa/live_verification/local_storage_session_hygiene_recovery_20260726.json`
  (SHA-256
  `c558861c7b0bb005e98937f086c6868008fb654640191a2c1c3dd33dbac0aab1`).
- Google Drive compact-manifest fallback:
  `MaskFactory_Recovery_Manifests` (`1p-C603pKnQZYay5hxarM2DGB6WVPXbfQ`);
  the 4,028-byte recovery receipt round-tripped byte-identically at SHA-256
  `c558861c7b0bb005e98937f086c6868008fb654640191a2c1c3dd33dbac0aab1`.
- Dirty-checkout boundary at final audit: branch
  `codex/maskfactory-runtime-implementation` was 10 commits behind and 24
  commits ahead of upstream, with 30 tracked status entries and 1,675
  untracked files. Reconcile by explicit path ownership in this checkout; do
  not reset it or create another clone/worktree to avoid the reconciliation.

## Routing reconciliation delta checkpoint

- Path:
  `C:\Comfy_UI_Main_Masking\.codex-ops\session_backups\routing_reconcile_before_change_20260726T182500Z`
- `SHA256SUMS.tsv` SHA-256:
  `415aee9d6bddb4376e9f06d6ebd92d58c55f6b7f45bfb3815b6fdcf686346c0e`
- Integrity: all 15 listed delta files re-hashed successfully. The checkpoint
  contains exact copies of every existing overlapping routing source/test,
  HEAD/status, and scoped index/worktree patches.
- Scope: no new full Git bundle was created; the verified full recovery
  checkpoint above remains the repository-wide rollback authority.

## Last-mile authority update checkpoint

- Path:
  `F:\CodexRecovery\maskfactory_last_mile_authority_20260726T212739Z`
- Manifest SHA-256:
  `b891b7e1c2c43d55785b62ce2e07134f88d889374684fa45c035c0c727adfaa4`
- Integrity: all 29 listed files re-hashed successfully; the 647,016-byte
  upstream-to-HEAD incremental Git bundle passed `git bundle verify`.
- Scope: exact pre-change copies of the self-hosted authority, instruction,
  item, tracker/report, phase, and heartbeat definitions plus scoped binary
  patches. The existing repository-wide checkpoint remains the recovery base;
  no prohibited full-repository backup was created.

## Four-hour readiness review

- Audit snapshot: control plane 85–90%, working autonomous runtime 45–55%,
  production qualification 20–30%, and end-to-end readiness 60–65%.
- Engineering delta: 27 commits, 70 source/tool/test files, approximately
  25,364 additions, and 317 passing steward tests with one Windows symlink skip.
- Runtime delta: three drill roots, 33 files, 266,072 bytes; no real
  25-mission campaign, no real 100-mask campaign, and no three consecutive
  target-meeting mixed campaigns.
- Binding conclusion:
  `SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE`.
- Full evidence and corrective sequence:
  `Plan/SELF_HOSTED_AUTONOMY_FOUR_HOUR_REVIEW_20260726.md`.

## Recovery-continuation checkpoint

- Path:
  `C:\Comfy_UI_Main_Masking\.codex-ops\backups\self_hosted_authority_resume_20260726T215828Z`
- Manifest SHA-256:
  `97f5abafb0b20156603f328840c059d17a078ff16959290fc9e4be4839234b87`
- Integrity: all 15 scoped entries, including the current authority/config/tracker
  bytes, active heartbeat definition, and scoped binary worktree/index patches,
  re-hashed successfully.
- Allocation: the checkout-volume incremental-backup guard admitted 2,500,000
  bytes with 96,766,853,120 bytes free. `F:\CodexRecovery` is currently below
  the 50 GiB floor, so no new recovery-volume allocation was made.
- Scope: recovery continuation only. This checkpoint does not create runtime
  evidence or change the binding
  `SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE` status.
