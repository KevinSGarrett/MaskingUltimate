# MaskFactory repository map

Updated UTC: 2026-07-28T21:27:49Z

## Live repository and ownership map

| Path | Repository/role | Owner | Mutation rule |
| --- | --- | --- | --- |
| `C:\Comfy_UI_Main_Masking` | sole canonical MaskFactory worktree; local `main` based on remotely protected `68e159f4e43c656e3e5de61adc3acaed304debd6` with the bounded authority-attribution release in progress | Masking task | normal scoped MaskFactory development; restore clean local/remote parity at the release boundary |
| `C:\Comfy_UI_Main_MaskFactory_Consumer` | standalone isolated Consumer repository, clean at `1091a9c8cc01ff554907b97a7e754c6c884cee01` | Masking task | remotely protected; no rewrite; not canonical MaskFactory source |
| `F:\CodexRecovery` | MaskFactory recovery/checkpoint authority | Masking task | preserve; F: remains below the 50 GiB allocation floor |
| `C:\MaskFactory_TierA_Backups` | compact no-loss rollback, semantic-attribution, and restore authority | Masking task | add only storage-guard-admitted scoped checkpoints; verify every manifest |
| `C:\MaskFactory_TierA_RestoreTests` | bounded restore-test evidence | Masking task | temporary validation trees must be retired after proof |
| `C:\Comfy_UI_Main` | sole canonical Comfy_UI_Main worktree | Main task `019fa6cc-eb76-74c1-8fd1-f062cec56dad` | read-only coordination from Masking unless Main explicitly accepts a release/adoption action |
| `F:\Codex_Recovery` | Main recovery authority | Main task | no-touch from Masking |
| MaskFactory retained data/runtime/evidence roots | external governed authorities, not source checkouts | named owner in local directory ledger | preserve or disposition only through their exact receipts |
| MaskFactory VHDX backups | non-equivalent recovery artifacts | Masking task | no-touch pending restore proof; equal size never implies duplicate |

## Absent former worktree paths

- `C:\w` is absent after both repositories independently checkpointed,
  semantically dispositioned, and retired their owned children; its final Main
  authority is SHA-256
  `9a332e7fab8f0da346f2ca7cafa3152c12158fd8437e964083bb4bcf0c17a599`.
- `C:\Comfy_UI_Main_Masking\.codex-ops\worktrees\canonical-reconciliation-20260728`
  is absent. Its clean integration authority was promoted into the physical
  canonical root.
- No dirty Masking checkout or dirty-recovery worktree remains registered.
  Former dirty bytes remain independently reconstructable from recovery refs,
  verified Tier-A checkpoints, and the historical-stash bundle.

## Current topology

- local branches: one (`main`);
- registered Masking worktrees: one (`C:\Comfy_UI_Main_Masking`);
- remote heads: seven (`main` plus six intentional recovery refs);
- stashes: zero;
- generated repository-local pre-commit cache: absent;
- Git-reported garbage: zero; and
- shared `C:\w`: absent.

The terminal local-convergence receipt is
`.codex-ops/SECOND_PHASE_LOCAL_CONVERGENCE_FINAL_20260728T192134Z.json`,
SHA-256
`895ac2ef26940b7037b61f2ac3d36ff59058ed624284fb7c50af5ff365711041`.

## Rollback and active correction authority

The second-phase source/control rollback checkpoint remains:
`C:\MaskFactory_TierA_Backups\second_phase_preconsolidation_20260728T162424Z`,
registry SHA-256
`b2882e7cd50a8bd5f560d85846e6409b754a585b5496dd746aab6cf1ac654197`.

The active Plan/Item/Tracker attribution-correction checkpoint is:
`C:\MaskFactory_TierA_Backups\authority_attribution_before_change_20260728T201447Z`,
with 17 payloads / 8,472,585 bytes, zero verification failures, and
`SHA256SUMS.tsv` SHA-256
`c3cece21605225ea35b6467bf8b35e4fc4819b4d683df8335ef8d063866e4f08`.
It preserves the exact affected control/Item/tracker files, the original
4,008-row stash matrices, and clean Git/ref/status proof. No prohibited full
repository bundle was created because `HEAD` equaled remotely protected
`origin/main`.

The generated row-level attribution authority is:
`C:\MaskFactory_TierA_Backups\historical_stashes_20260728T182808Z\stash_semantic_authority_matrix_v2.json`,
12,426,344 bytes, SHA-256
`a4436d4a17c7d37990e15c47623b3d51899e1ecba9f7db0b4f9507003dc54930`.
Its 4,008 rows all bind Plan, Item, tracker, evidence, exact blob hashes,
canonical location, rollback, limitations, and completion effect. The compact
receipt is
`.codex-ops/HISTORICAL_STASH_AUTHORITY_BINDING_20260728T212749Z.json`.
