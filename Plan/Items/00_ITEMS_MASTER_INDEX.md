# ITEMS — Master Index (Full End-to-End Completion Checklist)

**What this is:** the complete blueprint pack (`Plan\00–17`) decomposed into every single atomic
work item required to take the Ultimate Masking System from an empty machine to full completion
(all D1–D11 + the 20-image headline test). If every box below is checked with its verify clause
satisfied, the project is DONE — there is nothing else.

**Total items: 393** across 10 checklist files (including 9 phase exit gates + the project exit gate).

## File Map

| File | Phase | Items | Closes |
|------|-------|-------|--------|
| 01_ITEMS_P0_ENVIRONMENT.md | P0 Environment & Foundation (days 1–3) | 68 | D9 groundwork |
| 02_ITEMS_P1_GOLD_FACTORY_MVP.md | P1 Gold Factory MVP (wk 1–2) | 61 | D2 core, first gold |
| 03_ITEMS_P2_BODY_AWARE_DRAFTING.md | P2 Body-Aware Drafting (wk 2–4) | 49 | D1, G2 baseline |
| 04_ITEMS_P3_SPECIALIST_LANES.md | P3 Specialist Lanes (wk 4–6) | 45 | 100 gold, G1 ≤25 min |
| 05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md | P4 VLM QA + Active Learning (wk 5–7) | 28 | D4 |
| 06_ITEMS_P5_TRAINING.md | P5 Custom Model Training (wk 6–10, ≥200 gold) | 38 | D6, D7 |
| 07_ITEMS_P6_COMFYUI_SERVING.md | P6 ComfyUI & Serving (after D6) | 20 | D8 |
| 08_ITEMS_P7_SCALE_OPERATIONS.md | P7 Scale & Continuous | 17 | D5, D10, headline test |
| 09_ITEMS_P0_EXTERNAL_BOOTSTRAP.md | P0 External Foundation Bootstrap | 22 | Existing-model/dataset foundation for D1/D5/D6/D8 |
| 10_ITEMS_P8_MULTI_PERSON_MASKING.md | P8 Multi-Person / Multi-Character Masking (after P7) | 45 | D11, G9 |

## ID Scheme & Traceability

`MF-P<phase>-<task>.<item>` — items nest under the doc 14 WBS tasks; every cluster header cites
the governing spec doc/section. Build to the cited spec, never from memory. One addendum task
exists beyond doc 14's tables: **MF-P1-09 (ops bootstrap)** — backups/integrity automation pulled
forward from doc 15 so it starts the moment gold exists.

## Rules of Use

1. **Check `[x]` only when the item's verify clause actually passes** (test green, command output
   recorded, gate met). A checked box is a claim of evidence, not intent.
2. **Order:** work files top-to-bottom; phases follow the doc 14 §9 critical path
   P0→P1→P2→P3→P5→P6→P8 with P4 parallel to late P3. Within a phase, task clusters are ordered by
   dependency.
3. **Hard blockers (cannot be deferred, cannot be overridden):** MF-P0-07 doctor green ·
   MF-P1-03 ontology CI assert · MF-P1-07 format-QC BLOCK enforcement · MF-P4-05 VLM calibration
   gate · MF-P5-02.02 flip/swap_partner CI test · MF-P5-05.04 D7 gate · MF-P5-07.02 D6 gate ·
   MF-P8-05.01/.02 (QC-035/036 instance exclusivity/bleed) · MF-P8-07 split-integrity CI test.
4. **Phase exits:** each file ends with `MF-P<n>-EXIT`; do not start the next phase's model-facing
   work before the exit is checked (annotation cadence may continue across boundaries).
5. **Entry gates:** P5 requires ≥ 200 approved gold; P6 requires D6; P8 requires P7 substantially
   complete (D1–D10 satisfied) — see doc 17 §13.
6. **Conditional items** (MF-P5-08.01/.02, MF-P7-01.04, MF-P7-03.05) check as `[x] n/a — trigger
   not met` if their trigger never fires; that still counts as complete.
7. **Tracking:** these files are the live tracker — commit checkbox changes to git; mirror
   phase-level state in doc 14's checkboxes; log dated evidence in `Plan\OPS_LOG.md`.
8. **Deviations:** any deliberate departure from an item goes to `Plan\DECISIONS_LOG.md` with a
   reason — items are edited via git commit, never silently skipped.

## Definition of Project-Done

All 393 boxes checked ⇒ D1–D11 (doc 00 §4) all hold ⇒ run the single-person headline test
(MF-P7-EXIT): 20 never-seen images → full pipeline → human-approved gold packages in ≤ 4 hours
of operator time, zero format failures, zero left/right failures — **then** the multi-person
demonstration (MF-P8-EXIT, doc 17 §14): 10–20 real 2–4-person images → correctly-instanced gold
for every promoted person, zero cross-instance bleed. Both checkboxes together are the finish
line for the Ultimate (multi-character) Masking System.
