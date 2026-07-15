# ITEMS — Master Index (Full End-to-End Completion Checklist)

**What this is:** the complete governed blueprint (`Plan\00–22` plus the approved SAM 3.1 handoff) decomposed into every atomic
work item required to take the Ultimate Masking System from an empty machine to full completion
(all D1–D11 + the 20-image headline test). If every box below is checked with its verify clause
satisfied, the project is DONE — there is nothing else.

Later governed specs 18–22 and the SAM 3.1 handoff are imported into the same live tracker. The
source-to-item map is `TRACEABILITY_18_22_SAM31.md`; doc 18's original 70-entry checklist remains
an evidence source, not a separate status system.

**Total items: 609** across 19 checklist files (including 9 phase exit gates + the project exit gate).

## File Map

| File | Phase | Items | Closes |
|------|-------|-------|--------|
| 01_ITEMS_P0_ENVIRONMENT.md | P0 Environment & Foundation (days 1–3) | 68 | D9 groundwork |
| 02_ITEMS_P1_GOLD_FACTORY_MVP.md | P1 Gold Factory MVP (wk 1–2) | 61 | D2 core, first gold |
| 03_ITEMS_P2_BODY_AWARE_DRAFTING.md | P2 Body-Aware Drafting (wk 2–4) | 58 | D1, G2 baseline |
| 04_ITEMS_P3_SPECIALIST_LANES.md | P3 Specialist Lanes (wk 4–6) | 45 | 100 certified packages, labor metrics |
| 05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md | P4 VLM QA + Active Learning (wk 5–7) | 40 | D4 |
| 06_ITEMS_P5_TRAINING.md | P5 Custom Model Training (wk 6–10, ≥200 certified) | 38 | D6, D7 |
| 07_ITEMS_P6_COMFYUI_SERVING.md | P6 ComfyUI & Serving (after D6) | 20 | D8 |
| 08_ITEMS_P7_SCALE_OPERATIONS.md | P7 Scale & Continuous | 17 | D5, D10, headline test |
| 09_ITEMS_P0_EXTERNAL_BOOTSTRAP.md | P0 External Foundation Bootstrap | 22 | Existing-model/dataset foundation for D1/D5/D6/D8 |
| 10_ITEMS_P8_MULTI_PERSON_MASKING.md | P8 Multi-Person / Multi-Character Masking (after P7) | 45 | D11, G9 |
| 11_ITEMS_P0_MODERNIZATION_FOUNDATION.md | P0 v2/registry/provider foundation | 31 | reproducibility, registry governance, challenger installation |
| 12_ITEMS_P1_ONTOLOGY_V2_AND_TRUTH.md | P1 ontology-v2 and truth authority | 36 | v2 generator/migration/CVAT, four truth tiers |
| 13_ITEMS_P2_PROVIDER_MODERNIZATION.md | P2 provider-neutral modernization | 23 | v2 drafting, SAM 3.1/provider benchmark matrix |
| 14_ITEMS_P3_MODERN_SPECIALISTS.md | P3 modern specialists | 10 | measured pose/geometry/silhouette/specialist challengers |
| 15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md | P4 teachers/autonomy | 34 | v2 QA, cloud incremental value, certification/audit/revocation |
| 16_ITEMS_P5_CERTIFIED_TRAINING.md | P5 certified training | 22 | v2 training, tier weights, hard-bucket-safe promotion |
| 17_ITEMS_P6_MODERN_SERVING.md | P6 modern serving | 15 | v2 ComfyUI/API, provider-neutral serving, safe CVAT publication |
| 18_ITEMS_P7_CURRENCY_OPERATIONS.md | P7 currency/autonomous operations | 16 | v2 activation, recurring reviews, revised headline evidence |
| 19_ITEMS_P8_AUTONOMOUS_MULTI_PERSON.md | P8 autonomous multi-person | 8 | certificate-covered instances, residual/audit routing |

## ID Scheme & Traceability

`MF-P<phase>-<task>.<item>` — items nest under the doc 14 WBS tasks; every cluster header cites
the governing spec doc/section. Build to the cited spec, never from memory. One addendum task
exists beyond doc 14's tables: **MF-P1-09 (ops bootstrap)** — backups/integrity automation pulled
forward from doc 15 so it starts the moment gold exists. Post-v1 addenda use the next free
phase-native task numbers. Every later-spec requirement maps through
`TRACEABILITY_18_22_SAM31.md`; never create a second shadow tracker.

## Rules of Use

1. **Check `[x]` only when the item's verify clause actually passes** (test green, command output
   recorded, gate met). A checked box is a claim of evidence, not intent.
2. **Order:** work files top-to-bottom; phases follow the doc 14 §9 critical path
   P0→P1→P2→P3→P5→P6→P8 with P4 parallel to late P3. Within a phase, task clusters are ordered by
   dependency.
3. **Hard blockers (cannot be deferred, cannot be overridden):** MF-P0-07 doctor green ·
   MF-P1-03 ontology CI assert · MF-P1-07 format-QC BLOCK enforcement · MF-P4-05 VLM calibration
   gate · MF-P5-02.02 flip/swap_partner CI test · MF-P5-05.04 D7 gate · MF-P5-07.02 D6 gate ·
   MF-P8-05.01/.02 (QC-035/036 instance exclusivity/bleed) · MF-P8-07 split-integrity CI test ·
   registry/governance blockers in MF-P0-16 · v2 CI/activation blockers in MF-P1-10, MF-P1-11,
   MF-P4-09, MF-P5-09, MF-P7-06 · certification/revocation blockers in MF-P4-11 · truth/promotion
   blockers in MF-P1-13 and MF-P5-10 · recurring currency blockers in MF-P7-07 · autonomous
   multi-person blockers in MF-P8-11.
4. **Phase exits:** each file ends with `MF-P<n>-EXIT`; do not start the next phase's model-facing
   work before the exit is checked (annotation cadence may continue across boundaries).
5. **Entry gates:** P5 requires ≥200 certified training packages
   (`human_anchor_train_count + autonomous_certified_gold_count`); P6 requires D6 plus eligible
   promoted providers; P8 requires P7 substantially
   complete (D1–D10 satisfied) — see doc 17 §13.
6. **Conditional items** (MF-P5-08.01/.02, MF-P7-01.04, MF-P7-03.05) check as `[x] n/a — trigger
   not met` if their trigger never fires; that still counts as complete.
7. **Tracking:** these files define item metadata and their checkboxes remain stable. Live status,
   evidence, notes, and blockers are updated only through `Plan\Tracker\tracker.py`; regenerate
   `DASHBOARD.md`/phase views with `report` and log dated operational evidence in `Plan\OPS_LOG.md`.
8. **Deviations:** any deliberate departure from an item goes to `Plan\DECISIONS_LOG.md` with a
   reason — items are edited via git commit, never silently skipped.

## Definition of Project-Done

All 609 tracker items resolved with evidence ⇒ D1–D11 hold ⇒ run the revised autonomous single-person
headline test (`MF-P7-07.07` plus `MF-P7-EXIT`): 20 unseen images, certificate-covered selective
autonomy, a preselected blinded mixed audit, no routine per-image correction, separate labor/quality/
confidence reporting, zero format and left/right failures. Then run the autonomous multi-person
demonstration (`MF-P8-11.07` plus `MF-P8-EXIT`): 10–20 real 2–4-person images, certificate-covered
instances plus residual/audit routing, reciprocal contact/occlusion, and zero cross-instance bleed.
Both evidence bundles, current currency/rollback reviews, and every hard blocker are the finish line.
