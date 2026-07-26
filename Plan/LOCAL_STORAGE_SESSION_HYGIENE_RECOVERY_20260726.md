# Local storage and session hygiene recovery — 2026-07-26

## Outcome

- Restored `C:` from approximately 2.5 GiB free to 84.119 GiB
  without deleting ComfyUI project assets.
- Verified a compact 421.6 MB recovery checkpoint on `F:` before cleanup.
- Removed the redundant 24.0 GiB MaskFactory raw-Git backup archive; its
  commit exists in the current Git database and on multiple remote branches.
- Retired two clean, remote-contained MaskFactory worktrees.
- Preserved one partially retired residual because Windows reported protected
  `cvat` content; no force deletion crossed that boundary.
- Paused three standalone cron automations that created recurring task
  sessions.
- Preserved and hardened the two main-session heartbeat automations.
- Archived 13 stale MaskFactory automation-run sessions and 25 additional
  superseded shared/Comfy automation-run sessions.
- Connected the governed Google Drive fallback and proved a byte-identical
  4,028-byte upload/download SHA-256 round trip for the compact recovery
  receipt in `MaskFactory_Recovery_Manifests`.

## Verified checkpoint

- Root: `F:\CodexRecovery\maskfactory_recovery_20260726T145600Z`
- Files: 364
- Bytes: 421,577,346
- Manifest SHA-256:
  `7d4d26ae7ac1ce3e2e5d14501a8e3d386404636c19ef584065bbf923e0a77cda`

## Storage guard

- Policy: `configs/local_workspace_hygiene_v1.json`
- Library: `src/maskfactory/steward/storage_guard.py`
- Operator check: `tools/check_local_storage_guard.py`
- Tests: `tests/steward/test_storage_guard.py`
- Focused validation: 9 passed; Ruff passed.
- Final live state: `C:` is above the 50 GiB allocation floor and the 75 GiB
  warning threshold. The guard remains binding so renewed growth fails early.
- Live negative checks:
  - full repository bundle → blocked;
  - 1 GiB worktree while below floor → blocked.

## Session/scheduler state

Active heartbeats:

- `maskfactory-serverless-continuation-recovery` →
  `019f91d1-ea20-7d81-83ff-03d393eaa1f5`
- `persistently-wait-for-a6000-execution` →
  `019f9200-4805-7632-83d3-ee9ae614c603`

Paused standalone cron jobs:

- `comfy-ui-main-timed-probe-anti-loop-supervisor`
- `shared-openrouter-fallback-capability-supervisor`
- `shared-serverless-fallback-reliability-supervisor`

An older deleted automation, `maskfactory-autonomous-continuity-supervisor`,
had left repeated 15-minute Masking task sessions. Its 13 visible stale runs
were archived.

## Remaining limitations

- Local space is currently healthy, but new worktrees still require the guard
  and full repository bundles remain prohibited regardless of free space.
- No local Google Drive filesystem mount is configured. The connected Drive
  fallback is verified only for compact manifests/receipts; large runtime
  evidence remains on the named RunPod volume.
- The main checkout remains heavily dirty and has diverged from upstream. Its
  unique work is preserved, but reconciliation must follow explicit path
  ownership; do not reset it or create another clone to escape it.
- `SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE` remains binding until the
  real 25-mission, 100-mask, interruption/routing, and three sustained
  campaign gates pass.
