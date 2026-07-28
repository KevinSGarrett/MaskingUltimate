# Scene Sampling, Coverage, and Curriculum Specification

## 1. Principle

The subsystem does not choose every asset uniformly and does not enumerate the full Cartesian product.
It samples constrained, high-value combinations that close measured MaskFactory deficits while
maintaining broad marginal and pairwise diversity.

## 2. Coverage layers

### Layer A — MaskFactory canonical coverage

- view;
- pose;
- existing attributes such as hands/feet visible, contact, hair occlusion, clothing boundary, bare skin,
  fitted/loose clothing, back visible, fingers spread/merged, and props;
- instance count: solo, duo, small group;
- active ontology label presence/visibility.

### Layer B — DAZ generation coverage

- figure generation and mapping;
- anatomy configuration combination;
- presentation;
- adult age-appearance category;
- body-shape bins;
- skin-tone/material response;
- hair construction/length/texture/occlusion;
- wardrobe state/properties/layers;
- pose subfamily and articulation;
- self/multi-person contact and occlusion;
- camera azimuth/elevation/roll/focal/framing;
- lighting/background/prop/support;
- render profile and degradation;
- asset/product family.

### Layer C — high-risk intersections

Predeclared pairwise/selected three-way cells where failures are likely.

## 3. Corpus stages

| Stage | Accepted scenes | Purpose | May train a promoted model? |
|---|---:|---|---|
| engineering fixtures | 24–100 | mapping/worker/pass correctness | no |
| pilot | 1,000 | measure rejection, storage, coverage, domain appearance | no, experimental only |
| ablation corpus | 10,000 | matched 10/20/30% experiments | challenger only |
| core corpus v1 | 50,000–100,000 | balanced targeted training source | yes after ablation acceptance |
| scale corpus | 100,000+ | deficit-driven expansion | only immutable approved versions |

Scene count alone is not proof of quality. Every stage must meet its own coverage and validation
criteria.

## 4. Scene-family selection

Select in hierarchical order:

1. target ontology/version;
2. target MaskFactory deficit/risk bucket;
3. person count and relationship family;
4. anatomy-configuration combination;
5. pose/contact/occlusion template;
6. view/camera/framing;
7. body/skin/hair/wardrobe attributes;
8. lighting/environment/prop;
9. compatible concrete assets;
10. render/degradation profile.

This avoids selecting an appealing asset combination and only afterward discovering it adds no useful
coverage.

## 5. Sampling objective

For candidate recipe `r`:

```text
utility(r) =
  0.30 * canonical_coverage_deficit_gain
  + 0.20 * high_risk_intersection_gain
  + 0.15 * label_visibility_gain
  + 0.10 * asset_diversity_gain
  + 0.10 * failure_mining_priority
  + 0.05 * domain_randomization_gain
  + 0.05 * multi_person_identity_gain
  + 0.05 * recency_need
  - incompatibility_penalty
  - dominance_penalty
  - recent_repetition_penalty
  - predicted_rejection_cost
```

Weights are versioned and benchmarked. Hard constraints are applied before scoring; a high score cannot
override mapping, compatibility, capacity, or ontology rules.

## 6. Candidate generation

- Use stratified sampling for discrete axes.
- Use Latin hypercube or low-discrepancy sampling for continuous morph/camera/light parameters.
- Use pairwise combinatorial coverage for discrete high-cardinality factors.
- Use weighted reservoir selection for concrete assets under per-asset caps.
- Generate 10–100 feasible candidates per required scene and choose by utility plus diversity.
- Record all rejected candidate reasons for diagnosing inventory constraints.

## 7. Coverage targets

### Canonical MaskFactory targets

DAZ packages do not count toward certified-gold D5 coverage, but the synthetic lane mirrors and exceeds
the same structure for training balance:

- at least 8 accepted synthetic instances per view × pose × instance-count cell for pilot diagnostics;
- at least 40 per canonical attribute in pilot;
- larger core targets scale with label rarity and risk.

### Core corpus minimums

For a 50,000-scene corpus:

- each six-view bin ≥5,000 promoted instances;
- each major pose family ≥2,000;
- each canonical attribute ≥2,000 where applicable;
- each anatomy configuration ≥15,000 person instances;
- each duo configuration ≥1,500 scenes;
- each trio configuration ≥400 scenes;
- each quartet configuration ≥200 scenes;
- each adult age-appearance category ≥5,000 person instances once inventory supports it;
- each skin-tone band ≥5,000 person instances;
- each hair length/texture major category ≥1,000 applicable instances;
- each wardrobe state ≥1,000, with unclothed/underwear/swim/fitted/loose/layered separately reported;
- each camera elevation and focal family ≥2,000 scenes;
- each major lighting/environment family ≥2,000 scenes;
- each v2 positive atomic ≥2,000 visible instances before synthetic v2 is considered mature.

These are synthetic-balance targets, not real performance proof.

## 8. High-risk required intersections

At minimum track:

- hands visible × fingers spread/merged × close/full framing;
- hand-to-body contact × each major body target;
- hands × prop grip;
- feet/toes × footwear/barefoot × low angle;
- hair length/texture × face/ear/shoulder/chest/back occlusion;
- dark/light hair × matching background contrast;
- skin-tone band × hard/back/low-key/mixed lighting;
- fitted/loose/layered clothing × profile/back/three-quarter;
- straps/waistbands/lace/sheerness × skin boundary;
- anatomy atomic × view × partial visibility × occluder type;
- adult age-appearance category × body-shape range × pose;
- wide lens × close distance × limb foreshortening;
- telephoto × multi-person depth overlap;
- duo/trio/quartet × crossed limbs × similar appearance;
- foreground/background person anatomy combination × p-index role;
- crop truncation × each limb/torso side;
- support surface × seated/kneeling/lying;
- prop occlusion × face/torso/limb.

## 9. Label visibility budgeting

The sampler predicts label visibility from pose, camera, wardrobe, and mapping before rendering, then
updates with actual pixel counts. For each label, track:

- visible instance count;
- partially visible count;
- occluded/cropped/not-applicable count;
- pixel-area histogram;
- boundary-length histogram;
- front/back/profile distribution;
- person-count/contact context;
- clothing/material context;
- asset-family diversity.

Small labels require minimum pixel and boundary thresholds. A scene where a nipple, finger, toe, or ear
is technically one pixel does not satisfy a useful positive target.

## 10. Acceptance-aware planning

Raw planned counts are not coverage. Only accepted packages update accepted coverage. The planner tracks
yield per cell:

```text
yield = accepted / attempted
cost_per_accept = total_gpu_seconds / accepted
```

Low-yield cells trigger root-cause analysis:

- insufficient compatible assets;
- mapping failure;
- camera/framing conflict;
- pose/cloth collision;
- simulation instability;
- overly strict or incorrect validator;
- physically infeasible request.

The system does not endlessly oversample a broken cell.

## 11. Failure-mining feedback

MaskFactory real-image failure clusters generate synthetic acquisition demands only when a plausible
synthetic recipe can isolate the failure. Examples:

- left/right forearm swap → asymmetric poses across views;
- finger merges → hand close-ups, contact, occlusion, varied skin/background;
- hair bleed → alpha hair over varied backgrounds/shoulders;
- clothing boundary bleed → straps, waistbands, loose/fitted layers;
- cross-person bleed → crossed-limb duo/trio recipes;
- anatomy false positives on clothing → fully reviewed synthetic clothed-negative configurations plus
  real clothed-negative holdout remains final authority.

Each demand links to the originating failure cluster but does not replace real corrected evidence.

## 12. Curriculum

### Curriculum 0 — mapping fundamentals

Neutral unclothed/clothed solo figures, controlled background/light, canonical views.

### Curriculum 1 — articulation

Broad solo poses, hands/feet, hair, basic wardrobe, modest camera variation.

### Curriculum 2 — appearance and boundaries

Body/skin/hair/wardrobe/material/light/background diversity.

### Curriculum 3 — occlusion/contact

Self-contact, props, support surfaces, truncation, strong view/foreshortening.

### Curriculum 4 — multi-person

Separated duos → overlap → contact → trios → quartets.

### Curriculum 5 — domain randomization

Complex environments, degradation, challenging light, rare asset combinations.

### Curriculum 6 — failure-targeted bursts

Short, versioned generation campaigns for current real-image failure clusters.

Training can mix curricula, but dataset cards report composition. Later curricula do not delete earlier
baseline coverage.

## 13. Duplicate and family control

One scene family includes:

- same characters/assets/body shapes/poses/geometry;
- nearby cameras from one planned bracket;
- lighting variants;
- pristine and degraded variants;
- rerenders after nonsemantic runtime changes.

All family members share a group ID. Dataset sampling caps family members and split logic treats the
family as indivisible. Even though synthetic is train-only, grouping prevents thousands of near-identical
samples from dominating training or synthetic diagnostics.

## 14. Synthetic diagnostic sets

Reserve some asset families, pose templates, environments, and seeds for synthetic diagnostics that
measure generator/mapping generalization. They remain synthetic and cannot become final model promotion
authority. The trainer must not read diagnostic IDs for model selection if they are used as a reported
evaluation set.

## 15. Rebalancing and freeze

Before dataset freeze:

1. recompute accepted coverage;
2. verify hard minimums;
3. report marginal/pairwise gaps;
4. report product/asset/family dominance;
5. report label pixel/instance distributions;
6. report rejection/yield bias;
7. downsample oversupplied cells deterministically;
8. select samples using group-aware optimization;
9. enforce ≤30% synthetic within the final MaskFactory training set;
10. freeze sample IDs, weights, registry/mapping/runtime snapshots, and card.

## 16. Reporting

Coverage reports separate:

- planned;
- attempted;
- rendered;
- accepted;
- packaged;
- dataset-selected;
- actually consumed by training.

They also separate scene count, person-instance count, and effective training weight units. None is
labeled gold count or real accuracy.
