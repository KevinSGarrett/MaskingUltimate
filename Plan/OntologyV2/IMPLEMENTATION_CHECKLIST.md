# Adult Anatomy Ontology v2 — Implementation Checklist

This checklist is the evidence-preserving source companion to doc 18. Its 70 entries are now
imported one-to-one into the live tracker across `MF-P0-15`, `MF-P1-10` through `MF-P1-12`,
`MF-P2-10`, `MF-P4-09`, `MF-P5-09`, `MF-P6-05`, and `MF-P7-06`. Live status belongs only in
`Plan/Tracker/tracker.json`; this file retains the pre-import check/evidence record. See
`Plan/Items/TRACEABILITY_18_22_SAM31.md`.

Every checkbox requires specific evidence. Do not mark an item complete from code presence alone.

## A. Freeze and compatibility baseline

- [x] Hash/archive active v1 ontology, schemas, CVAT label map, derived config, registry, champions, and a representative package.
  Evidence: `qa/evidence/ontology_v2/v1_baseline.json`; `tools/freeze_ontology_v1_baseline.py --check` verifies the exact authority and immutable draft-baseline package tree.
- [x] Record v1 PART mapping `0..55` and prove migration never changes an old ID/name.
  Evidence: the baseline records every ID/name and `tests/test_ontology_v2_generation.py` proves the v2 prefix is byte-for-record append-only.
- [x] Resolve every literal 56/57 reference: v1 has 56 logits including background; v2 has 65.
  Evidence: active configs remain 56; inactive v2 generation requires exactly 65; drifted 57-class configs remain rejection fixtures only.
- [x] Add byte-compatibility test for v1 package/map/derived outputs after v2-capable code lands.
  Evidence: `tests/test_ontology_v2_baseline.py` binds active v1 config bytes and mapping to the frozen baseline; v2 writes separate inactive artifacts.
- [x] Add rollback rehearsal restoring v1 champion roles and workflows.
  Evidence: `qa/evidence/ontology_v2/v1_rollback_rehearsal.json` proves deliberate isolated drift and atomic exact-byte restoration of the registry and all shipped workflows without mutating production sources.

## B. Ontology generator and machine authority

- [x] Import ten proposed labels append-only from `ontology_v2_additions.yaml`.
  Evidence: `src/maskfactory/ontology_v2.py` generates inactive `configs/ontology_v2.yaml` with contiguous IDs `56..65` after unchanged v1 IDs.
- [x] Add boundary rules for areola ring, nipple carve-out, external vulva, shaft/glans, and scrotal midline.
  Evidence: every appended atomic references a validated machine-readable rule in `configs/ontology_v2.yaml`; unknown rules fail generation.
- [x] Add reciprocal swaps for areolae, nipples, and scrotal regions.
  Evidence: generator validation and `tests/test_ontology_v2_generation.py` require reciprocal character-side mappings.
- [x] Add alias resolver with warnings/provenance; aliases never enter maps/manifests.
  Evidence: `resolve_v2_alias` emits requested/canonical/alias/kind/warning provenance; tests cover spaced and underscored aliases, warnings, canonical pass-through, unknown refusal, and non-persistence as labels.
- [ ] Add all derived formulas and regenerate `configs/derived.yaml`.
  Progress: all formulas are generated in inactive `configs/derived_v2.yaml`; active `configs/derived.yaml` intentionally remains byte-identical until the activation gate.
- [x] Extend visualization colors with distinct, accessible, stable values.
  Evidence: inactive `configs/viz_v2.yaml` preserves every v1 color and appends unique fixed colors for every new atomic/union.
- [x] Generate `configs/ontology_v2.yaml`; retain active v1 until activation.
  Evidence: `tools/generate_ontology_v2.py --check` is drift-clean and the artifact declares `approved_design_not_active`; the runtime default remains `configs/ontology.yaml` / `body_parts_v1`.
- [x] CI proves IDs `0..55` unchanged and IDs `56..65` contiguous.
  Evidence: CI drift-checks all inactive v2 artifacts and pytest enforces the exact append-only mapping.
- [x] Tests prove exactly 66 class names including background and correct flips.
  Evidence: `tests/test_ontology_v2_generation.py` loads the generated ontology through the production loader and proves 65 PART records plus every reciprocal swap.

## C. Visibility, manifest, and migration

- [x] Add `occluded_by_clothing`, `not_applicable`, and `unreviewed_for_v2` to v2 schema only.
  Evidence: generated `manifest_v2.schema.json` carries the v2-only states; the active v1 schema is unchanged and tests assert the separation.
- [x] Implement state/mask invariants from doc 18 §4.
  Evidence: schema conditionals plus `v2_manifest_issues` enforce nonempty visible masks, null-mask states, separate ambiguity authority, hash-map membership, and human evidence for `not_applicable`.
- [x] Add `reviewed_ontology_version` and per-label review authority.
  Evidence: v2 manifests require root review version and exact per-entry reviewed/reviewer/time/source/ontology provenance.
- [x] Implement idempotent v1→v2 migration: pixels unchanged; ten labels unreviewed.
  Evidence: `migrate_v1_manifest_document` preserves the files map, appends exactly ten null-mask entries, downgrades the workflow to review, and returns byte-for-document identical output when rerun.
- [x] Never auto-convert unreviewed to absent/not-visible/not-applicable.
  Evidence: migrated additions are exactly `unreviewed_for_v2`; schema/custom invariants prevent that state from carrying a mask or reviewed authority.
- [x] Refuse v2 gold/dataset inclusion while any label remains unreviewed.
  Evidence: packager gold stamping and frozen-package dataset discovery both call the shared 66-label authority-completeness gate; tests prove rejection leaves the manifest unchanged. Autonomous certification is valid; human review is optional.
- [x] Add migration dry-run report, hashes, collision detection, and rollback.
  Evidence: `tools/migrate_manifest_v2.py` defaults to dry-run, records source/target/files-map hashes, refuses append collisions and post-migration drift, and restores the exact source bytes from a hash-verified backup.
- [x] Test every v2 state, including ambiguity and clothing occlusion.
  Evidence: parameterized tests cover all ten doc-18 labels and all review states, visible/null/ignore contracts, `occluded_by_clothing`, `not_applicable`, and forbidden `n/a` use on appended labels.

## D. Optional CVAT and autonomous authority resolution

- [x] Create versioned v2 CVAT project; never mutate open v1 tasks in place.
- [x] Add canonical labels and v2 visibility attributes.
- [x] Surface aliases as help/search text only.
- [x] Update task descriptions with doc 18 SOP and character-perspective reminder.
- [x] Add chest/pelvic review crop presets.
- [x] Push migrated tasks with additions explicitly unreviewed.
- [x] Pull exact v2 states/masks; reject aliases and unknown values.
- [x] Block export when visible masks are absent or null-mask states contain masks.
- [ ] Pilot 20–30 governed real images from MaskedWarehouse with Reference_Images retrieval/coverage evidence, covering all states and applicable classes.
- [ ] Record autonomous latency, ambiguity/abstention/correction outcomes, and revise guidelines before scale processing.

## E. Drafting and fusion

- [x] Add anatomy crop proposals without asserting hidden anatomy.
- [x] Add canonical open-vocabulary prompts with provider-neutral routing.
- [x] Route prompts through SAM2/fusion; detector boxes never become final masks directly.
- [x] Add same-side chest and pelvic geometry priors.
- [x] Enforce breast/pelvic carve-outs before PART-map write.
- [x] Preserve ambiguity/clothing occlusion rather than forcing candidates.
- [x] Produce panels, provenance, confidence, and correction instructions.
- [x] Test nude, clothed, partial, distant, hair-occluded, side-view, and cropped fixtures.

## F. QA and calibration

- [x] Implement QC-V2-001 through QC-V2-012.
- [x] Seed a good case and defects for every new check.
- [x] Extend topology, left/right, exclusivity, state consistency, and containment reports.
- [x] Add clothed false-positive sweep.
- [x] Extend VLM vocabulary while preserving QA-only governance.
- [ ] Build real adult calibration panels; synthetic near-duplicates are not gate authority.
- [ ] Pass calibrated recall/precision before anatomy routing is enabled.

## G. Dataset and training

- [x] Accept only authority-complete v2 packages for 66-class supervision.
  Evidence: the shared manifest eligibility gate remains mandatory at frozen-package discovery and the inactive fine-tune contract refuses any sample without complete v2 review authority.
- [x] Preserve v1 data without treating new labels as negatives.
  Evidence: v1 is explicitly 56-class pretraining-only; the contract exposes no negative IDs 56–65 and cannot place v1 packages into v2 fine-tuning.
- [x] Burn ambiguity to 255 and test IDs 56–65 export exactly.
  Evidence: dataset export now consumes separate v2 ambiguity masks; the fixture preserves all non-ambiguous IDs 56–65 byte-for-value and burns only the explicit region to 255.
- [x] Add anatomy-focused crops and whole-body anti-forgetting batches.
  Evidence: the deterministic reviewed-v2 sampler guarantees at least 50% positive anatomy crops once inventory exists and at least 25% whole-body draws, with zero fabricated positives.
- [x] Update flip/rotation/crop/color/class-weight tests.
  Evidence: v2 fixtures cover every appended flip, forced anatomy retention, rotation/ignore border, label-invariant color jitter, and 65-entry inverse-square-root weights capped at x8.
- [x] Author 66-class configs and eliminate the old 57-class conflict.
  Evidence: separate inactive SegFormer-B3 and Mask2Former-SwinB configs carry the exact 65-name vocabulary; validation rejects 57 while active v1 configs remain 56.
- [x] Build identity-separated positive and clothed-negative holdouts.
  Evidence: holdout manifests reject identity or pHash-connected groups crossing train/val/positive/clothed-negative cohorts and require explicit reviewed clothed negatives.
- [ ] Reach 50–100 clear positives per new class before production claims.
- [ ] Publish IoU, boundary-F, recall, clothed false positives, and side-swap rates.
- [x] Refuse promotion when any class lacks evidence or systematically fires on clothing.
  Evidence: the inactive gate requires all ten exact rows, >=50 clear positives per class, finite positive/clothed holdout metrics, and zero clothed false-positive images until real calibration authorizes otherwise. Machine evidence must be regenerated for the 66-class contract before activation.

## H. Registry, serving, and ComfyUI

- [x] Registry stores ontology version, exact 65-name vocabulary, and artifact hashes.
  Evidence: training artifacts and registered challengers bind the exact ordered vocabulary, its digest, checkpoint/config digests, and a matching artifact-hash map; promotion revalidates the complete contract.
- [x] Serving rejects v2 labels unless loaded champion declares exact v2 vocabulary.
  Evidence: v1 rejects v2-only labels, v2 refuses any reordered or incomplete 65-name vocabulary, and derived unions cannot masquerade as model logits.
- [x] Health/models/predict responses expose ontology version.
  Evidence: runtime tests assert `body_parts_v2` plus vocabulary digest and model contracts across all three response surfaces.
- [x] Add canonical labels/unions to ComfyUI selectors and package browser.
  Evidence: the dependency-light node pack reads package-major 1/2, filters by ontology, loads v2 manifest mask paths, and exposes the ten anatomy atomics plus governed unions.
- [x] Canonicalize UI/API aliases and return canonical provenance.
  Evidence: `penis head` resolves to canonical `glans_penis`/ID 62 while preserving requested text, alias status, warning, ontology, map, and class ID; union aliases route only to union loaders.
- [x] Add anatomy and clothed-negative workflow fixtures.
  Evidence: installed fixtures `wf_v2_anatomy_selector.json` and `wf_v2_clothed_negative_guard.json` are exercised by focused tests. Machine evidence: `qa/live_verification/ontology_v2_registry_serving_comfy_20260713.json`.
- [ ] Re-run latency/residency and Mode A/Mode B end-to-end tests.

## I. Operations and activation

- [x] Add coverage targets for every class/state/view/pose/occlusion context.
  Evidence: an inactive exact-vocabulary matrix binds all 65 foreground classes to nine review states, six views, seven poses, and eight occlusion contexts, plus explicit 50/100 clear-positive rows for IDs 56-65; non-authoritative, unreviewed, stale, duplicate, incomplete, or target-drifted evidence fails closed.
- [x] Add failure reasons and acquisition actions for boundary/side/clothing errors.
  Evidence: canonical reasons deterministically map to governed state/view/occlusion targets and hard-case actions; weekly plans and local clustering understand the v2 vocabulary, while aliases, fabricated positives, unreviewed negatives, and projected/amodal positives are refused. Evidence must include the anus lane before activation.
- [x] Update backup, restore, GC, reindex, DVC, and incident drills.
  Evidence: nightly restore sampling now dispatches v1/v2 verification; v2 restores fail on schema, semantic, exhaustive-hash, strict-mask, QA, or review-authority drift; reindex selects the schema by ontology; GC sandbox proof protects active/ambiguity authority; dataset builds select one ontology and refuse reused paths/tags, push before tagging, and mark exported only after success; copy-only v2 reindex plus exact-byte v1 rollback drills leave production sources unchanged. Machine evidence: `qa/live_verification/ontology_v2_recovery_operations_20260714.json`.
- [x] Update docs 00–17, SOPs, schemas, CLI help, generated references, tracker, and DoD.
  Evidence: an executable audit scans all 18 core docs, rejects unqualified 57-class drift, and requires v2 pointers in every version-sensitive document; doc 11 carries the separate-pilot SOP; doc 04 records schema/authority dispatch; doc 12 matches immutable DVC ordering; doc 17 is per-instance version-aware; CLI help exposes active-v1/gated-v2 choices; a generated 56→65 reference is drift-checked; the 414-item tracker, item counts, P0–P8/D1–D11/G1–G9 metadata, and version-aware D1 render cleanly. Machine evidence: `qa/live_verification/ontology_v2_documentation_alignment_20260714.json`.
- [ ] Full tests, drift, schemas, seeded QA, migration, rollback, CVAT pilot, dataset, training,
  leaderboard, serving, and ComfyUI evidence all pass.
- [ ] Only then switch active ontology/champions to `body_parts_v2` and record activation.
