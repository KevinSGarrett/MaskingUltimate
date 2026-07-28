# Section 18 — DAZ Runtime, Assets, Genesis 9 Mapping, Deterministic Scenes, and Exact Passes

**Acceptance order:** 18 of 20  
**Mapped unresolved tracker items:** 65  
**Current states:** open=17, partially_complete=48  
**Hard blockers in scope:** 0  
**Rows with explicit Kevin authority/input:** 0  
**Depends on:** Section 03, Section 04, Section 08, Section 17  
**Enables:** Section 19, Section 20

## Goal

Move the DAZ subsystem from mostly static/contract evidence to real, reproducible DAZ execution that produces exact single- and multi-person synthetic truth packages with deterministic mapping, render passes, validators, and pilots.

## Why this section exists

Sixty-five unresolved items remain across runtime, assets, Genesis 9 mapping, scene generation, render passes, validation, package integration, and multi-person pilots. These must be proven in real DAZ runs—not only schema or fixture tests.

## Scope

- Finish DAZ worker lifecycle, scripting, crash/popup/OOM control, and exact runtime snapshots.
- Acquire, register, smoke, license-review, and qualify required Genesis 9 assets.
- Complete Genesis 9 surface/node/material/rig-to-ontology mapping and ambiguity rules.
- Generate deterministic single-person and 2–4-person scenes with camera, pose, morphology, clothing, hair, contact, and crop controls.
- Render pristine RGB, instance, PART, MATERIAL/protected, alpha, depth, normals, relationship, and diagnostic passes from one frozen state.
- Decode losslessly, validate/repair with bounded history, issue acceptance certificates, ingest/revoke packages, and run solo/duo/trio/quartet pilots.

## Work packages

1. Replace static-only receipts with live DAZ worker evidence.
2. Complete asset registry and smoke matrix, including missing/partial/changed asset failure.
3. Finish mapping tables and exhaustive active-ID tests.
4. Execute deterministic recipe families and same-state pass replay.
5. Run 100-scene solo pilot and full 1–4-person pilot with zero exclusivity/bleed defects.

## Section-level testing

- DAZ clean launch/owned shutdown, popup/crash/OOM/retry/restart tests.
- Asset hash/license/path/compatibility and missing/partial/corrupt negative tests.
- Exhaustive Genesis 9 mapping, laterality, material, parent/child, and ambiguity tests.
- Scene determinism across seed, camera, pose, morphology, clothing, contact, and crop.
- Exact ID codec, orthogonal pass, alpha edge, finite depth/normal, coordinate, and same-state byte/semantic replay tests.
- V0–V9 validators, bounded repair, certificate replay, package adapter, revocation, solo and multi-person independent verification.

## Integration tests with the rest of the project

- Synthetic packages conform to the same ontology, ownership, QA, certificate, and revocation contracts as real packages.
- Section 19 consumes only accepted packages tied to real residual-gap cells.
- Section 20 can disable/rollback DAZ without affecting real-only production.

## Definition of done and acceptance criteria

- [ ] Required DAZ assets and mappings are real, current, and qualified.
- [ ] Deterministic single- and multi-person scene/pass generation works from clean state.
- [ ] Lossless decode, validation, bounded repair, certificate, package ingestion, and revocation pass.
- [ ] The 100-scene solo and 1–4-person pilots pass independent verification.
- [ ] All 65 mapped tracker items are complete.

## Required proof artifacts

- `daz_runtime_snapshot.json`
- `daz_asset_registry.json`
- `genesis9_mapping_bundle.json`
- `scene_determinism_report.json`
- `render_pass_replay_report.json`
- `daz_validation_certificate_report.json`
- `solo100_pilot_receipt.json`
- `multiperson_daz_pilot_receipt.json`
- `section_acceptance_receipt.json`

## Exit procedure

1. Run T0–T5 tests applicable to this section and preserve commands, exits, counts, environment, and hashes.
2. Verify every mapped tracker row against its own exact `Verify:` clause.
3. Produce and independently validate `section_acceptance_receipt.json`.
4. Exercise rollback/invalidation and verify zero leaked resources.
5. Update tracker rows through `Plan/Tracker/tracker.py`; regenerate dashboard/phase/profile reports.
6. Commit only section-scoped source/evidence locators and open the section PR.
7. Begin the next section only from the accepted commit.

## Mapped tracker items

| Item | Phase | Status | % | Hard blocker | Explicit user authority | Work remaining |
|---|---|---|---:|:---:|:---:|---|
| `MF-P9-03.02` | P9 | partially_complete | 75 | No | No | Configure named MaskFactoryDAZ application instance |
| `MF-P9-03.03` | P9 | partially_complete | 75 | No | No | Register dedicated F content/render paths |
| `MF-P9-03.04` | P9 | partially_complete | 75 | No | No | Disable default scene and unexpected startup actions |
| `MF-P9-03.09` | P9 | partially_complete | 70 | No | No | Render/decode procedural primitive without DAZ assets |
| `MF-P9-03.10` | P9 | partially_complete | 68 | No | No | Decide headless versus hidden-GUI worker from evidence |
| `MF-P9-03.11` | P9 | partially_complete | 68 | No | No | Prove clean restart and no dirty-scene reuse |
| `MF-P9-04.03` | P9 | partially_complete | 90 | No | No | Add CMS query and offline fallback scan |
| `MF-P9-04.04` | P9 | partially_complete | 80 | No | No | Scan filesystem and canonicalize logical URIs |
| `MF-P9-04.05` | P9 | partially_complete | 51 | No | No | Hash assets/products and resolve duplicates/shadows |
| `MF-P9-04.06` | P9 | partially_complete | 60 | No | No | Build closed asset taxonomy and compatibility graph |
| `MF-P9-04.07` | P9 | partially_complete | 75 | No | No | Build dependency and required-plugin graph |
| `MF-P9-04.08` | P9 | partially_complete | 70 | No | No | Create asset pools by generation/type/scene category |
| `MF-P9-04.09` | P9 | partially_complete | 60 | No | No | Implement type-specific load/fit/render smoke jobs |
| `MF-P9-04.10` | P9 | partially_complete | 72 | No | No | Implement certificates, revocation, quarantine, retest |
| `MF-P9-04.11` | P9 | open | 0 | No | No | Complete Genesis 9 pilot inventory |
| `MF-P9-05.01` | P9 | open | 0 | No | No | Freeze G9 neutral topology/skeleton/UV fingerprints |
| `MF-P9-05.03` | P9 | open | 0 | No | No | Build surface/bone/weight/facet inspection exports |
| `MF-P9-05.04` | P9 | open | 0 | No | No | Create draft v1 base-facet mapping |
| `MF-P9-05.05` | P9 | open | 0 | No | No | Resolve left/right and small-boundary mappings |
| `MF-P9-05.06` | P9 | open | 0 | No | No | Build MATERIAL and protected mapping tables |
| `MF-P9-05.07` | P9 | open | 0 | No | No | Test mapping across bounded morph/pose ranges |
| `MF-P9-05.08` | P9 | open | 0 | No | No | Build clothing-territory transfer compiler |
| `MF-P9-05.09` | P9 | open | 0 | No | No | Build hair mapping/alpha profiles |
| `MF-P9-05.10` | P9 | open | 0 | No | No | Build anatomy/geograft composition maps |
| `MF-P9-05.11` | P9 | open | 0 | No | No | Freeze v1 mapping bundle and validator set |
| `MF-P9-05.12` | P9 | partially_complete | 88 | No | No | Draft separate inactive v2 bundle |
| `MF-P9-06.01` | P9 | partially_complete | 60 | No | No | Implement canonical scene-recipe schema |
| `MF-P9-06.02` | P9 | partially_complete | 73 | No | No | Implement named random streams and canonical JSON |
| `MF-P9-06.03` | P9 | partially_complete | 60 | No | No | Implement compatible figure/preset/material selection |
| `MF-P9-06.04` | P9 | partially_complete | 65 | No | No | Implement correlated body/face/age-appearance profiles |
| `MF-P9-06.05` | P9 | partially_complete | 65 | No | No | Implement skin/hair/wardrobe/anatomy selection |
| `MF-P9-06.06` | P9 | partially_complete | 65 | No | No | Implement solo pose taxonomy and joint constraints |
| `MF-P9-06.07` | P9 | partially_complete | 65 | No | No | Implement cameras, framing, lights, environment, props |
| `MF-P9-06.08` | P9 | partially_complete | 70 | No | No | Implement collision/support/framing preflight |
| `MF-P9-06.09` | P9 | partially_complete | 70 | No | No | Save/read back fully resolved character/scene state |
| `MF-P9-06.10` | P9 | partially_complete | 65 | No | No | Produce 24–100 solo engineering fixtures |
| `MF-P9-07.01` | P9 | partially_complete | 70 | No | No | Implement pass-profile schema and scene-state freeze |
| `MF-P9-07.02` | P9 | partially_complete | 70 | No | No | Implement pristine RGB profile |
| `MF-P9-07.03` | P9 | partially_complete | 70 | No | No | Implement exact instance pass |
| `MF-P9-07.04` | P9 | partially_complete | 70 | No | No | Implement exact PART pass |
| `MF-P9-07.05` | P9 | partially_complete | 70 | No | No | Implement MATERIAL/protected passes |
| `MF-P9-07.06` | P9 | partially_complete | 70 | No | No | Implement coverage alpha and hair transparency |
| `MF-P9-07.07` | P9 | partially_complete | 70 | No | No | Implement depth/normals and coordinate sidecars |
| `MF-P9-07.08` | P9 | partially_complete | 70 | No | No | Implement relationship/diagnostic outputs |
| `MF-P9-07.09` | P9 | partially_complete | 70 | No | No | Implement vectorized decoder and package derivation |
| `MF-P9-07.10` | P9 | partially_complete | 70 | No | No | Prove same-state pass replay |
| `MF-P9-08.01` | P9 | partially_complete | 88 | No | No | Implement V0–V9 result schema and registry |
| `MF-P9-08.02` | P9 | partially_complete | 88 | No | No | Implement recipe/assembly/geometry validators |
| `MF-P9-08.03` | P9 | partially_complete | 88 | No | No | Implement pass/pixel/semantic validators |
| `MF-P9-08.04` | P9 | partially_complete | 88 | No | No | Implement bounded repairs and retry budgets |
| `MF-P9-08.05` | P9 | partially_complete | 88 | No | No | Implement acceptance certificate |
| `MF-P9-08.07` | P9 | partially_complete | 88 | No | No | Implement S00/package adapter |
| `MF-P9-08.08` | P9 | partially_complete | 88 | No | No | Run existing QC and DAZ-specific checks |
| `MF-P9-08.09` | P9 | partially_complete | 88 | No | No | Implement ingestion and revocation linkage |
| `MF-P9-08.10` | P9 | open | 0 | No | No | Accept and reverify 100-scene solo pilot |
| `MF-P9-09.01` | P9 | partially_complete | 85 | No | No | Implement duo placement/overlap/contact recipes |
| `MF-P9-09.02` | P9 | partially_complete | 85 | No | No | Implement p-index prominence after final camera |
| `MF-P9-09.03` | P9 | partially_complete | 85 | No | No | Implement shared-pass per-person derivation |
| `MF-P9-09.04` | P9 | partially_complete | 85 | No | No | Implement identity/exclusivity/bleed validators |
| `MF-P9-09.05` | P9 | partially_complete | 85 | No | No | Implement reciprocal contact/occlusion records |
| `MF-P9-09.06` | P9 | open | 0 | No | No | Accept separated/overlap/contact duo pilot |
| `MF-P9-09.07` | P9 | open | 0 | No | No | Add trio recipes and identity stress |
| `MF-P9-09.08` | P9 | open | 0 | No | No | Add quartet recipes and identity stress |
| `MF-P9-09.09` | P9 | open | 0 | No | No | Add crop, similar appearance, crossed limbs, prop contact |
| `MF-P9-09.10` | P9 | open | 0 | No | No | Reverify full 1–4-person pilot |

## Tracker-item exact verification text

### `MF-P9-03.02` — DAZ runtime and worker

- **Current:** `partially_complete` at 75%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 34
- **Requirement:** Configure named MaskFactoryDAZ application instance · Verify: exported profile · Blocked by: D2-01
- **Existing evidence to preserve/revalidate:** Closed MaskFactoryDAZ hidden-GUI profile exported to F:\DAZ\04_runtime\app_profiles\MaskFactoryDAZ\profile.json (SHA-256 397b8f92b0314a3c30f6e219c2201cef4efc998339aad35f8c6f0dd97a76dacb); live probe withheld because unmanaged/default DAZ PID 50884 was already running.

### `MF-P9-03.03` — DAZ runtime and worker

- **Current:** `partially_complete` at 75%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 35
- **Requirement:** Register dedicated F content/render paths · Verify: path enumeration · Blocked by: D1-03,D2-02
- **Existing evidence to preserve/revalidate:** Closed runtime profile and worker script register only F:\DAZ\03_content\libraries\MaskFactory_DAZ_Library and MaskFactory_User_Library; exported profile enumerates both. Live DAZ enumeration remains pending with D2-02 probe.

### `MF-P9-03.04` — DAZ runtime and worker

- **Current:** `partially_complete` at 75%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 36
- **Requirement:** Disable default scene and unexpected startup actions · Verify: clean-start capture · Blocked by: D2-02
- **Existing evidence to preserve/revalidate:** Launcher tests prove -noDefaultScene/-noPrompt and hidden process flags; bundle refuses prompts or any non-empty startup scene. Live clean-start capture remains pending with D2-02 probe.

### `MF-P9-03.09` — DAZ runtime and worker

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 41
- **Requirement:** Render/decode procedural primitive without DAZ assets · Verify: golden output · Blocked by: D2-05..08
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: host-side procedural primitive render/decode without DAZ assets. Module src/maskfactory/daz/render/procedural_primitive.py + schema daz_procedural_primitive_bundle; deterministic analytic_front_plane RGB/instance/PART + depth/normals EXR; golden hash verify; CLI build/verify; refuses live_daz/assets/accepted/training/gold. Published qa/fixtures/daz/procedural_primitives/daz_proc_prim_7c6483dd52c97066ea085e19/. Evidence: qa/live_verification/daz_procedural_primitive_static_20260719.json sha256 073ae1fac520451f11ff82d6bec544e8f46667269e12a32827f548f5ddf2661f. Not live DAZ Studio primitive smoke; completion withheld until D2 live worker primitive pass.

### `MF-P9-03.10` — DAZ runtime and worker

- **Current:** `partially_complete` at 68%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 42
- **Requirement:** Decide headless versus hidden-GUI worker from evidence · Verify: mode benchmark · Blocked by: D2-09
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: host-side worker mode decision retains hidden_gui as production mode; headless remains challenger and is refused without live mode benchmark. Module src/maskfactory/daz/worker_isolation_static.py + schema daz_worker_mode_decision_static_report; build_daz_command refuses non-hidden_gui / persistent_worker / -headless injection. Evidence: qa/live_verification/daz_worker_isolation_static_20260719.json file sha256 3ff10e1370c66c8ebcc13871b25bb4fcf27742c1b2bb49ad36863870d600984c; mode seal 3d47ab0874ae7cb2805c46764522e8668cc11b7f9c1545250165d07176f55a0a. Not live mode benchmark; headless not promoted.

### `MF-P9-03.11` — DAZ runtime and worker

- **Current:** `partially_complete` at 68%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 43
- **Requirement:** Prove clean restart and no dirty-scene reuse · Verify: repeated-job fixture · Blocked by: D2-09
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: clean-restart / no dirty-scene reuse host fixture contract. Module src/maskfactory/daz/worker_isolation_static.py + schema daz_clean_restart_static_report; binds process_per_job, persistent_worker=false, startup_scene_empty (worker_main.dsa startup_scene_not_empty), refuse parallel DAZ, job-private state, partial-not-accepted, repeated-job isolation. Evidence: qa/live_verification/daz_worker_isolation_static_20260719.json clean seal 58307bd7619761853c75287f430a32bee192c77a06e2ba170a9266880134ae0e. Not live repeated-job DAZ Studio fixture.

### `MF-P9-04.03` — Asset acquisition, registry, smoke, and qualification

- **Current:** `partially_complete` at 90%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 48
- **Requirement:** Add CMS query and offline fallback scan · Verify: online/offline comparison · Blocked by: D2-01
- **Existing evidence to preserve/revalidate:** Read-only local CMS adapter and explicit offline filesystem fallback are schema-valid and tested; live online snapshot cms_e94a27f9cabb4d19fd8423f0 observed 17 installed products and 4,677 content rows, and forced offline snapshot cms_offline_b58d776345e759643d279621 declares all metadata gaps. Autonomous source lineage now invalidates any stored complete fingerprint immediately when a source becomes pending. Final live online/offline path comparison remains pending a stable registered-root filesystem inventory after active acquisitions quiesce.

### `MF-P9-04.04` — Asset acquisition, registry, smoke, and qualification

- **Current:** `partially_complete` at 80%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 49
- **Requirement:** Scan filesystem and canonicalize logical URIs · Verify: deterministic inventory · Blocked by: D3-02
- **Existing evidence to preserve/revalidate:** Resumable state-schema-2 scanner registers content_primary, content_user, and legacy_dim independently; it canonicalizes root-relative paths and DAZ logical URIs, never follows reparse points, requeues directory drift, reconciles deleted children, and refuses final publication while incomplete. Current checkpoint: 7,794 content-primary directories complete, 66 pending, one user-root and one legacy-DIM root pending, zero failed; 41,094 observed primary files / 38,792,501,179 bytes. Autonomous source directory has 638 manifests; the bounded index has 489 indexed, six queued, zero failed, and 143 not yet discovered at its last refresh. Queue has 635 complete, 514 queued, 211 paused; F is soft-held at 140.407 GiB. Cross-source joins remain disabled until all roots and manifests stabilize. Evidence: qa/reports/daz_asset_observation_progress_20260716.json.

### `MF-P9-04.05` — Asset acquisition, registry, smoke, and qualification

- **Current:** `partially_complete` at 51%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 50
- **Requirement:** Hash assets/products and resolve duplicates/shadows · Verify: diff fixtures · Blocked by: D3-04
- **Existing evidence to preserve/revalidate:** Identity state remains durably checkpointed at 2,859 complete and zero failures. Capacity guard is soft with new_work_allowed=false; full suite 1,811/1,811. Evidence: qa/reports/daz_asset_identity_progress_20260716.json.

### `MF-P9-04.06` — Asset acquisition, registry, smoke, and qualification

- **Current:** `partially_complete` at 60%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 51
- **Requirement:** Build closed asset taxonomy and compatibility graph · Verify: graph validation · Blocked by: D3-03..05
- **Existing evidence to preserve/revalidate:** Graph node/hash, summary, and edge-resolution tampering fixtures fail closed; normalized plugin inputs reproduce verifiable portable graph identity. Six focused catalog tests and 1,811/1,811 full tests pass. Evidence: qa/reports/daz_qualified_pool_selection_20260716.json.

### `MF-P9-04.07` — Asset acquisition, registry, smoke, and qualification

- **Current:** `partially_complete` at 75%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 52
- **Requirement:** Build dependency and required-plugin graph · Verify: missing/cycle fixtures · Blocked by: D3-06
- **Existing evidence to preserve/revalidate:** Graph integrity tamper tests and downstream consumer tests pass; required dependencies must also carry active qualification before selection. Full suite 1,811/1,811. Evidence: qa/reports/daz_qualified_pool_selection_20260716.json.

### `MF-P9-04.08` — Asset acquisition, registry, smoke, and qualification

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 53
- **Requirement:** Create asset pools by generation/type/scene category · Verify: pool report · Blocked by: D3-06
- **Existing evidence to preserve/revalidate:** Active/stale certificate projection, missing-lineage refusal, static-vs-qualified separation, tamper detection, and certificate-aware CLI publication pass. Six focused pool tests and 1,811/1,811 full tests pass. Evidence: qa/reports/daz_qualified_pool_selection_20260716.json.

### `MF-P9-04.09` — Asset acquisition, registry, smoke, and qualification

- **Current:** `partially_complete` at 60%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 54
- **Requirement:** Implement type-specific load/fit/render smoke jobs · Verify: representative results · Blocked by: D2,D3-06
- **Existing evidence to preserve/revalidate:** Twenty-two smoke/qualification tests cover every known non-unknown asset class, mapping-required refusal, pass/fail evaluation, binding/process/semantic drift, immutable CLI publication, and certificate issue. Full suite 1,797/1,797. Evidence: qa/reports/daz_asset_smoke_qualification_20260716.json.

### `MF-P9-04.10` — Asset acquisition, registry, smoke, and qualification

- **Current:** `partially_complete` at 72%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 55
- **Requirement:** Implement certificates, revocation, quarantine, retest · Verify: change propagation · Blocked by: D3-09
- **Existing evidence to preserve/revalidate:** Certificate projection includes active/excluded identities and hash lineage, feeds qualified pools through the CLI, and refuses missing current runtime/script bindings. Full suite 1,811/1,811. Evidence: qa/reports/daz_qualified_pool_selection_20260716.json.

### `MF-P9-04.11` — Asset acquisition, registry, smoke, and qualification

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 56
- **Requirement:** Complete Genesis 9 pilot inventory · Verify: snapshot/certificates · Blocked by: P-01,D3

### `MF-P9-05.01` — Genesis 9 ontology mapping

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 59
- **Requirement:** Freeze G9 neutral topology/skeleton/UV fingerprints · Verify: fingerprint bundle · Blocked by: D3-11

### `MF-P9-05.03` — Genesis 9 ontology mapping

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 61
- **Requirement:** Build surface/bone/weight/facet inspection exports · Verify: inspection package · Blocked by: D2-05,D4-01

### `MF-P9-05.04` — Genesis 9 ontology mapping

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 62
- **Requirement:** Create draft v1 base-facet mapping · Verify: full facet coverage · Blocked by: D4-02,D4-03

### `MF-P9-05.05` — Genesis 9 ontology mapping

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 63
- **Requirement:** Resolve left/right and small-boundary mappings · Verify: golden boundary views · Blocked by: D4-04

### `MF-P9-05.06` — Genesis 9 ontology mapping

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 64
- **Requirement:** Build MATERIAL and protected mapping tables · Verify: orthogonality fixtures · Blocked by: D4-04

### `MF-P9-05.07` — Genesis 9 ontology mapping

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 65
- **Requirement:** Test mapping across bounded morph/pose ranges · Verify: stress matrix · Blocked by: D4-04

### `MF-P9-05.08` — Genesis 9 ontology mapping

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 66
- **Requirement:** Build clothing-territory transfer compiler · Verify: garment benchmark · Blocked by: D4-04,D3-09

### `MF-P9-05.09` — Genesis 9 ontology mapping

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 67
- **Requirement:** Build hair mapping/alpha profiles · Verify: hair fixtures · Blocked by: D3-09,D4-02

### `MF-P9-05.10` — Genesis 9 ontology mapping

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 68
- **Requirement:** Build anatomy/geograft composition maps · Verify: male/female fixtures · Blocked by: D4-01..06

### `MF-P9-05.11` — Genesis 9 ontology mapping

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 69
- **Requirement:** Freeze v1 mapping bundle and validator set · Verify: P-03 completion · Blocked by: D4-05..10

### `MF-P9-05.12` — Genesis 9 ontology mapping

- **Current:** `partially_complete` at 88%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 70
- **Requirement:** Draft separate inactive v2 bundle · Verify: no v1 leakage test · Blocked by: D4-11
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: build_v2_ontology_snapshot + publish_v2_ontology_snapshot + schema daz_ontology_v2_snapshot; activation_status=approved_design_not_active; mapping_authority=false; appended IDs 56..64; refuses v1 source and body_parts_v1 path leakage. Fixture publish under qa/fixtures/daz/ontology_v2_inactive_snapshots/. Evidence: qa/live_verification/daz_inactive_v2_ontology_snapshot_static_20260719.json. No live DAZ facet mapping / production activation claimed.

### `MF-P9-06.01` — Deterministic scene generation

- **Current:** `partially_complete` at 60%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 73
- **Requirement:** Implement canonical scene-recipe schema · Verify: schema fixtures · Blocked by: D1,D3,D4
- **Existing evidence to preserve/revalidate:** STATIC_PASS adjacent to MF-P9-06.10 v1.1: each engineering fixture embeds seal/validate-complete synthetic resolved recipes via seal_resolved_scene_recipe; schema/stream/camera/crop invariants fixture-proven. Evidence: qa/live_verification/daz_engineering_fixture_set_v11_static_20260719.json. No live mapping or rendered scenes claimed.

### `MF-P9-06.02` — Deterministic scene generation

- **Current:** `partially_complete` at 73%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 74
- **Requirement:** Implement named random streams and canonical JSON · Verify: byte-identical replay · Blocked by: D5-01
- **Existing evidence to preserve/revalidate:** STATIC_PASS adjacent to MF-P9-06.10 v1.1: stream_contract equals REQUIRED_RANDOM_STREAMS; stub and resolved-recipe stream recomputation fail-closed; CLI build/validate replay idempotent. Evidence: qa/live_verification/daz_engineering_fixture_set_v11_static_20260719.json. No live DAZ claimed.

### `MF-P9-06.03` — Deterministic scene generation

- **Current:** `partially_complete` at 60%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 75
- **Requirement:** Implement compatible figure/preset/material selection · Verify: selection tests · Blocked by: D3-08,D5-02
- **Existing evidence to preserve/revalidate:** Six selection tests cover deterministic ranking, compatible pairs, tone filtering, unqualified dependencies, empty qualified pools, tamper replay, static/qualified separation, and idempotent CLI publication. Full suite 1,811/1,811. Evidence: qa/reports/daz_qualified_pool_selection_20260716.json.

### `MF-P9-06.04` — Deterministic scene generation

- **Current:** `partially_complete` at 65%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 76
- **Requirement:** Implement correlated body/face/age-appearance profiles · Verify: bounded output report · Blocked by: D5-03
- **Existing evidence to preserve/revalidate:** An 800-profile report measured body tiers 50.625/34.545/14.830%, face tiers 51.7102/33.8807/14.4091%, maximum target deviation 1.7102 points, correlations 0.430586-0.774863, and passing bounds/continuity constraints. Seven focused and 1,818 full tests passed; see qa/reports/daz_character_profiles_20260716.json.

### `MF-P9-06.05` — Deterministic scene generation

- **Current:** `partially_complete` at 65%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 77
- **Requirement:** Implement skin/hair/wardrobe/anatomy selection · Verify: matrix coverage · Blocked by: D3,D4,D5-03
- **Existing evidence to preserve/revalidate:** Closed deterministic appearance selector covers two anatomy configurations, all 14 adult wardrobe states, and hair none/required for 56 matrix cells. It requires runtime-qualified assets, exact foundation replay, asset-specific anatomy/wardrobe mappings, dependency/base compatibility, deterministic cloth behavior, and inner-to-outer layering; tamper and immutable-publication refusals pass. 62/62 focused and 1,880/1,880 full repository tests pass. Evidence: qa/reports/daz_character_appearance_selection_20260716.json. Live DAZ fit/simulation/mapping readback remains pending.

### `MF-P9-06.06` — Deterministic scene generation

- **Current:** `partially_complete` at 65%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 78
- **Requirement:** Implement solo pose taxonomy and joint constraints · Verify: pose stress renders · Blocked by: D3,D5-02
- **Existing evidence to preserve/revalidate:** Closed deterministic solo-pose planner covers six major families and all 49 blueprint subfamilies through runtime-qualified Genesis 9 assets. Normalized descriptors bind canonical bone rotations, DAZ-runtime property limits, root/support/contact/visibility/occlusion/asymmetry metadata, hand/foot validity, intersection score, conversion lineage, and mandatory source/final readback. Joint values must be finite, remain inside exact recorded runtime bounds with a 0.25-degree margin and <=0.98 utilization, and partial-pose ownership conflicts require deterministic declared priority. 62/62 focused, 143 combined scene-planning, and 1,942/1,942 full repository tests pass. Evidence: qa/reports/daz_solo_pose_selection_20260716.json. Completion is withheld until live qualified descriptors, DAZ stress renders, support/intersection checks, and final joint readback exist.

### `MF-P9-06.07` — Deterministic scene generation

- **Current:** `partially_complete` at 65%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 79
- **Requirement:** Implement cameras, framing, lights, environment, props · Verify: coverage fixtures · Blocked by: D5-02
- **Existing evidence to preserve/revalidate:** Closed deterministic image-formation selector covers eight azimuth bins, six elevation bins, four roll bins, seven focal families, 12 framing profiles, seven aspect ratios, five resolution profiles, three beauty DOF modes, all 22 lighting profiles, seven exposure profiles, 21 environment subfamilies, four context complexities, and all four prop modes. Only runtime-qualified, compatible assets are selectable; environment restrictions, mutation prohibitions, stable prop object IDs/anchors, annotation-effect-off rules, camera/asset readback, projected bbox/prominence, and prop preflight are mandatory. 117/117 focused and 2,059/2,059 full repository tests pass. Evidence: qa/reports/daz_scene_formation_selection_20260716.json. Completion is withheld until live DAZ readback, accepted RGB/annotation passes, framing/prominence validation, and prop/contact geometry exist.

### `MF-P9-06.08` — Deterministic scene generation

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 80
- **Requirement:** Implement collision/support/framing preflight · Verify: negative fixtures · Blocked by: D5-06,D5-07
- **Existing evidence to preserve/revalidate:** Fail-closed solo-scene geometry preflight now recomputes upstream selection identities, enforces final camera/crop lineage, exact person count, the existing 4% promotion floor, all 10 solo framing profiles, six collision categories, broad-to-narrow collision evaluation, declared support contacts, intended-contact distance/normal/penetration, stable prop identity/anchors/occlusion, and a two-revision deterministic repair budget. All 40 focused negative/positive fixtures, 300 combined scene-planning tests, and 2,099/2,099 full repository tests pass. Evidence: qa/reports/daz_scene_preflight_20260716.json. Completion is withheld until actual DAZ final-scene geometry, collision, projected bbox/prominence, support/prop contact, and bounded repair evidence exist.

### `MF-P9-06.09` — Deterministic scene generation

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 81
- **Requirement:** Save/read back fully resolved character/scene state · Verify: replay record · Blocked by: D2,D5
- **Existing evidence to preserve/revalidate:** Final-state sealer now recomputes every upstream selection/report hash and cross-link, requires accepted geometry preflight, exact selected asset roles, applied property/controller/joint readback, exact camera/light/environment/prop state, empty startup scene, zero unexpected nodes or unresolved textures, and a scene-state fingerprint over hierarchy, geometry, transforms, materials, visibility, renderer, and pass profile. A second semantic evaluation and post-annotation-override restore must reproduce the same hash. 21/21 focused and 2,120/2,120 full repository tests pass. Evidence: qa/reports/daz_resolved_scene_state_20260716.json. Completion is withheld until real qualified DAZ readback and replay/restore hashes exist.

### `MF-P9-06.10` — Deterministic scene generation

- **Current:** `partially_complete` at 65%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 82
- **Requirement:** Produce 24–100 solo engineering fixtures · Verify: accepted fixture set · Blocked by: D5-01..09
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: published 100-fixture unrendered engineering set daz_engineering_fixture_set_754ed9a8dbb2f59882457b41 under schema 1.1.0 (24/48/72 retained). Evidence: qa/live_verification/daz_engineering_fixture_set_100_static_20260719.json sha256 b2b2a78cfdacde7253f4e9f07e591fe1f12f1d3ffcf9f995902bf3dd9390197f. Never accepted/rendered; D5 path still required.

### `MF-P9-07.01` — Exact render passes and decoding

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 85
- **Requirement:** Implement pass-profile schema and scene-state freeze · Verify: mutation detection · Blocked by: D2,D5
- **Existing evidence to preserve/revalidate:** qa/reports/daz_render_pass_profiles_20260716.json; 41/41 focused and 2161/2161 full tests; Ruff/Black/diff clean

### `MF-P9-07.02` — Exact render passes and decoding

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 86
- **Requirement:** Implement pristine RGB profile · Verify: renderer fixture · Blocked by: D6-01
- **Existing evidence to preserve/revalidate:** qa/reports/daz_pristine_rgb_20260716.json; 52/52 focused and 2215/2215 full tests; Ruff/Black/diff clean

### `MF-P9-07.03` — Exact render passes and decoding

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 87
- **Requirement:** Implement exact instance pass · Verify: ID codec exhaustive test · Blocked by: D4,D6-01
- **Existing evidence to preserve/revalidate:** qa/reports/daz_instance_pass_20260716.json; exhaustive 0-65535 codec; 44/44 focused and 2259/2259 full tests; Ruff/Black/diff clean

### `MF-P9-07.04` — Exact render passes and decoding

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 88
- **Requirement:** Implement exact PART pass · Verify: all active IDs · Blocked by: D4,D6-01
- **Existing evidence to preserve/revalidate:** qa/reports/daz_part_pass_20260716.json; all active v1 IDs 0-53; 48/48 focused and 2307/2307 full tests; Ruff/Black/diff clean

### `MF-P9-07.05` — Exact render passes and decoding

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 89
- **Requirement:** Implement MATERIAL/protected passes · Verify: orthogonal maps · Blocked by: D4,D6-01
- **Existing evidence to preserve/revalidate:** 60/60 focused and 2367/2367 full repository tests pass; all 16 MATERIAL IDs and protected IDs 50-53 are exercised; every orthogonality equation, five state points, nine forbidden effects, authority/sidecar/output/replay drift, material-only profile, and idempotent CLI/publication are verified. Ruff passes; Black checks 478 files; git diff and evidence JSON validate. Evidence: qa/reports/daz_material_protected_20260716.json.

### `MF-P9-07.06` — Exact render passes and decoding

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 90
- **Requirement:** Implement coverage alpha and hair transparency · Verify: edge fixtures · Blocked by: D4-09,D6
- **Existing evidence to preserve/revalidate:** 57/57 focused and 2424/2424 full repository tests pass. Exact uint16 threshold codes, all five hair construction routes, certificate-to-scene mapping lineage, coverage/depth/node ownership, visibility overflow, hair semantic and alpha defects, five state points, nine forbidden effects, sidecars, authority/output/replay drift, and idempotent CLI/publication are verified. Ruff passes; Black checks 480 files; diff and evidence JSON validate. Evidence: qa/reports/daz_coverage_alpha_20260716.json.

### `MF-P9-07.07` — Exact render passes and decoding

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 91
- **Requirement:** Implement depth/normals and coordinate sidecars · Verify: finite/convention tests · Blocked by: D6-01
- **Existing evidence to preserve/revalidate:** 70/70 focused and 2494/2494 full repository tests pass. Perspective/orthographic analytic primitives, inverse/proper-rotation/projection conventions, real float32 EXR headers/channels, display/data windows, finite/clip/sentinel/unit-vector rules, five state points, eleven forbidden effects, sidecars, authority/output/replay drift, resealed coordinate drift, and idempotent CLI/publication are verified. Ruff passes; Black checks 482 files; JSON schemas and diff validate. Evidence: qa/reports/daz_geometry_pass_20260716.json.

### `MF-P9-07.08` — Exact render passes and decoding

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 92
- **Requirement:** Implement relationship/diagnostic outputs · Verify: contact fixture · Blocked by: D6-03,D6-07
- **Existing evidence to preserve/revalidate:** qa/reports/daz_relationship_pass_20260716.json; 62/62 focused relationship/contact tests; 2556/2556 full repository tests; Ruff pass; item files Black-clean; 113 schemas parse; immutable CLI replay pass

### `MF-P9-07.09` — Exact render passes and decoding

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 93
- **Requirement:** Implement vectorized decoder and package derivation · Verify: lossless conversion · Blocked by: D6-03..08
- **Existing evidence to preserve/revalidate:** qa/reports/daz_package_derivation_20260716.json; 25/25 focused derivation tests; 366/366 combined D6 tests; 2581/2581 full repository tests; Ruff and targeted Black pass; 115 schemas parse; CLI replay pass

### `MF-P9-07.10` — Exact render passes and decoding

- **Current:** `partially_complete` at 70%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 94
- **Requirement:** Prove same-state pass replay · Verify: byte-identical semantic hashes · Blocked by: D6-01..09
- **Existing evidence to preserve/revalidate:** qa/reports/daz_same_state_replay_20260716.json; 48/48 focused replay tests; 414/414 combined D6 exact-chain tests; 2629/2629 full repository tests; Ruff and targeted Black pass; 116 schemas parse; CLI replay pass

### `MF-P9-08.01` — Validation and MaskFactory package integration

- **Current:** `partially_complete` at 88%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 97
- **Requirement:** Implement V0–V9 result schema and registry · Verify: contract tests · Blocked by: D1,D6
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: src/maskfactory/daz/validation_static_contracts.py + schema daz_validation_static_contracts_report; CLI daz recipes seal-validation-static-contracts. Evidence qa/live_verification/daz_validation_static_contracts_20260719.json file_sha256 186646c421f8f8f208fcb321c3e09b57a5d74560a35919b7afb345cf7ea52879 seal_sha256 447b91df6a48369113689f40c480d468f0e4d45438454e77fa3ab281b1faba02 report_id dvs_447b91df6a48369113689f40. Never live DAZ Studio validation, accepted packages, MF-P9-08.10 pilot, doctor-green, gold, Main-complete, or PRODUCTION_EVIDENCE_PASS.

### `MF-P9-08.02` — Validation and MaskFactory package integration

- **Current:** `partially_complete` at 88%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 98
- **Requirement:** Implement recipe/assembly/geometry validators · Verify: seeded defects · Blocked by: D5,D7-01
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: src/maskfactory/daz/validation_static_contracts.py + schema daz_validation_static_contracts_report; CLI daz recipes seal-validation-static-contracts. Evidence qa/live_verification/daz_validation_static_contracts_20260719.json file_sha256 186646c421f8f8f208fcb321c3e09b57a5d74560a35919b7afb345cf7ea52879 seal_sha256 447b91df6a48369113689f40c480d468f0e4d45438454e77fa3ab281b1faba02 report_id dvs_447b91df6a48369113689f40. Never live DAZ Studio validation, accepted packages, MF-P9-08.10 pilot, doctor-green, gold, Main-complete, or PRODUCTION_EVIDENCE_PASS.

### `MF-P9-08.03` — Validation and MaskFactory package integration

- **Current:** `partially_complete` at 88%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 99
- **Requirement:** Implement pass/pixel/semantic validators · Verify: full-image tests · Blocked by: D6,D7-01
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: src/maskfactory/daz/validation_static_contracts.py + schema daz_validation_static_contracts_report; CLI daz recipes seal-validation-static-contracts. Evidence qa/live_verification/daz_validation_static_contracts_20260719.json file_sha256 186646c421f8f8f208fcb321c3e09b57a5d74560a35919b7afb345cf7ea52879 seal_sha256 447b91df6a48369113689f40c480d468f0e4d45438454e77fa3ab281b1faba02 report_id dvs_447b91df6a48369113689f40. Never live DAZ Studio validation, accepted packages, MF-P9-08.10 pilot, doctor-green, gold, Main-complete, or PRODUCTION_EVIDENCE_PASS.

### `MF-P9-08.04` — Validation and MaskFactory package integration

- **Current:** `partially_complete` at 88%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 100
- **Requirement:** Implement bounded repairs and retry budgets · Verify: deterministic history · Blocked by: D7-02,D7-03
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: src/maskfactory/daz/validation_static_contracts.py + schema daz_validation_static_contracts_report; CLI daz recipes seal-validation-static-contracts. Evidence qa/live_verification/daz_validation_static_contracts_20260719.json file_sha256 186646c421f8f8f208fcb321c3e09b57a5d74560a35919b7afb345cf7ea52879 seal_sha256 447b91df6a48369113689f40c480d468f0e4d45438454e77fa3ab281b1faba02 report_id dvs_447b91df6a48369113689f40. Never live DAZ Studio validation, accepted packages, MF-P9-08.10 pilot, doctor-green, gold, Main-complete, or PRODUCTION_EVIDENCE_PASS.

### `MF-P9-08.05` — Validation and MaskFactory package integration

- **Current:** `partially_complete` at 88%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 101
- **Requirement:** Implement acceptance certificate · Verify: certificate replay · Blocked by: D7-01..04
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: src/maskfactory/daz/validation_static_contracts.py + schema daz_validation_static_contracts_report; CLI daz recipes seal-validation-static-contracts. Evidence qa/live_verification/daz_validation_static_contracts_20260719.json file_sha256 186646c421f8f8f208fcb321c3e09b57a5d74560a35919b7afb345cf7ea52879 seal_sha256 447b91df6a48369113689f40c480d468f0e4d45438454e77fa3ab281b1faba02 report_id dvs_447b91df6a48369113689f40. Never live DAZ Studio validation, accepted packages, MF-P9-08.10 pilot, doctor-green, gold, Main-complete, or PRODUCTION_EVIDENCE_PASS.

### `MF-P9-08.07` — Validation and MaskFactory package integration

- **Current:** `partially_complete` at 88%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 103
- **Requirement:** Implement S00/package adapter · Verify: package fixtures · Blocked by: D6,D7-05,D7-06
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: src/maskfactory/daz/validation_static_contracts.py + schema daz_validation_static_contracts_report; CLI daz recipes seal-validation-static-contracts. Evidence qa/live_verification/daz_validation_static_contracts_20260719.json file_sha256 186646c421f8f8f208fcb321c3e09b57a5d74560a35919b7afb345cf7ea52879 seal_sha256 447b91df6a48369113689f40c480d468f0e4d45438454e77fa3ab281b1faba02 report_id dvs_447b91df6a48369113689f40. Never live DAZ Studio validation, accepted packages, MF-P9-08.10 pilot, doctor-green, gold, Main-complete, or PRODUCTION_EVIDENCE_PASS.

### `MF-P9-08.08` — Validation and MaskFactory package integration

- **Current:** `partially_complete` at 88%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 104
- **Requirement:** Run existing QC and DAZ-specific checks · Verify: QA report · Blocked by: D7-07
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: src/maskfactory/daz/validation_static_contracts.py + schema daz_validation_static_contracts_report; CLI daz recipes seal-validation-static-contracts. Evidence qa/live_verification/daz_validation_static_contracts_20260719.json file_sha256 186646c421f8f8f208fcb321c3e09b57a5d74560a35919b7afb345cf7ea52879 seal_sha256 447b91df6a48369113689f40c480d468f0e4d45438454e77fa3ab281b1faba02 report_id dvs_447b91df6a48369113689f40. Never live DAZ Studio validation, accepted packages, MF-P9-08.10 pilot, doctor-green, gold, Main-complete, or PRODUCTION_EVIDENCE_PASS.

### `MF-P9-08.09` — Validation and MaskFactory package integration

- **Current:** `partially_complete` at 88%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 105
- **Requirement:** Implement ingestion and revocation linkage · Verify: descendant query · Blocked by: D1,D7-07
- **Existing evidence to preserve/revalidate:** STATIC_PASS only: src/maskfactory/daz/validation_static_contracts.py + schema daz_validation_static_contracts_report; CLI daz recipes seal-validation-static-contracts. Evidence qa/live_verification/daz_validation_static_contracts_20260719.json file_sha256 186646c421f8f8f208fcb321c3e09b57a5d74560a35919b7afb345cf7ea52879 seal_sha256 447b91df6a48369113689f40c480d468f0e4d45438454e77fa3ab281b1faba02 report_id dvs_447b91df6a48369113689f40. Never live DAZ Studio validation, accepted packages, MF-P9-08.10 pilot, doctor-green, gold, Main-complete, or PRODUCTION_EVIDENCE_PASS.

### `MF-P9-08.10` — Validation and MaskFactory package integration

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 106
- **Requirement:** Accept and reverify 100-scene solo pilot · Verify: independent verifier · Blocked by: D7

### `MF-P9-09.01` — Multi-person exact-synthetic truth

- **Current:** `partially_complete` at 85%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 109
- **Requirement:** Implement duo placement/overlap/contact recipes · Verify: duo matrix · Blocked by: D5,D7
- **Existing evidence to preserve/revalidate:** qa/reports/daz_duo_recipe_matrix_20260717.json; 9/9 duo cells; 78/78 focused, 393/393 adjacent, 2946/2946 full tests; Ruff and changed-surface Black pass

### `MF-P9-09.02` — Multi-person exact-synthetic truth

- **Current:** `partially_complete` at 85%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 110
- **Requirement:** Implement p-index prominence after final camera · Verify: permutation fixtures · Blocked by: D8-01
- **Existing evidence to preserve/revalidate:** qa/reports/daz_p_index_prominence_20260717.json

### `MF-P9-09.03` — Multi-person exact-synthetic truth

- **Current:** `partially_complete` at 85%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 111
- **Requirement:** Implement shared-pass per-person derivation · Verify: exact complements · Blocked by: D6,D8-02
- **Existing evidence to preserve/revalidate:** qa/reports/daz_shared_pass_d8_derivation_20260717.json

### `MF-P9-09.04` — Multi-person exact-synthetic truth

- **Current:** `partially_complete` at 85%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 112
- **Requirement:** Implement identity/exclusivity/bleed validators · Verify: seeded owner swaps · Blocked by: D8-03
- **Existing evidence to preserve/revalidate:** qa/reports/daz_multi_person_identity_validation_20260717.json

### `MF-P9-09.05` — Multi-person exact-synthetic truth

- **Current:** `partially_complete` at 85%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 113
- **Requirement:** Implement reciprocal contact/occlusion records · Verify: relationship fixtures · Blocked by: D6-08,D8-01
- **Existing evidence to preserve/revalidate:** qa/reports/daz_reciprocal_relationship_records_20260717.json

### `MF-P9-09.06` — Multi-person exact-synthetic truth

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 114
- **Requirement:** Accept separated/overlap/contact duo pilot · Verify: MM/MF/FF evidence · Blocked by: D8-01..05

### `MF-P9-09.07` — Multi-person exact-synthetic truth

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 115
- **Requirement:** Add trio recipes and identity stress · Verify: all composition families · Blocked by: D8-06

### `MF-P9-09.08` — Multi-person exact-synthetic truth

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 116
- **Requirement:** Add quartet recipes and identity stress · Verify: all composition families · Blocked by: D8-07

### `MF-P9-09.09` — Multi-person exact-synthetic truth

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 117
- **Requirement:** Add crop, similar appearance, crossed limbs, prop contact · Verify: hard-case set · Blocked by: D8

### `MF-P9-09.10` — Multi-person exact-synthetic truth

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 118
- **Requirement:** Reverify full 1–4-person pilot · Verify: zero exclusivity/bleed defects · Blocked by: D8

