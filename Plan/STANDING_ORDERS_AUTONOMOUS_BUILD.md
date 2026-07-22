# STANDING ORDERS — MaskFactory continuous autonomous build

**BINDING.** These standing orders govern this chat **and** every ongoing MaskFactory
autonomous-build session/agent in this repository. Re-read mid-flight. Side-chat
guidance does not auto-apply unless merged here. Prefer this file over chat-only memory.

**Canonical path:** `Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md`
**Pointers only elsewhere** (CLAUDE.md / AGENTS.md / `.cursor/rules/` / handoffs) — do not fork a second full copy that can drift.

**Related authorities (do not weaken these orders):**
- Live tracker: `Plan/Tracker/tracker.py`
- Governing plan: `maskfactory-full-completion_69d863cb.plan.md` + `Plan/` specs
- Docker ops: `Plan/DOCKER_RUNTIME_AND_SESSION_USE.md`

---

STANDING ORDERS — MaskFactory continuous autonomous build
(Session must obey these for the rest of this chat. Re-read mid-flight. Side-chat guidance does not auto-apply.)

MISSION
Build the real MaskFactory product end-to-end: masks, packages, autonomous certification/repair/abstain, live local runtime (Docker CVAT/Nuclio/Ollama), bridge contracts, and honest tracker truth. Maximize real product progress per hour. Do not optimize for looking busy.

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
- Tier 6 RUNPOD_SCALE_PASS: remote GPU execution is proven on persistent RunPod storage under a valid SharedRunPodCoordinator v2 capacity lease
- AUDIO: N/A for MaskFactory core — do not invent audio gates; Main-owned if bridge touches audio

Claim vocabulary ONLY: PLANNED, IN_PROGRESS, RECONSTRUCTED, STATIC_PASS, HARD_QA_PASS_BOUNDED, RUNTIME_PASS_BOUNDED, RUNTIME_BLOCKED, VISUAL_QA_PASS_BOUNDED, VISUAL_CRITIC_BLOCKED, PRODUCTION_EVIDENCE_PASS, RUNPOD_SCALE_PASS, AWAITING_MAIN, HOLD, BLOCKED, COMPLETE, AUDIO_QA_N_A_CORE.
Forbidden without matching evidence: “done/green/production-ready/fully working/visual QA pass/doctor green/gold”.

SELF-HOSTED LLM / OLLAMA (MUST USE WHEN VISUAL/VLM IN SCOPE)
- Endpoint: loopback only `http://127.0.0.1:11434` (live-probe; do not skip because of stale memory).
- Use for Tier 4 panel criticism (P-PART / P-IMAGE), `tools/smoke_ollama_vlm.py`, doctor `ollama_image`, governed `maskfactory vlmqa` paths — not as a substitute for HARD_QA.
- If Ollama down/wrong models: mark VISUAL_CRITIC_BLOCKED with exact evidence; continue HARD_QA + other lanes; repair Ollama/Docker yourself when in autonomous scope.
- Prefer governed Docker/Ollama models required by P0-05 / doctor registry over casual native leftovers. Determinism: temperature=0, seed=1337 where spec requires.
- Do not use cloud LLMs for MaskFactory VLM QA. Do not treat LLM chatter as certification.

DOCKER (FIRST-CLASS, AUTONOMOUS)
When engine is up: start/repair/smoke CVAT 2.24 (`localhost:8080`), Nuclio/`pth-sam2`, Ollama, GPU container proofs yourself — no permission asks.
Production CVAT = v2.24:8080 only (not cvat269:18080).
Fixture/FakeCvat/producer_partial ≠ live CVAT complete.
If Desktop truly down: host-only lanes continue; Docker items blocked with typed evidence.

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

REQUIRED REAL CORPORA (BINDING; DO NOT FORGET)
- `C:\Comfy_UI_Main\MaskedWarehouse` and its RunPod mirror `/workspace/assets/MaskedWarehouse` are required labeled-source inputs. Authority-qualified masks, points, silhouettes, and semantic annotations must feed their exact permitted training, calibration, seeded-defect, multi-person, and benchmark lanes; they must not remain inventory-only.
- `F:\Reference_Images`, especially `F:\Reference_Images\Ultimate_Masking_Reference_Images`, and its RunPod mirror `/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images` are required real-image retrieval, coverage, benchmark, and hard-case inputs.
- At session start and before remote corpus use, trust the latest hash-bound evidence only after
  `tools\verify_runpod_persistence.py` and `tools\verify_runpod_corpus_mirrors.py` pass for the
  current pod. Keep fresh local/remote sampled-file and database/manifest reconciliation items open
  until their exact verify clauses pass.
- Semantic visual-role qualification must use real source pixels and evidence-qualified valid masks. Synthetic shapes are contract/parser fixtures only and may not serve as positive semantic controls. Old draft, in-review, rejected, or visibly defective package masks may not serve as valid controls or gold.
- Preserve authority distinctions: external labeled reference, weighted pseudo-label, benchmark-only reference, human-anchor gold, autonomous-certified gold, draft, and rejected are different tiers. A folder name never promotes bytes.
- `C:\Comfy_UI_Main\MaskedWarehouse\Nude\_MASKFACTORY_INTAKE` is the durable adult-corpus memory. Adopt its recorded lineage before any rebuild; operate its role-separated 256-record shards continuously, checkpoint every shard, report every 1,000 records, and quarantine/abstain individual failures without stopping unrelated records. Use `Plan\26` and `Instructions\15`.
- The inactive ontology-v2 lane must include the complete visible adult anatomy contract and user aliases defined by doc 18, including anus and butt/breast/genital aliases. Adult/NSFW content is not itself an exclusion category; uniform provenance, rights, integrity, annotation-QA, split/leakage, authority, and applicable-use rules apply.

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
1) Live-probe Docker + Ollama + `maskfactory doctor` (snapshot only; do not stall).
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
- **Primary and independent juror:** use only the exact registry-selected models that pass doc 25's
  frozen positive-and-negative calibration and role thresholds.
- **Legacy stack:** `llava:13b`, `llama3.2-vision:11b`, and `qwen2.5vl:7b` remain
  `VISUAL_CRITIC_BLOCKED` under current zero-positive-pass/hallucination evidence; model presence or
  an older name-based role cannot authorize MVC promotion, CAA, or gold.
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

### Bulk semantic review is mandatory by default
- After a diagnostic sample exposes a corpus-level issue, process the eligible
  population in deterministic hash-bound batches rather than interrupting Kevin
  for one package at a time.
- Generate label-aware panels/contact sheets automatically; require the current
  promoted primary high-capability visual critic and an independent-family
  juror for every semantic pass.
- Accept exact label/pixel matches automatically. Relabel only into a new
  immutable package version when evidence is unambiguous; otherwise reject or
  abstain. Never rewrite a frozen package.
- One malformed or uncertain case becomes an exception row and cannot stop the
  rest of the batch. Report a compact summary and exceptions only. Human review
  is an optional exception route, never the default throughput dependency.
- `C:\Comfy_UI_Main\MaskedWarehouse`, `F:\Reference_Images`, and their exact
  RunPod mirrors must feed this bulk lane under their distinct authority rules.

Evidence must log: **model id, prompt hash, response, panel hashes**.

### GPU coordination (RunPod)

SharedRunPodCoordinator v2 is the exclusive cross-project admission authority
for the current 48 GB RunPod. Follow
`C:\Users\kevin\.codex\shared_runpod_coordinator\README.md`: request and
validate a lease before new GPU work, heartbeat it while the work runs, and
release it on completion or containment. Its fresh telemetry, qualified peak
reservations, and workload-compatibility rules supersede the former
single-workload assumption. `runs/gpu.lock` may serialize MaskFactory's own
critical sections, but it cannot block unrelated ComfyUI work.
`/workspace/tmp/gpu.lock` and mere foreign-process presence are not capacity
vetoes. CPU-only work never needs a lease. Never remove an active internal
lock, kill another project's process, steal a lease, or exceed a granted
reservation; use cooperative yield when capacity truly does not fit.

Serialize with hand/clothing tournament workers: run critic **bursts when VRAM free**, unload large VLMs after (`unload_after_burst`), do not OOM hand workers. Do not kill healthy hand tournament PIDs unless VRAM forces brief serialize — then resume.

### Proof vocabulary
Use `VISUAL_QA_PASS_BOUNDED` / `VISUAL_HARD_QA_PASS_BOUNDED` / `STRICT_VISUAL_QA_PASS_BOUNDED` only with panel+STRICT-VLM evidence. Use `VISUAL_CRITIC_BLOCKED` when the critic cannot run. Forbidden: blind “approved”, doctor-green inflation, gold claims without admission certificate + STRICT visual coverage.

### Procedures
See `Plan/Instructions/13_SELF_HOSTED_STRICT_VLM_GATE.md` and updates in `00_START_HERE`, `02`, `03`, `08`.

---

## Agent bootstrap (every new session)

1. Read **this entire file** (including **CONTINUOUS UNTIL E2E COMPLETE (NO STOP)** and **SELF-HOSTED STRICT VLM GATE**).
2. Live-probe Docker + Ollama per `Plan/DOCKER_RUNTIME_AND_SESSION_USE.md` (and RunPod notes if on pod).
3. `cd Plan/Tracker` → `python tracker.py report` + `python tracker.py next -n 10`.
4. Execute the continuous loop — no Kevin permission asks; **do not stop** until E2E complete; stop only for true `NEEDS KEVIN`, then switch to all other unblocked lanes. Ensure durable `nohup` pod/host jobs so agent death ≠ climb death.
