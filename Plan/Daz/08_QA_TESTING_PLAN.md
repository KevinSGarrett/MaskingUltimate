# QA and Testing Plan

## 1. Quality model

Quality is layered. A scene is accepted only if every applicable layer passes:

1. operating profile and technical lineage;
2. asset integrity and compatibility;
3. deterministic recipe validity;
4. scene assembly and geometry sanity;
5. render runtime integrity;
6. annotation pass validity;
7. semantic/ontology mapping validity;
8. multi-person identity and contact validity;
9. package/schema/hash validity;
10. dataset/training-authority validity;
11. real-image model benefit and non-regression.

A pass at a later layer never overrides failure at an earlier layer.

## 2. Test tiers

| Tier | Environment | Purpose | Required frequency |
|---|---|---|---|
| T0 Static | CI, no DAZ | schemas, config, lint, type, forbidden files, docs consistency | every change |
| T1 Unit | CI, procedural fixtures | samplers, hashes, IDs, mappings, validators, state machines | every change |
| T2 Contract | CI, synthetic packages | positive/negative schema and MaskFactory integration | every change |
| T3 DAZ smoke | local pinned DAZ | launch, script, primitive render, file protocol | runtime change and daily while active |
| T4 Asset smoke | local content | load/fit/render/dependency per asset | new/update/review cycle |
| T5 Mapping golden | local content | exact part/material/left-right boundary fixtures | mapping/runtime change |
| T6 Scene pilot | local content | 100–1,000 deterministic solo/multi scenes | release candidate |
| T7 Scale soak | local content | days-long queue, capacity, recovery, no dialogs | before activation and quarterly |
| T8 Training ablation | local training stack | synthetic mixture benefit | every corpus/model promotion |
| T9 Real holdout | isolated human anchors | final performance/non-regression authority | every promotion |
| T10 Recovery | restored environment | registry/mapping/package/queue backup integrity | before launch and quarterly |

## 3. Operating-profile and source-record tests

- Scheduled operation requires the expected private/local/noncommercial/non-distributed profile.
- Distribution, public hosting, or commercial deployment cannot be enabled by ordinary DAZ config.
- Automated purchasing and account-login fields are rejected by schemas.
- Missing source/product identity blocks reproducibility certification, not local ownership claims.
- An asset-file change invalidates its technical smoke and mapping certificates.
- A character asset with missing figure-generation or anatomy-configuration metadata is excluded until
  its technical compatibility is known.
- Distribution flag cannot become true under the private profile.
- A redacted report contains no account email, credential, serial, order token, or private source path.

## 4. Registry and asset tests

- DIM manifest parser handles valid, missing, duplicate, malformed, and unexpected fields.
- CMS-offline scan still inventories filesystem assets and records missing CMS metadata honestly.
- Duplicate product/file identifiers are deterministic and do not collapse distinct hashes.
- A file modification changes the asset snapshot and invalidates certificates.
- Dependencies form an acyclic resolvable graph or produce a declared incompatibility.
- Genesis 9, G8.1, pose, material, wardrobe, hair, prop, camera, light, environment, and unknown types
  classify correctly.
- An unknown type cannot enter a random pool.
- Broken texture paths, missing files, external paths, and cloud-only assets quarantine.
- A popup, fatal log entry, renderer fallback, or timeout quarantines the triggering combination.

## 5. Mapping tests

- Topology fingerprint includes facet order/count, vertex count, face/material groups, UV identity,
  skeleton/bone vocabulary, and base asset source.
- One changed facet or group invalidates the bundle.
- Every indexed label allowed by the selected ontology is represented in the mapping contract.
- Every visible person pixel has exactly one PART ID and one MATERIAL ID.
- No atomic PART overlap exists.
- Left/right use character perspective under front, back, profile, mirrored camera, and horizontal flip.
- Finger and toe territories remain stable through articulation.
- v2 carve-outs restore exact derived unions.
- Geografts without a compatible composition map are excluded.
- Clothing-territory transfer meets boundary and coverage tolerances on tight, loose, layered, and
  partially detached garments.
- Hair alpha fixtures pass at the declared opacity threshold.

## 6. Recipe and sampling tests

- Same registry snapshot, config, and seed produce byte-identical recipe JSON.
- Registry iteration order does not change selection.
- Different named random streams do not perturb unrelated decisions.
- Incompatible figure/pose/material/garment combinations cannot be emitted.
- Morph values remain inside per-control and correlated-body bounds.
- Character presets cannot select controls incompatible with the requested figure/configuration.
- Asset dominance, cooldown, and repetition caps are enforced.
- Coverage deficits increase selection probability without making impossible recipes.
- Every requested scene count/anatomy combination is represented according to the matrix.
- A recipe records explicit final values sufficient for replay.

## 7. Render and pass tests

- All passes have identical dimensions, camera matrix, frame, scene fingerprint, and render crop.
- Indexed passes are lossless, untone-mapped, undenoised, and contain only declared IDs.
- RGB and label edges align within the declared alpha/coverage convention.
- Transparent hair, lace, sheer fabrics, motion blur, depth of field, and antialiasing follow pass-specific
  rules.
- No object or material ID aliases another.
- Depth is finite where geometry is visible and has declared background behavior.
- Normals are finite and normalized within tolerance.
- Person visibility counts agree with instance masks.
- Repeated semantic-pass render produces identical hashes.
- An interrupted render cannot create a terminal success record.

## 8. Multi-person tests

- Instance IDs are stable and ranked by the MaskFactory prominence contract.
- Per-instance masks are mutually exclusive at every pixel.
- From p0's package, p1..pN are `other_person`; from p1's package, p0/p2..pN are `other_person`.
- Contact relationships are reciprocal.
- Front/back occlusion agrees with depth near the shared boundary.
- Crossed limbs retain owner identity.
- One scene's instances and variants all share one `image_id` split group.
- Seeded duplicate-person, merged-person, missing-person, cross-instance bleed, and nonreciprocal contact
  defects block.

## 9. Package and MaskFactory tests

- Current historical schemas remain readable through their correct version.
- New synthetic schema requires every synthetic-lineage field.
- A DAZ package cannot claim human review, autonomous certification, calibration, or holdout authority.
- Weight outside 0.10–0.25 fails.
- Source origin `synthetic` is accepted only by the new schema.
- Package file map is exhaustive and every SHA-256 verifies.
- Strict PNG mode/bit-depth/value tests pass for every map.
- Existing QC plus DAZ-specific checks run before freeze.
- Dataset builder forces all synthetic samples to train.
- Dataset builder rejects >30% synthetic share.
- Training launcher independently rejects >30%, wrong truth tier, missing lineage, or exposed holdouts.
- Synthetic counts remain separate and do not change certified-package requirements.

## 10. Scale and resilience tests

- Kill DAZ during assembly, simulation, RGB render, and ID render.
- Kill Python before and after lease/result transitions.
- Expire a heartbeat and verify one safe recovery, not duplicate acceptance.
- Fill the disk to soft and hard thresholds using a controlled fixture.
- Disconnect or remount F drive.
- Corrupt queue DB and rebuild from job manifests.
- Corrupt registry snapshot and restore from backup.
- Update an asset mid-queue and prove pending jobs invalidate.
- Place legacy GPU-lock/lease marker bytes and prove they cause no wait,
  timeout, refusal, mutation, reclamation, or scheduling decision.
- Trigger a popup and prove watchdog termination/quarantine.
- Run a seven-day soak with daily restarts and retained evidence.

## 11. Training and evaluation tests

- Real-only and mixed experiments use the same splits, seeds, schedule, and model family.
- Synthetic samples are absent from validation/final holdouts and certificate fitting.
- Scene variants and near duplicates cannot leak into diagnostics across groups.
- Dataset cards report image count, instance count, synthetic ratio, weight units, assets, render styles,
  mapping versions, and coverage.
- Real per-class IoU, boundary-F, false-positive, left/right, cross-person, and hard-bucket metrics are
  finite and comparable.
- Promotion rejects average gains hiding a hard-label regression.
- Model rollback restores the pre-DAZ champion and lifecycle state.

## 12. Evidence format

Every test run records:

- test suite/version and command;
- code Git SHA and dirty-state hash if applicable;
- DAZ/runtime/script/driver hashes for live tests;
- asset and mapping snapshot hashes;
- recipe seeds/IDs;
- start/end timestamps and machine profile;
- pass/fail/skip counts with skip reasons;
- output report SHA-256;
- log paths and retention classification.
