# ITEMS — Phase P5 Ontology-v2 and Certified-Truth Training (docs 18, 20, 22, SAM 3.1 handoff)

Goal: train and promote only from explicitly partitioned truth tiers and frozen, hard-bucket-safe evaluation.

## MF-P5-09 — Ontology-v2 dataset and training (spec: 18 checklist G)
- [ ] MF-P5-09.01 Accept only fully reviewed v2 packages for 65-class supervision · Verify: frozen discovery rejects incomplete review authority · Blocked by: MF-P1-11.06
- [ ] MF-P5-09.02 Preserve v1 data without treating appended labels as negatives · Verify: v1 is 56-class pretraining-only and cannot enter v2 fine-tuning as implicit negatives · Blocked by: MF-P5-09.01
- [ ] MF-P5-09.03 Burn ambiguity to ignore index 255 and export IDs 56..64 exactly · Verify: byte-for-value fixture preserves atomics outside explicit ambiguity · Blocked by: MF-P1-11.02
- [ ] MF-P5-09.04 Add anatomy-focused crops plus whole-body anti-forgetting batches without fabricated positives · Verify: deterministic sampler meets frozen proportions when inventory supports them · Blocked by: MF-P5-09.01
- [ ] MF-P5-09.05 Update flip, rotation, crop, color, and class-weight tests for v2 · Verify: every appended swap/ignore/weight invariant passes · Blocked by: MF-P1-10.03, MF-P5-09.03
- [ ] MF-P5-09.06 Author exact 65-class configs and eliminate 57-class conflict · Verify: config validation accepts 56 v1/65 v2 and rejects 57 · Blocked by: MF-P1-10.09
- [ ] MF-P5-09.07 Build identity-separated positive and clothed-negative holdouts · Verify: identity/pHash leakage and unreviewed negatives fail · Blocked by: human-anchor v2 corpus
- [ ] MF-P5-09.08 Reach 50–100 clear positive instances per appended class before production claims · Verify: immutable inventory report meets every per-class floor · Blocked by: NEEDS KEVIN: sufficient reviewed source evidence
- [ ] MF-P5-09.09 Publish per-class IoU, boundary-F, recall, clothed false positives, and side-swap rates · Verify: every appended class and required context has finite holdout evidence · Blocked by: MF-P5-09.07, MF-P5-09.08
- [ ] MF-P5-09.10 Refuse promotion when any appended class lacks evidence or systematically fires on clothing · Verify: negative promotion fixtures and real holdout gate pass · Blocked by: MF-P5-09.09 · HARD BLOCKER

## MF-P5-10 — Truth-tier dataset weights, certified gates, and challenger promotion (spec: 22 §§5,7; SAM handoff Gate/Metric Changes)
- [ ] MF-P5-10.01 Build datasets with human-anchor train weight 1.0, autonomous-certified configured weight 0.5–0.75, and pseudo-label weight 0.1–0.25 while preserving per-example tier/weight provenance · Verify: dataset manifest and loss loader reproduce exact effective weights · Blocked by: MF-P1-13.01 through MF-P1-13.05
- [ ] MF-P5-10.02 Keep human-anchor calibration/holdout and all final holdouts unreadable by trainers, pseudo-label generation, threshold tuning, and certificate fitting · Verify: path/capability tests fail every leakage route · Blocked by: MF-P1-13.02, MF-P1-13.03 · HARD BLOCKER
- [ ] MF-P5-10.03 Report all six truth counts separately and derive `certified_training_package_count = human_anchor_train_count + autonomous_certified_gold_count` · Verify: tracker/dataset tests reject collapsed effective-gold counts · Blocked by: MF-P1-13.01
- [ ] MF-P5-10.04 Report `effective_training_weight_units` only as a diagnostic; it cannot satisfy P5, D5, volume, coverage, or gold gates · Verify: threshold fixtures with high pseudo weight and insufficient certified count remain blocked · Blocked by: MF-P5-10.03
- [ ] MF-P5-10.05 Gate P5 entry at ≥200 certified training packages and D5 at ≥300 certified packages plus required coverage · Verify: tracker and builder enforce the same formulas · Blocked by: MF-P5-10.03 · HARD BLOCKER
- [ ] MF-P5-10.06 Build train-only pseudo-label manifests with verified lifecycle/ranking/mask hashes and stage-root containment · Verify: holdout overlap, stale cert, invalid ranking, hash drift, and path escape fail · Blocked by: MF-P4-11.11
- [ ] MF-P5-10.07 Train/evaluate EoMT/DINOv3 alongside SegFormer and Mask2Former under identical frozen data, ontology, hardware, QA, and measurement code · Verify: complete immutable run records and comparable metrics exist · Blocked by: MF-P0-17.10, MF-P5-10.05
- [ ] MF-P5-10.08 Define role-specific primary metric/labor objective and predeclare non-inferiority margins for every hard label/high-risk bucket before results · Verify: benchmark manifest hash predates metric output · Blocked by: frozen human-anchor holdout
- [ ] MF-P5-10.09 Require primary win or material labor reduction plus no hard-bucket, bleed, side, protected-region, hard-QA, determinism, crash/OOM, or rollback regression · Verify: average-win/hard-bucket-loss fixture is rejected · Blocked by: MF-P5-10.08 · HARD BLOCKER
- [ ] MF-P5-10.10 Bind promotion certificate to source/checkpoint/runtime/license/content/dataset/prompt/hardware/QA/measurement hashes and current lifecycle state · Verify: any missing/stale identity blocks promotion · Blocked by: MF-P0-16.08, MF-P5-10.09
- [ ] MF-P5-10.11 Promote winner and demote incumbent to benchmarked transactionally; prove one-command rollback restores role/lifecycle and serving · Verify: registry history and runtime smoke pass both directions · Blocked by: MF-P5-10.10 · HARD BLOCKER
- [ ] MF-P5-10.12 Evaluate final promotions only against image-disjoint human-anchor holdout and publish tier-separated leaderboard rows, human ceiling, labor metrics, and uncertainty · Verify: leaderboard rejects autonomous/pseudo truth as final authority · Blocked by: NEEDS KEVIN: sufficient final human-anchor holdout and completed training runs
