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
  "completion_profiles": { ... },
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
  "total_items": 827,                             // parsed from Items/*.md at last rebuild
  "total_tracked_including_orphaned": 827          // includes any orphaned ids
}
```

## `phase_meta`

One entry per phase P0–P9: `{name, file, entry_gate}`. `file` identifies the
legacy primary phase file; additional phase-native addendum files are discovered by the parser.
`entry_gate` is free text describing the
condition that should hold before starting that phase (see README §5) — not
mechanically enforced.

## `hard_blocker_prefixes`

The literal list of legacy id-prefixes used to compute each item's `hard_blocker`
flag at rebuild time. Addendum items also become hard blockers when their source
description contains the exact `HARD BLOCKER` marker.

## `metrics`

Free-form `{key: value}` map with scalar JSON values preserved by `--set`.
Seeded at rebuild with separate human-anchor partitions, autonomous-certified, pseudo-label, and
machine-candidate counts; `certified_training_package_count`; `effective_training_weight_units`;
zero-touch/routine-touch/audited/residual fractions, human touches per 100 images, manually changed
pixels per 100,000, audit failure rates, certified-package targets, and coverage. The certified package count
is derived from the human-anchor training count plus autonomous-certified count. Pseudo-labels and
calibration/holdout anchors never contribute to that gate.

## `completion_profiles`

```jsonc
"completion_profiles": {
  "core_autonomous_runtime": {},
  "independent_real_accuracy": {},
  "scale_daz_maturity": {}
}
```

These are placeholders, not mutable status. `compute_completion_profile_status()`
derives each profile from the exact `driven_by` item set frozen in `tracker.py`
and cross-validates it against `completion_track_registry.json`.

- `core_autonomous_runtime`: required and human-free; the sole product finish line.
- `independent_real_accuracy`: optional/non-blocking human-anchor/real-holdout claims.
- `scale_daz_maturity`: post-core/non-blocking scale, model-library, training, and DAZ maturity.

The tracker validator refuses registry/constant drift, unknown or duplicate profile
fields/items, prerequisite cycles, and any direct or transitive human-anchor, CVAT
correction, volume, full-library, DAZ, or soak dependency attached to core.

### Completion registry siblings

`completion_track_registry.json` is the closed, versioned planning authority:

- `authoritative_spec_sha256` binds the exact bytes of doc 24;
- `sha256` binds canonical UTF-8 JSON (`sort_keys`, compact separators, `ensure_ascii=false`) with
  the `sha256` field omitted;
- `tracker.py validate` independently recomputes both hashes before accepting profile status.

```jsonc
{
  "schema_version": "1.0.0",
  "registry_id": "maskfactory_completion_tracks",
  "policy_version": "2026-07-17",
  "authoritative_spec": "Plan/24_AUTONOMOUS_CORE_COMPLETION_AND_COMFYUI_BRIDGE.md",
  "profiles": [
    {
      "profile_id": "core_autonomous_runtime",
      "classification": "required | optional | post_core",
      "blocking_for_core_completion": true,
      "purpose": "...",
      "completion_claim": "...",
      "required_item_ids": ["MF-P6-07.01"],
      "prerequisite_profile_ids": [],
      "allowed_evidence": ["..."],
      "forbidden_claims": ["..."],
      "excluded_core_dependencies": ["human_anchor_masks"]
    }
  ]
}
```

`completion_track_registry.schema.json` is the formal Draft 2020-12 schema.
`tracker.py validate` implements equivalent stdlib closed-field checks so the
tracker does not acquire a runtime dependency on `jsonschema`.

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
{"ts": "...", "metrics_update": {"human_anchor_train_count": 42, "certified_training_package_count": 42, ...}}

// a `goal` call
{"ts": "...", "goal": "G2", "measured": "0.87 body / 0.71 fingers", "status": "met"}
```

This is the full audit trail of every change ever made through the CLI.
`DASHBOARD.md`'s "Recent Activity" section is just the tail of this file,
rendered.
