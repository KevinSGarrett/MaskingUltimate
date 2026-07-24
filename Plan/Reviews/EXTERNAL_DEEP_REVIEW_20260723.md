# MASKFACTORY / MASKINGULTIMATE — EXTERNAL DEEP REVIEW
## Masking & Segmentation System + Self-Hosted Autonomous Work-Cell Strategy

Date: 2026-07-23
Reviewer: Claude (external review session, read-only; no repo, tracker, or pod state was modified)
Scope reviewed:
- `C:\Comfy_UI_Main_Masking` (main repo, branch `codex/maskfactory-runtime-implementation`, dirty runtime root)
- `C:\w\maskfactory-plan-modernization` (active side branch `codex/maskfactory-plan-modernization`, head c85204659)
- `C:\w\*` (worktree/recovery-clone farm, ~40 directories)
- GitHub `KevinSGarrett/MaskingUltimate` (origin of both roots; 9 remote branches, 12 registered worktrees)
- Plan docs 00–26 (focus: 25 self-hosted visual authority, 26 adult corpus batch ingestion), Instructions 00–15,
  STANDING_ORDERS_AUTONOMOUS_BUILD, SIDE_SESSION_RESUME_RUNPOD_SAM31_WORKCELL_20260723
- Live tracker (DASHBOARD generated 2026-07-23T18:26Z), OPS_LOG through 2026-07-23,
  visual-critic qualification evidence (protocol v2 / contract v3 / evidence boards v5–v6),
  visual_critic_catalog.yaml, work-cell source (`src/maskfactory/autonomy/work_cell*.py`,
  `development_bundle.py`), mission + patch-bundle schemas, shard-0001 runtime evidence.

Note on "original project folder (before it became dirty)": the cleanest current expression of the
original governed project is the `maskfactory-plan-modernization` worktree plus the GitHub remote;
`C:\Comfy_UI_Main_Masking` is the dirty runtime-implementation root (510 uncommitted paths). Both were
reviewed in full.

---

# 0. EXECUTIVE VERDICT

The architecture is exceptional. The authority lattice (source_reference -> detection_proposal ->
mask_candidate -> machine_verified_candidate -> strict_visual_pass_bounded -> operationally_certified ->
autonomous_certified_gold), the proof-tier ladder, the claim firewall, fail-closed schemas, hash-bound
evidence, actor separation in the work cell, and typed abstentions are stronger than what most
production ML organizations run. Nothing in this review recommends weakening any of it.

The project's problem is not design. It is that the entire factory now funnels through exactly one
gate — qualified primary visual critic + independent-family juror (MF-P4-11.18 / 11.23) — and that
gate is currently failing for two compounding, fixable reasons:

1. A measurable, bimodal critic-protocol failure: every strong model rejects all valid masks;
   every weak model rubber-stamps everything. This is substantially a protocol/rubric/calibration
   design problem, not purely a model-capability problem, and it is fixable without new hardware.
2. A calibration-data famine: only 2 of 66 canonical labels currently have eligible real
   positive controls (hair, neck: 25 positives). Even a perfect critic cannot qualify against a
   corpus that does not exist.

Everything else — 81,910-record corpus terminalization, semantic requalification of the 641
quarantined legacy packages, training, champions, Mode B serving, the ComfyUI bridge, and the
`core_autonomous_runtime` close — is queued behind those two items. They are the critical path,
and both are attackable this week. The remainder of this review is organized around that fact.

---

# 1. MEASURED CURRENT STATE (facts as of 2026-07-23)

- Portfolio: 601/866 items (69.4%). Required profile `core_autonomous_runtime`: **blocked**.
- Tracked truth-tier counts: `autonomous_certified_gold_count = 0`, `strict_visual_pass_count = 0`,
  `certified_training_package_count = 0`, `human_anchor_* = 0`, champions = 0,
  `quarantined_legacy_package_count = 641`.
- Reference lane (CivitAI, 26 shards): shard 0001 fully covered at provider + hard-QC stage —
  256 records; 132 generated / 25 provider abstain / 99 catalog abstain; 133 draft masks;
  hard-QA 119 pass / 13 fail / 124 upstream abstain; one incident orphan quarantined; atomic
  per-record publication added (commit 302ffc2d6). Visual review, repair, terminal receipts,
  certification: all abstained pending qualified critics.
- SAM 3.1 runtime: box-refinement fixed with the `text:"visual"` sentinel;
  `strict_box_clip_component_cleanup_v1` added (dominance-gated, capped removed fraction, prompt
  point retained); resident-process pattern adopted (one model load served 65 person requests).
- Adult corpus adoption (doc 26): 16 datasets, 81,910 records, 322 shards/platform, sealed
  registry + shard index; CivitAI 6,537 files locked to reference-only/no-mask-truth roles;
  Porn-Blocker-Benchmark frozen evaluation-only.
- Positive-control status: 2/66 canonical labels have eligible real positive controls
  (hair + neck; 25 positives + 5 typed defects from CelebAMask-HQ, identity/split disjoint,
  15/15 calibration vs qualification_holdout). Canonical-anus polygon candidates: 31 reject /
  1 abstain on exact-record semantic screening. Deficit planner v2 reports 64/66 labels missing.
- Visual-critic qualification (all statuses = fail; RTX 6000 Ada 48GB, deterministic replay ok):

  | model | role | defect recall | precision | serious false-pass | valid-mask pass |
  |---|---|---|---|---|---|
  | qwen3_6_27b_fp8 (contract v3) | primary | 0.90 | 0.82 | 0.00 | **0.00** |
  | qwen3_6_27b_fp8 (board v5) | juror | 1.00 | 0.83 | 0.00 | **0.00** (label acc 0.5, ownership 0.0) |
  | internvl3_5_8b (protocol v2) | juror | 1.00 | 0.83 | 0.00 | **0.00** |
  | internvl3_5_8b (contract v3) | juror | 0.70 | 0.78 | 0.00 | **0.00** (abstention 0.25) |
  | minicpm_v_4_5 | primary | 0.30 | 1.00 | **0.50** | 1.00 |
  | glm_4_1v_9b_thinking (v3+v6) | primary | 0.00 | 0.00 | **1.00** | 1.00 |
  | pixtral_12b_2409 | primary | 0.00 | 0.00 | **1.00** | 1.00 |

- Qwen3-VL-30B-A3B-Instruct-FP8: downloaded (32.3 GB, single-GPU feasible), calibration null;
  its 2026-07-23 current-protocol run completed but was correctly re-classified as a
  protocol-behavior canary only (12 cases, single label `right_arm_external_reference`);
  the 66-class promotion firewall honestly reports 0/66 canonical coverage.
- Frozen qualification thresholds in force: defect recall >= 0.95, valid-mask pass >= 0.90,
  precision >= 0.80, serious false-pass <= 0.00, label accuracy = 1.0, ownership accuracy = 1.0,
  evidence localization = 1.0, schema compliance = 1.0, deterministic replay = 1.0,
  abstention <= 0.05, p95 latency <= 12s — evaluated on ~12-case boards.
- Hardware: one RunPod RTX 6000 Ada (48 GB, pod 1q4ji0gg1fkhvt). Senior/arbiter tier
  (Qwen3.5-122B ~127 GB, 397B ~406 GB, InternVL3.5-241B ~481 GB) remains planned-only.
- Governance moves this week (all correct): GPU/VRAM lease authority fully retired to telemetry;
  Windows shared coordinator retired; real-data-first learning order adopted; DAZ deferred
  post-core (storage floor breached anyway: 140.4 GiB free < 150 floor); doctor_fail_count = 4.
- Repo hygiene: main root 510 dirty paths + ~14 stray `.git/index.*` backups and `.lock.lock`
  residue; modernization worktree 97 dirty paths; ~40 directories under `C:\w`, most of them
  July 17–18 worker-control recovery clones and hash-dir farms (aiw/, mfw/, ctrlcp_*).

---

# 2. PART A — MASKING / SEGMENTATION SYSTEM: FINDINGS AND RECOMMENDATIONS

## A1. The critic bimodal failure is partly a protocol artifact — fix the protocol first (P0)

The measured pattern is unambiguous. The two capable models (Qwen3.6-27B, InternVL3.5-8B) achieve
0.70–1.00 defect recall with zero serious false-passes — exactly what you want from a veto — yet
pass 0% of valid masks. The weak models pass 100% of valid masks and catch 0% of defects. Nobody
threads the needle, and that shape points at the protocol as much as the models:

1. **Conjunction math.** The rubric demands 10 binary dimensions and any single "defect" fails the
   whole verdict. If a model has even a modest per-dimension false-alarm rate p on valid masks,
   P(overall pass | valid) ~ (1-p)^10. At p = 0.15 that is ~20%; at p = 0.25 it is ~6%. A strong,
   suspicious model is mathematically doomed to fail `valid_mask_pass_rate >= 0.90` under this
   contract even when its judgment per dimension is decent. The board-v5 transcript shows exactly
   this: on `vcr_001_valid` Qwen marks laterality/occlusion/ownership/protected "pass" but flips
   anatomy/boundary/leakage/topology to "defect" — classic per-dimension over-triggering.
2. **Critic-persona prior.** A model instructed to be a strict defect-finding critic over a
   10-item checklist has a strong prior toward finding fault. There is no anchor in the prompt
   for what an *acceptable* boundary looks like at this label's annotation fidelity.
3. **Ground-truth fidelity mismatch.** The valid positives currently come from CelebAMask-HQ
   (hair/neck) — external labeled references with famously loose boundaries. A pixel-strict
   critic that flags a coarse-but-correct hair mask's boundary is not hallucinating; it is
   applying a stricter standard than the source annotation can support. Tolerance must be bound
   to the source's declared fidelity tier, or every external-reference positive will fail forever.

### Recommended protocol v3 (all compatible with the frozen-threshold rule if issued as a new
### immutable protocol/threshold version — the registry model already supports this):

- **Severity-graded findings.** Replace binary pass/defect per dimension with
  none / cosmetic / minor / serious. Derive the verdict deterministically: serious anywhere =>
  defect; minor-only within per-label budget => pass_with_findings; else pass. Serious false-pass
  stays at 0.00; the conjunction trap disappears because cosmetic noise no longer fails a record.
- **Per-label, per-fidelity tolerance bands.** Bind acceptance tolerances to the source authority
  tier (`external_labeled_reference` vs certified package bytes) and to label scale — you already
  do exactly this in the deterministic QA registry (doc 25 §15); mirror it in the visual contract.
- **Reference-anchored comparative judging.** Include one known-good exemplar panel of the same
  label (from the calibration split, image-disjoint) in the prompt as the standard of acceptable
  tightness. VLMs are dramatically better at "is B as good as A" than at absolute grading.
- **Describe-then-judge two-pass.** Pass 1: model describes what the mask covers and where its
  boundary sits (grounding, no verdict). Pass 2: verdict conditioned on its own description.
  This measurably reduces defect-prior bias and produced the evidence-localization behavior the
  contract already demands.
- **Few-shot rubric anchors.** One passing and one failing worked example (calibration split,
  hash-bound into the prompt fingerprint) so "minor vs serious" is demonstrated, not implied.
- **Per-dimension focused queries where latency allows.** Six 2-second single-dimension questions
  frequently beat one 12-second omnibus on accuracy; the p95 12s budget already accommodates this
  for batch review on a dedicated critic window.
- **Calibrated deterministic decision layer.** Keep the model's raw graded findings as evidence,
  and fit the mapping from findings -> verdict (severity weights, minor-budget per label) ONLY on
  the calibration split, freeze it as part of the protocol fingerprint, then evaluate untouched
  on `qualification_holdout`. Your own 15/15 calibration/holdout split was built for exactly this.
  This honors "thresholds are frozen before the run" — the freeze happens before holdout contact,
  and a new protocol version is a new immutable registry entry, never an in-place edit.
- **Verdict-semantics amendment for doc 25 §7/§8 (proposed, needs your adoption):** redefine
  acceptance as "deterministic QA vector passes AND no qualified critic reports a serious defect
  AND evidence localization is coherent", rather than "the VLM says pass". The measured models can
  already support the first formulation (their zero serious-false-pass is the hard part and it is
  done); none can support the second. Fail-closed behavior on malformed/timeout/uncertain output
  is unchanged. This is the single highest-leverage sentence in this review.

### Why this ordering matters
Re-running the existing five single-GPU models plus Qwen3-VL-30B under protocol v3 against the
existing 30-control CelebA board costs a few GPU-hours and zero new hardware. If protocol v3 still
fails everything, you have cleanly isolated a model-capability gap and the burst-GPU tournament
(A4) is justified with evidence. If it passes, the entire factory unblocks. Either way you learn
the most important fact in the project for the least money.

## A2. Positive-control famine: run one planned 66-label sourcing sweep, not label-at-a-time (P0)

The CelebA control admission (2/66) proved the pipeline works: candidate selection -> per-record
exact-zoom semantic screening -> identity/split disjointness -> sealed admission. The anus batch
(31/32 rejected) proved the screening is honest. Now industrialize it:

- Extend `build_visual_corpus_source_deficits` from reporting deficits to **emitting candidate
  batches for every deficit label in one deterministic plan**: qualified polygon/RLE datasets
  first (16-dataset corpus, label-crosswalked), CelebAMask/LaPa/LV-MHP for face/hair/parsing
  labels, then shard-0001's 119 hard-QC-passing SAM3.1 drafts as *candidate* controls for
  person/limb-scale labels. Render panels for all of it in one GPU pass; screening is then
  review-only.
- Target coverage floors before critic promotion: >= 10 positives + >= 5 typed negatives per
  label for the top-20 risk labels (adult anatomy, hands, laterality pairs, multi-person
  ownership), >= 5/3 for the rest, growing toward the 100+ per-role boards in A3. 25 positives
  on 2 labels cannot qualify a 66-class role and the promotion firewall already says so.
- **Governance decision needed (flagging a live ambiguity):** the CelebA/anus per-record
  screening decisions were made by the interactive coding-agent session inspecting panels. That
  is a frontier-model-in-the-loop *control admission* step. Standing orders forbid cloud LLMs for
  "MaskFactory VLM QA"; control admission is QA-adjacent but is not mask certification. Two
  coherent policies exist — (a) codify session-agent screening as a bounded, logged,
  non-certifying control-admission activity (fast, precedent already set twice), or
  (b) restrict screening to self-hosted critics only (slower; circular until one qualifies).
  Recommend (a) with an explicit doc-25 §7 sentence and a decision-log entry, because the output
  is calibration controls, never gold, and every decision is already hash-bound and auditable.
- **Seeded-defect factory.** Negatives are cheap and you control them: build a deterministic
  defect-operator library (boundary erode/dilate, leakage paste, wrong-label swap, wrong-side
  flip, hole punch, component scatter, owner swap) applied to admitted positives, parameterized
  and hash-bound. Doc 25 §7 already names these; make the generator a governed tool so every
  label gets its full negative taxonomy automatically. This also feeds A5's quality regressor.
- **The optional human hour (stated honestly, not required).** Core explicitly excludes human
  anchors, and nothing here changes that. But the math is worth seeing: ~2–3 hours of your own
  CVAT clicks producing 30–60 anchors across the rarest labels would simultaneously unblock
  MF-P4-05.01, 09.06, 07.04, 08.08, 10.08, and P1-08.02–05, and would hand the critic-calibration
  corpus its highest-authority positives. It is the single highest-leverage optional human hour
  available anywhere in the project. If you never do it, the autonomous path above still works;
  it is just slower and leans harder on external-reference fidelity tiers.

## A3. Qualification statistics: 12-case boards with 1.0 point-estimate gates cannot work (P0)

Several thresholds (label accuracy = 1.0, ownership = 1.0, evidence localization = 1.0) are point
estimates over ~12 cases with ~2 valid positives. One hiccup = fail; passing proves little; the
board cannot distinguish a good model from a lucky one. You already use one-sided 95% Wilson
bounds for risk certification (MF-P4-11.09) — apply the same machinery here:

- Keep the current 12-case boards as **cheap stage-1 canaries** (you already reclassified the
  Qwen3-VL run this way — correct instinct; make it the rule).
- Promote roles only from **stage-2 boards of >= 100 cases per role** (e.g., 40 valid across
  fidelity tiers + 60 seeded/natural defects across the taxonomy), scored by Wilson lower bounds
  (e.g., serious-defect recall LB95 >= 0.90; valid-pass LB95 >= 0.80) rather than raw 1.0s.
  Zero-tolerance stays only where it belongs: serious false-pass and schema compliance.
- Freeze each board as a new immutable registry version; never resize a live board.

## A4. Widen the critic field with a burst-rented GPU tournament (P1, after A1 evidence)

The single 48 GB pod caps you at ~30B-class critics, and doc 25's arbiter tier (122B–481B) needs
3–10 GPUs you do not rent. Bridge sensibly:

- Rent one A100/H100-80GB (or 2×48GB) for a 1–2 day qualification tournament only; production
  stays on the 6000 Ada. Candidates within the family-independence rule:
  Qwen3-VL-30B-A3B-Instruct-FP8 (already downloaded, single-GPU), Qwen3.6-35B-A3B-FP8 (already
  downloaded, needs headroom or 80GB), InternVL3.5 mid-size (38B-class) as the independent
  family, Qwen2.5-VL-72B-AWQ (~40–44GB) as a stretch, MiniCPM-V-4.5 retest under protocol v3.
  Note your catalog currently lists MiniCPM under family_id `qwen` — verify; if its LLM base is
  Qwen it correctly cannot form quorum with a Qwen primary, and the catalog is right.
- Quantization is part of the frozen fingerprint (your rule, keep it): any AWQ/INT8 variant
  requalifies from scratch; a quantized juror that fits co-resident with SAM3.1 on the 48GB pod
  is the prize outcome of the tournament.
- The multi-GPU arbiter tier stays planned until two single-GPU roles qualify; an arbiter with
  no qualified critics beneath it resolves nothing.

## A5. Add cheap deterministic-adjacent quality signals so the VLM answers a narrower question (P1)

- **Mask-quality regressor:** train a small IoU/boundary-F predictor (or reuse SAM's own IoU
  head + stability score, which you get free per candidate) on the seeded-defect factory output.
  It is never authority — it feeds the calibrated decision layer and hard-case mining ranker.
- **Disagreement-driven review budget:** you already compute proposal IoU/boundary disagreement;
  route high-agreement + high-regressor-score candidates to a lighter critic contract and spend
  the expensive multi-zoom contract on the disagreement tail. Same rigor, ~2–4x review throughput.

## A6. Land the second provider family before scaling past shard 0001 (P1)

Shard 0001 ran effectively SAM3.1-only at the provider stage. The mission schema requires >= 2
distinct families, doc 25 §5 prefers >= 3 hypothesis-distinct paths, and the disagreement map —
the input to bounded repair ROIs — needs genuinely independent proposals. BiRefNet and
SAM2Matting are already live-verified challengers; wire one of them into the shard pipeline now.
Processing 25 more shards single-family means re-touching every record later for tournament
evidence — that is the expensive kind of rework the work cell exists to avoid.

## A7. Pre-stage the two things that make qualification day explosive (P1, zero risk)

- **Pre-render label-aware panels for all 641 quarantined legacy packages** during idle GPU time.
  Panel rendering is critic-independent; when a primary + juror qualify, the bulk semantic
  requalification wave becomes review-only and the 641-package quarantine can be burned down in
  days instead of weeks.
- **Stage the MF-P4-12.10 golden-record mission manifest now** (one exact record, full chain:
  source -> detection -> multi-provider -> QA vector -> quorum -> repair-if-needed -> semantic
  alignment -> immutable autonomous_certified_gold -> verify -> revoke -> replay). The day a
  quorum qualifies should end with the first certified-gold record in existence, not with
  manifest authoring.

## A8. Video, audio, DAZ boundaries — all currently correct; two cheap keep-warm items

- Video stays behind the go/no-go authority (right call). Keep the MatAnyone2 runtime lock
  current and retain temporal-ready metadata (frame index / source-video identity) on every
  record so the still-image corpus is video-upgradeable without re-ingestion.
- Audio remains metadata-only context (doc 26 §14) — no change; resist any future temptation to
  let audio context influence pixel authority.
- DAZ stays gated on the immutable residual-gap report (doc 26 §15) — the real-data-first
  adoption this week was the right strategic move; do not revisit until MF-P5-11.09 exists.

## A9. Smaller system items worth clearing

1. `doctor_fail_count = 4`: triage each failing check into fixed or typed pod-class N/A so the
   doctor reads honestly green-or-typed; a chronically part-red doctor trains agents to ignore it.
2. Storage: DAZ floor breach (140.4 < 150 GiB) is dormant-safe, but the same disk carries live
   work. `runtime_artifacts` holds ~12 versioned copies of the nude_polygon_refinement canaries,
   multiple multi-GB deploy tars, a vendored numpy tree under pycocotools_diag, and corpus tars —
   adopt a retention rule (keep latest 2 versions + anything referenced from
   qa/live_verification) and GC the rest; likely tens of GiB back.
3. Add `.gitignore` defaults for `runtime_artifacts/**` with an explicit allowlist for evidence
   promoted into `qa/live_verification/` — this single rule prevents most future "dirty repo"
   accumulation at the source.
4. `models/detect/yolo11m.pt` sits as a loose binary in-tree; confirm it is registry-bound and
   DVC/LFS-tracked like every other checkpoint.
5. Ontology count language drifts between "56 active v1 / 65 after v2" (older items) and the
   66-class firewall (current). The firewall is authoritative; sweep stale "65" references in
   Items text during the next tracker rebuild so future agents do not chase a phantom class.

---

# 3. PART B — SELF-HOSTED AUTONOMOUS WORK-CELL / LLM STRATEGY

## B0. What is already right (do not change)

Your instinct — stop shuttling micro-diffs between Codex Desktop and the pod; make the pod a
resident work cell that processes thousands of items and hands sealed batches back — is correct,
and the implementation is further along and better-governed than the way you described it:

- Mission manifests hash-bind ontology, target-contract schema, QA registry, provider catalog,
  critic catalog, and certification policy; >= 2 provider families enforced; authority ceiling
  explicit; output prefix escape-proofed.
- Ten-stage state machine with per-stage allowed actors (visual critics literally cannot write
  pixels, clear hard QC, or certify), leases/heartbeats/idempotent receipts, SQLite durability,
  crash/resume proven by canary.
- `bulk_policy` hard-codes the exact operating mode you asked for: milestone-only reporting,
  per-record chat suppressed, no routine human review, self-hosted bulk review, typed terminal
  outcomes (accepted/abstained/quarantined/rejected).
- Typed visual-unavailability abstention lets providers + hard QC keep producing while critics
  are unqualified — which is exactly why shard 0001 could complete its first two stages this week.
- The development patch bundle keeps Codex as the sole git authority: allowed-path scoping,
  >= 2 independent deterministic validators, git/gh forbidden as worker validators, sealed
  hashes, no-adoption ceiling. The pod prepares work; Codex adopts it. That separation is the
  correct answer to "self-hosted LLM does the work, Codex reviews" and it is already built.

The strategic caution to keep in view: the measured critic results show the self-hosted VLM is
not yet a near-frontier judge. The winning design — which docs 25/26 already encode — is that
deterministic code remains the authority and does most of the filtering, VLMs answer a narrowed
question as witnesses, and the text LLM only plans. Keep pushing intelligence into deterministic
gates and calibrated decision layers; buy VLM judgment only where pixels genuinely require eyes.

## B1. Add the missing pod-resident "mission steward" (text-LLM planner) (P1)

Doc 26 §13 assigns the text/planning model batch planning, failure clustering, coverage analysis,
hard-case selection, repair-hypothesis drafting, and milestone/exception summaries — but today
that thinking happens inside interactive Codex sessions between batches. Deploy a text model on
the same loopback (a Qwen3.6-27B text variant or smaller MoE is ample) as a steward job that:
watches queue/checkpoint state; drafts the next-wave mission manifest as a *proposal* the
deterministic validator must accept; clusters failure reasons from records.jsonl; ranks hard
cases for the next shard; and writes the milestone narrative. Strictly non-authoritative —
proposals and prose only. This converts "Codex thinks between batches" into "the pod thinks
between batches; Codex reviews sealed outputs," which is the last step of the round-trip
elimination you set out to achieve.

## B2. Pod-resident watchdog; finish inverting the Windows babysitter (P1)

`visual_critic_current_protocol_20260723` still drives lease-expiry wakeups from Windows
PowerShell (`wake_coordinator_at_expiry.ps1`, resume scripts) even though the shared coordinator
is retired. Port supervision pod-side: a small supervisor process (RunPod containers lack
systemd) owning heartbeat files, restart-with-backoff, a dead-man rule ("no checkpoint advance in
N minutes => restart stage worker; second stall on same record => quarantine it and move on"),
and boot-time relaunch via the pod start command. Windows becomes an optional observer. Agent
death != climb death is your standing order; this makes it structural instead of procedural.

## B3. Add a sealed "mission review bundle" for the Codex handoff (P1)

The patch bundle covers code. Add its sibling for operations: at every milestone, the work cell
seals one review bundle containing (a) the exception queue — top-K quarantines/abstentions with
their panels and reason codes; (b) metric deltas vs the prior milestone (yield per label, QC
failure histogram, repair success rate, latency, $/record); (c) threshold-breach candidates and
any proposed governed amendments; (d) exact evidence paths + hashes. A fresh Codex session
ingests one bundle instead of re-deriving state from a 12,000-line OPS_LOG and the tracker —
that is where your Codex context (and money) currently goes. This is the artifact that makes
"hand massive batches back for review" cheap on the reviewing side.

## B4. GPU plan for the 48 GB single pod — and when to add the second pod (P1/P2)

SAM3.1 resident + a 27–30B FP8 critic (peak ~45.8 GB measured) cannot co-reside; today you
serialize. Three options in order of preference once critics qualify:
1. **Second pod dedicated to critics** (cleanest; rent hourly during review waves; the mission
   schema already binds roles independently of pods). Post-qualification this is the single
   biggest throughput multiplier in the whole system: providers stream shards on pod A while
   pod B burns down the review queue and the 641-package requalification.
2. **Quantized juror co-residency**: an AWQ/INT4 juror at ~16–20 GB beside SAM3.1 — requalifies
   from scratch per your quantization-fingerprint rule (keep that rule).
3. **Time-sliced schedule policy file** the work cell reads (providers by day, critic bursts by
   night) so scheduling is self-serve rather than session-driven.
Also: run critics behind a persistent vLLM server per wave rather than load/unload per burst —
`unload_after_burst` made sense when sharing VRAM with tournament workers; a dedicated critic
window or pod removes the reload tax entirely.

## B5. Observability and steering metrics (P1, small)

One `mission_status.json` rollup regenerated at every checkpoint: records by terminal state,
per-label certification yield, quarantine-reason histogram, GPU-hours, and cost-per-record — plus
an optional one-line Slack ping at milestone cadence (you already run a Slack-centric ops stack).
When critics qualify, **$/certified-record** becomes the steering metric for every batching and
model-size decision; instrument it now so day one has a baseline.

## B6. Harden the development bundle contract (P2, cheap)

- Require the two independent validators to include at least `pytest` (focused list) and `ruff`
  by schema enum, not just "two distinct commands".
- On the Codex side, apply bundles only into a throwaway worktree, run the bundle's declared
  validator commands verbatim, and diff the declared changed-file list against the actual patch.
- Cap changed-file count / patch bytes per bundle to force decomposition of large changes.

## B7. Role-certificate lifecycle wiring (P2)

The mission role binding carries `revoked` but no expiry. P7-07.11 already mandates 90-day
requalification; stamp `qualified_until` into the role certificate and have the work cell's
binding check fail closed at expiry, so a stale critic can never silently keep reviewing.

## B8. Pod economics and durability (P2)

- The proven crash/resume queue makes **spot/community-tier pods safe** for shard climbs at
  roughly half the on-demand rate; keep on-demand only for interactive/critic-qualification work.
- Snapshot the persistent volume's sqlite queues + qa evidence on a cadence (volume persists, but
  a corrupt queue file is your real risk — the tracker already survived one parallel-write
  corruption this week per `tracker_recovery_20260723`), and continue the periodic pull to F:.
- Pin the pod bootstrap (paths.env, supervisor, model servers) into one idempotent script so a
  replacement pod reaches ready-state unattended; you are one pod-eviction away from needing it.

---

# 4. PART C — REPOSITORY AND PROCESS HYGIENE (the "dirty" problem, named directly)

## C1. Seal-and-reset the main root (P1)

`C:\Comfy_UI_Main_Masking` carries 510 dirty paths and ~14 stray `.git/index.*` backups plus
`.lock.lock` residue from crashed operations — that git directory is one bad crash away from an
index corruption incident. A deliberate seal wave, run as its own tracked item:
1. `git fsck` + verify HEAD/branch integrity first; then remove stale index backups and dead locks.
2. Commit-or-relocate by category: promoted evidence into `qa/live_verification/` (committed),
   pod scratch scripts into a gitignored `scratch/` area, panels/tars into retention-governed
   `runtime_artifacts` (gitignored per A9.3), and delete the truly disposable.
3. End state: `git status` on the main root fits on one screen, permanently, enforced by the
   gitignore-with-allowlist rule.

## C2. Archive-and-delete the C:\w farm (P1)

Roughly 25 of the ~40 directories are July 17–18 worker-control recovery clones plus hash-dir
farms (`aiw/`, `mfw/`, `ctrlcp_*`) from dead sessions. For each: check for unpushed work
(`git log --branches --not --remotes` + `git status`), tar anything unique into an archive
folder, delete the rest. Two `.patch` files at the C:\w root capture some of that history
already. This reclaims disk and — more importantly — removes a navigation tax: a fresh agent
listing C:\w today can burn an entire session just orienting. Keep exactly: the active
modernization worktree, mask-autonomy-bridge-plan lineage if still referenced, and the archive.

## C3. Branch reconciliation before the divergence compounds (P1)

Two long-lived diverging lines — `codex/maskfactory-runtime-implementation` (with 510 dirty
paths on top) and `codex/maskfactory-plan-modernization` (the adopted work-cell + SAM3.1 fixes) —
is an integration debt that grows daily. Sequence: land plan-modernization to the mainline via
PR; then absorb the runtime-implementation dirty work in bounded, scoped commits (the standing
orders already forbid absorbing unrelated dirt); then designate ONE canonical build worktree and
retire per-session throwaway clones in favor of `git worktree` off the single repo. Twelve
registered worktrees against one repo is fine as a mechanism; forty sibling clone folders is not.

## C4. Session-workspace convention going forward (P2)

Adopt one rule for all future agent sessions: new session = new `git worktree add` under
`C:\w\active\<purpose>-<date>`, deleted (worktree remove) at session seal, with anything durable
pushed or bundled first. The KICKOFF prompt and Instructions 03 can carry the one-liner. This
prevents the farm from regrowing.

---

# 5. WHERE THIS REVIEW TOUCHES GOVERNED RULES (explicit, for your decision log)

None of the recommendations weaken a hard gate. Three do require your explicit adoption as
governed amendments, consistent with how docs 25/26 were adopted:
1. **Verdict semantics** (A1): acceptance = deterministic QA + no-serious-defect quorum +
   coherent localization, replacing VLM-says-pass. New protocol/threshold registry version.
2. **Control-admission screening authority** (A2): codify session-agent per-record screening as
   bounded, logged, non-certifying — or explicitly forbid it and accept the slower path.
3. **Candidate-derived calibration controls** (A2): allow hard-QC-passing, consensus-backed,
   individually screened drafts as calibration-only positives (never gold, never training truth),
   amending doc 25 §7's blanket draft ineligibility for this one narrow, hash-bound use.

---

# 6. RECOMMENDED EXECUTION ORDER (next ~2 weeks)

1. **Critic protocol v3** (A1): severity-graded rubric, reference-anchored prompting,
   describe-then-judge, calibrated decision layer frozen on the calibration split. Rerun all
   five failed single-GPU models + Qwen3-VL-30B against the existing 30-control CelebA board.
   Cost: a few GPU-hours. This is the highest-information action available in the project.
2. **66-label positive-control sweep** (A2): deficit planner emits candidate batches for every
   label; render all panels in one GPU pass; screen per-record; adopt the three governed
   amendments (Section 5) in the decision log first. Floors: 10/5 for top-20 risk labels.
3. **Burst-GPU qualification tournament** (A4) if and only if protocol v3 leaves a capability
   gap: 1–2 days on an 80 GB pod, family-independent field, stage-2 boards per A3.
4. **Second provider family into the shard pipeline** (A6) before any shard past 0001 runs.
5. **Repo seal-and-reset + C:\w archive + branch reconciliation** (C1–C3), as tracked items.
6. **Pod-resident watchdog + mission steward + milestone Slack rollup** (B1, B2, B5).
7. **Pre-render 641 legacy panels + stage the MF-P4-12.10 golden-record manifest** (A7), so
   qualification day ends with the first `autonomous_certified_gold` in existence and the
   legacy quarantine burn-down starts the same week.

Post-qualification sequence (already correctly encoded in the plan, restated for continuity):
golden record -> shard 0001 terminalization -> remaining 25 reference shards + polygon lanes ->
641-package bulk requalification -> qualified training datasets (P5-11) -> real-supervision
foundation -> teacher-student cycles -> residual gap report -> only then DAZ scale.

---

# 7. APPENDIX — KEY PATHS AND EVIDENCE REVIEWED

- Standing orders: `C:\Comfy_UI_Main_Masking\Plan\STANDING_ORDERS_AUTONOMOUS_BUILD.md`
- Resume handoff: `Plan\SIDE_SESSION_RESUME_RUNPOD_SAM31_WORKCELL_20260723.md`
- Governing amendments: `Plan\25_SELF_HOSTED_VISUAL_AUTHORITY_AND_RUNPOD_MIGRATION_SPEC.md`,
  `Plan\26_ADULT_CORPUS_AUTONOMOUS_BATCH_INGESTION_SPEC.md` (modernization worktree)
- Tracker: `Plan\Tracker\DASHBOARD.md` (2026-07-23T18:26Z), tracker.py report/next
- Critic catalog: `configs\visual_critic_catalog.yaml` (sha 322d47c2…, all calibrations fail/null)
- Qualification evidence: `runtime_artifacts\visual_critic_protocol_v2_20260722\*_qualification.json`
- Current-protocol canary: `runtime_artifacts\visual_critic_current_protocol_20260723\`
- Work cell: `src\maskfactory\autonomy\work_cell*.py`, `development_bundle.py`,
  `src\maskfactory\schemas\runpod_autonomous_mission.schema.json`,
  `runpod_development_patch_bundle.schema.json`; tools `manage_runpod_autonomous_work_cell.py`,
  `prepare_runpod_autonomous_mission.py`, `run_runpod_work_cell_stage.py`
- Shard evidence: `qa\live_verification\runpod_sam31_first_shard_*_20260723.json`,
  consolidated shard validation under `runtime_artifacts\consolidated_shard0001_validation_20260723`
- Control admission: `qa\live_verification\runpod_celebamask_control_admission_20260723.json`,
  `visual_corpus_source_deficits_v2_20260723.json`
- Pod: 1q4ji0gg1fkhvt (RTX 6000 Ada 48GB); assets at `/workspace/assets/MaskedWarehouse` and
  `/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images` via `/workspace/paths.env`

END OF REVIEW
