# MaskFactory repository map

Updated: 2026-07-28

| Path | Repository/role | Owner | Mutation rule |
| --- | --- | --- | --- |
| `C:\Comfy_UI_Main_Masking` | dirty checkpoint-protected Masking recovery checkout | Masking task | no clean/reset/delete; reconcile by exact hash |
| `C:\Comfy_UI_Main_Masking\.codex-ops\worktrees\canonical-reconciliation-20260728` | clean Masking `main` checkout | Masking task | promoted Git/product authority |
| `C:\Comfy_UI_Main_MaskFactory_Consumer` | standalone isolated Consumer repository | Masking task | remotely protected; no rewrite |
| `F:\CodexRecovery` | Masking recovery/checkpoint authority | Masking task | preserve; F: below allocation floor |
| `C:\w` | mixed-repository physical worktree parent | owning git-common-dir | never bulk-delete |
| `C:\Comfy_UI_Main` and its worktrees | Comfy_UI_Main repository | Main task `019fa6cc-eb76-74c1-8fd1-f062cec56dad` | read-only coordination from Masking |
| `F:\Codex_Recovery` | Main recovery authority | Main task | no-touch |
| MaskFactory VHDX backups | non-equivalent recovery artifacts | Masking task | no-touch pending restore proof |

Second-phase rollback authority:
`C:\MaskFactory_TierA_Backups\second_phase_preconsolidation_20260728T162424Z`,
registry SHA-256
`b2882e7cd50a8bd5f560d85846e6409b754a585b5496dd746aab6cf1ac654197`.
It covers the 136 meaningful dirty-root source/control files and all 110
post-baseline files before consolidation mutation.

Shared `C:\w` currently contains 5,034,979,803 bytes. Ownership is unresolved
for the three large direct children until the Main task returns an exact
common-dir/archive disposition. Do not mutate them from Masking:

- `ci-sparse-validation` — 3,202,609,051 bytes;
- `worker-control-bridge-r4g-wrapper-failed-20260718` — 1,053,754,413 bytes;
- `fallback-incident-repair-20260726` — 778,599,790 bytes.

Exactly two registered Masking worktrees remain: the dirty recovery checkout
and clean `main`. Remote heads are `main` plus six explicit recovery refs;
local branches are `main` plus the branch checked out by the dirty recovery
checkout. See `.codex-ops/MAIN_PROMOTION_AND_BRANCH_CLEANUP_20260728T152359Z.json`
and `.codex-ops/LOCAL_DIRECTORY_DISPOSITION_20260728T153321Z.md`.
