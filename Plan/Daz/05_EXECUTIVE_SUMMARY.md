# Executive Summary

## 1. Recommendation

Proceed with implementation of the DAZ subsystem as a major synthetic-data source under
Kevin's locked private, personal, local, noncommercial, non-distributed operating profile. Technically,
DAZ is an unusually strong fit because it already provides
rigged figures, morphs, materials, hair, clothing, pose libraries, cameras, lights, environments, and a
scriptable renderer. Those capabilities remove much of the manual scene-building burden and make exact
geometry-aligned labels possible.

Do not treat DAZ as the sole foundation of MaskFactory accuracy. Its highest value is in controlled
coverage: rare body configurations, exact left/right, fingers and toes, adult anatomy, clothing
boundaries, self-occlusion, hand/body contact, and multi-person overlap. Real-image human-anchor
holdouts and independent model evidence remain mandatory.

## 2. Expected division of labor

### Kevin

- acquires/downloads assets and approves spending;
- installs or authorizes installation into the dedicated content library;
- supplies the real-world evaluation authority required by the existing MaskFactory plan.

### The autonomous subsystem

- scans, fingerprints, classifies, and dependency-maps assets;
- smoke-tests and quarantines assets;
- identifies coverage deficits;
- generates constrained characters and scenes;
- renders synchronized RGB and annotation passes;
- validates, repairs/retries, rejects, and packages samples;
- maintains storage, metrics, technical lineage, reports, and replay;
- builds controlled train-only dataset mixtures and evaluation proposals.

## 3. Business and technical value

- Millions of accurately labeled synthetic pixels without manual polygon drawing.
- Deterministic reproduction of failures and targeted regeneration.
- Systematic balancing of underrepresented views, poses, anatomy, body types, hair, clothing, and
  contact patterns.
- Exact per-person ownership for multi-person training.
- Exact geometry diagnostics that can expose errors in automated real-image masks.
- Lower marginal annotation cost after the initial mapping and automation investment.
- A reusable asset/test/mapping platform that can expand cautiously by figure generation.

## 4. Principal limitations

1. **Synthetic-to-real gap:** perfect synthetic labels do not guarantee photographic accuracy.
2. **Semantic mapping cost:** each supported base topology and special geograft needs validated mapping.
3. **Hair/transparency complexity:** strand and alpha hair require dedicated pass rules.
4. **Clothing territory complexity:** visible garment pixels must map to body-part territory without
   claiming hidden anatomy.
5. **Resource constraints:** the 8 GiB GPU and 361.6 GiB currently free on F require serialized rendering,
   measured retention, and likely future storage expansion for large scale.
6. **Real truth is still needed:** final calibration and promotion cannot be synthetic-only.

## 5. Initial implementation scope

The first production-capable slice should support:

- Genesis 9 base figures;
- active `body_parts_v1` mapping;
- one and two characters, expanding to three/four after identity validation passes;
- skin, material, morph, pose, camera, light, hair, wardrobe, and simple environment assets;
- static clothing and a small approved dynamic-cloth subset;
- RGB, instance, part, material, protected-object, depth, and normal passes;
- deterministic recipe/replay;
- strict asset and scene quarantine;
- MaskFactory weighted-pseudo train-only packages;
- a 100-scene engineering pilot followed by a 10,000-scene versioned corpus pilot;
- real-image ablation before any model promotion.

## 6. Resource expectations

The implementation is a multi-phase engineering program, not a one-script task. It requires:

- a DAZ Studio automation layer;
- Python orchestration and schemas;
- an asset and reproducibility registry;
- manual-once figure mapping work validated by automated fixtures;
- extensive scene/mask/replay tests;
- storage and retention management;
- training ablations on real holdouts.

At 50–250 MiB per retained scene package depending on resolution and pass set, 10,000 scenes may require
roughly 0.5–2.5 TiB before aggressive compression/retention. The initial 361.6 GiB free is suitable for
development and a measured pilot, not an unbounded million-scene archive. Capacity must be measured,
not guessed.

## 7. Success measures

### Subsystem measures

- ≥99% of accepted packages pass repeat verification.
- 100% of accepted packages have complete hashes, recipe, mapping, runtime, asset, and technical
  lineage.
- 0 accepted packages with unknown label IDs, mask/RGB dimension mismatch, cross-instance pixel
  ownership, unresolved missing assets, or incompatible character configuration.
- ≥95% unattended completion for eligible recipes after the asset library stabilizes; failures are
  honest rejects, not hidden.
- deterministic semantic pass replay for 100% of audit samples.
- no product or asset exceeds configured dominance caps.

### Model measures

- significant improvement on at least one declared real hard bucket;
- no hard-label regression beyond existing MaskFactory margins;
- no increase in left/right swap, cross-person bleed, protected-region violation, crash/OOM, or rollback
  failure;
- benefit persists when evaluated on untouched real human-anchor holdouts;
- synthetic mixing remains ≤30% and DAZ samples remain outside gold counts.

## 8. Go/no-go posture

| Decision | Status |
|---|---|
| Design and code development | Go |
| Independent synthetic fixture development | Go |
| DAZ asset cataloging after installation | Go, metadata only |
| DAZ-derived engineering smoke renders | Go after runtime and asset qualification |
| DAZ-derived local ML training/evaluation | Go after schema, mapping, and QA acceptance |
| Public/commercial/distributed use | Out of scope and no-go |
| Model promotion | No-go until real human-anchor ablation passes |
