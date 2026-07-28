# 17 — Local storage, session, and worktree hygiene

This instruction is binding for MaskFactory and for shared local operations
that could consume `C:` storage. It does not authorize deleting ComfyUI assets,
dirty user work, runtime evidence, or foreign project data.

## 1. Recurring session rule

Use only these heartbeat continuations:

- MaskFactory: `maskfactory-serverless-continuation-recovery` targeting
  `019f91d1-ea20-7d81-83ff-03d393eaa1f5`.
- ComfyUI: `persistently-wait-for-a6000-execution` targeting
  `019f9200-4805-7632-83d3-ee9ae614c603`.

Do not use project cron automations for continuous work. Cron jobs create
standalone Codex task/session records. The former PM, OpenRouter, and
Serverless reliability cron jobs are paused; their required routing invariants
are embedded in the two main-session heartbeat prompts.

Archive only superseded automation-run chats. Preserve both main sessions,
side conversations, user-created threads, and the newest diagnostic run when
it is still required.

## 2. Allocation gate

Run before every local worktree, clone, backup, or evidence allocation:

```powershell
python tools/check_local_storage_guard.py `
  --kind worktree `
  --expected-bytes <predicted-bytes>
```

The policy is `configs/local_workspace_hygiene_v1.json`.

- Warning: less than 75 GiB free.
- New allocation blocked: allocation would leave less than 50 GiB free.
- Full-repository bundles: always blocked.
- Maximum single incremental local backup: 1 GiB.

The CPU supervisor may continue useful work while allocation is blocked. The
gate prevents storage growth; it is not a reason to idle.

Do not create a replacement clone or worktree to escape a dirty checkout.
Resolve ownership path-by-path in the existing checkout. A new isolated tree
is allowed only for an actual execution requirement after the allocation gate
passes; it is never a substitute for reconciliation.

## 3. Recovery checkpoint format

Preserve:

1. exact Git HEAD, upstream, refs, and porcelain-v2 status;
2. binary worktree and index patches;
3. selected unique untracked source/configuration files;
4. automation definitions and exact main-session record when available;
5. SHA-256 manifest and independent re-read verification.

Do not create another raw `.git` archive or full repository bundle. Retain at
most two verified compact checkpoints for 24 hours unless a unique unresolved
recovery dependency is documented.

## 4. Worktree retirement

A worktree is eligible only when every condition is proven immediately before
retirement:

- zero tracked or untracked dirty entries;
- HEAD is contained by a remote branch;
- no process command line references the path;
- it is not the main checkout;
- no unresolved junction/reparse point can redirect deletion.

Use `git worktree remove` without `--force`. If Git partially unregisters a
tree or Windows reports access/reparse errors, stop and preserve the residual
for explicit inspection.

## 5. Artifact placement

- Large runtime/model/media outputs: authorized RunPod volume.
- Local repository: code, tests, compact schemas, manifests, and receipts.
- `F:\CodexRecovery`: compact verified rollback checkpoints only.
- Google Drive: compact manifests/receipts only, through the connected
  `MaskFactory_Recovery_Manifests` folder. A live upload/download SHA-256 probe
  passed on 2026-07-26; large runtime evidence remains on the named RunPod
  volume.

No status text may claim a Google Drive fallback merely because one was
planned; it must reference a successful byte/hash round-trip.

Outside a documented storage/recovery blocker, hygiene and bookkeeping together
must stay within 10% of active self-hosted-autonomy effort. Cleanup is a safety
control, not a progress substitute, and cannot advance runtime acceptance.
