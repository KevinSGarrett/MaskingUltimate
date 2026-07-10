# 07 — Phase Quick Reference

Condensed cheat-cards for each phase. These are quick-orientation aids, not
replacements — full detail always lives in `Plan\0X` (spec) and
`Plan\Items\0X` (checklist).

---

## P0 — Environment & Foundation (days 1–3, target)
**Entry gate:** none — first phase.
**Goal:** A fully working local environment: WSL2 + cu128 PyTorch on
Blackwell (sm_120), Docker/CVAT/nuclio, Ollama + local VLM, all 12 model
checkpoints registered, `maskfactory doctor` all-green, repo + CI scaffold.
**Key gotchas:** sm_120 needs PyTorch ≥2.7 cu128 wheels specifically — older
builds fail with "no kernel image available." `/mnt/c` I/O is slow for many
small files; hot work goes on WSL's own ext4 (`~/mfwork`). detectron2/mmcv
may need source builds on cu128. Full pitfall list: `Plan\06` §8.
**Exit:** `MF-P0-EXIT` — doctor green end-to-end, lockfiles + populated
model registry committed.

## P1 — Gold Factory MVP (weeks 1–2)
**Entry gate:** P0 exit.
**Goal:** One real image can go incoming → CVAT (Kevin annotates) →
approved gold package, with format QA (QC-001…010) structurally enforced.
First 5 gold packages produced by hand.
**Key gotchas:** Binary masks are always regenerated from the two label
maps (`label_map_part.png`, `label_map_material.png`) — never hand-edit a
binary PNG directly (QC-030). The age-safety intake gate is non-configurable
(`Plan\01` §7). `ontology.yaml` is generated from spec tables, never
hand-written (`MF-P1-03`, a hard blocker).
**Exit:** `MF-P1-EXIT`.

## P2 — Body-Aware Drafting (weeks 2–4)
**Entry gate:** P1 exit.
**Goal:** Full automatic drafting pipeline (S01–S09): person detection,
silhouette, parsing, pose, the geometry engine (limb capsules, joint bands,
torso partition), GDINO-assisted SAM2 refinement, and consensus fusion into
the master maps. First G2 (draft-quality IoU) measurement.
**Key gotchas:** GroundingDINO output is boxes only — it can never become a
final mask directly (`Plan\07` S06). Fusion must be deterministic (seed
1337) — verify byte-identical re-runs, don't just assume it. Z-order
arbitration rules for contested pixels are exact and specific (`Plan\07`
S09) — don't substitute a simpler heuristic.
**Exit:** `MF-P2-EXIT` — **D1** should be demonstrable here (one CLI
command drafts all 56 parts for a new image).

## P3 — Specialist Lanes (weeks 4–6)
**Entry gate:** P2 exit.
**Goal:** Hand/finger, chest/breast/clothing, hair/face, and feet/toes
lanes live; DensePose 3D-prior referee wired in; topology QCs (025–034)
active; 100 approved gold packages; median review time ≤25 min (G1).
**Key gotchas:** Never guess a finger split on merged/ambiguous fingers —
label `hand_base` + `ambiguous_do_not_use` and queue to the failure log
instead (`Plan\08` §2.6). The chest/breast lane's "visible-truth
constitution" (`Plan\08` §3.3) is load-bearing: the mask always follows
what's *actually visible* (skin or fabric), never an assumption of what's
underneath — the editable guess lives only in the separate projected-region
layer, never in the atomic PART map.
**Exit:** `MF-P3-EXIT`.

## P4 — VLM QA & Active Learning (weeks 5–7, parallel to late P3)
**Entry gate:** runs alongside late P3 (needs P2's panels to exist first).
**Goal:** Local VLM review + routing (quick-pass vs. careful queue),
failure-queue mining producing weekly acquisition plans, coverage-matrix
tracking, and — critically — the VLM calibration gate passed.
**Key gotchas:** The VLM is QA/router only — it can never approve gold,
clear a BLOCK, or edit a mask, structurally (`Plan\10` §5). The calibration
gate (`MF-P4-05`, hard blocker: ≥0.90 defect recall, ≥0.80 precision on the
40-panel eval set) must re-pass on *any* model or prompt-version change,
not just once.
**Exit:** `MF-P4-EXIT` — drives **D4** directly.

## P5 — Custom Model Training (weeks 6–10; entry gate: ≥200 gold)
**Entry gate:** `metrics.approved_gold_count >= 200`. Do not start training
work before this is genuinely true — a champion trained on too little data
has no real chance at the D6 gate, and the attempt burns real GPU-hours.
**Goal:** Fine-tune all 5 specialist models, run the leaderboard, promote
champions. Drives **D6** and **D7**, the two hardest gates in the project.
**Key gotchas:** The horizontal-flip augmentation MUST remap every
left/right label via `swap_partner` — this is a hard-blocker CI test
(`MF-P5-02.02`) because a missed remap silently poisons the entire training
set with L/R errors. Holdouts (`test_holdout`, `hard_case_holdout`) must
never be readable by the training code, structurally, not just by
convention. Champion promotion is a one-line registry edit — verify the
D6 gate honestly (beats the draft pipeline on the *frozen* holdout, no hard
class regressing >2 pts) before flipping it.
**Exit:** `MF-P5-EXIT`.

## P6 — ComfyUI Integration & Serving (starts after D6)
**Entry gate:** DoD **D6** satisfied.
**Goal:** The node pack (Mode A, reading gold packages directly) and the
FastAPI inference service (Mode B, live prediction on new images) both
working inside Kevin's existing ComfyUI install.
**Key gotchas:** The node pack must never write into `data\packages\` —
read-only, structurally enforced (`Plan\13` §5, mirrors QC-030). Mode A has
zero heavy dependencies (no cv2, no model loads) specifically so it can
never destabilize Kevin's existing ComfyUI environment.
**Exit:** `MF-P6-EXIT` — drives **D8**.

## P7 — Scale & Continuous Operation (ongoing)
**Entry gate:** P6 exit.
**Goal:** Scale to 300 (then 500) gold packages, prove the retrain cadence
works at least once, execute every runbook operation (backup restore, gc,
failure-mining resolution, incident drill) at least once for **D10**, then
run the actual finish-line headline test.
**Key gotchas:** Ontology growth (per-toe splits, finer thigh bands, etc.)
requires real evidence (≥10 distinct failure-queue items in 30 days per
missing boundary, doc 12 §8) — don't add labels speculatively.
**Exit:** `MF-P7-EXIT` — the project's actual finish line: 20 never-seen
images → full pipeline → approved gold in ≤4 hours of operator time, zero
format failures, zero left/right failures.
