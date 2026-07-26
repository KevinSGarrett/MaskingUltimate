# Current Task

Task ID: MASKFACTORY-SELF-HOSTED-AUTONOMY-E2E-20260726
Updated UTC: 2026-07-26T20:08:00Z

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
`MF-P6-17.02`, are tracker-complete. Continue the in-progress real campaign
lanes `MF-P6-17.03`, `MF-P6-17.04`, and `MF-P6-18.01` through
`MF-P6-18.04`, then close the measured acceptance rows under `MF-P6-19`.
Do not regress into micro-packet churn.

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
