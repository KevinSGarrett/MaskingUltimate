# Ontology v2 evidence review — 2026-07-12

Decision: **NO-GO. Keep `body_parts_v1` unchanged.**

The authoritative `qa/failure_queue.jsonl` contains 16 current, deduplicated QC-014 failures.
None is attributable to a missing per-toe, inner/outer-thigh, shin-front, or ear boundary, so the
current qualifying count remains zero for every candidate. The mandatory growth bar is at least
10 distinct failures within 30 days attributable to the missing boundary.

| Candidate | Qualifying failures | Required | Decision |
|---|---:|---:|---|
| Per-toe atomic splits | 0 | 10 | NO-GO |
| Left/right inner and outer thigh | 0 | 10 | NO-GO |
| Left/right shin-front | 0 | 10 | NO-GO |
| Enable reserved ears 54/55 | 0 | 10 | NO-GO |

No IDs, labels, boundaries, swap partners, CVAT labels, or dataset versions are authorized to
change. Re-evaluate only after the queue contains qualifying evidence; adult/NSFW metadata is
not an exclusion criterion for otherwise governed adult training sources.
