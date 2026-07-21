# Controlled Windows Restart Handoff — 2026-07-18

This file is the durable pre-restart handoff for the wedged WslService recovery. The containing Git
commit is the restart-handoff commit; its parent is the last validated product increment.

## Authoritative active worktree

- Root: `C:\Comfy_UI_Main_Masking`
- Branch: `codex/maskfactory-runtime-implementation`
- Validated product parent: `c421f8dd875f29ef39c30c39ad4fbf2a822cd9da`
- Upstream before this handoff: `545a550a3c415dcb2b37ee847ae1cb76a66e856c`
- Divergence before this handoff: zero behind, one ahead
- Product increment: MF-P6-09.03 complete; 53 focused authority/truth/bridge tests passed;
  tracker validated 798 items with 24 unresolved hard blockers
- Push state: local commit is preserved; GitHub returned HTTP 403 because the available credential
  resolves to `KevinGarrett-Scentiment`, which lacks write access to
  `KevinSGarrett/MaskingUltimate`

## Preserved dirty paths — do not clean, stage, overwrite, or relabel

Tracked modifications:

- `src/maskfactory/authority/__init__.py`
- `src/maskfactory/authority/operational_certificate.py`
- `src/maskfactory/validation.py`
- `tests/test_operational_certificate_issuance.py`

Untracked frozen worker paths:

- `configs/operational_autonomy_policy.yaml`
- `src/maskfactory/authority/operational_policy.py`
- `src/maskfactory/schemas/operational_policy_evidence.schema.json`
- `tests/test_operational_policy.py`

Untracked retained scope packets:

- `runtime_artifacts/agent_handoffs/scope_packets/20260718T144918-0500_mf_cursor_08_05_policy.json`
- `runtime_artifacts/agent_handoffs/scope_packets/20260718T144920-0500_mf_cursor_08_06_repair.json`
- `runtime_artifacts/agent_handoffs/scope_packets/20260718T144921-0500_mf_cursor_08_07_invalidation.json`
- `runtime_artifacts/agent_handoffs/scope_packets/20260718T144923-0500_mf_cursor_09_01_identity.json`
- `runtime_artifacts/agent_handoffs/scope_packets/20260718T150005-0500_mf_cursor_08_05_policy_r2.json`
- `runtime_artifacts/agent_handoffs/scope_packets/20260718T150006-0500_mf_cursor_08_06_repair_r2.json`
- `runtime_artifacts/agent_handoffs/scope_packets/20260718T150007-0500_mf_cursor_08_07_invalidation_r2.json`
- `runtime_artifacts/agent_handoffs/scope_packets/20260718T150008-0500_mf_cursor_09_01_identity_r2.json`
- `runtime_artifacts/agent_handoffs/scope_packets/p000_20260718T194919065Z_mf_cursor_08_05_policy_824de162.json`
- `runtime_artifacts/agent_handoffs/scope_packets/p000_20260718T194920961Z_mf_cursor_08_06_repair_e86c6033.json`
- `runtime_artifacts/agent_handoffs/scope_packets/p000_20260718T194922077Z_mf_cursor_08_07_invalidation_0c58adc4.json`
- `runtime_artifacts/agent_handoffs/scope_packets/p000_20260718T194923227Z_mf_cursor_09_01_identity_fd07561f.json`
- `runtime_artifacts/agent_handoffs/scope_packets/p000_20260718T200005913Z_mf_cursor_08_05_policy_r2_b7da27c8.json`
- `runtime_artifacts/agent_handoffs/scope_packets/p000_20260718T200006679Z_mf_cursor_08_06_repair_r2_70b835ba.json`
- `runtime_artifacts/agent_handoffs/scope_packets/p000_20260718T200007691Z_mf_cursor_08_07_invalidation_r2_a7bd8055.json`
- `runtime_artifacts/agent_handoffs/scope_packets/p000_20260718T200008519Z_mf_cursor_09_01_identity_r2_cffd67a4.json`

## Preserved worktrees

- `C:\w\mask-autonomy-bridge-plan` — branch `codex/mask-autonomy-bridge-plan`, HEAD
  `6361df208e01d183083ee6c113e016467a486706`
- `C:\w\mask8s_e0f53b6f` — detached HEAD `093b9b1d74fb21ec5653d9dae395af878a8f0909`
- `C:\w\mfw\a1fed8eb1622c878` — detached HEAD `093b9b1d74fb21ec5653d9dae395af878a8f0909`
- `C:\w\mfw\b90c7f19654319e1` — detached HEAD `093b9b1d74fb21ec5653d9dae395af878a8f0909`
- `C:\w\mfw\c2ad2d6d230fe405` — detached HEAD `093b9b1d74fb21ec5653d9dae395af878a8f0909`

## Restart boundary

- Commit `545a550a3c415dcb2b37ee847ae1cb76a66e856c` and
  `qa/live_verification/docker_maintenance_rollback_20260718T2132Z.json` remain unchanged.
- No Docker, WSL, provider, service, UI, model, test-suite, or runtime operation was started during
  restart preparation.
- After a normal Windows restart, verify host/WSL/Docker recovery before resuming any runtime-dependent
  operation. Do not discard any path or worktree listed above.
