# ITEMS — Phase P1: Gold Factory MVP (Weeks 1–2)

Optional accuracy/portfolio goal: image → CVAT → human-anchor gold package with format QA enforced
(legacy D2). Per doc 24 this lane is useful independent truth evidence but is not a prerequisite for
the required human-free `core_autonomous_runtime` profile. Parent IDs from doc 14 §2.

## MF-P1-01 — JSON schemas + validators (spec: 04)
- [ ] MF-P1-01.01 Write `schemas\manifest.schema.json` per doc 04 §1 (source/person/parts/inpaint_derivatives/tooling/review/qa/files blocks)
- [ ] MF-P1-01.02 Write `schemas\qa_report.schema.json` per doc 04 §2 (checks[], metrics_per_part, consensus, vlm_review, overall/score)
- [ ] MF-P1-01.03 Write `schemas\model_registry.schema.json` per doc 04 §3
- [ ] MF-P1-01.04 Write `schemas\failure_queue.schema.json` (per-line object, doc 04 §4 incl. failure_reason enum)
- [ ] MF-P1-01.05 Write `schemas\coverage_matrix.schema.json` (closed view/pose/attribute vocab, doc 04 §5)
- [ ] MF-P1-01.06 Write `schemas\crop_transform.schema.json` ({part, x0, y0, scale, crop_size, source_sha256}, doc 03 §5)
- [ ] MF-P1-01.07 Implement validator + packager invariants in code: every enabled label appears in `parts` · visibility ∉ {visible, partially_visible} ⇒ `mask_file: null` (atomics) · `human_approved_gold` ⇒ qa_overall pass + review block present
- [ ] MF-P1-01.08 Invalid-fixture per schema · pytest asserts rejection with JSON-pointer paths

## MF-P1-02 — SQLite state + orchestrator (spec: 04 §6, 05 §3/§6)
- [ ] MF-P1-02.01 Create `data\maskfactory.sqlite`: tables images / stage_runs / review_tasks / training_runs · WAL mode · single-writer (orchestrator) guard
- [ ] MF-P1-02.02 Enforce status transitions: ingested→drafted→auto_qa→vlm_qa→in_review→corrected→approved_gold→exported, plus rejected / quarantined / deprecated branches
- [ ] MF-P1-02.03 Orchestrator: stage graph · per-stage config-hash stamping · `--stage` force/skip flags · stages communicate via files + manifest deltas only · idempotent re-runs overwrite own `work\`
- [ ] MF-P1-02.04 Error policy: transient (OOM/IO) 2 retries with backoff · semantic → review queues · fatal → image `quarantined`, batch continues
- [ ] MF-P1-02.05 `runs\gpu.lock` acquire/release + stale-lock detection (doctor reports it)
- [ ] MF-P1-02.06 Implement `maskfactory reindex` (rebuild DB from manifests) + `--dry-run` diff mode
- [ ] MF-P1-02.07 Logging: loguru → `logs\maskfactory_<date>.log` + per-run `runs\<run_id>\run.json` (config hash, model keys, durations, VRAM peak)
- [ ] MF-P1-02.08 Crash test: kill −9 mid-run → resume completes · `reindex --dry-run` diff == 0

## MF-P1-03 — ontology.yaml generator + CI assert (spec: 02 §10)
- [ ] MF-P1-03.01 Encode ALL doc 02 tables as generator source data: PART IDs 0–55, MATERIAL IDs 0–15, region-band registry, derived-union registry, projected registry, protected classes, per-label boundaries metadata
- [ ] MF-P1-03.02 Generator emits `configs\ontology.yaml`: per label {id, name, mask_type, map, side, parent_union, enabled, expected_area_pct_range, max_components, exclusivity_group, swap_partner, visibility_default}
- [ ] MF-P1-03.03 `ontology.py` loader = the ONLY label authority in code · unknown label anywhere → hard error
- [ ] MF-P1-03.04 CI job regenerates YAML from tables and diffs — any drift fails CI
- [ ] MF-P1-03.05 Unit tests: 56 parts present · ears 54/55 `enabled: false` · every sided label has swap_partner · every atomic has area range + max_components
- [ ] MF-P1-03.06 Author `configs\viz.yaml`: fixed per-label colors, overlay style (RGBA 255,64,64,110 + 1 px contour), panel layout, tile size 512

## MF-P1-04 — S00 intake incl. safety gate (spec: 07 S00, 10 §7, 01 §7)
- [ ] MF-P1-04.01 Ingest: SHA-256 → `image_id = img_<hash12>` · duplicate hash → skip + log
- [ ] MF-P1-04.02 Decode · reject min side < 512 (`intake.min_side`) or corrupt → `rejected`
- [ ] MF-P1-04.03 EXIF/metadata strip (PNG lossless; JPG byte-copied, metadata stripped)
- [ ] MF-P1-04.04 `source_origin` from drop subfolder (incoming\generated|owned|licensed|consented) · root drops → quarantined until sorted
- [ ] MF-P1-04.05 Compute + store 64-bit pHash (near-duplicate guard for split assignment, doc 12 §1)
- [ ] MF-P1-04.06 Record exact provenance, rights/allowed-use, integrity, and deterministic intake outcome for every source
- [ ] MF-P1-04.07 Write manifest skeleton · SQLite row `ingested`
- [ ] MF-P1-04.08 Test batch: 10 mixed images incl. seeded duplicate, undersize, and quarantine case → all outcomes correct

## MF-P1-05 — Maps → binaries + derivations (spec: 03 §4/§6)
- [ ] MF-P1-05.01 Minimal `fuse`/mapbuild for P1: build `label_map_part.png` (16-bit) + `label_map_material.png` (8-bit) from human CVAT masks (priority argmax; full consensus lands P2)
- [ ] MF-P1-05.02 `maskfactory export-binaries`: regenerate ALL binary PNGs from maps via png_strict (binaries are views)
- [ ] MF-P1-05.03 Author `configs\derived.yaml` (every union formula from doc 02 §7: left/right_hand = hand_base ∪ fingers, arms, legs, visible_body_skin = atomics ∩ material skin, both_* unions…) · implement `maskfactory derive`
- [ ] MF-P1-05.04 Author `configs\inpaint.yaml` (defaults d8f4 @1024 ref, per-label overrides) · implement `maskfactory derive-inpaint` → `inpaint\inpaint_<label>_d<k>f<f>.png` (dilate → feather ramp; grayscale allowed) · settings + source gold hash → manifest `inpaint_derivatives[]`
- [ ] MF-P1-05.05 Round-trip test: maps → binaries → maps is identical
- [ ] MF-P1-05.06 QC-001…007 subset green on exporter outputs

## MF-P1-06 — CVAT bridge v1 (spec: 11 §2)
- [ ] MF-P1-06.01 `maskfactory cvat init-project` (REST): active project `MaskFactory_body_parts_v1` · all v1 ontology labels, fixed viz colors, type=mask · attributes `visibility` (enum doc 02 §8), `ambiguous` (bool), `notes` (text) · v2 always uses the separate doc-18 pilot project
- [ ] MF-P1-06.02 `cvat push <ids>`: image + draft masks as RLE pre-annotations · context images (all-parts overlay; disagreement heatmap when present) · 1 image/job, 10 jobs/task, assignee kevin
- [ ] MF-P1-06.03 `cvat pull <ids>`: export corrected masks + attributes → package · retain `annotations\cvat_task_backup.zip` · auto-trigger re-fuse + re-QA
- [ ] MF-P1-06.04 `labelmap.py` ontology↔CVAT id mapping · author `configs\cvat.yaml` (URL, project ids, label mapping, `provider: cvat` field for the §9 LS fallback)
- [ ] MF-P1-06.05 Round-trip test: push known mask → pull unedited → pixel-identical

## MF-P1-07 — Packager + format QA battery (spec: 09 §1/§7, 03 §3/§9)
- [ ] MF-P1-07.01 Implement QC-001 dims · QC-002 binary {0,255} (inpaint\/matting\ exempt-listed) · QC-003 PNG mode L/no alpha/magic
- [ ] MF-P1-07.02 Implement QC-004 filename↔ontology · QC-005 manifest schema+invariants · QC-006 hash integrity
- [ ] MF-P1-07.03 Implement QC-007/030 map↔binary regeneration identity (hand-edit detection) · QC-008 states complete · QC-009 derived reproducible from formula+input hashes · QC-010 crop transform valid
- [ ] MF-P1-07.04 Auto-fix policy (doc 09 §7): regenerate binaries · drop sub-threshold components · fill sub-threshold holes · re-derive unions — each attempted once, logged, re-checked; nothing else auto-edited
- [ ] MF-P1-07.05 `maskfactory package <id>`: rerun battery → any BLOCK bounces to `rejected_needs_fix` printing failing panel paths · pass → approval confirm → stamp review block (reviewer, timestamps, minutes) → statuses gold → freeze + full `files{}` hash map → DVC add
- [ ] MF-P1-07.06 `verify-package <id>` (all hashes + format QCs) with `--root` and `--sample N` flags (runbook §5 + nightly sweep use)
- [ ] MF-P1-07.07 Versioning: corrections spawn `masks@v2\`, atomic promotion, v1 → deprecated kept until gc (30 d)
- [ ] MF-P1-07.08 Seeded-defect fixture per QC-001…010 · pytest: each trips exactly its QC · human approval CANNOT override a BLOCK (enforcement test)
- [ ] MF-P1-07.09 `dvc init` · configure remote `s3://maskfactory-dvc-dev` (dev acct 548846591581, creds via env) · first `dvc add data\packages` + `dvc push` succeeds

## MF-P1-08 — First 5 gold packages, hand-driven (spec: 11 SOP-1/-5)
- [ ] MF-P1-08.01 Curate + drop 5 governed images into `incoming\<origin>\` · ingest clean
- [ ] MF-P1-08.02 Annotate image 1 fully in CVAT per SOP-1 (all visible atomics, bands, materials, visibility attrs, honest ambiguity)
- [ ] MF-P1-08.03 Annotate images 2–5 the same way
- [ ] MF-P1-08.04 `package` + `verify-package` all 5 → `human_approved_gold`
- [ ] MF-P1-08.05 Record baseline minutes/image in OPS_LOG (G1 baseline for the throughput trend)

## MF-P1-09 — Ops bootstrap (addendum to doc 14 P1; spec: 15 §2/§5)
- [ ] MF-P1-09.01 Register nightly scheduled task (Windows Task Scheduler → WSL): B1 `robocopy /MIR` of packages/qa/configs + state.db snapshot → `D:\MaskFactoryBackup\`
- [ ] MF-P1-09.02 Register nightly B5 SQLite `.backup` (7 rotations) BEFORE the mirror
- [ ] MF-P1-09.03 Register nightly integrity sweep: `maskfactory verify-package --sample 10`
- [ ] MF-P1-09.04 Weekly B2 cold-copy task/reminder (zip → external SSD, offline)
- [ ] MF-P1-09.05 Dry-run one restore: pull 1 package from B1 to temp → `verify-package --root` passes

## P1 Exit Gate
- [ ] MF-P1-EXIT End-to-end demo recorded in OPS_LOG: incoming → CVAT → human-anchor gold with QA enforced · doc 14 §2 checkboxes updated
