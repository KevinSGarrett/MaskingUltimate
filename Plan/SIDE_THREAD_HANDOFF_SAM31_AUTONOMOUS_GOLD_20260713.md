# MaskFactory SAM 3.1 Modernization and Autonomous-Gold Handoff

**Created:** 2026-07-13
**Purpose:** Self-contained handoff from the SAM 3.1/autonomous-gold side conversation to the main implementation session.
**Status:** User-approved implementation mandate; this file is a handoff, not completion evidence.
**Important:** Preserve and reconcile all existing uncommitted work. Do not reset, discard, or overwrite unrelated changes.

## Main-session directive

Fully execute the approved SAM 3.1 modernization, private-personal-noncommercial license correction,
and autonomous-certified-gold redesign. Preserve existing work; implement and verify every required
plan, item, tracker, code, configuration, schema, test, runtime, model-registry, CVAT, training,
serving, benchmark, rollback, and operations change. Continue autonomously until blocked only by a
genuinely required Kevin action. Never claim completion or performance without specific evidence.

## User-confirmed operating profile

MaskFactory is exclusively:

- private and local;
- for Kevin's personal use;
- noncommercial;
- not distributed, shared, sold, hosted as a public service, or planned for any of those uses.

The project must stop treating "production" as meaning commercial deployment. In project documents,
`production` means only the active local MaskFactory path.

Add the following policy fields to the external-source and model registries and enforce them in
validation:

```yaml
use_profile: private_personal_noncommercial
distribution_allowed: false
commercial_deployment: false
content_compatibility:
  adult_nonexplicit: allowed | prohibited | unclear
  consensual_explicit_adult: allowed | prohibited | unclear
```

Noncommercial licenses are not blockers under this operating profile when their other terms permit
the intended local use. Exact license text, source, version, and content restrictions must still be
recorded. Do not infer that "noncommercial" also means adult-content compatible.

## Content and model decisions

### Hard exclusion

- **Do not install, register, benchmark, or use Sapiens2 in an adult/explicit MaskFactory path.** Its
  license prohibits pornographic use regardless of whether the use is commercial. Official source:
  <https://github.com/facebookresearch/sapiens2/blob/main/LICENSE.md>.

### Retained and newly required providers

- Retain original Sapiens 0.6B for private noncommercial use. It is the original CC-BY-NC Sapiens,
  not Sapiens2. Source: <https://github.com/facebookresearch/sapiens>.
- Retain and benchmark RMBG-2.0 for private noncommercial use. Source:
  <https://huggingface.co/briaai/RMBG-2.0>.
- Retain SAM 2.1 as incumbent, CVAT editor, measured baseline, fallback, and rollback provider.
- Add official SAM 3.1 as a first-class challenger for concept discovery, text/exemplar prompting,
  exhaustive instance discovery, point/box/mask refinement, repair proposals, and CVAT assistance.
  Source: <https://github.com/facebookresearch/sam3>.
- Optionally screen SAM3-LiteText as a lower-memory experiment, never as a silent substitute for the
  official SAM 3.1 checkpoint.
- Add RF-DETR as the preferred modern person-detector challenger to YOLO11. Keep YOLO11 as incumbent;
  YOLO26 may be benchmarked under the private-local AGPL profile.
- Add RTMW-X as the whole-body pose challenger and RTMO for crowded scenes; retain DWPose incumbent.
- Retain MediaPipe Hands as an independent handedness and landmark vote.
- Add SAM 3D Body as the primary modern challenger to DensePose; retain DensePose as legacy fallback.
- Benchmark BiRefNet Dynamic, HR, and HR-matting against the current BiRefNet-general and ViTMatte
  paths.
- Add Qwen3-VL 4B and a feasible quantized 8B variant as challengers to Qwen2.5-VL. Retire LLaVA only
  after a measured replacement win.
- Retain SegFormer and Mask2Former training baselines. Add EoMT with DINOv3 as the modern custom-model
  challenger.
- Retain the original local GroundingDINO only as a fallback. Do not replace an offline reproducible
  role with a paid hosted GroundingDINO API.
- Upgrade CVAT 2.24 through a parallel, backed-up, rollback-tested migration to the current validated
  stable release; never destructively upgrade the only working deployment.
- Keep the proven PyTorch 2.11/cu128 core unless a measured compatibility need requires change. Use
  isolated environments for SAM 3.1, Qwen3-VL, RF-DETR, EoMT/DINOv3, and other incompatible stacks.

## Provider-neutral target architecture

Do not mechanically rename SAM2 identifiers to SAM3. Introduce provider contracts and retain legacy
manifest compatibility:

- `PersonDetector`
- `ConceptDetector`
- `InteractiveSegmenter`
- `GeometryProvider`
- `PoseProvider`
- `SilhouetteProvider`
- `VlmReviewer`

Target flow:

```text
RF-DETR / SAM 3.1 discovery
  -> person, part, garment, accessory, and repeated-instance proposals
  -> SAM 3.1 or SAM 2.1 refinement
  -> RTMW + MediaPipe + SAM 3D Body geometry
  -> BiRefNet Dynamic/HR silhouette and matting
  -> provider-neutral fusion and hard QA
  -> Qwen3-VL semantic criticism and autonomous repair
  -> autonomous certification or residual human audit
  -> custom EoMT/DINOv3, SegFormer, and Mask2Former tournament
  -> role-specific champions with one-command rollback
```

## Autonomous-gold redesign

The existing autonomy implementation is real but its present authority contract conflicts with the
near-zero-human-work objective. It currently requires at least 300 human-audited accepted cases per
label/context certificate, reserves all gold authority for humans, keeps machine labels out of project
gold counts, requires 200 human-approved packages for P5, and requires manual CVAT approval across P8.
This can create thousands of manual reviews and must be corrected without falsifying truth provenance.

### Required truth tiers

Add and schema-validate these distinct tiers:

| Tier | Meaning | Permitted use |
|---|---|---|
| `human_anchor_gold` | Small, stratified, carefully audited reference truth with explicit `train`, `calibration`, or `holdout` partition | Weight 1.0 only for the training partition; calibration and holdout partitions never train |
| `autonomous_certified_gold` | Multi-provider winner satisfying an active risk certificate and every hard gate | Production training and dataset-volume gates; initial weight 0.5-0.75 |
| `weighted_pseudo_label` | Useful machine label without full certification | Train only at weight 0.1-0.25 |
| `machine_candidate` | Uncertain, vetoed, out-of-distribution, or unresolved result | Repair or residual review only |

Never rename machine truth `human_approved_gold`. Keep authority explicit in manifests, indexes,
leaderboards, datasets, serving output, and ComfyUI metadata.

### Autonomous certification requirements

A mask may become `autonomous_certified_gold` only when all applicable checks pass:

1. Candidate sources represent genuinely different model families; correlated SAM variants do not
   count as fully independent providers.
2. The blinded tournament includes available SAM3.1, SAM2.1, parsing, custom champion, silhouette,
   geometry, specialist, and deterministic-repair candidates.
3. Strict format, dimensions, hashes, topology, components, ontology, exclusivity, protected-region,
   handedness, front/back, and visibility checks pass.
4. Multi-person masks pass instance exclusivity, zero cross-person bleed, and reciprocal contact or
   occlusion checks.
5. The candidate is stable under resize, crop, color, prompt, and flip-with-swap-partner perturbations.
6. Independent masks and boundaries meet risk-bucket agreement thresholds.
7. Qwen3-VL and every enabled eligible independent critic find no blocking semantic defect.
8. No out-of-distribution or distribution-drift detector fires.
9. Checkpoint, source commit, runtime, prompt, candidate, ranking, evidence, and final-mask hashes are
   complete and internally consistent.
10. An unexpired, unrevoked certificate covers the exact risk bucket and pipeline fingerprint.

Any failure enters bounded autonomous repair before human routing. Only irreducible disagreement,
high-risk uncertainty, or drift enters the residual human queue.

### Calibration and audit strategy

Replace the mandatory 300-human-cases-per-label/context design with selective pooled calibration:

- Maintain stratified `human_anchor_gold` train, calibration, and final-holdout partitions spanning
  large body parts, limbs, hands/feet, hair/face, clothing/materials, sensitive anatomy, occlusion,
  and multi-person contact. The final holdout is image-disjoint from every training and tuning path.
- Pool evidence by empirically justified risk groups rather than every label/context Cartesian product.
- Use selective prediction: certify only high-agreement, in-distribution cases and abstain on the rest.
- Freeze per-bucket maximum false-accept and serious-failure rates, perform a documented power
  calculation, and require a one-sided 95% upper confidence bound below each maximum. Use conservative
  exact bounds for zero/rare serious failures; sparse buckets abstain rather than borrowing unjustified
  confidence.
- Use an unbiased random audit component plus deterministic risk oversampling. Approximately 1-2% is
  a workload target only; rare/high-risk buckets and statistical minimum sample floors take precedence.
- Provide batch audit/approval panels; do not require routine CVAT editing.
- Revoke the relevant certificate immediately after a serious audited false accept, hash mismatch,
  fingerprint change, or material drift.
- Keep human-anchor holdouts out of autonomous training and all pseudo-label paths.
- Retraining creates a new fingerprint and must be revalidated, but unaffected evidence should be
  reusable through explicitly versioned compatibility rules rather than discarded wholesale.

Operational targets:

```yaml
target_zero_touch_fraction: 0.95
maximum_routine_human_touch_fraction: 0.05
target_manual_pixel_edit_fraction: 0.01
```

These are targets requiring measurement, not completion claims.
`target_zero_touch_fraction` measures intervention volume only; it is never an accuracy estimate or a
statistical confidence claim.

## Gate and metric changes

- Report `human_anchor_train_count`, `human_anchor_calibration_count`,
  `human_anchor_holdout_count`, `autonomous_certified_gold_count`,
  `weighted_pseudo_label_count`, and `machine_candidate_count` separately.
- P5 entry becomes `certified_training_package_count >= 200`, where
  `certified_training_package_count = human_anchor_train_count + autonomous_certified_gold_count`.
  Pseudo-labels and holdout/calibration anchors never satisfy this gate.
- Report `effective_training_weight_units` separately as the sum of actual per-example training
  weights. It is a scheduling/optimization diagnostic and never a gold, volume, coverage, P5, or D5
  gate.
- D5 becomes at least 300 certified packages with required coverage, not 300 manually corrected
  packages.
- VLM calibration uses the human-anchor corpus plus continuing audited certified cases.
- Final model promotion is evaluated only against the image-disjoint human-anchor holdout.
- P8 automatically accepts certificate-covered instances; CVAT receives only residual cases and audits.
- The headline test becomes 20 unseen images processed autonomously, with a preselected blinded audit
  sample and no routine per-image correction.
- Replace the primary labor metric `minutes/image` with human touches per 100 images, audited fraction,
  residual-review fraction, and manually changed pixels per 100,000 predicted pixels.
- Add tracker metrics for the three anchor partitions, `autonomous_certified_gold_count`,
  `weighted_pseudo_label_count`, `machine_candidate_count`, `certified_training_package_count`,
  `effective_training_weight_units`, `zero_touch_fraction`, `residual_review_fraction`,
  `audit_false_accept_rate`, and `serious_false_accept_rate`.

## Required repository surfaces

Reconcile and update, at minimum:

- Plan documents 00, 01, 03-17, and 19-21; add an authoritative technology-currency/model-challenge
  specification.
- Instructions where they state that model choices are permanently final or that humans are always
  the only gold authority.
- Items and tracker entries in P0, P1, P2, P3, P4, P5, P6, P7, and P8; reopen affected exits honestly.
- Tracker source, validation, dashboard, goals, metrics, phase reports, and item-count drift.
- `configs/external_sources.yaml`, `pipeline.yaml`, `prompting.yaml`, `vlm.yaml`, `qa.yaml`, and
  `autonomous_masks.yaml`.
- `models/model_registry.json` and every checkpoint/source/runtime/hash smoke fixture.
- Environment lockfiles and isolated provider environments.
- `src/maskfactory/stages/s01_person_detection.py`, `s02_silhouette.py`, `s03_parsing.py`,
  `s04_pose.py`, `s05_geometry.py`, `s06_openvocab.py`, `s07_sam2.py`, `s08_5_densepose.py`,
  `s09_fusion.py`, and production orchestration.
- `src/maskfactory/serve/providers.py`, `serve/api.py`, `vlm/workhorse.py`, and `vlm/production.py`.
- All files under `src/maskfactory/autonomy/`.
- `src/maskfactory/datasets/builder.py`, `coverage.py`, `coverage_v2.py`, and `active_learning.py`.
- Manifest, lifecycle, dataset, leaderboard, registry, coverage, review, and serving schemas.
- Package finalization, verification, reindexing, DVC selection, training-weight handling, CVAT routing,
  ComfyUI nodes/workflows, and provenance display.
- Unit, integration, property, regression, live-smoke, compatibility, migration, rollback, performance,
  determinism, OOM, and full-suite tests.

Keep legacy `sam2_refine` manifests and historical evidence readable through compatibility aliases.
Never rewrite historical benchmark evidence to make it appear that SAM 3.1 produced old results.

## Benchmark matrix

Use identical frozen images, prompts, parts, hardware, QA, and truth:

1. SAM2.1 only.
2. SAM3.1 only.
3. SAM3.1 discovery -> SAM2.1 refinement.
4. SAM3.1 discovery -> SAM3.1 refinement.
5. RF-DETR detection -> SAM2.1 refinement.
6. RF-DETR detection -> SAM3.1 refinement.
7. Each winning route with and without SAM 3D Body.
8. Each winning route with relevant BiRefNet variants and pose challengers.

Measure per-label IoU, boundary-F at two pixels, small-part recall, person/part instance recall,
cross-person bleed, left/right and front/back errors, clothing/anatomy confusion, missing/hallucinated
parts, hard-QA failures, correction pixels, audit time, peak VRAM, cold/warm latency, OOM/crash rate,
and deterministic repeatability.

Promote by role only after a measured win or meaningful labor reduction and predeclared
non-inferiority margins pass for every hard label and high-risk bucket. An average improvement cannot
hide a hard-bucket regression. Promotion also requires complete provenance, reliable operation on the
available 8 GB GPU or an explicitly approved alternate runtime, and a tested one-command rollback.

## Technology-currency policy

- Run a model, runtime, dependency, license, and content-compatibility audit every 90 days and before
  dataset freeze, training, production promotion, or a major release.
- Newer models automatically become challengers, never automatic replacements.
- Architecture documents name roles; registries select current providers.
- CI fails on missing source/checkpoint hashes, unresolved license/content compatibility, expired
  currency review, invalid benchmark certificates, or untested rollback.
- Historical evidence remains immutable.

Document 22 is the authoritative detailed contract for active registry versions, provider/model
lifecycle states, per-provider content decisions, license activation blockers, non-collapsing truth
metrics, certification statistics, hard-bucket non-inferiority, and currency review.

## Safe execution order

1. Read the live tracker and current uncommitted diff; preserve all existing work.
2. Record the user-confirmed private/noncommercial profile and Sapiens2 exclusion in authoritative
   governance and registries.
3. Amend architecture and autonomy specifications, items, tracker schemas, metrics, and gates.
4. Implement truth-tier schemas and backward-compatible readers before changing writers.
5. Implement provider interfaces and compatibility aliases before integrating new models.
6. Build isolated environments, pin sources/checkpoints, and run smokes one provider at a time.
7. Wire candidates into shadow tournaments; do not silently change active providers.
8. Implement autonomous certification, pooled calibration, residual routing, dataset weighting, and
   audit/revocation paths.
9. Migrate CVAT in parallel and verify rollback.
10. Run frozen screening, then human-anchor benchmark, promote role winners, and retain rollback.
11. Run focused tests, full tests, lint/format, tracker rebuild/validate/report, doctor, live smokes, and
    end-to-end headline demonstrations.
12. Update OPS_LOG, DECISIONS_LOG, model registry, evidence files, tracker statuses, and handoff notes
    honestly.

## Completion standard

Do not claim 98% confidence or 100% completion merely because code and documentation exist. Completion
requires real installation and checkpoint evidence, full test success, tracker validation, current
doctor output, live hardware measurements, CVAT migration/rollback proof, frozen benchmark results,
autonomous certification and revocation demonstrations, zero-touch/residual metrics, and end-to-end
single- and multi-person headline evidence. Anything needing source images, a small human-anchor audit,
credential acceptance, billable compute, or other genuinely non-delegable Kevin action must be marked
`NEEDS KEVIN:` while all other actionable work continues.
