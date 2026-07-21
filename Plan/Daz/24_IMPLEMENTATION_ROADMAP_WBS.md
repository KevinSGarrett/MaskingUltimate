# Implementation Roadmap and Work Breakdown Structure

## 1. Execution model

Work is delivered in reversible vertical increments. An item is complete only when implementation,
tests, documentation, evidence, and rollback are present. Parallel work is allowed only when it does
not share mutable registry, mapping, schema, or runtime authority.

## 2. Global completion record

Every WBS item records:

- item ID and blueprint sections;
- starting code/config/state hashes;
- exact files and schemas changed;
- commands and test results;
- evidence artifact paths and SHA-256;
- unresolved defects;
- rollback command/procedure;
- downstream items unlocked;
- tracker/log updates performed by the main project session.

## 3. Phase D0 — baseline and no-drift snapshot

| ID | Work | Depends | Required evidence |
|---|---|---|---|
| D0-01 | Read live instructions, tracker, active amendments, schemas, ontology, tests | none | dated source list |
| D0-02 | Capture dirty worktree without altering unrelated changes | D0-01 | scoped status/diff record |
| D0-03 | Run current tracker rebuild/validate/report when main workflow permits | D0-01 | dashboard hash |
| D0-04 | Run current unit/lint/schema suite | D0-01 | baseline report |
| D0-05 | Snapshot active truth tiers, splits, synthetic cap, p-index rules | D0-01 | contract fixture |
| D0-06 | Snapshot machine, drives, GPU, driver, DAZ/DIM presence | D0-01 | machine profile |
| D0-07 | Verify F:\DAZ root identity and capacity | D0-06 | path report |
| D0-08 | Freeze implementation feature flag default-disabled | D0-04 | config test |

Rollback: delete only newly created DAZ-local configuration and leave MaskFactory behavior unchanged.

## 4. Phase D1 — schemas, paths, and control plane skeleton

| ID | Work | Depends | Required evidence |
|---|---|---|---|
| D1-01 | Add DAZ config schemas and typed loader | D0 | positive/negative fixtures |
| D1-02 | Implement registered roots/path traversal checks | D1-01 | path test matrix |
| D1-03 | Create F:\DAZ directory initializer and root identity | D1-02 | dry-run/apply/diff |
| D1-04 | Add SQLite schema, WAL, migrations, integrity command | D1-01 | migration round trip |
| D1-05 | Add structured events and stable error codes | D1-04 | event fixtures |
| D1-06 | Add CLI group and JSON output contract | D1-01 | CLI snapshots |
| D1-07 | Add doctor without live mutation | D1-03,D1-06 | doctor report |
| D1-08 | Add feature disable/enable and one-command stop | D1-01 | disable test |
| D1-09 | Add repository ignore/pre-commit source-asset scan | D1-03 | seeded-file detection |
| D1-10 | Full baseline regression with DAZ disabled | D1-01..09 | zero unrelated regressions |

## 5. Phase D2 — DAZ runtime and primitive worker

| ID | Work | Depends | Required evidence |
|---|---|---|---|
| D2-01 | Install/locate and hash pinned DAZ Studio | D0-06 | runtime snapshot |
| D2-02 | Configure named MaskFactoryDAZ application instance | D2-01 | exported profile |
| D2-03 | Register dedicated F content/render paths | D1-03,D2-02 | path enumeration |
| D2-04 | Disable default scene and unexpected startup actions | D2-02 | clean-start capture |
| D2-05 | Build/deploy versioned DAZ Script bundle | D2-01 | bundle hash |
| D2-06 | Implement atomic recipe/result file protocol | D1-04,D2-05 | interrupted-write tests |
| D2-07 | Implement process launcher, log capture, timeout, watchdog | D2-06 | failure injection |
| D2-08 | Implement machine-level GPU lease | D1-04,D2-07 | contention tests |
| D2-09 | Render/decode procedural primitive without DAZ assets | D2-05..08 | golden output |
| D2-10 | Decide headless versus hidden-GUI worker from evidence | D2-09 | mode benchmark |
| D2-11 | Prove clean restart and no dirty-scene reuse | D2-09 | repeated-job fixture |

## 6. Phase D3 — asset inventory and qualification

| ID | Work | Depends | Required evidence |
|---|---|---|---|
| D3-01 | Configure DIM downloads/content library under F | D2-03 | DIM path snapshot |
| D3-02 | Parse DIM install manifests | D1-04 | parser fixtures |
| D3-03 | Add CMS query and offline fallback scan | D2-01 | online/offline comparison |
| D3-04 | Scan filesystem and canonicalize logical URIs | D3-02 | deterministic inventory |
| D3-05 | Hash assets/products and resolve duplicates/shadows | D3-04 | diff fixtures |
| D3-06 | Build closed asset taxonomy and compatibility graph | D3-03..05 | graph validation |
| D3-07 | Build dependency and required-plugin graph | D3-06 | missing/cycle fixtures |
| D3-08 | Create asset pools by generation/type/scene category | D3-06 | pool report |
| D3-09 | Implement type-specific load/fit/render smoke jobs | D2,D3-06 | representative results |
| D3-10 | Implement certificates, revocation, quarantine, retest | D3-09 | change propagation |
| D3-11 | Complete Genesis 9 pilot inventory | P-01,D3 | snapshot/certificates |

## 7. Phase D4 — topology and ontology mapping

| ID | Work | Depends | Required evidence |
|---|---|---|---|
| D4-01 | Freeze G9 neutral topology/skeleton/UV fingerprints | D3-11 | fingerprint bundle |
| D4-02 | Load canonical MaskFactory v1 ontology snapshot | D0-05 | ontology hash |
| D4-03 | Build surface/bone/weight/facet inspection exports | D2-05,D4-01 | inspection package |
| D4-04 | Create draft v1 base-facet mapping | D4-02,D4-03 | full facet coverage |
| D4-05 | Resolve left/right and small-boundary mappings | D4-04 | golden boundary views |
| D4-06 | Build MATERIAL and protected mapping tables | D4-04 | orthogonality fixtures |
| D4-07 | Test mapping across bounded morph/pose ranges | D4-04 | stress matrix |
| D4-08 | Build clothing-territory transfer compiler | D4-04,D3-09 | garment benchmark |
| D4-09 | Build hair mapping/alpha profiles | D3-09,D4-02 | hair fixtures |
| D4-10 | Build anatomy/geograft composition maps | D4-01..06 | male/female fixtures |
| D4-11 | Freeze v1 mapping bundle and validator set | D4-05..10 | P-03 completion |
| D4-12 | Draft separate inactive v2 bundle | D4-11 | no v1 leakage test |

Rollback: revoke mapping version and descendants; never edit a frozen bundle in place.

## 8. Phase D5 — character and solo-scene engine

| ID | Work | Depends | Required evidence |
|---|---|---|---|
| D5-01 | Implement canonical scene-recipe schema | D1,D3,D4 | schema fixtures |
| D5-02 | Implement named random streams and canonical JSON | D5-01 | byte-identical replay |
| D5-03 | Implement compatible figure/preset/material selection | D3-08,D5-02 | selection tests |
| D5-04 | Implement correlated body/face/age-appearance profiles | D5-03 | bounded output report |
| D5-05 | Implement skin/hair/wardrobe/anatomy selection | D3,D4,D5-03 | matrix coverage |
| D5-06 | Implement solo pose taxonomy and joint constraints | D3,D5-02 | pose stress renders |
| D5-07 | Implement cameras, framing, lights, environment, props | D5-02 | coverage fixtures |
| D5-08 | Implement collision/support/framing preflight | D5-06,D5-07 | negative fixtures |
| D5-09 | Save/read back fully resolved character/scene state | D2,D5 | replay record |
| D5-10 | Produce 24–100 solo engineering fixtures | D5-01..09 | accepted fixture set |

## 9. Phase D6 — pass renderer and semantic decoder

| ID | Work | Depends | Required evidence |
|---|---|---|---|
| D6-01 | Implement pass-profile schema and scene-state freeze | D2,D5 | mutation detection |
| D6-02 | Implement pristine RGB profile | D6-01 | renderer fixture |
| D6-03 | Implement exact instance pass | D4,D6-01 | ID codec exhaustive test |
| D6-04 | Implement exact PART pass | D4,D6-01 | all active IDs |
| D6-05 | Implement MATERIAL/protected passes | D4,D6-01 | orthogonal maps |
| D6-06 | Implement coverage alpha and hair transparency | D4-09,D6 | edge fixtures |
| D6-07 | Implement depth/normals and coordinate sidecars | D6-01 | finite/convention tests |
| D6-08 | Implement relationship/diagnostic outputs | D6-03,D6-07 | contact fixture |
| D6-09 | Implement vectorized decoder and package derivation | D6-03..08 | lossless conversion |
| D6-10 | Prove same-state pass replay | D6-01..09 | byte-identical semantic hashes |

## 10. Phase D7 — strict validation and package integration

| ID | Work | Depends | Required evidence |
|---|---|---|---|
| D7-01 | Implement V0–V9 result schema and registry | D1,D6 | contract tests |
| D7-02 | Implement recipe/assembly/geometry validators | D5,D7-01 | seeded defects |
| D7-03 | Implement pass/pixel/semantic validators | D6,D7-01 | full-image tests |
| D7-04 | Implement bounded repairs and retry budgets | D7-02,D7-03 | deterministic history |
| D7-05 | Implement acceptance certificate | D7-01..04 | certificate replay |
| D7-06 | Add MaskFactory synthetic schema versions | P-02,D1 | historical compatibility |
| D7-07 | Implement S00/package adapter | D6,D7-05,D7-06 | package fixtures |
| D7-08 | Run existing QC and DAZ-specific checks | D7-07 | QA report |
| D7-09 | Implement ingestion and revocation linkage | D1,D7-07 | descendant query |
| D7-10 | Accept and reverify 100-scene solo pilot | D7 | independent verifier |

## 11. Phase D8 — multi-person and difficult coverage

| ID | Work | Depends | Required evidence |
|---|---|---|---|
| D8-01 | Implement duo placement/overlap/contact recipes | D5,D7 | duo matrix |
| D8-02 | Implement p-index prominence after final camera | D8-01 | permutation fixtures |
| D8-03 | Implement shared-pass per-person derivation | D6,D8-02 | exact complements |
| D8-04 | Implement identity/exclusivity/bleed validators | D8-03 | seeded owner swaps |
| D8-05 | Implement reciprocal contact/occlusion records | D6-08,D8-01 | relationship fixtures |
| D8-06 | Accept separated/overlap/contact duo pilot | D8-01..05 | MM/MF/FF evidence |
| D8-07 | Add trio recipes and identity stress | D8-06 | all composition families |
| D8-08 | Add quartet recipes and identity stress | D8-07 | all composition families |
| D8-09 | Add crop, similar appearance, crossed limbs, prop contact | D8 | hard-case set |
| D8-10 | Reverify full 1–4-person pilot | D8 | zero exclusivity/bleed defects |

## 12. Phase D9 — coverage planner and autonomous corpus

| ID | Work | Depends | Required evidence |
|---|---|---|---|
| D9-01 | Implement closed coverage vocabulary | D0,D5 | schema/report |
| D9-02 | Import real MaskFactory deficit signals | D9-01 | adapter test |
| D9-03 | Implement stratified/low-discrepancy candidate generation | D5,D9-01 | distribution tests |
| D9-04 | Implement utility scoring and feasible selection | D3,D9-03 | deterministic ranking |
| D9-05 | Implement dominance/cooldown/near-duplicate limits | D9-04 | concentration report |
| D9-06 | Feed validation outcomes back to planner | D7,D9-04 | adaptive simulation |
| D9-07 | Generate 1,000-scene pilot | D8,D9 | acceptance/cost report |
| D9-08 | Calibrate storage, retry, timeout, and target sizes | D9-07 | measured profile |
| D9-09 | Generate immutable 10,000-scene ablation corpus | D9-08 | corpus hash/card |
| D9-10 | Verify coverage minima and selected intersections | D9-09 | coverage report |

## 13. Phase D10 — datasets, training, and real-image evaluation

| ID | Work | Depends | Required evidence |
|---|---|---|---|
| D10-01 | Implement builder train-only/weight/share constraints | D7,D9 | adversarial manifests |
| D10-02 | Implement independent launcher constraints | D10-01 | bypass tests |
| D10-03 | Freeze real-only baseline splits/config/seeds | P-04 | baseline bundle |
| D10-04 | Build matched 10%, 20%, 30% mixtures | D9-09,D10-01 | dataset cards |
| D10-05 | Train matched challengers | D10-03,D10-04 | run manifests |
| D10-06 | Evaluate real primary/hard-bucket metrics | D10-05 | comparison report |
| D10-07 | Run source-family/style/asset ablations | D10-05 | domain-gap analysis |
| D10-08 | Select mixture/weights only from real evidence | D10-06..07 | decision record |
| D10-09 | Test model rollback and DAZ-disable behavior | D10-08 | rollback rehearsal |

## 14. Phase D11 — unattended operations

| ID | Work | Depends | Required evidence |
|---|---|---|---|
| D11-01 | Implement scheduler, pause/resume/drain | D1,D9 | queue tests |
| D11-02 | Implement disk reservation and retention | D9-08 | fill/drain tests |
| D11-03 | Implement dashboards and alerts | D7,D11-01 | alert fixtures |
| D11-04 | Implement control/registry/mapping/recipe backups | D1,D4,D11 | restore drill |
| D11-05 | Implement package-metadata and optional bulk strategy | D11-04 | recovery matrix |
| D11-06 | Test drive loss, DB corruption, crash, popup, OOM | D11 | failure campaign |
| D11-07 | Run seven-day soak with daily restart | D11-01..06 | soak report |
| D11-08 | Rebuild registry/queue/package history after restore | D11-04..07 | clean-root evidence |
| D11-09 | Activate recurring local schedule and ceilings | D11-07 | activation record |

## 15. Phase D12 — later expansion

- Genesis 8/8.1 mapping and separate qualification.
- Additional hair/cloth simulation families.
- More complex transparent garments and layered accessories.
- Wider indoor/outdoor environment library.
- Additional render engines only through separate pass validation.
- Higher resolutions and multi-GPU workers after capacity proof.
- v2 training only after the main project activates v2.
- Other independently designed synthetic engines for domain diversity.

Each expansion starts with inventory, mapping, fixtures, pilot, and real-image ablation; no earlier
certificate is reused by asset name alone.

## 16. Critical path

~~~text
D0 -> D1 -> D2 -> D3 -> D4 -> D5 -> D6 -> D7 -> D8 -> D9 -> D10 -> D11
                  \---------------- operations work can prepare in parallel ----------------/
~~~

Asset acquisition can proceed alongside D1–D2. Schema work can proceed before assets exist. Training
cannot start until schema/package integration, a frozen corpus, and real baseline exist.

## 17. Program completion

The DAZ strategy is implemented when D0–D11 applicable items have real evidence, the 1–4-person corpus
passes semantic replay and identity checks, matched real-image ablation shows accepted benefit, the
system runs unattended for seven days, recovery succeeds from a clean target, and DAZ can be disabled
or its trained model rolled back without disrupting ordinary MaskFactory operation.
