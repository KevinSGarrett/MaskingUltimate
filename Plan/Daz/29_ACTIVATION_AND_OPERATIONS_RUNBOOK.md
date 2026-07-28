# Activation and Operations Runbook

## 1. Scope

This runbook is the operator sequence after the implementation exists. Commands are normative examples;
the implementation must keep `--help` and this file synchronized.

## 2. First-time preparation

1. Confirm current main-project tracker/instructions.
2. Capture scoped Git status and baseline tests.
3. Confirm F:\DAZ is the intended volume and has sufficient free space.
4. Initialize the exact folder tree with dry-run, then apply.
5. Configure local environment variables:

~~~powershell
$env:MASKFACTORY_DAZ_ROOT = 'F:\DAZ'
$env:DAZ_STUDIO_EXE = '<installed DAZ Studio executable>'
~~~

6. Create the named DAZ application instance and dedicated content/render roots.
7. Deploy the versioned DAZ Script bundle.
8. Keep `enabled: false`.
9. Run doctor and save JSON evidence.

~~~powershell
maskfactory daz doctor --json
maskfactory daz lineage verify --json
~~~

## 3. Asset installation boundary

Kevin downloads/purchases assets and installs them into the dedicated content library. The autonomous
subsystem then handles:

~~~powershell
maskfactory daz assets scan --json
maskfactory daz assets diff --json
maskfactory daz assets smoke --all-eligible --json
maskfactory daz assets list --state quarantined --json
~~~

Do not manually copy repaired files into multiple content roots. If an asset requires a local metadata
override, create a versioned registry override; do not edit vendor files.

## 4. Runtime qualification

Run in order:

1. executable/version/hash check;
2. clean-scene launch;
3. primitive script execution;
4. primitive RGB render;
5. exact ID render and decode;
6. forced timeout;
7. forced unexpected-dialog fixture where practical;
8. process-kill/partial-output recovery;
9. legacy GPU-lock/lease marker present but ignored and preserved;
10. clean restart/repeat.

Store outputs under `F:\DAZ\04_runtime\runtime_snapshots\<id>` and
`F:\DAZ\08_asset_tests\jobs`.

## 5. Mapping qualification

~~~powershell
maskfactory daz mappings build --figure genesis9 --ontology body_parts_v1
maskfactory daz mappings validate <mapping-id> --json
maskfactory daz mappings show <mapping-id> --json
~~~

Review machine-generated reports for:

- topology/facet coverage;
- unmapped/duplicate territories;
- left/right fixtures;
- small-region boundaries;
- morph/pose stress;
- clothing transfer;
- hair alpha;
- male/female anatomy composition.

Freeze a new mapping version only after all required golden fixtures pass. Never edit a frozen mapping.

## 6. Engineering pilot

Generate 24–100 solo scenes:

~~~powershell
maskfactory daz coverage plan --count 100 --profile engineering
maskfactory daz scenes enqueue --plan <plan-path>
maskfactory daz worker run
maskfactory daz report daily
~~~

Then:

~~~powershell
maskfactory daz validate <scene-id>
maskfactory daz replay <scene-id>
maskfactory daz package <scene-id>
maskfactory daz ingest <scene-id>
~~~

Confirm every accepted scene has exact semantic replay and complete package hashes.

## 7. Multi-person pilot

Activate in stages:

1. duo separated;
2. duo partial overlap;
3. duo contact/crossed limbs;
4. trio separated/overlap/contact;
5. quartet separated/overlap/contact.

For each stage require all male/female composition families, construction-order permutations, p-index
prominence, mutual exclusivity, reciprocal contact, and shared split grouping.

## 8. Measured capacity calibration

After at least 100 representative scenes:

~~~powershell
maskfactory daz report storage --json
maskfactory daz retention plan --json
~~~

Record:

- bytes per output class/profile;
- temporary peak;
- seconds/GPU seconds per stage;
- retry/rejection overhead;
- 1k/10k/50k capacity projections;
- selected soft/hard/emergency floors;
- maximum committed queue size.

Do not queue the 10k corpus until the measured storage plan fits.

## 9. Corpus pilot

1. freeze registry, mapping, runtime, code, configs, coverage vocabulary;
2. create immutable plan ID;
3. reserve storage;
4. enqueue bounded batches;
5. run worker under selected schedule;
6. inspect daily reports;
7. pause automatically on hard thresholds or semantic failures;
8. freeze accepted snapshot and dataset card;
9. run independent replay sample;
10. build matched ablation datasets.

## 10. Activation procedure

Before setting `enabled: true`:

- complete readiness checklist evidence;
- pass 100-scene independent reverification;
- pass multi-person identity pilot;
- pass disk/resource/recovery exercises;
- pass seven-day soak;
- verify backup restore;
- verify one-command disable;
- verify pre-DAZ model rollback;
- record schedule, GPU hours, storage ceiling, and alert destinations.

Then:

~~~powershell
maskfactory daz doctor --json
maskfactory daz worker status --json
maskfactory daz worker resume
~~~

Enable only the bounded recurring plan; never create an unbounded queue.

## 11. Daily operation

1. Check doctor summary and disk reservation.
2. Check worker/lease health.
3. Review accepted/rejected/retry trends.
4. Review first semantic failure immediately.
5. Review top asset/combination failures.
6. Confirm coverage is moving toward declared deficits.
7. Check dominance/near-duplicate reports.
8. Confirm package/replay samples.
9. Check downstream ingestion and dataset status.
10. Preserve daily report hash.

## 12. Adding assets

~~~powershell
maskfactory daz worker drain
maskfactory daz assets scan
maskfactory daz assets diff
maskfactory daz assets smoke --all-eligible
maskfactory daz coverage report
maskfactory daz worker resume
~~~

Only affected certificates/recipes are invalidated. Existing immutable corpus versions retain their
original snapshots.

## 13. Updating DAZ Studio, renderer, plugin, or driver

1. drain worker;
2. snapshot old runtime;
3. perform local update;
4. create new runtime snapshot;
5. run primitive suite;
6. rerun affected asset/mapping fixtures;
7. compare semantic hashes and RGB tolerances;
8. create a new runtime version;
9. requeue only compatible jobs;
10. retain rollback path to prior runtime when practical.

## 14. Pause, drain, stop, and disable

~~~powershell
maskfactory daz worker pause     # stop new leases
maskfactory daz worker drain     # finish active jobs
maskfactory daz worker status
maskfactory daz worker stop      # if implemented after drain
maskfactory daz disable
~~~

Emergency stop terminates process trees and marks partial jobs recoverable/rejected; it never promotes
their files.

## 15. Common incidents

### F drive missing

- pause new work;
- do not recreate F:\DAZ on the wrong volume;
- verify volume/root identity;
- remount correct drive;
- integrity-check DB/files;
- recover expired leases;
- rerun affected jobs.

### Disk floor reached

- drain render leases;
- finish validation/package cleanup if space permits;
- run retention dry-run;
- remove approved rebuildable classes;
- reconcile free/reserved/committed bytes;
- resume with reduced bounded plan.

### DAZ prompt or hang

- let watchdog capture log/window metadata and terminate;
- quarantine triggering asset/combination;
- restart clean instance;
- reproduce once in an isolated diagnostic job;
- add a deterministic handling rule or keep excluded.

### Renderer/GPU OOM

- record the exact typed runtime failure and telemetry;
- retry only when the admitted job's ordinary bounded retry policy permits it;
- quarantine persistent scene/asset;
- do not silently switch renderer.

### Accepted semantic defect discovered

- stop DAZ ingestion;
- identify asset/mapping/runtime/validator scope;
- revoke affected certificate;
- enumerate descendant scenes, packages, datasets, runs, models;
- rebuild/rerender with a new version;
- rerun full affected QA and real regression.

### Queue DB corruption

- stop writers;
- preserve original database/WAL;
- restore latest verified snapshot to a new location;
- replay event/job manifests;
- reconcile files and states;
- verify no duplicate acceptance;
- atomically replace only after integrity tests.

## 16. Retention operation

~~~powershell
maskfactory daz retention plan --json
maskfactory daz retention apply --plan <plan-id> --dry-run
maskfactory daz retention apply --plan <plan-id>
~~~

Review bytes by class and every protected reference. Retention never follows a path outside F:\DAZ.

## 17. Backup and restore drill

~~~powershell
maskfactory daz backup create --tier A
maskfactory daz backup verify <backup-id>
maskfactory daz backup restore-test <backup-id> --target <empty-root>
~~~

The restore test must validate DB, registry, mapping, recipe, one package, one semantic replay, and one
dataset/model lineage chain.

## 18. Dataset and training operation

~~~powershell
maskfactory daz dataset build --plan <dataset-plan>
maskfactory daz dataset verify <dataset-id>
maskfactory daz dataset card <dataset-id>
~~~

Before training, verify real splits unchanged, synthetic share/weights, no synthetic evaluation rows,
scene grouping, source/mapping composition, and dataset hash. Run real-only baseline and matched
challengers under the same configuration.

## 19. Model rollback

1. pause DAZ-derived model promotion;
2. select recorded predecessor;
3. atomically restore model/lifecycle/serving config;
4. clear/rebuild compatible caches;
5. run model smoke and headline MaskFactory tests;
6. record rollback evidence;
7. leave corpus/state intact for diagnosis.

## 20. End-of-session handoff

- release/expire leases;
- stop or explicitly leave authorized jobs running;
- ensure partial outputs are marked correctly;
- save evidence under defined F paths;
- record exact commands/results/changed files;
- update tracker/log through the main project workflow;
- name remaining dependency and next actionable item;
- verify a fresh session can reproduce the state from files alone.
