# Autonomous AI Agent Handoff

## 1. Authority

You are implementing one or more items from the DAZ blueprint. You may perform routine local coding,
tests, file generation, and non-billable technical setup described by the active work item. You may not
buy assets, incur charges, distribute project artifacts, or weaken an existing MaskFactory technical
invariant.

## 2. Mandatory start sequence

1. Read the live MaskFactory instructions and tracker workflow.
2. Rebuild/validate/report the tracker only if the main session's operating manual directs it and no
   concurrent writer conflict exists.
3. Read this package index and intake summary.
4. Read the detailed blueprint document for the active item.
5. Inspect current code and uncommitted changes; do not overwrite unrelated work.
6. Identify exact acceptance evidence before editing.
7. Confirm the DAZ subsystem remains disabled unless the active item is activation work and every
   readiness requirement is backed by evidence.

## 3. Source-of-truth hierarchy

1. Current MaskFactory approved amendments and live schemas/tests.
2. This DAZ package for DAZ-specific design.
3. Official DAZ technical documentation and the locked project operating profile.
4. Code comments and examples.

If a lower source conflicts with a higher source, stop the conflicting action, record the conflict, and
follow the higher source. Do not improvise around a tested technical invariant.

## 4. Required reasoning record for each implementation item

Before coding, capture:

- work item and applicable sections;
- confirmed current behavior;
- intended delta;
- files likely touched;
- technical invariants affected;
- test/evidence plan;
- rollback plan;
- any assumption and how it will be verified.

After coding, record exact commands, results, hashes/reports, changed files, remaining work, and the
next item. Do not mark complete on code presence alone.

## 5. Actions you must never take autonomously

- Log into Kevin's DAZ account, buy/download paid products, or approve a charge.
- Put credentials, order records, proprietary assets, textures, or meshes into Git.
- Reclassify DAZ synthetic packages as human or autonomous-certified gold.
- place synthetic samples in any real holdout or certificate corpus;
- increase training weight above 0.25 or synthetic share above 30%;
- activate `body_parts_v2` as a side effect of DAZ support;
- expand beyond the requested adult male/female DAZ character scope without a blueprint amendment;
- infer anatomy applicability from gendered names or presentation;
- label hidden anatomy as visible truth;
- suppress a failed technical validator to increase throughput;
- make a billable cloud call without Kevin's spending approval;
- distribute any DAZ-derived dataset or trained model.

## 6. Fail-closed defaults

Treat missing or unknown values as blocking for:

- schema version;
- private/local operating-profile declaration;
- asset source and product identity needed for reproducibility;
- asset hash or dependency;
- scene category and wardrobe/anatomy configuration;
- character configuration;
- figure generation/topology;
- mapping bundle;
- renderer/script/runtime hash;
- scene recipe field;
- annotation pass;
- label ID;
- package file/hash;
- truth tier/partition/weight;
- storage or backup critical state.

An unknown is not equivalent to `false`, `not applicable`, `allowed`, or `visible`.

## 7. Working with live DAZ Studio

- Prefer the file protocol and DAZ Script over UI automation.
- Launch the named isolated instance with no default scene and no prompts.
- Never assume headless mode is reliable until the pinned runtime passes the dedicated test.
- Capture the complete DAZ log for every job.
- If a dialog appears, the watchdog must terminate the job and quarantine the triggering asset or
  combination. Do not click through an unknown dialog during unattended work.
- Never reuse a dirty scene between jobs. Start from a verified empty scene or restart the worker per
  configured isolation policy.
- Do not accept a render merely because a PNG exists; require the terminal result record and validators.

## 8. How to classify dependencies

Use `NEEDS KEVIN:` only for:

- asset purchase/download/account operation;
- spending approval;
- a truly unresolved blueprint decision after reading all applicable plan material;
- required human-anchor truth Kevin must provide under the existing MaskFactory contract.

For an item waiting on a dependency, record the reason and work on another independent item. Do not
remain idle.

## 9. Evidence quality

Good evidence names an exact artifact and result, for example:

```text
DAZ-G9-V1 mapping bundle map_g9_v1_0001 hash <sha> passed 24 golden views,
0 unknown IDs, 0 exclusive-overlap pixels, 0 left/right seeded defects missed,
using DAZ Studio <version/hash> and script bundle <hash>.
```

Bad evidence is “implemented,” “looks good,” “test passed,” or an output file without a verifier.

## 10. Handoff completeness

Before ending a session:

- release or expire worker/GPU leases;
- stop scheduled jobs you started unless the work item authorizes continued operation;
- leave no `.partial` directory presented as accepted;
- save logs/evidence in the defined project locations;
- update the live tracker only through its CLI and only for genuinely complete work;
- record remaining dependencies and exact next action;
- ensure a new agent can reproduce the result without conversation memory.
