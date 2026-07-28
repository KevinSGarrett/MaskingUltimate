# Training, Domain Gap, Evaluation, and Promotion

## 1. Purpose

Use exact DAZ geometry labels to improve real-image MaskFactory performance without allowing synthetic
appearance to become the final measure of success. Training decisions are made by matched experiments
on untouched real-image evaluation data.

## 2. Data roles

| Data | Training | Validation/tuning | Final evaluation | Gold counts |
|---|---:|---:|---:|---:|
| DAZ synthetic | yes, weighted | synthetic diagnostics only | no | no |
| real weighted pseudo | as current plan permits | as current plan permits | no | no |
| autonomous certified real | as current plan permits | real calibration per plan | supporting | certified only |
| human-anchor real | yes/split by current plan | yes | yes | human |

DAZ cannot replace the real-image benchmark. It can eliminate manual drawing for its own scenes and can
target rare geometry that real data does not cover densely.

## 3. Default mixing policy

- Truth tier: `weighted_pseudo_label`.
- Per-sample loss weight: 0.10–0.25; start at 0.20.
- Synthetic image share: 30% maximum.
- All synthetic rows: train partition.
- Grouping: scene family, pristine image, variants, and all person instances stay together.
- Reporting: both image share and weighted-loss-unit share.
- Sampling: target hard buckets rather than flooding easy full-body scenes.

## 4. Baseline experiment set

Freeze identical model initialization, real splits, augmentations, optimizer, schedule, resolution, and
evaluation code for:

| Experiment | Real share | DAZ share | DAZ weight |
|---|---:|---:|---:|
| E0 | 100% | 0% | n/a |
| E1 | 90% | 10% | 0.20 |
| E2 | 80% | 20% | 0.20 |
| E3 | 70% | 30% | 0.20 |
| E4 | 80% | 20% | 0.10 |
| E5 | 80% | 20% | 0.25 |
| E6 | 80% | 20% targeted hard buckets | 0.20 |

Repeat selected experiments across enough seeds to distinguish a real effect from run noise.

## 5. Curriculum

Suggested order:

1. base pose/view/body-shape diversity;
2. hair and ordinary clothing boundaries;
3. hands, feet, fingers, toes, and foreshortening;
4. self-contact and prop contact;
5. two-person overlap/contact;
6. trio/quartet identity stress;
7. unclothed male/female anatomy;
8. thin/transparent/loose/layered materials;
9. difficult lighting, crop, blur, compression, and low resolution.

Curriculum stages are ablated. If early synthetic exposure harms real feature learning, use later-stage
fine-tuning, lower weights, balanced batch composition, or targeted auxiliary batches.

## 6. Batch composition

Control at batch or accumulation-window level:

- real/synthetic ratio;
- person-count distribution;
- ontology label presence;
- rare-label minimum;
- asset-family diversity;
- pristine/variant ratio;
- body/skin/hair/wardrobe/pose/camera mix.

Avoid batches dominated by one DAZ character/look or multiple variants of one scene.

## 7. Loss strategy

Candidate approaches, tested separately:

- uniform 0.10–0.25 synthetic sample weight;
- per-label synthetic weights for rare atomics;
- boundary-focused auxiliary loss;
- instance exclusivity loss;
- contact/occlusion auxiliary prediction;
- source-balanced normalization or sampler;
- confidence-aware downweighting at alpha/transparency boundaries.

No experimental loss changes the stored truth tier. Loss configuration is a training-run property.

## 8. Domain randomization

Randomize physically meaningful factors:

- skin shader/material response;
- hair construction and reflectance;
- garment fabrics, roughness, weave, thickness, and color;
- focal length, perspective, camera response;
- light direction, size, hardness, color temperature, contrast;
- indoor/outdoor/studio backgrounds;
- exposure, white balance, noise, compression, resolution, blur;
- body shape, pose, overlap, crop, and scale.

Do not randomize annotations independently from geometry. Keep transformations plausible enough that
the model learns human structure rather than render artifacts.

## 9. Reducing DAZ fingerprints

- cap each character, material, outfit, pose, environment, and product contribution;
- prevent recurring complete “looks”;
- vary renderer settings within validated profiles;
- hold out entire asset/product/environment families for diagnostics;
- compare embeddings of DAZ and real images;
- train a source classifier: high source separability signals remaining domain gap;
- mine failure clusters where the model relies on synthetic edges or shaders;
- combine DAZ later with other synthetic engines when useful.

## 10. Real evaluation sets

Maintain untouched real groups for:

- single full body;
- close portrait/upper body;
- back/profile/three-quarter views;
- hands/fingers and hand-to-body contact;
- feet/toes/footwear;
- long/curly/coily/transparent-edge hair;
- fitted/loose/layered/sheered clothing boundaries;
- male/female unclothed anatomy represented by the active ontology;
- crop/truncation/foreshortening;
- two, three, and four promoted people;
- crossed limbs, similar appearance, contact, and deep occlusion;
- phone/compressed/low-light/high-contrast images;
- artwork or nonphotographic domains when they are production scope.

No DAZ image or derived variant enters these sets.

## 11. Primary metrics

- per-class IoU and Dice;
- boundary F-score at declared tolerances;
- full-body union IoU;
- instance AP/IoU for multi-person;
- false-positive area outside target;
- false-negative area within target;
- left/right swap rate;
- cross-person bleed rate;
- protected-region violation rate;
- small-region recall;
- calibration/abstention quality;
- runtime, peak VRAM, OOM, and crash rate.

Report macro, micro, per-label, per-person-count, and hard-bucket results with confidence intervals.

## 12. Synthetic diagnostics

Synthetic held-out scenes are useful for controlled debugging:

- exact pose/view cells;
- never-seen asset families;
- never-seen environments/render profiles;
- label visibility and boundary complexity;
- controlled occlusion/contact severity;
- known left/right and identity ownership.

Synthetic results diagnose mechanisms but never decide real model promotion alone.

## 13. Ablations

Required ablations:

- real only versus real+DAZ;
- 10/20/30% share;
- 0.10/0.20/0.25 weight;
- broad versus hard-bucket-targeted DAZ;
- pristine only versus validated RGB variants;
- single-person only versus multi-person DAZ;
- clothed versus anatomy-inclusive;
- hair/wardrobe/contact subcorpora;
- asset-family held out;
- camera/light/environment randomization;
- v1 versus v2 only after v2 becomes active;
- DAZ alone versus DAZ plus another synthetic source when added.

## 14. Acceptance logic

A DAZ-enriched challenger may replace the current champion only when:

- the declared real primary metric materially improves;
- every protected hard label meets its non-inferiority margin;
- left/right, cross-person, and protected-region errors do not regress;
- improvement is seen on untouched real data and not only synthetic diagnostics;
- multiple seeds support the conclusion;
- runtime/resource/rollback requirements pass;
- dataset and run manifests are fully reproducible.

If only selected buckets improve, retain DAZ for targeted experts, auxiliary stages, or curriculum
batches instead of replacing the global champion.

## 15. Statistical comparison

- Use paired per-image bootstrap confidence intervals.
- Report absolute and relative differences.
- Correct or clearly label multiple hard-bucket comparisons.
- Publish sample counts and missing/applicable counts.
- Separate tuning results from final confirmatory evaluation.
- Predeclare primary metric and non-inferiority margins before reading final results.
- Retain all run seeds, checkpoints, metrics, and dataset hashes.

## 16. Failure analysis loop

For each real failure:

1. classify mapping, appearance-domain, pose, visibility, identity, or model-capacity cause;
2. check whether an equivalent DAZ coverage cell exists;
3. inspect model behavior on controlled synthetic sweeps;
4. add or rebalance DAZ only when the mechanism is representable;
5. retrain a matched challenger;
6. verify improvement on untouched real images;
7. retain or revert based on evidence.

DAZ is not used to manufacture an easy test that validates its own training data.

## 17. Continual training

After initial acceptance:

- snapshot every corpus version immutably;
- add new assets only through qualification and contribution caps;
- regenerate targeted scenes from measured real failures;
- keep a replayable benchmark subset from every corpus;
- rerun real regression suites after mapping/runtime changes;
- periodically compare current mixture with the real-only baseline;
- remove asset families that contribute style overfit or label defects.

## 18. Model lineage and rollback

Every trained model records:

- code/config/base-model hashes;
- real and DAZ dataset hashes;
- DAZ scene/mapping/runtime composition;
- synthetic image and weighted-unit share;
- seeds/schedule/hardware;
- full real/synthetic metrics;
- selected checkpoint;
- predecessor and rollback target.

Rollback restores model files, lifecycle state, serving configuration, and cache references in one
tested operation.

## 19. Confidence expectations

DAZ should substantially increase geometric coverage and label precision for controlled body regions,
contact, and multi-person ownership. It cannot by itself guarantee near-perfect masks on arbitrary real
photos because sensor, styling, anatomy, motion, environment, compression, and artistic-domain gaps
remain. Confidence should be updated from real ablation evidence, not a fixed promise.

## 20. Completion criteria

- E0–E6 datasets and runs are reproducible.
- Synthetic share/weight/split constraints pass adversarial tests.
- Real primary and hard-bucket reports include confidence intervals.
- Required ablations identify where DAZ helps, is neutral, or harms.
- The chosen mixture has a written evidence record and tested rollback.
- No synthetic diagnostic or count is presented as real gold authority.
