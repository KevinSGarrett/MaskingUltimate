# MaskFactory Project Tracker — README

This folder is the **live, machine-readable status tracker** for the entire
Ultimate Masking System build-out: all 798 action items from
`Plan\Items\*.md`, three independently scoped completion profiles, the
Definition-of-Done (D1–D11) and Goals (G1–G9) rollups, and tier-separated
truth, labor, audit, coverage, and certified-package metrics.

**The required finish line is `core_autonomous_runtime`.** The legacy all-item
percentage is a portfolio rollup that includes optional independent-accuracy and
post-core scale/DAZ work; it is not global end-to-end completion authority.

**If you are an AI agent picking up this project cold, read this file
first, then run `python tracker.py report` and open `DASHBOARD.md` to see
exactly where the project currently stands.**

---

## 1. The Three Sources of Truth (do not confuse them)

| What | Lives in | Who edits it | How |
|---|---|---|---|
| **Item metadata** (id, description, phase, spec reference, verify/blocker clauses, hard-blocker / conditional / exit-gate flags) | `Plan\Items\*.md` (21 parsed checklist files plus the master/traceability documents) | A human, deliberately, when the plan itself changes | Edit the markdown, then run `python tracker.py rebuild` |
| **Item state** (status, percent, evidence, notes, blocked reason, timestamps) | `Tracker\tracker.json` | Anyone (human or AI) working the project | **Only** via `python tracker.py set ...` / `metrics` / `goal` |
| **Completion policy** (required core, optional independent accuracy, post-core scale/DAZ) | self-hashed `completion_track_registry.json`, schema, byte-hashed doc 24, and mirrored constants in `tracker.py` | Deliberate governed plan change only | Edit all authorities together, reseal both hashes, and run `validate`; drift fails closed |

`tracker.json` is never hand-edited. `Plan\Items\*.md` is never used to record
progress (checkboxes there stay as originally written — the live status is
in the tracker, not in those files). This split means the checklist files
stay a stable, versionable spec, while the tracker is the fast-moving,
disposable-and-regenerable state layer on top of it — `rebuild` can be run
at any time and will never lose recorded progress, because it merges by id.

---

## 2. Requirements

Python 3.11+ with the project dependencies installed. Registry validation uses
the project's declared `jsonschema` dependency and Draft 2020-12; run from the
repository environment or install the locked project dependencies first. Run
everything from this folder:

```
cd C:\Comfy_UI_Main_Masking\Plan\Tracker
python tracker.py <command> ...
```

---

## 3. Command Reference

### `rebuild` — (re)parse Items/*.md into tracker.json
```
python tracker.py rebuild
```
Run this once to initialize (already done — `tracker.json` exists with all
798 items after the docs 18–24/SAM 3.1/DAZ/bridge reconciliation). Rerun it any time `Plan\Items\*.md` is
edited (labels added, items split, etc.). It **preserves all existing
status/evidence/notes** for ids that still exist, marks ids no longer found
in the source as `orphaned: true` (never deletes their history), and adds
any brand-new ids as fresh `open` items. A timestamped backup of the prior
`tracker.json` is written to `Tracker\backups\` before every save, by every
command that writes state — so nothing is ever unrecoverable.

### `show` — full detail on one item
```
python tracker.py show MF-P0-01.01
```
Prints the complete JSON record: description, spec reference, status,
evidence, notes, blocked reason, hard-blocker/conditional flags, timestamps.

### `set` — the only way to change an item's state
```
python tracker.py set <ID> [--status STATUS] [--note "..."] [--evidence "..."]
                           [--percent 0-100] [--blocked-reason "..."]
                           [--actor "..."]
```
- `--status` must be one of: `open`, `in_progress`, `partially_complete`,
  `blocked`, `complete`, `failed`, `deferred`, `not_applicable` (see §4 for
  what each means).
- Marking `complete` **requires** `--evidence` (either on this call or
  already recorded) — the tool refuses otherwise. Evidence should be
  concrete: a file path, a command's output, a git commit hash, a test
  name that passed, an OPS_LOG date. "done" is not evidence.
- Marking `blocked` **requires** `--blocked-reason` (same rule). Be
  specific: what exactly is blocking it, and (if known) what would unblock
  it.
- `--note` appends to a running note history without changing status —
  useful for logging progress on something still `in_progress`.
- `--percent` lets you record partial progress (e.g. 60) independent of
  status; `complete`/`not_applicable` force it to 100, `open` forces it to 0.
- `--actor` records who/what made the change (default `ai_agent`); use
  `--actor kevin` for changes made by Kevin directly, or a more specific
  agent name if useful.
- Calling `set <ID>` with no flags just prints the current record (safe,
  read-only — a no-op you can always run to check before changing anything).

Examples:
```
python tracker.py set MF-P0-01.01 --status complete --evidence "nvidia-smi confirms 592.01, logged in OPS_LOG 2026-07-10"
python tracker.py set MF-P2-05.02 --status blocked --blocked-reason "sam2.1_hiera_large.pt download failing, HF endpoint 503"
python tracker.py set MF-P5-03.02 --status in_progress --percent 40 --note "training started, 12k/40k iters"
python tracker.py set MF-P5-08.01 --status not_applicable --evidence "trigger never fired: <80 hair-prominent golds at P5 close"
```

### `list` — filter and browse
```
python tracker.py list [--phase P0..P9] [--status open,blocked] [--hard-blockers]
                        [--conditional] [--blocked] [--search "sam2"]
                        [--profile core_autonomous_runtime]
```
Statuses can be comma-separated. No filters = list everything (798 lines).
`--profile` restricts the result—including `--blocked` or `--hard-blockers`—to
the profile's complete transitive item-dependency closure.

### `next` — what should I work on
```
python tracker.py next -n 10 [--phase P0] [--profile core_autonomous_runtime]
```
Returns the next N items that are not yet resolved (`open`, `in_progress`,
`partially_complete`, or `failed`). While `core_autonomous_runtime` is
incomplete, unqualified `next` calls prioritize its items before optional
portfolio work. `--profile` strictly limits suggestions to that profile's
complete transitive dependency closure.
Within a priority group, results follow phase order (P0→P9) then document
order. This does **not** do full dependency-graph solving —
it respects the project's overall phase sequence and the order items were
written in (which itself follows the dependency order laid out in doc 14),
but it does not know about phase entry gates (see §5) or hard-blocker
priority beyond flagging them. Use judgment: hard-blocker items and phase
exit gates are usually worth tackling before moving deeper into a phase.

### `metrics` — free-form project counters
```
python tracker.py metrics --set human_anchor_train_count=42
python tracker.py metrics --set autonomous_certified_gold_count=180
python tracker.py metrics --show
```
Currently tracked keys (seeded at rebuild, editable any time):
the three `human_anchor_*_count` partitions, `autonomous_certified_gold_count`,
`weighted_pseudo_label_count`, `machine_candidate_count`,
`certified_training_package_count`, `effective_training_weight_units`, zero-touch, routine-touch,
audited/residual fractions, human touches per 100 images, manually changed pixels per 100,000,
and audit failure rates,
certified-package targets, and coverage. Metric values are stored as scalar JSON values.
`certified_training_package_count` is automatically recomputed as
`human_anchor_train_count + autonomous_certified_gold_count`; pseudo-labels and calibration/holdout
anchors never satisfy P5 or D5.

### `goal` — record a measured Goal (G1–G9)
```
python tracker.py goal G2 --measured "0.87 body / 0.71 fingers" --status met
```
`--status` is one of `pending`, `met`, `not_met`. Goals are continuous
metrics (mean IoU, minutes/image, etc.) that can only be known after an
actual measurement (e.g. a leaderboard run or a timed annotation session) —
they are not auto-computed the way DoD items are (see §5).

### `validate` — consistency check
```
python tracker.py validate
```
Confirms 798 non-orphaned items, no duplicate/invalid statuses, validates the
closed completion registry and its mirror in `tracker.py`, fails any direct or
transitive human/CVAT/volume/full-library/DAZ/soak dependency assigned to core, and flags
`complete` items missing evidence, `blocked` items missing a reason, and any
orphaned items. Exits non-zero only on a structural problem (never on
warnings) — safe to run in CI or as a pre-commit check.

### `report` — regenerate the human-readable views
```
python tracker.py report
```
Regenerates `DASHBOARD.md` (required core status first, a clearly labeled
portfolio %, independent completion profiles, per-phase progress, optional
DAZ status, separately scoped core/portfolio blockers, DoD table, Goals table, tracked metrics, recent
activity, suggested next actions) and
`phases\P0.md` … `phases\P8.md` (every single item in that phase, live
status glyph, evidence, notes — a full-detail mirror of the original
`Plan\Items\*.md` file but reflecting current real state).

**Run `report` after every batch of `set`/`metrics`/`goal` calls** so the
markdown views stay in sync with `tracker.json`. The markdown files are
never hand-edited — they carry an auto-generated banner as a reminder.

The `daz_*` vertical-slice metrics are live-evidence counters in the optional
post-core `scale_daz_maturity` profile, not core planning targets. Update them only
when the corresponding governed identity snapshot, graph, certificate, scene, package, training run,
or real-image benchmark changes; fixture-only work must leave the live counter unchanged.

---

## 4. Status Taxonomy

| Status | Meaning | Counts as "done"? |
|---|---|---|
| `open` | Not started. Default for everything at rebuild. | No |
| `in_progress` | Actively being worked right now. | No |
| `partially_complete` | Some sub-verification passed, not all of it yet. | No |
| `blocked` | Cannot proceed; `blocked_reason` required. | No |
| `complete` | Verify clause satisfied; `evidence` required. | **Yes** |
| `failed` | Attempted, did not pass verification — needs rework, distinct from `blocked` (which means *can't even attempt yet*). | No |
| `deferred` | Intentionally postponed / deprioritized (not the same as blocked — nothing is stopping it, it's just not now). | No |
| `not_applicable` | A conditional item whose trigger never fired (see Items master index rule: this legitimately counts as resolved). | **Yes** |

Only `complete` and valid `not_applicable` states count toward item rollups.
`not_applicable` requires evidence and is permitted only for an explicitly
conditional item outside the mandatory `core_autonomous_runtime` dependency
closure. Profile status is computed across each profile's complete transitive
item-dependency closure; every core dependency must be `complete`. The portfolio
percentage must never be called end-to-end completion because it deliberately
mixes required, optional, and post-core scope.

---

## 5. Hard Blockers, Conditional Items, and Phase Gates

Hard-blocker items are called out because the project's own spec docs are
explicit that they cannot be skipped, worked around, or approved past. The
legacy blocker clusters remain active, and modernization addenda declare
additional atomic blockers with the literal `HARD BLOCKER` marker:

- `MF-P0-07.*` — the `doctor` command must be all-green before real work starts
- `MF-P1-03.*` — the ontology.yaml CI assert (label authority integrity)
- `MF-P1-07.*` — format-QC BLOCK enforcement (bad gold must be structurally impossible)
- `MF-P4-05.*` — the VLM calibration gate (≥0.90 recall / ≥0.80 precision or no VLM in prod)
- `MF-P5-02.02` — the flip/swap_partner CI test (prevents silent L/R data poisoning)
- `MF-P5-05.04` — the D7 gate (finger mIoU ≥ 0.70)
- `MF-P5-07.02` — the D6 gate (champion model beats the draft pipeline)
- `MF-P8-05.01` / `.02` — QC-035/036 instance exclusivity + cross-instance bleed (doc 17)
- `MF-P8-07.*` — the multi-person dataset split-integrity CI test (doc 17 §8)
- modernization blockers cover ontology-v2 activation, per-provider governance,
  autonomous certification, truth-tier training eligibility, hard-bucket
  non-inferiority, serving rollback, and recurring currency review

`python tracker.py list --hard-blockers` shows the full portfolio. Use
`python tracker.py list --hard-blockers --profile core_autonomous_runtime` for
the required finish line. The dashboard renders core and optional/portfolio
blockers separately.

**Conditional items** (`MF-P5-08.01`, `MF-P5-08.02`, `MF-P7-01.04`,
`MF-P7-03.05`) may legitimately resolve to `not_applicable` if their trigger
condition in the spec never fires — that is not a failure, it's a correct
outcome. Use `--status not_applicable --evidence "trigger not met: ..."`.

**Phase entry gates** are informational (shown in `DASHBOARD.md` and each
`phases\P#.md`) but not mechanically enforced by the CLI — nothing stops you
from marking a P5 item complete before `certified_training_package_count` hits 200. The
gates exist so an agent reads them and *chooses* not to start P5 work early,
per the project's own critical-path rules in doc 14 §9. Check
`metrics --show` and the DoD table before starting a gated phase.

P6 has two lanes: legacy trained-champion serving retains its D6/provider gates,
while doc-24 `MF-P6-07` through `MF-P6-12` core-autonomy/bridge work has no
D6, human, package-volume, full-library, DAZ, or soak prerequisite.

---

## 6. Completion Profiles, Definition of Done, and Goals

`DASHBOARD.md` renders all three systems automatically.

- **`core_autonomous_runtime`** is required and human-free. It proves autonomous
  mask generation, hard QA, independent critics, bounded repair, abstention,
  exact-output certification, revocation, recovery, and the adopted ComfyUI bridge.
- **`independent_real_accuracy`** is optional/non-blocking. Human anchors, CVAT,
  blinded audits, and real holdouts support only its accuracy/calibration claims.
- **`scale_daz_maturity`** is post-core/non-blocking. Corpus scale, full-library
  qualification, custom training, DAZ, and long soaks belong only here.

- **DoD (D1–D11)** status is **computed automatically** from the status of
  each entry's `driven_by` item(s) — you never set a DoD status directly.
  If a computed status looks wrong, the fix is to correct the `driven_by`
   mapping inside `tracker.py`'s `DOD` dict, not to hand-set anything. D1 is version-aware:
   56 indexed PART drafts for active v1 and 65 only after gated v2 activation.
- **Goals (G1–G9)** are continuous measured metrics (mean IoU, human touches,
  audited/residual fractions, changed pixels, review minutes, and other measured
  image, etc.) that genuinely require a human/AI to go measure something
  (e.g. run the leaderboard, time an annotation session) and record it with
  `tracker.py goal <Gid> --measured "..." --status {pending,met,not_met}`.

The requested product finish line is the computed `core_autonomous_runtime`
profile. Legacy D/G rollups and headline tests remain visible evidence mapped to
their proper profile; human-anchor/blinded/volume/DAZ requirements cannot silently
redefine core completion.

---

## 7. Rules for Any AI Agent Using This Tracker

1. **Never hand-edit `tracker.json`.** Always go through `set` / `metrics` /
   `goal`. If you need to change item *metadata* (description, spec ref),
   edit `Plan\Items\*.md` and run `rebuild` — never patch `tracker.json`
   directly for that either.
2. **Evidence and blocked-reasons are not optional decoration.** The CLI
   enforces this at the boundary (it will refuse the call), but the spirit
   matters more than the mechanism: write evidence a skeptical reviewer
   would find convincing, and blocked-reasons specific enough that someone
   else could actually unblock the item.
3. **Don't mark something complete because you wrote code for it.** Match
   the item's own verify clause (visible in its description, carried over
   verbatim from `Plan\Items\*.md`) — most items require a test, a fixture
   result, or a real run's output, not just "implemented."
4. **Run `python tracker.py report` after any batch of changes.** The
   markdown dashboard/phase files are what a human (or the next AI session)
   will actually read; if you only mutate `tracker.json` and never
   regenerate, the visible state goes stale.
5. **Run `python tracker.py validate` before ending a work session.** It's
   cheap, fast, and catches silent drift (missing evidence, missing
   blocked-reasons, unexpected item-count changes).
6. **Respect profile-scoped gates.** Package-volume and holdout gates still
   govern their training/accuracy profiles, but they do not delay doc-24 core
   autonomy/bridge work. Use `next`'s core-first default and the dashboard's
   separately scoped blocker sections.
7. **When in doubt about an item's meaning, go to the spec.** Every item
   carries a `spec_ref` (e.g. `06 §1`) pointing at the exact section of the
   numbered documents in `Plan\` that define it in full. The item text
   in the tracker is a compressed checklist line, not the full contract.
8. **This is Kevin's real project status.** Never infer zero progress or completion from when the
   tracker was created; read the live item state and evidence. Do not simulate progress.

---

## 8. Files In This Folder

| File | What |
|---|---|
| `tracker.py` | The Python CLI. Source of tracker logic; Draft 2020-12 registry validation uses `jsonschema`. |
| `tracker.json` | Canonical state store. Machine-owned; don't hand-edit. |
| `completion_track_registry.json` | Frozen required/optional/post-core completion policy and exact item assignments; binds doc 24 bytes and its own canonical content SHA-256. |
| `completion_track_registry.schema.json` | Closed Draft 2020-12 schema for the completion policy; `validate` runs schema and semantic cross-authority checks. |
| `CHANGELOG.jsonl` | Append-only audit log — one JSON line per `set`/`metrics`/`goal` call ever made, with timestamp, actor, old/new status. Never edited or truncated by the tool. |
| `backups\` | Timestamped snapshots of `tracker.json`, written automatically before every save. Safe to prune manually if it grows large; never required for normal operation. |
| `DASHBOARD.md` | Auto-generated project-wide rollup. Regenerate with `report`. |
| `phases\P0.md` … `P9.md` | Auto-generated, full-detail live mirror of each phase's items with current status/evidence/notes. Regenerate with `report`. |
| `README.md` | This file. |
| `SCHEMA.md` | Formal field-by-field reference for `tracker.json`'s structure. |
