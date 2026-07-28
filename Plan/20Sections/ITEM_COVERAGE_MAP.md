# Unresolved Item Coverage Map

Every one of the **285** unresolved tracker items appears exactly once.

| Section | Item | Phase | Status | % | Hard | User authority | Requirement |
|---:|---|---|---|---:|:---:|:---:|---|
| 01 | `MF-P6-20.01` | P6 | open | 0 | Yes | No | Inventory and reconcile the full-product and accepted autonomy source lines by exact commit/tree/path ownership, preserving unrelated staged, dirty, and untracked work |
| 02 | `MF-P6-20.02` | P6 | open | 0 | Yes | No | Produce one canonical integrated source tree containing product code, autonomy/runtime code, package metadata, configs, schemas, CLIs, services, tests, and operating procedures |
| 03 | `MF-P0-EXIT` | P0 | partially_complete | 85 | No | No | Doctor all green end-to-end · `env\` lockfiles + populated `model_registry.json` committed (D9 provable on paper) · phase checkboxes in doc 14 §1 updated |
| 03 | `MF-P0-17.25` | P0 | partially_complete | 85 | No | No | Prove production package durability on persistent RunPod storage independently from the F-drive backup tier |
| 03 | `MF-P6-20.03` | P6 | open | 0 | Yes | No | Classify and repair the complete product test baseline, including completion-policy drift and every external-asset dependency |
| 03 | `MF-P6-20.04` | P6 | open | 0 | Yes | No | Prove clean-export installation, exact-byte runtime closure, focused/integration/full-suite execution, bounded service health, and owned shutdown |
| 04 | `MF-P1-12.09` | P1 | partially_complete | 78 | No | No | Build a 20–30 real-image authority pilot from `C:\Comfy_UI_Main\MaskedWarehouse` plus retrieval/coverage evidence from `F:\Reference_Images\Ultimate_Masking_Reference_Images` and their RunPod mirrors |
| 04 | `MF-P1-12.10` | P1 | blocked | 0 | No | No | Record autonomous pilot latency, ambiguity/abstention outcomes, correction loops, and guideline changes before scale processing |
| 04 | `MF-P2-09.09` | P2 | blocked | 0 | No | Yes | Benchmark baseline vs each enabled assist on ≥30 image-disjoint human-anchor instances; publish per-label IoU, boundary-F, false-positive rate, latency, correction-pixel/labor delta, and hard-bucket non-inferiority; promote only measured winners and retain one-command rollback |
| 04 | `MF-P9-13.06` | P9 | partially_complete | 92 | No | No | Materialize qualified train-only packages and dataset cards with source/label/weight composition |
| 04 | `MF-P9-13.07` | P9 | partially_complete | 80 | No | No | Enforce the combined external-label batch cap while keeping certified real supervision dominant |
| 04 | `MF-P9-13.08` | P9 | partially_complete | 82 | No | No | Run leakage-disjoint real ablations by source and mapped label scope against qualified external-labeled benchmarks and any available independent human-anchor holdout |
| 04 | `MF-P9-14.06` | P9 | partially_complete | 50 | No | No | Materialize selections with hash verification and contact sheets |
| 04 | `MF-P9-14.09` | P9 | partially_complete | 95 | No | No | Run recurring drift/coverage reports and immutable benchmark versioning |
| 04 | `MF-P9-14.10` | P9 | in_progress | 80 | No | No | Reconcile `F:\Reference_Images\Ultimate_Masking_Reference_Images` with RunPod `/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images` before remote retrieval/calibration |
| 05 | `MF-P1-08.02` | P1 | blocked | 0 | No | Yes | Annotate image 1 fully in CVAT per SOP-1 (all visible atomics, bands, materials, visibility attrs, honest ambiguity) |
| 05 | `MF-P1-08.03` | P1 | blocked | 0 | No | Yes | Annotate images 2–5 the same way |
| 05 | `MF-P1-08.04` | P1 | blocked | 58 | No | Yes | `package` + `verify-package` all 5 → `human_approved_gold` |
| 05 | `MF-P1-08.05` | P1 | blocked | 0 | No | Yes | Record baseline minutes/image in OPS_LOG (G1 baseline for the throughput trend) |
| 05 | `MF-P1-09.05` | P1 | blocked | 35 | No | Yes | Dry-run one restore: pull 1 package from B1 to temp → `verify-package --root` passes |
| 05 | `MF-P1-EXIT` | P1 | blocked | 0 | No | Yes | End-to-end demo recorded in OPS_LOG: incoming → CVAT → human-anchor gold with QA enforced · doc 14 §2 checkboxes updated |
| 05 | `MF-P2-08.02` | P2 | blocked | 0 | No | Yes | Review/correct the calibration subset in CVAT → approximately 30 human-anchor packages with explicit train/calibration/holdout partitions |
| 05 | `MF-P2-08.03` | P2 | blocked | 0 | No | Yes | Create `runs\leaderboard.jsonl` · publish `draft_pipeline_full` row: draft-vs-gold per-part IoU + boundary-F on these packages |
| 06 | `MF-P0-17.13` | P0 | partially_complete | 97 | No | No | Keep the proven PyTorch 2.11/cu128 core and isolate incompatible SAM 3.1, Qwen3-VL, RF-DETR, EoMT/DINOv3, pose, and geometry stacks |
| 06 | `MF-P2-11.04` | P2 | partially_complete | 98 | No | No | Integrate SAM 3.1 point/box/mask refinement and repair proposals behind `InteractiveSegmenter` |
| 06 | `MF-P2-11.07` | P2 | in_progress | 90 | No | No | Integrate SAM 3D Body behind `GeometryProvider` while retaining DensePose fallback |
| 06 | `MF-P2-11.10` | P2 | in_progress | 90 | No | No | Integrate EoMT/DINOv3 as a trainable challenger contract while retaining SegFormer/Mask2Former baselines |
| 06 | `MF-P2-11.13` | P2 | partially_complete | 75 | No | No | Build the frozen SAM/provider benchmark matrix covering SAM2.1, SAM3.1, hybrid discovery/refinement, RF-DETR routes, SAM 3D Body, BiRefNet, and pose variants |
| 06 | `MF-P2-11.14` | P2 | partially_complete | 75 | No | No | Measure per-label IoU, boundary-F, small-part/instance recall, bleed, side/front-back errors, anatomy/clothing confusion, hallucinations, QA failures, correction pixels, audit time, VRAM, latency, crash/OOM, and determinism |
| 06 | `MF-P2-11.15` | P2 | partially_complete | 95 | Yes | No | Promote winners by role only after primary win/labor reduction plus every hard-label/high-risk non-inferiority margin, then prove one-command rollback |
| 06 | `MF-P2-11.18` | P2 | open | 0 | No | No | Integrate PDFNet or its qualified equivalent as an independent fine-boundary challenger |
| 07 | `MF-P2-08.01` | P2 | blocked | 88 | No | Yes | Ingest + draft 25 images end-to-end, model-major batching (one heavy model resident at a time; runtime ≈2.5–3.5 min/img verified vs doc 07 budget table) |
| 07 | `MF-P2-08.04` | P2 | blocked | 98 | No | Yes | Record G2 initial numbers in OPS_LOG · verify **D1**: one CLI command takes a new incoming image to every indexed PART draft in the selected production ontology (56 active v1; 65 after gated v2 activation) |
| 07 | `MF-P2-EXIT` | P2 | blocked | 0 | No | Yes | Drafts measurably reduce human touches, changed pixels, residual-review fraction, and review minutes versus the P1 human-anchor baseline without quality regression · doc 14 §3 checkboxes updated |
| 08 | `MF-P4-12.11` | P4 | partially_complete | 72 | Yes | No | Define, calibrate, freeze, and hash-bind the quantitative per-label/per-context QA registry covering presence, area references, components/holes, ownership/containment, protected/exclusive/cross-person overlap, laterality/front-back, parent-child and atomic-map rules, boundary metrics, fill/leakage/unsupported pixels, thin structures, topology, transforms, perturbations, duplicates, and complete-map recomposition |
| 09 | `MF-P3-08.01` | P3 | partially_complete | 90 | No | No | Add SAM 3.1 discovery/refinement candidates to hand/finger, chest/pelvic, hair, feet/toes, clothing, accessory, and repeated-instance lanes |
| 09 | `MF-P3-08.02` | P3 | partially_complete | 95 | No | No | Evaluate SAM3-LiteText only as an optional lower-memory experiment and never a substitute for official SAM 3.1 |
| 09 | `MF-P3-08.03` | P3 | partially_complete | 80 | No | No | Benchmark BiRefNet Dynamic/HR/HR-matting against BiRefNet-general and ViTMatte for silhouette, hair edge, and matting roles |
| 09 | `MF-P3-08.04` | P3 | partially_complete | 80 | No | No | Benchmark RTMW-X/RTMO against DWPose for whole-body, hands/feet, rear, contact, occlusion, and crowded scenes |
| 09 | `MF-P3-08.05` | P3 | partially_complete | 80 | No | No | Benchmark SAM 3D Body against DensePose for geometry priors, contact/occlusion, rear/front, and multi-person identity |
| 09 | `MF-P3-08.06` | P3 | partially_complete | 80 | No | No | Keep MediaPipe Hands as an independent handedness/landmark vote and measure its incremental value |
| 09 | `MF-P3-08.08` | P3 | partially_complete | 90 | No | No | Define role-specific non-inferiority margins for every hard specialist class/context before opening benchmark results |
| 09 | `MF-P3-08.09` | P3 | partially_complete | 90 | Yes | No | Promote no specialist from model card/download/smoke alone; require measured winner, complete license/content/runtime hashes, reliable 8 GB operation or approved alternate runtime, and rollback |
| 09 | `MF-P3-08.10` | P3 | partially_complete | 75 | No | No | Publish specialist overlays, disagreements, correction-pixel deltas, and review-time impact to the leaderboard/evidence package |
| 10 | `MF-P4-01.06` | P4 | blocked | 0 | No | Yes | 20-image run: verdicts land correctly for every hard-class panel + P-IMAGE sanity output |
| 10 | `MF-P4-04.03` | P4 | blocked | 0 | No | Yes | 30-image hand-count audit matches the matrix exactly |
| 10 | `MF-P4-05.01` | P4 | blocked | 65 | Yes | Yes | Build `qa\vlm_eval\`: 40 panels with known ground truth — 20 good, 20 seeded defects spanning the problems taxonomy (wrong_side, boundary loose/tight, clothing-as-skin, neighbor bleed, missing area, hidden-area mask, finger_merge, hair edge, occlusion error) |
| 10 | `MF-P4-05.04` | P4 | blocked | 25 | Yes | Yes | Run and PASS the gate on qwen2.5vl:7b · record scores in OPS_LOG (fallback model scored too) |
| 10 | `MF-P4-06.04` | P4 | blocked | 75 | No | Yes | Weekly IAA report (per-class IoU vs targets ≥ 0.92 body / ≥ 0.80 fingers) · first report produced and filed |
| 10 | `MF-P4-06.05` | P4 | blocked | 80 | No | Yes | IAA numbers exported as the leaderboard human-ceiling row input |
| 10 | `MF-P4-07.04` | P4 | blocked | 25 | No | Yes | Rebuild and PASS the production VLM calibration gate from exactly 20 distinct frozen, QA-passing human-anchor calibration packages after every bound prompt/controller/evidence change |
| 10 | `MF-P4-08.08` | P4 | blocked | 0 | Yes | Yes | Rebuild and PASS the gold-backed calibration gate; measure correction-time improvement on at least 30 approved anchor masks |
| 10 | `MF-P4-09.06` | P4 | blocked | 0 | No | Yes | Build real calibration panels; synthetic/near-duplicate panels are diagnostic only |
| 10 | `MF-P4-09.07` | P4 | blocked | 0 | Yes | No | Pass calibrated recall/precision and hard-bucket gates before anatomy routing is enabled |
| 10 | `MF-P4-10.08` | P4 | blocked | 0 | No | Yes | Build a frozen image-disjoint ≥200-case incremental-value corpus covering serious defects, good masks, hard labels, contexts, and naturally occurring errors |
| 10 | `MF-P4-10.09` | P4 | blocked | 0 | Yes | No | Require every provider/model/prompt to pass serious recall, overall recall, precision, false-pass, incremental recall, usefulness, cost/useful-correction, review-time, and high-risk non-regression thresholds simultaneously |
| 10 | `MF-P4-10.12` | P4 | partially_complete | 80 | No | No | Evaluate each local-Qwen challenger on untouched teacher holdout, local 40-panel gate, ≥200-case incremental set, per-label/serious regressions, latency/VRAM, and reviewer time; promote only a measured win with rollback |
| 10 | `MF-P4-11.25` | P4 | partially_complete | 85 | Yes | No | Require package-specific semantic label/pixel alignment from a current primary critic plus independent-family juror before autonomous package freeze and training; bind exact source, final mask set, every active label/mask, label-aware panels, deterministic QA, quorum, and report hashes, and quarantine legacy packages missing either semantic or quorum binding without rewriting them - Verify: wrong-label consensus, all-pass structural QA, missing/stale/same-family critic, hard-veto, incomplete-label, and hash-drift fixtures all fail closed - Blocked by: MF-P4-11.18, MF-P4-11.19, MF-P4-11.21 - HARD BLOCKER |
| 10 | `MF-P4-11.26` | P4 | partially_complete | 88 | Yes | No | Run semantic requalification in deterministic bulk batches by default across eligible MaskFactory packages, qualified MaskedWarehouse labels/masks, and reference-library retrieval cases; automatically accept exact matches, publish unambiguous relabels only as new immutable versions, continue past malformed/uncertain cases, and emit compact summary/exception reports with human review optional - Verify: batch planner is deterministic, every case/panel/mask is hash-bound, required primary-plus-independent roles are explicit, one malformed case does not stop other cases, and no frozen package is mutated - Blocked by: MF-P4-11.21, MF-P4-11.25 - HARD BLOCKER |
| 10 | `MF-P4-11.11` | P4 | partially_complete | 72 | Yes | No | Allow `autonomous_certified_gold` only for one exact immutable per-record package binding target contract, qualified per-label/context QA registry and vector, current semantic alignment, qualified independent critic quorum, complete mask-set/package revision, and unexpired/unrevoked certificate; population statistics, provider consensus, operational certificates, sparse/shifted evidence, and missing bindings cannot promote the record |
| 10 | `MF-P4-11.15` | P4 | blocked | 0 | No | Yes | Demonstrate certificate build, eligible selection, residual abstention, serious-failure revocation, fingerprint-drift revocation, and weekly mixed audit on real governed evidence |
| 10 | `MF-P4-11.18` | P4 | partially_complete | 98 | Yes | No | Enforce frozen real-image valid-mask pass rate, defect recall/precision, serious false-pass, abstention, hallucinated-context, label-scope, evidence-localization, deterministic replay, malformed/truncated/schema, latency, and panel-budget thresholds; GPU/VRAM measurements are telemetry only and cannot admit, rank, promote, or reject a role; rejecting everything or reviewing the wrong target/person/tile is unavailable, never qualified |
| 10 | `MF-P4-11.19` | P4 | in_progress | 76 | No | No | Require an independently trained juror family for high-risk pass routes and prevent correlated variants from creating quorum |
| 10 | `MF-P4-11.23` | P4 | in_progress | 20 | Yes | No | Maintain a frozen real-image visual-regression suite covering all 66 active classes plus every required risk/domain stratum: hands/fingers, feet/toes, hair, clothing/skin boundaries, complete visible adult anatomy, label scale, laterality, ownership, transform, occlusion/contact, crop/out-of-frame, media domain, and multi-person risk, using `F:\Reference_Images` for coverage/retrieval and qualified `C:\Comfy_UI_Main\MaskedWarehouse` labels or exact qualified package masks for labeled cases |
| 10 | `MF-P4-12.01` | P4 | partially_complete | 98 | Yes | No | Implement durable 256-record shard queue state, owned leases, retry caps, heartbeats, checkpoints, idempotency, submitted-unknown recovery, and milestone reports |
| 10 | `MF-P4-12.02` | P4 | partially_complete | 80 | No | No | Run the polygon lane through qualified external-mask comparison, hard QC, strict per-record visual review, repair/abstain, and signed outcomes |
| 10 | `MF-P4-12.03` | P4 | partially_complete | 70 | No | No | Generate multi-provider masks from bbox prompts without treating boxes as pixels |
| 10 | `MF-P4-12.04` | P4 | partially_complete | 65 | No | No | Process all 26 CivitAI reference shards (6,537 images) through multi-provider proposal generation, provider comparison, hard QC, strict per-record visual review, bounded repair, abstention/quarantine, and exact-output certification without source truth |
| 10 | `MF-P4-12.05` | P4 | partially_complete | 90 | Yes | No | Require complete source/mask/overlay/contour/ownership evidence and one structured strict-VLM verdict per record |
| 10 | `MF-P4-12.06` | P4 | partially_complete | 97 | No | No | Run bounded automatic repair/no-progress detection and continue-on-exception outcomes |
| 10 | `MF-P4-12.07` | P4 | partially_complete | 64 | No | No | Pass one representative shard from every lane before expansion |
| 10 | `MF-P4-12.08` | P4 | partially_complete | 5 | Yes | No | Expand progressively to 1,000 records and the full eligible corpus without threshold weakening |
| 10 | `MF-P4-12.09` | P4 | partially_complete | 30 | No | No | Publish dataset-level anatomy/action/domain/split/agreement/QC/repair/abstention/certification coverage reports |
| 10 | `MF-P4-12.10` | P4 | open | 0 | Yes | No | Prove one exact real record from `source_reference` through detection, ownership, multi-provider masks, frozen per-label/context QA, qualified independent visual quorum, bounded repair when required, complete-map semantic alignment, immutable `autonomous_certified_gold` package, verification, revocation, and stale-certificate rejection |
| 10 | `MF-P4-EXIT` | P4 | blocked | 0 | No | Yes | **D4** demonstrated: VLM reviews + agree/disagree routing correct on the 20-image validation set · mining produced ≥ 1 weekly acquisition plan · doc 14 §5 checkboxes updated |
| 10 | `MF-P6-17.03` | P6 | in_progress | 60 | Yes | No | Run exact evidence panels through a qualified high-end primary visual critic and qualified independent-family juror; text-only or correlated critics cannot approve |
| 10 | `MF-P6-17.04` | P6 | in_progress | 55 | Yes | No | Persist terminal accept/repair/abstain/reject/quarantine outcomes and complete accounting for every mask record |
| 10 | `MF-P6-21.02` | P6 | open | 0 | Yes | No | Make provider and critic disagreement fail closed as abstain/adjudicate/reject/quarantine, never an implicit pass; preserve hard-QA veto authority |
| 10 | `MF-P6-21.03` | P6 | open | 0 | Yes | No | Bind the current source-qualified 66-class visual gate, exact critic qualifications, and mask-campaign prerequisites into the canonical runtime without duplicating historical campaigns |
| 11 | `MF-P3-07.01` | P3 | blocked | 0 | No | Yes | Residual/audit cadence uses SOP-2 (hands), SOP-3 (panels first), and SOP-4 (chest crop-zoom, projected separate) without requiring routine review of certificate-covered masks |
| 11 | `MF-P3-07.02` | P3 | blocked | 0 | No | No | Reach 100 certified packages with `human_anchor_train_count` and `autonomous_certified_gold_count` reported separately; pseudo-labels never count |
| 11 | `MF-P3-07.03` | P3 | blocked | 0 | No | Yes | Report human touches/100 images, audited fraction, residual-review fraction, changed pixels/100k, and review minutes as a secondary diagnostic |
| 11 | `MF-P3-07.04` | P3 | blocked | 0 | No | Yes | Begin fresh-day second-look sampling of hard-class human anchors and autonomous audits; formal mixed sampler lands P4-11 |
| 11 | `MF-P3-EXIT` | P3 | blocked | 0 | No | No | All lanes live · hard classes have panels/QCs · 100 certified packages reached with tier-separated counts · selective audit/residual labor reported · doc 14 §4 updated |
| 11 | `MF-P5-01.06` | P5 | open | 0 | No | No | Build `datasets\bodyparts@v1` · `dvc add` · `git tag dataset/bodyparts-v1` · `dvc push` to the governed local/persistent remote |
| 11 | `MF-P7-01.01` | P7 | blocked | 0 | No | Yes | Weekly acquisition driven by mining plans until **300 optional legacy training/scale certified packages** exist, counting only `human_anchor_train` plus exact `autonomous_certified_gold` packages carrying the required legacy statistical certificate; report both tiers separately and reject `operationally_certified_artifact`, bridge/operational certificates, drafts, candidates, pseudo labels, and any truth-tier alias |
| 11 | `MF-P7-01.02` | P7 | blocked | 0 | No | No | Verify coverage matrix ≥ 80% of view×pose cells at target (≥8/cell) and every attribute ≥ 40 — together with 01.01 this closes **D5** |
| 11 | `MF-P7-01.03` | P7 | blocked | 0 | No | No | Continue cadence toward the 500-package stretch target (G6) |
| 11 | `MF-P7-01.04` | P7 | deferred | 0 | No | No | (If used) Synthetic bootstrapping for stubborn deficit cells: scripted/3D-rendered images per doc 12 §9 · `source_origin: synthetic` · ≤ 30% mix cap · train-only · same QA battery |
| 11 | `MF-P5-11.01` | P5 | open | 0 | Yes | No | Export qualified polygons and machine-verified candidates into immutable weighted training datasets with exact source/remap/group seals |
| 11 | `MF-P5-11.08` | P5 | open | 0 | No | No | Implement hard-case mining over disagreement, rare/small anatomy, contact, cross-person leakage, occlusion, crop, laterality/front-back, wrong owner, boundary failure, repair exhaustion, and weak domain yield |
| 11 | `MF-P5-11.09` | P5 | open | 0 | Yes | No | Publish the immutable residual real-data gap report that names label/domain/risk/ownership/topology cells eligible for targeted DAZ generation |
| 12 | `MF-P1-10.05` | P1 | partially_complete | 90 | No | No | Add all v2 derived formulas and regenerate the active `configs/derived.yaml` only at activation |
| 12 | `MF-P5-03.02` | P5 | blocked | 75 | No | No | Train SegFormer-B3 directly on RunPod · eval per-part IoU + boundary-F on val every 4k |
| 12 | `MF-P5-03.03` | P5 | partially_complete | 65 | No | No | Challenger: Mask2Former-SwinB config + run (activation checkpointing) — optional Swin-L only on a capacity-qualified RunPod tier (05-08.03) |
| 12 | `MF-P5-03.04` | P5 | blocked | 0 | No | No | Final eval on frozen test_holdout + hard_case_holdout → leaderboard rows with full per-class + group scores |
| 12 | `MF-P5-04.02` | P5 | blocked | 70 | No | No | Train + eval · GATE: beats SCHP+S08 heuristics on material mIoU AND strap/waistband IoU ≥ 0.55 |
| 12 | `MF-P5-05.03` | P5 | blocked | 0 | No | No | Train + eval on the hand-crop holdout |
| 12 | `MF-P5-05.04` | P5 | blocked | 70 | Yes | Yes | GATE (**D7**): finger-class mean IoU ≥ 0.70 AND merged-finger false-split rate < 2% |
| 12 | `MF-P5-05.05` | P5 | blocked | 98 | No | Yes | On win: replace lane steps 2.3–2.4 as crop drafter (SAM2 stays the interactive editor) · model outputs pass QC-018 paste-back ≥ 0.995 |
| 12 | `MF-P5-06.01` | P5 | blocked | 90 | No | No | `training\leaderboard.py` full schema writer · standing baselines auto-scored per dataset version: sam2_only · sam2_pose · sam2_parsing · draft_pipeline_full |
| 12 | `MF-P5-06.03` | P5 | blocked | 92 | No | No | Champion pointers in `models\model_registry.json` (`role: champion_bodypart` etc.) · all loaders/serving read champions ONLY |
| 12 | `MF-P5-07.02` | P5 | blocked | 70 | Yes | Yes | Verify **D6/G7**: champion beats draft_pipeline_full on frozen test_holdout in BOTH mean per-part IoU and boundary-F, with NO tracked hard class regressing > 2 pts |
| 12 | `MF-P5-07.03` | P5 | blocked | 0 | No | Yes | Remeasure G1 (target trend ≤ 12 min/img) + publish G2/G3 numbers |
| 12 | `MF-P5-07.04` | P5 | blocked | 0 | No | Yes | QC-034 regression sweep on a re-processed sample after the swap — clean |
| 12 | `MF-P5-08.01` | P5 | deferred | 0 | No | No | (Trigger: ≥80 hair-prominent certified training packages with required human-anchor holdout) ViTMatte fine-tune · GATE: hair boundary-F ≥0.65 AND matte MSE −15% vs stock |
| 12 | `MF-P5-08.02` | P5 | deferred | 0 | No | No | (Trigger: ≥ 120 approved projected labels AND chest-lane fail rate > 10%) breastproj SegFormer-B1 · GATE: projected IoU ≥ 0.75 · outputs provenance-tagged `model:breastproj@<run>`, purple-editable, never truth |
| 12 | `MF-P5-08.03` | P5 | open | 0 | No | No | (Optional) RunPod scale runbook executed once: validate persistent inputs · train directly on the selected pod · persist/hash outputs and evidence |
| 12 | `MF-P5-09.08` | P5 | blocked | 0 | No | Yes | Reach 50–100 clear positive instances per appended class before production claims |
| 12 | `MF-P5-09.09` | P5 | blocked | 0 | No | No | Publish per-class IoU, boundary-F, recall, clothed false positives, and side-swap rates |
| 12 | `MF-P5-09.10` | P5 | blocked | 0 | Yes | No | Refuse promotion when any appended class lacks evidence or systematically fires on clothing |
| 12 | `MF-P5-10.07` | P5 | partially_complete | 75 | No | No | Train/evaluate EoMT/DINOv3 alongside SegFormer and Mask2Former under identical frozen data, ontology, hardware, QA, and measurement code |
| 12 | `MF-P5-10.08` | P5 | partially_complete | 90 | No | No | Define role-specific primary metric/labor objective and predeclare non-inferiority margins for every hard label/high-risk bucket before results |
| 12 | `MF-P5-10.11` | P5 | partially_complete | 90 | Yes | No | Promote winner and demote incumbent to benchmarked transactionally; prove one-command rollback restores role/lifecycle and serving |
| 12 | `MF-P5-10.12` | P5 | blocked | 40 | No | Yes | Evaluate final promotions only against image-disjoint human-anchor holdout and publish tier-separated leaderboard rows, human ceiling, labor metrics, and uncertainty |
| 12 | `MF-P5-EXIT` | P5 | blocked | 0 | No | Yes | Custom models are the drafters · leaderboard is the arbiter · **D6 + D7** checked with evidence rows · doc 14 §6 checkboxes updated |
| 12 | `MF-P5-11.03` | P5 | open | 0 | No | No | Train and benchmark anatomy-aware challengers, then promote only measured winners through existing champion policy |
| 12 | `MF-P5-11.04` | P5 | open | 0 | Yes | No | Build the real-supervision foundation with source-family-balanced sampling, per-source/per-label reliability weights, coarse-versus-fine losses, and rare-class coverage |
| 12 | `MF-P5-11.05` | P5 | open | 0 | No | No | Implement and benchmark the hierarchical cascade for person/character discovery, ownership/occlusion, silhouette, coarse anatomy, atomic specialists, boundary refinement, and complete-map consistency |
| 12 | `MF-P5-11.06` | P5 | open | 0 | No | No | Run leakage-safe self-supervised or masked-image representation pretraining over eligible `F:\Reference_Images` and reference-only MaskedWarehouse partitions without pixel-label invention |
| 12 | `MF-P5-11.07` | P5 | open | 0 | Yes | No | Run proposal expansion and iterative teacher-student retraining with immutable weighted mixtures: certified truth highest, qualified polygons/RLE medium, eligible machine candidates lower, and boxes/prompts/actions/references/unqualified proposals zero pixel-loss weight |
| 12 | `MF-P5-11.10` | P5 | open | 0 | No | No | After a qualified still-image champion, implement the temporal video lane with keyframes, bidirectional propagation, correspondence/flow consistency, persistent ownership, cut/occlusion/re-entry recovery, uncertain-frame re-segmentation, and per-frame immutable evidence; keep audio as context-only metadata |
| 12 | `MF-P7-02.02` | P7 | blocked | 35 | No | No | Execute ≥ 1 trigger-driven retrain end-to-end (build @vN+1 → train → leaderboard → promote/reject) · champion history visible in registry |
| 12 | `MF-P7-06.05` | P7 | blocked | 0 | No | No | Run full tests, drift/schema checks, seeded QA, migration/rollback, CVAT pilot, dataset/training, leaderboard, serving, and ComfyUI evidence |
| 12 | `MF-P7-06.06` | P7 | blocked | 0 | Yes | No | Switch active ontology/champions to `body_parts_v2` only after every v2 item/evidence gate passes and record atomic activation/rollback |
| 12 | `MF-P7-07.06` | P7 | partially_complete | 75 | No | No | Demonstrate trigger-driven retraining with new fingerprint, compatibility-scoped evidence reuse, recertification/abstention, role promotion/rejection, and rollback |
| 13 | `MF-P6-18.01` | P6 | in_progress | 60 | No | No | Replace routine per-step/per-file/per-mask handoffs with an integrated tracker-selection→campaign-builder→guarded-runtime→patch/test/repair→reconciliation→one-packet supervisor chain |
| 13 | `MF-P6-18.02` | P6 | in_progress | 65 | Yes | No | Implement typed exception escalation only for security/credentials, destructive or external authority, contradictory truth, policy/schema change, unreconciled ambiguity, repair exhaustion, or terminal adoption |
| 13 | `MF-P7-08.02` | P7 | open | 0 | No | No | Prove durable RunPod queue, checkpoint, crash recovery, and capacity-coordinated provider/VLM bursts |
| 14 | `MF-P6-18.03` | P6 | in_progress | 85 | No | No | Measure autonomous eligible-work percentage, Codex handoffs/time, route use, GPU time, duplicate/recovery events, repair attempts, mask outcomes, critic disagreement, reconciliation, and release |
| 14 | `MF-P6-18.04` | P6 | in_progress | 80 | Yes | No | Enforce targets of ≥80% autonomous preparation, ≤1 routine Codex handoff per 25 missions or 100 masks, ≥70% lower Codex usage per accepted artifact, zero duplicates, and 100% reconciliation/release |
| 14 | `MF-P6-19.03` | P6 | open | 0 | Yes | No | Run one governed 100-mask campaign with deterministic subcampaign splits if required |
| 14 | `MF-P6-19.04` | P6 | open | 0 | Yes | No | Run three consecutive mixed campaigns meeting every Plan-27 SLO, publish the immutable acceptance/reconstruction/operating packet, update the tracker through its CLI, and close the throughput gate |
| 14 | `MF-P6-21.01` | P6 | open | 0 | Yes | No | Publish a compact committed evidence locator for every completion-critical accepted runtime, routing, campaign, visual, release, and adoption milestone |
| 14 | `MF-P6-21.04` | P6 | open | 0 | Yes | No | Reconstruct the accepted 25-mission/recovery evidence and the eventual 100-mask/three-mixed-campaign evidence from the canonical integrated tree |
| 14 | `MF-P7-07.05` | P7 | partially_complete | 95 | No | No | Track human touches per 100 images, audited fraction, residual-review fraction, manually changed pixels per 100,000 predicted pixels, zero-touch fraction, quality, and failure-rate bounds separately |
| 14 | `MF-P7-08.03` | P7 | open | 0 | Yes | No | Account all 81,910 adopted records as qualified input, candidate, repaired, abstained/rejected, quarantined, or holdout and bind accepted outputs into training/release/recovery evidence |
| 15 | `MF-P6-01.07` | P6 | blocked | 92 | No | Yes | Author `maskfactory_nodes\workflows\wf_inpaint_gold_hand.json` · runs end-to-end in ComfyUI (gold left_hand d8f4 inpaint chain) |
| 15 | `MF-P6-02.01` | P6 | blocked | 99 | No | Yes | `serve\api.py`: GET /health (versions, loaded models, VRAM) · GET /models (registry roles + champions) · POST /predict (multipart image + labels/return/inpaint params → base64 PNGs + manifest-lite JSON with per-label visibility guess, areas, provenance) · POST /refine (image + label + clicks → SAM2 single-part refine) |
| 15 | `MF-P6-02.03` | P6 | blocked | 99 | No | No | Model residency per doc 05 §5 schedule: champion body-part + hand specialist + clothing parser sequential slots · production `/refine` resolves the governed RunPod interactive role (SAM 3.1 first); SAM2.1 is loaded only for an explicitly typed bounded fallback/rollback |
| 15 | `MF-P6-02.05` | P6 | blocked | 85 | No | Yes | Latency measured: /predict warm ≤ 4 s all-labels · ≤ 2 s single-label · /refine ≤ 1.2 s/click · cold start ≤ 60 s |
| 15 | `MF-P6-03.02` | P6 | blocked | 98 | No | No | Author + verify `wf_bodypart_conditioned.json` (visible_body_skin − clothing_visible via Mask From Label Map → skin-only img2img) |
| 15 | `MF-P6-03.03` | P6 | blocked | 92 | No | Yes | Author + verify `wf_live_predict_inpaint.json` on a NEVER-SEEN image (LoadImage → Predict left_forearm → inpaint) — this run is the **D8** demonstration |
| 15 | `MF-P6-05.07` | P6 | blocked | 0 | No | No | Re-run latency/residency and Mode A/Mode B end-to-end tests |
| 15 | `MF-P6-06.03` | P6 | partially_complete | 90 | No | No | Select SAM 3.1 first on the RunPod production route; retain SAM2.1 only as a typed bounded fallback/benchmark/rollback and local `pth-sam2` only as optional CVAT assistance |
| 15 | `MF-P6-06.07` | P6 | partially_complete | 85 | No | No | Complete parallel CVAT upgrade migration/rollback and verify SAM2/SAM3 assistance against preserved task data |
| 15 | `MF-P6-06.08` | P6 | partially_complete | 80 | No | No | Run provider-neutral Mode B prediction/refine and Mode A package workflows on unseen single/multi-person inputs, measuring warm/cold latency, VRAM, OOM, determinism, provenance, and rollback |
| 15 | `MF-P6-EXIT` | P6 | blocked | 0 | No | No | **D8** demonstrated live for the optional legacy lane (Mode A + Mode B workflows) · doc 14 §7 checkboxes updated · This item does not define project-wide or `core_autonomous_runtime` completion; the required adopted bridge exit is `MF-P6-12.06` |
| 16 | `MF-P6-11.01` | P6 | blocked | 88 | No | No | Implement the external main-controller `MaskFactoryAdapter` boundary so durable orchestration never depends on ComfyUI node IDs or MaskFactory internal paths |
| 16 | `MF-P6-11.02` | P6 | blocked | 88 | Yes | No | Implement Mode A immutable package reads with source/package/mask/revocation/instance/ontology/transform validation and no write path; cap raw manifest/status/reference evidence at noncertified and require a separate active exact operational wrapper for production use |
| 16 | `MF-P6-11.03` | P6 | blocked | 79 | No | No | Implement Mode B localhost health/capability/predict/refine client with timeouts, closed responses, request hashing, and draft-only default authority |
| 16 | `MF-P6-11.04` | P6 | blocked | 80 | No | No | Normalize and arbitrate eligible Mode A and Mode B receipts by exact scope, authority, QA, freshness, preservation risk, and cost; never compare incompatible latents or silently weaken requirements |
| 16 | `MF-P6-11.05` | P6 | blocked | 88 | No | No | Implement authenticated, replay-protected downstream repair/quality feedback bound to exact parent receipt/release/capability/policy/certificate/source/owner/transform/QA/protected state and hypothesis budget that MaskFactory may validate, reject, mine, or use to create a new candidate without mutating frozen packages/certificates or creating truth |
| 16 | `MF-P6-11.06` | P6 | blocked | 90 | No | No | Implement trusted-signed/checkpointed append-only bridge journaling, idempotency, and a closed durable state machine across admit, route, lease, submit-known/unknown, reconcile, result, validate, cache/decision, feedback, adoption, invalidation, retry/repair, recovery, and rollback |
| 16 | `MF-P6-11.07` | P6 | blocked | 84 | Yes | No | Add bounded transient retries, circuit breaker, deadline/resource enforcement, scoped DAG blocking, and explicit no-silent-fallback behavior |
| 16 | `MF-P6-11.08` | P6 | blocked | 86 | No | No | Add receipt-last atomic commit, restart recovery with `outcome_unknown` reconciliation before retry, health/capability/revocation-at-decision evidence, cache freshness, and service/node-pack drift detection; frozen v1 GPU-lease fields are telemetry-only compatibility and can never gate recovery |
| 16 | `MF-P6-12.02` | P6 | blocked | 84 | No | No | Run the single-person Mode A vertical slice from adopted package/certificate through adapter binding into a downstream ComfyUI inpaint/edit pass |
| 16 | `MF-P6-12.03` | P6 | blocked | 80 | No | No | Run the overlapping/contact two-person Mode A vertical slice with distinct character instances, skeleton/ownership masks, protected regions, and transform chains |
| 16 | `MF-P6-12.04` | P6 | blocked | 86 | No | No | Run Mode B health/predict/refine as draft, prove service-down behavior, and when eligible pass an exact original prediction through a subsequent independent operational-certification transaction |
| 16 | `MF-P6-12.05` | P6 | blocked | 83 | Yes | No | Execute the cross-project compatibility, trust/canonicalization, encoded/pixel identity, image/video-time, ownership, authority/training-truth firewall, executable geometry, idempotency, signed-journal, outage, submitted-unknown restart, cache, invalidation, rollback, and no-silent-fallback qualification matrix |
| 16 | `MF-P6-12.06` | P6 | blocked | 78 | No | No | Publish the final MaskFactory release and main-project adoption/handoff receipts, regenerate tracker reports, and close only `core_autonomous_runtime` when its exact gates pass |
| 17 | `MF-P8-10.01` | P8 | blocked | 40 | No | Yes | Curate/collect 10–20 real 2–4-person images with generated/owned/licensed/consented provenance |
| 17 | `MF-P8-10.02` | P8 | blocked | 40 | No | Yes | Run the full activated pipeline end-to-end on this set |
| 17 | `MF-P8-10.03` | P8 | blocked | 5 | No | No | Automatically accept only certificate-covered instances; route residual cases and preselected audits through SOP-1–SOP-6 without routine CVAT review of every instance |
| 17 | `MF-P8-10.04` | P8 | blocked | 0 | No | Yes | Confirm QC-035/036 clean on every autonomous-certified or human-anchor package in this set |
| 17 | `MF-P8-10.05` | P8 | blocked | 0 | No | Yes | Record **D11** demonstration evidence; measure **G9** (cross-instance bleed rate — target 0) |
| 17 | `MF-P8-10.06` | P8 | blocked | 0 | No | No | Update tier-separated metrics per instance: human-anchor partitions, autonomous-certified, pseudo, and machine candidates; each instance counts once in its own tier and only active certified tiers satisfy volume gates |
| 17 | `MF-P8-11.03` | P8 | partially_complete | 92 | No | No | Include SAM3.1 exhaustive instance discovery, SAM2.1/SAM3.1 refinement, RF-DETR, pose, geometry, silhouette, fusion, specialist, and deterministic-repair families when available |
| 17 | `MF-P8-11.07` | P8 | blocked | 0 | No | Yes | Run the complete real 10–20 image, 2–4-person demonstration with certificate-covered instances, residual reviews, blinded audits, and zero measured cross-instance bleed |
| 17 | `MF-P8-11.08` | P8 | blocked | 0 | No | No | Prove rollback from any promoted multi-person provider/certificate to incumbents without corrupting frozen packages or historical evidence |
| 17 | `MF-P8-EXIT` | P8 | blocked | 0 | No | Yes | **D11/G9** hold on real multi-person images (not just synthetic fixtures) · doc 00 §4 and doc 01 §3 both reflect this as demonstrated · doc 14 §11 checkboxes updated |
| 18 | `MF-P9-03.02` | P9 | partially_complete | 75 | No | No | Configure named MaskFactoryDAZ application instance |
| 18 | `MF-P9-03.03` | P9 | partially_complete | 75 | No | No | Register dedicated F content/render paths |
| 18 | `MF-P9-03.04` | P9 | partially_complete | 75 | No | No | Disable default scene and unexpected startup actions |
| 18 | `MF-P9-03.09` | P9 | partially_complete | 70 | No | No | Render/decode procedural primitive without DAZ assets |
| 18 | `MF-P9-03.10` | P9 | partially_complete | 68 | No | No | Decide headless versus hidden-GUI worker from evidence |
| 18 | `MF-P9-03.11` | P9 | partially_complete | 68 | No | No | Prove clean restart and no dirty-scene reuse |
| 18 | `MF-P9-04.03` | P9 | partially_complete | 90 | No | No | Add CMS query and offline fallback scan |
| 18 | `MF-P9-04.04` | P9 | partially_complete | 80 | No | No | Scan filesystem and canonicalize logical URIs |
| 18 | `MF-P9-04.05` | P9 | partially_complete | 51 | No | No | Hash assets/products and resolve duplicates/shadows |
| 18 | `MF-P9-04.06` | P9 | partially_complete | 60 | No | No | Build closed asset taxonomy and compatibility graph |
| 18 | `MF-P9-04.07` | P9 | partially_complete | 75 | No | No | Build dependency and required-plugin graph |
| 18 | `MF-P9-04.08` | P9 | partially_complete | 70 | No | No | Create asset pools by generation/type/scene category |
| 18 | `MF-P9-04.09` | P9 | partially_complete | 60 | No | No | Implement type-specific load/fit/render smoke jobs |
| 18 | `MF-P9-04.10` | P9 | partially_complete | 72 | No | No | Implement certificates, revocation, quarantine, retest |
| 18 | `MF-P9-04.11` | P9 | open | 0 | No | No | Complete Genesis 9 pilot inventory |
| 18 | `MF-P9-05.01` | P9 | open | 0 | No | No | Freeze G9 neutral topology/skeleton/UV fingerprints |
| 18 | `MF-P9-05.03` | P9 | open | 0 | No | No | Build surface/bone/weight/facet inspection exports |
| 18 | `MF-P9-05.04` | P9 | open | 0 | No | No | Create draft v1 base-facet mapping |
| 18 | `MF-P9-05.05` | P9 | open | 0 | No | No | Resolve left/right and small-boundary mappings |
| 18 | `MF-P9-05.06` | P9 | open | 0 | No | No | Build MATERIAL and protected mapping tables |
| 18 | `MF-P9-05.07` | P9 | open | 0 | No | No | Test mapping across bounded morph/pose ranges |
| 18 | `MF-P9-05.08` | P9 | open | 0 | No | No | Build clothing-territory transfer compiler |
| 18 | `MF-P9-05.09` | P9 | open | 0 | No | No | Build hair mapping/alpha profiles |
| 18 | `MF-P9-05.10` | P9 | open | 0 | No | No | Build anatomy/geograft composition maps |
| 18 | `MF-P9-05.11` | P9 | open | 0 | No | No | Freeze v1 mapping bundle and validator set |
| 18 | `MF-P9-05.12` | P9 | partially_complete | 88 | No | No | Draft separate inactive v2 bundle |
| 18 | `MF-P9-06.01` | P9 | partially_complete | 60 | No | No | Implement canonical scene-recipe schema |
| 18 | `MF-P9-06.02` | P9 | partially_complete | 73 | No | No | Implement named random streams and canonical JSON |
| 18 | `MF-P9-06.03` | P9 | partially_complete | 60 | No | No | Implement compatible figure/preset/material selection |
| 18 | `MF-P9-06.04` | P9 | partially_complete | 65 | No | No | Implement correlated body/face/age-appearance profiles |
| 18 | `MF-P9-06.05` | P9 | partially_complete | 65 | No | No | Implement skin/hair/wardrobe/anatomy selection |
| 18 | `MF-P9-06.06` | P9 | partially_complete | 65 | No | No | Implement solo pose taxonomy and joint constraints |
| 18 | `MF-P9-06.07` | P9 | partially_complete | 65 | No | No | Implement cameras, framing, lights, environment, props |
| 18 | `MF-P9-06.08` | P9 | partially_complete | 70 | No | No | Implement collision/support/framing preflight |
| 18 | `MF-P9-06.09` | P9 | partially_complete | 70 | No | No | Save/read back fully resolved character/scene state |
| 18 | `MF-P9-06.10` | P9 | partially_complete | 65 | No | No | Produce 24–100 solo engineering fixtures |
| 18 | `MF-P9-07.01` | P9 | partially_complete | 70 | No | No | Implement pass-profile schema and scene-state freeze |
| 18 | `MF-P9-07.02` | P9 | partially_complete | 70 | No | No | Implement pristine RGB profile |
| 18 | `MF-P9-07.03` | P9 | partially_complete | 70 | No | No | Implement exact instance pass |
| 18 | `MF-P9-07.04` | P9 | partially_complete | 70 | No | No | Implement exact PART pass |
| 18 | `MF-P9-07.05` | P9 | partially_complete | 70 | No | No | Implement MATERIAL/protected passes |
| 18 | `MF-P9-07.06` | P9 | partially_complete | 70 | No | No | Implement coverage alpha and hair transparency |
| 18 | `MF-P9-07.07` | P9 | partially_complete | 70 | No | No | Implement depth/normals and coordinate sidecars |
| 18 | `MF-P9-07.08` | P9 | partially_complete | 70 | No | No | Implement relationship/diagnostic outputs |
| 18 | `MF-P9-07.09` | P9 | partially_complete | 70 | No | No | Implement vectorized decoder and package derivation |
| 18 | `MF-P9-07.10` | P9 | partially_complete | 70 | No | No | Prove same-state pass replay |
| 18 | `MF-P9-08.01` | P9 | partially_complete | 88 | No | No | Implement V0–V9 result schema and registry |
| 18 | `MF-P9-08.02` | P9 | partially_complete | 88 | No | No | Implement recipe/assembly/geometry validators |
| 18 | `MF-P9-08.03` | P9 | partially_complete | 88 | No | No | Implement pass/pixel/semantic validators |
| 18 | `MF-P9-08.04` | P9 | partially_complete | 88 | No | No | Implement bounded repairs and retry budgets |
| 18 | `MF-P9-08.05` | P9 | partially_complete | 88 | No | No | Implement acceptance certificate |
| 18 | `MF-P9-08.07` | P9 | partially_complete | 88 | No | No | Implement S00/package adapter |
| 18 | `MF-P9-08.08` | P9 | partially_complete | 88 | No | No | Run existing QC and DAZ-specific checks |
| 18 | `MF-P9-08.09` | P9 | partially_complete | 88 | No | No | Implement ingestion and revocation linkage |
| 18 | `MF-P9-08.10` | P9 | open | 0 | No | No | Accept and reverify 100-scene solo pilot |
| 18 | `MF-P9-09.01` | P9 | partially_complete | 85 | No | No | Implement duo placement/overlap/contact recipes |
| 18 | `MF-P9-09.02` | P9 | partially_complete | 85 | No | No | Implement p-index prominence after final camera |
| 18 | `MF-P9-09.03` | P9 | partially_complete | 85 | No | No | Implement shared-pass per-person derivation |
| 18 | `MF-P9-09.04` | P9 | partially_complete | 85 | No | No | Implement identity/exclusivity/bleed validators |
| 18 | `MF-P9-09.05` | P9 | partially_complete | 85 | No | No | Implement reciprocal contact/occlusion records |
| 18 | `MF-P9-09.06` | P9 | open | 0 | No | No | Accept separated/overlap/contact duo pilot |
| 18 | `MF-P9-09.07` | P9 | open | 0 | No | No | Add trio recipes and identity stress |
| 18 | `MF-P9-09.08` | P9 | open | 0 | No | No | Add quartet recipes and identity stress |
| 18 | `MF-P9-09.09` | P9 | open | 0 | No | No | Add crop, similar appearance, crossed limbs, prop contact |
| 18 | `MF-P9-09.10` | P9 | open | 0 | No | No | Reverify full 1–4-person pilot |
| 19 | `MF-P9-10.01` | P9 | partially_complete | 88 | No | No | Implement closed coverage vocabulary |
| 19 | `MF-P9-10.02` | P9 | partially_complete | 88 | No | No | Import real MaskFactory deficit signals |
| 19 | `MF-P9-10.03` | P9 | partially_complete | 88 | No | No | Implement stratified/low-discrepancy candidate generation |
| 19 | `MF-P9-10.04` | P9 | partially_complete | 88 | No | No | Implement utility scoring and feasible selection |
| 19 | `MF-P9-10.05` | P9 | partially_complete | 88 | No | No | Implement dominance/cooldown/near-duplicate limits |
| 19 | `MF-P9-10.06` | P9 | partially_complete | 88 | No | No | Feed validation outcomes back to planner |
| 19 | `MF-P9-10.07` | P9 | partially_complete | 62 | No | No | Generate a targeted 1,000-scene pilot from the immutable real-data residual-gap report |
| 19 | `MF-P9-10.08` | P9 | partially_complete | 60 | No | No | Calibrate storage, retry, timeout, and target sizes |
| 19 | `MF-P9-10.09` | P9 | partially_complete | 58 | No | No | Generate immutable targeted 10,000-scene ablation corpus |
| 19 | `MF-P9-10.10` | P9 | partially_complete | 60 | No | No | Verify coverage minima and selected intersections |
| 19 | `MF-P9-10.11` | P9 | open | 0 | Yes | No | Admit DAZ scale only from the doc-26 immutable residual real-data gap report; independent foundation/mapping/small renderer canaries may continue earlier |
| 19 | `MF-P9-11.03` | P9 | open | 0 | No | No | Freeze real-only baseline splits/config/seeds |
| 19 | `MF-P9-11.04` | P9 | open | 0 | No | No | Build matched 10%, 20%, 30% mixtures |
| 19 | `MF-P9-11.05` | P9 | open | 0 | No | No | Train matched challengers |
| 19 | `MF-P9-11.06` | P9 | open | 0 | No | No | Evaluate real primary/hard-bucket metrics |
| 19 | `MF-P9-11.07` | P9 | open | 0 | No | No | Run source-family/style/asset ablations |
| 19 | `MF-P9-11.08` | P9 | open | 0 | No | No | Select mixture/weights only from real evidence |
| 19 | `MF-P9-11.09` | P9 | open | 0 | No | No | Test model rollback and DAZ-disable behavior |
| 19 | `MF-P9-12.01` | P9 | partially_complete | 88 | No | No | Implement scheduler, pause/resume/drain |
| 19 | `MF-P9-12.02` | P9 | partially_complete | 88 | No | No | Implement disk reservation and retention |
| 19 | `MF-P9-12.03` | P9 | partially_complete | 85 | No | No | Implement dashboards and alerts |
| 19 | `MF-P9-12.04` | P9 | partially_complete | 94 | No | No | Implement control/registry/mapping/recipe backups |
| 19 | `MF-P9-12.05` | P9 | partially_complete | 94 | No | No | Implement package-metadata and optional bulk strategy |
| 19 | `MF-P9-12.06` | P9 | partially_complete | 94 | No | No | Test drive loss, DB corruption, crash, popup, OOM |
| 19 | `MF-P9-12.07` | P9 | open | 0 | No | No | Run seven-day soak with daily restart |
| 19 | `MF-P9-12.08` | P9 | partially_complete | 75 | No | No | Rebuild registry/queue/package history after restore |
| 19 | `MF-P9-12.09` | P9 | open | 0 | No | No | Activate recurring local schedule and ceilings |
| 19 | `MF-P9-15.01` | P9 | partially_complete | 35 | No | No | Make near-perfect selective autonomy the product acceptance target: ordinary mIoU ≥0.95, boundary-F1 ≥0.90, hard anatomy mIoU ≥0.85 |
| 19 | `MF-P9-15.02` | P9 | partially_complete | 88 | Yes | No | Require zero cross-instance bleed, zero left/right swaps, and 100% format integrity |
| 19 | `MF-P9-15.03` | P9 | partially_complete | 35 | No | No | Sustain zero-touch fraction ≥0.95, routine human touch ≤0.05, and manual pixel-edit fraction ≤0.01 |
| 19 | `MF-P9-15.08` | P9 | partially_complete | 74 | No | No | Demonstrate end-to-end autonomous generate→critic→repair→certify→audit operation with sparse owner decisions |
| 19 | `MF-P7-03.01` | P7 | blocked | 35 | No | Yes | Backup restore drill (15 §5): 3 random packages from B2 → temp restore → `verify-package --root` all pass → one pushed to CVAT usable → logged in OPS_LOG |
| 19 | `MF-P7-03.03` | P7 | blocked | 30 | No | Yes | Failure-mining drill: take one acquisition_plan item to full resolution (collect/re-annotate → gold → failure_queue item `resolved: true` with resolution_pkg_version) |
| 19 | `MF-P7-03.06` | P7 | blocked | 25 | No | Yes | Sign the **D10** checklist with dates in OPS_LOG (backup, retrain, failure mining, gc, incident drill) |
| 19 | `MF-P7-EXIT` | P7 | blocked | 0 | No | Yes | Optional `scale_daz_maturity` / `independent_real_accuracy` portfolio milestone: all applicable D1–D10 boxes in doc 00 §4 checked with evidence · **revised headline test passed:** 20 unseen images → selective autonomous certification/residual routing → preselected blinded mixed audit, no routine per-image correction, zero format/L/R failures, and separate labor/quality/confidence metrics (docs 20/22; MF-P7-07.07) · Per doc 24 this item is not a project-wide or `core_autonomous_runtime` exit gate |
| 19 | `MF-P7-07.01` | P7 | partially_complete | 70 | Yes | No | Run model, runtime, dependency, license/allowed-use, benchmark-certificate, and rollback review every 90 days and before dataset freeze, training, promotion, or major release |
| 19 | `MF-P7-07.03` | P7 | partially_complete | 97 | Yes | No | Fail CI on stale/missing active-path hashes, decisions, currency reviews, benchmark evidence, or rollback evidence |
| 19 | `MF-P7-07.07` | P7 | blocked | 0 | No | Yes | Run 20 unseen images autonomously with a preselected blinded mixed audit sample and no routine per-image correction |
| 19 | `MF-P7-07.08` | P7 | blocked | 0 | No | No | Demonstrate target zero-touch 0.95, routine human touch ≤0.05, and manual pixel edit ≤0.01 as measured operational outcomes—not completion assumptions |
| 19 | `MF-P7-07.11` | P7 | open | 0 | Yes | No | Requalify every promoted visual-critic role on the frozen positive/negative corpus every 90 days and on model, quantization, runtime, prompt, renderer, or target-contract change |
| 19 | `MF-P7-07.12` | P7 | open | 0 | No | No | Re-run the authorized read-only AWS-versus-RunPod inventory before major model/dataset acquisition or storage migration |
| 19 | `MF-P7-07.13` | P7 | open | 0 | Yes | No | Audit every active transferred asset against its sealed migration manifest and persistent RunPod path |
| 19 | `MF-P7-07.14` | P7 | open | 0 | No | No | Rehearse rollback from a migrated or newly promoted critic/proposal artifact to the prior exact RunPod-resident version |
| 20 | `MF-P6-22.01` | P6 | open | 0 | Yes | No | Assemble one immutable MaskFactory release candidate with exact commit/tree, package/deployment, ontology/API, runtime/model/config, test, campaign, visual, evidence-index, limitation, startup/shutdown, invalidation, and rollback bindings |
| 20 | `MF-P6-22.02` | P6 | open | 0 | Yes | No | Deliver the pinned cross-session adoption packet from MaskFactory session `019f91d1-ea20-7d81-83ff-03d393eaa1f5` to ComfyUI session `019f9200-4805-7632-83d3-ee9ae614c603`; keep ComfyUI masking deferred before this gate |
| 20 | `MF-P6-22.03` | P6 | open | 0 | Yes | No | Run live bounded ComfyUI masking E2E against the pinned release for every required serving mode, including accept, provider/deterministic failure, abstain/quarantine, restart/replay, invalidation refusal, and rollback |
| 20 | `MF-P6-22.04` | P6 | open | 0 | Yes | No | Publish the final Ultimate Masking System acceptance/reconstruction packet and close only the claims whose exact gates passed |
| 20 | `MF-P7-07.09` | P7 | partially_complete | 75 | No | No | Run doctor, live provider smokes, frozen benchmarks, optional CVAT migration/rollback, statistical certificate/revocation, single-person headline, and tracker/report before declaring the legacy modernization/portfolio profile complete; this bundle has no core-completion authority |
| 20 | `MF-P9-EXIT` | P9 | open | 0 | No | No | Qualified external labels and DAZ improve untouched real human-anchor results; reference leakage is zero; selective autonomy meets the quality/labor targets; DAZ survives the seven-day soak and remains reversible |
