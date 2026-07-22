# ITEMS — Master Index (Full End-to-End Completion Checklist)

**What this is:** the complete governed blueprint (`Plan\00–25`, the approved SAM 3.1 handoff, and `Plan\Daz\00–32`) decomposed into every atomic
work item required to take the Ultimate Masking System from an empty machine to full completion
under three claim-scoped profiles. `core_autonomous_runtime` is the required human-free product
finish line; `independent_real_accuracy` and `scale_daz_maturity` are optional/non-blocking profiles.

Later governed specs 18–22 and the SAM 3.1 handoff are imported into the same live tracker. The
source-to-item map is `TRACEABILITY_18_22_SAM31.md`; doc 18's original 70-entry checklist remains
an evidence source, not a separate status system.

**Total items: 833** across 21 checklist files (including profile-scoped phase exits and the required
doc-24 core exit). No legacy phase exit is global completion authority.

## File Map

| File | Phase | Items | Closes |
|------|-------|-------|--------|
| 01_ITEMS_P0_ENVIRONMENT.md | P0 Environment & Foundation (days 1–3) | 68 | D9 groundwork |
| 02_ITEMS_P1_GOLD_FACTORY_MVP.md | P1 Gold Factory MVP (wk 1–2) | 61 | optional D2 accuracy/portfolio evidence, first gold |
| 03_ITEMS_P2_BODY_AWARE_DRAFTING.md | P2 Body-Aware Drafting (wk 2–4) | 58 | D1, G2 baseline |
| 04_ITEMS_P3_SPECIALIST_LANES.md | P3 Specialist Lanes (wk 4–6) | 45 | 100 certified packages, labor metrics |
| 05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md | P4 VLM QA + Active Learning (wk 5–7) | 40 | D4 |
| 06_ITEMS_P5_TRAINING.md | P5 Custom Model Training (wk 6–10, ≥200 certified) | 38 | D6, D7 |
| 07_ITEMS_P6_COMFYUI_SERVING.md | P6 legacy trained-champion serving plus independent doc-24 core bridge lane | 20 | optional D8 plus required core bridge |
| 08_ITEMS_P7_SCALE_OPERATIONS.md | P7 Optional Scale & Continuous | 17 | optional D5, D10, headline test |
| 09_ITEMS_P0_EXTERNAL_BOOTSTRAP.md | P0 External Foundation Bootstrap | 24 | Existing-model/dataset foundation for D1/D5/D6/D8 |
| 10_ITEMS_P8_MULTI_PERSON_MASKING.md | P8 Multi-Person / Multi-Character Masking (after P7) | 45 | D11, G9 |
| 11_ITEMS_P0_MODERNIZATION_FOUNDATION.md | P0 v2/registry/provider foundation | 41 | reproducibility, registry governance, challenger installation, RunPod durability, AWS inventory/migration |
| 12_ITEMS_P1_ONTOLOGY_V2_AND_TRUTH.md | P1 ontology-v2 and truth authority | 36 | v2 generator/migration/CVAT, four truth tiers |
| 13_ITEMS_P2_PROVIDER_MODERNIZATION.md | P2 provider-neutral modernization | 30 | v2 drafting, proposal diversity, disagreement maps, bounded repair, SAM 3.1/provider benchmark matrix |
| 14_ITEMS_P3_MODERN_SPECIALISTS.md | P3 modern specialists | 10 | measured pose/geometry/silhouette/specialist challengers |
| 15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md | P4 teachers/autonomy | 45 | v2 QA, evidence-qualified visual critics, cloud incremental value, certification/audit/revocation |
| 16_ITEMS_P5_CERTIFIED_TRAINING.md | P5 certified training | 22 | v2 training, tier weights, hard-bucket-safe promotion |
| 17_ITEMS_P6_MODERN_SERVING.md | P6 modern serving | 15 | v2 ComfyUI/API, provider-neutral serving, safe CVAT publication |
| 18_ITEMS_P7_CURRENCY_OPERATIONS.md | P7 currency/autonomous operations | 20 | v2 activation, critic currency, RunPod asset durability, recurring reviews, revised headline evidence |
| 19_ITEMS_P8_AUTONOMOUS_MULTI_PERSON.md | P8 autonomous multi-person | 8 | certificate-covered instances, residual/audit routing |
| 20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md | P9 external supervision, reference intelligence, DAZ autonomy | 147 | qualified train-only labels, 83k reference lanes, exact synthetic truth, minimal binary review |
| 21_ITEMS_P6_AUTONOMOUS_CORE_AND_CROSS_PROJECT_BRIDGE.md | P6 autonomous core and cross-project ComfyUI bridge | 43 | required human-free runtime completion, exact-output authority, release/adoption bridge, recovery |

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
3. **Hard blockers are absolute within their assigned completion profile.** Only blockers in the
   `core_autonomous_runtime` dependency closure block required completion; optional accuracy/training/
   DAZ blockers cannot be imported into core. The portfolio blocker inventory includes: MF-P0-07 doctor green ·
   MF-P1-03 ontology CI assert · MF-P1-07 format-QC BLOCK enforcement · MF-P4-05 VLM calibration
   gate · MF-P5-02.02 flip/swap_partner CI test · MF-P5-05.04 D7 gate · MF-P5-07.02 D6 gate ·
   MF-P8-05.01/.02 (QC-035/036 instance exclusivity/bleed) · MF-P8-07 split-integrity CI test ·
   registry/governance blockers in MF-P0-16 · v2 CI/activation blockers in MF-P1-10, MF-P1-11,
   MF-P4-09, MF-P5-09, MF-P7-06 · certification/revocation blockers in MF-P4-11 · truth/promotion
   blockers in MF-P1-13 and MF-P5-10 · recurring currency blockers in MF-P7-07 · autonomous
   multi-person blockers in MF-P8-11 · autonomous core/bridge blockers in MF-P6-07 through MF-P6-12.
4. **Phase exits:** each file ends with `MF-P<n>-EXIT`; do not start the next phase's model-facing
   work before the exit is checked (annotation cadence may continue across boundaries).
5. **Entry gates:** P5 requires ≥200 certified training packages
   (`human_anchor_train_count + autonomous_certified_gold_count`) for the training/scale profile.
   Legacy P6 trained-champion serving retains D6/provider gates, but `MF-P6-07` through `MF-P6-12`
   core autonomy/bridge work has no D6, human, corpus-volume, full-library, DAZ, or soak prerequisite.
   P8's legacy maturity path requires P7 substantially
   complete (D1–D10 satisfied) — see doc 17 §13.
6. **Conditional items** (MF-P5-08.01/.02, MF-P7-01.04, MF-P7-03.05) check as `[x] n/a — trigger
   not met` if their trigger never fires; that still counts as complete.
7. **Tracking:** these files define item metadata and their checkboxes remain stable. Live status,
   evidence, notes, and blockers are updated only through `Plan\Tracker\tracker.py`; regenerate
   `DASHBOARD.md`/phase views with `report` and log dated operational evidence in `Plan\OPS_LOG.md`.
8. **Deviations:** any deliberate departure from an item goes to `Plan\DECISIONS_LOG.md` with a
   reason — items are edited via git commit, never silently skipped.

## Definition of Project-Done

The requested product is DONE when the tracker computes `core_autonomous_runtime = complete` from the
doc-24 gates and the pinned MaskFactory/main-project adoption bundle. That profile requires autonomous
generation, hard QA, critic diversity, bounded repair, abstention, operational certification,
revocation, Mode A/Mode B authority, single-/multi-person integration, restart, and rollback evidence.

The legacy D1–D11 rollups, 20-image blinded headline test, human-anchor/CVAT work, 200/300/500 package
targets, full model-library qualification, DAZ work, and seven-day soak remain tracked in
`independent_real_accuracy` or `scale_daz_maturity`. They support additional claims and must not be
presented as blockers to the required core profile. The authoritative mapping is
`Plan\Tracker\completion_track_registry.json`.
