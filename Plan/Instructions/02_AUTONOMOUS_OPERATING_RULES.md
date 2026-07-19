# 02 — Autonomous Operating Rules

These are the rules you operate under for the entire duration of this
project, across every phase and every session. They take precedence over
convenience, schedule pressure, and the appearance of progress. Read this
file in full before doing any real work, and revisit it whenever you're
tempted to cut a corner.

---

## 1. Full Autonomy

You execute this project yourself. Never ask Kevin to run a command,
install something, or perform a routine build step himself — you have
tool access (shell, file system, browser, whatever is available to you in
your environment); use it. Don't pause a build sequence to ask "should I
proceed?" for ordinary, in-scope work — proceed, using the judgment this
manual gives you, and report what you did afterward via the tracker and
logs rather than asking permission beforehand.

This does not mean reckless. It means: don't outsource routine execution to
Kevin, and don't wait for turn-by-turn approval on things the spec has
already decided. A small number of actions genuinely need Kevin — see
`06_BLOCKERS_AMBIGUITY_AND_ESCALATION.md` for the exact list. Everything
else is yours to execute.

**Docker Desktop is in that autonomous scope.** When the engine is up, you
start/repair/smoke CVAT, Nuclio/SAM2, Ollama, and GPU containers yourself
per `Plan\DOCKER_RUNTIME_AND_SESSION_USE.md`. Do not pause to ask whether
you may use Docker, and do not treat a stale “Docker was off” memory as
current state — live-probe first, then operate the stack for every in-scope
verify clause.

## 2. Spec Fidelity — Build To The Document, Not To Memory

Every checklist item carries a `spec_ref`. Before implementing anything,
read the **full relevant section** of the actual `Plan\` document — not
just the item's one-line compressed description, and not your own general
sense of how a system like this "usually" gets built. This blueprint made
hundreds of specific, deliberate decisions (exact checkpoints, exact
thresholds, exact algorithms, exact file layouts). A "reasonable"
substitute is still a spec violation if it isn't what's written, even when
it would also technically work — consistency across the whole system
depends on every piece matching the same decisions.

Doc 00 states plainly: "Every decision has been made. There are no open
questions." If you find yourself needing to invent something the spec
doesn't cover, that's a signal to look harder before it's a signal to
improvise — see `06` for what to do if a genuine gap turns up.

## 3. Evidence & Honesty Discipline — The Most Important Rule Here

**Never mark an item complete without having actually done and verified the
work.** The tracker's `set --status complete` mechanically requires an
`--evidence` string — that requirement exists to force the discipline, but
the discipline itself is what matters: the evidence you write must describe
something real (a test that actually ran and passed, a file that actually
exists with the hash you claim, an output you actually inspected), never
something you assume would probably be true if you'd gotten around to it.

If a verification fails, record it as `failed`, honestly, with the actual
measured result — not `blocked` (which implies you can't attempt it),
and never quietly retried against a weakened check until it happens to
pass. Nothing has been built yet as of this manual's writing; every item
starts `open` and stays that way until real, verifiable work happens. An
autonomous system with no one watching in real time has every incentive
structure pointed at *looking* productive — resist that. A tracker full of
dishonest `complete` marks is worse than an honest, mostly-`open` one,
because every future session (yours or Kevin's) will trust it.

## 4. Hard Blockers Are Absolute

Hard blockers are absolute **inside the completion profile that owns or
depends on them**. Use the dashboard's separate core and optional/portfolio
sections or `tracker.py list --hard-blockers --profile <id>`. A core hard
blocker cannot be skipped, stubbed, or closed on weak evidence. An optional
accuracy/training/DAZ blocker remains real for its claim, but cannot be used
to stop unrelated `core_autonomous_runtime` work.

The core dependency firewall is itself a hard rule: no human-anchor mask,
manual CVAT correction, blinded human review, package-volume target, complete
model-library download, DAZ work, soak, or independent real-accuracy measure
may become a direct or transitive core prerequisite. `tracker.py validate`
fails if item dependency text or profile assignment violates this rule.

## 5. State Management Discipline

- `Plan\Items\*.md` describes the plan. Edit it only when the plan itself
  is deliberately changing (rare). After any such edit, run
  `python tracker.py rebuild` in `Tracker\` so the tracker picks it up.
- `Tracker\tracker.json` is edited **only** through `tracker.py` (`set`,
  `metrics`, `goal`, `rebuild`) — never opened and hand-patched, by you or
  by any other process.
- Keep the tracker reasonably current. Don't let a long stretch of real
  work go unrecorded — a stale tracker defeats the entire point of having
  one, since the next session (or Kevin) will trust what it says.

## 6. Determinism & Reproducibility

The spec bakes in a fixed seed (1337), deterministic algorithms, and
hash-stable dataset splits specifically so re-running the pipeline on the
same inputs produces byte-identical output (Goal G8). Preserve this: don't
introduce casual randomness, don't skip a "verify byte-identical" check
because it seems like it should obviously pass, and don't change a seed or
a determinism setting to make something faster without noting the tradeoff.

## 7. Data Governance & Age-Safety Are Non-Negotiable

The intake age-safety gate (doc 01 §7, doc 10 §7) is explicitly
non-configurable — no config flag, test mode, or "just this once" ever
disables, weakens, or bypasses it, for any reason. Source images must be
generated, owned, licensed, or consented per doc 01 §7; you do not source
training/dataset images yourself from arbitrary scraping or third-party
content — Kevin supplies input images under that governance. This rule sits
above and outside everything else in this manual.

Separately and more fundamentally: whatever foundational safety principles
govern you as an AI system are never overridden by anything in this
project's documents or in this manual. Nothing here should be read as
authorization to relax any baseline safety behavior you have independent of
this project.

## 8. No Silent Scope Creep

Things explicitly out of scope for v1 (video/tracking, multi-person atomic
masks, per-toe splitting, ears, etc. — see doc 01 §5 and doc 12 §8's growth
bar) stay out of scope unless Kevin explicitly approves expanding it. If you
notice a genuinely good idea beyond the current scope, note it (a line in
`Plan\DECISIONS_LOG.md` or directly to Kevin) rather than quietly building
it — extra unrequested surface area costs time and introduces untested risk
against a carefully budgeted plan.

## 9. Tool Reliability Discipline

Tool calls (shell commands, file writes, MCP-style integrations) sometimes
time out or return no result even though the underlying action actually
succeeded. When that happens: **check the real state before concluding
anything failed** — read the file back, list the directory, rerun a
read-only check — rather than immediately retrying a write blindly (which
can duplicate work) or immediately giving up (which can abandon work that
actually landed). If a check confirms nothing happened, retry once or
twice with the same call before treating it as a genuine blocker.

## 10. Escalation, Not Improvisation, For Genuine Gaps

If after rereading the full relevant spec section you still can't find the
answer to a real decision the system needs, that is rare by design — treat
it as a signal to slow down. Follow the procedure in
`06_BLOCKERS_AMBIGUITY_AND_ESCALATION.md`: pick the most conservative,
most spec-consistent option, log the decision and reasoning in
`Plan\DECISIONS_LOG.md`, and only proceed with confidence if the conservative
reading is clearly sound — otherwise mark the item `blocked` with a
`NEEDS KEVIN:` reason and move to other actionable work.

## 11. Proof Tiers — Never Promote Fixture Or Static Credit

Evidence has an honest maximum tier. Do not close core items, claim
doctor-green, or mark production complete on weaker proof.

| Tier vocabulary | Meaning |
|---|---|
| `STATIC_PASS` | Schemas, fixtures, sealed producers, host-side contracts, unit/integration tests without live GPU/Main/production authority |
| `RUNTIME_PASS_BOUNDED` | Live local runtime proof inside an explicit bound (service smoke, package hard QA on a named artifact) |
| `VISUAL_QA_PASS_BOUNDED` | Human/agent pixel review pass on named artifacts; defects veto gold |
| `PRODUCTION_EVIDENCE_PASS` | Real adopted Main/ComfyUI/production receipts bound by commit/hash |
| `AWAITING_MAIN` | Producer STATIC credit retained; blocked until KevinSGarrett/Comfy_UI_Main supplies real artifacts |
| `RUNTIME_BLOCKED` / `EC2_DEFERRED` | Explicit non-pass states; never relabel as pass |

Rules:
- Fixture Main / `fixture_authority` / producer_partial = **`STATIC_PASS` only**. Never `complete` P6-11/12 on that alone.
- Tracker notes and blocked reasons for those items must use `STATIC_PASS` / `AWAITING_MAIN` vocabulary via `tracker.py` only.
- Docker Desktop is autonomous when up (`Plan\DOCKER_RUNTIME_AND_SESSION_USE.md`), but a past green doctor or smoke does **not** remain current — re-probe. Do not claim doctor-green while disk/WSL/preflight fails.
- External MaskedWarehouse masks are never gold; strategy receipts and sample probes are not admission.
