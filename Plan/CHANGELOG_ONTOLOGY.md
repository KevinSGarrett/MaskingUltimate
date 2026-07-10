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
