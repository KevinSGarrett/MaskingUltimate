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
3. If any item was left `in_progress` from a previous session, run
   `python tracker.py show <id>` and read its `notes` — the last note
   should tell you exactly what was done and what's left. If it doesn't
   (an older session didn't leave a clean handoff), reconstruct state by
   checking what actually exists on disk before assuming anything.
4. Before starting work in a phase you haven't touched yet, confirm its
   entry gate is actually satisfied (see `DASHBOARD.md`'s Entry Gate column
   and `07_PHASE_QUICK_REFERENCE.md`) — e.g. don't start P5 training items
   before `metrics.certified_training_package_count >= 200` for the training
   profile. Do not apply that rule to doc-24 P6-07..12: the core autonomy/
   bridge lane intentionally has no D6, human, volume, full-library, DAZ, or
   soak prerequisite.
5. If the session will touch the MaskFactory↔ComfyUI bridge, release,
   adoption, schema mapping, invalidation, or either preserved worktree, read
   `09_CROSS_PROJECT_BRIDGE_RELEASE_AND_SESSION_HANDOFF.md`, verify both pinned
   task IDs, verify the current packet against
   `10_AUTONOMOUS_CORE_BRIDGE_PLANNING_PRESERVATION_MANIFEST.json`, and inspect
   the latest durable producer/Main handoff before any cleanup, rebase,
   replacement, or runtime use.
6. Decide the scope for this session: usually a full item cluster (e.g. all
   of `MF-P2-05.*`) rather than a single isolated item, since items within a
   cluster are almost always one coherent implementation task split into
   checkable sub-steps (see `04` §3).

## 2. The Main Work Loop

Repeat for each item or cluster:

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

## 4. End-of-Session Checklist

1. `python tracker.py report` — always, even if you already ran it
   mid-session; make sure the very last thing reflects the very latest
   state.
2. `python tracker.py validate` — confirm no missing-evidence or
   missing-blocked-reason drift crept in, and that the item count still
   matches expectations (798, unless `Plan\Items\*.md` was deliberately
   edited and rebuilt).
3. If you're stopping mid-item, leave a clean handoff:
   `python tracker.py set <id> --status in_progress --percent <N> --note
   "handoff: <exactly what's done, what's left, and any gotcha the next
   session needs to know>"`. Assume the next session has zero memory of
   this one.
4. If a git repository exists yet (from `MF-P0-08.01` onward), commit and
   push whatever changed this session. Once DVC is initialized
   (`MF-P1-07.09` onward), `dvc push` anything DVC-tracked that changed
   (dataset builds, model checkpoints). This mirrors doc 14 §10's rule:
   every session ends with the relevant pushes, not just local commits.
5. Check whether any named completion profile changed. Only
   `core_autonomous_runtime` is the required finish line; preserve optional
   profile status honestly. If a phase exit changed, also review its
   profile scope before treating it as a dependency.
6. If bridge state changed, update the durable handoff using instruction 09's
   closed status/message template, send the same commit/PR/release/adoption or
   invalidation identities to both pinned tasks, and retain both isolated
   worktrees until the receiving tasks acknowledge them. A message without
   verifiable artifact hashes is a preservation signal, not adoption authority.
