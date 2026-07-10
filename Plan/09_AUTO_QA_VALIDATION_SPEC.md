# Document 09: Automatic QA & Validation Specification

All thresholds live in `configs\qa.yaml` (defaults shown). Severity: **BLOCK** = package cannot
reach gold (human approval cannot override); **ROUTE** = forces careful human review;
**WARN** = recorded, shown in CVAT. Scaled px values use ref long-side 1024 and scale linearly.

---

## 1. Format & Integrity Checks (all BLOCK)

| ID | Check | Rule |
|----|-------|------|
| QC-001 | dimensions_match_source | every mask W×H == source W×H |
| QC-002 | binary_values_only | histogram ∈ {0,255} exactly (except inpaint\, matting\ which are exempt-listed) |
| QC-003 | png_mode | mode L, no alpha, no palette, PNG magic bytes |
| QC-004 | filename_ontology_match | every file maps to an enabled ontology label; no strays |
| QC-005 | manifest_schema_valid | jsonschema pass + invariants (doc 04 §1) |
| QC-006 | hash_integrity | manifest.files hashes match disk |
| QC-007 | map_binary_consistency | regenerating binaries from maps == on-disk binaries (QC-030 alias) |
| QC-008 | required_states_complete | every enabled label has a visibility state |
| QC-009 | derived_not_hand_authored | derived files' recorded formula+input hashes reproduce them |
| QC-010 | crop_transform_valid | transform json schema + bounds inside source |

## 2. Geometric / Semantic Checks

| ID | Check | Rule | Sev |
|----|-------|------|-----|
| QC-011 | atomic_exclusivity | pairwise atomic overlap == 0 px (structural; verify) | BLOCK |
| QC-012 | inside_silhouette | body-part pixels ⊄ person_full_visible ≤ 0.2% of part | ROUTE |
| QC-013 | protected_overlap | part ∩ {background, other_person, face_protected(for non-face parts), occluding_object} ≤ 0.5% part area; skin-derived ∩ clothing == 0 | BLOCK |
| QC-014 | left_right_consistency | part side vs pose skeleton side (limb chain), MediaPipe handedness, DensePose L/R surface — 2-of-3 vote must match label; else fail | BLOCK |
| QC-015 | area_sanity | part area / person bbox area within per-class [min,max] from `ontology.yaml expected_area_pct_range` (e.g. forearm 0.8–4%, finger 0.02–0.5%, thigh 3–12%) | ROUTE |
| QC-016 | visibility_vs_frame | if pose says part's keypoints are outside frame / absent chain → mask must not exist; catches "claims foot but cropped above ankle" | BLOCK |
| QC-017 | components_limit | connected components ≤ ontology max_components (limb 1, hair ≤ 4, torso 1–2 for occlusion splits) | ROUTE |
| QC-018 | crop_roundtrip | crop↔full reprojection IoU ≥ 0.995 | BLOCK |
| QC-019 | breast_skin_identity | derived breast_skin == breast part ∩ material skin (exact) | BLOCK |
| QC-020 | projected_containment | projected regions ⊂ torso region ∪ clothing; never counted as visible truth; no projected file inside masks\ | BLOCK |
| QC-021 | hole_ratio | interior holes ≤ 1% part area (exempt: lace_or_sheer-covered parts, hair) | WARN |
| QC-022 | edge_alignment | mean image-gradient magnitude on mask contour ≥ 0.6 × gradient on a ±3 px band (edges should sit on real edges) | WARN |
| QC-023 | visibility_state_consistency | state visible ⇒ area ≥ 90% amodal est.; partially ⇒ 10–90%; mismatch → fix state or mask | ROUTE |
| QC-024 | front_back_surface | DensePose surface majority matches front/back class (doc 08 §5) | ROUTE |

## 3. Topology / Skeleton Constraints (QC-025 … QC-029, all ROUTE)

Adjacency graph rule: dilate each part 3 px(scaled); required neighbors must intersect.
- QC-025 chain integrity: wrist↔hand_base, elbow↔(upper_arm & forearm), knee↔(thigh & calf),
  ankle↔(calf & foot_base), toes↔foot_base, fingers↔hand_base, neck↔head_face — unless an
  occlusion entry in manifest explains the gap (occluder mask must actually cover the gap band).
- QC-026 finger containment: each finger ⊂ dilate(hand crop region, 10 px); thumb adjacency to
  hand_base mandatory.
- QC-027 band geometry: joint bands intersect both their limb segments; band height within
  ±30% of formula value.
- QC-028 side coherence: all left_* parts' centroids form a consistent side-chain vs skeleton
  (no single part flipped across midline without pose support).
- QC-029 breast position: breast centroids within chest region horizontal band; left/right order
  matches view (mirrored in back-¾ = impossible → fail).

## 4. Consensus & Model-Disagreement Checks

- QC-031 (ROUTE): part disagreement_score > 0.5 over > 3% area → `model_disagreement_high`.
- QC-032 (WARN): SAM2 predicted_iou < 0.5 (`sam2_low_conf`).
- QC-033 (ROUTE): parsing_degraded or pose_degraded flags set.
- QC-034 (BLOCK): iou_vs_previous_gold < 0.5 when re-processing an image that already has gold
  (regression guard for pipeline changes).

## 4.5 Multi-Person Checks — AMENDED, doc 17 §7 (multi-person images only)

| ID | Check | Rule | Sev |
|----|-------|------|-----|
| QC-035 | instance_silhouette_exclusivity | no two promoted instances' silhouettes overlap IoU > `instance_overlap_max` (0.3) — catches a real person falsely split into two instances | **BLOCK** |
| QC-036 | cross_instance_bleed | instance i's atomic masks must not extend into a pixel region confidently owned by a *different* promoted instance's silhouette core, beyond the shared `interperson_contact_boundary` band | **BLOCK** |
| QC-037 | interperson_contact_reciprocity | if instance A records a contact/occlusion relationship with instance B, instance B's package must record the reciprocal | ROUTE |
| QC-038 | instance_count_sanity | promoted-instance count matches S01's ranked output and the configured cap | WARN |

QC-035/036 are hard blockers — the direct multi-person analogue of QC-011 (exclusivity) and
QC-013 (protected overlap). Computed by S09.5 (doc 07), evaluated at S10 alongside every other
check in this document.

## 5. Metrics (per part, stored in qa_report.metrics_per_part)

- `iou_vs_consensus`, `iou_vs_previous_gold_or_model`
- `boundary_f_2px` (BoundaryF: precision/recall of contour pixels within 2 px(scaled) tolerance)
- `hausdorff_95` (optional, hard classes) — 95th-percentile symmetric contour distance
- `hole_ratio`, `components`, `mask_area_px`, `mask_bbox`
- `disagreement_score` (doc 08 §7)
- `overlap_with_protected_regions`, `overlap_with_mutually_exclusive_parts` (should be 0)
Package `qa_score` = weighted mean of per-part normalized metrics (weights per class tier in
qa.yaml: fingers/hair/chest ×2). Human review status is stored alongside — **a human approval
never overrides a BLOCK**; the packager re-runs the battery at approval time.

## 6. Boundary Zoom QA Panels (auto-generated, `qa_panels\`)

For every hard-class mask (fingers, toes, hair, breasts/chest boundary, straps, belly_button,
contact regions, occlusion edges) generate a 5-tile panel PNG:
`[source crop | mask-only | overlay | contour-on-source | protected-neighbor overlap heat]`
at 2× zoom of the part bbox. Panels are the units the VLM reviews (doc 10) and the first thing
the human sees in the review checklist (doc 11 SOP-3). Panel spec (tile size 512, layout, colors)
in `configs\viz.yaml`.

## 7. Auto-Fix Policy (before failing)

Deterministic fixes attempted once, logged, then re-checked: regenerate binaries from maps
(QC-007), drop sub-threshold components (QC-017), fill sub-threshold holes (QC-021), re-derive
unions (QC-009). Anything else → human. No silent geometry edits beyond these listed operations.
