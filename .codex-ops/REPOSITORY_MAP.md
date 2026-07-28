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

Exactly two registered Masking worktrees remain: the dirty recovery checkout
and clean `main`. Remote heads are `main` plus six explicit recovery refs;
local branches are `main` plus the branch checked out by the dirty recovery
checkout. See `.codex-ops/MAIN_PROMOTION_AND_BRANCH_CLEANUP_20260728T152359Z.json`
and `.codex-ops/LOCAL_DIRECTORY_DISPOSITION_20260728T153321Z.md`.
