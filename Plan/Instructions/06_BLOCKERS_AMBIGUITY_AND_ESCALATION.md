# 06 — Blockers, Ambiguity, and Escalation

What to do when you're stuck, when the spec seems ambiguous, and — the
most important part of this document — exactly which actions genuinely
require Kevin versus which are yours to handle autonomously.

---

## 1. Technical Blocker (Environment, Tooling, Dependency)

1. Check `Plan\15_RISKS_OPERATIONS_RUNBOOK.md` §7 first — it's an
   extensive troubleshooting table (sm_120 kernel errors, CVAT 502s, SAM2
   interactor stalls, Ollama OOM, DVC push failures, stale GPU locks, and
   more) built specifically for this project's known failure modes. Most
   technical blockers are already answered there.
2. If the runbook resolves it: fix it, verify the fix actually worked, and
   proceed — no need to log this as a blocker if it was transient and
   resolved within the session.
3. If it isn't resolved: mark the item `blocked` with a specific reason
   (what you tried, what the actual error was), move to a different
   actionable item so the session isn't idle, and revisit later or next
   session. Don't spin retrying the same fix indefinitely.

## 2. Spec Ambiguity

This should be rare — the blueprint's own stated design goal is zero open
questions. Before treating something as genuinely ambiguous:

1. Reread the **full** relevant spec section, not just the item line.
2. Check `Plan\00` §5 ("How To Use This Pack") and this folder's
   `01_PROJECT_MAP.md` quick-lookup table for a doc you might have missed.
3. Check whether a *different* doc resolves it — cross-references between
   the 16 docs are extensive (e.g. a formatting question in doc 03 might
   be pinned down further by a QC definition in doc 09).

If it's still genuinely unresolved after that:

- Pick the most **conservative, most spec-consistent** reading — the
  interpretation that best matches the project's stated philosophy
  elsewhere (never guess, visible-pixels-only, honest uncertainty states
  over invented precision, exclusivity by construction, etc. — see
  `08_QUALITY_AND_SAFETY_GUARDRAILS.md`).
- Log the gap and your reasoning in `Plan\DECISIONS_LOG.md` using its
  template, **before** proceeding.
- If you're genuinely confident the conservative reading is sound, proceed
  and mark the item complete with evidence that references the decisions
  log entry.
- If you're not confident, mark the item `blocked` with
  `--blocked-reason "NEEDS KEVIN: ambiguity — see DECISIONS_LOG entry
  <date/title>"` and move to other work.

## 3. Verification Genuinely Fails

Status is `failed`, not `blocked` — you attempted it and it didn't pass.
Record the actual measured result as evidence, identify the likely cause by
reference to the relevant spec section, and loop back to the earlier items
that would need to change for it to pass (more data, different
hyperparameters, a bug fix). Never narrow the eval set, weaken the
threshold, or reinterpret the metric to force a pass — see the worked
example in `04_ITEM_EXECUTION_GUIDE.md` §5.

## 4. What Only Kevin Can Do

| Action | Why it's Kevin's, not yours |
|---|---|
| **Supplying source images** for the dataset | Data governance (doc 01 §7) requires generated/owned/licensed/consented provenance — you cannot source this yourself. |
| **Doing the actual CVAT annotation/correction work** (the manual clicks in doc 11's SOPs) | Doc 11 is explicitly Kevin's operator manual — human judgment on mask correction is the point of that review layer. Build and automate everything around it (drafts, QA, panels, the CVAT bridge, the whole tooling stack) so his manual time is minimized, but don't attempt to replace his review judgment yourself, even if you technically have UI-automation tools that could click through CVAT. |
| **Approving second-review / IAA sign-off** | Same reasoning — this is the human-consistency check the pipeline is built around. |
| **Spending real money** (launching the optional AWS burst training instance, any other billable action) | The *decision* to use g6e.xlarge spot in the dev account is already made in the spec — but actually incurring a real-world cost is a distinct action that needs an explicit go-ahead from Kevin first, every time, even though the technical choice was pre-approved. |
| **Approving a scope change** (adding a v2-deferred label, enabling video/multi-person, anything doc 01 §5 lists as out-of-scope) | These were deliberately deferred; expanding scope is a project decision, not a build decision. |
| **Resolving a genuinely unresolved spec ambiguity** (after you've exhausted §2 above) | At that point it needs a human call, logged as such. |
| **Relaxing any data-governance or age-safety rule, for any reason** | Never — not even Kevin overrides this one; if he asks you to, that itself is a signal to hold the line and explain why, not comply. |

## 5. Everything Else Is Yours

Environment setup, writing and testing code, running the pipeline on
images Kevin has already supplied, downloading public model checkpoints,
building and running the automated QA/VLM layers, training models,
building the ComfyUI integration, writing documentation, and all tracker
bookkeeping — all of this you do autonomously, start to finish, without
checking in first. Report what you did through the tracker and logs; you
don't need Kevin's turn-by-turn approval to do it.
