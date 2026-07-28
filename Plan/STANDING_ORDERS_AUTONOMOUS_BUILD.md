# STANDING ORDERS — MaskFactory continuous autonomous build

**BINDING.** These standing orders govern this chat **and** every ongoing MaskFactory
autonomous-build session/agent in this repository. Re-read mid-flight. Side-chat
guidance does not auto-apply unless merged here. Prefer this file over chat-only memory.

**Durable semantic-review boundary.** Qualified labeled inputs come from
`C:\Comfy_UI_Main\MaskedWarehouse`, exact qualified MaskFactory packages, and
coverage/retrieval inputs from `F:\Reference_Images`. Run label-aware review in
deterministic bulk batches with a primary critic plus an independent-family juror.
Continue past malformed or uncertain cases, emit a compact exception report, and
keep human review as an optional exception path rather than the default throughput lane.

**Canonical path:** `Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md`
**Pointers only elsewhere** (CLAUDE.md / AGENTS.md / `.cursor/rules/` / handoffs) — do not fork a second full copy that can drift.

**Related authorities (do not weaken these orders):**
- Live tracker: `Plan/Tracker/tracker.py`
- Governing plan: `maskfactory-full-completion_69d863cb.plan.md` + `Plan/` specs
- Docker ops: `Plan/DOCKER_RUNTIME_AND_SESSION_USE.md`
- Current self-hosted autonomy track: `Plan/27_SELF_HOSTED_AUTONOMOUS_LLM_CONTINUOUS_OPERATIONS_SPEC.md`
- Current self-hosted operating instruction: `Plan/Instructions/16_SELF_HOSTED_AUTONOMOUS_LLM_CONTINUOUS_OPERATIONS.md`

## Current pursuing-goal priority — self-hosted continuous autonomy

The accepted bounded steward is foundation evidence, not completion of the
intended autonomous workforce. Prioritize `MF-P6-13` through `MF-P6-19` so the
system continuously selects tracker/DAG work, batches 25 engineering missions
or 100 compatible masks, performs bounded patch/test/repair and mask/QA work,
and emits one consolidated Codex decision packet instead of routine micro
handoffs.

The CPU supervisor is always-on; GPU work is atomic and immediately released.
Every local RunPod GPU command uses `tools/run_with_shared_pod_gpu_lease.py`.
If local admission is unavailable, use broker-only Serverless, governed
Qwen-first OpenRouter advisory, or CPU-safe work as specified by Plan 27.
Never dual-submit, directly call providers/endpoints, preempt foreign work, or
let text-only reasoning approve a mask.

Until the real 25-mission campaign, governed 100-mask campaign, interruption
and routing drills, and three consecutive target-meeting campaigns pass,
report `SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE`.

### Self-hosted autonomy last-mile gate

`MF-P6-19.01` (the real 25-mission campaign) and `MF-P6-19.02`
(interruption/all-route recovery) have accepted terminal evidence and must not
be repeated. Satisfy the dependency-ready prerequisites for `MF-P6-19.03`, run
its one governed 100-mask campaign with exact outcome/visual/QA/promotion
accounting, then run the three consecutive mixed campaigns and final immutable
operating packet required by `MF-P6-19.04`. Serverless and OpenRouter remain
reconciled child routes of those parent campaigns, never detached evidence
factories.

When Pod-local admission is unavailable, capacity is proven only by material,
source-and-parent-bound child work on the verified execution host and terminal
reconciliation; historical jobs, idle ledgers, and micro-handoffs do not
qualify. No runtime item advances on static fixtures alone. Report fixtures as
`STATIC_PASS_CONTROL_PLANE_ONLY`. Do not create successor packets without a
material immutable-contract change or replacement clones/worktrees to evade
checkout reconciliation. Acceptance counts real model requests, accepted
artifacts, terminal reconciliation, and release—not commit, test, schema,
manifest, or receipt volume.

---

STANDING ORDERS — MaskFactory continuous autonomous build
(Session must obey these for the rest of this chat. Re-read mid-flight. Side-chat guidance does not auto-apply.)

MISSION
Build the real MaskFactory product end-to-end: masks, packages, autonomous certification/repair/abstain, persistent RunPod execution, bridge contracts, and honest tracker truth. Local Docker/CVAT/Nuclio/Ollama is optional diagnostic integration and may be operated only when Kevin explicitly requests that exact local action in the current turn. Maximize real product progress per hour. Do not optimize for looking busy.

AUTHORITY
- Live tracker = status authority (`Plan/Tracker/tracker.py`), not plan prose, checkboxes, or memory.
- Governing plan: `maskfactory-full-completion_69d863cb.plan.md` + `Plan/` specs.
- Docker/Ollama ops: `Plan/DOCKER_RUNTIME_AND_SESSION_USE.md` (live-probe; never trust “Docker was off” memory).
- Human review / CVAT correction / human anchors are NOT certification authority and NOT operational blockers for core autonomy. Default is auto-certify / auto-repair / abstain-reject with typed evidence.

AUTONOMY (NO HUMAN IN THE LOOP FOR ROUTINE WORK)
- Do not ask Kevin for permission, confirmation, “should I proceed?”, or turn-by-turn approval on in-scope work.
- Do not pause between sub-steps, subagent returns, pytest, doctor, smoke, or tracker updates. Chain the next wave immediately.
- Milestone-batched reporting only (cluster/wave), not per-task chatter.
- Stop ONLY for true NEEDS KEVIN: credentials/terms acceptance, privileged host actions Kevin alone can do, external-repo actions requiring Kevin authority, unavailable governed source approvals. Prefix tracker `blocked_reason` with `NEEDS KEVIN: …`.
- Everything else: execute yourself (shell, files, Docker, Ollama, browser, tests). If blocked technically, leave typed evidence and switch lanes — do not idle waiting for chat.

ANTI-LOOP / ANTI-HOUSEKEEPING (HARD)
Forbidden as primary work unless a tracker verify clause explicitly requires it AND product work is blocked without it:
- Endless plan/doc rewriting, dashboard cosmetics, “hygiene” refactors, re-litigating already-decided specs
- Re-running the same STATIC pytest/schema wave and calling it progress
- Re-probing Docker/doctor every few minutes without a new claim
- Polishing fixtures/FakeCvat while a live HARD_QA/RUNTIME/VISUAL climb is available
- Reopening completed items from stale prose
- Waiting on human/CVAT gold when autonomous evidence hierarchy applies
- Inventing new process docs instead of climbing proof tiers on real items

Anti-spin rule: if the same failure class repeats 2× without a new root cause + fix, classify defect vs environment, record honest `failed`/`blocked`/`RUNTIME_BLOCKED`/`VISUAL_CRITIC_BLOCKED`, switch to an unblocked parallel lane, continue.

REAL WORK SELECTION (EVERY WAVE)
1) `python tracker.py report` + `python tracker.py next -n 10` (from `Plan/Tracker/`)
2) Prefer items that advance: live packages, HARD_QA (QC-001…), doctor/smoke, panels + Ollama VLM, MaskedWarehouse admission, Mode A/B, release/bridge evidence — over pure schema/fixture work when those are ready.
3) Parallelize independent lanes; serialize only tracker integration, release claims, and bridge authority transitions.
4) Keep STATIC work on RUNTIME_BLOCKED / AWAITING_MAIN items while climbing HARD_QA/RUNTIME/VISUAL on every ready item.
5) Never invent Main adoption; leave `awaiting_main` until real Main artifacts exist.

MANDATORY PROOF LADDER (LOCAL-FIRST)
Declare target tier before edits. Never report a lower tier as a higher tier.
- Tier 0 RECONSTRUCTED: branch/HEAD/dirty ownership; item+blockers; live Docker/CVAT/Ollama probe; prior highest tier
- Tier 1 STATIC_PASS: schemas fail-closed; focused pytest; ruff; tracker deps; evidence paths/hashes
- Tier 2 HARD_QA_PASS_BOUNDED: real QC battery / seeded defects when masks/packages/certification in scope (pytest JSON shape ≠ HARD_QA)
- Tier 3 RUNTIME_PASS_BOUNDED: live Docker preflight when in scope; doctor/provider smoke; real bounded package run; CVAT/SAM2/Ollama smokes when claimed
- Tier 4 VISUAL_QA_PASS_BOUNDED: render real panels (source/mask/overlay/contour/ownership); review pixels/paths; local VLM critic when Ollama up; panel+report hashes. Decoding a PNG ≠ visual QA. VLM never clears hard BLOCK or invents gold.
- Tier 5 PRODUCTION_EVIDENCE_PASS: verify clause satisfied; `tracker.py set … --evidence` with real commands/paths/hashes before `complete`
- Tier 6 EC2_DEFERRED until local tiers green for claimed scope
- AUDIO: N/A for MaskFactory core — do not invent audio gates; Main-owned if bridge touches audio

Claim vocabulary ONLY: PLANNED, IN_PROGRESS, RECONSTRUCTED, STATIC_PASS, HARD_QA_PASS_BOUNDED, RUNTIME_PASS_BOUNDED, RUNTIME_BLOCKED, VISUAL_QA_PASS_BOUNDED, VISUAL_CRITIC_BLOCKED, PRODUCTION_EVIDENCE_PASS, AWAITING_MAIN, HOLD, BLOCKED, COMPLETE, EC2_DEFERRED, AUDIO_QA_N_A_CORE.
Forbidden without matching evidence: “done/green/production-ready/fully working/visual QA pass/doctor green/gold”.

SELF-HOSTED VISION AUTHORITY (MUST USE WHEN VISUAL/VLM IN SCOPE)
- Production endpoint: private loopback service on the selected RunPod, bound to exact registry-selected model/runtime hashes. Local Ollama is optional diagnostic integration only.
- Use for Tier 4 panel criticism (P-PART / P-IMAGE) and governed VLM-QA paths—not as a substitute for HARD_QA.
- If the qualified endpoint/models are unavailable, mark `VISUAL_CRITIC_BLOCKED` with exact evidence and continue HARD_QA plus other lanes. Do not substitute unqualified local models.
- Model presence is not authority. Positive-and-negative calibration and role qualification are mandatory. Determinism: temperature=0, seed=1337 where the spec requires.
- Do not use cloud LLMs for MaskFactory VLM QA. Do not treat LLM chatter as certification.

LOCAL DOCKER / WSL / GPU (OPTIONAL, EXPLICIT REQUEST ONLY)
Do not probe, start, restart, repair, update, pull, build, or execute local
Docker Desktop, WSL, CVAT, Nuclio/SAM2, Ollama, or GPU work unless Kevin
explicitly requests that exact local operation in the current turn. Optional
local integration evidence cannot replace persistent RunPod production proof.
Fixture/FakeCvat/producer_partial still does not equal live runtime completion.

TRACKER HYGIENE (CONTINUOUS, NOT STALE)
- Edit `tracker.json` ONLY via `tracker.py` (never hand-patch).
- On start of item: `set … --status in_progress` with note of target proof tier.
- On verified progress: update percent/notes/metrics immediately — do not batch hours of real work into a late write.
- `complete` ONLY with real `--evidence` meeting the item’s acceptance tiers (not STATIC alone when verify demands more).
- Partial but honest: `partially_complete` / `blocked` / `failed` with measured evidence.
- After every governed wave/cluster: `validate` then `report` (refresh DASHBOARD/phase views). After deliberate `Plan/Items` edits: `rebuild`.
- OPS_LOG + DECISIONS_LOG + durable handoff when governed state changes. Commit only verified scoped MaskFactory paths; never absorb dirty `Comfy_UI_Main`.

DEFINITION OF DONE (PER ITEM)
An item is COMPLETE only when:
1) Spec section for that item was followed (spec_ref), not improvisation
2) All required proof tiers for its verify clause are green (or honest N/A/deferred recorded)
3) Evidence cites real commands, artifact paths, and hashes under qa/live_verification or OPS_LOG
4) Tracker set + validate + report reflect that state
5) No silent weakening of QC/thresholds to force a pass

ACCEPTANCE / QA BAR (PRODUCT)
- Hard QC BLOCK is absolute; VLM/human/bridge cannot override.
- MaskedWarehouse sources are not gold until inventory, provenance, identity/dedup, ontology remap, lineage, and independent cross-provider QA pass.
- Prefer climbing HARD_QA → RUNTIME → VISUAL on every mask-producing increment immediately after STATIC — do not defer “until later polish.”

CORRECTION LOOP
Fail → capture command/QC → classify defect vs env → fix owned scope → re-run failed tier + neighbor regression → evidence shows fail→fix→revalidate → only then raise claimed tier.

CONTINUOUS LOOP (NO IDLE)
Reconstruct → select unblocked highest-value item → declare target tier → implement → climb tiers now → tracker update → next item. Repeat until true completion gates or only NEEDS KEVIN remain.

---

## CONTINUOUS UNTIL E2E COMPLETE (NO STOP)

**Kevin mandate (IMPLEMENTED INTO RULES — binding):** Agents are **NOT allowed to stop**. Work continuously and autonomously without stopping until the **entire MaskFactory project is fully completed end-to-end**. Auto only (no grok/composer override). **NEVER EC2.** Re-read this section mid-flight. Side-chat guidance does **not** relax, pause, or weaken this rule.

### Forbidden (hard — treat as standing-order violations)
- Ending a wave with idle wait for Kevin chat, “awaiting instructions,” or turn-by-turn permission theater on in-scope work.
- Declaring “no further action,” “parked,” “done for now,” or equivalent while unblocked product work remains anywhere in the tracker.
- Parking after a seal/audit/wave while climbable HARD_QA / RUNTIME / VISUAL / package / bridge / Mode A/B / gold-path work is still open and unblocked.
- Waiting for subagent notifications, background job chatter, or Cursor UI events **without immediately chaining** the next highest-value unblocked wave in parallel.
- Treating usage-limit, context exhaustion, session death, agent crash, or chat end as a **project pause** without **immediately** ensuring durable continuation: `nohup` / systemd-equivalent long jobs on the pod (or host), durable handoff notes, and a **new agent / session relaunch** that resumes the continuous loop.
- Idling on a single `NEEDS KEVIN` lane when other unblocked lanes exist.

### Required (hard)
- After **every** wave completion (seal, tracker update, smoke, subagent return, babysit tick): **IMMEDIATELY** chain the next highest-value unblocked work (`tracker.py next`, parallel lanes when independent).
- Keep product climb **durable**: long RunPod/host jobs under `nohup` (or equivalent) so **Cursor agent death ≠ climb death**. Agent death must trigger relaunch + resume, not idle.
- Stop **only** for true `NEEDS KEVIN` (credentials/terms, privileged host actions only Kevin can perform, external-repo authority, unavailable governed source approvals). Even then: prefix `blocked_reason` with `NEEDS KEVIN: …`, leave typed evidence, and **switch to all other unblocked lanes** — do not idle the session.
- Milestone-batched reporting only; never pause the loop to wait for human acknowledgment of a status update.
- Do **not** weaken the STRICT VLM gate, proof tiers, NEVER-EC2, or tracker honesty to invent a stop condition.

### Never-idle chaining procedure (summary)
See `Plan/Instructions/00_START_HERE.md`, `02_AUTONOMOUS_OPERATING_RULES.md`, and `03_SESSION_PLAYBOOK.md` for the full procedure. Binding loop: reconstruct → select → climb → evidence → tracker → **immediate next wave** → repeat until E2E complete or only true `NEEDS KEVIN` remain (with other lanes still running).

FIRST ACTIONS NOW
1) Inspect CPU-safe project state and prior runtime evidence; do not probe or start local Docker, Ollama, WSL, or GPU services.
2) `tracker.py next` / hard-blockers for `core_autonomous_runtime`.
3) Pick the highest-value climbable wave (prefer RUNTIME/VISUAL/HARD_QA-ready over more STATIC-only).
4) Execute without waiting for Kevin — and do not stop until E2E complete.

---

## RUNPOD RUNTIME NOTES (established; do not contradict standing orders)

These facts supplement the standing orders for GPU/runtime climb when local VRAM is the ceiling. They do **not** weaken proof tiers, autonomy, tracker hygiene, Docker production rules on the Windows host, or the NEVER-EC2 rule.

1. **Runtime gold / VLM climb may use RunPod RTX 6000 Ada** when the local 8 GB GPU is the ceiling. **NEVER EC2** for that work (or any MaskFactory work).
2. **Authoritative catch-up archives on pod** (sealed via `paths.env`; do not treat as a separate product/dataset):
   - Ultimate reference library: `/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images` (from `F:\Reference_Images\Ultimate_Masking_Reference_Images`)
   - MaskedWarehouse: `/workspace/assets/MaskedWarehouse` (`MASKED_WAREHOUSE`; matches local inventory when sealed)
   - Always `source /workspace/paths.env` on the pod before path-dependent work.
3. **CVAT / Nuclio on current nested RunPod = `RUNTIME_BLOCKED_POD_CLASS` (no DinD).** Gold path does **not** hard-require CVAT when `sam2_1_large` is live. Seal/keep: `qa/live_verification/cvat_nuclio_runpod_deferred_pod_class.json`.
4. **Proof-tier vocabulary remains binding on RunPod too** — same Tier 0–6 ladder and claim vocabulary as above; no inflated “done/green/gold/doctor-green” claims without matching evidence.
5. Production CVAT **v2.24 on localhost:8080** remains the Windows/Docker Desktop production rule when that stack is in scope; pod-class DinD limits do not invent a second production CVAT authority.

---

## SELF-HOSTED STRICT VLM GATE (binding — 2026-07-21)

Kevin mandate: **self-hosted high-end LLM on RunPod (or local Ollama loopback) MUST perform STRICT visual review / QA / approval / adjustments / corrections for MaskFactory autonomy — no blind approvals.** Cloud LLMs are forbidden for MF VLM QA. **NEVER EC2.**

### Authority & endpoints
- Endpoint: `http://127.0.0.1:11434` only (pod or host loopback).
- Config: `configs/vlm.yaml` → `strict_visual_gate` (+ governance `may_author_masks=false`, `may_approve_gold=false`, `may_clear_blocks=false`).
- Code: `src/maskfactory/vlm/strict_gate.py`
- Tools: `tools/run_tournament_ollama_critic_router.py`, `tools/run_tournament_mvc_visual_hard_qa.py`, `tools/smoke_strict_vlm_gate.py`, admission via `tools/build_autonomous_gold_admission.py`
- Profile: `configs/autonomy_autonomous_gold_profile.yaml` → `require_strict_visual_gate_pass: true`

### Model policy (strict)
- **Primary (high-end):** `llava:13b` (preferred) or `llama3.2-vision:11b` (alternate).
- **Secondary / ensemble:** `qwen2.5vl:7b` — **must not** be the sole rubber-stamp critic for MVC promotion, CAA, or gold.
- Legacy `models.primary_vlm: qwen2.5vl:7b` remains the calibrated S11 production fingerprint until recalibrated; **autonomy STRICT gate ignores qwen-as-sole-primary.**
- Determinism: `temperature=0`, `seed=1337` (required).

### Rubric & fail-closed behavior
Structured JSON must score: anatomy, boundary, leakage, emptiness, label_consistency, overlay_contour_review. Any dimension **fail** ⇒ overall fail.
- VLM **FAIL / uncertain / low confidence / problems** → abstain / residual / repair queue — **never gold / CAA mint**.
- VLM **never** clears hard QC BLOCK.
- Ollama down, required models missing, invalid JSON, or `--skip-vlm` → **`VISUAL_CRITIC_BLOCKED`** (do not silently skip; do not promote).
- Panels required: **source + mask + overlay** (contour/heat encouraged). Decoding a PNG alone ≠ visual QA.

### Mandatory scopes
STRICT gate is mandatory before accepting / promoting when masks/panels exist for:
1. Tournament MVC emit acceptance / residual visual critic paths
2. CAA admission / `autonomous_certified_gold`
3. Package freeze / challenger train acceptance panels (when in scope)
4. Mode B / champion promotion visual smoke (when applicable)
5. Hand + clothing climbs in flight

Evidence must log: **model id, prompt hash, response, panel hashes**.

### GPU coordination (RunPod)
Serialize with hand/clothing tournament workers through the shared FIFO lease:
run critic **bursts only while MaskFactory owns the active lease**, unload large
VLMs after (`unload_after_burst`), and do not OOM hand workers. Never kill,
pause, or preempt ComfyUI or another session's process.

## RunPod execution

The shared Pod-resident FIFO lease is mandatory before every MaskFactory local
GPU launch. This standing order supersedes the retired direct-execution rule.

- Database:
  `/workspace/.maskfactory/shared_pod_coordination/shared_gpu_leases_v1.sqlite`
- Manager:
  `/workspace/.maskfactory/shared_pod_coordination/tools/manage_shared_pod_gpu_lease_v2.py`
- MaskFactory session:
  `019f91d1-ea20-7d81-83ff-03d393eaa1f5`
- Protected owner token:
  `/tmp/maskfactory-019f91d1-ea20-7d81-83ff-03d393eaa1f5-shared-gpu-owner.token`
  (mode `0600`; never place it under `/workspace`, print it, or commit it)
- Guarded launcher:
  `tools/run_with_shared_pod_gpu_lease.py`

The guarded launcher must enqueue the immutable job identity, acquire the active
lease, heartbeat for the complete child lifetime, and terminally release it.
Only the guarded launcher's own child may be terminated during its cleanup.
`runs/gpu.lock` remains an internal MaskFactory critical-section lock and cannot
replace the shared lease. A direct `python`, Ollama, CUDA, Torch, tournament,
training, visual-critic, or other GPU launch that bypasses the guarded launcher
is a standing-order violation.

If the lease is queued or denied, do not start the local child and do not treat
that as a stop condition. Preserve the FIFO request and immediately continue in
this order:

1. For an eligible GPU payload, use only the shared RunPod Serverless broker
   with MaskFactory's authorized session/profile: `decide`, then `reserve`, then
   `submit`, then `status`/`reconcile`. Never submit directly to an endpoint.
2. OpenRouter may run concurrently with Serverless, or alone when Serverless is
   unavailable, for bounded coding, architecture, QA reasoning, test analysis,
   documentation, and non-authoritative multimodal review under the shared
   `$10.00` UTC-day hard cap (`$9.50` admission ceiling). Prefer the least-cost
   capable Qwen model. It may not mint masks, clear HARD_QA, approve gold, or
   replace the binding self-hosted strict-VLM gate.
3. Continue the highest-value CPU-safe lane and retry the same queued lease
   identity without duplicating a local, Serverless, or OpenRouter job.

Serverless and OpenRouter do not acquire or retain the local GPU lease. Before
Serverless reservation, any lease held during local preflight must be
terminally released. Stale-lease recovery requires both owner-process-dead and
zero-matching-GPU-process evidence. Never infer either condition and never kill
another process.

### Proof vocabulary
Use `VISUAL_QA_PASS_BOUNDED` / `VISUAL_HARD_QA_PASS_BOUNDED` / `STRICT_VISUAL_QA_PASS_BOUNDED` only with panel+STRICT-VLM evidence. Use `VISUAL_CRITIC_BLOCKED` when the critic cannot run. Forbidden: blind “approved”, doctor-green inflation, gold claims without admission certificate + STRICT visual coverage.

### Procedures
See `Plan/Instructions/13_SELF_HOSTED_STRICT_VLM_GATE.md` and updates in `00_START_HERE`, `02`, `03`, `08`.

---

## Local storage and session hygiene

- The MaskFactory and ComfyUI main heartbeat automations are the only recurring
  project continuations. Do not create standalone cron-run Codex sessions.
- Run `tools/check_local_storage_guard.py` before every local worktree, clone,
  backup, or evidence allocation.
- Below the configured 50 GiB floor, new local worktrees/backups are forbidden.
  Below 75 GiB remains a warning and cleanup/recovery lane.
- Full-repository bundles are prohibited. Preserve unique dirty work with
  binary patches, selected untracked source/configuration, hashes, and remote
  commit proof.
- Large runtime artifacts belong on the authorized RunPod volume. Local
  storage keeps compact manifests/receipts; Google Drive is unclaimed until a
  live write/read/hash probe passes.
- The compact-manifest Drive probe passed on 2026-07-26 for
  `MaskFactory_Recovery_Manifests`; this does not authorize moving large
  runtime artifacts off the named RunPod volume.
- Never retire a dirty, process-owned, non-remote-contained, main-checkout, or
  unresolved reparse-point worktree. Never force-delete through a junction.

## Agent bootstrap (every new session)

1. Read **this entire file** (including **CONTINUOUS UNTIL E2E COMPLETE (NO STOP)** and **SELF-HOSTED STRICT VLM GATE**).
2. Read `Plan/DOCKER_RUNTIME_AND_SESSION_USE.md`; verify the selected RunPod,
   persistent-volume paths, and shared GPU lease authority. Do not probe or
   operate the local Docker/WSL/Ollama stack without Kevin's exact current-turn
   request.
3. `cd Plan/Tracker` → `python tracker.py report` + `python tracker.py next -n 10`.
4. Execute the continuous loop — no Kevin permission asks; **do not stop** until E2E complete; stop only for true `NEEDS KEVIN`, then switch to all other unblocked lanes. Ensure durable `nohup` pod/host jobs so agent death ≠ climb death.
