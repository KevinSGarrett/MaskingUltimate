# 01 — Project Map

Everything about MaskFactory lives under `C:\Comfy_UI_Main_Masking\`. This
document is the complete map: four planning layers, plus the actual system
you will build starting in Phase P0.

---

## 1. The Four Planning Layers

| Layer | Location | What it is | Who edits it, and when |
|---|---|---|---|
| **Spec** | `Plan\00`–`22`, plus approved handoffs | The complete technical blueprint, including ontology-v2, multi-provider teachers, autonomous certification/repair, technology currency, and SAM 3.1 modernization. | Changes only through deliberate spec/owner amendments. Later approved decisions outrank conflicting earlier text and must be recorded in traceability. |
| **Checklist** | `Plan\Items\` (19 parsed phase files, 609 action items) | The spec atomized into checkable build items, each tagged with its phase, governing source, explicit verification, and blockers. | Edit only when the plan itself changes. After editing, run `python tracker.py rebuild` in `Tracker\`. |
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

## 2. The Specification Set (`Plan\00`–`22` plus approved handoffs)

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
| 17 | `17_MULTI_PERSON_MULTI_CHARACTER_MASKING_SPEC.md` | Multi-person identity, instance isolation, QA, and serving |
| 18 | `18_ADULT_ANATOMY_ONTOLOGY_V2_SPEC.md` | Ontology-v2 contract, migration, QA, training, serving, and operations |
| 19 | `19_MULTI_PROVIDER_TEACHER_AND_CONTINUOUS_IMPROVEMENT_SPEC.md` | Provider-neutral cloud teachers, eligibility, adjudication, and learning |
| 20 | `20_PROGRESSIVE_AUTONOMOUS_MASK_FACTORY_SPEC.md` | Truth tiers, autonomous certification, audits, revocation, and promotion |
| 21 | `21_AUTONOMOUS_REPAIR_EXECUTION_SPEC.md` | Guarded repair execution, rollback, and repair evidence |
| 22 | `22_TECHNOLOGY_CURRENCY_AND_MODEL_CHALLENGE_SPEC.md` | Challenger lifecycle, governance, benchmarking, and recurring currency review |

The approved SAM 3.1/autonomous-gold handoff is also authoritative. Its full
requirement mapping is maintained in `Plan\Items\TRACEABILITY_18_22_SAM31.md`.

Plus `Plan\CHANGELOG_ONTOLOGY.md` (ontology version history) and, once you
create them per §5 below, `Plan\OPS_LOG.md` and `Plan\DECISIONS_LOG.md`.

## 3. The Checklist (`Plan\Items\`)

The parsed checklist contains **609 atomic items across 19 phase files**.
`Plan\Items\00_ITEMS_MASTER_INDEX.md` is the authoritative file/count map,
and `Plan\Items\TRACEABILITY_18_22_SAM31.md` maps every requirement in docs
18–22 and the SAM 3.1 handoff to an existing or newly added item. Each item
has an id (`MF-P<phase>-<task>.<item>`), a governing source, an explicit
verification clause, and explicit blockers.

## 4. The Tracker (`Plan\Tracker\`)

| File/dir | What |
|---|---|
| `tracker.py` | The CLI. `rebuild`, `show`, `set`, `list`, `next`, `metrics`, `goal`, `validate`, `report`. |
| `tracker.json` | Canonical live state of all 609 items + DoD + Goals + metrics. |
| `CHANGELOG.jsonl` | Append-only audit trail of every state change ever made. |
| `backups\` | Auto-snapshots of `tracker.json` before every write. |
| `DASHBOARD.md` | Auto-generated project-wide rollup. Regenerate with `report`. |
| `phases\P0.md`…`P8.md` | Auto-generated full-detail live status per phase. |
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
