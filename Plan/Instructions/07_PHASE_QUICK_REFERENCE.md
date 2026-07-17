# 07 — Phase Quick Reference

**Profile rule:** these phase cards describe the complete portfolio. Required
completion is the doc-24 `core_autonomous_runtime` profile, not every phase
exit. Human-anchor/CVAT/blinded/volume/training/DAZ/soak gates apply only to
their optional profile unless the completion registry explicitly maps an item
into core.

Condensed cheat-cards for each phase. These are quick-orientation aids, not
replacements — full detail always lives in `Plan\0X` (spec) and
`Plan\Items\0X` (checklist).

---

## P0 — Environment & Foundation (days 1–3, target)
**Entry gate:** none — first phase.
**Goal:** A fully working local environment: WSL2 + cu128 PyTorch on
Blackwell (sm_120), Docker/CVAT/nuclio, Ollama + local VLM, governed registry
v2, incumbent checkpoints, and honestly staged modern challengers with isolated
runtimes, `maskfactory doctor` all-green, repo + CI scaffold.
**Key gotchas:** sm_120 needs PyTorch ≥2.7 cu128 wheels specifically — older
builds fail with "no kernel image available." `/mnt/c` I/O is slow for many
small files; hot work goes on WSL's own ext4 (`~/mfwork`). detectron2/mmcv
may need source builds on cu128. Full pitfall list: `Plan\06` §8.
**Exit:** `MF-P0-EXIT` plus `MF-P0-16.12`/required provider smokes — doctor
green, lockfiles and active registry validated; planned challengers are not
misreported as installed.

## P1 — Gold Factory MVP (weeks 1–2)
**Entry gate:** P0 core exit plus active-registry governance.
**Goal:** One real image can become an immutable human-anchor package, with
format QA structurally enforced; ontology-v2 and four explicit truth tiers are
schema-valid while active v1 remains unchanged until activation.
**Key gotchas:** Binary masks are always regenerated from the two label
maps (`label_map_part.png`, `label_map_material.png`) — never hand-edit a
binary PNG directly (QC-030). Source provenance and content-lane decisions
remain explicit; no age-eligibility gate is added. `ontology.yaml` is generated from spec tables, never
hand-written (`MF-P1-03`, a hard blocker).
**Exit:** `MF-P1-EXIT` for the optional human-truth portfolio lane; this is not the required core exit.

## P2 — Body-Aware Drafting (weeks 2–4)
**Entry gate:** P1 core exit; v2 drafting additionally needs inactive v2 authority/migration contracts.
**Goal:** Full automatic drafting pipeline (S01–S09): person detection,
silhouette, parsing, pose, the geometry engine (limb capsules, joint bands,
torso partition), provider-neutral discovery/refinement, and consensus fusion
into the master maps. SAM 3.1 and modern providers enter only as governed shadow
challengers until frozen role benchmarks pass. First G2 measurement uses human-anchor truth.
**Key gotchas:** GroundingDINO output is boxes only — it can never become a
final mask directly (`Plan\07` S06). Fusion must be deterministic (seed
1337) — verify byte-identical re-runs, don't just assume it. Z-order
arbitration rules for contested pixels are exact and specific (`Plan\07`
S09) — don't substitute a simpler heuristic.
**Exit:** `MF-P2-EXIT` — **D1** should be demonstrable here (one CLI
command drafts every selected production PART for a new image: 56 for active v1, 65 only after
the doc-18 v2 activation gate).

## P3 — Specialist Lanes (weeks 4–6)
**Entry gate:** P2 core exit; each modern specialist needs an installed governed challenger.
**Goal:** Hand/finger, chest/breast/clothing, hair/face, and feet/toes
lanes live; DensePose 3D-prior referee wired in; topology QCs (025–034)
active; 100 certified packages with truth tiers separated; residual/audit labor,
changed pixels, and quality reported independently.
**Key gotchas:** Never guess a finger split on merged/ambiguous fingers —
label `hand_base` + `ambiguous_do_not_use` and queue to the failure log
instead (`Plan\08` §2.6). The chest/breast lane's "visible-truth
constitution" (`Plan\08` §3.3) is load-bearing: the mask always follows
what's *actually visible* (skin or fabric), never an assumption of what's
underneath — the editable guess lives only in the separate projected-region
layer, never in the atomic PART map.
**Exit:** `MF-P3-EXIT`.

## P4 — VLM QA & Active Learning (weeks 5–7, parallel to late P3)
**Entry gate:** runs alongside late P3. Legacy population-risk/independent-accuracy certification
requires image-disjoint human-anchor calibration evidence; doc-24 exact-output operational core
certification does not.
**Goal:** Local/cloud VLM review, bounded repair, selective certification,
mixed random+risk audit, revocation, residual routing,
failure-queue mining producing weekly acquisition plans, coverage-matrix
tracking, and all frozen VLM/incremental-value/statistical gates passed.
**Key gotchas:** The VLM is QA/router only — it can never approve gold,
clear a BLOCK, or edit a mask, structurally (`Plan\10` §5). The calibration
gate (`MF-P4-05`, hard blocker: ≥0.90 defect recall, ≥0.80 precision on the
40-panel eval set) must re-pass on *any* model or prompt-version change,
not just once.
**Exit:** `MF-P4-EXIT` — drives **D4** directly.

## P5 — Optional Custom Model Training (weeks 6–10; entry gate: ≥200 certified training packages)
**Entry gate:** `metrics.certified_training_package_count >= 200` plus an
image-disjoint human-anchor holdout. Do not start training
work before this is genuinely true — a champion trained on too little data
has no real chance at the D6 gate, and the attempt burns real GPU-hours.
**Goal:** Train SegFormer/Mask2Former/EoMT and specialists with tier-specific
weights, run frozen human-anchor leaderboards, and promote only role winners
that pass every hard/high-risk non-inferiority margin and rollback test.
**Key gotchas:** The horizontal-flip augmentation MUST remap every
left/right label via `swap_partner` — this is a hard-blocker CI test
(`MF-P5-02.02`) because a missed remap silently poisons the entire training
set with L/R errors. Holdouts (`test_holdout`, `hard_case_holdout`) must
never be readable by the training code, structurally, not just by
convention. Champion promotion is a one-line registry edit — verify the
D6 gate honestly (beats the draft pipeline on the *frozen* holdout, no hard
class regressing >2 pts) before flipping it.
**Exit:** `MF-P5-EXIT`.

## P6 — ComfyUI Integration, Serving, Autonomous Core, and Cross-Project Bridge
**Entry gates:** Legacy trained-champion serving retains D6/provider/rollback
requirements. `MF-P6-07` through `MF-P6-12` has no D6, human, corpus-volume,
full-library, DAZ, or soak prerequisite and is the required core path.
**Goal:** The node pack (Mode A, reading gold packages directly) and the
provider-neutral FastAPI service (Mode B, live prediction on new images) both
working inside Kevin's existing ComfyUI install.
**Key gotchas:** The node pack must never write into `data\packages\` —
read-only, structurally enforced (`Plan\13` §5, mirrors QC-030). Mode A has
zero heavy dependencies (no cv2, no model loads) specifically so it can
never destabilize Kevin's existing ComfyUI environment.
**Required exit:** all `core_autonomous_runtime` gates through `MF-P6-12.06`
pass with matching release/adoption receipts. `MF-P6-EXIT`/D8 remains legacy
node/workflow portfolio evidence.

## P7 — Scale & Continuous Operation (optional/post-core maturity)
**Entry gate:** P6 exit plus current currency, certificate, and rollback reviews.
**Goal:** Scale to 300 (then 500) optional legacy training/scale packages in
`human_anchor_train` or exact `autonomous_certified_gold`, with truth tiers separate and
`operationally_certified_artifact`/bridge certificates explicitly ineligible; prove the retrain cadence
works at least once, execute every runbook operation (backup restore, gc,
failure-mining resolution, incident drill) at least once for **D10**, then
run the optional scale/independent-accuracy headline test. This is not the
core finish line.
**Key gotchas:** Ontology growth (per-toe splits, finer thigh bands, etc.)
requires real evidence (≥10 distinct failure-queue items in 30 days per
missing boundary, doc 12 §8) — don't add labels speculatively.
**Exit:** `MF-P7-07.07` plus `MF-P7-EXIT`: 20 unseen images processed through
selective autonomous certification/residual routing with a preselected blinded
mixed audit, no routine per-image correction, zero format/L/R failures, and
separate labor, quality, and confidence reporting.

## P8 — Autonomous Multi-Person / Multi-Character Masking
**Entry gate:** P7 substantially complete for the legacy portfolio-scale P8 lane. The bounded
human-free core ownership/integration case in `MF-P6-12.03` has no P7 prerequisite.
**Goal:** Every promoted instance is correctly separated, contact/occlusion is reciprocal,
certificate-covered instances bypass routine review, and only residual/preselected audits reach CVAT.
**Key gotchas:** Solo certificates never authorize overlap/contact/crowd contexts. QC-035/036,
image-group split integrity, exact instance identity, mixed audits, and serious-failure revocation remain hard blockers.
**Exit:** `MF-P8-11.07` plus `MF-P8-EXIT`: the real 10–20 image demonstration
has zero measured cross-instance bleed with complete certificate/residual/audit evidence.
This legacy human-audited exit supports independent accuracy. Core multi-person
integration closes through the human-free `MF-P6-12.03` and qualification matrix.

## P9 — Reference/DAZ Expansion (optional post-core maturity)
**Entry gate:** `core_autonomous_runtime` is complete and the exact DAZ assets, renderer/runtime,
storage, and optional work authorization needed by the selected P9 slice are available.
**Goal:** Qualify hash-bound assets and topology mappings, render exact synthetic PART/MATERIAL/
instance/depth/normal truth, measure whether it improves declared routes, and run the scoped
reliability period for `scale_daz_maturity`.
**Key gotchas:** Fixture-only schemas are not live asset authority; unqualified assets remain
quarantined; synthetic geometry does not become independent real-image truth; DAZ status cannot
change `core_autonomous_runtime`.
**Exit:** `MF-P9-EXIT` closes only `scale_daz_maturity` for its frozen asset/runtime/observation
scope. It is never a project-wide or core finish line.
