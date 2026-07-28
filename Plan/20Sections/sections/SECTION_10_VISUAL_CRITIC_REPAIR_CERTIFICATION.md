# Section 10 — Visual Critic Committee, Repair, Certification, Revocation, and 66-Class Safety

**Acceptance order:** 10 of 20  
**Mapped unresolved tracker items:** 35  
**Current states:** blocked=14, in_progress=4, open=3, partially_complete=14  
**Hard blockers in scope:** 18  
**Rows with explicit Kevin authority/input:** 12  
**Depends on:** Section 05, Section 08, Section 09  
**Enables:** Section 11, Section 12, Section 14, Section 15, Section 16, Section 17, Section 19, Section 20

## Goal

Establish qualified primary and independent-family visual authority, fail-closed disagreement, bounded repair, exact terminal accounting, and real certificate/revocation behavior across every active class and risk stratum.

## Why this section exists

This is the largest core safety bottleneck. The project has strong schemas and fixtures, but current qualification still lacks sufficient real 66-class coverage, independent juror proof, live calibration sets, full corpus execution, and accepted 100-record accounting.

## Scope

- Build the 20-anchor/40-panel calibration set, 30-image audits, 200-case incremental corpus, and 66-class visual-regression suite.
- Qualify a high-end primary critic and independent-family juror; prohibit same-family quorum.
- Implement fail-closed disagreement, unavailable/unqualified critic abstention, and hard-QA veto authority.
- Run deterministic hard QA, specialist-aware review, bounded hypothesis-distinct repair, no-progress termination, and immutable parent preservation.
- Execute representative then scaled polygon/provider/reference shards with complete source/mask/panel/verdict lineage.
- Build/revoke/replay exact record certificates; persist accept/repair/abstain/reject/quarantine outcomes.
- Bind the current 66-class gate into the canonical runtime and reconstruct visual evidence through the locator.

## Work packages

1. Freeze visual corpora and qualification thresholds before model results.
2. Run positive/negative qualification for primary and juror roles.
3. Finish strict per-record panel/evidence requirements and batch continuation behavior.
4. Run representative shards, 1,000-record expansion, and eligible full corpus without threshold weakening.
5. Publish coverage, defect, repair, abstention, certification, audit, and revocation reports.
6. Close P4 exit only on real governed evidence.

## Section-level testing

- Wrong label/target/person/tile, all-reject, rubber-stamp, hallucinated context, evidence-free, malformed/truncated, nondeterministic, timeout, and unavailable critic fixtures.
- Same-family quorum, primary/juror disagreement, hard-QA override, stale qualification, and missing-label negative tests.
- Repair success/no-progress/retry-cap/immutable-parent/continue-on-exception tests.
- Real-image serious-defect recall, precision, false-pass, abstention, label-scope, latency, and panel-budget gates.
- Certificate issuance, selection, fingerprint drift, revocation, stale refusal, and replay tests.
- One 100-record terminal-accounting run with zero lost/duplicate outcomes.

## Integration tests with the rest of the project

- Section 11 counts only exact certified truth tiers.
- Section 14 campaigns cannot bypass visual or deterministic authority.
- Sections 15–17 propagate abstain/reject/quarantine and certificate invalidation exactly.
- Section 20 release validation rejects stale or historical-only critic evidence.

## Required user/authority actions

- Provide/approve sufficient governed human-anchor sources for the frozen visual corpora.
- Perform only the required blinded/second-review authority actions; do not turn routine per-image review into a hidden prerequisite.
- Authorize any paid evaluation calls before they are used.

## Definition of done and acceptance criteria

- [ ] Qualified current primary and independent juror roles exist.
- [ ] The 66-class real-image suite covers every required risk/domain stratum.
- [ ] Disagreement and insufficient evidence fail closed.
- [ ] Repair/certification/revocation paths pass real and negative evidence.
- [ ] Every processed record has one terminal outcome and exact accounting.
- [ ] P4 exit, MF-P6-17.03/.04, and MF-P6-21.02/.03 are accepted.

## Required proof artifacts

- `visual_regression_66_manifest.json`
- `critic_qualification_primary.json`
- `critic_qualification_juror.json`
- `visual_gate_report.json`
- `repair_accounting.json`
- `certificate_revocation_demo.json`
- `corpus_coverage_report.json`
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
| `MF-P4-01.06` | P4 | blocked | 0 | No | Yes | 20-image run: verdicts land correctly for every hard-class panel + P-IMAGE sanity output |
| `MF-P4-04.03` | P4 | blocked | 0 | No | Yes | 30-image hand-count audit matches the matrix exactly |
| `MF-P4-05.01` | P4 | blocked | 65 | Yes | Yes | Build `qa\vlm_eval\`: 40 panels with known ground truth — 20 good, 20 seeded defects spanning the problems taxonomy (wrong_side, boundary loose/tight, clothing-as-skin, neighbor bleed, missing area, hidden-area mask, finger_merge, hair edge, occlusion error) |
| `MF-P4-05.04` | P4 | blocked | 25 | Yes | Yes | Run and PASS the gate on qwen2.5vl:7b · record scores in OPS_LOG (fallback model scored too) |
| `MF-P4-06.04` | P4 | blocked | 75 | No | Yes | Weekly IAA report (per-class IoU vs targets ≥ 0.92 body / ≥ 0.80 fingers) · first report produced and filed |
| `MF-P4-06.05` | P4 | blocked | 80 | No | Yes | IAA numbers exported as the leaderboard human-ceiling row input |
| `MF-P4-07.04` | P4 | blocked | 25 | No | Yes | Rebuild and PASS the production VLM calibration gate from exactly 20 distinct frozen, QA-passing human-anchor calibration packages after every bound prompt/controller/evidence change |
| `MF-P4-08.08` | P4 | blocked | 0 | Yes | Yes | Rebuild and PASS the gold-backed calibration gate; measure correction-time improvement on at least 30 approved anchor masks |
| `MF-P4-09.06` | P4 | blocked | 0 | No | Yes | Build real calibration panels; synthetic/near-duplicate panels are diagnostic only |
| `MF-P4-09.07` | P4 | blocked | 0 | Yes | No | Pass calibrated recall/precision and hard-bucket gates before anatomy routing is enabled |
| `MF-P4-10.08` | P4 | blocked | 0 | No | Yes | Build a frozen image-disjoint ≥200-case incremental-value corpus covering serious defects, good masks, hard labels, contexts, and naturally occurring errors |
| `MF-P4-10.09` | P4 | blocked | 0 | Yes | No | Require every provider/model/prompt to pass serious recall, overall recall, precision, false-pass, incremental recall, usefulness, cost/useful-correction, review-time, and high-risk non-regression thresholds simultaneously |
| `MF-P4-10.12` | P4 | partially_complete | 80 | No | No | Evaluate each local-Qwen challenger on untouched teacher holdout, local 40-panel gate, ≥200-case incremental set, per-label/serious regressions, latency/VRAM, and reviewer time; promote only a measured win with rollback |
| `MF-P4-11.25` | P4 | partially_complete | 85 | Yes | No | Require package-specific semantic label/pixel alignment from a current primary critic plus independent-family juror before autonomous package freeze and training; bind exact source, final mask set, every active label/mask, label-aware panels, deterministic QA, quorum, and report hashes, and quarantine legacy packages missing either semantic or quorum binding without rewriting them - Verify: wrong-label consensus, all-pass structural QA, missing/stale/same-family critic, hard-veto, incomplete-label, and hash-drift fixtures all fail closed - Blocked by: MF-P4-11.18, MF-P4-11.19, MF-P4-11.21 - HARD BLOCKER |
| `MF-P4-11.26` | P4 | partially_complete | 88 | Yes | No | Run semantic requalification in deterministic bulk batches by default across eligible MaskFactory packages, qualified MaskedWarehouse labels/masks, and reference-library retrieval cases; automatically accept exact matches, publish unambiguous relabels only as new immutable versions, continue past malformed/uncertain cases, and emit compact summary/exception reports with human review optional - Verify: batch planner is deterministic, every case/panel/mask is hash-bound, required primary-plus-independent roles are explicit, one malformed case does not stop other cases, and no frozen package is mutated - Blocked by: MF-P4-11.21, MF-P4-11.25 - HARD BLOCKER |
| `MF-P4-11.11` | P4 | partially_complete | 72 | Yes | No | Allow `autonomous_certified_gold` only for one exact immutable per-record package binding target contract, qualified per-label/context QA registry and vector, current semantic alignment, qualified independent critic quorum, complete mask-set/package revision, and unexpired/unrevoked certificate; population statistics, provider consensus, operational certificates, sparse/shifted evidence, and missing bindings cannot promote the record |
| `MF-P4-11.15` | P4 | blocked | 0 | No | Yes | Demonstrate certificate build, eligible selection, residual abstention, serious-failure revocation, fingerprint-drift revocation, and weekly mixed audit on real governed evidence |
| `MF-P4-11.18` | P4 | partially_complete | 98 | Yes | No | Enforce frozen real-image valid-mask pass rate, defect recall/precision, serious false-pass, abstention, hallucinated-context, label-scope, evidence-localization, deterministic replay, malformed/truncated/schema, latency, and panel-budget thresholds; GPU/VRAM measurements are telemetry only and cannot admit, rank, promote, or reject a role; rejecting everything or reviewing the wrong target/person/tile is unavailable, never qualified |
| `MF-P4-11.19` | P4 | in_progress | 76 | No | No | Require an independently trained juror family for high-risk pass routes and prevent correlated variants from creating quorum |
| `MF-P4-11.23` | P4 | in_progress | 20 | Yes | No | Maintain a frozen real-image visual-regression suite covering all 66 active classes plus every required risk/domain stratum: hands/fingers, feet/toes, hair, clothing/skin boundaries, complete visible adult anatomy, label scale, laterality, ownership, transform, occlusion/contact, crop/out-of-frame, media domain, and multi-person risk, using `F:\Reference_Images` for coverage/retrieval and qualified `C:\Comfy_UI_Main\MaskedWarehouse` labels or exact qualified package masks for labeled cases |
| `MF-P4-12.01` | P4 | partially_complete | 98 | Yes | No | Implement durable 256-record shard queue state, owned leases, retry caps, heartbeats, checkpoints, idempotency, submitted-unknown recovery, and milestone reports |
| `MF-P4-12.02` | P4 | partially_complete | 80 | No | No | Run the polygon lane through qualified external-mask comparison, hard QC, strict per-record visual review, repair/abstain, and signed outcomes |
| `MF-P4-12.03` | P4 | partially_complete | 70 | No | No | Generate multi-provider masks from bbox prompts without treating boxes as pixels |
| `MF-P4-12.04` | P4 | partially_complete | 65 | No | No | Process all 26 CivitAI reference shards (6,537 images) through multi-provider proposal generation, provider comparison, hard QC, strict per-record visual review, bounded repair, abstention/quarantine, and exact-output certification without source truth |
| `MF-P4-12.05` | P4 | partially_complete | 90 | Yes | No | Require complete source/mask/overlay/contour/ownership evidence and one structured strict-VLM verdict per record |
| `MF-P4-12.06` | P4 | partially_complete | 97 | No | No | Run bounded automatic repair/no-progress detection and continue-on-exception outcomes |
| `MF-P4-12.07` | P4 | partially_complete | 64 | No | No | Pass one representative shard from every lane before expansion |
| `MF-P4-12.08` | P4 | partially_complete | 5 | Yes | No | Expand progressively to 1,000 records and the full eligible corpus without threshold weakening |
| `MF-P4-12.09` | P4 | partially_complete | 30 | No | No | Publish dataset-level anatomy/action/domain/split/agreement/QC/repair/abstention/certification coverage reports |
| `MF-P4-12.10` | P4 | open | 0 | Yes | No | Prove one exact real record from `source_reference` through detection, ownership, multi-provider masks, frozen per-label/context QA, qualified independent visual quorum, bounded repair when required, complete-map semantic alignment, immutable `autonomous_certified_gold` package, verification, revocation, and stale-certificate rejection |
| `MF-P4-EXIT` | P4 | blocked | 0 | No | Yes | **D4** demonstrated: VLM reviews + agree/disagree routing correct on the 20-image validation set · mining produced ≥ 1 weekly acquisition plan · doc 14 §5 checkboxes updated |
| `MF-P6-17.03` | P6 | in_progress | 60 | Yes | No | Run exact evidence panels through a qualified high-end primary visual critic and qualified independent-family juror; text-only or correlated critics cannot approve |
| `MF-P6-17.04` | P6 | in_progress | 55 | Yes | No | Persist terminal accept/repair/abstain/reject/quarantine outcomes and complete accounting for every mask record |
| `MF-P6-21.02` | P6 | open | 0 | Yes | No | Make provider and critic disagreement fail closed as abstain/adjudicate/reject/quarantine, never an implicit pass; preserve hard-QA veto authority |
| `MF-P6-21.03` | P6 | open | 0 | Yes | No | Bind the current source-qualified 66-class visual gate, exact critic qualifications, and mask-campaign prerequisites into the canonical runtime without duplicating historical campaigns |

## Tracker-item exact verification text

### `MF-P4-01.06` — S11 VLM QA runner

- **Current:** `blocked` at 0%
- **Source:** `05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md` line 16
- **Requirement:** 20-image run: verdicts land correctly for every hard-class panel + P-IMAGE sanity output
- **Current blocked reason:** NEEDS KEVIN: the governed VLM gate requires 20 distinct frozen human-anchor packages before an authoritative 20-image verdict run; current anchor count is 0.

### `MF-P4-04.03` — Coverage matrix live

- **Current:** `blocked` at 0%
- **Source:** `05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md` line 34
- **Requirement:** 30-image hand-count audit matches the matrix exactly
- **Current blocked reason:** NEEDS KEVIN: the 30-image hand-count audit requires 30 human-anchor packages and independent human count authority.

### `MF-P4-05.01` — Coverage matrix live

- **Current:** `blocked` at 65%
- **Source:** `05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md` line 37
- **Requirement:** Build `qa\vlm_eval\`: 40 panels with known ground truth — 20 good, 20 seeded defects spanning the problems taxonomy (wrong_side, boundary loose/tight, clothing-as-skin, neighbor bleed, missing area, hidden-area mask, finger_merge, hair edge, occlusion error)
- **Current blocked reason:** NEEDS KEVIN: the fail-closed builder requires exactly 20 distinct frozen QA-passing human-anchor packages; synthetic and autonomous-certified packages are diagnostic or ineligible for this calibration authority.
- **Existing evidence to preserve/revalidate:** Implementation and tests: src/maskfactory/vlm/eval.py, src/maskfactory/cli.py, tests/test_vlm_eval_gate.py. Durable contract audit: qa/live_verification/vlm_gold_calibration_builder_20260712.json. The fail-closed builder requires 20 distinct hash-bound governed gold sources and 40 balanced panels; the item remains blocked until the source count exists.

### `MF-P4-05.04` — Coverage matrix live

- **Current:** `blocked` at 25%
- **Source:** `05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md` line 40
- **Requirement:** Run and PASS the gate on qwen2.5vl:7b · record scores in OPS_LOG (fallback model scored too)
- **Current blocked reason:** NEEDS KEVIN: Qwen and fallback scoring cannot be authoritative until MF-P4-05.01 has a real 20-human-anchor and 40-panel corpus. Current live diagnostics correctly fail the gate.
- **Existing evidence to preserve/revalidate:** qa/live_verification/vlmqa_run_cli_20260712.json proves live fail-closed VLM gate enforcement. qa/live_verification/autonomy_certificate_scope_hardening_20260713.json proves complete pipeline binding and collision-free revocation. qa/live_verification/autonomy_human_gold_authority_hardening_20260713.json proves certificate truth is linked to human gold and actual machine winners. qa/live_verification/autonomy_recurring_lifecycle_hardening_20260713.json proves fail-closed recurring audit and train-only pseudo-label handling. Actual qwen/fallback scoring against the governed 40-panel approved-gold corpus remains required.

### `MF-P4-06.04` — Second review + IAA

- **Current:** `blocked` at 75%
- **Source:** `05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md` line 46
- **Requirement:** Weekly IAA report (per-class IoU vs targets ≥ 0.92 body / ≥ 0.80 fingers) · first report produced and filed
- **Current blocked reason:** NEEDS KEVIN: the first genuine IAA report requires Kevin's second-review sign-off and archived reviewer mask pairs; no real qa/iaa archive exists.

### `MF-P4-06.05` — Second review + IAA

- **Current:** `blocked` at 80%
- **Source:** `05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md` line 47
- **Requirement:** IAA numbers exported as the leaderboard human-ceiling row input
- **Current blocked reason:** NEEDS KEVIN: a human-ceiling leaderboard row requires real IAA numbers from signed second reviews; fixture-only numbers cannot be published.

### `MF-P4-07.04` — Specialist-aware autonomous committee

- **Current:** `blocked` at 25%
- **Source:** `05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md` line 53
- **Requirement:** Rebuild and PASS the production VLM calibration gate from exactly 20 distinct frozen, QA-passing human-anchor calibration packages after every bound prompt/controller/evidence change · Verify: image-disjoint package/mask/fingerprint hashes are frozen and current
- **Current blocked reason:** NEEDS KEVIN: approve at least 20 distinct frozen QA-passing human-anchor packages; calibration and holdout anchors cannot be replaced by synthetic, autonomous-certified, or pseudo-labeled masks.

### `MF-P4-08.08` — Autonomous mask repair execution

- **Current:** `blocked` at 0%
- **Source:** `05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md` line 63
- **Requirement:** Rebuild and PASS the gold-backed calibration gate; measure correction-time improvement on at least 30 approved anchor masks · Verify: current controller/prompt/evidence fingerprint passes and paired review-time report shows measured effect · Blocked by: NEEDS KEVIN: at least 30 reviewed human-anchor masks and any authorized paid calls · HARD BLOCKER
- **Current blocked reason:** NEEDS KEVIN: at least 30 reviewed human-anchor masks, paired review-time measurements, and any authorized paid calls are required for the gold-backed repair calibration gate.

### `MF-P4-09.06` — Ontology-v2 QA and calibration

- **Current:** `blocked` at 0%
- **Source:** `15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md` line 20
- **Requirement:** Build real calibration panels; synthetic/near-duplicate panels are diagnostic only · Verify: frozen panel manifest is image-disjoint and binds human-anchor truth hashes · Blocked by: NEEDS KEVIN: sufficient reviewed human-anchor packages
- **Current blocked reason:** NEEDS KEVIN: sufficient image-disjoint reviewed human-anchor packages do not yet exist for authoritative real calibration panels.

### `MF-P4-09.07` — Ontology-v2 QA and calibration

- **Current:** `blocked` at 0%
- **Source:** `15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md` line 21
- **Requirement:** Pass calibrated recall/precision and hard-bucket gates before anatomy routing is enabled · Verify: current fingerprint-bound gate passes on the frozen real panel set · Blocked by: MF-P4-09.06 · HARD BLOCKER
- **Current blocked reason:** The anatomy routing gate cannot run until MF-P4-09.01 removes the retired QC, MF-P4-09.06 supplies real calibration panels, and measured hard-bucket recall/precision passes.

### `MF-P4-10.08` — Governed multi-provider teacher and human-anchor improvement loop

- **Current:** `blocked` at 0%
- **Source:** `15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md` line 31
- **Requirement:** Build a frozen image-disjoint ≥200-case incremental-value corpus covering serious defects, good masks, hard labels, contexts, and naturally occurring errors · Verify: corpus audit rejects leakage/duplication/coverage gaps · Blocked by: NEEDS KEVIN: sufficient human-anchor truth and any approved cloud evaluation budget
- **Current blocked reason:** NEEDS KEVIN: the ≥200-case image-disjoint human-anchor corpus and any billable cloud-evaluation authorization are not yet available.

### `MF-P4-10.09` — Governed multi-provider teacher and human-anchor improvement loop

- **Current:** `blocked` at 0%
- **Source:** `15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md` line 32
- **Requirement:** Require every provider/model/prompt to pass serious recall, overall recall, precision, false-pass, incremental recall, usefulness, cost/useful-correction, review-time, and high-risk non-regression thresholds simultaneously · Verify: frozen evaluation report and threshold tests pass · Blocked by: MF-P4-10.08 · HARD BLOCKER
- **Current blocked reason:** No frozen ≥200-case incremental-value report exists because MF-P4-10.08 lacks the required human-anchor corpus and any approved live provider budget.

### `MF-P4-10.12` — Governed multi-provider teacher and human-anchor improvement loop

- **Current:** `partially_complete` at 80%
- **Source:** `15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md` line 35
- **Requirement:** Evaluate each local-Qwen challenger on untouched teacher holdout, local 40-panel gate, ≥200-case incremental set, per-label/serious regressions, latency/VRAM, and reviewer time; promote only a measured win with rollback · Verify: immutable candidate identity, certificate, and rollback pass · Blocked by: MF-P4-10.09, MF-P4-10.11
- **Existing evidence to preserve/revalidate:** qa/governance/benchmark_matrices/qwen_challenger_benchmark_v1.json canonical SHA-256 3425c7464035eb012e6c4220748103d61df6b7bb8a69cef24e14b6fdfa163ffd; qa/live_verification/sam3_litetext_installation_bundle_20260715.json; 63 affected-policy and 1593 full tests pass.

### `MF-P4-11.25` — P4

- **Current:** `partially_complete` at 85%
- **Source:** `15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md` line 11
- **Requirement:** Require package-specific semantic label/pixel alignment from a current primary critic plus independent-family juror before autonomous package freeze and training; bind exact source, final mask set, every active label/mask, label-aware panels, deterministic QA, quorum, and report hashes, and quarantine legacy packages missing either semantic or quorum binding without rewriting them - Verify: wrong-label consensus, all-pass structural QA, missing/stale/same-family critic, hard-veto, incomplete-label, and hash-drift fixtures all fail closed - Blocked by: MF-P4-11.18, MF-P4-11.19, MF-P4-11.21 - HARD BLOCKER
- **Existing evidence to preserve/revalidate:** qa/live_verification/historical_caa_641_to_220_reconciliation_20260722.json; live sanitized inventory seal 4b1acb18100980f284c9c2f363911ef3a6783f1161a05156a60896edd21140aa; 16 focused tests PASS.

### `MF-P4-11.26` — P4

- **Current:** `partially_complete` at 88%
- **Source:** `15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md` line 12
- **Requirement:** Run semantic requalification in deterministic bulk batches by default across eligible MaskFactory packages, qualified MaskedWarehouse labels/masks, and reference-library retrieval cases; automatically accept exact matches, publish unambiguous relabels only as new immutable versions, continue past malformed/uncertain cases, and emit compact summary/exception reports with human review optional - Verify: batch planner is deterministic, every case/panel/mask is hash-bound, required primary-plus-independent roles are explicit, one malformed case does not stop other cases, and no frozen package is mutated - Blocked by: MF-P4-11.21, MF-P4-11.25 - HARD BLOCKER
- **Existing evidence to preserve/revalidate:** qa/live_verification/historical_caa_641_to_220_reconciliation_20260722.json; classification report SHA-256 30c701d4a3e5e812b430c8d908dfbba2ecff0fba9dded1a6bd2b0e27ce539479.

### `MF-P4-11.11` — Selective autonomous tournament, certification, audit, and revocation

- **Current:** `partially_complete` at 72%
- **Source:** `15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md` line 48
- **Requirement:** Allow `autonomous_certified_gold` only for one exact immutable per-record package binding target contract, qualified per-label/context QA registry and vector, current semantic alignment, qualified independent critic quorum, complete mask-set/package revision, and unexpired/unrevoked certificate; population statistics, provider consensus, operational certificates, sparse/shifted evidence, and missing bindings cannot promote the record · Verify: population-certificate, scope/context/fingerprint/drift, missing semantic/quorum/QA, and stale/revoked fixtures route residual or quarantine · Blocked by: MF-P4-11.10, MF-P4-11.18, MF-P4-11.19, MF-P4-12.11 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** qa/live_verification/autonomous_gold_per_record_qa_admission_20260722.json SHA256 50a284c6306f8b8b60565b090be73ffa4bb1bdb6f2327b1c6df153f56c43c3e9; 78 focused/adjacent pytest cases PASS; Ruff/Black/schema/diff integrity PASS.

### `MF-P4-11.15` — Selective autonomous tournament, certification, audit, and revocation

- **Current:** `blocked` at 0%
- **Source:** `15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md` line 52
- **Requirement:** Demonstrate certificate build, eligible selection, residual abstention, serious-failure revocation, fingerprint-drift revocation, and weekly mixed audit on real governed evidence · Verify: live evidence report contains exact hashes and measured rates, not implementation claims · Blocked by: NEEDS KEVIN: sufficient blinded human-anchor audits and source images
- **Current blocked reason:** NEEDS KEVIN: real governed sources and sufficient blinded human-anchor audits are required for the live certificate/selection/abstention/revocation/weekly-audit demonstration.

### `MF-P4-11.18` — Selective autonomous tournament, certification, audit, and revocation

- **Current:** `partially_complete` at 98%
- **Source:** `15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md` line 55
- **Requirement:** Enforce frozen real-image valid-mask pass rate, defect recall/precision, serious false-pass, abstention, hallucinated-context, label-scope, evidence-localization, deterministic replay, malformed/truncated/schema, latency, and panel-budget thresholds; GPU/VRAM measurements are telemetry only and cannot admit, rank, promote, or reject a role; rejecting everything or reviewing the wrong target/person/tile is unavailable, never qualified · Verify: all-reject, rubber-stamp, hallucinated-context, wrong-target/person/tile, evidence-free, nondeterministic, and hardware-telemetry-gated critics fail role qualification · Blocked by: MF-P4-11.17 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** qa/live_verification/runpod_current_visual_critic_failclosed_20260723.json

### `MF-P4-11.19` — Selective autonomous tournament, certification, audit, and revocation

- **Current:** `in_progress` at 76%
- **Source:** `15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md` line 56
- **Requirement:** Require an independently trained juror family for high-risk pass routes and prevent correlated variants from creating quorum · Verify: same-family ensemble fixtures abstain while qualified independent-family evidence proceeds · Blocked by: MF-P4-11.16, MF-P4-11.18
- **Existing evidence to preserve/revalidate:** qa/live_verification/runpod_current_visual_critic_failclosed_20260723.json

### `MF-P4-11.23` — Selective autonomous tournament, certification, audit, and revocation

- **Current:** `in_progress` at 20%
- **Source:** `15_ITEMS_P4_AUTONOMY_AND_TEACHERS.md` line 60
- **Requirement:** Maintain a frozen real-image visual-regression suite covering all 66 active classes plus every required risk/domain stratum: hands/fingers, feet/toes, hair, clothing/skin boundaries, complete visible adult anatomy, label scale, laterality, ownership, transform, occlusion/contact, crop/out-of-frame, media domain, and multi-person risk, using `F:\Reference_Images` for coverage/retrieval and qualified `C:\Comfy_UI_Main\MaskedWarehouse` labels or exact qualified package masks for labeled cases · Verify: missing strata are explicit failures, every promoted critic/provider/prompt/runtime change reruns the suite, and serious regression blocks promotion; synthetic-only suites cannot promote · Blocked by: MF-P4-11.17, MF-P4-11.21 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** qa/live_verification/frozen_real_visual_regression_suite_20260722.json; qa/live_verification/visual_regression_66_class_promotion_gate_20260723.json; qa/live_verification/visual_corpus_source_deficits_v2_20260723.json self_sha256=34fd8c93d9cd4825879753d4dcaa62c70afbb2ee3fa33a1b1cb31f942a340980; qa/live_verification/runpod_canonical_polygon_semantic_review_20260723.json; qa/live_verification/runpod_celebamask_control_admission_20260723.json self_sha256=3c225fd8dc53b856c5ac0299838d760cac9f3d7d636e41999934b355b2995c9d; focused tests PASS; Ruff, Black, tracker validation, and diff integrity PASS

### `MF-P4-12.01` — P4

- **Current:** `partially_complete` at 98%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 13
- **Requirement:** Implement durable 256-record shard queue state, owned leases, retry caps, heartbeats, checkpoints, idempotency, submitted-unknown recovery, and milestone reports · Verify: crash/replay/expired-lease/contention tests resume by sample ID without duplicate accepted work · Blocked by: MF-P0-18.01 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** qa/live_verification/runpod_sam31_provider_canary_failclosed_20260723.json; qa/live_verification/runpod_visual_unavailability_batch_abstention_20260723.json self SHA-256 3b53eaf5821e7dc7356e2a6882ed878fa8bf02d22ce69f9249ecf333b93983b5; qa/live_verification/runpod_persistence_refresh_20260723.json; qa/live_verification/runpod_corpus_mirrors_refresh_20260723.json; qa/live_verification/runpod_nude_queue_crash_resume_20260723.json file SHA-256 1b79b623d368cac039f4ffd077ebfbcbadb927363449ced91644ca6a0158463c self SHA-256 c20abf5fba44cffdd1655ae7ffd4fc7febf7478a34f4d38ec3714952623e6faf; qa/live_verification/runpod_sam31_reference_wave64_checkpoint_20260723.json self SHA-256 dbc32f5af91a1d1405ccc93ced2b976458ad17ded5ac79c62abc91fe1bfc19d3; qa/live_verification/runpod_sam31_resident_wave64_20260723.json self SHA-256 dd95b29af1a90d69e525b8624ff48124c10427b2017c028822f4bfbc76753b74

### `MF-P4-12.02` — P4

- **Current:** `partially_complete` at 80%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 14
- **Requirement:** Run the polygon lane through qualified external-mask comparison, hard QC, strict per-record visual review, repair/abstain, and signed outcomes · Verify: exact source/polygon/mask/panel/provider/verdict lineage for every record · Blocked by: MF-P0-18.03 through MF-P0-18.07, MF-P4-12.01
- **Existing evidence to preserve/revalidate:** qa/live_verification/nude_training_role_ownership_reconciliation_20260722.json; v6 population summary file sha256 80bfcc9ee098d0535a4b3036c8e51db80bc43afc9783bec9f5d44a0483b4a69e / self seal a4e5fb103d104b754c5b82ea1c3f8982c5224873676f3662dcc0f3af7d0c607c; population sha256 cc94942372110dca15ae9bb76bad1c7dfcc6a30ffeb733e157536aced5a3fdbe; 4 verified, 9 ambiguous, 96,501 unresolved, zero training authority; 66 focused/adjacent tests pass; Ruff/Black/tracker/diff pass.

### `MF-P4-12.03` — P4

- **Current:** `partially_complete` at 70%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 15
- **Requirement:** Generate multi-provider masks from bbox prompts without treating boxes as pixels · Verify: canary proves provider provenance, boundary refinement, hard QC, strict review, and terminal outcomes · Blocked by: MF-P0-18.04, MF-P4-12.01
- **Existing evidence to preserve/revalidate:** qa/live_verification/runpod_sam31_first_shard_resident_consolidation_20260723.json self SHA-256 47978a9b2076596d3caa3ed7b332ca5f2e09140ac7075cce759003e66a7523d0

### `MF-P4-12.04` — P4

- **Current:** `partially_complete` at 65%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 16
- **Requirement:** Process all 26 CivitAI reference shards (6,537 images) through multi-provider proposal generation, provider comparison, hard QC, strict per-record visual review, bounded repair, abstention/quarantine, and exact-output certification without source truth · Verify: downloaded images/prompts never become masks, gold, or pixel labels; only newly generated hash-bound artifacts may earn machine-verified supervision and insufficient evidence abstains · Blocked by: MF-P0-18.04, MF-P4-12.01
- **Existing evidence to preserve/revalidate:** qa/live_verification/runpod_sam31_first_shard_resident_consolidation_20260723.json self SHA-256 47978a9b2076596d3caa3ed7b332ca5f2e09140ac7075cce759003e66a7523d0

### `MF-P4-12.05` — P4

- **Current:** `partially_complete` at 90%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 17
- **Requirement:** Require complete source/mask/overlay/contour/ownership evidence and one structured strict-VLM verdict per record · Verify: contact-sheet-only, missing-panel, rubber-stamp, and hard-QC-clear attempts fail · Blocked by: MF-P4-11.18 through MF-P4-11.22 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** qa/live_verification/nude_civitai_reference_strict_visual_batch_implementation_20260722.json; qa/live_verification/nude_civitai_strict_visual_structured_repair_intent_20260722.json; qa/live_verification/runpod_visual_unavailability_batch_abstention_20260723.json self SHA-256 3b53eaf5821e7dc7356e2a6882ed878fa8bf02d22ce69f9249ecf333b93983b5; 30 focused work-cell tests PASS; Ruff/Black/diff integrity PASS

### `MF-P4-12.06` — P4

- **Current:** `partially_complete` at 97%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 18
- **Requirement:** Run bounded automatic repair/no-progress detection and continue-on-exception outcomes · Verify: pass/repair/abstain/quarantine controls preserve immutable parents and do not stall unrelated records · Blocked by: MF-P4-12.02 through MF-P4-12.05
- **Existing evidence to preserve/revalidate:** qa/live_verification/nude_civitai_repair_queue_checkpoint_20260722.json; 129 focused/adjacent/tracker tests PASS; Ruff/Black/diff integrity clean; qa/live_verification/runpod_split_person_recomposition_hard_qa_20260723.json file SHA-256 ff33339afcf250cc4f443cd0959cdde893ae53f1139137945509deaebc9e7ec8 self SHA-256 d75cccf0766c203930b46988c849f92e3a13bb1885fba7ff7faed4aff57a2a0e

### `MF-P4-12.07` — P4

- **Current:** `partially_complete` at 64%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 19
- **Requirement:** Pass one representative shard from every lane before expansion · Verify: decode, annotation alignment, schema, provenance, hard QC, strict VLM, repair/abstention, resume, and evidence writing are measured · Blocked by: MF-P4-12.01 through MF-P4-12.06
- **Existing evidence to preserve/revalidate:** runtime_artifacts/nude_corpus_canary_20260722_v2/report.json; qa/live_verification/nude_holdout_policy_v4_rebind_20260722.json; qa/live_verification/nude_polygon_v4_requalification_20260722.json; qa/live_verification/nude_provider_canary_manifest_20260722.json; qa/live_verification/nude_pixel_semantic_visual_evidence_20260722.json; qa/live_verification/nude_batch_milestone_integrity_20260722.json; qa/live_verification/nude_polygon_autotuned_repair_20260722.json; qa/live_verification/nude_label_scale_whole_person_hard_qc_20260722.json; qa/live_verification/nude_yolo_person_detection_canary_20260722.json; qa/live_verification/nude_dual_detector_person_ownership_canary_20260722.json; qa/live_verification/runpod_split_person_recomposition_hard_qa_20260723.json file SHA-256 ff33339afcf250cc4f443cd0959cdde893ae53f1139137945509deaebc9e7ec8 self SHA-256 d75cccf0766c203930b46988c849f92e3a13bb1885fba7ff7faed4aff57a2a0e

### `MF-P4-12.08` — P4

- **Current:** `partially_complete` at 5%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 20
- **Requirement:** Expand progressively to 1,000 records and the full eligible corpus without threshold weakening · Verify: checkpoint/milestone/throughput/GPU reports and zero lost or duplicate decisions · Blocked by: MF-P4-12.07 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** qa/live_verification/nude_batch_milestone_integrity_20260722.json

### `MF-P4-12.09` — P4

- **Current:** `partially_complete` at 30%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 21
- **Requirement:** Publish dataset-level anatomy/action/domain/split/agreement/QC/repair/abstention/certification coverage reports · Verify: report totals reconcile every processed record and cannot hide a failing stratum · Blocked by: MF-P4-12.08
- **Existing evidence to preserve/revalidate:** HARD_QA_PASS_BOUNDED accounting: qa/live_verification/nude_terminal_queue_and_coverage_bridge_20260722.json; real report runtime_artifacts/nude_dataset_coverage_v2_20260722/holdout_complete.json file SHA256 138761e930d47907970a17c82eb64cef9c1faab234c166d34b0eae0618f91bb4 self SHA256 293dc3e193b3567d3e9481f3e8ec105da826041725f2c1d2593a5b171a5d2612. Full population remains open.

### `MF-P4-12.10` — P4

- **Current:** `open` at 0%
- **Source:** `22_ITEMS_P0_ADULT_CORPUS_AUTONOMY.md` line 22
- **Requirement:** Prove one exact real record from `source_reference` through detection, ownership, multi-provider masks, frozen per-label/context QA, qualified independent visual quorum, bounded repair when required, complete-map semantic alignment, immutable `autonomous_certified_gold` package, verification, revocation, and stale-certificate rejection · Verify: clean-checkout source-to-package and revoke/replay tests bind every exact hash and no weaker status or population evidence can promote the record · Blocked by: MF-P2-11.21, MF-P4-11.18, MF-P4-11.19, MF-P4-11.25, MF-P4-12.06 · HARD BLOCKER

### `MF-P4-EXIT` — Phase Exit Gate

- **Current:** `blocked` at 0%
- **Source:** `05_ITEMS_P4_VLM_QA_ACTIVE_LEARNING.md` line 66
- **Requirement:** **D4** demonstrated: VLM reviews + agree/disagree routing correct on the 20-image validation set · mining produced ≥ 1 weekly acquisition plan · doc 14 §5 checkboxes updated
- **Current blocked reason:** NEEDS KEVIN: D4 requires human-anchor calibration, a valid 20-image VLM run, and human second-review evidence; the required anchor set does not yet exist.

### `MF-P6-17.03` — Autonomous mask generation, adjustment, visual QA, and outcomes

- **Current:** `in_progress` at 60%
- **Source:** `23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md` line 54
- **Requirement:** Run exact evidence panels through a qualified high-end primary visual critic and qualified independent-family juror; text-only or correlated critics cannot approve · Verify: positive/negative calibration, disagreement, unavailable, malformed, timeout, and hard-QA-override fixtures fail closed · Blocked by: MF-P6-17.02, existing MF-P4-11.23 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** STATIC_PASS control-plane commit 1780dff94: immutable five-role PNG panel binding, qualified-role certificate validation, independent-family/same-model exclusion, fail-closed response envelopes, hard-QA veto precedence, and deterministic quorum replay. Focused 14 PASS; neighboring autonomy wave 113 PASS, 1 expected Windows symlink skip; Ruff, compileall, and diff-check PASS.

### `MF-P6-17.04` — Autonomous mask generation, adjustment, visual QA, and outcomes

- **Current:** `in_progress` at 55%
- **Source:** `23_ITEMS_P6_SELF_HOSTED_AUTONOMOUS_LLM_OPERATIONS.md` line 55
- **Requirement:** Persist terminal accept/repair/abstain/reject/quarantine outcomes and complete accounting for every mask record · Verify: 100-record campaign reconciles all inputs, outputs, evidence, repairs, critic decisions, and authority limitations with zero loss or duplicate promotion · Blocked by: MF-P6-17.03 · HARD BLOCKER
- **Existing evidence to preserve/revalidate:** STATIC_PASS control-plane commit 759218bc6: immutable accept/repair/abstain/reject/quarantine records, exact input/evidence bindings, no authority or promotion claim, deterministic campaign reconciliation, and a 100-record fixture with 100/100 terminal accounting, zero loss, and zero duplicate promotion. Focused 8 PASS; neighboring autonomy wave 121 PASS, 1 expected Windows symlink skip; Ruff, compileall, and diff-check PASS.

### `MF-P6-21.02` — Evidence reconstruction and integrated mask safety

- **Current:** `open` at 0%
- **Source:** `24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md` line 21
- **Requirement:** Make provider and critic disagreement fail closed as abstain/adjudicate/reject/quarantine, never an implicit pass; preserve hard-QA veto authority · Verify: focused and integrated tests prove disagreement blocks promotion, unqualified/unavailable critics abstain, and unrelated records continue with exact accounting · Blocked by: MF-P6-17.02, MF-P6-20.02 · HARD BLOCKER

### `MF-P6-21.03` — Evidence reconstruction and integrated mask safety

- **Current:** `open` at 0%
- **Source:** `24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md` line 22
- **Requirement:** Bind the current source-qualified 66-class visual gate, exact critic qualifications, and mask-campaign prerequisites into the canonical runtime without duplicating historical campaigns · Verify: missing/stale/historical-only visual evidence blocks promotion and accepted P4/P6 evidence reconstructs from the locator · Blocked by: MF-P4-11.23, MF-P6-17.03, MF-P6-21.01, MF-P6-21.02 · HARD BLOCKER

