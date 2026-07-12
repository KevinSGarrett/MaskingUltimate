# Document 11: Human Review Workflow (CVAT Operator Manual)

The human is the semantic authority. This doc is the complete operator manual: project setup,
SOPs, statuses, hotkeys, second review, and throughput targets.

---

## 1. Review Statuses (per part — manifest `parts.*.status`)

`draft_model_generated → human_corrected → human_approved_gold`
plus `rejected_needs_fix` (bounced by QA or reviewer) and `deprecated` (superseded version).
Package status (SQLite) mirrors the worst part status. Approval order rule: format BLOCKs must be
clear BEFORE approval is possible (packager enforces, doc 09 §5).

Early semantic routes that occur before a full review package exists (currently S02 silhouette
ratio review) return through an immutable reviewer artifact rather than a threshold change. The
operator reviews/corrects the native mask, then runs
`maskfactory review resolve-s02 <image_id> <pN> --mask <png> --reviewer <name>
--decision confirmed_valid|corrected --note <reason>`. The next normal draft run forces S02,
reproduces the exact queued model/config evidence, and applies the reviewed mask only when every
hash, dimension, context boundary, and queue identity still matches. The model QC remains recorded
as failed; separate human semantic authority satisfies the review route. Conflicting, stale, or
tampered resolutions are refused.

## 2. CVAT Project Setup (scripted — `maskfactory cvat init-project`)

- One CVAT project `MaskFactory_body_parts_v1`; labels auto-created from `ontology.yaml` with
  fixed colors (viz.yaml), type=mask, plus attributes: `visibility` (enum, doc 02 §8),
  `ambiguous` (bool), `notes` (text).
- Extra image layers pushed with each task: disagreement heatmap, all-parts overlay (as context
  images), so the reviewer sees contested pixels immediately.
- Tasks = 1 image per job, batched 10 jobs/task; assignee kevin; SAM2 interactor enabled
  (Magic Wand → interactor → SAM2) for click-refine; brush/polygon tools for manual fixes.
- `maskfactory cvat push <ids>` uploads image + draft masks as pre-annotations (RLE);
  `maskfactory cvat pull <ids>` exports corrected masks + attributes back to the package
  (`annotations\cvat_task_backup.zip` retained), then re-fuse + re-QA run automatically.

**AMENDED (doc 17 §9):** for a multi-person image, one CVAT task is created per (image, promoted
instance) — a 2-person image produces 2 review jobs, each showing that instance's own crop and
draft masks exactly like today's single-instance flow — plus one shared "image overview" context
job showing every promoted instance together, specifically for checking interperson contact/
occlusion consistency (SOP-6 below). Single-person images are unaffected: one job, as today.

## 3. SOP-1 — Standard Review Pass (per image)

1. Open job → context overlay: 10-second whole-figure sanity scan (missing parts? obvious L/R?).
2. Work the **careful queue list** (task description auto-lists parts flagged by QC/VLM with
   their correction_instructions) first, then quick-pass parts.
3. Per flagged part: jump to part (label hotkeys 1–9 mapped to most-edited classes), inspect at
   ≥200% zoom on boundaries, fix via SAM2 clicks (positive/negative) or brush; joints/bands:
   verify band sits on the keypoint and touches both segments.
4. Set `visibility` attribute for every part you touch; for honest uncertainty use
   `ambiguous_do_not_use` + note — never guess (constitution).
5. Whole-image final pass at fit-zoom; mark job **completed**.
Time target: 8–15 min standard image; 20–30 min hard image (many flags).

## 4. SOP-2/3/4 — Hard-Class Addenda

- **SOP-2 Hands (mandatory crop review):** open hand crop context; verify handedness vs arm chain
  (follow the arm, not the thumb); check every inter-finger gap is NOT filled; merged fingers →
  hand_base + ambiguous states, never invented splits.
- **SOP-3 Panels first:** for fingers/hair/chest/straps/contact, review the qa_panels\ 5-tile
  panel BEFORE editing — the protected-overlap heat tile shows exactly where bleed is.
- **SOP-4 Chest lane:** always at crop zoom. Verify: skin-visible contour honest; clothed contour
  follows fabric; breast_skin empty when fully clothed (that's correct); projected region edited
  only in the projected layer task (separate CVAT job set, purple labels) — projected never drawn
  in the atomic job.

## 5. SOP-5 — Approval & Packaging

`maskfactory package <image_id>`: re-runs full QA battery → if pass, prompts approval
confirmation → stamps review block (reviewer, timestamps, minutes from CVAT), sets statuses
`human_approved_gold`, freezes package, DVC add. Any BLOCK → package bounces to
`rejected_needs_fix` with the failing panel paths printed.

Post-gold corrections never overwrite the active version in place. Run
`maskfactory correction begin <image_id> --instance <pN>` to create the next `masks@vN`
workspace, edit its authoritative PART/MATERIAL maps through the human review process, then run
`maskfactory correction refresh <image_id> --instance <pN> --version <N>` to regenerate strict
binary views. Finally, `maskfactory correction promote ... --reviewer <name> --minutes <N>`
requires a fresh explicit confirmation, reruns the complete format battery, reseals all derived
artifacts and hashes, DVC-adds the image package, and atomically synchronizes SQLite. The previous
version remains hash-sealed and deprecated for 30 days; any QA, DVC, filesystem, or database
failure restores the pre-promotion package and state exactly.

## SOP-6 — Interperson Contact Review (NEW, doc 17 §9 — multi-person images only)

After each promoted instance's own SOP-1 pass: open the shared image-overview context job →
confirm every `interperson_contact_boundary` band makes sense against the source (an arm really
does cross behind the other person, etc.) → check both involved instances' packages recorded the
relationship reciprocally (QC-037's human-facing counterpart) → fix on either side if only one
recorded it. This is a quick confirmation pass, not a re-annotation — the band geometry itself
comes from S09.5 automatically.

## 6. Second Review (inter-annotator safeguard)

- Sample: 15% of approved packages, stratified to over-sample hard classes (fingers, toes,
  chest boundary, pelvic/waistband, hairline, hand-body contact ×2 weight).
- Performed on a different day (or by Quatavius when onboarded) with fresh eyes; reviewer sees
  panels only first, then full image; verdict pass/fail per sampled part.
- Fail → package demoted to `rejected_needs_fix`, disagreement logged to failure_queue
  (`failure_reason: second_review_fail`), both mask versions kept for the disagreement archive
  `qa\iaa\` (inter-annotator IoU tracked; target ≥ 0.92 on body, ≥ 0.80 fingers).
- Weekly IAA report is a leaderboard input (human consistency bounds model targets).

## 7. Throughput & Capacity Model

| Phase | Automation level | Human min/img | Images/10h week |
|-------|------------------|---------------|-----------------|
| P2 (drafts basic) | parsing+SAM2 drafts | ~25 | ~24 |
| P3 (lanes live) | crop lanes + panels | ~15 | ~40 |
| P5 (custom models) | near-gold drafts | ~8–12 | ~60 |
Reaching G6 (300 gold): ~6–8 weeks of ~10 review-hours/week from P3 onward. Quick-pass queue
discipline (doc 10 §5) is what makes these numbers real — don't re-inspect what QA+VLM+consensus
all cleared beyond the skim.

## 8. Annotator Quality Rules (the honesty contract)

Never label hidden anatomy as visible · never split merged fingers by guess · never "improve" a
boundary beyond what pixels show · when the guideline is ambiguous, follow doc 02 §6 tie-breakers;
if still ambiguous → ambiguous_do_not_use + note (notes feed guideline updates via the ontology
change procedure) · left/right = character, always — when in doubt, trace the limb chain.
