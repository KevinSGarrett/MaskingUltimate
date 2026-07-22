# Project Intake Summary and Source-of-Truth Profile

## 1. Request interpretation

Kevin requested an exhaustive implementation blueprint for making DAZ Studio a highly autonomous
synthetic-data source for MaskFactory. The system must ingest a manually acquired DAZ asset library,
autonomously catalog and test it, generate diverse adult characters and 1–4-person scenes, render RGB
and exact geometry-derived annotations, reject defective scenes, package accepted results, and feed
them into MaskFactory's versioned training path. The plan must cover clothing and unclothed adult
anatomy, multiple body configurations and presentations, broad poses, contacts, occlusions, cameras,
lighting, environments, props, hair, materials, body shapes, and deterministic replay.

All DAZ content, generated scenes, caches, renders, annotations, and DAZ-specific dataset artifacts use
`F:\DAZ` as their canonical root. Design documents live in `C:\Comfy_UI_Main_Masking\Plan\Daz`.

## 2. Scope calibration

| Dimension | Selected scope |
|---|---|
| System class | Complex AI/data-generation subsystem integrated into a production-oriented local pipeline |
| Blueprint depth | Enterprise-complete / Level C |
| Operating profile | Private, personal, local, noncommercial, not distributed |
| Transfer target | MaskFactory developers and autonomous coding agents |
| Delivery mode | Fully drafted modular blueprint package with implementation-ready contracts |
| Human recurring work | Acquire/install assets and approve spending; no per-scene posing or mask drawing |
| Character scope | Unambiguously adult synthetic humans only |
| Scene scale | One through four promoted characters per image |
| Ontology scope | Active v1 and separately inactive v2, selected explicitly per job |

## 3. Confirmed facts

### 3.1 MaskFactory facts

- Repository root is `C:\Comfy_UI_Main_Masking`.
- The live project currently tracks 831 items and is actively changing; this DAZ blueprint must not
  overwrite the live tracker or unrelated work.
- MaskFactory uses file-based, deterministic, idempotent stages and immutable evidence.
- Active part ontology is `body_parts_v1`, IDs 0–55. `body_parts_v2`, IDs 0–65, is approved but inactive
  until its existing migration and evidence requirements pass.
- Multi-person operation promotes up to four people by default, executes per-instance pipelines, and
  requires QC-035 instance exclusivity and QC-036 cross-instance bleed hard blocks.
- Dataset splits are deterministic by `image_id`, with pHash grouping. Synthetic sources are train-only.
- Current specification limits synthetic content to at most 30% of any training set.
- Truth tiers are exactly `human_anchor_gold`, `autonomous_certified_gold`,
  `weighted_pseudo_label`, and `machine_candidate`.
- Only human-anchor holdouts may be final evaluation authority. Synthetic data cannot replace them.
- The local hardware profile includes an 8 GiB NVIDIA GPU, so DAZ rendering and MaskFactory model work
  must be serialized through one machine-level GPU lease.
- `F:\DAZ` currently exists and is empty. At blueprint time, drive F has approximately 361.6 GiB free.
- The current manifest schemas do not yet have a dedicated `source_origin: synthetic` contract. This
  requires an explicit schema migration and regression tests before DAZ package intake.

### 3.2 DAZ technical facts

- DAZ Install Manager supports separate download and content-install locations and multiple install
  paths, enabling a dedicated `F:\DAZ` library.
- Install manifests expose product name, product/store identifier, order/install timestamps, install
  path, and file lists useful for registry construction.
- DAZ Studio exposes DAZ Script, a QtScript/ECMAScript-based scripting environment integrated with the
  Studio API.
- Official APIs expose content directories, product containers, content types, asset loading, scene
  nodes, skeletons, bones, properties, geometry, face/material groups, cameras, render managers, and
  render options.
- DAZ Studio's command line supports isolated instances, script arguments, no-prompt automation, and
  an experimental headless mode. Third-party products may still display dialogs, so a watchdog and
  quarantine mechanism are mandatory.
- Iray materials include a Material ID property and Material ID canvas support, useful as one render
  mechanism, but exact MaskFactory part truth still requires controlled flat-ID passes and validation.

### 3.3 Operating-profile decision

- Kevin has declared this a private, personal, local, noncommercial project with no present or future
  distribution.
- The DAZ blueprint treats that declaration as the controlling operating profile.

## 4. Locked design decisions

1. **Personal-use operating decision:** local DAZ generation and MaskFactory training are the complete
   project scope; distribution, public hosting, and commercial use are outside scope.
2. **No autonomous purchasing:** Kevin acquires assets and approves every charge. Automation begins only
   after files are available locally.
3. **F-drive authority:** `F:\DAZ` is canonical for assets, installers, generated data, caches, and DAZ
   DVC/local-backup data. The C-drive repository stores code, small configs, schemas, registries, and
   hashes—not proprietary DAZ content or bulk renders.
4. **Generation 9 first:** Genesis 9 is the first production mapping target because one base topology
   reduces duplicated mapping work. Genesis 8/8.1 support is a later, separate mapping family and may
   not inherit G9 validation.
5. **Deterministic constrained sampling:** Randomness is seeded, bounded, compatibility-aware, and
   coverage-driven. Blind random asset combination is prohibited.
6. **One-time mapping by base topology:** Supported base figures receive frozen polygon/surface/bone
   mapping bundles. Characters, morphs, and poses inherit only when topology and mapping fingerprints
   match.
7. **Exact-to-scene, not human gold:** Geometry passes are exact for the rendered synthetic scene after
   validation, but semantic mapping and synthetic-to-real gap remain. Packages use
   `weighted_pseudo_label` with a `synthetic_geometry_exact` source attribute and a configured
   0.10–0.25 training weight.
8. **Visible truth remains visible:** Hidden/amodal body geometry is exported to a separate research
   channel and cannot become visible-mask training truth.
9. **Clothing pixels carry two orthogonal meanings:** the PART map assigns the body territory represented
   by the visible garment surface; the MATERIAL map assigns clothing. Underlying anatomy is not exposed
   or treated as visible.
10. **Render pristine first:** optical/compression degradation is applied after pristine RGB and exact
    maps are accepted; masks are transformed with exact nearest-neighbor geometry and never blurred.
11. **Asset-independent splits:** near-identical scene families and all variants of one scene seed are
    grouped so train-only synthetic variants cannot create misleading internal evaluation.
12. **No automatic promotion:** DAZ-enriched models must win ablations on untouched real human-anchor
    holdouts and hard buckets; synthetic-only gains do not authorize serving.

## 5. Assumptions requiring verification during implementation

| ID | Assumption | Verification method | Failure response |
|---|---|---|---|
| A-01 | DAZ Studio can render the required passes reliably in a dedicated automation instance | scripted pilot of 100 scenes with zero dialogs and reproducible hashes | pin another Studio version, change renderer/pass strategy, or block |
| A-02 | Genesis 9 topology remains stable for the selected base assets | hash base geometry, facet count/order, UV and bone vocabulary | create a new mapping version; never reuse by name alone |
| A-03 | Purchased pose/material/wardrobe assets expose sufficient metadata | compare DIM/CMS metadata with load-time inspection | require curated registry overrides or quarantine |
| A-04 | Hair transparency can yield stable binary visibility masks | alpha/ID tests against known fixtures | use dedicated alpha pass or exclude asset |
| A-05 | Clothing territory can be transferred from skin/body mapping accurately | rendered boundary fixtures and surface-to-body projection metrics | asset-specific map, restrict garment, or quarantine |
| A-06 | 361.6 GiB initially supports a pilot | real bytes/scene measurements | lower retention, add storage, or cap queue |
| A-07 | No third-party plugin is required for the minimum viable path | clean Studio install pilot | register the plugin as a pinned technical dependency |

## 6. Critical implementation prerequisites

| ID | Prerequisite | Owner | Can other work proceed? | Completion evidence |
|---|---|---|---|---|
| P-01 | No indexed asset inventory exists in `F:\DAZ` | Kevin + subsystem scanner | Yes: generic implementation | catalog scan and at least one qualified Genesis 9 pilot set |
| P-02 | Source-origin schema mismatch | MaskFactory developer | No DAZ package ingestion | versioned schema migration and negative/positive tests |
| P-03 | No Genesis mapping bundle has been validated | mapping implementation | No production annotation pass | frozen mapping hash and golden-render acceptance |
| P-04 | No real-image ablation result exists | training/evaluation phase | Generation can proceed; serving promotion cannot | frozen real-image benchmark certificate |

## 7. Explicit exclusions

- Autonomous asset purchasing, account login automation, or spending.
- Redistribution of DAZ assets, installers, source textures, `.duf` content, extracted meshes, or a
  DAZ-derived dataset.
- Public, commercial, or hosted operation.
- Character families outside the requested adult male/female DAZ figure scope.
- Non-human creatures, animals, fantasy anatomies, or a non-human MaskFactory ontology.
- More than four promoted people in the initial production scope.
- Video/temporal training in the initial implementation.
- Mirrors, recursive reflections, volumetric silhouettes, transparent bodies, and topology-changing
  simulations in the initial implementation.
- Treating a DAZ asset's product category, name, or marketing image as sufficient technical
  compatibility evidence.

## 8. Desired outcome

Once the subsystem meets its engineering acceptance criteria, Kevin's recurring work is limited to
selecting/acquiring assets, placing or installing them into the content library, and approving spending
decisions. The subsystem then
rescans assets, runs compatibility smoke tests, expands the coverage plan, generates and renders scenes,
validates every pass, packages accepted samples, reports coverage/storage/quality, and proposes versioned
training builds without manual character posing or mask painting.
