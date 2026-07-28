# Local Authority Reconciliation Ledger - 2026-07-28

## Scope and recovery authority

This ledger implements Plan 29 for the protected checkout at
`C:\Comfy_UI_Main_Masking`, dirty HEAD
`61b4ffed850ab9570253acde5704a5bf44d4f7b6`.

The independently verified checkpoints are:

- baseline:
  `F:\CodexRecovery\maskfactory_reconciliation_checkpoint_20260728T042648Z`,
  registry SHA-256
  `903b960291b049ef26c4c36fa55d568158a0918763aea4a830fce5d1f11f2b0a`;
- incremental:
  `C:\MaskFactory_TierA_Backups\second_phase_preconsolidation_20260728T162424Z`,
  registry SHA-256
  `b2882e7cd50a8bd5f560d85846e6409b754a585b5496dd746aab6cf1ac654197`.

The incremental checkpoint contains the 136 selected meaningful files, the
exact tracked patch, all live status/untracked listings, 110 post-baseline
files, refs, worktrees, and remote heads. The live source/control universe is
137 unique files because `.codex-ops\CURRENT_TASK.md` is tracked but was not in
the 136-file selection.

Before the physical-root transition, a complete supplemental archive was
created at
`C:\MaskFactory_TierA_Backups\dirty_root_full_untracked_20260728T164707Z`.
It contains and readback-verifies 7,081 remaining nonsnapshot entries (7,052
files, 29 directories), 830,807,268 logical bytes, in an 843,448,320-byte tar
with SHA-256
`ec62c54e33a3de0b1a54c2b3d0f062bb642bc1b32ca2cbb5be6d6aaab61a9054`.
The five-entry registry revalidates at SHA-256
`2e0e3d6d617f442b2bfd3bf28efdb35398d1e2d5d2468a3bdad6da7998a436f3`.

The same checkpoint contains an exact 26,256-file, 1,264,564,175-byte ignored
inventory (SHA-256
`4597333c85e668fb9740dd100cd5069f3c3a74d1553b7a53ed8387c3562ba6fc`).
It consists of the reproducible `.venv`, pytest/Ruff caches, and tiny
HuggingFace download metadata and is `GENERATED_RUNTIME_ONLY`; it is
reconstructed from project/tool authorities, not adopted or backed up as
source.

## Exhaustive result

| Classification | Count | Canonical decision |
|---|---:|---|
| Exact bytes already in clean `main` | 99 | `ALREADY_PRESENT` |
| Different candidate/current bytes | 37 | reviewed below |
| Absent from clean `main` | 1 | historical handoff, `ARCHIVE_ONLY` |
| Total | 137 | zero unexplained source/control paths |

Eleven files are tracked modifications in the dirty checkout. Ten overlap the
136-file checkpoint selection; `.codex-ops\CURRENT_TASK.md` is the additional
file. The earlier checkpoint receipt's `dirty_untracked_count=7094` label
counted all porcelain rows and is not authoritative for tracked/untracked
partitioning. The bytes and archive entry counts remain valid.

## Thirty-seven differing paths

### Current control authority supersedes stale control text

The following dirty versions are preserved but not adopted because current
`main` contains the later repository-reconciliation state, Plan-29 rules, or
shared-FIFO GPU authority:

- `.codex-ops/CURRENT_TASK.md`
- `AGENTS.md`
- `Plan/05_SYSTEM_ARCHITECTURE.md`
- `Plan/06_ENVIRONMENT_AND_INSTALLATION.md`
- `Plan/10_LLM_VLM_QA_LAYER.md`
- `Plan/12_DATASET_TRAINING_ACTIVE_LEARNING.md`
- `Plan/13_COMFYUI_INTEGRATION.md`
- `Plan/14_IMPLEMENTATION_ROADMAP_WBS.md`
- `Plan/23_EXTERNAL_SUPERVISION_REFERENCE_DAZ_AND_MINIMAL_REVIEW_SPEC.md`
- `Plan/25_SELF_HOSTED_VISUAL_AUTHORITY_AND_RUNPOD_MIGRATION_SPEC.md`
- `Plan/26_ADULT_CORPUS_AUTONOMOUS_BATCH_INGESTION_SPEC.md`
- `Plan/DECISIONS_LOG.md`
- `Plan/DOCKER_RUNTIME_AND_SESSION_USE.md`
- `Plan/Instructions/02_AUTONOMOUS_OPERATING_RULES.md`
- `Plan/Instructions/03_SESSION_PLAYBOOK.md`
- `Plan/Instructions/13_SELF_HOSTED_STRICT_VLM_GATE.md`
- `Plan/Instructions/14_SELF_HOSTED_VISUAL_AUTHORITY_AND_RUNPOD_MIGRATION.md`
- `Plan/Instructions/15_ADULT_CORPUS_BATCH_OPERATION.md`
- `Plan/Items/05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md`
- `Plan/Items/06_ITEMS_P5_TRAINING.md`
- `Plan/RESTART_HANDOFF_AUTONOMOUS_20260719.md`
- `Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md`
- `Plan/Tracker/DASHBOARD.md`
- `Plan/Tracker/phases/P4.md`
- `Plan/Tracker/phases/P5.md`
- `Plan/Tracker/README.md`
- `Plan/Tracker/tracker.json`

The principal contradiction is explicit: the dirty versions repeatedly say
GPU/VRAM admission is disabled and production executes directly on a selected
Pod. Current authority requires every local RunPod GPU child to use
`tools/run_with_shared_pod_gpu_lease.py` and the shared FIFO. Reintroducing the
dirty text would weaken a binding safety/ownership contract.

`tracker.json` was compared item-by-item: no dirty-only item, note, status,
percent, evidence, or blocked reason exists. Therefore current tracker state is
the semantic superset; no stale state was replayed.

### Historical tracker and operational records

- `Plan/Tracker/CHANGELOG.jsonl`: `ADOPT`. Sixty-five exact JSON events from
  the dirty log were absent from current `main`. Their effects were already
  present in current item state/notes. The records were backfilled as history
  only, taking the log from 2,043 to 2,108 records, with zero dirty record
  absent afterward. No item state was changed by this merge.
- `Plan/OPS_LOG.md`: current `main` remains the active log and already contains
  a canonical reconciliation pointer. The dirty-only entries remain exact in
  both checkpoints. Their work is represented by committed receipts and the
  headings listed below; obsolete runtime instructions are not reactivated.

Recovered historical OPS headings include the 2026-07-21 standing-order,
Mode-B/CAA, hand-climb, strict-VLM, no-stop, and Pod-sync waves and the
2026-07-28 checkpoint, pack repair, WSL audit, bounded source recovery,
fallback/Serverless/external-supervision/repair/certificate/evidence/failed-
initialization/plan-modernization/Consumer/Climb4 reconciliations. Each
2026-07-28 operation has a committed `.codex-ops` receipt in current `main`.

### Parsed/AST-equivalent or stronger executable authority

| Dirty path | Disposition | Basis |
|---|---|---|
| `configs/multiprovider_tournament_families.yaml` | `SUPERSEDED` | parsed YAML equal; current formatting is canonical |
| `src/maskfactory/ontology_v2_resolution_preflight.py` | `SUPERSEDED` | Python AST equal |
| `tests/test_ontology_v2_resolution_preflight.py` | `SUPERSEDED` | import-order-only difference |
| `tools/run_multiprovider_gold_tournament.py` | `SUPERSEDED` | Python AST equal |
| `tools/run_tournament_ollama_critic_router.py` | `SUPERSEDED` | Python AST equal |
| `src/maskfactory/vlm/strict_gate.py` | `SUPERSEDED` | current removes unused state/exception binding; focused tests pass |
| `tools/smoke_strict_vlm_gate.py` | `SUPERSEDED` | current removes unused NumPy import; behavior retained |
| `tools/run_tournament_mvc_visual_hard_qa.py` | `SUPERSEDED` | current replaces legacy sequencer authority with mandatory shared GPU lease |

Focused verification:

```text
pytest tests/test_ontology_v2_resolution_preflight.py
       tests/test_strict_vlm_gate.py tests/test_vlm_config.py
=> 17 passed

ruff check <all seven reviewed Python source/test/tool paths>
=> PASS
```

Governing authorities and tracker mappings:

- all rows: Plan 28 sections 2-5, Plan 29, Instruction 17,
  `MF-P6-20.01`;
- ontology rows: Plan 18, OntologyV2 implementation checklist,
  `MF-P1-10.01` through `MF-P1-11.08`;
- strict-VLM/tournament rows: Instruction 13, Standing Orders strict visual
  gate, `MF-P4-01.01`, `MF-P4-11.16` through `.24`, and `MF-P6-21.03`;
- GPU-route replacement: `MF-P6-15.01`.

No product/runtime/visual completion status is raised by these supersession
decisions.

## One absent path

`Plan/SIDE_SESSION_RESUME_RUNPOD_SAM31_WORKCELL_20260723.md` is
`ARCHIVE_ONLY / SUPERSEDED_HANDOFF`.

It records the SAM3.1 visual-text box prompt repair, deterministic component
cleanup, RunPod work-cell files, one hard-QC-pass/strict-visual-abstain canary,
and explicit no-gold limitations. Its cited commits
`298c8f6be7cc67646592ee76d980abe78b50d333` and
`a82972dbe8f46b3f3cd9d10d629f8246fbcb3ecd` are ancestors of current `main`;
all fourteen listed work-cell source/tool/schema paths are present.

The handoff is not copied into active Plan because it instructs agents to use a
retired worktree and direct-Pod execution without the mandatory shared FIFO
lease. Its exact bytes remain in the incremental archive and its useful
implementation is already canonical.

## Tracker state

`MF-P6-20.01` is the non-duplicative governing row. Its metadata explicitly
requires scattered-directory, Plan/Item/Instruction/tracker, physical-root,
and rollback convergence. `tracker.py rebuild` preserved 906 items with zero
new or orphaned rows. After physical/root/shared-path convergence and the
fresh 5,139-node collection produced 5,098 passes, 41 governed skips, and zero
failures, `tracker.py set` closed only this repository-reconciliation row at
100%. `tracker.py report` and `tracker.py validate` pass
with 906 non-orphaned items, 53 unresolved hard blockers, and zero structural
problems. No successor product/runtime/visual/campaign row advanced.

## Shared `C:\w`

The phase-start total was 5,034,979,803 bytes. Ownership is coordinated with
Main task `019fa6cc-eb76-74c1-8fd1-f062cec56dad`.

- MaskFactory-owned `C:\w\mfw` was an exact zero-file/zero-byte shell and was
  removed non-recursively under
  `.codex-ops/MFW_EMPTY_NAMESPACE_RETIREMENT_20260728T163459Z.json`.
- Main owns the standalone sparse-validation clone, two generated
  runtime/evidence exports, one empty Main shell, and two patch files.
- Main may disposition neutral/foreign `active`, `aiw`, and
  `mask-autonomy-bridge-plan` only under the agreed exact preservation/empty
  gates.
- No task may remove any unassigned shared path or `C:\w` itself.

Main returned its exact post-disposition authority:

- checkpoint:
  `F:\Codex_Recovery\main_shared_cw_checkpoint_20260728T162954Z`;
- source manifest: 5,654 files / 1,832,370,752 bytes, SHA-256
  `aae95e1fb8706b66eb58c62eefe0ccabafb09faeaa12856a193403378ce769bd`;
- archive SHA-256:
  `4d04f897a58a0b0c07475b15590f19e6e7c0881c79fc4b341c06bd119330e196`;
- readback: 5,654/5,654 exact;
- semantic review: all 84 non-equivalent candidates dispositioned with zero
  unresolved and all 5,654 files Plan/Item/Tracker-bound;
- retirement: exactly nine assigned paths, 17,936 files including standalone
  Git objects, and 5,034,979,803 logical bytes;
- post-state: all nine paths absent and `C:\w` has zero direct children; and
- receipt SHA-256:
  `d4586b0608dace04eb30200429e3dee172c508d01ffc663cabdb821609a6625d`.

After both tasks confirmed that no process, worktree, ref, or dependency used
the parent, the exact empty non-reparse `C:\w` root was removed
non-recursively. Its receipt is
`.codex-ops/EMPTY_SHARED_CW_ROOT_RETIREMENT_20260728T172928Z.json`.

Main's terminal repository authority is clean local/remote `main`
`ee2717ab4d8985182e73b0a79c131b2076443952`, with one local branch, one
worktree, zero stashes, three intentional remote heads, zero open pull
requests, and full/connectivity fsck passing. Its committed final shared-path
receipt is `.codex-ops/SHARED_CW_SECOND_PHASE_FINAL_20260728T171508Z.json`,
SHA-256
`9a332e7fab8f0da346f2ca7cafa3152c12158fd8437e964083bb4bcf0c17a599`.

## Opaque nested repositories and runtime caches

After all hash-listed ordinary untracked/ignored files were removed, 28 nested
directories remained because their internal Git metadata made them
intentionally opaque to the first cleanup pass. The exact classification at
`C:\MaskFactory_TierA_Backups\opaque_nested_repos_20260728T171012Z\
opaque_directory_classification.json` covers 72,981 files and
2,849,108,209 logical bytes:

| Disposition | Directories | Result |
|---|---:|---|
| `GENERATED_RUNTIME_ONLY` | 22 | pre-commit and third-party runtime source caches retired |
| `SUPERSEDED` | 5 | four historical MaskFactory publish clones and one CVAT clone retired after ref/source review |
| `FOREIGN_OWNED` | 1 | Main inspect clone retired after Main containment confirmation |
| `BLOCKED_REVIEW_REQUIRED` | 0 | none |

Forty dirty files in the historical MaskFactory/CVAT candidates are retained
and readback-verified in `dirty_files.tar`, SHA-256
`432e4f7d7881474ef8b95af4359d14aaebe359ab8bb45c68f4480e882d4f332c`.
The current 66-class/P0-P9 authority semantically supersedes the historical
65-class/P0-P8 ontology candidate; no stale implementation was adopted.

The late Main-owned clone
`C:\Comfy_UI_Main_Masking\tmp\comfy_commit_inspect` contained 45 physical
files and 532,815,333 logical bytes. It was clean, had no HEAD, and had the
sole ref
`cb856abe617241e3e3beb374e849bbc16ca4b43e` at
`refs/remotes/origin/codex/wave88-autonomous-completion-20260726`. Main proved
that commit is contained by current local and remote Main and separately
preserved by its recovery authorities. Full fsck/pack checks passed, the exact
path is absent, and no product status changed. The deterministic Main commit
tree manifest SHA-256 is
`0e4e7a367b90c0b954e8edf1b2ea497a4ad422c651b8f900df7d0ce45da06668`.
The retirement receipt explicitly records that a physical 45-row `.git`-file
manifest was not captured; the directory registry binds its count/bytes and
the Main commit/tree binds its semantic content.

## Late historical-stash reconciliation

The final repository-state audit found five historical stashes after branch
and worktree normalization. All five stash merge commits, their index
parents, and their untracked parents are preserved in the verified
incremental bundle at
`C:\MaskFactory_TierA_Backups\historical_stashes_20260728T182808Z`.
The bundle SHA-256 is
`f4fb70e328a171d7e9896130decac4fd7701b0238712d8a30b5f7232dfbc6398`.

The exhaustive matrix covers 4,008 candidate path rows:

- 1,976 are already exact in current main;
- 18 are adopted exactly from the verified stash;
- nine stash rows map to six bounded semantic ports on current main;
- one duplicate fixed-script path is adopted to its canonical tool name;
- 379 are exact historical bytes already contained in main history and
  superseded by later main;
- three form an incomplete certifiable-subset prototype and remain preserved
  but unadopted;
- seven are superseded by current RunPod/shared-lease or protected
  Consumer/real-Main authority;
- twelve are stale control snapshots archived without replay;
- 1,561 are historical evidence/runtime payloads;
- 27 are generated pre-commit cache entries; and
- 15 are other historical non-source payloads.

The semantic-disposition matrix SHA-256 is
`4fcd20a9f49600f7fdf3dd8528e48f427ba5857b14cf26091ecb1202138d7b65`
with zero unresolved rows. The useful recovery cohorts restore Docker serve
contract/schema/tool coverage, measured-champion and production-audit glue,
Nuclio SAM2 bounded repair helpers, robust Windows PID/VHD repair behavior,
read-only gold-volume inputs, and matching tests/CLI wiring. Focused tests,
Ruff, YAML/PowerShell parsing, CLI help, and the fail-closed Docker contract
tool pass. Tracker row `MF-P6-20.01` was reopened during this work and may be
closed again only after complete-suite, export, clean-status, push-parity,
and terminal-receipt gates pass.

Those gates passed for executable source commit
`bc4c36ff98ebc4cc9b706ba58a10ef559d0497ee`. The fresh full collection
produced 5,098 passes, 41 governed skips, zero failures, and six warnings from
5,139 nodes. Its clean archive SHA-256 is
`4d6aa42fb0a2d8c921822c20657995d530c50fa7a4a806cf9b71591931f9ec7f`;
the 2,500,515-byte wheel SHA-256 is
`644f0aa34a466a11ff607d201d9d4344b994544dbf2b5588f5d82c9e7941c026`,
and isolated no-dependency install/import passed. The hook cache was removed
again after its governed one-time recreation, leaving zero residue. The
hook's repository-local `PRE_COMMIT_HOME` override was removed and the
original hook was preserved in Tier-A, preventing recurrence without
weakening any hook. Full Git
integrity passed before removal of exactly 13 reported temporary object files
(93,260,117 bytes); Git now reports zero garbage.

## Physical canonical root

`C:\Comfy_UI_Main_Masking` is now the sole registered MaskFactory worktree and
is checked out on clean `main`. The former dirty branch was made clean only
after all 11 tracked file bytes rehashed to the independent Tier-A supplement;
it remains remotely reconstructable at
`codex/recovery-maskfactory-20260728-61b4ffe`.

No `git clean`, hard reset, bulk Git garbage collection, directory
replacement, or bulk `C:\w` deletion was used. The exact transition is
recorded in
`.codex-ops/PHYSICAL_CANONICAL_ROOT_CONVERGENCE_20260728T172153Z.json`.
