# Operations, Capacity, Backup, Security, and Cost

## 1. Operating target

Run the DAZ generator unattended on Kevin's local machine while protecting MaskFactory workloads,
preventing disk exhaustion, preserving reproducibility records, and avoiding unexpected billable
actions.

## 2. Resource model

Track per scene and pass profile:

- DAZ startup and asset-load seconds;
- simulation/geometry/render/decode/QA/package seconds;
- GPU seconds and peak VRAM;
- peak RAM and CPU;
- read/write bytes and temporary peak;
- pristine RGB, semantic, diagnostic, and rejected bytes;
- retry count and wasted resource cost.

Capacity forecasts use measured p50/p95/p99, not estimates.

## 3. Storage formula

~~~text
retained_bytes =
  accepted_scenes × mean_retained_bytes_per_scene
  + rejected_debug_retention
  + active_temporary_peak
  + registry/mapping/recipe/evidence
  + backup_copies
  + free_space_reserve
~~~

Report projections for 1k, 10k, 50k, 100k, and 1M scenes under minimal, standard, relationship, and full
diagnostic profiles.

## 4. Initial capacity posture

At blueprint inspection, F had approximately 361.6 GiB free. That supports development and a bounded
pilot, not an assumed large corpus. Before the 10,000-scene run:

1. render at least 100 representative scenes;
2. measure all file classes and temporary peaks;
3. apply proposed retention/compression;
4. reserve space for retries and one recovery copy;
5. calculate hard maximum queue commitment;
6. obtain Kevin's decision before any paid storage expansion.

## 5. Disk thresholds

Configure both GiB and percentage thresholds:

| Level | Default action |
|---|---|
| normal | schedule within reservation budget |
| soft floor | stop creating new long-horizon plans; finish leased jobs |
| hard floor | drain new render leases; allow validation/package cleanup |
| emergency floor | stop DAZ processes after safe checkpoint; preserve DB/recipes/logs |

Actual values are chosen after pilot measurement. A job reserves expected temporary and retained bytes
before lease.

## 6. Retention classes

| Class | Contents | Default |
|---|---|---|
| R0 permanent-small | configs, schemas, registry snapshots, mappings, recipes, manifests, hashes | retain |
| R1 accepted authority | semantic maps and pristine source for active datasets | retain while referenced |
| R2 rebuildable accepted | depth/normals/diagnostics/debug scenes | policy-based |
| R3 derived variants | degradations/thumbnails/caches | regenerate/delete first |
| R4 rejected evidence | compact report + representative crops/logs | bounded days/count |
| R5 temporary | partial renders, decode scratch, simulations | delete after terminal state |
| R6 installers/cache | locally recoverable packages/shaders/textures | user-configured |

No retention action deletes an artifact referenced by an active dataset/model without first producing a
dependency report.

## 7. Safe retention workflow

1. compute immutable candidate list;
2. exclude live leases and protected references;
3. print dry-run by class, bytes, age, and dependency;
4. verify R0 exclusion and minimum recovery set;
5. atomically mark selected rows;
6. delete only the exact resolved paths under registered roots;
7. record outcome and freed bytes;
8. reconcile database/file inventory;
9. alert on partial failure.

## 8. GPU and process scheduling

- One machine-level lease covers DAZ rendering, MaskFactory inference, and training.
- CPU scanning/recipe/decoding may run concurrently within RAM/IO limits.
- Interactive MaskFactory work can receive a higher-priority reservation.
- Scheduler supports quiet hours, maximum daily GPU hours, temperature/power limits, and pause/drain.
- DAZ worker does not silently switch renderers or compete for VRAM.
- GPU/VRAM admission leases do not exist; worker/data ownership recovery remains independent.

## 9. Worker lifecycle

Initial mode is one job per DAZ process for isolation. Promote to a persistent worker only after:

- no scene-state leakage across a large fixture sequence;
- memory/VRAM growth remains bounded;
- crash recovery is equivalent;
- periodic clean restart is implemented;
- time saved materially exceeds added risk.

Persistent workers restart by job count, elapsed time, memory threshold, or runtime warning.

## 10. Queue operations

Supported operations:

- enqueue bounded plan;
- pause planning;
- pause new leases;
- drain active jobs;
- cancel unleased jobs;
- retry reason-specific failures;
- reprioritize coverage demands;
- recover expired leases;
- rebuild queue state from manifests/events;
- disable DAZ intake while retaining history.

No cancellation presents a partial scene as accepted.

## 11. Monitoring

### Machine

- F free/reserved/committed bytes;
- C free space;
- GPU utilization/VRAM/temperature;
- CPU/RAM/IO;
- DAZ and worker process health.

### Pipeline

- queue depth and oldest age;
- stage duration p50/p95/p99;
- first-pass/eventual acceptance;
- retry/rejection by code;
- worker crashes/timeouts/prompts;
- semantic replay and package verification;
- accepted scenes/person instances per hour.

### Coverage and corpus

- deficit cells;
- label/pose/view/person-count distribution;
- asset/product dominance;
- near-duplicate rate;
- bytes and GPU hours per useful coverage unit.

## 12. Alerts

| Severity | Examples | Action |
|---|---|---|
| info | new asset snapshot, planned maintenance | report |
| warning | soft disk floor, rising retry, stale certificate | pause planning/investigate |
| high | hard disk floor, repeated crash, mapping mismatch | drain affected work |
| critical | corrupt DB, accepted semantic defect, source files in Git | stop DAZ ingestion and preserve evidence |

Alerts are local by default. Any external notification integration is separately configured and uses no
DAZ source content.

## 13. Daily report

Include:

- start/end backlog and active leases;
- attempted/accepted/rejected/retried scenes and people;
- runtime/GPU/storage totals;
- top failure codes/assets/combinations;
- coverage gained and remaining deficits;
- replay/package integrity;
- disk forecast and retention recommendation;
- asset/mapping/runtime changes;
- downstream package/dataset counts;
- explicit actions needed.

## 14. Backup classes

### Tier A — essential small state

- F root/control config;
- registry snapshots and migrations;
- mapping bundles and golden-fixture metadata;
- recipes, scene manifests, certificates, output hash maps;
- queue/event history;
- dataset/model manifests;
- code Git references and environment/runtime snapshots.

### Tier B — accepted semantic authority

- pristine RGB used by active datasets;
- instance/PART/MATERIAL/protected maps;
- required coverage alpha;
- accepted package reports.

### Tier C — rebuildable bulk

- depth/normals/diagnostics;
- RGB variants;
- rejected renders;
- caches and simulations;
- installers where redownload/reinstall is practical.

## 15. Backup destinations

Primary working state is F:\DAZ. A backup is not another directory on the same volume. Use a separate
local disk or existing private backup system chosen by Kevin. The subsystem can prepare and verify a
backup plan but never starts a billable cloud service.

## 16. Restore tests

Quarterly and before major activation:

1. create an empty temporary restore root;
2. restore Tier A;
3. validate root identity/path remapping;
4. migrate and integrity-check state DB;
5. rebuild registry views;
6. resolve a frozen recipe;
7. verify mapping and package hashes;
8. restore or rebuild one Tier B scene;
9. reproduce one semantic pass;
10. verify one dataset row/model lineage;
11. record duration, missing files, and report hash.

## 17. Local security

- Credentials remain in DAZ/DIM or OS credential storage, never configs or logs.
- Worker runs with only the filesystem access it needs.
- Content is read-only to generation jobs.
- Paths are resolved under registered roots; traversal and junction escape are rejected.
- Temporary/output creation uses job-private directories and atomic promotion.
- Download/extraction is separate from the render worker.
- Logs redact usernames, account fields, and absolute portable paths.
- Source assets are excluded from Git and portable package creation.
- Hashes detect accidental modification; they do not replace backups.

## 18. Database recovery

- SQLite WAL/checkpoint schedule is explicit.
- Transactions are short; render work occurs outside DB transactions.
- Daily integrity check and snapshot run after drain/checkpoint.
- Append-only event history can reconstruct queue transitions.
- Job manifests and result files reconcile state after restore.
- Corruption recovery works on a copy; original bytes are preserved for diagnosis.

## 19. Runtime and asset updates

Updates are never silent:

1. pause affected new work;
2. snapshot old runtime/registry;
3. install/update locally;
4. create new hashes and diff;
5. revoke dependent technical certificates;
6. rerun primitive, asset, mapping, and scene fixtures;
7. compare RGB/semantic replay;
8. resume only compatible pools;
9. retain old corpus identity.

## 20. Cost controls

Local operation tracks:

- storage purchase/expansion;
- optional paid assets;
- electricity estimate from GPU hours;
- optional cloud/backup/compute;
- operator time for one-time setup.

The system may forecast costs and produce a shopping list. It cannot purchase assets, storage, cloud
capacity, or compute. Any billable action requires Kevin's explicit confirmation at that time.

## 21. Service targets

Initial measurable targets after asset stabilization:

- ≥95% unattended eventual completion for eligible recipes;
- 100% accepted semantic replay in audits;
- zero partial-output acceptance;
- queue recovery without duplicate acceptance;
- seven-day soak without unresolved interactive prompt;
- backup restore of Tier A plus one accepted scene;
- one-command pause/drain/disable;
- accurate disk forecast within ±15% after pilot calibration.

## 22. Completion criteria

- Capacity and reservation model is based on real pilot measurements.
- Disk-fill, drive-loss, GPU-contention, crash, prompt, and DB-corruption exercises pass.
- Retention dry-run and apply preserve active references.
- Tier A restore succeeds on a clean root.
- Daily reports and local alerts are actionable.
- Seven-day soak satisfies declared targets.
- No operation can independently initiate a charge.
