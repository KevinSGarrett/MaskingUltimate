# ITEMS — Phase P8: Multi-Person / Multi-Character Masking (NEW)

Goal: activate true multi-instance execution on top of the already-proven single-instance
system, so photos with 2 to `max_instances_per_image` people get correctly-instanced, non-
bleeding certified or residual human-anchor truth for every promoted person. Parent IDs from doc 14 §11. Governing specs: doc 17 as amended by docs 20/22.
(complete decision record) — every cluster below cites the exact doc 17 section.

**Entry gate:** P7 substantially complete (D1–D10 satisfied). This phase generalizes a working
system; it is not a from-scratch parallel build.

## MF-P8-01 — Activate multi-instance S01 loop (spec: 17 §4–5)
- [ ] MF-P8-01.01 Implement orchestrator outer loop: for each promoted instance from S01's ranked output, run S02→S09 scoped to that instance's own crop
- [ ] MF-P8-01.02 Wire per-instance `other_person_protected`: every other detected person (promoted or not) visible in instance i's crop is masked as PART 50 for that specific run, recomputed fresh each iteration
- [ ] MF-P8-01.03 Multi-instance fixture set (2–3 test images with known, hand-verified instance counts) — orchestrator produces exactly N packages for N promoted people
- [ ] MF-P8-01.04 Regression check: existing single-person fixtures (from P1–P7) still produce exactly one `p0` package, byte-identical to pre-P8 pipeline output

## MF-P8-02 — S03/S04 co-subject disambiguation (spec: 17 §5)
- [ ] MF-P8-02.01 Implement bbox/silhouette match: assign each parsing/pose detection to its nearest promoted-instance bbox
- [ ] MF-P8-02.02 Suppress non-matching detections before they reach S05 geometry-engine priors
- [ ] MF-P8-02.03 Seeded 2-person crop fixture: confirm zero cross-contamination (instance 0's priors never include instance 1's limbs)
- [ ] MF-P8-02.04 Handle genuine ambiguity (two people very close/overlapping in the crop) via `ambiguous_do_not_use` rather than a forced guess — consistent with the project's never-guess principle (doc 08 §2.6 precedent)

## MF-P8-03 — S09.5 Instance Reconciliation stage (spec: 17 §5–6)
- [ ] MF-P8-03.01 Implement cross-instance silhouette-overlap check (`instance_overlap_max` = 0.3 IoU default)
- [ ] MF-P8-03.02 Implement `interperson_contact_boundary` band computation, injected into both involved instances' own `masks_regions\`
- [ ] MF-P8-03.03 Implement `image_manifest.json` writer: `promoted_instances`, `background_person_count`, `crowd_scene`, `interperson_relationships[]`
- [ ] MF-P8-03.04 Seeded false-split fixture (two heavily-overlapping detections simulating one real person mis-split) correctly triggers the overlap check
- [ ] MF-P8-03.05 Seeded genuine-contact fixture (two people, arm around shoulder) produces reciprocal bands in both packages

## MF-P8-04 — Package layout + image_manifest.json live (spec: 17 §6, 03 §2)
- [ ] MF-P8-04.01 Implement `instances\pN\` nesting in the packager (extends the existing single-instance packager from P1, per the instance-aware-from-day-one bake-in)
- [ ] MF-P8-04.02 Verify manifest schema amendment is live: per-instance `interperson[]` field populated correctly (doc 04 §1)
- [ ] MF-P8-04.03 Round-trip test: build a multi-instance package → `verify-package` on every instance folder → all pass
- [ ] MF-P8-04.04 Confirm single-person packages remain the trivial N=1 case — no regression on any P1–P7 fixture or existing gold

## MF-P8-05 — QC-035…038 implemented (spec: 17 §7, 09 §4.5) — HARD BLOCKER (QC-035/036)
- [ ] MF-P8-05.01 Implement QC-035 `instance_silhouette_exclusivity` (BLOCK)
- [ ] MF-P8-05.02 Implement QC-036 `cross_instance_bleed` (BLOCK)
- [ ] MF-P8-05.03 Implement QC-037 `interperson_contact_reciprocity` (ROUTE)
- [ ] MF-P8-05.04 Implement QC-038 `instance_count_sanity` (WARN)
- [ ] MF-P8-05.05 Seeded fixture per QC-035/036/037/038 — pytest confirms each trips exactly its check, none other
- [ ] MF-P8-05.06 Confirm QC-035/036 cannot be overridden by human approval — same non-overridable BLOCK mechanism as every existing hard blocker (doc 09 §5); enforcement test, not just documentation

## MF-P8-06 — Multi-instance CVAT workflow (spec: 17 §9, 11 SOP-6)
- [ ] MF-P8-06.01 Extend `cvat push` to create one task per (image, promoted instance)
- [ ] MF-P8-06.02 Implement the shared "image overview" context job showing every promoted instance together
- [ ] MF-P8-06.03 Extend `cvat pull` to route corrected masks back to the correct instance's own package
- [ ] MF-P8-06.04 Author SOP-6 operator checklist for interperson contact review (doc 11 amendment already specifies the content; wire it into the actual task description template)
- [ ] MF-P8-06.05 2-person fixture produces exactly 2 instance jobs + 1 overview job in CVAT, verified end-to-end

## MF-P8-07 — Split-integrity CI test (spec: 17 §8, 12 §1) — HARD BLOCKER
- [ ] MF-P8-07.01 Implement the dedicated test: assert no `image_id` has instances split across train/val/test/hard_case_holdout
- [ ] MF-P8-07.02 Deliberately-broken dataset-builder fixture (one that buckets by instance_id instead of image_id) confirmed to FAIL this test
- [ ] MF-P8-07.03 Wire this test into the same CI gate as the existing flip/swap_partner test (MF-P5-02.02) — blocks all training-related merges

## MF-P8-08 — Coverage matrix + leaderboard instance-context dimension (spec: 17 §8, 04 §5, 12 §10)
- [ ] MF-P8-08.01 Add the `solo | duo | small_group` dimension to `coverage_matrix.json` + `coverage report`
- [ ] MF-P8-08.02 Extend `leaderboard.jsonl` schema + reporting to include the instance-context breakout alongside the pooled score
- [ ] MF-P8-08.03 Verify existing single-person leaderboard rows are unaffected — backward compatible, all default to `solo`

## MF-P8-09 — ComfyUI `person_index` parameter (spec: 17 §11, 13 §2)
- [ ] MF-P8-09.01 Add optional `person_index` input (default 0) to every relevant MaskFactory node
- [ ] MF-P8-09.02 Update Package Browser to list `(image_id, person_index)` pairs
- [ ] MF-P8-09.03 Regression test: existing single-person workflows re-run byte-identical with the new default parameter present
- [ ] MF-P8-09.04 New multi-instance workflow test: correctly loads instance p1's masks from a 2-person package

## MF-P8-10 — First real multi-person certified/residual evidence set (spec: 17 §14; 20 §§5–6; 22 §5)
- [ ] MF-P8-10.01 Curate/collect 10–20 real 2–4-person images with generated/owned/licensed/consented provenance
- [ ] MF-P8-10.02 Run the full activated pipeline end-to-end on this set
- [ ] MF-P8-10.03 Automatically accept only certificate-covered instances; route residual cases and preselected audits through SOP-1–SOP-6 without routine CVAT review of every instance
- [ ] MF-P8-10.04 Confirm QC-035/036 clean on every autonomous-certified or human-anchor package in this set
- [ ] MF-P8-10.05 Record **D11** demonstration evidence; measure **G9** (cross-instance bleed rate — target 0)
- [ ] MF-P8-10.06 Update tier-separated metrics per instance: human-anchor partitions, autonomous-certified, pseudo, and machine candidates; each instance counts once in its own tier and only active certified tiers satisfy volume gates

## P8 Exit Gate
- [ ] MF-P8-EXIT **D11/G9** hold on real multi-person images (not just synthetic fixtures) · doc 00 §4 and doc 01 §3 both reflect this as demonstrated · doc 14 §11 checkboxes updated
