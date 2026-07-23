# ITEMS — Phase P9 External Supervision, Reference Intelligence, and DAZ Autonomous Truth (docs 23; Daz 00–32)

> **Completion-profile scope (doc 24):** this is the optional/post-core
> `scale_daz_maturity` and independent-accuracy lane. Reference-corpus, DAZ, training, real-holdout,
> human-anchor, volume, and soak gates remain valid only for their named claims and cannot block or
> revoke `core_autonomous_runtime` or impersonate operational artifact authority.

Goal: use qualified existing labels, the governed 83k reference corpus, and exact DAZ synthetic geometry to maximize autonomous real-image mask quality while keeping human work sparse and preserving real human-anchor calibration/holdout authority.

## MF-P9-01 — Controlled baseline and safety freeze (spec: Daz 24 D0; Daz 00–32)
- [ ] MF-P9-01.01 Read live instructions, tracker, active amendments, schemas, ontology, tests · Verify: dated source list · Blocked by: none
- [ ] MF-P9-01.02 Capture dirty worktree without altering unrelated changes · Verify: scoped status/diff record · Blocked by: D0-01
- [ ] MF-P9-01.03 Run current tracker rebuild/validate/report when main workflow permits · Verify: dashboard hash · Blocked by: D0-01
- [ ] MF-P9-01.04 Run current unit/lint/schema suite · Verify: baseline report · Blocked by: D0-01
- [ ] MF-P9-01.05 Snapshot active truth tiers, splits, synthetic cap, p-index rules · Verify: contract fixture · Blocked by: D0-01
- [ ] MF-P9-01.06 Snapshot machine, drives, GPU, driver, DAZ/DIM presence · Verify: machine profile · Blocked by: D0-01
- [ ] MF-P9-01.07 Verify F:\DAZ root identity and capacity · Verify: path report · Blocked by: D0-06
- [ ] MF-P9-01.08 Freeze implementation feature flag default-disabled · Verify: config test · Blocked by: D0-04

## MF-P9-02 — Control plane foundation (spec: Daz 24 D1; Daz 00–32)
- [ ] MF-P9-02.01 Add DAZ config schemas and typed loader · Verify: positive/negative fixtures · Blocked by: D0
- [ ] MF-P9-02.02 Implement registered roots/path traversal checks · Verify: path test matrix · Blocked by: D1-01
- [ ] MF-P9-02.03 Create F:\DAZ directory initializer and root identity · Verify: dry-run/apply/diff · Blocked by: D1-02
- [ ] MF-P9-02.04 Add SQLite schema, WAL, migrations, integrity command · Verify: migration round trip · Blocked by: D1-01
- [ ] MF-P9-02.05 Add structured events and stable error codes · Verify: event fixtures · Blocked by: D1-04
- [ ] MF-P9-02.06 Add CLI group and JSON output contract · Verify: CLI snapshots · Blocked by: D1-01
- [ ] MF-P9-02.07 Add doctor without live mutation · Verify: doctor report · Blocked by: D1-03,D1-06
- [ ] MF-P9-02.08 Add feature disable/enable and one-command stop · Verify: disable test · Blocked by: D1-01
- [ ] MF-P9-02.09 Add repository ignore/pre-commit source-asset scan · Verify: seeded-file detection · Blocked by: D1-03
- [ ] MF-P9-02.10 Full baseline regression with DAZ disabled · Verify: zero unrelated regressions · Blocked by: D1-01..09

## MF-P9-03 — DAZ runtime and worker (spec: Daz 24 D2; Daz 00–32)
- [ ] MF-P9-03.01 Install/locate and hash pinned DAZ Studio · Verify: runtime snapshot · Blocked by: D0-06
- [ ] MF-P9-03.02 Configure named MaskFactoryDAZ application instance · Verify: exported profile · Blocked by: D2-01
- [ ] MF-P9-03.03 Register dedicated F content/render paths · Verify: path enumeration · Blocked by: D1-03,D2-02
- [ ] MF-P9-03.04 Disable default scene and unexpected startup actions · Verify: clean-start capture · Blocked by: D2-02
- [ ] MF-P9-03.05 Build/deploy versioned DAZ Script bundle · Verify: bundle hash · Blocked by: D2-01
- [ ] MF-P9-03.06 Implement atomic recipe/result file protocol · Verify: interrupted-write tests · Blocked by: D1-04,D2-05
- [ ] MF-P9-03.07 Implement process launcher, log capture, timeout, watchdog · Verify: failure injection · Blocked by: D2-06
- [ ] MF-P9-03.08 Retire machine-level GPU leases and prove DAZ launch is not gated by GPU/VRAM reservation, checkout, or file-lock state · Verify: legacy lock presence does not block launch · Blocked by: D1-04,D2-07
- [ ] MF-P9-03.09 Render/decode procedural primitive without DAZ assets · Verify: golden output · Blocked by: D2-05..08
- [ ] MF-P9-03.10 Decide headless versus hidden-GUI worker from evidence · Verify: mode benchmark · Blocked by: D2-09
- [ ] MF-P9-03.11 Prove clean restart and no dirty-scene reuse · Verify: repeated-job fixture · Blocked by: D2-09

## MF-P9-04 — Asset acquisition, registry, smoke, and qualification (spec: Daz 24 D3; Daz 00–32)
- [ ] MF-P9-04.01 Configure DIM downloads/content library under F · Verify: DIM path snapshot · Blocked by: D2-03
- [ ] MF-P9-04.02 Parse DIM install manifests · Verify: parser fixtures · Blocked by: D1-04
- [ ] MF-P9-04.03 Add CMS query and offline fallback scan · Verify: online/offline comparison · Blocked by: D2-01
- [ ] MF-P9-04.04 Scan filesystem and canonicalize logical URIs · Verify: deterministic inventory · Blocked by: D3-02
- [ ] MF-P9-04.05 Hash assets/products and resolve duplicates/shadows · Verify: diff fixtures · Blocked by: D3-04
- [ ] MF-P9-04.06 Build closed asset taxonomy and compatibility graph · Verify: graph validation · Blocked by: D3-03..05
- [ ] MF-P9-04.07 Build dependency and required-plugin graph · Verify: missing/cycle fixtures · Blocked by: D3-06
- [ ] MF-P9-04.08 Create asset pools by generation/type/scene category · Verify: pool report · Blocked by: D3-06
- [ ] MF-P9-04.09 Implement type-specific load/fit/render smoke jobs · Verify: representative results · Blocked by: D2,D3-06
- [ ] MF-P9-04.10 Implement certificates, revocation, quarantine, retest · Verify: change propagation · Blocked by: D3-09
- [ ] MF-P9-04.11 Complete Genesis 9 pilot inventory · Verify: snapshot/certificates · Blocked by: P-01,D3

## MF-P9-05 — Genesis 9 ontology mapping (spec: Daz 24 D4; Daz 00–32)
- [ ] MF-P9-05.01 Freeze G9 neutral topology/skeleton/UV fingerprints · Verify: fingerprint bundle · Blocked by: D3-11
- [ ] MF-P9-05.02 Load canonical MaskFactory v1 ontology snapshot · Verify: ontology hash · Blocked by: D0-05
- [ ] MF-P9-05.03 Build surface/bone/weight/facet inspection exports · Verify: inspection package · Blocked by: D2-05,D4-01
- [ ] MF-P9-05.04 Create draft v1 base-facet mapping · Verify: full facet coverage · Blocked by: D4-02,D4-03
- [ ] MF-P9-05.05 Resolve left/right and small-boundary mappings · Verify: golden boundary views · Blocked by: D4-04
- [ ] MF-P9-05.06 Build MATERIAL and protected mapping tables · Verify: orthogonality fixtures · Blocked by: D4-04
- [ ] MF-P9-05.07 Test mapping across bounded morph/pose ranges · Verify: stress matrix · Blocked by: D4-04
- [ ] MF-P9-05.08 Build clothing-territory transfer compiler · Verify: garment benchmark · Blocked by: D4-04,D3-09
- [ ] MF-P9-05.09 Build hair mapping/alpha profiles · Verify: hair fixtures · Blocked by: D3-09,D4-02
- [ ] MF-P9-05.10 Build anatomy/geograft composition maps · Verify: male/female fixtures · Blocked by: D4-01..06
- [ ] MF-P9-05.11 Freeze v1 mapping bundle and validator set · Verify: P-03 completion · Blocked by: D4-05..10
- [ ] MF-P9-05.12 Draft separate inactive v2 bundle · Verify: no v1 leakage test · Blocked by: D4-11

## MF-P9-06 — Deterministic scene generation (spec: Daz 24 D5; Daz 00–32)
- [ ] MF-P9-06.01 Implement canonical scene-recipe schema · Verify: schema fixtures · Blocked by: D1,D3,D4
- [ ] MF-P9-06.02 Implement named random streams and canonical JSON · Verify: byte-identical replay · Blocked by: D5-01
- [ ] MF-P9-06.03 Implement compatible figure/preset/material selection · Verify: selection tests · Blocked by: D3-08,D5-02
- [ ] MF-P9-06.04 Implement correlated body/face/age-appearance profiles · Verify: bounded output report · Blocked by: D5-03
- [ ] MF-P9-06.05 Implement skin/hair/wardrobe/anatomy selection · Verify: matrix coverage · Blocked by: D3,D4,D5-03
- [ ] MF-P9-06.06 Implement solo pose taxonomy and joint constraints · Verify: pose stress renders · Blocked by: D3,D5-02
- [ ] MF-P9-06.07 Implement cameras, framing, lights, environment, props · Verify: coverage fixtures · Blocked by: D5-02
- [ ] MF-P9-06.08 Implement collision/support/framing preflight · Verify: negative fixtures · Blocked by: D5-06,D5-07
- [ ] MF-P9-06.09 Save/read back fully resolved character/scene state · Verify: replay record · Blocked by: D2,D5
- [ ] MF-P9-06.10 Produce 24–100 solo engineering fixtures · Verify: accepted fixture set · Blocked by: D5-01..09

## MF-P9-07 — Exact render passes and decoding (spec: Daz 24 D6; Daz 00–32)
- [ ] MF-P9-07.01 Implement pass-profile schema and scene-state freeze · Verify: mutation detection · Blocked by: D2,D5
- [ ] MF-P9-07.02 Implement pristine RGB profile · Verify: renderer fixture · Blocked by: D6-01
- [ ] MF-P9-07.03 Implement exact instance pass · Verify: ID codec exhaustive test · Blocked by: D4,D6-01
- [ ] MF-P9-07.04 Implement exact PART pass · Verify: all active IDs · Blocked by: D4,D6-01
- [ ] MF-P9-07.05 Implement MATERIAL/protected passes · Verify: orthogonal maps · Blocked by: D4,D6-01
- [ ] MF-P9-07.06 Implement coverage alpha and hair transparency · Verify: edge fixtures · Blocked by: D4-09,D6
- [ ] MF-P9-07.07 Implement depth/normals and coordinate sidecars · Verify: finite/convention tests · Blocked by: D6-01
- [ ] MF-P9-07.08 Implement relationship/diagnostic outputs · Verify: contact fixture · Blocked by: D6-03,D6-07
- [ ] MF-P9-07.09 Implement vectorized decoder and package derivation · Verify: lossless conversion · Blocked by: D6-03..08
- [ ] MF-P9-07.10 Prove same-state pass replay · Verify: byte-identical semantic hashes · Blocked by: D6-01..09

## MF-P9-08 — Validation and MaskFactory package integration (spec: Daz 24 D7; Daz 00–32)
- [ ] MF-P9-08.01 Implement V0–V9 result schema and registry · Verify: contract tests · Blocked by: D1,D6
- [ ] MF-P9-08.02 Implement recipe/assembly/geometry validators · Verify: seeded defects · Blocked by: D5,D7-01
- [ ] MF-P9-08.03 Implement pass/pixel/semantic validators · Verify: full-image tests · Blocked by: D6,D7-01
- [ ] MF-P9-08.04 Implement bounded repairs and retry budgets · Verify: deterministic history · Blocked by: D7-02,D7-03
- [ ] MF-P9-08.05 Implement acceptance certificate · Verify: certificate replay · Blocked by: D7-01..04
- [ ] MF-P9-08.06 Add MaskFactory synthetic schema versions · Verify: historical compatibility · Blocked by: P-02,D1
- [ ] MF-P9-08.07 Implement S00/package adapter · Verify: package fixtures · Blocked by: D6,D7-05,D7-06
- [ ] MF-P9-08.08 Run existing QC and DAZ-specific checks · Verify: QA report · Blocked by: D7-07
- [ ] MF-P9-08.09 Implement ingestion and revocation linkage · Verify: descendant query · Blocked by: D1,D7-07
- [ ] MF-P9-08.10 Accept and reverify 100-scene solo pilot · Verify: independent verifier · Blocked by: D7

## MF-P9-09 — Multi-person exact-synthetic truth (spec: Daz 24 D8; Daz 00–32)
- [ ] MF-P9-09.01 Implement duo placement/overlap/contact recipes · Verify: duo matrix · Blocked by: D5,D7
- [ ] MF-P9-09.02 Implement p-index prominence after final camera · Verify: permutation fixtures · Blocked by: D8-01
- [ ] MF-P9-09.03 Implement shared-pass per-person derivation · Verify: exact complements · Blocked by: D6,D8-02
- [ ] MF-P9-09.04 Implement identity/exclusivity/bleed validators · Verify: seeded owner swaps · Blocked by: D8-03
- [ ] MF-P9-09.05 Implement reciprocal contact/occlusion records · Verify: relationship fixtures · Blocked by: D6-08,D8-01
- [ ] MF-P9-09.06 Accept separated/overlap/contact duo pilot · Verify: MM/MF/FF evidence · Blocked by: D8-01..05
- [ ] MF-P9-09.07 Add trio recipes and identity stress · Verify: all composition families · Blocked by: D8-06
- [ ] MF-P9-09.08 Add quartet recipes and identity stress · Verify: all composition families · Blocked by: D8-07
- [ ] MF-P9-09.09 Add crop, similar appearance, crossed limbs, prop contact · Verify: hard-case set · Blocked by: D8
- [ ] MF-P9-09.10 Reverify full 1–4-person pilot · Verify: zero exclusivity/bleed defects · Blocked by: D8

## MF-P9-10 — Coverage-driven autonomous corpus generation (spec: Daz 24 D9; Daz 00–32)
- [ ] MF-P9-10.01 Implement closed coverage vocabulary · Verify: schema/report · Blocked by: D0,D5
- [ ] MF-P9-10.02 Import real MaskFactory deficit signals · Verify: adapter test · Blocked by: D9-01
- [ ] MF-P9-10.03 Implement stratified/low-discrepancy candidate generation · Verify: distribution tests · Blocked by: D5,D9-01
- [ ] MF-P9-10.04 Implement utility scoring and feasible selection · Verify: deterministic ranking · Blocked by: D3,D9-03
- [ ] MF-P9-10.05 Implement dominance/cooldown/near-duplicate limits · Verify: concentration report · Blocked by: D9-04
- [ ] MF-P9-10.06 Feed validation outcomes back to planner · Verify: adaptive simulation · Blocked by: D7,D9-04
- [ ] MF-P9-10.07 Generate a targeted 1,000-scene pilot from the immutable real-data residual-gap report · Verify: acceptance/cost/target-cell report · Blocked by: D8,D9,MF-P9-10.11
- [ ] MF-P9-10.08 Calibrate storage, retry, timeout, and target sizes · Verify: measured profile · Blocked by: D9-07
- [ ] MF-P9-10.09 Generate immutable targeted 10,000-scene ablation corpus · Verify: corpus hash/card and exact gap-cell bindings · Blocked by: D9-08,MF-P9-10.11
- [ ] MF-P9-10.10 Verify coverage minima and selected intersections · Verify: coverage report · Blocked by: D9-09
- [ ] MF-P9-10.11 Admit DAZ scale only from the doc-26 immutable residual real-data gap report; independent foundation/mapping/small renderer canaries may continue earlier · Verify: admission refuses unconditional synthetic-first scale, unknown gap cells, stale corpus/champion hashes, or absent matched real-only ablation design · Blocked by: MF-P5-11.09 · HARD BLOCKER

## MF-P9-11 — Training mixture and real-image promotion (spec: Daz 24 D10; Daz 00–32)
- [ ] MF-P9-11.01 Implement builder train-only/weight/share constraints · Verify: adversarial manifests · Blocked by: D7,D9
- [ ] MF-P9-11.02 Implement independent launcher constraints · Verify: bypass tests · Blocked by: D10-01
- [ ] MF-P9-11.03 Freeze real-only baseline splits/config/seeds · Verify: baseline bundle · Blocked by: P-04
- [ ] MF-P9-11.04 Build matched 10%, 20%, 30% mixtures · Verify: dataset cards · Blocked by: D9-09,D10-01
- [ ] MF-P9-11.05 Train matched challengers · Verify: run manifests · Blocked by: D10-03,D10-04
- [ ] MF-P9-11.06 Evaluate real primary/hard-bucket metrics · Verify: comparison report · Blocked by: D10-05
- [ ] MF-P9-11.07 Run source-family/style/asset ablations · Verify: domain-gap analysis · Blocked by: D10-05
- [ ] MF-P9-11.08 Select mixture/weights only from real evidence · Verify: decision record · Blocked by: D10-06..07
- [ ] MF-P9-11.09 Test model rollback and DAZ-disable behavior · Verify: rollback rehearsal · Blocked by: D10-08

## MF-P9-12 — Unattended operations, resilience, and activation (spec: Daz 24 D11; Daz 00–32)
- [ ] MF-P9-12.01 Implement scheduler, pause/resume/drain · Verify: queue tests · Blocked by: D1,D9
- [ ] MF-P9-12.02 Implement disk reservation and retention · Verify: fill/drain tests · Blocked by: D9-08
- [ ] MF-P9-12.03 Implement dashboards and alerts · Verify: alert fixtures · Blocked by: D7,D11-01
- [ ] MF-P9-12.04 Implement control/registry/mapping/recipe backups · Verify: restore drill · Blocked by: D1,D4,D11
- [ ] MF-P9-12.05 Implement package-metadata and optional bulk strategy · Verify: recovery matrix · Blocked by: D11-04
- [ ] MF-P9-12.06 Test drive loss, DB corruption, crash, popup, OOM · Verify: failure campaign · Blocked by: D11
- [ ] MF-P9-12.07 Run seven-day soak with daily restart · Verify: soak report · Blocked by: D11-01..06
- [ ] MF-P9-12.08 Rebuild registry/queue/package history after restore · Verify: clean-root evidence · Blocked by: D11-04..07
- [ ] MF-P9-12.09 Activate recurring local schedule and ceilings · Verify: activation record · Blocked by: D11-07

## MF-P9-13 — Qualified MaskedWarehouse external supervision (spec: 23 §§4–6; MASKEDWAREHOUSE_SOURCE_REGISTRY)
- [ ] MF-P9-13.01 Lock the private/personal/noncommercial/non-distributed use profile and official license evidence for every inventoried source · Verify: machine registry rejects any profile drift or missing source · Blocked by: none
- [ ] MF-P9-13.02 Admit qualified CelebAMask-HQ, LaPa, and LV-MHP as `external_labeled_reference` for exact-scope training supervision and semantic visual calibration while retaining `weighted_pseudo_label` for model-loss accounting · Verify: authority tests allow only qualified label-scoped training/calibration and reject operational-gold, certificate, distribution, and certified-volume claims · Blocked by: MF-P9-13.01 · HARD BLOCKER
- [ ] MF-P9-13.03 Keep CC-BY-NC-ND preview and unknown-provenance body archive blocked · Verify: conversion/training negative fixtures pass · Blocked by: MF-P9-13.01
- [ ] MF-P9-13.04 Complete deterministic remap, hash manifest, alignment QA, identity, and split-dedup qualification per source · Verify: every required gate is evidence-bound before admission · Blocked by: MF-P9-13.01 through MF-P9-13.03
- [ ] MF-P9-13.05 Build role-aware converters that preserve coarse/split-required uncertainty as ignore rather than fabricated atomic PART truth · Verify: ambiguous pixels are 255 and label-scope fixtures pass · Blocked by: MF-P9-13.04
- [ ] MF-P9-13.06 Materialize qualified train-only packages and dataset cards with source/label/weight composition · Verify: builder and launcher accept only gated rows · Blocked by: MF-P9-13.05
- [ ] MF-P9-13.07 Enforce the combined external-label batch cap while keeping certified real supervision dominant · Verify: boundary and bypass tests pass · Blocked by: MF-P9-13.06
- [ ] MF-P9-13.08 Run leakage-disjoint real ablations by source and mapped label scope against qualified external-labeled benchmarks and any available independent human-anchor holdout · Verify: only non-regressing sources/labels remain active and absence of optional human anchors does not block the external-source ablation · Blocked by: MF-P9-13.06

## MF-P9-14 — Governed reference corpus, benchmark, and retrieval (spec: 23 §§7–8; reference_library.yaml)
- [ ] MF-P9-14.01 Freeze source/output roots, immutable-original policy, uniform registration, and no-truth authority · Verify: policy validator passes and source selection does not change truth or authority · Blocked by: none
- [ ] MF-P9-14.02 Complete exact inventory, validation, SHA dedup, and representative selection · Verify: counts reconcile and invalid files are reason-coded · Blocked by: MF-P9-14.01
- [ ] MF-P9-14.03 Complete body-part/difficulty visual indexing of every exact representative · Verify: classified equals representative count with zero unresolved failures · Blocked by: MF-P9-14.02
- [ ] MF-P9-14.04 Build near-duplicate groups and leakage-resistant diversity ranking · Verify: deterministic replay and duplicate fixtures pass · Blocked by: MF-P9-14.03
- [ ] MF-P9-14.05 Select exactly 2,500 benchmark and 18,000 retrieval references with declared coverage · Verify: tier counts and all required body-part tags pass · Blocked by: MF-P9-14.04
- [ ] MF-P9-14.06 Materialize selections with hash verification and contact sheets · Verify: every output exists and matches its recorded SHA-256 · Blocked by: MF-P9-14.05
- [ ] MF-P9-14.07 Enforce zero path/SHA/near-duplicate overlap between benchmark and all training/calibration/holdout sources · Verify: builder/preflight leakage fixtures block · Blocked by: MF-P9-14.05 · HARD BLOCKER
- [ ] MF-P9-14.08 Connect retrieval references to coverage deficits, hard-case matching, semantic-calibration case acquisition, and acquisition planning without truth promotion · Verify: retrieved images are demonstrably consumed by selection reports yet remain no-authority until independently paired with a qualified mask · Blocked by: MF-P9-14.05
- [ ] MF-P9-14.09 Run recurring drift/coverage reports and immutable benchmark versioning · Verify: update cannot silently replace a frozen benchmark · Blocked by: MF-P9-14.06 through MF-P9-14.08
- [ ] MF-P9-14.10 Reconcile `F:\Reference_Images\Ultimate_Masking_Reference_Images` with RunPod `/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images` before remote retrieval/calibration · Verify: inventory seal, database/manifest hashes, and sampled source hashes match; drift fails before provider invocation · Blocked by: MF-P9-14.02

## MF-P9-15 — Near-perfect selective autonomy with minimal binary review (spec: 23 §§2–3,9–12; docs 20–22)
- [ ] MF-P9-15.01 Make near-perfect selective autonomy the product acceptance target: ordinary mIoU ≥0.95, boundary-F1 ≥0.90, hard anatomy mIoU ≥0.85 · Verify: blinded real human-anchor holdout report meets each metric without bucket collapse · Blocked by: frozen real human-anchor holdout and eligible challengers
- [ ] MF-P9-15.02 Require zero cross-instance bleed, zero left/right swaps, and 100% format integrity · Verify: any seeded or audited violation blocks/revokes · Blocked by: existing QA/certification paths · HARD BLOCKER
- [ ] MF-P9-15.03 Sustain zero-touch fraction ≥0.95, routine human touch ≤0.05, and manual pixel-edit fraction ≤0.01 · Verify: measured production report, not review-time proxy · Blocked by: end-to-end eligible corpus
- [ ] MF-P9-15.04 Present only QA-complete evidence bundles for a binary approve/reject owner decision · Verify: incomplete QA/identity/split/hash bundles cannot be decided · Blocked by: none
- [ ] MF-P9-15.05 Record decisions in an idempotent hash-chained ledger · Verify: tamper, replay, and conflicting-decision fixtures fail closed · Blocked by: MF-P9-15.04
- [ ] MF-P9-15.06 On approve, seal prepared human-anchor truth or record autonomous audit agreement without changing authority · Verify: approval never invents human gold · Blocked by: MF-P9-15.04, MF-P9-15.05
- [ ] MF-P9-15.07 On reject, route bounded repair and revoke exact audited certificate scope when applicable · Verify: residual/revocation transaction test passes · Blocked by: MF-P9-15.04, MF-P9-15.05
- [ ] MF-P9-15.08 Demonstrate end-to-end autonomous generate→critic→repair→certify→audit operation with sparse owner decisions · Verify: headline evidence reports quality and labor separately · Blocked by: MF-P9-15.01 through MF-P9-15.07

## P9 Exit Gate
- [ ] MF-P9-EXIT Qualified external labels and DAZ improve untouched real human-anchor results; reference leakage is zero; selective autonomy meets the quality/labor targets; DAZ survives the seven-day soak and remains reversible · Verify: signed P9 evidence bundle plus full regression, real holdout ablations, rollback, and tracker validation pass · Blocked by: every MF-P9 item
