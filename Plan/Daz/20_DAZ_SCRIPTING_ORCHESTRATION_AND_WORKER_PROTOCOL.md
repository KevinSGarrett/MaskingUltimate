# DAZ Scripting, Orchestration, and Worker Protocol

## 1. Design

Python is the policy/control plane. DAZ Script is the in-process scene/render execution plane. The two
communicate through schema-validated JSON and atomic files. Routine operation never requires Kevin to
open, pose, dress, texture, light, frame, or save individual scenes.

DAZ Script is appropriate because DAZ officially exposes script access to content management, asset
metadata, scene nodes, skeletons/bones, properties, geometry/materials, cameras, render managers, and
render settings. Official command-line options support named instances, script arguments, no-prompt
automation, and an experimental headless mode.

## 2. Runtime modes

### Preferred production mode: isolated hidden-GUI worker

Use a dedicated `MaskFactoryDAZ` application instance launched with no default scene and no prompts.
Hide the window through the process launcher when supported. This is preferred initially because some
renderers/plugins may not behave correctly headless.

### Headless challenger mode

`-headless` is experimental in official documentation. Enable only after the exact pinned DAZ/runtime,
renderer, and pilot asset set pass the same 1,000-scene suite as hidden-GUI mode. Promotion requires no
quality, feature, dialog, crash, or output regression and retains one-command fallback.

### Debug interactive mode

Explicit operator-only mode for mapping/asset investigation. It cannot write accepted packages without
re-running the recipe through production mode.

## 3. Process launch contract

Conceptual command:

```powershell
& $env:DAZ_STUDIO_EXE `
  -instanceName MaskFactoryDAZ `
  -noDefaultScene `
  -noPrompt `
  -logSize 100m `
  -scriptArg "F:\DAZ\10_queue\leased\<job>\scene_recipe.json" `
  -scriptArg "F:\DAZ\10_queue\leased\<job>\worker_result.partial.json" `
  "F:\DAZ\04_runtime\scripts\active\worker_main.dsa"
```

The actual tested option order and executable behavior are frozen in the runtime profile. Never pass
credentials or large JSON on the command line. Paths are quoted and verified against registered roots.

## 4. Worker isolation

- one OS process per job for highest isolation during pilot;
- optional persistent process only after leak/dirty-scene soak tests;
- unique DAZ instance name when parallel workers are later enabled;
- dedicated application settings/profile;
- explicit content roots and render directory;
- offline generation default;
- job-private temp/render directory;
- clean scene at start and verified node count zero;
- process-tree kill on timeout/popup/crash;
- no reuse of partial job state as accepted.

## 5. Queue and lease protocol

### Lease acquisition

Within one SQLite transaction:

1. select highest-priority eligible pending job;
2. revalidate operating profile, asset/mapping/runtime snapshots, capacity, and GPU policy;
3. mark `leased` with worker ID, PID placeholder, acquired/expires timestamps, attempt number;
4. create atomic lease JSON;
5. reserve expected disk bytes;
6. launch the render phase directly; no GPU/VRAM lease or checkout exists.

### Heartbeat

Worker writes at least every 15 seconds:

```json
{
  "job_id": "...",
  "worker_id": "...",
  "pid": 1234,
  "stage": "render_part_id",
  "progress": 0.61,
  "updated_at": "...",
  "output_bytes": 123456789
}
```

Heartbeat update is atomic. Scheduler reads it but does not trust progress alone; process existence and
output state are checked.

### Lease expiry

After no heartbeat beyond the stage-specific threshold:

- inspect process tree;
- terminate if still hung;
- move partial output to quarantine;
- release the job's durable disk reservation; no GPU/VRAM reservation exists;
- classify failure;
- retry only according to bounded policy.

## 6. DAZ Script module responsibilities

```text
worker_main.dsa        parse args, validate roots, sequence stages, terminal result
lib/io.dsa             strict JSON/file/hash helpers and atomic writes
lib/logging.dsa        structured events and DAZ log correlation
lib/scene.dsa          clear scene, node inventory, snapshot, cleanup
lib/assets.dsa         resolve/load assets via content manager
lib/figures.dsa        base figure, morphs, geografts, fit/follow
lib/posing.dsa         bone/property pose application and contact deltas
lib/materials.dsa      material application and reversible ID overrides
lib/cameras.dsa        camera construction/readback/framing
lib/lights.dsa         light/environment construction/readback
lib/geometry.dsa       topology, facet/material groups, bounds, contact diagnostics
lib/render.dsa         renderer/options/output configuration
lib/passes.dsa         RGB and annotation pass orchestration
lib/result.dsa         checksums, result schema, exit status
```

Modules do not decide sampling, scene-category targets, truth weights, or dataset eligibility.

## 7. Recipe validation in DAZ

Python validates before queueing; DAZ Script validates again:

- schema/version supported;
- job/scene/seed/path identity;
- all asset IDs resolve to expected relative paths/hashes;
- content roots match runtime;
- mapping/ontology/render profile supported;
- numeric values finite/in range;
- person count 1–4;
- no duplicate slot IDs;
- output directory empty/job-private;
- script bundle hash matches recipe.

DAZ Script does not attempt to “fix” an invalid recipe.

## 8. Scene assembly sequence

For each person slot:

1. load base figure using `DzContentMgr.openFile/loadAsset` through registered content;
2. identify created figure node by scene diff and asset source;
3. verify skeleton/topology/mapping family;
4. apply character/shaping presets;
5. set explicit morph properties by stable URI/name path;
6. apply skin/eye/detail materials;
7. load and fit geografts;
8. load/fit hair and wardrobe inner-to-outer;
9. apply pose and expression;
10. apply contact-solver root/joint deltas;
11. run rig adjustment/simulation profiles;
12. force geometry cache update;
13. audit final nodes/properties/topology/materials.

Then load environment/props, set support/contact transforms, create camera/lights, and frame all promoted
persons.

## 9. Asset loading

- Prefer CMS/content-manager asset resolution and native file loading.
- Resolve all paths relative to registered content roots.
- Capture before/after scene node lists to know what an asset changed.
- For material/pose presets, select the intended target explicitly.
- A preset that alters unexpected nodes, renderer, output, camera, or dimensions produces an error.
- Missing-file messages and DAZ log events are parsed into structured errors.
- Auto-install-missing is disabled; a job never downloads content during generation.

## 10. Property and morph application

Use stable property URI/name paths and verify readback. For every applied value:

- record requested and final value;
- detect controllers/auto-follow that changed other properties;
- collect all changed character-controller properties for the final configuration record;
- reject NaN/Inf/out-of-range;
- verify no locked/hidden critical property was silently ignored;
- force geometry/rig evaluation before fingerprinting.

## 11. Pose and transform application

- Figure local pose and world root transform are separate.
- Apply full/partial poses in declared priority order.
- Verify final bone rotations against the recipe tolerance.
- Preserve character-left/right bone identity.
- Compute support and contact site positions after final morph/pose.
- Record final camera-relative joint projections as diagnostics.

## 12. Simulation

Dynamic cloth/hair is opt-in per certified asset/profile:

1. set deterministic timeline, frame range, collision settings, and seed if exposed;
2. start from a declared simulation pose;
3. simulate to the final frame;
4. bake/cache result under a content-addressed key;
5. verify repeated geometry fingerprint/tolerance;
6. reject nondeterministic or failed simulations;
7. bind cache/profile hash to the scene.

Static assets require no simulation and are the initial production default.

## 13. Camera framing

Python supplies desired camera profile and target projected boxes. DAZ Script:

- creates/loads the camera;
- aims at a weighted target of promoted figures;
- solves distance/focal position to satisfy margin/prominence/crop constraints;
- reads back matrices and projected bounds;
- performs up to two bounded adjustments;
- fails rather than accepting missing/off-frame people.

## 14. Render orchestration

1. Freeze the final scene-state fingerprint.
2. Render beauty RGB with declared realistic settings.
3. Save and hash RGB.
4. Switch to annotation profile through reversible overrides or dedicated canvases.
5. Render instance, PART, MATERIAL, protected, alpha, depth, and normals in declared order.
6. Restore original materials/visibility after each override.
7. Verify final scene-state fingerprint has not changed semantically.
8. Write scene graph and final property summaries.
9. Write worker result last.

If the renderer cannot produce a required pass reliably, the job fails; no pass is guessed from another
image.

## 15. Annotation material overrides

The worker must not permanently edit vendor materials. It stores a reversible stack:

- node/material identity;
- original shader/material pointer or serialized property snapshot;
- pass-specific flat emission/unlit material;
- exact ID color;
- opacity/cutout handling;
- restoration result.

After restoration, compare material/source hashes or the appropriate runtime identity. Persistent worker
mode is forbidden until restoration tests prove no cross-job contamination.

## 16. Result protocol

DAZ Script writes `worker_result.partial.json` during work only for diagnostics. On success it writes a
complete terminal result to a new temp file and atomically renames to `worker_result.json`:

```json
{
  "schema_version": "1.0.0",
  "job_id": "job_...",
  "scene_id": "scene_...",
  "status": "success",
  "runtime_snapshot_sha256": "...",
  "script_bundle_sha256": "...",
  "scene_state_sha256": "...",
  "outputs": [{"role":"rgb_pristine","path":"...","sha256":"..."}],
  "events_file": "events.jsonl",
  "final_scene_summary": "scene_summary.json",
  "started_at": "...",
  "finished_at": "..."
}
```

Failure results name stage, reason code, retryability, last successful artifact, DAZ log hash, and scene
snapshot availability. Python validates the result before changing queue state.

## 17. Timeout profiles

Initial maximums, replaced by measured p99 plus an operating buffer:

| Stage | Timeout |
|---|---:|
| DAZ startup | 180 s |
| asset load per item | 120 s |
| scene assembly | 600 s |
| simulation | 1,800 s |
| smoke render | 300 s |
| core RGB render | 1,800 s |
| each ID pass | 600 s |
| result/finalize | 120 s |

Output growth/renderer progress can extend within a hard job ceiling; no stage runs indefinitely.

## 18. Dialog and crash handling

Official no-prompt behavior may not cover third-party plugins/scripts. The watchdog monitors:

- DAZ process responsiveness;
- top-level windows belonging to the worker process;
- application log messages;
- heartbeat age;
- renderer progress/output growth;
- crash-report directories.

Unexpected dialog behavior:

1. capture title/class/process and safe screenshot if configured;
2. do not click;
3. terminate process tree;
4. quarantine asset/combination with evidence;
5. preserve partial recipe/log;
6. retry only after a known technical suppression or asset change.

## 19. GPU/VRAM governance retirement

DAZ RGB/ID rendering uses no GPU/VRAM admission, reservation, checkout,
scheduler, capacity lease, or file-lock gate. Runtime utilization and memory
measurements are diagnostic only. A real OOM becomes a typed workload failure;
it cannot weaken annotation resolution, semantics, or quality requirements.

## 20. Persistent worker acceptance

Persistent mode requires:

- 10,000 sequential jobs without scene/material/property leakage;
- bounded memory/VRAM growth;
- clean scene verification after every job;
- same semantic hashes as process-per-job mode;
- crash recovery without losing queue authority;
- no popup increase;
- one-command fallback.

Until then, process-per-job is the production authority.

## 21. Replay

`maskfactory daz replay <scene-id>` resolves the exact recipe, asset snapshot, runtime, script, mapping,
and render profiles. It refuses replay if exact assets are unavailable unless `--diagnostic-current-assets`
is explicitly selected; such a diagnostic can never overwrite historical output. Semantic passes must
match hashes. RGB uses exact hash or a declared renderer-tolerance comparison.

## 22. Official technical references

The implementation should begin from DAZ's official scripting samples and API rather than copied forum
snippets. Relevant links are maintained in `31_OFFICIAL_SOURCE_REGISTRY.md`, including command-line
options, scripting samples, `DzContentMgr`, `DzAssetMgr`, `DzScene`, `DzSkeleton`, `DzFacetMesh`,
`DzMaterial`, `DzRenderMgr`, renderer/camera APIs, and Install Manager setup/manifests.
