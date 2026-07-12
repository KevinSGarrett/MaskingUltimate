# Ontology Changelog

Every ontology change lands here BEFORE it lands in `configs\ontology.yaml`, per the change
procedure in `02_MASK_ONTOLOGY_SPEC.md` §9. Entry template:

```
## [body_parts_vX] — YYYY-MM-DD
- Change: (add/rename/split/retire label <name>, ID <n>)
- Evidence: (failure_queue items / coverage need — link the ≥10-failures analysis per doc 12 §8)
- Boundary definition: (exact rule added to doc 02 §6)
- swap_partner: (for sided labels)
- Back-annotation plan: (re-annotate N existing golds | mark not_annotated_in_vX)
- Dataset impact: (major version bump → datasets\<name>@vN+1)
- Approved by: Kevin
```

---

## [body_parts_v1] — 2026-07-09
- Initial ontology. 56 atomic PART IDs (0–55), 16 MATERIAL IDs (0–15), band/derived/projected/
  protected registries as specified in `02_MASK_ONTOLOGY_SPEC.md`. IDs 54/55 (ears) reserved,
  disabled. Per-toe splits and finer thigh/shin bands explicitly deferred to v2 pending
  failure-mining evidence.

## [body_parts_v2 evaluation: NO-GO] — 2026-07-12
- Change: None. Keep `body_parts_v1`; IDs and enabled states remain unchanged.
- Evidence: `qa/reports/ontology_v2_evidence_review_2026-07-12.{json,md}`. The live failure
  queue contains 16 current deduplicated QC-014 failures, but none is attributable to the
  proposed per-toe, inner/outer-thigh, shin-front, or ear boundaries; every candidate remains
  at 0/10 qualifying distinct failures.
- Boundary definition: None authorized.
- swap_partner: None added or changed.
- Back-annotation plan: Not applicable because the evidence gate failed.
- Dataset impact: None; no major-version bump.
- Approval: No owner approval requested because this is a threshold-mandated NO-GO, not an
  ontology change. Any future GO still requires Kevin's approval under the template above.
