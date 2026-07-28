# Section 17 — Real Multi-Person and Multi-Character Masking

**Acceptance order:** 17 of 20  
**Mapped unresolved tracker items:** 10  
**Current states:** blocked=9, partially_complete=1  
**Hard blockers in scope:** 0  
**Rows with explicit Kevin authority/input:** 6  
**Depends on:** Section 10, Section 12, Section 15  
**Enables:** Section 18, Section 19, Section 20

## Goal

Prove the activated system on 10–20 governed real 2–4-person images with exact instance ownership, certificate-covered acceptance, residual routing, blinded audits, zero cross-instance bleed, and rollback.

## Why this section exists

Synthetic fixtures and partial runs do not satisfy the real D11/G9 requirement. The remaining work needs governed multi-person sources, complete live execution, audit authority, and exact instance/certificate evidence.

## Scope

- Curate 10–20 governed real 2–4-person inputs across separation, overlap, contact, crop, similar appearance, crossed limbs, and prop contact.
- Run exhaustive instance discovery, pose, geometry, silhouette, fusion, specialists, refinement, and deterministic repair.
- Accept only certificate-covered instances; route residuals and preselected audits.
- Measure identity/exclusivity, laterality, ownership, reciprocal contact/occlusion, and cross-instance bleed.
- Prove provider/certificate rollback without corrupting frozen packages or history.

## Work packages

1. Freeze source/instance/relationship manifest before outcomes.
2. Execute the full activated pipeline and preserve per-person provider evidence.
3. Perform required blinded audits and residual reviews only.
4. Publish tier-separated per-instance metrics and D11/G9 evidence.
5. Rehearse role/certificate rollback and replay.

## Section-level testing

- Person discovery completeness and stable p-index/owner assignment.
- Seeded owner swap, left/right swap, cross-person bleed, shared-region, contact, crop, and similar-appearance faults.
- Certificate-covered accept versus residual/audit routing tests.
- QC-035/036 and complete-map per-instance recomposition.
- One-command provider rollback, certificate revocation, and replay.

## Integration tests with the rest of the project

- Section 18 DAZ multi-person truth uses the same ownership/relationship contracts.
- Section 16/20 Main adoption propagates instance identity and residual states exactly.
- Section 19 headline metrics include real multi-person hard buckets.

## Required user/authority actions

- Supply sufficient governed real 2–4-person images.
- Perform the preselected blinded human-anchor audit where required.

## Definition of done and acceptance criteria

- [ ] The full 10–20 image real set completes.
- [ ] Every instance has one truth tier and exact terminal state.
- [ ] Measured cross-instance bleed is zero for accepted packages.
- [ ] Blinded audits and residual routing pass without routine review of every instance.
- [ ] Rollback passes and P8 exit is accepted.

## Required proof artifacts

- `real_multiperson_input_manifest.json`
- `instance_relationship_manifest.json`
- `multiperson_e2e_receipt.json`
- `blinded_audit_report.json`
- `D11_G9_metrics.json`
- `multiperson_rollback_receipt.json`
- `section_acceptance_receipt.json`

## Exit procedure

1. Run T0–T5 tests applicable to this section and preserve commands, exits, counts, environment, and hashes.
2. Verify every mapped tracker row against its own exact `Verify:` clause.
3. Produce and independently validate `section_acceptance_receipt.json`.
4. Exercise rollback/invalidation and verify zero leaked resources.
5. Update tracker rows through `Plan/Tracker/tracker.py`; regenerate dashboard/phase/profile reports.
6. Commit only section-scoped source/evidence locators and open the section PR.
7. Begin the next section only from the accepted commit.

## Mapped tracker items

| Item | Phase | Status | % | Hard blocker | Explicit user authority | Work remaining |
|---|---|---|---:|:---:|:---:|---|
| `MF-P8-10.01` | P8 | blocked | 40 | No | Yes | Curate/collect 10–20 real 2–4-person images with generated/owned/licensed/consented provenance |
| `MF-P8-10.02` | P8 | blocked | 40 | No | Yes | Run the full activated pipeline end-to-end on this set |
| `MF-P8-10.03` | P8 | blocked | 5 | No | No | Automatically accept only certificate-covered instances; route residual cases and preselected audits through SOP-1–SOP-6 without routine CVAT review of every instance |
| `MF-P8-10.04` | P8 | blocked | 0 | No | Yes | Confirm QC-035/036 clean on every autonomous-certified or human-anchor package in this set |
| `MF-P8-10.05` | P8 | blocked | 0 | No | Yes | Record **D11** demonstration evidence; measure **G9** (cross-instance bleed rate — target 0) |
| `MF-P8-10.06` | P8 | blocked | 0 | No | No | Update tier-separated metrics per instance: human-anchor partitions, autonomous-certified, pseudo, and machine candidates; each instance counts once in its own tier and only active certified tiers satisfy volume gates |
| `MF-P8-11.03` | P8 | partially_complete | 92 | No | No | Include SAM3.1 exhaustive instance discovery, SAM2.1/SAM3.1 refinement, RF-DETR, pose, geometry, silhouette, fusion, specialist, and deterministic-repair families when available |
| `MF-P8-11.07` | P8 | blocked | 0 | No | Yes | Run the complete real 10–20 image, 2–4-person demonstration with certificate-covered instances, residual reviews, blinded audits, and zero measured cross-instance bleed |
| `MF-P8-11.08` | P8 | blocked | 0 | No | No | Prove rollback from any promoted multi-person provider/certificate to incumbents without corrupting frozen packages or historical evidence |
| `MF-P8-EXIT` | P8 | blocked | 0 | No | Yes | **D11/G9** hold on real multi-person images (not just synthetic fixtures) · doc 00 §4 and doc 01 §3 both reflect this as demonstrated · doc 14 §11 checkboxes updated |

## Tracker-item exact verification text

### `MF-P8-10.01` — First real multi-person certified/residual evidence set

- **Current:** `blocked` at 40%
- **Source:** `10_ITEMS_P8_MULTI_PERSON_MASKING.md` line 68
- **Requirement:** Curate/collect 10–20 real 2–4-person images with generated/owned/licensed/consented provenance
- **Current blocked reason:** NEEDS KEVIN: completion requires 10-20 Kevin-supplied governance-compliant real 2-4-person images. The current governed real set is below the required count.
- **Existing evidence to preserve/revalidate:** Four qualifying governed 2-4-person sources are collected with real per-instance evidence: img_7b7a3c7d5dd3, img_6d6bb33f01a1, img_5bc6130e5055, and img_a3d2663ad90d. Six more qualifying sources are required to reach the minimum ten.

### `MF-P8-10.02` — First real multi-person certified/residual evidence set

- **Current:** `blocked` at 40%
- **Source:** `10_ITEMS_P8_MULTI_PERSON_MASKING.md` line 69
- **Requirement:** Run the full activated pipeline end-to-end on this set
- **Current blocked reason:** NEEDS KEVIN: the full activated run cannot reach the required 10-20 set until MF-P8-10.01 supplies the remaining governed sources; current partial real runs remain evidence only.
- **Existing evidence to preserve/revalidate:** Both currently qualifying 2-4-person sources (2/10 minimum set) now complete S00-S11; seven schema-valid instance review packages were assembled and live CVAT handoff created tasks 9-17: seven instance jobs plus two overview jobs, 166 preannotation shapes. Durable API-confirmed evidence: qa/live_verification/p8_real_cvat_handoff_20260712.json. Source-count gate remains 2/10, so percent stays 20 and S13-S15/gold remain open.

### `MF-P8-10.03` — First real multi-person certified/residual evidence set

- **Current:** `blocked` at 5%
- **Source:** `10_ITEMS_P8_MULTI_PERSON_MASKING.md` line 70
- **Requirement:** Automatically accept only certificate-covered instances; route residual cases and preselected audits through SOP-1–SOP-6 without routine CVAT review of every instance
- **Current blocked reason:** Autonomous certificates do not yet cover this real multi-person set. Certificate-covered instances will auto-route; Kevin is needed only for residual corrections and preselected audits.
- **Existing evidence to preserve/revalidate:** Live CVAT v2.24 handoff is ready for every current promoted instance: task IDs 9,10,11 and overview 12 for img_7b7a3c7d5dd3; task IDs 13,14,15,16 and overview 17 for img_6d6bb33f01a1. Seven package manifests have reviewer=null and approved_at=null. Audit explicitly records human_correction_completed=false and human_approval_completed=false.

### `MF-P8-10.04` — First real multi-person certified/residual evidence set

- **Current:** `blocked` at 0%
- **Source:** `10_ITEMS_P8_MULTI_PERSON_MASKING.md` line 71
- **Requirement:** Confirm QC-035/036 clean on every autonomous-certified or human-anchor package in this set
- **Current blocked reason:** NEEDS KEVIN: QC-035/036 approval-set confirmation requires completed Kevin-approved packages from MF-P8-10.03.

### `MF-P8-10.05` — First real multi-person certified/residual evidence set

- **Current:** `blocked` at 0%
- **Source:** `10_ITEMS_P8_MULTI_PERSON_MASKING.md` line 72
- **Requirement:** Record **D11** demonstration evidence; measure **G9** (cross-instance bleed rate — target 0)
- **Current blocked reason:** NEEDS KEVIN: D11/G9 final measurement requires the complete approved real multi-person set.

### `MF-P8-10.06` — First real multi-person certified/residual evidence set

- **Current:** `blocked` at 0%
- **Source:** `10_ITEMS_P8_MULTI_PERSON_MASKING.md` line 73
- **Requirement:** Update tier-separated metrics per instance: human-anchor partitions, autonomous-certified, pseudo, and machine candidates; each instance counts once in its own tier and only active certified tiers satisfy volume gates
- **Current blocked reason:** Tier-separated counts cannot advance until real outputs become human-anchor train, calibration, holdout, or autonomous-certified under current unrevoked certificates; pseudo-labels and candidates remain separate.

### `MF-P8-11.03` — Certificate-covered multi-person instances and residual routing

- **Current:** `partially_complete` at 92%
- **Source:** `19_ITEMS_P8_AUTONOMOUS_MULTI_PERSON.md` line 13
- **Requirement:** Include SAM3.1 exhaustive instance discovery, SAM2.1/SAM3.1 refinement, RF-DETR, pose, geometry, silhouette, fusion, specialist, and deterministic-repair families when available · Verify: tournament evidence preserves person/instance identity and independent-family provenance · Blocked by: MF-P2-11.03 through MF-P2-11.08
- **Existing evidence to preserve/revalidate:** Existing multi-person lifecycle/tournament contracts plus production SAM3.1 sidecar: qa/live_verification/multi_person_lifecycle_route_contract_20260715.json and qa/live_verification/sam31_production_shadow_orchestration_20260715.json SHA-256 c9ef811e69776bc41bad8a5c8964f615ef4d3de53852d409780bdc2490694df7; complete repository 1659/1659. Remaining: official live qualification and governed real multi-person exhaustive discovery/tournaments/lifecycle receipts/D11-G9 evidence.

### `MF-P8-11.07` — Certificate-covered multi-person instances and residual routing

- **Current:** `blocked` at 0%
- **Source:** `19_ITEMS_P8_AUTONOMOUS_MULTI_PERSON.md` line 17
- **Requirement:** Run the complete real 10–20 image, 2–4-person demonstration with certificate-covered instances, residual reviews, blinded audits, and zero measured cross-instance bleed · Verify: D11/G9 evidence binds every source, instance, mask, certificate, audit, and final package hash · Blocked by: NEEDS KEVIN: sufficient governed multi-person sources and the preselected blinded human-anchor audit
- **Current blocked reason:** NEEDS KEVIN: sufficient governed 2-4-person sources and the preselected blinded human-anchor audit are required; certificate-covered instances otherwise route automatically.

### `MF-P8-11.08` — Certificate-covered multi-person instances and residual routing

- **Current:** `blocked` at 0%
- **Source:** `19_ITEMS_P8_AUTONOMOUS_MULTI_PERSON.md` line 18
- **Requirement:** Prove rollback from any promoted multi-person provider/certificate to incumbents without corrupting frozen packages or historical evidence · Verify: one-command role/lifecycle rollback plus certificate revocation and replay smoke pass · Blocked by: promoted challenger and MF-P8-11.07
- **Current blocked reason:** Rollback demonstration requires at least one promoted multi-person challenger/certificate and the completed real MF-P8-11.07 evidence set.

### `MF-P8-EXIT` — Phase Exit Gate

- **Current:** `blocked` at 0%
- **Source:** `10_ITEMS_P8_MULTI_PERSON_MASKING.md` line 76
- **Requirement:** **D11/G9** hold on real multi-person images (not just synthetic fixtures) · doc 00 §4 and doc 01 §3 both reflect this as demonstrated · doc 14 §11 checkboxes updated
- **Current blocked reason:** NEEDS KEVIN: P8 exit requires D11/G9 on the completed real multi-person set after Kevin's source supply and CVAT approvals.

