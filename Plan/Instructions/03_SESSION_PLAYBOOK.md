# 03 — Session Playbook

This is the procedure you run every session, start to finish. A "session"
is however much continuous work you do in one sitting — it might cover one
item or a whole cluster; it ends whenever you're stopping, whether that's
because the work is done or because context/time is running out.

---

## 1. Start-of-Session Checklist

1. `cd C:\Comfy_UI_Main_Masking\Plan\Tracker` then `python tracker.py report`
   — always regenerate first; never trust a `DASHBOARD.md` that might be
   from a previous session without refreshing it.
2. Read `DASHBOARD.md`: **Required Core Status** first, then core blockers
   and Suggested Next Actions. The portfolio percentage and optional/
   portfolio blockers include independent-accuracy and scale/DAZ work and
   cannot redefine core completion.
3. **RunPod production awareness (mandatory for production work).** Verify the
   current pod, persistent-volume paths, corpus mirrors, and shared coordinator.
   Re-read `Plan\DOCKER_RUNTIME_AND_SESSION_USE.md` and probe Docker Desktop
   (`docker info`, `docker ps`, CVAT `localhost:8080/api/server/about`,
   Ollama `127.0.0.1:11434/api/version`, `wsl -l -v`) before any
   only before an explicitly selected local CVAT/Nuclio/Ollama integration item. Do not trust a prior chat memory
   that Docker was off. When the engine is up, start/repair/smoke services
   yourself (`python tools/bootstrap_cvat.py`, smokes, `maskfactory doctor`)
   for every in-scope need — do not wait for Kevin to operate containers.
   Never treat local doctor-green as production progress or authority.
4. **Proof-tier honesty.** Before marking bridge/core items complete, re-read
   `02` §11. P6-11/12 producer fixture work is `STATIC_PASS` +
   `AWAITING_MAIN` until real Main adoption/runtime evidence exists. Record
   tracker notes only through `tracker.py` using that vocabulary.
5. If any item was left `in_progress` from a previous session, run
   `python tracker.py show <id>` and read its `notes` — the last note
   should tell you exactly what was done and what's left. If it doesn't
   (an older session didn't leave a clean handoff), reconstruct state by
   checking what actually exists on disk before assuming anything.
6. Before starting work in a phase you haven't touched yet, confirm its
   entry gate is actually satisfied (see `DASHBOARD.md`'s Entry Gate column
   and `07_PHASE_QUICK_REFERENCE.md`) — e.g. don't start P5 training items
   before `metrics.certified_training_package_count >= 200` for the training
   profile. Do not apply that rule to doc-24 P6-07..12: the core autonomy/
   bridge lane intentionally has no D6, human, volume, full-library, DAZ, or
   soak prerequisite.
7. If the session will touch the MaskFactory↔ComfyUI bridge, release,
   adoption, schema mapping, invalidation, or either preserved worktree, read
   `09_CROSS_PROJECT_BRIDGE_RELEASE_AND_SESSION_HANDOFF.md`, verify both pinned
   task IDs, verify the current packet against
   `10_AUTONOMOUS_CORE_BRIDGE_PLANNING_PRESERVATION_MANIFEST.json`, and inspect
   the latest durable producer/Main handoff before any cleanup, rebase,
   replacement, or runtime use.
8. Decide the scope for this session: usually a full item cluster (e.g. all
   of `MF-P2-05.*`) rather than a single isolated item, since items within a
   cluster are almost always one coherent implementation task split into
   checkable sub-steps (see `04` §3).
9. **STRICT VLM gate awareness (when visual/MVC/CAA/gold/champion in scope).**
   Re-read Standing Orders § SELF-HOSTED STRICT VLM GATE and
   `13_SELF_HOSTED_STRICT_VLM_GATE.md`. Confirm the RunPod private endpoint plus
   the evidence-qualified primary and independent-family juror from doc 25. Do not promote MVC/CAA
   without panel+STRICT-VLM evidence. On RunPod, serialize with hand climb
   VRAM; unload VLMs after critic bursts. NEVER EC2; no cloud VLM for MF QA.
10. **NO-STOP orientation.** Re-read Standing Orders § CONTINUOUS UNTIL E2E
    COMPLETE (NO STOP) and `02` §13. This session does **not** end with idle
    wait for Kevin. Plan the continuous chain: after each wave, immediate next
    highest-value unblocked work until E2E complete (or only true NEEDS KEVIN
    remain while other lanes still run). Ensure durable `nohup` for long climbs.
11. **Bulk-first visual throughput.** When a diagnostic package reveals a
    population-level semantic or pixel issue, follow Instruction 14 §1.1 and
    MF-P4-11.26: batch the entire eligible population, generate contact sheets,
    run the promoted primary plus independent-family juror, and return only a
    compact summary/exceptions. Do not turn one-at-a-time review into the normal
    operating loop or make human review the default dependency.

## 2. The Main Work Loop

Repeat for each item or cluster — **never idle between iterations**:

1. **Pick the work.** Either the next cluster in the current phase's Items
   file (document order generally follows dependency order — see doc 14 §9
   critical path), or `python tracker.py next -n 10`. While core is open,
   this defaults to core-first prioritization. Use `--profile <id>` to work
   one claim scope explicitly and `--phase <P>` only when intentionally
   narrowing it.
2. **Read the full spec section** named in the cluster header's
   `(spec: ...)` — not just the item's compressed description. Confirm the
   exact reference by looking at the actual `Plan\Items\0X_....md` file or
   `tracker.py show <id>`, not from memory of a paraphrase.
3. **Check flags.** Is it `hard_blocker`? Extra rigor, no shortcuts (see
   `02` §4). Is it `conditional`? Its trigger might genuinely not apply yet
   — confirm before treating it as blocking.
4. **Implement.** Write the code/config, run the command, download the
   model, author the doc — whatever the item actually calls for — using
   your available tools.
5. **Verify.** Actually run whatever check makes the item's own verify
   clause true. Don't infer that it would pass; observe that it did.
6. **Record.** `python tracker.py set <id> --status ... --evidence "..."`
   (or `--note` for an in-flight update, or `--blocked-reason` if stuck —
   see `05` for the exact command shapes and `06` for what to do when
   stuck).
7. **Log if warranted.** A `doctor` run, a benchmark, a restore drill, or
   any other result explicitly called for in an item description
   ("record in `Plan\OPS_LOG.md`") gets an entry there in the format shown
   in that file's template. Any deliberate deviation from the spec gets an
   entry in `Plan\DECISIONS_LOG.md`.
8. **Periodically regenerate.** Run `python tracker.py report` after
   finishing a cluster (not necessarily after every single item — batching
   is fine) so `DASHBOARD.md` and `phases\*.md` stay reasonably fresh.
9. **IMMEDIATELY chain the next wave.** Do not wait for Kevin chat, do not
   declare “no further action,” do not park after a seal while unblocked
   work remains. If a subagent or background job is still running, start the
   next independent unblocked lane in parallel (or babysit with productive
   adjacent work) — never idle solely waiting for notifications.
10. **Durable continuation.** Long RunPod/host climbs must run under `nohup`
    (or equivalent). If this Cursor agent is about to die (usage limit,
    context, crash): leave tracker handoff notes, confirm nohup jobs alive,
    and treat relaunch of a new agent as mandatory — agent death ≠ climb death.

## 3. Updating Metrics and Goals As You Go

- Package-volume metrics belong to training/scale or independent-accuracy
  profiles; they do not change core status. When a package genuinely reaches a truth tier, update that tier's count immediately. Use
  `human_anchor_train_count`, `human_anchor_calibration_count`, `human_anchor_holdout_count`,
  `autonomous_certified_gold_count`, or `weighted_pseudo_label_count` as applicable. The tracker
  derives `certified_training_package_count` from the training-anchor and autonomous-certified
  counts; pseudo-label and holdout/calibration counts never satisfy P5 or D5.
- Whenever you complete an actual measurement the spec calls a "Goal"
  against (mean IoU on a holdout, minutes-per-image timing, a boundary
  F-score run), record it: `python tracker.py goal G<n> --measured "..."
  --status {pending,met,not_met}`. Don't wait until the very end of the
  project to backfill these — record them as each measurement actually
  happens.

## 4. End-of-Session Checklist (handoff only — NOT a project stop)

A “session end” is a **continuity handoff**, never a permission to idle the
project. MaskFactory continues until E2E complete (Standing Orders § CONTINUOUS
UNTIL E2E COMPLETE (NO STOP)).

1. `python tracker.py report` — always, even if you already ran it
   mid-session; make sure the very last thing reflects the very latest
   state.
2. `python tracker.py validate` — confirm no missing-evidence or
   missing-blocked-reason drift crept in, and that the item count still
   matches expectations (827, unless `Plan\Items\*.md` was deliberately
   edited and rebuilt).
3. If you're stopping mid-item, leave a clean handoff:
   `python tracker.py set <id> --status in_progress --percent <N> --note
   "handoff: <exactly what's done, what's left, and any gotcha the next
   session needs to know>"`. Assume the next session has zero memory of
   this one.
4. Confirm durable `nohup` (or equivalent) jobs are alive on pod/host for any
   in-flight climb. If this agent is dying: relaunch / ensure the next agent
   starts immediately — do not treat usage-limit as project pause.
5. If a git repository exists yet (from `MF-P0-08.01` onward), commit and
   push whatever changed this session **only when Kevin/session policy
   already requires it** — never invent a stop to wait for commit approval.
   Once DVC is initialized (`MF-P1-07.09` onward), `dvc push` anything
   DVC-tracked that changed (dataset builds, model checkpoints).
6. Check whether any named completion profile changed. Only
   `core_autonomous_runtime` is the required finish line; preserve optional
   profile status honestly. If a phase exit changed, also review its
   profile scope before treating it as a dependency.
7. If bridge state changed, update the durable handoff using instruction 09's
   closed status/message template, send the same commit/PR/release/adoption or
   invalidation identities to both pinned tasks, and retain both isolated
   worktrees until the receiving tasks acknowledge them. A message without
   verifiable artifact hashes is a preservation signal, not adoption authority.
8. **Chain continuity:** the last act of a dying session is naming the next
   highest-value unblocked wave for the relaunched agent — not “awaiting Kevin.”

## 5. Never-Idle Chaining Procedure (full)

Use this whenever a wave finishes, a seal lands, a subagent returns, or you
are tempted to stop:

| Step | Action |
|------|--------|
| A | Write tracker evidence / OPS_LOG for the wave just finished |
| B | `python tracker.py next -n 10` (+ hard-blockers for core profile) |
| C | Pick highest-value **unblocked** climb (prefer HARD_QA/RUNTIME/VISUAL/product over housekeeping) |
| D | If current lane is `NEEDS KEVIN`, switch to **all other** unblocked lanes |
| E | Launch/continue durable pod jobs with `nohup` before relying on Cursor foreground |
| F | Start the next wave **immediately** — no Kevin chat wait, no “parked,” no “no further action” |
| G | Repeat until E2E complete; only true NEEDS KEVIN items may sit blocked, and never alone if other lanes are open |

Forbidden stop phrases (examples): “no further action,” “waiting for Kevin,”
“parked after seal,” “will resume when notified,” “usage limit — project paused.”
Required replacement: durable handoff + next wave + agent relaunch if needed.
