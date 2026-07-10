# tracker.json — Schema Reference

`tracker.json` is the canonical state store. This document is the formal
field-by-field reference. It is regenerated/rewritten only by `tracker.py`
(`rebuild`, `set`, `metrics`, `goal`) — never hand-edited. Read this if you
need to inspect the file directly (e.g. with `jq`) or write an alternative
tool against it.

---

## Top-Level Structure

```jsonc
{
  "meta": { ... },
  "phase_meta": { ... },
  "hard_blocker_prefixes": [ ... ],
  "metrics": { ... },
  "dod": { ... },
  "goals": { ... },
  "items": { "<id>": { ... }, ... }
}
```

## `meta`

```jsonc
{
  "schema_version": "1.0.0",
  "generated_at": "2026-07-10T01:55:22+00:00",   // last `rebuild` timestamp
  "generator": "tracker.py rebuild",
  "total_items": 326,                             // parsed from Items/*.md at last rebuild
  "total_tracked_including_orphaned": 326          // includes any orphaned ids
}
```

## `phase_meta`

One entry per phase P0–P7: `{name, file, entry_gate}`. `file` points to the
corresponding `Plan\Items\*.md`. `entry_gate` is free text describing the
condition that should hold before starting that phase (see README §5) — not
mechanically enforced.

## `hard_blocker_prefixes`

The literal list of id-prefixes used to compute each item's `hard_blocker`
flag at rebuild time (see README §5 for what they are and why).

## `metrics`

Free-form `{key: value}` map, all values stored as strings after a `--set`.
Seeded at first rebuild with:
`approved_gold_count`, `target_gold_p5_entry`, `target_gold_d5`,
`target_gold_g6_stretch`, `coverage_cells_at_target_pct`. Any new key can be
added via `metrics --set newkey=value`.

## `dod` (Definition of Done, D1–D11)

Currently an empty placeholder per id (`{}`) — DoD status is **not stored**;
it is computed on demand by `compute_dod_status()` in `tracker.py` from the
live status of each entry's `driven_by` items (defined in the `DOD` constant
in `tracker.py`, mirroring doc 00 §4). The placeholder exists so future
versions could cache or override a computed value without a schema change.

## `goals` (G1–G9)

```jsonc
"G2": {
  "status": "pending | met | not_met",
  "measured": null,          // free text once recorded, e.g. "0.87 body / 0.71 fingers"
  "updated_at": null         // ISO-8601 UTC timestamp of last `goal` call, or null
}
```
Goal *text* and *target* (what G2 means, what number counts as "met") live
in the `GOALS` constant in `tracker.py` (mirroring doc 01 §3), not in
`tracker.json` — `tracker.json` only stores the measured/status state.

## `items."<id>"` — one record per checklist item

```jsonc
{
  // -------- METADATA (derived from Plan\Items\*.md; set only by `rebuild`) --------
  "id": "MF-P0-01.01",
  "phase": "P0",
  "cluster_id": "MF-P0-01",
  "cluster_title": "WSL2 Ubuntu 22.04 + systemd + hot workdir",
  "spec_ref": "06 \u00a71",              // section of Plan\ this item is defined by
  "description": "Confirm NVIDIA driver \u2265 591 on Windows host ...",
  "source_file": "01_ITEMS_P0_ENVIRONMENT.md",
  "source_line": 6,                       // line number in that file, at last rebuild
  "is_exit_gate": false,                  // true only for the *-EXIT items
  "hard_blocker": false,                  // true if id matches hard_blocker_prefixes
  "conditional": false,                   // true if id is in the conditional-items set

  // -------- STATE (mutated only by `set`) --------
  "status": "open",                       // one of the 8 statuses (see README §4)
  "percent_complete": 0,                  // 0-100
  "notes": [                              // append-only history, most recent last
    {"ts": "2026-07-10T...", "actor": "ai_agent", "text": "..."}
  ],
  "evidence": null,                       // string once status=complete (required)
  "blocked_reason": null,                 // string once status=blocked (required)
  "created_at": "2026-07-10T01:55:22+00:00",
  "updated_at": "2026-07-10T01:55:22+00:00",
  "orphaned": false                       // true if id no longer exists in source Items/*.md
}
```

### Field notes

- **`spec_ref` / `source_file` / `source_line`**: your path back to the full
  human-written contract for this item. The tracker only ever stores the
  compressed one-line description; always defer to the spec doc for
  ambiguity.
- **`orphaned`**: set only by `rebuild`, when an id that previously existed
  in `Plan\Items\*.md` is no longer found there (the file was edited). The
  full state record (status, evidence, notes) is preserved forever, just
  flagged. Orphaned items are excluded from all rollup math (`phase_stats`,
  overall progress, `EXPECTED_ITEM_COUNT` comparisons) but still visible via
  `show`/direct JSON inspection.
- **`notes`**: unbounded list; `report` only renders the last 3 per item in
  `phases\P#.md` to keep those files readable, but all notes are retained in
  `tracker.json` and in `CHANGELOG.jsonl` forever.

---

## `CHANGELOG.jsonl` (sibling file, not part of tracker.json)

One JSON object per line, append-only, one of three shapes:

```jsonc
// an item `set` call
{"ts": "...", "id": "MF-P0-01.01", "actor": "ai_agent",
 "old_status": "open", "new_status": "complete", "percent_complete": 100,
 "note": null, "evidence": "...", "blocked_reason": null}

// a `metrics --set` call
{"ts": "...", "metrics_update": {"approved_gold_count": "42", ...}}

// a `goal` call
{"ts": "...", "goal": "G2", "measured": "0.87 body / 0.71 fingers", "status": "met"}
```

This is the full audit trail of every change ever made through the CLI.
`DASHBOARD.md`'s "Recent Activity" section is just the tail of this file,
rendered.
