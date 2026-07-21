# ITEMS — Phase P4: VLM QA & Active Learning (Weeks 5–7, overlaps P3)

**Completion-profile scope:** human-anchor calibration, blinded audit, and population-confidence work
in this phase serves optional `independent_real_accuracy`. The required core instead qualifies the
exact-output operational certificate and autonomous abstention path in doc 24/MF-P6-07..12; optional
P4 evidence cannot block or redefine its completion.

Goal: D4 — VLM review + routing correct on the 20-image validation set; mining loop producing the weekly plan. Parent IDs from doc 14 §5.

## MF-P4-01 — S11 VLM QA runner (spec: 10 §1–4)
- [ ] MF-P4-01.01 `vlm\client.py`: Ollama API client (127.0.0.1:11434) · S11 runs in its exclusive GPU slot — orchestrator stops other GPU stages during the batch
- [ ] MF-P4-01.02 Author versioned prompt files `vlm\prompts\{p_part,p_image,p_manifest}.txt` exactly per doc 10 §3 (strict-JSON verdict contracts) · author `configs\vlm.yaml` (model slots, prompt_version, routing thresholds, cloud-teacher enablement reconciled with exact-image default-deny governance)
- [ ] MF-P4-01.03 Panel input prep: 5-tile panels downscaled to 1024 long side · whole-image overlay + compact manifest digest (label:state:area% table) · relevant qa_report excerpts
- [ ] MF-P4-01.04 Strict-JSON parse · one "JSON only" retry · still bad → verdict `uncertain` (never guess)
- [ ] MF-P4-01.05 Verdicts append to `qa_report.vlm_review.verdicts[]` {label, panel_file, model, prompt_version, verdict, confidence, problems[], evidence, correction_instruction, latency_ms}
- [ ] MF-P4-01.06 20-image run: verdicts land correctly for every hard-class panel + P-IMAGE sanity output

## MF-P4-02 — Router + review queues (spec: 10 §5)
- [ ] MF-P4-02.01 `vlm\router.py` implementing the full 5-row routing table (pass/pass → quick-pass · pass/fail → careful+instruction · ROUTE/pass → careful · ROUTE/fail → careful priority↑ + heatmap pinned · any/uncertain → careful, NO hints)
- [ ] MF-P4-02.02 Correction instructions attached to CVAT task descriptions, explicitly marked machine-generated
- [ ] MF-P4-02.03 Invariant tests: VLM can NEVER approve gold, NEVER clear a BLOCK, NEVER edit a mask (no code path exists)
- [ ] MF-P4-02.04 Behavior test covering all 5 routing combinations

## MF-P4-03 — Failure queue + mining jobs (spec: 12 §7, 04 §4, 10 §8)
- [ ] MF-P4-03.01 `qa\failure_queue.jsonl` writers wired from: lanes (finger_merge…), QC fails, second-review fails, VLM/auto-QA disagreements, human-edit deltas
- [ ] MF-P4-03.02 Priority scorer: 0.4·class_error_rate (leaderboard trend) + 0.3·coverage_deficit + 0.2·downstream_use_weight + 0.1·recency (14 d decay) · author `configs\training\use_weights.yaml` (hands/chest 1.0, feet 0.8, bands 0.5)
- [ ] MF-P4-03.03 Weekly mining job: text-LLM clustering of failure_reason strings → `qa\reports\acquisition_plan_<date>.md` with top-20 priority actions (collect cell X / re-annotate ids / promote to hard_case_holdout / §8 label proposal)
- [ ] MF-P4-03.04 Nightly P-MANIFEST lint sweep over new packages → findings report · weekly QA summary markdown drafted by text LLM
- [ ] MF-P4-03.05 Register the nightly + weekly jobs as scheduled tasks (Task Scheduler → WSL), joining the P1-09 backup tasks

## MF-P4-04 — Coverage matrix live (spec: 12 §2, 04 §5)
- [ ] MF-P4-04.01 Tagger writes view × pose × attributes per approved package into `qa\coverage_matrix.json` (closed vocabulary only)
- [ ] MF-P4-04.02 `maskfactory coverage report`: heat table + ranked deficit list (target − count, normalized) feeding §7 priorities
- [ ] MF-P4-04.03 30-image hand-count audit matches the matrix exactly

## MF-P4-05 — VLM calibration gate (spec: 10 §4) — BLOCKER for VLM in prod
- [ ] MF-P4-05.01 Build `qa\vlm_eval\`: 40 panels with known ground truth — 20 good, 20 seeded defects spanning the problems taxonomy (wrong_side, boundary loose/tight, clothing-as-skin, neighbor bleed, missing area, hidden-area mask, finger_merge, hair edge, occlusion error)
- [ ] MF-P4-05.02 `maskfactory vlmqa eval`: defect recall + precision report · GATE: ≥ 0.90 recall AND ≥ 0.80 precision or production use is refused
- [ ] MF-P4-05.03 Gate wired to change detection: any model or prompt_version change invalidates the pass and forces re-eval
- [ ] MF-P4-05.04 Run and PASS the gate on qwen2.5vl:7b · record scores in OPS_LOG (fallback model scored too)

## MF-P4-06 — Second review + IAA (spec: 11 §6)
- [ ] MF-P4-06.01 Stratified 15% sampler over approved packages (hard classes ×2 weight: fingers, toes, chest boundary, pelvic/waistband, hairline, hand-body contact)
- [ ] MF-P4-06.02 Second-review flow: different day / fresh eyes · panels-first, then full image · pass/fail per sampled part captured
- [ ] MF-P4-06.03 Fail path: package demoted `rejected_needs_fix` · failure_queue(second_review_fail) · both mask versions archived to `qa\iaa\`
- [ ] MF-P4-06.04 Weekly IAA report (per-class IoU vs targets ≥ 0.92 body / ≥ 0.80 fingers) · first report produced and filed
- [ ] MF-P4-06.05 IAA numbers exported as the leaderboard human-ceiling row input

## MF-P4-07 — Specialist-aware autonomous committee (spec: 10 §10, 16 §8)
- [ ] MF-P4-07.01 Validate `S06/auxiliary/auxiliary_predictions.json` and supply exact specialist masks, detector/checkpoint provenance, confidence, boxes, and protected proposals to both local and eligible cloud S11 reviewers
- [ ] MF-P4-07.02 Include auxiliary protected proposals in collision checks; register exact specialist outputs as separately provenance-preserving, full-map-QA tournament candidates; route material specialist/final disagreement to careful review with a pinned heatmap
- [ ] MF-P4-07.03 Reconcile local/cloud runtime configuration; live-smoke the primary VLM, fallback VLM, and text LLM; keep cloud image transmission exact-hash/rights/provider opt-in with shadow-only authority
- [ ] MF-P4-07.04 Rebuild and PASS the production VLM calibration gate from exactly 20 distinct frozen, QA-passing human-anchor calibration packages after every bound prompt/controller/evidence change · Verify: image-disjoint package/mask/fingerprint hashes are frozen and current

## MF-P4-08 — Autonomous mask repair execution (spec: 21)
- [ ] MF-P4-08.01 Derive side-aware repair ROIs from S05 geometry, bind local/cloud coordinates to the ROI, and pass it as the real SAM2 box prompt · Verify: source/ROI coordinate, clipping, outside-point rejection, and real-box-prompt tests pass · Blocked by: production S05 geometry
- [ ] MF-P4-08.02 Implement ordinary-refinement and catastrophic-reconstruction guards for change, ROI escape, person-relative area, components, and protected overlap · Verify: each guard has a seeded rejection fixture and catastrophic mode cannot bypass protected/ROI limits · Blocked by: MF-P4-08.01
- [ ] MF-P4-08.03 Compose atomic complete-map transactions that may displace ordinary draft labels but never protected authority; record displacement and rerun QA · Verify: per-label rollback preserves S09 baseline and protected collisions fail · Blocked by: MF-P4-08.02
- [ ] MF-P4-08.04 Re-audit the exact winner with fresh Qwen plus every enabled eligible Gemini/OpenAI/Anthropic reviewer; require unanimous advisory pass at the governed floor and reserve any 95% acceptance claim for frozen human-gold calibration · Verify: votes bind candidate ID/path/hash/round, raw self-confidence is not called calibrated, and a missing/failing reviewer is not a pass · Blocked by: MF-P4-10.03 through MF-P4-10.06
- [ ] MF-P4-08.05 Feed failed reviewer plans into bounded polygon/SAM2 rounds, downgrade rejected winners, deduplicate proposals, and stop honestly on convergence/caps/no progress · Verify: candidate/round caps, failed-winner downgrade, dedup, exhaustion, budget, and no-progress tests pass · Blocked by: MF-P4-08.02 through MF-P4-08.04
- [ ] MF-P4-08.06 Publish only non-gold review drafts into CVAT with backup, exact verification, rollback, completed-task refusal, and human-edit overwrite refusal · Verify: write/verify/mismatch rollback and task/manual-shape negative fixtures pass · Blocked by: MF-P4-08.03 · HARD BLOCKER
- [ ] MF-P4-08.07 Prove the controller with focused/full tests, lint/format checks, tracker validation, and a live non-mutating shadow repair on a real image · Verify: evidence report binds source/baseline/candidate/QA/reviewer hashes and all commands pass · Blocked by: governed real source; live cloud committee additionally NEEDS KEVIN spending/credential approval
- [ ] MF-P4-08.08 Rebuild and PASS the gold-backed calibration gate; measure correction-time improvement on at least 30 approved anchor masks · Verify: current controller/prompt/evidence fingerprint passes and paired review-time report shows measured effect · Blocked by: NEEDS KEVIN: at least 30 reviewed human-anchor masks and any authorized paid calls · HARD BLOCKER

## P4 Exit Gate
- [ ] MF-P4-EXIT **D4** demonstrated: VLM reviews + agree/disagree routing correct on the 20-image validation set · mining produced ≥ 1 weekly acquisition plan · doc 14 §5 checkboxes updated
