# Activation Readiness Checklist

No subsection may be skipped. `N/A` requires an explicit rationale and approving owner. A checkbox is
closed only with named evidence, not intent.

## A. Operating profile and acquisition boundaries

- [ ] A-01 Operating profile is exactly private, personal, local, noncommercial, and not distributed.
- [ ] A-02 `distribution_allowed` is false in every active DAZ and MaskFactory configuration.
- [ ] A-03 Public hosting and commercial deployment are absent from the worker and serving paths.
- [ ] A-04 Local RGB, annotation, dataset, training, and evaluation operations are enabled only through
  the defined technical pipeline.
- [ ] A-05 Kevin remains the only authority for purchases and paid downloads.
- [ ] A-06 No automatic purchasing, account login, or terms-acceptance workflow exists.
- [ ] A-07 Asset source/product records exist for organization, dependencies, updates, and replay.
- [ ] A-08 Account credentials and order tokens never enter the registry or logs.
- [ ] A-09 The operating-profile tests fail any accidental distribution/commercial drift.
- [ ] A-10 The operating profile loads consistently in scanner, worker, packager, and trainer.

## B. Character and anatomy configuration

- [ ] B-01 The registry represents the requested adult male and adult female DAZ figure families.
- [ ] B-02 Character, body, face, skin, hair, wardrobe, and anatomy selections have explicit asset IDs.
- [ ] B-03 Age-appearance categories are ordinary coverage dimensions with reproducible morph values.
- [ ] B-04 Anatomy configuration is explicit and is not inferred from a product name or presentation.
- [ ] B-05 Clothed, partially clothed, and unclothed configurations are all schedulable.
- [ ] B-06 Every anatomy or geograft asset has a compatible topology mapping.
- [ ] B-07 Multi-character male/female configuration matrices are fully represented.
- [ ] B-08 Scene configuration metadata follows each render and annotation package.
- [ ] B-09 Character-configuration fixtures cover valid, incompatible, missing-dependency, and unmapped
  cases.

## C. Storage and security

- [ ] C-01 Exact `F:\DAZ` folder tree exists with correct permissions.
- [ ] C-02 Proprietary roots are excluded from Git and distributable artifacts.
- [ ] C-03 DAZ credentials/account data are absent from configs, logs, recipes, and reports.
- [ ] C-04 F-drive soft/hard free-space thresholds are configured and tested.
- [ ] C-05 Retention plan is based on measured bytes per scene.
- [ ] C-06 Control, registry, mapping, and config backups are current.
- [ ] C-07 One restore drill passes on a clean test root.
- [ ] C-08 Bulk-output backup policy is explicit by data class.
- [ ] C-09 Local DVC/cache strategy does not trigger unapproved cloud cost.
- [ ] C-10 Path traversal, junction escape, and unapproved network-root tests pass.

## D. DAZ runtime

- [ ] D-01 DAZ Studio version and executable hash are pinned.
- [ ] D-02 Renderer, plugin inventory, NVIDIA driver, and runtime profile are pinned.
- [ ] D-03 Dedicated `MaskFactoryDAZ` application instance is initialized.
- [ ] D-04 Content and render directories point only to registered roots.
- [ ] D-05 No default scene or interactive startup action runs.
- [ ] D-06 Script bundle deploys and verifies by hash.
- [ ] D-07 No-prompt automation behavior is tested.
- [ ] D-08 Headless mode is used only if the exact runtime proves reliable; otherwise hidden GUI worker is
  documented.
- [ ] D-09 Primitive render/file-protocol smoke passes.
- [ ] D-10 Popup watchdog, crash capture, timeout, and process-tree termination pass.
- [ ] D-11 Machine-level GPU lease interoperates with MaskFactory inference/training.

## E. Asset registry and qualification

- [ ] E-01 DIM install manifests and CMS/filesystem scans reconcile.
- [ ] E-02 Every product and asset has a stable ID and SHA-256.
- [ ] E-03 Asset types, figure generation, compatibility base, dependencies, and scene categories
  validate.
- [ ] E-04 Missing/modified/orphan/shadowed assets are reported.
- [ ] E-05 Unknown asset types cannot enter generation pools.
- [ ] E-06 Every eligible asset has a current smoke certificate.
- [ ] E-07 Load, texture, fit, pose, preview, and log checks pass.
- [ ] E-08 Updating an asset revokes dependent certificates and queued recipes.
- [ ] E-09 Quarantine and retest flows are tested.
- [ ] E-10 Registry snapshot can be rebuilt and diffed deterministically.

## F. Figure and ontology mapping

- [ ] F-01 Genesis 9 base topology fingerprint is frozen.
- [ ] F-02 v1 mapping covers every required indexed PART label.
- [ ] F-03 Material and protected-region mappings are separate and complete.
- [ ] F-04 Left/right character-perspective fixtures pass every view.
- [ ] F-05 Finger, toe, ear, torso, breast, pelvis, glute, wrist, ankle, and hair boundaries pass.
- [ ] F-06 Approved morph/pose ranges do not break mapping.
- [ ] F-07 Clothing-territory transfer passes tight/loose/layered fixtures.
- [ ] F-08 Hair/alpha policy passes representative assets.
- [ ] F-09 Geografts without approved mappings block.
- [ ] F-10 v2 mapping remains inactive unless the existing MaskFactory v2 requirements pass.

## G. Scene generation

- [ ] G-01 Recipe schema is closed and versioned.
- [ ] G-02 Same seed/snapshot/config yields identical recipe.
- [ ] G-03 Recipe records final explicit choices and numeric values.
- [ ] G-04 Morph correlation and joint-limit constraints pass.
- [ ] G-05 Camera framing/prominence/truncation targets pass.
- [ ] G-06 Collision and contact tolerances pass.
- [ ] G-07 Solo pose/body/hair/wardrobe/camera/light coverage pilot passes.
- [ ] G-08 Duo separated/overlap/contact pilot passes.
- [ ] G-09 Trio/quartet identity pilot passes before those counts activate.
- [ ] G-10 Asset dominance and repetition caps pass.
- [ ] G-11 Coverage-driven selection measurably reduces declared deficits.

## H. Rendering and annotation

- [ ] H-01 RGB and all mandatory passes render from one frozen scene state.
- [ ] H-02 Indexed passes use exact lossless IDs without tone mapping or lossy effects.
- [ ] H-03 Pass dimensions/camera/crop/frame hashes agree.
- [ ] H-04 ID decoder rejects unknown/aliased colors.
- [ ] H-05 Every visible person pixel has exactly one instance, PART, and MATERIAL authority.
- [ ] H-06 Protected objects/support/accessories follow per-instance rules.
- [ ] H-07 Depth/normals are finite and consistent.
- [ ] H-08 Hair, lace, sheer, and transparency edge rules pass.
- [ ] H-09 Amodal/hidden outputs are physically separate and train-ineligible.
- [ ] H-10 Semantic pass replay is hash-identical.

## I. Validation and packaging

- [ ] I-01 Every asset, recipe, scene, pass, semantic, multi-person, and package validator has
  seeded negative tests.
- [ ] I-02 No hard validator can be downgraded by a routine config flag.
- [ ] I-03 Bounded retry cannot repeat indefinitely.
- [ ] I-04 Rejected and quarantined states are distinct and reason-coded.
- [ ] I-05 Partial outputs never become accepted packages.
- [ ] I-06 Package hash map is exhaustive.
- [ ] I-07 100 accepted pilot packages pass repeat verification.
- [ ] I-08 A random audit replays semantic passes exactly.
- [ ] I-09 Multi-person exclusivity and cross-instance bleed tests pass.
- [ ] I-10 Accepted packages retain all required evidence without proprietary asset copies.

## J. MaskFactory integration

- [ ] J-01 Versioned manifests accept `source_origin: synthetic` with structured technical lineage.
- [ ] J-02 Historical manifests remain valid under their own schema.
- [ ] J-03 Synthetic packages use `weighted_pseudo_label`, train, weight 0.10–0.25.
- [ ] J-04 Synthetic packages cannot claim human review or autonomous certification.
- [ ] J-05 DAZ package adapter uses the canonical ontology loader.
- [ ] J-06 Existing strict PNG and applicable QC run.
- [ ] J-07 Synthetic packages remain outside certified/gold counts and certified coverage.
- [ ] J-08 Dataset builder forces synthetic train-only.
- [ ] J-09 Dataset builder and training launcher both hard-reject >30% synthetic.
- [ ] J-10 Multi-person instances/variants stay grouped by image/scene family.
- [ ] J-11 Full existing test suite remains green with DAZ disabled.

## K. Training and promotion

- [ ] K-01 Real-only baseline is frozen.
- [ ] K-02 10%, 20%, and 30% matched DAZ ablations are reproducible.
- [ ] K-03 Synthetic data is absent from all final real holdouts and certificate fitting.
- [ ] K-04 Dataset cards report synthetic source composition and weights.
- [ ] K-05 Candidate wins on declared real primary metrics.
- [ ] K-06 Every hard label/risk bucket meets non-inferiority.
- [ ] K-07 Left/right, cross-person, protected-region, determinism, OOM, and rollback do not regress.
- [ ] K-08 A synthetic-diagnostic-only win is rejected.
- [ ] K-09 DAZ-trained models remain in the local/private project profile.
- [ ] K-10 One-command model rollback passes.

## L. Operations

- [ ] L-01 Queue lease, heartbeat, retry, drain, pause, and resume pass.
- [ ] L-02 Disk-full, F-drive-loss, GPU-contention, process-kill, popup, and corrupt-result tests pass.
- [ ] L-03 Seven-day soak completes within declared error/retry limits.
- [ ] L-04 Daily report separates throughput, QA, coverage, storage, and model metrics.
- [ ] L-05 Alerts have owner, severity, acknowledgment, and response action.
- [ ] L-06 Scheduled retention never deletes the only copy of registry/mapping/evidence.
- [ ] L-07 Quarterly runtime/asset/mapping/backup review is scheduled.
- [ ] L-08 DAZ generation can be disabled without affecting normal MaskFactory intake.
- [ ] L-09 Queue/registry/package history remains rebuildable after rollback.
- [ ] L-10 Kevin approves activation schedule and resource ceilings.

## Final release decision

- [ ] All applicable A–L items have evidence.
- [ ] No critical technical failure is open.
- [ ] Requirements traceability has no orphan requirement or untested technical invariant.
- [ ] Risk register has no unaccepted critical residual risk.
- [ ] Rollback rehearsal completed.
- [ ] Final activation decision is recorded with date, evidence bundle hash, and rollback target.
