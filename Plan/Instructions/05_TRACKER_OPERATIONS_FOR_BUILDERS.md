# 05 — Tracker Operations For Builders

`Tracker\README.md` is the formal command reference — read it once in full.
This document is a shorter, situational companion: **"I'm at this exact
moment in the build loop — what tracker command do I run right now?"**

All commands run from `C:\Comfy_UI_Main_Masking\Plan\Tracker\`.

---

## Situational Cheat-Sheet

| Situation | Command |
|---|---|
| Starting a session | `python tracker.py report` then read `DASHBOARD.md` |
| Deciding what to work on | `python tracker.py next -n 10 [--phase P#]` or `python tracker.py list --phase P# --status open` |
| About to start a specific item | `python tracker.py show <id>` — check for existing notes/evidence before assuming it's untouched |
| Finished and verified an item | `python tracker.py set <id> --status complete --evidence "<specific, real>"` |
| Hit a real technical wall | `python tracker.py set <id> --status blocked --blocked-reason "<specific>"` |
| Hit something only Kevin can resolve | `python tracker.py set <id> --status blocked --blocked-reason "NEEDS KEVIN: <specific>"` — see the convention note below |
| Made partial progress, ending session here | `python tracker.py set <id> --status in_progress --percent <N> --note "handoff: <exact state + next step>"` |
| Verification actually failed (not blocked, attempted and didn't pass) | `python tracker.py set <id> --status failed --evidence "<what was measured>"` |
| A conditional item's trigger never fired | `python tracker.py set <id> --status not_applicable --evidence "trigger not met: <why>"` |
| A new package reached `human_approved_gold` | `python tracker.py metrics --set approved_gold_count=<N>` — do this every time, not in a batch at phase-end |
| Just ran a leaderboard eval / timing measurement tied to a Goal | `python tracker.py goal G<n> --measured "<value>" --status {pending,met,not_met}` |
| Wondering if something is a hard blocker | `python tracker.py list --hard-blockers [--phase P#]` |
| Checking what's currently blocked, project-wide | `python tracker.py list --blocked`, or just read `DASHBOARD.md`'s "Currently Blocked Items" |
| Checking things needing Kevin specifically | `python tracker.py list --blocked --search "NEEDS KEVIN"` |
| Finished a cluster or a chunk of work | `python tracker.py report` |
| Before ending any session | `python tracker.py validate` then `python tracker.py report` |
| `Plan\Items\*.md` was deliberately edited | `python tracker.py rebuild` (safe — preserves all existing status/evidence/notes by id) |

---

## The `NEEDS KEVIN:` Convention

The tracker's `blocked_reason` field is free text — there's no separate
"needs human" flag in the schema. Use the literal prefix `NEEDS KEVIN:` at
the start of the reason string whenever an item is blocked on something
only Kevin can resolve (see `06_BLOCKERS_AMBIGUITY_AND_ESCALATION.md` for
what qualifies). This makes those items trivially searchable —
`tracker.py list --blocked --search "NEEDS KEVIN"` — separating "waiting on
Kevin" from ordinary technical blockers ("waiting on a flaky download") at
a glance, for both you and for Kevin himself when he checks in.

## Batching, Not Spamming

You don't need to call `report` after every single one of 326 items —
that's wasted work. Call it after finishing a cluster, or when you're about
to stop for the session, or when you specifically want to hand off a fresh
`DASHBOARD.md` for Kevin to glance at. Do call `set` for every item the
moment you've actually verified it, though — that write is cheap, and
letting real completions sit unrecorded for a long stretch is exactly the
kind of tracker/reality drift rule 5 in `02_AUTONOMOUS_OPERATING_RULES.md`
warns against.

## If a Tracker Command Errors

The CLI is deliberately strict at a few points (refuses `complete` without
evidence, refuses `blocked` without a reason, validates status values). If
a command errors, read the message — it's written to tell you exactly what
additional flag it needs. This is the tool enforcing rule 3
(`02_AUTONOMOUS_OPERATING_RULES.md`), not a bug to route around; supply
the missing, honest information rather than looking for a way past the
check.
