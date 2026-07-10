# 01 — Project Map

Everything about MaskFactory lives under `C:\Comfy_UI_Main_Masking\`. This
document is the complete map: four planning layers, plus the actual system
you will build starting in Phase P0.

---

## 1. The Four Planning Layers

| Layer | Location | What it is | Who edits it, and when |
|---|---|---|---|
| **Spec** | `Plan\00`–`16` (17 files) | The complete, authoritative technical blueprint. Every model, threshold, format, and algorithm decision, made in advance. | Essentially frozen. Only changes via the deliberate ontology/spec change procedures described inside (e.g. doc 02 §9). If you think a spec doc is wrong, that's a `06`-style escalation, not a silent edit. |
| **Checklist** | `Plan\Items\00`–`08` (9 files, 348 action items) | The spec atomized into checkable build items, each tagged with its phase and the exact spec section that defines it. | Edit only if the plan itself changes (rare, deliberate). After editing, run `python tracker.py rebuild` in `Tracker\`. |
| **State** | `Plan\Tracker\` | The live, mutable status of every item: open/blocked/complete/etc., evidence, notes, timestamps — plus Definition-of-Done and Goals rollups. | You update this constantly, through `tracker.py` only. Never hand-edit `tracker.json`. |
| **Operating Manual** | `Plan\Instructions\` (this folder) | How you, the building AI, actually conduct yourself session to session. | Static reference for you. Not something you update as part of normal building work. |

A fifth layer — **the actual system** — doesn't exist yet. It's what you
create by executing the checklist. Once Phase P0 starts, you'll be building
out `C:\Comfy_UI_Main_Masking\{src, configs, models, data, datasets, cvat,
qa, runs, logs, tools, env}\` exactly per `Plan\05_SYSTEM_ARCHITECTURE.md`
§3. That tree, once it exists, is also authoritative for its own state
(manifests, `qa_report.json`, the pipeline's own SQLite DB per doc 04 §6) —
but none of that replaces the project-level Tracker described here, which
tracks *build progress*, not *per-image pipeline state*. Don't confuse the
two: `Plan\Tracker\` tracks "has the hand lane been implemented"; the
eventual `data\maskfactory.sqlite` tracks "has image img_a3f9... reached
gold." Both matter; they answer different questions.

---

## 2. The 17 Spec Documents (`Plan\00`–`16`)

| # | File | Contents |
|---|------|----------|
| 00 | `00_MASTER_INDEX.md` | Doc map, global conventions, Definition of Done (D1–D10) |
| 01 | `01_PROJECT_CHARTER_AND_SCOPE.md` | Mission, goals (G1–G8), scope, principles, data governance |
| 02 | `02_MASK_ONTOLOGY_SPEC.md` | Every label, ID, mask-type taxonomy, L/R rules, visibility states, z-order |
| 03 | `03_GOLD_MASK_FORMAT_SPEC.md` | Binary PNG spec, package layout, naming, gold-vs-inpaint separation |
| 04 | `04_DATA_SCHEMAS_AND_MANIFESTS.md` | Full JSON schemas: manifest, qa_report, model registry, failure queue, coverage matrix, state DB |
| 05 | `05_SYSTEM_ARCHITECTURE.md` | Component architecture, module boundaries, consensus engine, VRAM schedule |
| 06 | `06_ENVIRONMENT_AND_INSTALLATION.md` | Hardware plan, exact env builds, every model checkpoint, CVAT deployment |
| 07 | `07_PIPELINE_STAGE_SPECS.md` | Stages S00–S15: I/O contracts, algorithms, runtime budgets |
| 08 | `08_SPECIALIST_LANES_SPEC.md` | Hand/finger, chest/breast/clothing, hair/face, feet/toes, 3D-prior lanes |
| 09 | `09_AUTO_QA_VALIDATION_SPEC.md` | All 34 automatic checks (QC-001…034), metrics, topology rules |
| 10 | `10_LLM_VLM_QA_LAYER.md` | Local VLM setup, prompts, verdict schema, routing, cloud-LLM boundary |
| 11 | `11_HUMAN_REVIEW_WORKFLOW.md` | CVAT project config, Kevin's SOPs, statuses, second review |
| 12 | `12_DATASET_TRAINING_ACTIVE_LEARNING.md` | Splits, DVC, fine-tune specs for all 5 models, leaderboard |
| 13 | `13_COMFYUI_INTEGRATION.md` | Custom node pack, inpaint derivation, inference service |
| 14 | `14_IMPLEMENTATION_ROADMAP_WBS.md` | Phases P0–P7, every task ID, deliverable, acceptance criteria |
| 15 | `15_RISKS_OPERATIONS_RUNBOOK.md` | Risk register, daily ops, **troubleshooting table**, backup/restore, glossary |
| 16 | `16_EXTERNAL_FOUNDATION_BOOTSTRAP.md` | Existing model, workflow, and dataset bootstrap sources |

Plus `Plan\CHANGELOG_ONTOLOGY.md` (ontology version history) and, once you
create them per §5 below, `Plan\OPS_LOG.md` and `Plan\DECISIONS_LOG.md`.

## 3. The Checklist (`Plan\Items\00`–`08`)

| File | Phase | Items | Closes |
|---|---|---|---|
| `00_ITEMS_MASTER_INDEX.md` | — | (index, no checkboxes) | — |
| `01_ITEMS_P0_ENVIRONMENT.md` | P0 | 68 | D9 groundwork |
| `02_ITEMS_P1_GOLD_FACTORY_MVP.md` | P1 | 61 | D2 core, first gold |
| `03_ITEMS_P2_BODY_AWARE_DRAFTING.md` | P2 | 49 | D1, G2 baseline |
| `04_ITEMS_P3_SPECIALIST_LANES.md` | P3 | 45 | 100 gold, G1 ≤25 min |
| `05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md` | P4 | 28 | D4 |
| `06_ITEMS_P5_TRAINING.md` | P5 | 38 | D6, D7 |
| `07_ITEMS_P6_COMFYUI_SERVING.md` | P6 | 20 | D8 |
| `08_ITEMS_P7_SCALE_OPERATIONS.md` | P7 | 17 | D5, D10, headline test |
| `09_ITEMS_P0_EXTERNAL_BOOTSTRAP.md` | P0 | 22 | Existing-model/dataset foundation |

348 total action items. Each line carries an id (`MF-P<phase>-<task>.<item>`),
a description, and (via its cluster header) a `spec_ref` pointing at the
exact spec section that defines it.

## 4. The Tracker (`Plan\Tracker\`)

| File/dir | What |
|---|---|
| `tracker.py` | The CLI. `rebuild`, `show`, `set`, `list`, `next`, `metrics`, `goal`, `validate`, `report`. |
| `tracker.json` | Canonical live state of all 348 items + DoD + Goals + metrics. |
| `CHANGELOG.jsonl` | Append-only audit trail of every state change ever made. |
| `backups\` | Auto-snapshots of `tracker.json` before every write. |
| `DASHBOARD.md` | Auto-generated project-wide rollup. Regenerate with `report`. |
| `phases\P0.md`…`P7.md` | Auto-generated full-detail live status per phase. |
| `README.md` | The formal command reference (read this for full CLI detail). |
| `SCHEMA.md` | Field-by-field `tracker.json` reference. |

## 5. Two Log Files You Will Use (`Plan\` root)

`Plan\OPS_LOG.md` and `Plan\DECISIONS_LOG.md` are referenced throughout the
spec and checklist but are working documents you fill in as you go. Stub
templates with the exact format to follow already exist at
`Plan\OPS_LOG.md` and `Plan\DECISIONS_LOG.md` — use them as-is. See
`03_SESSION_PLAYBOOK.md` and `06_BLOCKERS_AMBIGUITY_AND_ESCALATION.md` for
when to write to each.

## 6. Quick Lookup — "Which Doc Answers This?"

| Question | Go to |
|---|---|
| Exact PNG format / package layout for a gold mask? | `Plan\03` |
| Which model do I use for X, and what checkpoint? | `Plan\06` §3 |
| What are the 34 QA checks and their thresholds? | `Plan\09` |
| How does the hand/finger lane handle merged fingers? | `Plan\08` §2 |
| What's the exact manifest.json schema? | `Plan\04` §1 |
| How do I set up the CVAT project? | `Plan\11` §2, `Plan\06` §4 |
| What are the fine-tune configs for the 5 models? | `Plan\12` §6 |
| How does ComfyUI load a gold mask? | `Plan\13` §2 |
| Something's broken (CVAT, GPU OOM, DVC push failing)? | `Plan\15` §7 (troubleshooting table) |
| What exactly is Definition of Done? | `Plan\00` §4, and `Tracker\DASHBOARD.md`'s live DoD table |
| Is this item a hard blocker? | `Tracker\README.md` §5, or `tracker.py list --hard-blockers` |
| What phase am I in, what's the entry gate? | `Tracker\DASHBOARD.md`, or `07_PHASE_QUICK_REFERENCE.md` here |
