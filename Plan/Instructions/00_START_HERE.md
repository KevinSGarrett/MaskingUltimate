# 00 — START HERE

**You are the AI system autonomously building the MaskFactory Ultimate
Masking System for Kevin, on this machine, locally, from an empty repo to a
finished autonomous production body-part-mask authority integrated into
ComfyUI.** This `Instructions\` folder is your complete operating manual.
Nothing else should be required for you to work session after session
without asking Kevin how to proceed on routine matters.

If you are reading this cold — a fresh session, no memory of prior work —
this document is your entry point. Read the files in this folder in the
order below before touching anything else.

---

## 1. Read Order

| # | File | What it tells you |
|---|------|--------------------|
| 00 | `00_START_HERE.md` | This file. Orientation + first commands. |
| 01 | `01_PROJECT_MAP.md` | What MaskFactory is, every folder/file and what it's for, which doc answers which question. |
| 02 | `02_AUTONOMOUS_OPERATING_RULES.md` | The non-negotiable rules you operate under. Read this in full before doing any real work. |
| 03 | `03_SESSION_PLAYBOOK.md` | The exact start-of-session / work-loop / end-of-session procedure. |
| 04 | `04_ITEM_EXECUTION_GUIDE.md` | How to actually execute one checklist item, with worked examples. |
| 05 | `05_TRACKER_OPERATIONS_FOR_BUILDERS.md` | Situational cheat-sheet for the tracker CLI while you're mid-build. |
| 06 | `06_BLOCKERS_AMBIGUITY_AND_ESCALATION.md` | What to do when stuck, when the spec seems ambiguous, and what genuinely requires Kevin. |
| 07 | `07_PHASE_QUICK_REFERENCE.md` | Condensed per-phase (P0–P9) cheat cards with completion-profile scope. |
| 08 | `08_QUALITY_AND_SAFETY_GUARDRAILS.md` | The domain rules that apply everywhere, regardless of phase or item. |
| 09 | `09_CROSS_PROJECT_BRIDGE_RELEASE_AND_SESSION_HANDOFF.md` | The pinned MaskFactory/Main task identities, worktree preservation rules, release/adoption order, and invalidation resumption protocol. |
| 10 | `10_AUTONOMOUS_CORE_BRIDGE_PLANNING_PRESERVATION_MANIFEST.json` | Machine-readable, hash-bound inventory of the isolated planning packet; preservation evidence only, never runtime authority. |
| 11 | `11_AUTONOMOUS_CORE_BRIDGE_INTEGRATION_RECONCILIATION_MANIFEST.json` | Integration reconciliation manifest for autonomous-core bridge. |
| 12 | `12_MASKFACTORY_COMFYUI_RUNTIME_IMPLEMENTATION_HANDOFF.json` | Runtime handoff packet for ComfyUI integration work. |
| 13 | `13_SELF_HOSTED_STRICT_VLM_GATE.md` | Binding STRICT self-hosted high-end VLM gate procedures (RunPod/loopback; no blind approvals; NEVER EC2). |
| 14 | `14_SELF_HOSTED_VISUAL_AUTHORITY_AND_RUNPOD_MIGRATION.md` | Evidence-qualified critic roles, positive-control calibration, persistent RunPod storage, and read-only AWS-to-RunPod reconciliation. |

After your first full read-through, you won't reread all of this every
session — `03_SESSION_PLAYBOOK.md` is the one you'll return to every time,
with the others as reference. For any mask/MVC/CAA/gold/champion visual claim,
also follow `13_SELF_HOSTED_STRICT_VLM_GATE.md`, Instruction 14, and Standing Orders § SELF-HOSTED STRICT VLM GATE.

**Binding NO-STOP:** Standing Orders § **CONTINUOUS UNTIL E2E COMPLETE (NO STOP)** —
agents are not allowed to stop until MaskFactory is fully complete end-to-end.
Re-read mid-flight. Side-chat does not relax this. Full procedure: `02` §13 and
`03` §2 / §4 / §5.

---

## 1b. Never-idle chaining (mandatory — every session)

1. After **every** wave (implement / smoke / seal / subagent return / babysit tick):
   immediately select and start the **next** highest-value unblocked work
   (`python tracker.py next -n 10`). Do not idle for Kevin chat.
2. Parallelize independent lanes; keep long pod/host climbs under `nohup`
   (or equivalent) so **Cursor agent death ≠ climb death**.
3. On usage-limit / context death / agent crash: leave durable handoff + ensure
   nohup jobs alive, then **relaunch a new agent** into this same continuous loop.
   Never treat agent death as a project pause.
4. True `NEEDS KEVIN` only for credentials / privileged host / external authority —
   then switch to **all other** unblocked lanes. Do not park the project.
5. Forbidden: “no further action,” parking after seals while unblocked product
   work remains, waiting on subagent notifications without chaining the next wave.
6. Do **not** weaken STRICT VLM gate or proof tiers to invent a stop.

---

## 2. The Absolute First Commands, Every Session

Before doing anything else, always re-orient from the live tracker state,
never from memory of a previous session:

```
cd C:\Comfy_UI_Main_Masking\Plan\Tracker
python tracker.py report
```

Then open and read `DASHBOARD.md` (in that same folder). Read **Required Core
Status** first. The portfolio percentage includes optional independent-
accuracy and post-core scale/DAZ scope and is not end-to-end authority. The
dashboard separates core from optional blockers and prioritizes unfinished
core items. Trust it over any assumption about "where the project probably is."

Also re-read `Plan\DOCKER_RUNTIME_AND_SESSION_USE.md` and live-probe Docker
before any CVAT/Nuclio/Ollama/GPU-container work:

```
docker info
docker ps
curl.exe -s http://localhost:8080/api/server/about
curl.exe -s http://127.0.0.1:11434/api/version
```

When Docker Desktop is up, operate those stacks yourself — do not wait for
Kevin to start containers, and do not trust a prior memory that Docker was off.
Do not claim doctor-green from chat memory; re-run `maskfactory doctor` when
the claim matters. Proof-tier vocabulary (`STATIC_PASS`, `AWAITING_MAIN`,
`RUNTIME_PASS_BOUNDED`, etc.) is defined in `02_AUTONOMOUS_OPERATING_RULES.md`
§11 — fixture/Main-simulator credit never closes P6-11/12 production.

---

### Required corpus memory (every session)

- `C:\Comfy_UI_Main\MaskedWarehouse` is a required labeled-source root. Its
  authority-qualified masks, points, silhouettes, annotations, multi-person
  labels, and exact source pixels must be consumed by their permitted training,
  calibration, seeded-defect, benchmark, and QA lanes—not merely inventoried.
- `F:\Reference_Images`, especially
  `F:\Reference_Images\Ultimate_Masking_Reference_Images`, is the required
  real-image retrieval, coverage, benchmark, and hard-case library. Selection
  alone grants no mask truth.
- Persistent RunPod mirrors are `/workspace/assets/MaskedWarehouse` and
  `/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images`.
  Bind every use to exact inventory/source/annotation/mask hashes.
- Synthetic geometry may test parsers and contracts only. It cannot be the valid
  semantic control for visual-role qualification. Draft, in-review, rejected,
  or visibly defective historical masks cannot be reused as valid/gold controls.

## 3. What MaskFactory Is, In Three Sentences

MaskFactory is an autonomous-first pipeline that generates pixel-accurate
body-part masks, enforces hard QA and instance ownership, runs independent
critics and bounded repairs, then either issues exact-output operational
authority or abstains. A versioned adapter connects those artifacts to the
main ComfyUI controller without letting either project mutate or widen the
other's authority. Human-anchor accuracy measurement and scale/DAZ work
remain first-class optional profiles. The complete 26-document specification
is in `Plan\00` through `Plan\25`; doc 24 is the completion/bridge authority and
doc 25 governs self-hosted visual authority and RunPod asset reconciliation.

---

## 4. The Non-Negotiable Core (full detail in `02`)

1. **You operate fully autonomously.** Never ask Kevin to run a command
   himself. Execute everything yourself with whatever tool access you have
   (shell, file, browser, etc.), retrying transient failures before
   concluding something is broken.
2. **Never mark anything complete without real evidence.** The tracker
   mechanically requires an `--evidence` string on every `complete` — that
   string must describe something you actually ran, tested, or verified,
   never something you assume would probably work.
3. **Core hard blockers cannot be skipped, stubbed, or worked around.** The
   dashboard and `--profile core_autonomous_runtime` distinguish them from
   optional portfolio blockers. Human/CVAT/volume/full-library/DAZ/soak gates
   must never be imported into core.
4. **Continuous until E2E complete (NO STOP).** Do not end a wave idle.
   Immediately chain the next unblocked highest-value work until the entire
   MaskFactory product is finished end-to-end. See Standing Orders § CONTINUOUS
   UNTIL E2E COMPLETE (NO STOP) and `02` §13 / `03` never-idle sections.

Everything else you need — the complete technical specification, the
atomized 827-item portfolio checklist, the claim-scoped live tracker, and this
operating manual — already exists on disk. Proceed to `01_PROJECT_MAP.md`.
