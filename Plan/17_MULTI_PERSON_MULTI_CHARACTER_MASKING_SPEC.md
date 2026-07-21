# Document 17: Multi-Person / Multi-Character Masking Specification

> **Completion-profile scope (doc 24):** multi-person instance ownership, cross-instance protection,
> transforms, hard QA, bounded repair/abstention, operational certification, and bridge qualification
> are required core behavior. Human review, CVAT, human-approved gold, training-data expansion, and
> population-accuracy claims are optional-profile branches and cannot block core completion.

**Amends and extends documents 00–16** (including doc 16's External Foundation Bootstrap work,
which this document does not otherwise touch). This document is the single authoritative spec for
processing images containing **more than one person**, promoting every sufficiently-prominent
person to a fully-masked "instance" rather than treating everyone but one primary subject as a
single exclusion blob. Where this document's decisions touch an existing doc, that doc carries a
short pointer note at the relevant section; this document holds the full decision.

---

## 1. Why This Exists, and What Changed

The original v1 scope (doc 01 §4 item 1, §5) explicitly limited the system to **one primary
person per image**, with every other visible person collapsed into the `other_person` protected
class (doc 02 PART id 50) — masked only enough to prevent bleed, never given their own atomic
parts. That decision is now **superseded**: multi-character masking is in scope, and is treated
with the same rigor as every other capability in this project — full ontology, full autonomous QA,
instance ownership, repair/abstention, certification, and bridge implications. Optional human review
and training-data implications remain fully specified without becoming core gates.

This document does **not** throw out the single-person work. It generalizes it. The core
insight that makes this tractable: **a multi-person image is processed as N independent
single-person pipeline runs, one per promoted person, each reusing the entire existing
single-person machinery unchanged** — with a small, consistent thread of "who is my target, and
who is everyone else" running through the early stages. Nothing about SAM2 refinement, the
geometry engine, the specialist lanes, or the QA battery needs to know it's processing "instance 1
of 3" versus "the only person in the photo."

## 2. Scope Statement (Honest Boundaries)

**In scope, fully:** photos containing **2 to `max_instances_per_image`** (config, default 4)
clearly visible, sufficiently prominent people — duos, small groups, family-photo-scale scenes.
Every promoted person gets the complete treatment for the package ontology: all 56 v1 PART IDs
while `body_parts_v1` is active, or all 65 after a `body_parts_v2` package has passed the doc-18
review/activation gates; all specialist lanes, the full QA battery (plus the new checks in §7),
VLM review, CVAT human review, and inclusion in
the training dataset.

**Explicitly still out of scope, with a documented threshold rather than an ambiguous failure
mode:** dense crowd scenes. An image with more than `crowd_scene_threshold` (config, default 8)
total detected people is quarantined as `crowd_scene_out_of_scope` rather than partially
processed — reviewing N people's masks per image scales annotation cost roughly linearly with N,
and crowd-scale review economics are a genuinely different problem from "a photo of 2–4 people,"
deserving its own future evaluation (tracked as a v3 horizon, not silently attempted here).
**Also unchanged:** "character" in this document means a human subject, exactly as it means
throughout docs 01–15 — this does not introduce non-human/creature ontology, which would be a
separate, larger scope decision.

## 3. Terminology

- **Person instance**: one distinct human subject in a source image that receives full
  atomic-part mask treatment.
- **`person_index`**: 0-based integer, unique within an `image_id`, assigned by a deterministic
  ranking rule (§4). `person_index=0` is always the top-ranked instance — this preserves a stable,
  canonical ordering and makes every existing single-person image (the overwhelming majority of
  what's already been built and will continue to be built) the trivial N=1 case of this same
  scheme.
- **`instance_id`**: `<image_id>_p<person_index>` (e.g. `img_a3f9c2e17b04_p0`,
  `..._p1`). This is the new unit of "one fully-processed package."
- **Promoted instance**: a detected person ranked within the top `max_instances_per_image` by the
  selection score, who therefore receives full pipeline treatment.
- **Background `other_person_protected`**: any detected-but-not-promoted person, OR — critically —
  during the processing of **any one** promoted instance's own pipeline run, **every other**
  person visible within that instance's crop (including other promoted instances!) is treated as
  `other_person_protected` for that specific run. This is the existing PART-50 mechanism
  (doc 02), just applied fresh per instance-run rather than globally-once.
- **Co-subject**: informal term for "another promoted instance visible within this instance's
  crop" — used in QA/review messaging, not a new PART id.
- **Interperson contact/occlusion boundary**: a new region-band (mask_type `region_band`, see
  §5) marking pixels where two *different* promoted instances visibly touch or occlude one
  another (an arm around a shoulder, one person standing in front of another).

## 4. Person Detection, Ranking & Promotion Policy — Amends doc 07 S01

S01 already detects every person bbox in frame (unchanged capability). The amendment:

1. Score **every** detected person using the existing metric (doc 07 S01: silhouette area ×
   centeredness) — no new metric invented.
2. Apply a minimum-prominence floor: bbox area ≥ `instance_min_area_pct` (config, default 4% of
   frame area). Persons below this floor are never promoted — they're too small/marginal to be
   worth full instance treatment and become background `other_person_protected` candidates.
3. Rank the remaining persons by score; the top `max_instances_per_image` (default 4) are
   **promoted**, assigned `person_index` 0..N-1 by descending score. Deterministic tie-break:
   left-to-right reading order of bbox center-x (preserves G8 reproducibility — same image, same
   assignment, every run).
4. Total raw detections > `crowd_scene_threshold` (default 8) → the **whole image** is
   `quarantined(crowd_scene_out_of_scope)`, no partial promotion attempted (§2).
5. Zero persons passing the prominence floor → unchanged existing path,
   `rejected(no_person)`.
6. Non-promoted persons who still pass the prominence floor (i.e. ranked 5th+ when the cap is 4)
   are **not quarantined** — the image is processed normally for its top-4 promoted instances;
   the extra people are simply `other_person_protected` background for every promoted run.

## 5. Per-Instance Pipeline Execution & the New S09.5 Stage — Amends doc 05, doc 07

Per image, the orchestrator now runs:

1. **S01** (amended, §4): detect, score, rank, promote instances 0..N-1.
2. **For each promoted instance i, in order:** run **S02 through S09** exactly as already
   specified in doc 07, scoped to instance i's own crop (bbox × padding, same convention as
   today). Within this run: every *other* detected person (promoted or not) whose silhouette
   falls even partially inside instance i's crop is masked as `other_person_protected`.
   - **S02 (silhouette), S05 (geometry engine), S06 (GDINO), S07 (SAM2 refinement), the
     specialist lanes (doc 08), and S09 (fusion)** require **no internal logic changes** — they
     already operate on "the" person within a crop; they now simply run once per promoted
     instance instead of once per image.
   - **S03 (parsing) and S04 (pose)** need one small, honest addition: when a co-subject is
     partially visible within instance i's crop, the stage must identify *which* detected human
     each parsing/pose result belongs to (by bbox/silhouette match against instance i's own
     defining bbox) and suppress any detection belonging to a different person before it can
     leak into instance i's own priors. This is the one place real (small) engineering work is
     needed beyond "run it again" — everywhere else, the existing machinery is reused unchanged.
3. **S09.5 — Instance Reconciliation (NEW, runs once per image, after all promoted instances
   complete their own S09):**
   - Cross-instance silhouette-overlap check: no two promoted instances' final silhouettes may
     overlap beyond a small threshold (`instance_overlap_max`, default IoU 0.3) — this catches
     the real failure mode of one actual person being falsely split into two instances by a
     detection error. Feeds QC-035 (§7).
   - Computes and injects the `interperson_contact_boundary` band (§3, §6) into **both** involved
     instances' own packages, from each instance's own perspective.
   - Writes the preliminary `image_manifest.json` (§6) indexing all promoted instances and any
     background-person count.
   - This runs **before** S10 auto-QA specifically so a bad instance split is caught by an
     automatic check before any VLM or human review time is spent on it.
4. **S10 → S13** (auto-QA, VLM QA, CVAT, gold export) run per promoted instance as already
   specified, with the amendments in §7 (new QA checks) and §9 (CVAT workflow).
5. **S00 (intake)** applies the uniform source-admission contract once to the whole source image
   before person detection. Provenance, rights/allowed-use, integrity, and intake outcome are
   inherited by every promoted instance.
6. **S14/S15** (dataset build, active learning) are amended in §8 — critically, the dataset split
   is computed per **image**, never per **instance**.

## 6. Ontology & Package/Manifest Amendments — Amends doc 02, doc 03, doc 04

- **No instance-specific atomic PART or MATERIAL IDs.** Multi-person support itself adds no
  labels. Each instance uses one complete declared ontology: 56 PART IDs / 16 MATERIAL IDs for
  v1, or the append-only 65 PART IDs / same 16 MATERIAL IDs for v2 (doc 18). A left hand is a
  left hand whether it belongs to instance 0 or instance 1; versions may not mix within an image.
- **Clarification, not a new ID:** PART 50 (`other_person`) / MATERIAL 13
  (`other_person_material`) now explicitly mean "any human visible in *this instance's* crop who
  is not this instance" — true whether that other human is a promoted instance processed
  separately in their own right, or a non-promoted background person.
- **New region-band registry entry** (doc 02 §4 mechanism, no new mechanism):
  `interperson_contact_boundary` — pixels where two *different* promoted instances' bodies
  visibly touch or occlude each other. Same band-width convention as the existing
  `body_contact_region` (8 px @1024 ref, scaled).
- **New package layout** (extends doc 03 §2, fully backward compatible — see §11):
  ```
  data\packages\<image_id>\
    image_manifest.json                 <- NEW, image-level index (below)
    instances\
      p0\   <- structurally IDENTICAL to today's single-instance package layout:
              source-crop ref, label_map_part.png, label_map_material.png, masks\,
              masks_regions\, masks_derived\, projected\, inpaint\, protected\, matting\,
              overlays\, qa_panels\, crops\, annotations\, manifest.json, qa_report.json
      p1\   <- same structure, second promoted instance
      ...
  ```
- **`image_manifest.json`** (new, small, one per image):
  ```jsonc
  {
    "image_id": "img_a3f9c2e17b04",
    "source_file": "source.png",
    "promoted_instances": ["p0", "p1"],
    "background_person_count": 1,
    "crowd_scene": false,
    "interperson_relationships": [
      { "a": "p0", "b": "p1", "relationship": "contact",
        "contact_band_file_a": "instances/p0/masks_regions/interperson_contact_boundary.png",
        "contact_band_file_b": "instances/p1/masks_regions/interperson_contact_boundary.png" }
    ],
    "created_at": "..."
  }
  ```
- **Per-instance `manifest.json`** (doc 04 §1) gains one new field: `interperson: []`, an array
  of `{other_instance_id, relationship, contact_band_file}` objects — the per-instance mirror of
  the relationship recorded at the image level.

## 7. New / Amended QA Checks — Amends doc 09

Continuing the existing QC-001…034 numbering:

| ID | Check | Rule | Severity |
|----|-------|------|----------|
| QC-035 | instance_silhouette_exclusivity | No two promoted instances in one image have silhouette IoU > `instance_overlap_max` (0.3) | **BLOCK** |
| QC-036 | cross_instance_bleed | Instance i's atomic masks must not extend into a pixel region confidently owned by a *different* promoted instance's silhouette core, beyond the shared `interperson_contact_boundary` band | **BLOCK** |
| QC-037 | interperson_contact_reciprocity | If instance A records a contact/occlusion relationship with instance B, instance B's package must record the reciprocal entry | ROUTE |
| QC-038 | instance_count_sanity | Promoted-instance count matches S01's ranked output and the configured cap; flags if an instance silently disappeared mid-pipeline | WARN |

QC-035 and QC-036 are **hard blockers** — the direct multi-person analogue of the existing
single-person exclusivity (QC-011) and protected-overlap (QC-013) checks, which are already
foundational, non-overridable BLOCKs. A silent cross-instance bleed is exactly the kind of
mistake that quietly poisons a dataset the way an undetected L/R swap does; it gets the same
absolute treatment.

## 8. Dataset, Training & Split-Integrity Amendments — Amends doc 12 (CRITICAL)

- **The train/val/test split, and `hard_case_holdout` membership, is computed on `image_id`,
  never on `instance_id`.** All promoted instances from the same source image land in the
  **same** split. Splitting a photo's two people across train and test would leak
  shared background/lighting/context across the holdout boundary — exactly the kind of subtle
  correctness bug this project's whole "no open questions" philosophy exists to prevent.
- This is enforced the same way the flip/swap_partner rule is enforced (doc 12 §4, a hard-blocker
  CI test): a dedicated test asserts no `image_id` has instances split across different dataset
  partitions. Any dataset builder change that could violate this is blocked from merging.
- **Coverage matrix** (doc 04 §5) gains an instance-count dimension alongside the existing
  view×pose×attribute cells: `solo | duo | small_group`, so multi-person scenes get their own
  coverage targets rather than being invisibly folded into single-person cells.
- **Leaderboard reporting** (doc 12 §10): per-part IoU/boundary-F is reported **both** pooled
  across all instances (directly comparable to existing single-person baselines) **and** broken
  out by instance-context (solo vs. multi-person-scene), since a model might perform differently
  on isolated crops versus crops containing nearby `other_person_protected` regions and contact
  bands.

## 9. Human Review Workflow Amendments — Amends doc 11

- **One CVAT task per (image, promoted instance)** — a 2-person image produces 2 review jobs,
  each showing that instance's own crop and draft masks, exactly like today's single-instance
  review — **plus** one shared "image overview" context job showing all instances together (the
  existing "context image / all-parts overlay" mechanism, doc 11 §2, extended to show every
  promoted instance in one frame) specifically for checking interperson contact/occlusion
  consistency.
- **New short SOP** (SOP-6): reviewing interperson contact bands — confirm both involved
  instances' packages agree on the contact zone (QC-037's human-facing counterpart).

## 10. VLM QA Note — Light Touch on doc 10

No structural change. One addition: when a panel is generated for a promoted instance in a
multi-person image, the VLM prompt context includes "this panel is for person N of M in this
image" so its reasoning about `other_person_protected` regions in the crop isn't confused by the
presence of visible co-subjects. Doc 06 (environment) requires **no amendment at all** — no new
model or checkpoint is needed; S01's existing detector already finds multiple people.

## 11. ComfyUI Integration Amendments — Amends doc 13

- Every "Load ___ Mask" node gains an optional `person_index` input, **defaulting to 0** — every
  existing single-person workflow keeps working with zero changes.
- The Package Browser node lists `(image_id, person_index)` pairs once multi-instance packages
  exist.

## 12. Backward Compatibility & Migration

Nothing has been built yet as of this document's writing — **this is adopted from the very
start, at zero migration cost.** A single-person image is simply the degenerate N=1 case: one
`instances\p0\` folder (structurally identical to what doc 03 already fully specifies) and a
trivial `image_manifest.json` with `promoted_instances: ["p0"]`. Every single-person item already
in `Plan\Items\01`–`07` remains valid exactly as written; they build the p0 path. Nothing about
this document requires reworking already-completed work, because no work has been completed yet.

## 13. Phased Build Strategy — Amends doc 14

- **P0:** unchanged — pure environment setup, instance-agnostic.
- **P1:** amend the ontology-generation, manifest-schema, and package-layout items to bake in
  the `instances\pN\` structure and `image_manifest.json` from the start (§6), even though only
  p0 will be exercised until Phase P8 activates true multi-instance execution. Zero extra cost
  now; avoids any future breaking migration.
- **P2:** amend the S01 item to implement the full ranking/promotion/prominence-floor logic
  (§4) — even though, until P8, the orchestrator still only *processes* `person_index=0`. S01
  computes and records every detected person's rank regardless; P2 doesn't yet loop over them.
- **P3–P7:** **no changes.** They build out the single-instance (p0) path in full, exactly as
  already specified — the instance wrapper is transparent to them.
- **New Phase P8 — Multi-Person / Multi-Character Masking:** activates the true multi-instance
  outer loop, S09.5 instance reconciliation, QC-035…038, the multi-instance CVAT workflow, the
  split-integrity enforcement, and the ComfyUI `person_index` selector. **Entry gate:** P7
  substantially complete (the single-instance system is proven — D1–D10 satisfied) — because P8
  is explicitly a generalization of an already-working system, not a from-scratch parallel build.
  Full task breakdown: `Plan\Items\10_ITEMS_P8_MULTI_PERSON_MASKING.md`. This P7/D1–D10 entry gate
  governs the legacy portfolio-scale P8 lane only. The bounded autonomous single-/multi-person core
  qualification in doc 24 and `MF-P6-12.03` has no P7, package-volume, CVAT, or human-review
  prerequisite.

## 14. Optional Multi-Person Accuracy/Scale Definition of Done and Goal

**Completion-profile scope (doc 24 supersession):** D11, G9, human-approved counting, and the
≥200/≥300/500 milestones below are retained for optional `independent_real_accuracy` and
`scale_daz_maturity` claims. They do not define, block, or revoke `core_autonomous_runtime`. Core
multi-person completion instead requires the autonomous ownership, transform, hard-QA,
repair/abstention, exact-output certification, and adopted bridge demonstrations in doc 24.

- **D11:** A photo containing 2 to `max_instances_per_image` people produces correctly-instanced,
  non-cross-bleeding, QA-passing gold packages for every promoted person, with interperson
  contact/occlusion correctly and reciprocally handled.
- **G9:** Multi-person correctness — cross-instance bleed rate in approved multi-person gold.
  Target: 0 (hard gate, same zero-tolerance spirit as G5's left/right rule).
- **Optional-profile counting convention:** each promoted instance that reaches
  `human_approved_gold` counts as
  **one unit** toward `metrics.approved_gold_count`, Goal G6, and DoD D5 — a 3-person image, once
  all 3 instances are approved, contributes 3, not 1. This is consistent with each instance being
  a genuinely complete, independent set of atomic masks (doc 17 §6), and keeps the existing
  ≥200/≥300/500 targets meaningful without a separate multi-person accounting scheme.

## 15. New Risk Register Entry — Amends doc 15 §1

| ID | Risk | L | I | Mitigation | Trigger/Owner |
|----|------|---|---|------------|---------------|
| R18 | Instance mis-split (one real person falsely detected as two) or cross-instance mask bleed | M | H | QC-035/036 hard BLOCKs, deterministic ranking/tie-break, S09.5 reconciliation runs before any review time is spent | any QC-035/036 fire on approved gold = incident, doc 15 §8-style |
