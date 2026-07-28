# Review Findings — MaskingUltimate / `C:\Comfy_UI_Main_Masking`

**Review date:** 2026-07-27  
**Reviewed inputs:** uploaded `Plan(2).zip`; uploaded compact local-directory snapshot; GitHub repository `KevinSGarrett/MaskingUltimate`.

## Executive finding

The project should not return to a broad autonomous “finish everything” loop. It currently has multiple materially different authorities: a stale GitHub `main`, older open PR lines, a much newer local/runtime line, a large dirty/untracked working state, and accepted runtime evidence that is not yet bound to one complete clean source tree. The correct recovery is the 20-gate sequence in this package.

## Verified inventory

- Local tracker: **906 items**.
- Complete: **621**.
- Remaining: **285** — 120 partially complete, 90 blocked, 61 open, 11 in progress, 3 deferred.
- Remaining hard blockers: **54**.
- Remaining rows explicitly requiring Kevin-supplied source/review/authority: **51**.
- The uploaded Plan bundle and the snapshot's Plan directory are byte-identical for all substantive files; the only Plan-zip-only files were Python cache files.
- Snapshot source identity: local branch `codex/maskfactory-runtime-implementation`, HEAD `2c04e1a7f5adf5f6948af01423f67a867206e8c2`.
- Snapshot Git state captured **712 porcelain entries**: 8 tracked modifications and 704 untracked path groups/entries in the compact status file.

## Clean-reconstruction defect found during this review

A fresh `pytest --collect-only -q` from the extracted snapshot fails during collection because `maskfactory.models` cannot be imported. The captured untracked inventory includes stale `src/maskfactory/models/__pycache__` paths, but the corresponding source package is not present in the snapshot. This strongly indicates prior test success depended on another checkout, an installed copy, or stale environment state. Section 2 must recover the authoritative source, and Section 3 must prove bytecode-disabled clean reconstruction.

The snapshot includes a prior green progress log with approximately 916 test outcomes and exit code 0. Plan 28 separately records a 4,446-test full-product surface that did not pass. These are different test claims; the smaller saved log cannot close the complete-product gate.

## GitHub divergence found

- GitHub `main` still exposes the older 393-item tracker and a July 11 dashboard at 102/393 complete.
- GitHub PR #1 is an open draft carrying a large full-product build line (95 commits, 846 files).
- GitHub PR #2 is an open plan/bridge line based on another non-main branch.
- PRs #3–#7 were merged into the non-main `codex/maskfactory-runtime-implementation` lineage, not into `main`.
- The local snapshot HEAD `2c04e1a...` is not currently resolvable as a commit in the GitHub repository.

Therefore, “what is complete” depends on which tree is inspected. Sections 1–3 eliminate that ambiguity before any downstream item may receive completion credit.

## Remaining work by phase

| Phase | Unresolved |
|---|---:|
| P0 | 3 |
| P1 | 9 |
| P2 | 13 |
| P3 | 14 |
| P4 | 32 |
| P5 | 33 |
| P6 | 44 |
| P7 | 24 |
| P8 | 10 |
| P9 | 103 |


## Core versus optional closure

The required core profile still has unresolved canonical integration, current visual authority, real 100-mask/mixed-campaign proof, serving/bridge adoption, and final release work. Independent-real-accuracy and scale/DAZ-maturity remain separate optional profiles; they must not delay a valid core release, but they also must not be reported as complete without their own human-audit, scale, soak, and metric evidence.

## Recommended operating rule

One section is the **only active acceptance unit**. Preparatory long-lead work such as human annotation, approved asset transfer, or DAZ asset acquisition may overlap, but no later section may be marked accepted before all of its dependency sections are accepted. Every section ends with an immutable receipt, exact test evidence, rollback proof, and tracker-CLI update.
