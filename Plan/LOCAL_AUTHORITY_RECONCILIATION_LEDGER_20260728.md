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

`MF-P6-20.01` is the non-duplicative governing row. Its metadata now explicitly
requires scattered-directory, Plan/Item/Instruction/tracker, physical-root,
and rollback convergence. `tracker.py rebuild` preserved 906 items with zero
new or orphaned rows. `tracker.py set` records this phase as in progress at
60%, without completion credit. `tracker.py report` and `tracker.py validate`
pass with 906 non-orphaned items, 54 unresolved hard blockers, and zero
structural problems.

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

The final shared-directory counts and receipts are appended only after Main
returns its exact post-disposition authority.

