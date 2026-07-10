# 00 — START HERE

**You are the AI system autonomously building the MaskFactory Ultimate
Masking System for Kevin, on this machine, locally, from an empty repo to a
finished, trained, production body-part-mask factory integrated into
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
| 07 | `07_PHASE_QUICK_REFERENCE.md` | Condensed per-phase (P0–P7) cheat cards. |
| 08 | `08_QUALITY_AND_SAFETY_GUARDRAILS.md` | The domain rules that apply everywhere, regardless of phase or item. |

After your first full read-through, you won't reread all of this every
session — `03_SESSION_PLAYBOOK.md` is the one you'll return to every time,
with the others as reference.

---

## 2. The Absolute First Commands, Every Session

Before doing anything else, always re-orient from the live tracker state,
never from memory of a previous session:

```
cd C:\Comfy_UI_Main_Masking\Plan\Tracker
python tracker.py report
```

Then open and read `DASHBOARD.md` (in that same folder). It tells you,
right now: overall % complete, per-phase progress, which items are
currently blocked and why, which Definition-of-Done criteria are satisfied,
what the suggested next actions are. Trust this file over any assumption
about "where the project probably is."

---

## 3. What MaskFactory Is, In Three Sentences

MaskFactory is a production-grade, human-in-the-loop pipeline that produces
pixel-perfect binary PNG masks for every visible body part of a character
in an image — combining SAM2, human parsing, pose estimation, open-vocab
detection, a local VLM for QA, and CVAT for human review — then uses the
resulting gold-standard dataset to fine-tune its own custom segmentation
models, which are finally served back into ComfyUI. Every decision about
labels, formats, thresholds, models, and workflow was made in advance and
written down across 16 specification documents in `Plan\`; your job is to
execute that plan, not to redesign it. The full charter, goals, and scope
are in `Plan\01_PROJECT_CHARTER_AND_SCOPE.md` — read `01_PROJECT_MAP.md` in
this folder next for the complete map of where everything lives.

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
3. **The seven hard-blocker item clusters cannot be skipped, stubbed, or
   worked around**, no matter how much schedule pressure exists. They exist
   specifically to prevent silent, expensive-to-discover-later corruption
   of the dataset (left/right swaps, format drift, an untrustworthy VLM,
   model regression). See `02` and `Plan\Tracker\README.md` §5 for the list.

Everything else you need — the complete technical specification, the
atomized 326-item build checklist, the live status tracker, and this
operating manual — already exists on disk. Proceed to `01_PROJECT_MAP.md`.
