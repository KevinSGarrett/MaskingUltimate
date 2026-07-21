# MaskFactory Integration, Schemas, CLI, and State

## 1. Integration objective

Add DAZ as a versioned synthetic source without changing existing truth tiers, certified counts,
holdouts, ontology authority, or multi-person identity rules. DAZ remains optional and default-disabled;
normal MaskFactory intake and inference behave identically when it is disabled.

## 2. Required schema migration

Create new schema versions instead of editing historical meaning:

- add `synthetic` to source-origin vocabulary;
- add a required `synthetic_lineage` object when source origin is synthetic;
- add `annotation_authority: geometry_render`;
- add explicit `train_eligible` and `evaluation_eligible`;
- add scene/recipe/registry/runtime/mapping/pass hashes;
- add shared `scene_id`, `scene_family_id`, `image_id`, and variant group;
- add person construction and anatomy-configuration metadata;
- add visible-only/amodal separation flags;
- add synthetic sample weight;
- add an exact source-attribute value `synthetic_geometry_exact`.

Historical manifests continue to validate against their original schema.

## 3. Truth contract

Every DAZ training sample is:

~~~yaml
source_origin: synthetic
annotation_authority: geometry_render
truth_tier: weighted_pseudo_label
truth_partition: train
train_eligible: true
evaluation_eligible: false
training_loss_weight: 0.20
source_attributes: [synthetic_geometry_exact, visible_pixel_truth]
counts_as_human_anchor_gold: false
counts_as_autonomous_certified_gold: false
~~~

Weight is configurable from 0.10 through 0.25. Dataset and launcher both reject out-of-range values.

## 4. Package adapter

The adapter consumes one accepted DAZ scene package and emits MaskFactory intake records:

1. verify scene certificate and hashes;
2. load the selected ontology through the canonical loader;
3. decode shared instance/PART/MATERIAL/protected maps;
4. rank visible characters to p0–pN using the existing prominence function;
5. derive one promoted-person package per p-index;
6. derive target and other-person masks without rerendering;
7. attach source lineage and shared grouping IDs;
8. run strict PNG/value/schema checks;
9. run applicable existing QC plus DAZ checks;
10. atomically publish to `F:\DAZ\16_maskfactory_exports\intake_ready`;
11. ingest through the ordinary package boundary;
12. record the resulting MaskFactory package IDs.

## 5. Ontology integration

- Python loads the active ontology name/IDs/derived definitions once per job.
- The mapping compiler binds its bundle to the ontology snapshot hash.
- DAZ Script receives a resolved asset/facet-to-ID table; it does not define IDs.
- v1 and v2 packages use different mapping/output directories and schema declarations.
- v1 is the default.
- v2 remains inactive until the live MaskFactory project activates it independently.
- A dataset cannot mix ontology versions unless the existing dataset design explicitly supports and
  records separate heads.

## 6. S00 source adapter

Implement a DAZ-specific S00 adapter or equivalent source plugin:

~~~text
accepted DAZ scene
  -> verify source package
  -> materialize/read pristine RGB
  -> register synthetic source record
  -> emit promoted-person candidates
  -> attach exact mask authority
  -> bypass real-image mask-provider voting
  -> enter normal package/QC/dataset interfaces
~~~

The adapter bypasses mask generation providers because exact geometry maps already exist. It does not
bypass package verification, ontology checks, identity rules, split grouping, or dataset constraints.

## 7. Human-review fields

Synthetic packages must not fabricate:

- reviewer identity;
- CVAT task/job IDs;
- manual edit timestamps;
- human-review completion state;
- autonomous-certified-real evidence;
- calibration authority.

The schema represents the geometry renderer directly. Existing real-image review states remain
unchanged.

## 8. Package file map

Required minimum per promoted person:

~~~text
source_rgb.png
full_body.png
parts/<canonical-label>.png or indexed_part.png
material.png
other_person.png
protected.png
source_manifest.json
instance_manifest.json
synthetic_lineage.json
qa_report.json
hashes.json
~~~

Whether MaskFactory stores both indexed and per-label binary masks follows its active package standard.
Conversion must be lossless and derived from one indexed authority.

## 9. State database

Use a dedicated SQLite database under `F:\DAZ\10_queue` with WAL and foreign keys:

| Table | Purpose |
|---|---|
| `registry_snapshots` | immutable asset inventories |
| `assets` | current asset state |
| `asset_certificates` | smoke results bound to hashes |
| `mapping_bundles` | mapping lifecycle |
| `coverage_demands` | requested cells and priority |
| `scene_recipes` | canonical resolved recipes |
| `jobs` | queue state and attempts |
| `leases` | worker/GPU ownership and heartbeat |
| `scene_outputs` | rendered file/hash state |
| `validation_results` | normalized check outcomes |
| `scene_certificates` | accepted-scene evidence |
| `package_exports` | MaskFactory package linkage |
| `dataset_membership` | dataset snapshot rows |
| `events` | append-only operational history |

State transitions are transactions. File presence alone never advances a row.

## 10. CLI contract

~~~text
maskfactory daz doctor
maskfactory daz lineage verify
maskfactory daz assets scan|diff|list|show
maskfactory daz assets smoke [--asset-id ID|--all-eligible]
maskfactory daz assets quarantine|retest
maskfactory daz mappings build|validate|show|diff
maskfactory daz coverage report|plan
maskfactory daz recipes generate|validate|show
maskfactory daz scenes enqueue|status|cancel|replay
maskfactory daz worker run|status|pause|resume|drain
maskfactory daz validate <scene-id>
maskfactory daz package <scene-id>
maskfactory daz ingest <scene-id>
maskfactory daz dataset build|verify|card
maskfactory daz report daily|coverage|storage|assets
maskfactory daz retention plan|apply
maskfactory daz backup create|verify|restore-test
~~~

Every command supports JSON output. Mutations support dry-run where meaningful, return stable exit
codes, and never prompt during scheduled work.

## 11. Configuration files

~~~text
configs/daz/paths.yaml
configs/daz/operating_profile.yaml
configs/daz/worker.yaml
configs/daz/assets.yaml
configs/daz/mapping.yaml
configs/daz/scene_sampling.yaml
configs/daz/render_profiles.yaml
configs/daz/validation.yaml
configs/daz/coverage_axes.yaml
configs/daz/dataset.yaml
configs/daz/retention.yaml
configs/daz/alerts.yaml
~~~

Checked-in files contain defaults and schemas. Machine paths and executable locations live in untracked
local overrides or environment variables.

## 12. Doctor checks

`maskfactory daz doctor` reports independently:

- F root identity and free space;
- DAZ executable path/version/hash;
- named application instance;
- content-library registration;
- DIM/CMS visibility;
- script bundle deployment/hash;
- renderer/plugin/driver snapshot;
- queue DB integrity;
- write/read/atomic-rename test;
- primitive DAZ script execution;
- primitive render/decode;
- GPU lease interoperability;
- active ontology loader and mapping availability;
- package schema and adapter availability;
- DAZ enabled/disabled state.

Doctor is diagnostic; it does not mutate assets or launch corpus generation.

## 13. Dataset builder integration

Builder rules:

- synthetic rows are train only;
- scene family, pristine image, variants, and all person instances remain in one split;
- sample weight is explicit per row;
- synthetic image share and weighted-unit share are both reported;
- image share cannot exceed 30%;
- synthetic rows never satisfy real/certified minimum counts;
- material and source composition appear in the dataset card;
- asset/product contribution caps are checked;
- near-duplicate families cannot cross partitions;
- incompatible ontology/mapping versions cannot silently mix.

## 14. Training launcher integration

The launcher independently rechecks:

- dataset manifest and card hashes;
- source origin/truth tier/partition;
- weight range;
- synthetic image share;
- absence from validation/test/calibration inputs;
- ontology and head compatibility;
- mapping/source composition declarations;
- model/config/run lineage.

This second implementation prevents a malformed hand-built dataset from bypassing the builder.

## 15. Coverage integration

DAZ counts live in a separate synthetic namespace:

~~~text
real certified coverage
real machine-candidate coverage
DAZ accepted synthetic coverage
DAZ training membership
DAZ diagnostic performance
~~~

DAZ may consume real coverage deficits as sampling targets, but its generated counts do not close
certified-real checklist counts.

## 16. Error and exit codes

Reserve a stable range:

| Range | Meaning |
|---:|---|
| 70–79 | configuration/path/runtime |
| 80–89 | registry/asset |
| 90–99 | mapping/ontology |
| 100–109 | recipe/coverage |
| 110–119 | worker/render |
| 120–129 | validation/package |
| 130–139 | dataset/training |
| 140–149 | storage/recovery |

CLI JSON includes `code`, `reason`, `entity_ids`, `retryable`, and evidence paths.

## 17. Events and observability

Emit structured events for:

- scan started/completed/diffed;
- certificate created/revoked;
- demand/recipe created;
- job leased/heartbeat/stage/completed/failed;
- validation result and disposition;
- package exported/ingested/revoked;
- dataset built/rejected;
- training experiment linked;
- retention/backup/recovery action.

Metrics use bounded labels; asset IDs remain in logs/reports rather than high-cardinality metric labels.

## 18. Revocation propagation

If an asset, mapping, runtime, pass profile, or validator is found defective:

1. mark the bound technical certificate revoked;
2. query all descendant scenes/packages/datasets/runs;
3. prevent new use;
4. remove affected rows from future dataset snapshots;
5. mark trained models affected;
6. rerender/rebuild only after corrected versions pass;
7. retain immutable evidence of what changed.

## 19. Backward compatibility tests

- DAZ disabled produces identical CLI/config behavior for existing commands.
- Historical manifest versions validate unchanged.
- Existing package counts and dashboard formulas do not include synthetic rows.
- Existing dataset builds without DAZ remain byte-identical where deterministic.
- Existing model promotion/rollback remains functional.
- Removing the DAZ plugin/config does not corrupt normal state.

## 20. Definition of done

- New schemas, migration logic, positive/negative fixtures, and historical fixtures pass.
- DAZ source packages convert losslessly into expected MaskFactory packages.
- One through four people retain correct p-index and split grouping.
- Builder and launcher independently enforce weight, train-only, and 30% constraints.
- Synthetic data cannot claim real gold/certification/review authority.
- DAZ-disabled full MaskFactory tests remain green.
- Revocation traces from one changed mapping to every affected downstream artifact.
