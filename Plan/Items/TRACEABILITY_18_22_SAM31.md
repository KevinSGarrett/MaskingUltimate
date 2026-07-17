# Requirements Traceability — Docs 18–22 and SAM 3.1 Handoff

**Status:** authoritative tracker-import map
**Generated scope:** 798 total Items records = 609 prior records + 146 document-23/DAZ records +
43 document-24 autonomous-core/cross-project-bridge records
**Sources:** docs 18–23, `OntologyV2/IMPLEMENTATION_CHECKLIST.md`, `SIDE_THREAD_HANDOFF_SAM31_AUTONOMOUS_GOLD_20260713.md`, and `Plan/Daz/00–32`

This matrix prevents later specifications from living outside the live tracker. A range means every numbered step, bullet, table rule, and acceptance condition in the named source section is decomposed by the referenced atomic Items. Existing IDs are reused where they already carry the same verification contract; the delta files add only missing scope.

## Document 23 and DAZ incorporation

Document 23, Kevin's approved pasted amendment, and the complete `Plan\Daz\00–32` pack map to
`20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md`. DAZ WBS D0–D11 is imported one-for-one as
`MF-P9-01.*` through `MF-P9-12.*`; MaskedWarehouse qualification is `MF-P9-13.*`, the reference
corpus is `MF-P9-14.*`, and minimal-review near-perfect selective autonomy is `MF-P9-15.*`.
This remains one tracker; DAZ readiness checklists are evidence sources, not shadow status systems.

## Owner override applied during import

Kevin explicitly rejected adding an age-eligibility/unknown-age fail-closed tracker gate. That source requirement is superseded and is **not** active tracker authority. The import instead tracks permitted content lanes, provider/artifact-specific compatibility, rights/license decisions, and the removal/non-reintroduction of QC-V2-011 age eligibility through `MF-P2-10.02`, `MF-P4-09.01`, and `MF-P4-10.03`. This override does not prohibit adult/NSFW training data.

## Doc 18 executable checklist — exact one-to-one import (70 entries)

The checklist order within each lettered section maps sequentially to the listed IDs. This is an exact 70-entry import, not a section summary.

| Checklist section | Source entries | Tracker IDs | Count |
|---|---:|---|---:|
| A. Freeze and compatibility baseline | 1–5 | `MF-P0-15.01`–`.05` | 5 |
| B. Ontology generator and machine authority | 1–9 | `MF-P1-10.01`–`.09` | 9 |
| C. Visibility, manifest, and migration | 1–8 | `MF-P1-11.01`–`.08` | 8 |
| D. CVAT and human review | 1–10 | `MF-P1-12.01`–`.10` | 10 |
| E. Drafting and fusion | 1–8 | `MF-P2-10.01`–`.08` | 8 |
| F. QA and calibration | 1–7 | `MF-P4-09.01`–`.07` | 7 |
| G. Dataset and training | 1–10 | `MF-P5-09.01`–`.10` | 10 |
| H. Registry, serving, and ComfyUI | 1–7 | `MF-P6-05.01`–`.07` | 7 |
| I. Operations and activation | 1–6 | `MF-P7-06.01`–`.06` | 6 |
| **Total** |  |  | **70** |

Completed/open state is migrated from the checklist only when its evidence satisfies the new `Verify:` clause. The prior 60 checked entries are not assumed complete merely from code presence; their tracker evidence cites the original evidence artifact plus current tests. The 10 prior open entries remain unresolved or blocked.

## Doc 19 — Multi-provider teacher and continuous improvement

| Source requirement | Tracker coverage |
|---|---|
| §1 governed hybrid, correction-time objective, no self-training from unverified output | `MF-P4-10.01`, `.07`, `.10`–`.12`; `MF-P1-13.05`–`.06` |
| §2 component roles, pixel authority, human-anchor authority | `MF-P4-10.01`; `MF-P2-11.01`; `MF-P1-13.01`–`.06` |
| §3 steps 1–3 evidence bundle, deterministic veto, selective escalation | `MF-P4-10.02`, `.07` |
| §3 steps 4–7 eligibility, reservation, cascade, strict parse | `MF-P4-10.03`–`.06` |
| §3 steps 8–10 isolated candidates, guards, blinded selection, reversible draft, outcome record | `MF-P4-10.06`–`.07`; `MF-P4-08.01`–`.07`; `MF-P6-06.05`–`.06` |
| §4 all budget/cap/retry/bundle/ledger/batch constraints | `MF-P4-10.04`–`.05` |
| §5 privacy, credentials, logging, provider-specific compatibility/retention review | `MF-P4-10.03`, `MF-P0-16.07`–`.10`, subject to owner override above |
| §6 frozen ≥200-case corpus and all simultaneous incremental-value thresholds | `MF-P4-10.08`–`.09` |
| §6 shadow-only outcome/no authority escalation | `MF-P4-10.07`, `.09` |
| §7 hash-bound human-anchor records and image-level immutable splits | `MF-P4-10.10`; `MF-P1-13.02`–`.03` |
| §7 ≥50 exemplar and ≥500 LoRA readiness gates; forbidden targets | `MF-P4-10.11` |
| §7 five-part challenger evaluation, promotion, rollback | `MF-P4-10.12`; `MF-P5-10.08`–`.12` |
| §8 implemented control surfaces/status/evaluation/harvest/distillation/golden reference | `MF-P4-10.02`–`.12`; existing `MF-P4-07.01`–`.04`; registry evidence in this matrix |

## Doc 20 — Progressive autonomous mask factory

| Source requirement | Tracker coverage |
|---|---|
| §1 separate machine/human truth tiers and per-context earned autonomy | `MF-P1-13.01`–`.06`; `MF-P4-11.01`, `.08`–`.11` |
| §2 candidate sources, immutable evidence, hard vetoes, scoring, score/margin, disagreement | `MF-P4-11.02`–`.05` |
| §3 bounded corrections, isolated candidates, rerun vetoes/comparison, caps | existing `MF-P4-08.01`–`.05`; `MF-P4-11.06` |
| §4 certificate sample authority, confidence bounds, fingerprints, hashes, leakage, expiry/revocation | `MF-P4-11.08`–`.13`; `MF-P1-13.04` |
| §4.1 safe pre-review improvements, per-label rollback, non-gold authority | `MF-P4-11.06`; existing `MF-P4-08.03`–`.06`; `MF-P6-06.04`–`.06` |
| §5 lifecycle outcomes and permitted use | `MF-P1-13.01`–`.08` |
| §6 mixed random/risk audit, floors, immediate serious revocation, drift | `MF-P4-11.12`–`.13`; `MF-P7-07.04`–`.05` |
| §7 failure mining, reliability, retraining fingerprint, measured plan credit | `MF-P4-11.14`; `MF-P7-07.06` |
| §8 complete autonomy control surface, weekly operation, pseudo dataset | `MF-P4-11.02`–`.15`; `MF-P5-10.06`; `MF-P7-07.04` |

## Doc 21 — Autonomous repair execution

| Source requirement | Tracker coverage |
|---|---|
| §1 exact-candidate convergence and authority limits | existing `MF-P4-08.04`, `.07`–`.08`; `MF-P4-11.11` |
| §2 architecture from geometry/candidates through QA/tournament/all-provider review | existing `MF-P4-08.01`–`.05`; `MF-P4-10.02`–`.07` |
| §3 spatial ROI/coordinate/change-limit contract | existing `MF-P4-08.01`–`.02` |
| §4 isolated pixel tools/provenance/guards | existing `MF-P4-08.02`, `.05` |
| §5 atomic reassignment, protected authority, displacement, rollback | existing `MF-P4-08.03` |
| §6 12-candidate/three-round exact-vote controller and honest stop conditions | existing `MF-P4-08.04`–`.05`; `MF-P4-11.06` |
| §7 selection, failed-winner downgrade, nonregressing broken-baseline progress | existing `MF-P4-08.03`–`.05` |
| §8 CVAT non-gold publication, backup, refusal, verification, rollback | existing `MF-P4-08.06`; `MF-P6-06.05`–`.06` |
| §9 cost/privacy/availability | `MF-P4-10.03`–`.05`, subject to owner override above |
| §10 evidence, recalibration, focused/full/live acceptance | existing `MF-P4-08.07`–`.08`; `MF-P4-11.15` |

## Doc 22 — Registry governance, certification, and promotion control

| Source requirement | Tracker coverage |
|---|---|
| §1 operating profile/content lanes | `MF-P0-16.01`, `.07`–`.10` |
| §2 exact v2 registry, legacy isolation, unified validation, duplicate keys, atomic writes | `MF-P0-16.02`–`.05`, `.12` |
| §3 lifecycle meanings, no planned installed artifacts, transactional promotion/rollback | `MF-P0-16.06`, `.11`; `MF-P2-11.12`, `.15` |
| §4 license/content activation prerequisites and probe separation | `MF-P0-16.07`–`.10` |
| §5 truth tiers, partitions, separate counts, certified/effective formulas | `MF-P1-13.01`–`.06`; `MF-P5-10.01`–`.05` |
| §6 distinct throughput/quality/confidence, buckets, power/floors/bounds, selective prediction, mixed audits, revocation | `MF-P4-11.01`, `.08`–`.13`; `MF-P7-07.04`–`.05` |
| §7 frozen role benchmark, primary win, hard-bucket non-inferiority, regression families, hashes, rollback | `MF-P2-11.13`–`.15`; `MF-P3-08.08`–`.10`; `MF-P5-10.07`–`.12` |
| §8 90-day/pre-event currency review and challenger-only discovery | `MF-P7-07.01`–`.03` |
| §9 complete regression evidence list | `MF-P0-16.12`; `MF-P4-11.09`–`.13`; `MF-P5-10.09`–`.11`; tracker coverage tests |

## SAM 3.1 modernization/autonomous-gold handoff

| Handoff requirement | Tracker coverage |
|---|---|
| Operating profile and registry policy fields | `MF-P0-16.01`, `.07`–`.10` |
| Sapiens2 exclusion/original Sapiens retention | `MF-P0-17.01` |
| SAM2.1 incumbent and official SAM 3.1 first-class challenger | `MF-P0-17.02`–`.04`; `MF-P2-11.03`–`.04`; `MF-P6-06.03` |
| RF-DETR/YOLO, RTMW-X/RTMO, MediaPipe, SAM 3D Body/DensePose | `MF-P0-17.05`–`.07`; `MF-P2-11.05`–`.07`; `MF-P3-08.04`–`.06` |
| BiRefNet variants, Qwen3-VL, EoMT/DINOv3, local GroundingDINO | `MF-P0-17.08`–`.11`; `MF-P2-11.08`–`.11`; `MF-P3-08.03`; `MF-P5-10.07` |
| Parallel CVAT upgrade and isolated runtimes | `MF-P0-17.12`–`.14`; `MF-P6-06.07` |
| Provider-neutral interfaces and legacy compatibility | `MF-P2-11.01`–`.02`; `MF-P6-06.01` |
| Target provider flow and shadow integration | `MF-P2-11.03`–`.12`; `MF-P3-08.01`–`.07` |
| Four truth tiers and permitted uses | `MF-P1-13.01`–`.09`; `MF-P5-10.01`–`.06` |
| Ten autonomous certification checks | `MF-P4-11.02`–`.11`; `MF-P8-11.01`–`.04` |
| Pooled calibration, selective prediction, bounds/floors, mixed audit, revocation/evidence reuse | `MF-P4-11.08`–`.14`; `MF-P7-07.04`–`.06` |
| Gate/metric changes and revised labor/headline metrics | `MF-P5-10.03`–`.05`; `MF-P7-07.05`–`.08`; tracker metrics/DoD/Goals mappings |
| Required repository surfaces | Cross-phase clusters `MF-P0-15` through `MF-P8-11`; existing `MF-P4-08` retained |
| Full benchmark matrix and role promotion | `MF-P2-11.13`–`.15`; `MF-P3-08.08`–`.10`; `MF-P5-10.07`–`.12` |
| 90-day technology currency | `MF-P7-07.01`–`.03` |
| Safe execution order and completion evidence | dependency clauses on every new item; `MF-P7-07.09`–`.10` |
| Autonomous multi-person acceptance/audit | `MF-P8-11.01`–`.08` |

## Deliberate reuse rather than duplication

- Existing `MF-P2-09.*` remains the governed auxiliary-specialist implementation; `MF-P2-11.*` adds provider-neutral modern challengers and the new benchmark matrix.
- Existing `MF-P4-07.*` remains the specialist-aware committee; `MF-P4-10.*` adds provider eligibility, budget, frozen incremental-value, and improvement-loop gates.
- Existing `MF-P4-08.*` remains doc-21 repair authority and now includes explicit verify/blocker clauses; no second repair controller was created.
- Existing `MF-P5-06.*`/`MF-P5-07.*` retain baseline leaderboard/champion work; `MF-P5-10.*` adds truth tiers, hard-bucket non-inferiority, lifecycle transitions, and exact promotion certificates.
- Existing `MF-P8-05.*` and `MF-P8-07.*` remain hard instance/split blockers; `MF-P8-11.*` adds certificate-covered routing and mixed audits.

## Coverage audit rule

CI must parse all Items files, assert exactly 70 ontology-v2 imported IDs, assert every doc 18–22 and handoff section above has at least one valid non-orphaned tracker ID, reject duplicate IDs, reject stale item totals, and reject reintroduction of the owner-excluded age-eligibility gate in the imported tracker files.
