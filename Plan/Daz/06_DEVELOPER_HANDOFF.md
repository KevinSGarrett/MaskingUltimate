# Developer Handoff

## 1. Mission

Implement the DAZ subsystem described in this package without weakening existing MaskFactory contracts.
The implementation must be reversible, deterministic, schema-driven, test-first for all hard validators,
and isolated from the proprietary bulk content under `F:\DAZ`.

## 2. Read-before-code order

1. Current `Plan\Instructions\00_START_HERE.md` through
   `Plan\Instructions\09_EXTERNAL_FOUNDATION_BOOTSTRAP_PLAYBOOK.md`.
2. Current `Plan\SIDE_THREAD_HANDOFF_SAM31_AUTONOMOUS_GOLD_20260713.md`.
3. Current docs 02, 04, 05, 07, 09, 12, 17, 18, 20, 21, and 22.
4. This package files 00–31.
5. Live tracker and dashboard, read through `tracker.py`; do not copy checklist state from this blueprint.

## 3. Non-negotiable implementation invariants

- Do not copy DAZ assets, textures, installers, extracted meshes, or source `.duf` files into Git.
- Do not add a fifth MaskFactory truth tier. Use `weighted_pseudo_label` plus structured synthetic
  lineage.
- Do not count DAZ packages toward certified training package, D5, human gold, or certificate evidence.
- Do not permit synthetic data in calibration/holdout paths.
- Do not exceed 30% synthetic images in any training dataset or launcher input.
- Do not mix ontology versions in a scene, package, or dataset.
- Do not hard-code ontology IDs in DAZ Script. The Python control plane emits the frozen mapping table
  generated from the canonical ontology loader.
- Do not infer v2 anatomy applicability from gender presentation. Synthetic anatomy configuration must
  be explicit and mapping-bound.
- Do not use hidden/amodal anatomy as visible PART truth.
- Do not allow two promoted people to own the same visible pixel.
- Do not rely on a UI click path for routine automation.
- Do not silently fall back to CPU renderer, another renderer, a default scene, missing texture, or an
  incompatible asset.
- Do not mutate existing MaskFactory schemas in place without versioned migration and compatibility
  fixtures.

## 4. Recommended repository layout

```text
C:\Comfy_UI_Main_Masking\
  configs\daz\
    paths.yaml
    worker.yaml
    operating_profile.yaml
    asset_policy.yaml
    scene_sampling.yaml
    render_profiles.yaml
    validation.yaml
    retention.yaml
    coverage_axes.yaml
  integrations\daz\
    scripts\
      worker_main.dsa
      lib\
        io.dsa
        logging.dsa
        scene.dsa
        assets.dsa
        figures.dsa
        posing.dsa
        materials.dsa
        cameras.dsa
        lights.dsa
        geometry.dsa
        render.dsa
        passes.dsa
        result.dsa
    README.md
  src\maskfactory\daz\
    __init__.py
    config.py
    paths.py
    schemas.py
    lineage.py
    registry.py
    dim_manifest.py
    cms_catalog.py
    fingerprints.py
    compatibility.py
    quarantine.py
    smoke.py
    mapping\
      bundle.py
      topology.py
      transfer.py
      validate.py
    coverage\
      vocabulary.py
      deficits.py
      sampler.py
    scenes\
      recipe.py
      character.py
      pose.py
      multiperson.py
      camera.py
      lighting.py
      environment.py
      constraints.py
    worker\
      launcher.py
      protocol.py
      lease.py
      watchdog.py
      gpu.py
    render\
      passes.py
      id_codec.py
      decode.py
      alpha.py
    validation\
      assets.py
      scene.py
      geometry.py
      labels.py
      multiperson.py
      replay.py
    integration\
      intake.py
      package.py
      coverage.py
      dataset.py
    reports.py
    orchestrator.py
  src\maskfactory\schemas\
    daz_asset_registry.schema.json
    daz_scene_recipe.schema.json
    daz_worker_result.schema.json
    daz_mapping_bundle.schema.json
    daz_scene_package.schema.json
    daz_smoke_certificate.schema.json
    daz_coverage_plan.schema.json
  tests\daz\
    fixtures\
    test_*.py
```

This layout is a recommendation, not authorization to reorganize unrelated modules. If the current
repository convention has evolved, preserve its style while keeping the same component boundaries.

## 5. Configuration contract

All machine-specific absolute paths live in an untracked local configuration or environment variable.
Checked-in defaults use logical roots and environment interpolation:

```yaml
schema_version: 1.0.0
enabled: false
daz_root: ${MASKFACTORY_DAZ_ROOT:-F:/DAZ}
daz_studio_executable: ${DAZ_STUDIO_EXE}
automation_instance: MaskFactoryDAZ
content_library: ${MASKFACTORY_DAZ_ROOT}/03_content/libraries/MaskFactory_DAZ_Library
asset_registry_snapshot: null
```

`enabled` remains false until technical readiness evidence is complete. Configuration loaders reject unknown keys,
relative traversal, roots outside registered locations, missing schema versions, and network paths unless
explicitly approved.

## 6. CLI surface

Implement commands under a coherent `maskfactory daz` group:

```text
maskfactory daz doctor
maskfactory daz lineage verify
maskfactory daz assets scan
maskfactory daz assets diff
maskfactory daz assets smoke [--asset-id ...] [--all-eligible]
maskfactory daz assets quarantine <asset-id> --reason <code>
maskfactory daz mappings build --figure genesis9 --ontology body_parts_v1
maskfactory daz mappings validate <mapping-id>
maskfactory daz coverage report
maskfactory daz coverage plan --count N
maskfactory daz scenes validate-recipe <path>
maskfactory daz scenes enqueue --plan <path>
maskfactory daz worker run [--once]
maskfactory daz worker status
maskfactory daz worker pause|resume|drain
maskfactory daz validate <scene-id>
maskfactory daz package <scene-id>
maskfactory daz ingest <scene-id>
maskfactory daz report daily
maskfactory daz replay <scene-id>
maskfactory daz retention plan|apply
maskfactory daz backup verify
```

Every mutation supports `--dry-run` where meaningful, prints a machine-readable summary, writes an
operation record, and returns nonzero when an engineering precondition fails. Commands must not prompt
in scheduled operation.

## 7. Schema migration requirements

### 7.1 Manifest source

Version both v1 and v2 instance schemas to add `synthetic` to `source_origin` and a required
`synthetic_lineage` block when selected. Do not reinterpret `generated`; existing packages remain
valid under their historical schema.

### 7.2 Synthetic lineage

Require:

- generator `daz_studio`;
- scene, recipe, runtime, script, renderer, asset snapshot, mapping, and pass-profile hashes;
- asset-registry and operating-profile snapshot hashes;
- promoted-person and instance mapping;
- `geometry_exact: true` only after exact-pass QA;
- `semantic_mapping_status: validated`;
- visible-only declaration;
- train-only declaration;
- no-gold-count declaration;
- parent scene family and variant group IDs.

### 7.3 Tooling and review

Current schemas require CVAT as the annotation tool. Add a versioned synthetic annotation authority
that does not invent a human review block. The package verifier must distinguish:

- human-reviewed packages;
- autonomously certified real-image packages;
- geometry-labeled synthetic weighted pseudo packages.

Do not fill `reviewer: kevin` or `human_edit: true` for synthetic data.

## 8. Implementation order

1. Schemas and negative fixtures.
2. Paths/config/doctor with subsystem disabled.
3. Operating-profile configuration and path controls.
4. DIM/filesystem catalog and registry snapshot.
5. Worker protocol using independent primitive fixtures.
6. GPU lease and watchdog.
7. Asset smoke tests.
8. Genesis 9 topology fingerprint and mapping bundle format.
9. Solo scene recipes and render passes.
10. Pass decoder and strict validation.
11. Package adapter and MaskFactory schema integration.
12. Multi-person recipes and per-instance packaging.
13. Coverage sampler and reports.
14. Dataset/training ratio and holdout guards.
15. Operational scheduler, retention, backup, and recovery.
16. Real-image ablations and activation.

Each step must leave the disabled existing system green.

## 9. Testing rules

- Use small procedurally generated primitives for CI. CI must not require DAZ store assets.
- DAZ-installed live tests are explicit opt-in and record exact local artifact hashes.
- Every hard validator has at least one seeded negative fixture proving it blocks.
- Test Windows paths with spaces, non-ASCII asset names, long paths, and case differences.
- Test stale leases, killed processes, corrupt result JSON, partial images, disk-full, renderer mismatch,
  missing texture, unknown ID, two-person overlap, left/right swap, and mapping hash drift.
- Keep all random tests seeded and emit the seed on failure.

## 10. Definition of an acceptable pull request

A DAZ implementation PR is acceptable when:

- default-disabled behavior is proven;
- no proprietary file is staged;
- schemas and fixtures are versioned;
- full existing tests remain green;
- new tests cover positive and negative paths;
- docs and CLI help match behavior;
- migrations are reversible;
- hard technical validators cannot be bypassed with a normal flag;
- generated bulk data is outside Git;
- rollback instructions are tested and included.
