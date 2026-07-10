# Document 14: Implementation Roadmap & Work Breakdown Structure

Phases P0–P7. Every task has an ID (`MF-P<phase>-<nn>`), a deliverable, and an acceptance
criterion; a task is DONE only when code + test + the acceptance check all exist (no "works on
my machine" closes). Spec column names the governing document — build to the spec, not to memory.
Builder = AI coding agent under Kevin's direction (doc 01 roles); solo-dev rhythm in §10.

**Timeline (target):** P0 days 1–3 · P1 weeks 1–2 · P2 weeks 2–4 · P3 weeks 4–6 · P4 weeks 5–7
(overlaps P3) · P5 weeks 6–10 (needs ≥200 gold) · P6 after D6 · P7 continuous.

---

## 1. Phase P0 — Environment & Foundation (Days 1–3) → feeds D9

| ID | Task | Deliverable | Acceptance | Spec |
|----|------|-------------|-----------|------|
| MF-P0-01 | WSL2 Ubuntu 22.04 + systemd + hot workdir | `~/mfwork` on ext4, `/mnt/c` repo junctioned | `wsl -l -v` shows v2; IO benchmark noted | 06 §1 |
| MF-P0-02 | conda env `maskfactory`, PyTorch ≥2.7 cu128 | `env\environment.yml` + lock | `torch.cuda.get_device_capability()==(12,0)`; sm_120 tensor op runs | 06 §2 |
| MF-P0-03 | Docker Desktop + CVAT v2.24.0 pinned | CVAT at 127.0.0.1:8080, admin user | login OK; version endpoint matches pin | 06 §4 |
| MF-P0-04 | nuclio serverless SAM2 interactor | function `pth-sam2` deployed (CPU) | interactive click-segment works on a test image in CVAT UI | 06 §4 |
| MF-P0-05 | Ollama + Qwen2.5-VL 7B Q4 (+ llama3.2-vision fallback) | models pulled, smoke prompt | P-PART prompt on sample panel returns parseable JSON | 06 §5, 10 §3 |
| MF-P0-06 | `maskfactory models fetch` — M1–M12 checkpoints | `models\` populated + `model_registry.json` with SHA-256 | every hash verifies; re-run is a no-op | 06 §3, 04 §3 |
| MF-P0-07 | `maskfactory doctor` | doctor command implementing the full checklist | all checks green on this machine; any red exits non-zero with fix hint | 06 §8 |
| MF-P0-08 | Repo + quality rails | git init, pre-commit (ruff/black), `png_strict.py` writer, GitHub Actions (lint+unit) | CI green on empty test suite; cv2.imwrite ban lint rule fires on a fixture | 05 §3, 06 §2 |

**Exit:** doctor green end-to-end; D9 provable on paper (lockfiles + registry exist).

## 2. Phase P1 — Gold Factory MVP (Weeks 1–2) → D2 partial

| ID | Task | Deliverable | Acceptance | Spec |
|----|------|-------------|-----------|------|
| MF-P1-01 | Schemas + validators | jsonschema for manifest/qa_report/registry/failure/coverage | invalid fixtures rejected with pointer paths | 04 |
| MF-P1-02 | SQLite state + orchestrator skeleton | `state.db`, stage graph, retries, `reindex` | kill −9 mid-run → resume completes; reindex rebuilds db from packages | 04 §6, 05 §3 |
| MF-P1-03 | ontology.yaml generator + CI assert | generator from doc 02 tables; CI job diffs YAML↔tables | any table/YAML drift fails CI; 56 parts + 16 materials + swap_partners present | 02 §10 |
| MF-P1-04 | S00 intake (incl. safety gate) | ingest CLI: hash id, EXIF strip, min-side, pHash, quarantine flow | 10-image mixed batch → correct ids, quarantine catches seeded case | 07 S00, 10 §7 |
| MF-P1-05 | Maps→binaries exporter | `export-binaries`, `derive` (unions), png_strict everywhere | round-trip map→binaries→map identical; QC-001..007 pass on outputs | 03 §4 |
| MF-P1-06 | CVAT bridge v1 | `cvat init-project/push/pull` | draft masks appear as editable pre-annotations; pull round-trips pixel-identical | 11 §2 |
| MF-P1-07 | Packager + format QA subset | `package`, `verify-package`, QC-001…010 + QC-030 | seeded-defect fixtures each trip their QC; BLOCK prevents approval | 09 §2, 03 §8 |
| MF-P1-08 | First 5 gold, hand-driven | 5 approved packages via manual CVAT annotation | all 5 pass verify-package; time-per-image logged as baseline | 11 SOP-1 |

**AMENDED (doc 17 §13):** MF-P1-05 (exporter/package layout), MF-P1-01 (schemas), and MF-P1-03
(ontology generator) each bake in the `instances\pN\` package structure and `image_manifest.json`
from the start, at zero extra cost, even though only p0 is exercised until Phase P8. This avoids
any future breaking migration. See `Plan\Items\10_ITEMS_P8_MULTI_PERSON_MASKING.md` for the
itemized version of this note.

**Exit:** an image can go incoming→CVAT→approved gold package with format QA enforced (D2 core).

## 3. Phase P2 — Body-Aware Drafting (Weeks 2–4) → G2 first measurement

| ID | Task | Deliverable | Acceptance | Spec |
|----|------|-------------|-----------|------|
| MF-P2-01 | S01 person det + S02 silhouette | stages + fixtures | primary-person bbox & silhouette IoU ≥0.95 vs hand truth on 10 fixtures | 07 |
| MF-P2-02 | S03 parsing (Sapiens + SCHP remap) | 28-class→ontology remap tables | remap unit-tested; disagree% logged | 07 S03 |
| MF-P2-03 | S04 pose + view/pose_tags | DWPose+MediaPipe, tags emitted | tags correct on 20-image tagged set ≥90% | 07 S04 |
| MF-P2-04 | S05 geometry engine | limb capsules, joint bands, torso partition, SAM2 prompt plans | band geometry unit tests (0.6×width rule); prompt plans render on overlay | 07 S05, 02 §6 |
| MF-P2-05 | S06 GDINO assist + S07 SAM2 refine | box assist + multimask refine loop | per-part drafts for the 46 core parts on 10 fixtures | 07 S06–07 |
| MF-P2-06 | S09 fusion v1 + z-order | weighted vote + panoptic resolution, seed 1337 | byte-identical maps across 2 runs (G8 spot); exclusivity QC-011 clean | 07 S09 |
| MF-P2-07 | Overlays + 5-tile panels + semantic QCs | viz module; QC-011…020 | panels generated for hard classes; QC-014 catches seeded L/R swap | 09 §3, §6 |
| MF-P2-08 | 25 images through drafts→review | 25 more gold; G2 measured | mean draft IoU report vs these golds published to leaderboard as `draft_pipeline_full` | 12 §10 |

**AMENDED (doc 17 §13):** MF-P2-01's S01 implementation includes the full ranking/promotion/
prominence-floor logic (doc 17 §4) — even though, until Phase P8, the orchestrator still only
*processes* `person_index=0`. S01 computes and records every detected person's rank regardless;
P2 doesn't yet loop over them.

**Exit:** drafts materially reduce annotation time (G1 trend visible); D1 true.

## 4. Phase P3 — Specialist Lanes (Weeks 4–6) → 100 gold, G1 ≤25 min

| ID | Task | Deliverable | Acceptance | Spec |
|----|------|-------------|-----------|------|
| MF-P3-01 | Crop contract + hand lane | 1.6×bbox→1024 crops, transforms, lane 2.1–2.8 | paste-back IoU ≥0.995; finger gap negatives verified on fixtures | 03 §5, 08 §2 |
| MF-P3-02 | Chest/clothing lane + S08 parser | material map, strap/waistband thin-structure, sheer detect | seeded clothed-breast fixture: breast_skin empty, projected drafted, QC-019/020 pass | 08 §3, 07 S08 |
| MF-P3-03 | Hair/face lane + matting | trimap±6px, ViTMatte, face_protected | hair binary + matte emitted when ≥2% trigger; face guard QC clean | 08 §4 |
| MF-P3-04 | Feet/toes lane | foot_base/toes split, shod rule | shod fixture → material footwear + toes not_visible | 08 §6 |
| MF-P3-05 | DensePose referee (S09 input + QC-014 vote) | detectron2 DensePose in WSL | L/R 2-of-3 vote live; front/back consistency flags fire on fixture | 08 §5, 09 QC-014 |
| MF-P3-06 | Topology QCs + regression guard | QC-025…029, QC-031, QC-034 | chain-break fixture blocked; gold v2 vs v1 diff report renders | 09 §4 |
| MF-P3-07 | Reach 100 approved gold | annotation sprint w/ lanes | 100 packages; median review ≤25 min (G1-P3); IAA process started | 11 §6–7 |

**Exit:** all lanes live; hard classes have panels + QCs; throughput at phase target.

## 5. Phase P4 — VLM QA & Active Learning (Weeks 5–7) → D4

| ID | Task | Deliverable | Acceptance | Spec |
|----|------|-------------|-----------|------|
| MF-P4-01 | S11 VLM QA runner | panel batching, JSON parse+retry, verdict writes | verdicts land in qa_report on 20-image set | 10 §2–4 |
| MF-P4-02 | Router + queues | quick-pass vs careful queues into CVAT task descriptions | routing table behavior matches doc on all 5 combinations | 10 §5 |
| MF-P4-03 | Failure queue + weekly mining job | failure_queue.jsonl writers, clustering report | acquisition_plan generated with priority-ordered actions | 12 §7, 04 §4 |
| MF-P4-04 | Coverage matrix live | tagger + `coverage report` | heat table matches hand count on 30-image audit | 12 §2 |
| MF-P4-05 | **VLM calibration gate** | 40-panel eval set (20 good/20 seeded), `vlmqa eval` | ≥0.90 defect recall, ≥0.80 precision — gate blocks prod use otherwise; re-run wired to model/prompt change | 10 §4 |
| MF-P4-06 | Second review + IAA reporting | 15% stratified sampler, iaa report | first IAA report produced; disagreements land in failure_queue | 11 §6 |

**Exit:** D4 demonstrated on the 20-image validation set; mining produces the weekly plan.

## 6. Phase P5 — Custom Model Training (Weeks 6–10; entry gate ≥200 gold) → D6, D7

| ID | Task | Deliverable | Acceptance | Spec |
|----|------|-------------|-----------|------|
| MF-P5-01 | Dataset build v1 + DVC | `datasets\bodyparts@v1` + card + `dvc push` | rebuild byte-identical; holdout isolation verified (trainer cannot read it) | 12 §1, §3 |
| MF-P5-02 | Aug pipeline w/ swap_partner flip test | MMSeg dataset/transform code | CI flip-remap unit test green (BLOCKER); rare-class crop sampling measured | 12 §4 |
| MF-P5-03 | Train 6.1 body-part segmenter | SegFormer-B3 run (+SwinB challenger) | leaderboard rows exist; eval on frozen holdouts | 12 §6.1 |
| MF-P5-04 | Train 6.2 clothing parser | run + eval | strap/waistband IoU ≥0.55 checked | 12 §6.2 |
| MF-P5-05 | Train 6.3 hand specialist | hand-crop run | **finger mIoU ≥0.70 (D7)**; merged false-split <2% | 12 §6.3 |
| MF-P5-06 | Leaderboard + promotion mechanics | compare CLI, champion pointers in registry | one-edit promotion + instant rollback demonstrated | 12 §10 |
| MF-P5-07 | Champion into pipeline | S03/S09 consume `custom_bodypart` @0.45; lane 2.3–2.4 swap | **D6/G7:** champion beats draft pipeline on frozen holdout, no hard class −2 pts; G1 remeasured ≤12 min trend | 12 §6.1 |
| MF-P5-08 | (Cond.) 6.4 matting / 6.5 projected | runs if triggers met | their §6.4/§6.5 gates | 12 §6.4–6.5 |

**Exit:** custom models are the drafters; leaderboard is the arbiter; D6+D7 checked.

## 7. Phase P6 — ComfyUI & Serving (after D6) → D8

| ID | Task | Deliverable | Acceptance | Spec |
|----|------|-------------|-----------|------|
| MF-P6-01 | Node pack Mode A | `maskfactory comfy install`; all §2 nodes | wf_inpaint_gold_hand.json runs end-to-end in ComfyUI | 13 §1–2 |
| MF-P6-02 | `serve\api.py` | /health /models /predict /refine + gpu.lock | latency targets met warm; lock mutual-exclusion demonstrated | 13 §3 |
| MF-P6-03 | Mode B node + workflows | MF Predict Masks + 3 shipped workflows | wf_live_predict_inpaint.json works on a never-seen image (**D8**) | 13 §2, §4 |
| MF-P6-04 | Read-only enforcement audit | test that no Comfy path writes packages | mutation attempt fixture errors (QC-030 parity) | 13 §5 |

## 8. Phase P7 — Scale & Continuous Operation → D5, D10

| ID | Task | Deliverable | Acceptance | Spec |
|----|------|-------------|-----------|------|
| MF-P7-01 | Scale gold 300→500 | annotation cadence w/ mining-driven acquisition | **D5:** ≥300 gold, coverage ≥80% cells | 12 §2 |
| MF-P7-02 | Retrain cadence live | trigger-driven P5 reruns | ≥1 retrain executed off a trigger; champion history in registry | 12 §7 |
| MF-P7-03 | Ops drills | backup-restore, gc, failure-mining, incident playbook each run once | **D10** checklist signed with dates | 15 |
| MF-P7-04 | Ontology v2 evaluation | evidence review (per-toe? finer bands? ears?) | decision doc appended to CHANGELOG_ONTOLOGY.md | 02 §9, 12 §8 |
| MF-P7-05 | v2 horizons noted | video (SAM2 tracking) — **AMENDED (doc 17):** multi-person promotion is no longer just an assessment here; it graduated to the full Phase P8 below | written go/no-go for video only; multi-person has its own phase | 01 §5, 17 |

## 9. Dependencies & Critical Path

`P0 → P1 → P2 → P3 → P5 → P6` is the critical path; P4 runs parallel to late P3 (needs P2
panels). Inside P5: P5-01→02→03→06→07 serial; 04/05 parallel to 03. Gold-count gates: P5 entry
≥200 approved (else keep annotating in P3/P4 mode); D5 needs P7-01. Hard blockers by design:
CI flip test (P5-02) blocks all training merges; calibration gate (P4-05) blocks VLM in prod;
format QCs block approval everywhere from P1-07 onward.

## 10. Solo-Dev Weekly Rhythm (P3 onward)

Mon: mining report + acquisition plan review (30 min) · Tue–Thu: build tasks (current phase) ·
Fri: annotation block (~4 h) + weekly backup verify · Sat/Sun optional annotation (~6 h to hit
10 h/wk → G6 in 6–8 weeks). Every session starts with `maskfactory doctor` (10 s) and ends with
`git push` + `dvc push`. Phase reviews at each Exit: check the phase's D-items, update this doc's
checkboxes, log deviations in `Plan\DECISIONS_LOG.md` (create on first deviation).

## 11. Phase P8 — Multi-Person / Multi-Character Masking (NEW, doc 17) → D11, G9

**Entry gate:** P7 substantially complete — D1–D10 satisfied. P8 is explicitly a generalization
of an already-working single-instance system, not a from-scratch parallel build (doc 17 §13).

| ID | Task | Deliverable | Acceptance | Spec |
|----|------|-------------|-----------|------|
| MF-P8-01 | Activate multi-instance S01 loop | orchestrator calls S02–S09 once per promoted instance, not once per image | 3-person fixture produces 3 distinct instance packages under `instances\` | 17 §4–5 |
| MF-P8-02 | S03/S04 co-subject disambiguation | bbox/silhouette-match suppression of other-person detections within a crop | seeded 2-person crop fixture: no cross-contamination of parsing/pose priors | 17 §5 |
| MF-P8-03 | S09.5 Instance Reconciliation stage | cross-instance overlap check, reciprocal contact-band injection, `image_manifest.json` writer | seeded false-split fixture triggers the overlap check; reciprocal band appears in both packages | 17 §5–6 |
| MF-P8-04 | Package layout + image_manifest.json live | `instances\pN\` nesting, image-level manifest, per-instance `interperson[]` field | round-trip: build → verify-package on every instance folder → all pass | 17 §6, 03 §2 |
| MF-P8-05 | QC-035…038 implemented | new checks wired into S10 | seeded fixtures trip each check exactly; QC-035/036 confirmed as hard BLOCKs | 17 §7, 09 §4.5 |
| MF-P8-06 | Multi-instance CVAT workflow | per-instance task creation + shared overview job, SOP-6 | 2-person fixture produces 2 instance jobs + 1 overview job in CVAT | 17 §9, 11 SOP-6 |
| MF-P8-07 | Split-integrity CI test | dedicated test: no image_id split across train/val/test/hard_case | seeded multi-instance fixture set passes; a deliberately-broken builder fails the test | 17 §8, 12 §1 |
| MF-P8-08 | Coverage matrix + leaderboard instance-context dimension | `solo/duo/small_group` cells; leaderboard reports pooled + context-broken-out scores | coverage report shows the new dimension; leaderboard rows include both views | 17 §8, 04 §5, 12 §10 |
| MF-P8-09 | ComfyUI `person_index` parameter | every relevant node updated, default 0 | existing single-person workflows re-run byte-identical; multi-instance workflow loads p1 correctly | 17 §11, 13 §2 |
| MF-P8-10 | First multi-person gold packages | 10–20 real 2–4-person images through the full activated pipeline | QC-035/036 clean on all; **D11** demonstrated; G9 measured at 0 bleed | 17 §14 |

**Exit:** `MF-P8-EXIT` — **D11/G9** hold on real multi-person images, not just fixtures; doc 00 §4
and doc 01 §3 both reflect this as demonstrated, not just specified.

