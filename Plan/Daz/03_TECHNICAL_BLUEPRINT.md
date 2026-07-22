# Technical Blueprint

## 1. Architectural role

The DAZ subsystem is an upstream synthetic-source engine. It does not replace MaskFactory stages
S00–S15, the ontology loader, QA, truth tiers, immutable package format, dataset builder, holdouts,
training controls, or serving promotion. It creates synthetic source images and exact-to-scene annotation
evidence, then hands accepted packages to a DAZ-aware S00 adapter and the normal downstream contracts.

```text
Kevin-acquired DAZ content
        |
        v
F:\DAZ asset staging -> technical scan and qualification -> asset registry
        |                                          |
        |                              compatibility/dependency graph
        v                                          v
asset smoke workers -----------------------> eligible asset pools
                                                   |
MaskFactory coverage deficits ---------------------+
                                                   v
                                       deterministic scene planner
                                                   |
                                                   v
                                     DAZ Studio scripted worker
                                                   |
                         +-------------------------+-------------------------+
                         |                         |                         |
                      RGB pass               annotation passes       scene metadata
                         +-------------------------+-------------------------+
                                                   v
                                         synthetic scene validator
                                      reject / retry / quarantine / accept
                                                   |
                                                   v
                                      immutable synthetic scene package
                                                   |
                                                   v
                                 MaskFactory synthetic intake + normal QA
                                                   |
                                                   v
                               train-only weighted pseudo-label dataset lane
                                                   |
                                                   v
                               real-image holdout ablation and promotion decision
```

## 2. Component model

| Component | Responsibility | Proposed repository location | Bulk-data location |
|---|---|---|---|
| DAZ configuration | Paths, worker, render profiles, policies | `configs/daz/*.yaml` | none |
| Asset lineage registry | product, asset, dependency, version, and hash records | small schemas/code in repo | `F:\DAZ\01_source_records` technical records |
| Asset scanner | DIM/CMS/filesystem scan and hash inventory | `src/maskfactory/daz/assets/` | registry DB under `F:\DAZ\05_registry` |
| Compatibility engine | figure generation, dependencies, allowlists | `src/maskfactory/daz/compatibility.py` | reports/overrides under F |
| Mapping engine | topology fingerprint and ontology mapping bundles | `src/maskfactory/daz/mapping/` | frozen maps under `F:\DAZ\07_mappings` |
| Coverage planner | translates MaskFactory deficits into scene demands | `src/maskfactory/daz/coverage/` | plans under `F:\DAZ\09_generation` |
| Scene sampler | seeded constrained selection and recipe output | `src/maskfactory/daz/scenes/` | recipes/queue under F |
| Windows worker | launches/monitors DAZ Studio and leases GPU | `src/maskfactory/daz/worker/` | worker state/logs under F |
| DAZ Script runtime | scene build, pass setup, render, metadata export | `integrations/daz/scripts/` | deployed copy under `F:\DAZ\04_runtime` |
| Pass decoder | converts exact colors/canvases into integer maps | `src/maskfactory/daz/render/` | scene outputs under F |
| Scene validator | geometry/RGB/map/lineage/replay checks | `src/maskfactory/daz/validation/` | evidence under F |
| Package adapter | emits MaskFactory-compatible source/package records | `src/maskfactory/daz/integration/` | accepted packages under F |
| CLI | scan, smoke, map, plan, run, validate, package, report | additions to `src/maskfactory/cli.py` or plugin group | none |
| Scheduler | queue leasing, retries, retention, pause/resume | `src/maskfactory/daz/orchestrator.py` | queue DB under F |
| Training constraint checks | train-only, weight, ratio, and source enforcement | current dataset/training modules | versioned datasets under F/C pointers |

## 3. Process boundaries

### 3.1 Python control plane

Python owns registry/schema validation, coverage calculations, scene recipe
creation, queue leasing, process lifecycle, pass decoding, QA, packaging, reports, and MaskFactory
integration. It never manipulates DAZ content by scraping undocumented binary formats when an official
DAZ API or install manifest supplies the needed information.

### 3.2 DAZ Studio execution plane

A pinned Windows DAZ Studio installation owns asset loading, scene graph construction, posing, morph
application, fitting, simulation where enabled, camera/light creation, geometry inspection available
through the API, and rendering. Each job is supplied by an immutable JSON recipe path and produces one
machine-readable result record. Interactive UI input is not part of routine execution.

### 3.3 File protocol

The planes communicate through atomic files, not UI automation:

- Python writes `scene_recipe.json.tmp`, fsyncs, then atomically renames to `scene_recipe.json`.
- The worker creates a lease with owner PID, worker instance, heartbeat, and expiration.
- DAZ Script writes outputs to a job-private `.partial` directory.
- DAZ Script writes `worker_result.json` last, containing success/failure and all emitted paths.
- Python verifies every hash, promotes `.partial` to `rendered`, and releases the lease.
- Incomplete directories after lease expiry are quarantined, never silently resumed as accepted.

## 4. State machines

### 4.1 Asset state

```text
discovered -> inspect_pending
          -> smoke_pending -> mapped_pending -> eligible
          -> quarantined -> retest_pending -> eligible
          -> retired
```

An asset can be `eligible` only when its exact hash, dependencies, generation compatibility, scene
compatibility, mapping strategy, and smoke certificate are current. A file update invalidates
downstream certificates.

### 4.2 Scene state

```text
planned -> queued -> leased -> assembling -> geometry_checked -> rendering
       -> rendered -> validating -> accepted -> packaged -> ingested
       -> retryable_failed -> queued
       -> rejected
       -> quarantined
```

No state is inferred from the presence of an image file. State changes are transactional and bound to
evidence hashes.

### 4.3 Mapping state

```text
draft -> coverage_checked -> golden_fixture_checked -> approved -> active
      -> superseded | revoked
```

Mappings are keyed by base figure, topology fingerprint, subdivision/cage policy, ontology version,
mapping algorithm version, and any geograft fingerprint. Asset names are not sufficient keys.

## 5. Determinism contract

Every scene derives independent random streams from a root seed using named namespaces:

```text
root_seed = 1337 or job-specified seed
character_seed = H(root_seed, scene_id, "character")
pose_seed      = H(root_seed, scene_id, "pose")
camera_seed    = H(root_seed, scene_id, "camera")
lighting_seed  = H(root_seed, scene_id, "lighting")
render_seed    = H(root_seed, scene_id, "render")
degrade_seed   = H(root_seed, scene_id, "degrade")
```

The recipe stores chosen asset IDs and final numeric parameters, not merely the seed. Reproduction must
not depend on registry ordering. Exact replay requires the same DAZ build, renderer, driver-relevant
profile, assets, mappings, script bundle, render settings, and recipe hashes. Where Iray is not
bit-exact across driver versions, acceptance is based on exact annotation hashes plus declared RGB
tolerance; the non-bit-exact condition is recorded.

## 6. Truth and label authority

The annotation engine produces:

- **visible person-instance ownership**;
- **visible MaskFactory PART territory** for each promoted person;
- **visible MATERIAL ownership**;
- **protected other-person/object/support/accessory regions** from each instance's perspective;
- **depth and normal diagnostics**;
- **visible/occluded relationship metadata**;
- **optional amodal geometry diagnostics**, stored separately and barred from visible truth.

Accepted DAZ samples use:

```yaml
truth_tier: weighted_pseudo_label
truth_partition: train
training_loss_weight: 0.20  # configurable only within 0.10..0.25
source_lineage:
  kind: synthetic_geometry_exact
  semantic_mapping_status: validated
  visible_only: true
  synthetic_gold_count_eligible: false
```

This preserves the current four-tier MaskFactory contract. “Exact” means exact relative to the frozen
scene, pass, and semantic mapping. It never means human-anchor truth for real imagery.

## 7. Ontology-version behavior

- The job declares exactly one target: `body_parts_v1` or `body_parts_v2`.
- The active default remains v1 until MaskFactory's existing v2 activation bundle passes.
- A v1 job must not emit IDs 56–65 into its indexed PART map.
- A v2 job must map and validate all IDs 0–65, including explicit state behavior for anatomy that is
  not applicable or not visible.
- Synthetic geometry can know applicability, but the existing human-review-only v2 `not_applicable`
  rule means synthetic packages need a dedicated structured `synthetic_configuration_evidence` field;
  they must not impersonate human review authority.
- Generated maps use the canonical ontology loader at runtime. No DAZ script hard-codes a second list
  of label names or IDs.

## 8. Resource and concurrency architecture

- One global GPU lease coordinates DAZ rendering, MaskFactory inference, and training.
- Asset scanning, hashing, recipe generation, pass decoding, and most QA can run CPU-side while the GPU
  is idle or leased elsewhere.
- Initial deployment runs one DAZ worker. Horizontal multi-worker support is designed but disabled until
  per-instance DAZ settings, storage throughput, and GPU capacity are measured.
- The worker has wall-clock, no-heartbeat, render-progress, and output-growth timeouts.
- The scheduler pauses before F-drive free space falls below a configured hard floor.
- Queue and state DB use WAL and a single-writer pattern consistent with MaskFactory.

## 9. Security and privacy

- DAZ account credentials remain in DAZ Install Manager/approved OS credential storage, never in scene
  recipes, logs, Git, or registries.
- Product records exclude account identifiers; exported reports use stable local asset IDs and hashes.
- DAZ assets, installers, source textures, and extracted geometry never enter Git or a distributable
  MaskFactory package.
- All paths in manifests are relative to a registered root or use a logical URI. Absolute private paths
  are excluded from portable evidence.
- The subsystem makes no network calls during generation unless a separately allowlisted dependency
  requires it; default runtime is offline.

## 10. Observability

Metrics are separated by meaning:

- asset counts by state, type, generation, product family, and scene compatibility;
- scene queue depth, success, retry, rejection, quarantine, and failure taxonomy;
- render seconds, GPU seconds, peak VRAM, CPU, RAM, and bytes per pass;
- coverage demand and accepted contribution by axis and pairwise interaction;
- asset dominance and selection entropy;
- mapping confidence and boundary failure rates;
- accepted synthetic count and training weight units, never gold counts;
- storage growth, retention deletions, backup freshness, and restore tests;
- ablation deltas on real human-anchor holdouts.

No dashboard labels synthetic volume, zero-touch operation, or render QA as real-image accuracy.
