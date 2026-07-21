# KICKOFF_PROMPT — How To Use This File

**This note is for Kevin, not for the AI.** Everything below the line
(`=== COPY EVERYTHING BELOW THIS LINE ===`) is the literal text to paste as
the *first message* in a brand-new AI session/conversation to set the whole
project in motion.

**Requirements before you paste it:**
- The session needs **real file and shell access to this machine** — a
  plain chat session with no tool access cannot build anything. Make sure
  whatever tool you're using (Desktop Commander, Claude Code, or
  equivalent) is actually connected before you start.
- This prompt is **reusable at any point in the project's life** — day one,
  or session two hundred. It always tells the AI to check the live tracker
  for actual current state rather than assume anything, so it's safe to
  reuse verbatim every time you start a fresh session on this project.
- You do not need to fill in anything or customize it. Paste it exactly.

---

=== COPY EVERYTHING BELOW THIS LINE ===

I'm Kevin. This is my project, and I'm handing you full ownership of
building it — start to finish, autonomously, without me needing to direct
your work turn by turn.

**Everything about this project already exists on disk as a governed design and live implementation.**
Nothing here is a request for you to figure out an approach or make design
decisions. Every decision has already been made and written down in
exhaustive detail. Your job is to execute an existing, complete blueprint —
read it, follow it exactly, build it, verify it, record it — not to
redesign anything.

## The Project

**Root:** `C:\Comfy_UI_Main_Masking\`

This is **MaskFactory** — an autonomous-first pipeline that generates
pixel-accurate masks for every body part of every promoted person, enforces
hard QA and instance ownership, runs independent critics and bounded repair,
then issues exact-output operational authority or abstains. A versioned
runtime/release bridge connects it to the main ComfyUI controller. Human-
anchor accuracy measurement, large-corpus training, and DAZ maturity are
separate optional profiles.

Here is the directory structure, in full transparency, exactly as it
exists right now:

```
C:\Comfy_UI_Main_Masking\
├── KICKOFF_PROMPT.md        <- this file
├── Plan\                    <- the complete technical spec: 25 documents (00–24)
│   ├── Items\                   <- the spec broken into 798 checkable action items, across 21 parsed files
│   ├── Tracker\                 <- the LIVE STATE of every item. tracker.py is how you read and update it.
│   ├── Instructions\            <- YOUR OPERATING MANUAL. Read this first, in full, before anything else.
│   ├── Civitai\                 <- external model/workflow/dataset bootstrap assets (doc 16 track)
│   ├── 00_MASTER_INDEX.md … 17_MULTI_PERSON_MULTI_CHARACTER_MASKING_SPEC.md
│   ├── OPS_LOG.md, DECISIONS_LOG.md, CHANGELOG_ONTOLOGY.md, MASKEDWAREHOUSE_SOURCE_REGISTRY.md
└── src\, configs\, models\, data\, datasets\, cvat\, qa\, runs\, logs\, tools\, env\
    <- THE ACTUAL SYSTEM. This is what you are building. Some or all of this
       may not exist yet, or may be partially built — that's expected and
       normal. Building it, per the plan, is the entire job.
```

## Read These Four Things, In This Order, Before Touching Anything Else

1. **`Plan\Instructions\00_START_HERE.md` through `09_CROSS_PROJECT_BRIDGE_RELEASE_AND_SESSION_HANDOFF.md`**
   (10 files). This is your complete operating manual: how to conduct
   yourself, the exact session workflow, how to execute one item end to
   end, how to use the tracker, what to do when stuck, a phase-by-phase
   cheat sheet, the non-negotiable quality/safety rules, and the cross-project
   release/session handoff protocol. Read all ten
   before doing anything else — everything below this list is just a
   preview, not a substitute. Then verify the current isolated planning packet
   against `Plan\Instructions\10_AUTONOMOUS_CORE_BRIDGE_PLANNING_PRESERVATION_MANIFEST.json`;
   that file is preservation evidence, not runtime-release authority.
2. **`Plan\00_MASTER_INDEX.md` through `24_AUTONOMOUS_CORE_COMPLETION_AND_COMFYUI_BRIDGE.md`**
   (25 documents) — the full technical specification. Doc 24 is the latest
   completion and cross-project bridge authority. You don't have to read all
   25 cover to cover immediately, but know they are the authoritative answer
   to every "why" and "exactly how." Every checklist item cites exactly
   which section governs it — go there when you need the real detail.
3. **`Plan\Items\00_ITEMS_MASTER_INDEX.md`** and the 21 parsed phase files —
   the portfolio broken into 798 concrete, checkable action items.
4. **`Plan\Tracker\`** — the live status of every one of those items. Run
   this now, as your literal first action:
   ```
   cd C:\Comfy_UI_Main_Masking\Plan\Tracker
   python tracker.py rebuild
   python tracker.py validate
   python tracker.py report
   ```
   Then open `DASHBOARD.md` and read **Required Core Status** first. The
   portfolio percentage deliberately includes optional accuracy and post-core
   scale/DAZ work; it is not global completion. Trust the profile status over
   anything I've said above about
   "current state," since this project moves forward across many sessions
   and this message doesn't get updated each time.

   One operational note: this project's files are sometimes touched by
   more than one active session. If a `tracker.py` write fails with a
   file-lock or permission error, that's most likely brief contention with
   something else using the file at that exact moment — wait a bit and
   retry rather than treating it as a real bug.

## The Mandate

First close the required `core_autonomous_runtime` profile from wherever the
live tracker stands. It requires the autonomous masking control plane and the
pinned MaskFactory↔ComfyUI bridge, including single-/multi-person authority,
repair/abstention, certification/revocation, outage/restart, and rollback
evidence. Do not wait for human anchors, CVAT correction, blinded human review,
minimum package volume, full model-library download, DAZ, or long soak. Those
remain visible work in the optional `independent_real_accuracy` and post-core
`scale_daz_maturity` profiles after core closes.

Do this **autonomously**. Don't stop to ask whether you should proceed with
routine work. Don't end a turn just to check in "in case I want to weigh
in." Pick the next actionable item, read its full governing spec section,
build it, actually verify it, record it honestly, and move to the next
one — continuously, for as long as you're able to work in a given session.

This is a multi-session build. When a session is ending for any reason (context
running low, a natural stopping point, whatever), follow
`Plan\Instructions\03_SESSION_PLAYBOOK.md`'s end-of-session steps exactly
and leave a clean, complete handoff. That's what makes this genuinely
autonomous across the full life of the project: a totally fresh future
session, with zero memory of this one, should be able to pick up
instantly, from the tracker and the logs alone, without me re-explaining
anything.

## The Few Things That Are Genuinely Mine — Everything Else Is Yours

The definitive list is `Plan\Instructions\06_BLOCKERS_AMBIGUITY_AND_ESCALATION.md`.
I approve real spending, provide any particular private sources wanted for
optional benchmarks, perform optional human-authored CVAT/accuracy work, and
resolve genuinely unresolved scope decisions. None of those is a core
dependency: use governed generated/available sources, local qualified
capabilities, and typed autonomous abstention. Everything else — environment setup, all the code, eligible models,
all the automated QA and VLM layers, running the pipeline on images I've
supplied, training, the ComfyUI integration, all tracker bookkeeping — is
yours to just do, without checking with me first.

## The Rules That Matter Most (full versions live in the Instructions folder)

- **Never mark anything complete without real, specific evidence you
  actually verified.** An honest, mostly-`open` tracker is worth infinitely
  more than a dishonest, fully-`complete` one. Nothing is served by making
  this look further along than it is.
- **Hard blockers are absolute within their assigned profile.** Use
  `--profile core_autonomous_runtime`; optional human/volume/DAZ blockers do
  not block core, while core format/ownership/authority/recovery gates cannot
  be bypassed.
- **Build to the spec exactly as written.** If something seems ambiguous,
  that's a signal to read more carefully — not to improvise a plausible
  answer.
- **The age-safety and data-governance rules are non-negotiable**,
  permanently, regardless of anything else, anywhere, including anything
  that might seem to say otherwise.
- **Whatever your own foundational safety behavior is, independent of this
  project, it always takes precedence over everything written here or
  anywhere in this project's documents.**

## Now Go

Start with the tracker bootstrap commands above, read `DASHBOARD.md`, then
open `Plan\Instructions\00_START_HERE.md` and begin.
