# PURSUING GOAL — ULTIMATE MASKING SYSTEM (MaskFactory) — REVISION 2026-07-23R
# (external-deep-review-integrated; supersedes the prior pursuing goal text in full)

Complete C:\Comfy_UI_Main_Masking / MaskFactory end to end as the production-grade autonomous
ultimate masking authority, including the binding autonomous-certified-gold quality amendment:
canonical authority tiers; exact per-record target, geometry, QA, semantic, independent
qualified-critic, repair, package, certificate, revocation, and lineage bindings; historical CAA
quarantine/requalification; complete real-corpus and CivitAI reference-only batch processing;
live RunPod qualification; immutable releases; service/recovery; and genuine single- and
multi-person ComfyUI consumption. Preserve accepted modernization/bridge lineage, keep human
review optional, never confuse proposals/VLM opinions/operational certificates with autonomous
training gold, and keep the goal active until live end-to-end evidence proves every required
core gate.

This revision additionally binds four things into the goal itself:
(1) full integration of the 2026-07-23 external deep review and Kevin's adoption of its three
governed amendments; (2) restoration of self-hosted visual authority via critic protocol v3 and
the 66-label control program as the explicit critical path; (3) a product-first anti-spin rule
so every session produces measurable masking-system progress instead of housekeeping loops; and
(4) a Git/GitHub cadence policy so the repository stays continuously, correctly updated —
clean at every session seal, without micro-PR spam and without ever again creating new project
folders to escape a dirty tree.

## 0. READ THESE, IN THIS ORDER, BEFORE ACTING

1. This entire pursuing goal.
2. C:\Comfy_UI_Main_Masking\Plan\SIDE_SESSION_RESUME_RUNPOD_SAM31_WORKCELL_20260723.md
3. C:\MaskFactory_Reviews\EXTERNAL_REVIEW_20260723\MASKFACTORY_EXTERNAL_DEEP_REVIEW_20260723.md
   (the external deep review; binding input per section 1 below)
4. Plan\STANDING_ORDERS_AUTONOMOUS_BUILD.md, then `python tracker.py report` and
   `python tracker.py next -n 15` from Plan\Tracker.

Then reconcile the recovery snapshot against current worktrees, Git state, live tracker, RunPod
runtime, and durable mission/queue state. Treat recorded branch heads and process identifiers as
observations to verify, not permanent truth. Recovery-time observed head:
a82972dbe8f46b3f3cd9d10d629f8246fbcb3ecd; later observed head c85204659 (2026-07-23); verify
the live head before building on it.

## 1. EXTERNAL DEEP-REVIEW INTEGRATION (BINDING)

- Copy the external review into the governed repo at
  Plan\Reviews\EXTERNAL_DEEP_REVIEW_20260723.md in the modernization worktree and commit it, so
  every future session sees it without depending on a loose folder.
- Kevin ADOPTS the review's three governed amendments effective 2026-07-23. Record each in
  Plan\DECISIONS_LOG.md and implement each as a NEW immutable protocol/threshold/registry
  version — never an in-place edit of a frozen artifact:

  AMENDMENT 1 — Visual verdict semantics. Per-record visual acceptance is redefined as:
  the deterministic QA vector passes AND no qualified critic reports a SERIOUS defect AND the
  critic's evidence localization is coherent — replacing "the VLM says pass". Deterministic hard
  blocks remain absolute; serious-false-pass tolerance remains 0.00; malformed, truncated,
  timed-out, uncertain, or schema-invalid critic output remains a typed abstention, never a pass.

  AMENDMENT 2 — Control-admission screening authority. Interactive session-agent per-record
  screening of calibration-control candidates (the exact procedure already used for the
  CelebAMask and canonical-anus admissions) is codified as a bounded, logged, hash-bound,
  NON-CERTIFYING control-admission activity. Its outputs are calibration controls only — never
  mask gold, never training truth, never certificates.

  AMENDMENT 3 — Candidate-derived calibration controls. A draft machine mask that passes
  deterministic hard QC, carries multi-provider pixel consensus, and passes individual
  per-record screening under Amendment 2 may be admitted as a CALIBRATION-ONLY positive control
  at its declared fidelity tier. This narrowly amends doc 25 §7's blanket draft ineligibility
  for this one hash-bound use; such controls can never become gold, training truth, or package
  authority.

- Convert the review's recommendations into tracker-visible work through tracker.py:
  P0 items (protocol v3; 66-label control sweep; two-stage Wilson qualification boards) start
  immediately; P1 items (burst tournament conditional, second provider family, panel
  pre-rendering, golden-record staging, watchdog, mission steward, review bundle, repo seal)
  are scheduled this cycle; P2 items are recorded. The tracker and governing plans remain the
  status authority; where the review conflicts with a governing plan on anything beyond the
  three adopted amendments, propose the change through DECISIONS_LOG rather than silently
  diverging.

## 2. REPOSITORY BOUNDARIES AND GIT/GITHUB CADENCE (BINDING)

Boundaries:
- Perform the modernization work in: C:\w\maskfactory-plan-modernization
- Intended branch: codex/maskfactory-plan-modernization
- Never absorb C:\Comfy_UI_Main_Masking's dirty runtime work into the modernization branch.
- The earlier blanket prohibition on touching the main root's dirty state is REPLACED by the
  governed one-time seal wave below. Nothing is discarded without classification; this is a
  seal, not a clean.

One-time hygiene seal wave (exactly one bounded wave, then done — never a recurring project):
1. `git fsck` the main repo and verify HEAD/branch integrity FIRST; only then remove stale
   `.git\index.*` backups and dead `.lock`/`.lock.lock` files, recording evidence.
2. Categorize the main root's dirty paths on their own branch: promoted evidence commits into
   qa\live_verification; pod scratch scripts relocate to a gitignored scratch\ area; panels,
   tars, and diagnostic trees move under retention-governed runtime_artifacts; only
   classified-disposable artifacts are deleted. Verified work is committed in bounded, scoped
   commits — never one giant absorb-everything commit.
3. Adopt .gitignore defaults for runtime_artifacts\** with an explicit allowlist for evidence
   promoted into qa\live_verification, in both roots.
4. Archive-and-delete the stale C:\w recovery clones and hash-dir farms (aiw\, mfw\, ctrlcp_*,
   worker-control-*): for each, check `git log --branches --not --remotes` and `git status`,
   tar anything unique into C:\w\_archive, then delete. Keep only the active modernization
   worktree, any still-referenced lineage, and the archive.
5. Register the session-workspace convention: a new session that needs isolation uses
   `git worktree add` under C:\w\active\<purpose>-<date> and removes it at session seal.
   NEVER create a new sibling clone/project folder again — the fix for a dirty tree is the
   seal procedure, not a fresh copy.

Continuous cadence thereafter:
- Commit at every sealed wave: bounded, scoped, evidence-linked messages.
- Push the working branch at every wave seal and at session end. Never end a session with
  verified work unpushed.
- No micro-PR spam: pushes go to the working branch; open or refresh at most ONE pull request
  per lane milestone (e.g., protocol v3 landed; control sweep landed; work-cell throughput
  cluster landed); merge to main only at governed integration points.
- Branch reconciliation task (schedule this cycle): land codex/maskfactory-plan-modernization
  to the mainline via PR; then absorb the sealed runtime-implementation work in bounded scoped
  commits; then designate ONE canonical build worktree going forward.
- Clean-at-seal invariant: at every session seal, `git status --porcelain` (outside allowlisted
  ignored paths) is empty or explicitly explained in the handoff. If the out-of-allowlist dirty
  count exceeds 50 mid-session, run a bounded seal step before starting new work.
- Repo hygiene after the seal wave is maintenance-by-cadence only. Re-running hygiene,
  re-auditing sealed evidence, or tidying as a primary wave is a standing-order violation.

## 3. PRODUCT-FIRST EXECUTION RULE (ANTI-SPIN, BINDING)

Real masking-product progress every session is mandatory and measurable. "Real progress" means
at least one of the following actually happened and is tracker-recorded with evidence:
- new positive or negative calibration controls admitted for a deficit label;
- a critic qualification measurement executed under a frozen board (canary or stage-2);
- records advanced to a later pipeline stage (provider -> hard QC -> visual -> repair ->
  package -> certificate) or to a typed terminal outcome;
- a work-cell throughput capability (resident predictor, persistent critic server, watchdog,
  mission steward, milestone/review bundle) proven LIVE on the pod;
- a training-preparation artifact sealed (dataset export, holdout seal, mixture manifest);
- a shard, milestone, or mission advanced through the durable controller.

Support work — documentation edits, plan rewrites, dashboard/report regeneration, re-audits of
already-sealed evidence, runtime re-probing without a new claim, tracker grooming, and repo
tidying — is capped at roughly 20% of a session after the one-time seal wave, and is never the
first or the last wave of a session. The first wave of every session advances a product lane.

Spin detection and mandatory response: (a) the same failure class twice without a new root
cause; (b) two consecutive waves with zero product-item tracker movement; (c) a third artifact
version of the same experiment without a changed hypothesis — on any of these, classify defect
vs environment, record the honest status, and SWITCH LANES immediately. Unblocked parallel
lanes always exist: control sourcing, panel pre-rendering for the 641 quarantined packages,
second provider family integration, steward/watchdog build, shard staging, golden-record
manifest staging. Never create new diagnostic project folders; diagnostics live under
runtime_artifacts governed by the retention rule (keep latest 2 versions plus anything
referenced from qa\live_verification; GC the rest).

## 4. RUNPOD EXECUTION BOUNDARY

- All production masking, segmentation, visual criticism, mask correction, corpus processing,
  training-image qualification, GPU benchmarking, and large-scale model work runs on the
  directly selected RunPod. Do not run production masking locally. Local work is limited to
  safe source development, CPU tests, schemas, manifests, evidence verification, tracker
  bookkeeping, and final authority-controlled adoption.
- The retired Windows-local shared coordinator, shared scheduler, capacity reservation, or
  cross-pod lease ledger is not an execution authority and must not block the selected pod.
  Any remaining Windows-driven lease-expiry/wake/resume scripting is ported pod-side.
- A pod-resident watchdog/supervisor is REQUIRED: heartbeat files, restart-with-backoff, a
  dead-man rule (no checkpoint advance in N minutes => restart the stage worker; a second stall
  on the same record => quarantine it and continue), and boot-time relaunch via the pod start
  command. Windows becomes an optional observer. Agent death must never equal climb death.
- Durable mission, shard, and record leases inside the MaskFactory work cell remain required
  for crash recovery, ownership, retry, checkpoint, and idempotency control.
- Pod scaling is PRE-APPROVED up to two concurrent pods without asking: the production 48 GB
  pod plus either a burst pod for critic-qualification tournaments or a dedicated critic pod
  once roles qualify. Prefer spot/community pricing for resumable shard work (the durable queue
  makes eviction safe); keep on-demand for interactive and qualification work; record cost per
  wave; scale down when idle. More than two concurrent pods requires a NEEDS KEVIN note.
- Pin the pod bootstrap (paths.env, supervisor, model servers) into one idempotent script so a
  replacement pod reaches ready-state unattended; snapshot the persistent volume's sqlite
  queues and qa evidence on a cadence.
- Never use EC2.

## 5. CURRENT VERIFIED CHECKPOINT (2026-07-23 — verify live before building on it)

- Official SAM3.1 box refinement repaired via the governed visual-text prompt path; deterministic
  strict_box_clip_component_cleanup_v1 in place; resident-process execution adopted (one model
  load serving many person requests).
- Reference shard 0001: provider + deterministic hard-QC stage coverage COMPLETE — 256 records;
  132 generated / 25 provider abstain / 99 catalog abstain; 133 hash-verified draft candidates;
  hard-QA 119 pass / 13 fail / 124 upstream abstain; one historical orphan quarantined; atomic
  per-record publication landed.
- Strict visual authority remains UNAVAILABLE: all six single-GPU critic candidates failed
  qualification in a bimodal pattern (capable models reject 100% of valid masks; weak models
  rubber-stamp 100%); the Qwen3-VL-30B run is a protocol-behavior canary only; exactly 2 of 66
  canonical labels have eligible real positive controls; all 641 legacy packages remain
  quarantined pending semantic-alignment + independent-quorum requalification.
- These facts define the current critical path. Nothing above proves strict visual approval,
  certification, autonomous gold, training truth, shard completion, or production promotion.

## 6. COMPLETE PURSUING GOAL — THE RUNPOD-RESIDENT AUTONOMOUS WORK CELL

Implement and validate the complete RunPod-resident MaskFactory autonomous work-cell
architecture end to end so that RunPod — not Codex Desktop — performs approximately 80–95% of
routine per-record mask-production and validation work in large, continuous, resumable missions.

Replace the micro-handoff pattern (Codex -> one RunPod operation -> Codex interpretation ->
another RunPod operation) with:

Codex admits one frozen, hash-bound mission -> RunPod continuously executes hundreds or
thousands of records -> RunPod reports only at configured milestones, material incidents,
patch-adoption requests, or mission completion.

The finished system must include and prove all of the following:

### 6.1 Durable, hash-bound mission admission

Every mission binds: exact input manifests and source hashes; shard identities and sample
ordering; ontology, label-map, target-contract, and ownership-policy versions; provider,
runtime, checkpoint, dependency, prompt, and implementation hashes; frozen deterministic-QA and
visual-qualification policies; permitted repair operations and protected regions; retry, time,
VRAM, attempt, changed-pixel, and resource budgets; allowed input, output, evidence, checkpoint,
and package paths; required primary-critic and independent-juror roles; certificate-authority
ceiling; checkpoint and milestone intervals; terminal, abstention, quarantine, incident, and
escalation conditions. Mission identity and policy fail closed if any bound artifact drifts.

### 6.2 Persistent RunPod-resident mission controller

A long-running controller that autonomously: claims missions, shards, and records atomically;
maintains owned leases and heartbeats; recovers expired work safely; resumes from exact sample
and stage checkpoints; enforces idempotency and prevents duplicate accepted work; distinguishes
retryable failure, terminal failure, abstention, quarantine, rejection, and submitted-unknown
states; isolates individual record failures without stopping healthy records; survives worker
or parent-process crashes; supports pod replacement without losing accepted outputs or queue
truth; enforces retry caps and typed no-progress outcomes; runs under the section-4 watchdog;
and continues until the mission reaches a real terminal state or material incident.

### 6.3 Persistent GPU-resident execution

Eliminate unnecessary per-record process creation and model reloading. The RunPod execution
layer must: keep SAM3.1 and other active providers resident across records when their runtimes
support it; run qualified critics behind a persistent server per review wave rather than
load/unload per burst (unload only when co-residency genuinely demands it); keep the GPU
productively occupied through bounded batching, prefetching, and pipeline overlap where
deterministic behavior permits; load and unload large critics according to the mission's VRAM
schedule; avoid unnecessary CPU staging gaps; preserve exact runtime, model, checkpoint, prompt,
and source identity; record model-load time separately from inference time; record throughput,
utilization, latency, VRAM, failure, and recovery metrics; never allocate VRAM merely to appear
busy; and never kill or interfere with unrelated healthy pod processes.

### 6.4 Autonomous per-record processing pipeline

The work cell carries each eligible record through the entire applicable pipeline without
conversational supervision: source decoding and integrity verification; hashing, normalization,
and transform tracking; person detection and instance ownership; laterality, front/back,
containment, and target-contract construction; multi-provider proposal generation and provider
disagreement handling; SAM3.1-first segmentation and refinement; deterministic pixel hard QA;
full-resolution source, mask, overlay, contour, ownership, and focused evidence panels;
qualified primary visual criticism; independent-family juror review; structured defect
classification and localization; bounded correction planning; segmentation-provider
regeneration or refinement; complete deterministic and visual revalidation after every pixel
change; pass, repair, abstain, quarantine, reject, or typed failure outcome; immutable revision
and evidence sealing; package construction; deterministic certificate evaluation only when
every required authority exists; and record, shard, milestone, and mission reporting.

### 6.5 Separate model and authority roles

Do not treat one model as every authority. Maintain independently bound roles for: text/code
mission planner; a POD-RESIDENT MISSION STEWARD (self-hosted text model on the loopback that
watches queue/checkpoint state, drafts next-wave mission manifests as PROPOSALS the
deterministic validator must accept, clusters failure reasons, ranks hard cases, and writes
milestone narratives — strictly non-authoritative, proposals and prose only, per doc 26 §13);
detection and ownership providers; segmentation and refinement providers; deterministic QA;
primary visual critic; independent-family visual juror; bounded correction planner;
deterministic certificate service; and mission controller.

A visual model may diagnose defects and prescribe bounded repair inputs, but it may not
directly author authoritative mask pixels, waive hard-QC failures, change frozen thresholds, or
mint certificates. Only an approved segmentation/refinement provider may change mask pixels,
and every changed mask becomes a new immutable revision that repeats the complete verification
path. Role certificates carry a qualified_until expiry (90-day requalification per P7-07.11)
and the work cell's role-binding check fails closed at expiry or revocation.

### 6.6 Strict visual-authority qualification (CRITICAL PATH — protocol v3 program)

Restore trustworthy self-hosted visual authority before allowing certification. This is the
single gate the entire factory funnels through; execute it as follows:

a) CRITIC PROTOCOL V3 (new immutable protocol + threshold registry version):
   - severity-graded findings per dimension (none / cosmetic / minor / serious) with the
     verdict derived deterministically: serious anywhere => defect; minor-only within the
     per-label budget => pass_with_findings; else pass — eliminating the 10-way binary
     conjunction that mathematically forces capable models to fail valid masks;
   - per-label, per-fidelity tolerance bands bound to the source authority tier
     (external_labeled_reference vs certified package bytes) and label scale, mirroring the
     deterministic QA registry;
   - reference-anchored comparative judging: one known-good same-label exemplar panel
     (calibration split, image-disjoint) included in the prompt as the acceptance standard;
   - describe-then-judge two-pass prompting; few-shot pass/fail rubric anchors hash-bound into
     the prompt fingerprint; per-dimension focused queries where the latency budget allows;
   - a calibrated deterministic decision layer (severity weights, per-label minor budgets) fit
     ONLY on the calibration split, frozen into the protocol fingerprint before any holdout
     contact. Serious-false-pass tolerance stays 0.00. Fail-closed behavior on malformed,
     truncated, timed-out, or uncertain output is unchanged.
   - FIRST ACTION of this program: rerun all five previously failed single-GPU critics plus
     Qwen3-VL-30B-A3B-Instruct-FP8 against the existing 30-control CelebAMask board under v3,
     BEFORE renting any new hardware. This is the highest-information, lowest-cost experiment
     available in the project.

b) 66-LABEL POSITIVE/NEGATIVE CONTROL SWEEP (runs in parallel with a):
   - extend the source-deficit planner to emit candidate batches for EVERY deficit label in one
     deterministic plan: qualified polygon/RLE datasets first, CelebAMask/LaPa/LV-MHP for
     face/hair/parsing labels, then shard-0001's hard-QC-passing drafts as candidate controls
     under Amendments 2 and 3;
   - render all candidate panels in one GPU pass so screening becomes review-only;
   - per-record screening under Amendment 2; identity/split disjointness enforced;
   - coverage floors before critic promotion: >= 10 positives + >= 5 typed negatives per label
     for the top-20 risk labels (adult anatomy, hands, laterality pairs, multi-person
     ownership), >= 5 / >= 3 elsewhere;
   - build the seeded-defect operator library (boundary erode/dilate, leakage paste, wrong
     label, wrong side, hole punch, component scatter, owner swap) as a governed,
     parameterized, hash-bound tool so every admitted positive automatically yields its full
     negative taxonomy.

c) TWO-STAGE QUALIFICATION STATISTICS: 12-case boards are stage-1 canaries ONLY and can never
   promote a role. Role promotion requires frozen stage-2 boards of >= 100 cases per role,
   scored by one-sided 95% Wilson lower bounds (serious-defect recall LB95 >= 0.90; valid-mask
   pass LB95 >= 0.80), with zero tolerance retained only where it belongs: serious false-pass
   and schema compliance. Every board is an immutable version; never resize a live board.

d) CONDITIONAL BURST TOURNAMENT: only if protocol v3 leaves a measured capability gap — rent
   one 80 GB (or 2x48 GB) pod for a 1–2 day family-independent qualification tournament
   (Qwen3-VL-30B already downloaded; Qwen3.6-35B; an InternVL3.5 mid-size as the independent
   family; a quantized juror that can co-reside with SAM3.1 on the 48 GB pod is the prize
   outcome, requalified at its exact quantization). Verify the MiniCPM family_id in the catalog.

e) QUALIFICATION CORPUS COVERAGE requirements (unchanged in substance): real, frozen positive
   and negative cases covering all required active labels and risk/domain strata — valid masks
   that must pass; seeded and natural defects that must fail; complete visible adult anatomy;
   hands, fingers, feet, toes, hair, thin structures; clothing/skin and adjacent-label
   boundaries; small/medium/large target scales; ownership and cross-person leakage;
   multi-person scenes; occlusion and contact; cropped/out-of-frame targets; laterality and
   front/back errors; wrong label/target/person/tile; unsupported pixels, holes, fragmentation,
   overfill, underfill, boundary defects; malformed, truncated, schema-invalid, evidence-free,
   hallucinated, and nondeterministic responses; replay determinism, latency, VRAM, and
   panel-budget limits. A promoted role must demonstrate GENUINE valid-mask acceptance as well
   as defect detection: rejecting everything, rubber-stamping everything, reviewing the wrong
   subject, or emitting ungrounded evidence fails qualification. Require one qualified primary
   critic plus one independently qualified juror from a different model family, with exact
   model, runtime, prompt, corpus, panel, implementation, and result hashes, frozen role
   metrics, and exact role certificates. A model-availability smoke, text-only response, narrow
   one-label corpus, synthetic-only suite, or deterministic PNG check is not qualification.
   Until this evidence exists, strict visual authority remains unavailable and every
   certification path abstains — while providers, hard QC, panel pre-rendering, and control
   sourcing continue at full speed.

### 6.7 Bounded autonomous correction loop

Failure -> structured defect hypothesis -> exact bounded ROI, box, points, mask prior, and
protected regions -> segmentation-provider repair -> new immutable revision -> full hard QA ->
primary visual critic -> independent juror. Enforce: maximum attempts; maximum changed-pixel
fraction; protected neighboring masks and instances; no seed-only retries; no VLM-authored
authoritative pixels; before/after measurements; full revalidation after every change; typed
no-progress detection; abstention or quarantine when confidence or evidence remains
insufficient; and no threshold weakening to increase yield.

### 6.8 Immutable evidence, packages, and fail-closed certification

For every attempted record, retain exact: source and transform identity; target and ownership
contract; provider inputs and outputs; prompt and runtime bindings; every mask revision and
hash; deterministic QA measurements and blockers; visual panels and hashes; primary-critic and
juror requests and responses; correction hypotheses and bounded repair inputs; retry and
recovery history; terminal disposition; package contents and hashes; certificate decision and
authority ceiling. Only the deterministic certificate service may issue a certificate, and only
when all frozen requirements, independent visual roles, package bindings, and evidence checks
pass. Never permit: certification from an unqualified critic; visual override of a
deterministic hard block; gold or training-truth promotion from reference-only sources;
certification from incomplete, missing, stale, or hash-drifted evidence; or silent continuation
after authority or schema drift.

### 6.9 Compact milestone reporting and observability

The RunPod work cell reports to Codex only for: mission admission; configured milestones
(normally every 1,000 terminal records); a systemic defect affecting a material portion of the
mission; frozen policy, schema, ontology, or implementation mismatch; persistent infrastructure
failure after bounded autonomous recovery; a complete tested patch-bundle adoption request; or
mission completion with its sealed manifest and report. It does NOT interrupt Codex for
individual mask failures, expected abstentions, normal bounded repairs, provider disagreements
governed by frozen policy, model loading/unloading, routine checkpoints, recoverable worker
exits, or individual test failures covered by an admitted repair policy.

Additions: (a) at every milestone the work cell seals one MISSION REVIEW BUNDLE — exception
queue (top-K quarantines/abstentions with panels and reason codes), metric deltas vs the prior
milestone, threshold-breach candidates and proposed governed amendments, and exact evidence
paths + hashes — so a fresh Codex session ingests one artifact instead of re-deriving state
from the OPS_LOG; (b) regenerate one mission_status.json rollup at every checkpoint (records by
terminal state, per-label yield, quarantine-reason histogram, GPU-hours, cost-per-record);
(c) an optional one-line Slack ping at milestone cadence. Full per-record evidence remains on
persistent RunPod storage; Codex receives compact summaries. Instrument cost-per-certified-
record now so day one of certification has a baseline steering metric.

### 6.10 Isolated self-hosted development missions

Allow the RunPod-hosted coding/planning model to perform substantial bounded development work
in disposable clean snapshots or isolated worktrees. Every development mission declares: exact
base commit; allowed paths; forbidden paths; acceptance contract; required validators; test and
formatting commands; runtime/resource budget; patch authority ceiling. The model may inspect,
implement, test, diagnose, and repair within that boundary, then return one signed
prepared-only patch bundle containing: base commit; changed paths; exact patch bytes and hash;
model and runtime identity; commands and complete outputs; test, lint, schema, and validator
results; at least two independent validators — which MUST include a focused pytest list and
ruff; risk assessment; known limitations; output and evidence hashes. Bundles carry caps on
changed-file count and patch bytes to force decomposition of large changes. Codex retains final
adoption, Git, GitHub, release, policy, and authoritative-branch control; applies each bundle
only into a throwaway worktree; reruns the declared validators verbatim; and diffs the declared
changed-file list against the actual patch before adoption. The RunPod development model never
silently adopts its own patch.

### 6.11 Progressive scale proof

Prove the system progressively without redefining a small canary as completion: one
deterministic SAM3.1 canary; one bounded multi-record wave; one representative 256-record shard
from every relevant supervision lane; crash, restart, expired-lease, contention, duplicate-work,
and pod-replacement recovery tests; a qualified real-image primary critic and independent
juror; a complete bounded correction and re-review canary; a 1,000-record autonomous milestone
with compact reporting; full eligible corpus-scale missions; isolated development-mission
patch-bundle canaries; and final end-to-end acceptance against the governing tracker and plans.

Measure: percentage of routine records completed without conversational intervention; recovery
success after process and pod failures; duplicate accepted-work count; provider and critic
throughput; GPU utilization, latency, and VRAM; hard-QC and visual failure distributions;
repair attempt and repair-success rates; abstention and quarantine rates; certification yield
only after authority exists; false-pass and false-reject risk; evidence and package integrity;
cost per record and (once authority exists) cost per certified record; and the product-progress
metric from section 3 per session.

Target operating outcomes: at least 90% of routine records finish without conversational
intervention; at least 95% of recoverable process failures resume automatically; approximately
one Codex interaction per 1,000 records or material incident; zero duplicate accepted outputs;
zero certificates from unqualified critics; zero LLM overrides of deterministic hard-QC
failures; every pixel change creates a new immutable revision and repeats full QA; every
development patch arrives as one complete validated adoption bundle; pod replacement loses no
accepted artifacts or durable queue truth; the repository is clean-at-seal every session; and
every session records real product progress per section 3.

## 7. IMMEDIATE CONTINUATION (ORDERED)

1. Read the four documents in section 0; reconcile live state; refresh tracker.
2. Run the ONE-TIME hygiene seal wave (section 2) as a single bounded wave: fsck, seal the main
   root by category, gitignore-with-allowlist, archive C:\w, register the workspace convention.
   Then hygiene drops to cadence-maintenance permanently.
3. Commit the external review into Plan\Reviews; record Amendments 1–3 in DECISIONS_LOG;
   create/refresh tracker items for the review's P0/P1 recommendations.
4. Build critic protocol v3 and rerun the six-model field against the existing 30-control board
   (section 6.6a) — first product wave, before any new hardware.
5. In parallel, run the 66-label control sweep (6.6b): planner -> candidates -> one-pass panel
   render -> per-record screening -> sealed admissions, plus the seeded-defect operator library.
6. Stand up the two-stage Wilson boards (6.6c); run the conditional burst tournament (6.6d)
   only on a measured v3 capability gap.
7. Wire the second provider family (BiRefNet or SAM2Matting, both live-verified) into the shard
   pipeline BEFORE any shard past 0001 runs, so tournament/disagreement evidence exists.
8. Pre-render label-aware panels for all 641 quarantined legacy packages during idle GPU time;
   stage the MF-P4-12.10 golden-record mission manifest NOW so qualification day ends with the
   first autonomous_certified_gold in existence.
9. Build the pod watchdog, mission steward, persistent critic server, mission_status.json, and
   milestone review bundle (sections 4, 6.5, 6.9) so corpus-scale missions run hands-off.
10. Replace any remaining per-record SAM3.1 reload paths with the tested resident/persistent
    predictor path; prove with a bounded canary before scaling.
11. On qualification day: golden record end-to-end -> shard 0001 terminalization -> 1,000-record
    milestone -> eligible corpus-scale missions -> 641-package bulk semantic requalification.
12. Maintain the git cadence (section 2) and the product-first rule (section 3) throughout;
    seal every session per the playbook with a clean tree and pushed branch.

## 8. AUTHORITY AND TRUTH CONSTRAINTS

Do not claim or imply any of the following until exact evidence satisfies its full governing
acceptance contract: strict visual QA pass; qualified visual role; independent juror authority;
operational certification; autonomous certified gold; training truth; completed shard;
completed 1,000-record milestone; production champion promotion; end-to-end completion.

Reference-only, synthetic, generated, or CivitAI source images are not pixel truth merely
because a generated mask passes deterministic QA. Amendment 1 changes only the visual verdict
semantics; it does not weaken deterministic hard blocks, the zero serious-false-pass tolerance,
independence requirements, or fail-closed abstention. Keep the live tracker truthful after
every governed state change. Record exact commands, paths, hashes, counts, failure
classifications, abstentions, and authority limits. Never weaken QA thresholds, visual-role
requirements, independence requirements, or evidence contracts to force progress — and never
substitute hygiene, bookkeeping, or re-auditing for product progress to appear busy.

## 9. REAL-DATA-FIRST LEARNING OBJECTIVE (BINDING PRIORITY)

Use the 81,910-record governed adult-corpus intake, qualified MaskedWarehouse assets, and the
approximately 83,422-image F:\Reference_Images library as the primary route to first-generation
and iteratively improved masking accuracy before beginning large-scale DAZ production.

Complete the learning cycle: qualified real polygon supervision -> hierarchical
person/ownership/coarse/fine/boundary training -> leakage-safe reference-domain self-supervised
pretraining -> SAM 3.1-first and independent-provider proposal expansion -> deterministic hard
QA -> qualified primary critic and independent-family juror -> bounded segmentation-provider
repair -> exact per-record authority evaluation -> weighted teacher-student retraining ->
disagreement and hard-case mining -> immutable residual coverage-gap analysis -> targeted DAZ
generation and real-holdout ablation only for demonstrated remaining gaps.

The internal architecture uses specialized routes for person discovery, instance ownership,
silhouettes, coarse regions, fine anatomy, hands and feet, thin structures, facial features,
adult anatomy, clothing boundaries, multi-person contact, and boundary refinement while
producing one unified canonical ontology and released package. Preserve every source annotation
at its actual granularity: never manufacture fine pixel labels from coarse regions, boxes,
prompts, actions, scene metadata, or reference images. Reference imagery may contribute domain
representation, retrieval, difficult-case sampling, proposal generation, and pseudo-label
candidates, but receives no pixel authority without complete qualification.

Use dataset-family-balanced sampling, leakage-safe lineage groups, frozen holdouts, per-dataset
reliability measurements, and explicit training weights: current certified gold highest;
qualified external polygons medium; qualified machine-generated masks bounded lower; and
unqualified masks, boxes, prompts, detections, references, and metadata zero pixel-supervision
weight. The self-hosted text model owns planning, reconciliation, coverage analysis, failure
clustering, batch selection, and bounded repair hypotheses. Qualified visual models inspect
exact per-record evidence and diagnose defects. Segmentation/refinement providers alone may
change pixels. The deterministic certificate service alone may issue authority.

Add temporal video masking after the still-image foundation is strong, including keyframes,
bidirectional propagation, temporal consistency, ownership persistence, cut/re-entry handling,
and automatic uncertain-frame reselection; retain temporal-ready metadata (frame index /
source-video identity) on every record now so the still-image corpus is video-upgradeable
without re-ingestion. Keep audio limited to timing and contextual metadata; it is never
anatomical pixel truth. Defer DAZ scale until an immutable residual real-data gap report
identifies deficiencies such as rare angles, exact laterality, contact, cross-person occlusion,
severe foreshortening, extreme cropping, or underrepresented labels; retain DAZ training weight
only when matched real-only versus real-plus-DAZ experiments improve untouched real holdouts.

This learning objective does not by itself complete the pursuing goal. Training, critic
qualification, proposal expansion, autonomous qualification, temporal execution, champion
promotion, RunPod-scale operation, DAZ benefit, release, and end-to-end integration remain open
until proven by current live evidence.

## 10. DEFINITION OF COMPLETE

This pursuing goal is complete only when the RunPod-resident work cell — not repeated Codex
micro-supervision — has been implemented and evidence proves the complete mission lifecycle:

Signed mission admission -> durable queue and lease ownership -> detection and ownership ->
persistent segmentation execution -> deterministic hard QA -> qualified independent visual
review -> bounded repair -> complete revalidation -> immutable package -> deterministic
certificate decision -> checkpoint and crash recovery -> compact milestone reporting ->
corpus-scale execution,

and when isolated RunPod development missions produce complete tested adoption bundles while
Codex retains final authority, AND:

- the external deep review is committed into Plan\Reviews with Amendments 1–3 recorded in
  DECISIONS_LOG and implemented as immutable protocol/registry versions;
- a primary visual critic and independent-family juror hold current, unexpired role
  certificates earned on stage-2 (>= 100-case, Wilson-bound) frozen real-image boards;
- the one-time hygiene seal wave is done, the C:\w farm is archived, the branch reconciliation
  has landed, and the clean-at-seal git cadence has been sustained across sessions;
- every session in the record shows real product progress per section 3.

A passing SAM canary, one completed shard, one VLM smoke, static tests, a clean repo, a
well-groomed tracker, or an implemented controller without live corpus-scale proof does not
complete this goal. Housekeeping is never completion. Keep the goal active until live
end-to-end evidence proves every required core gate.

END OF PURSUING GOAL — REVISION 2026-07-23R
