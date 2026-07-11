# Multi-Person Promotion Horizon Decision

Date: 2026-07-12

Architecture decision: **GO — already promoted into normative Phase P8 / document 17.**

Production promotion decision: **NO-GO until D11/G9 pass on real reviewed images.**

Document 17 replaced the old horizon question with a complete design: process each promoted
person as an independent `instances/pN` package under one image. Atomic ontology names do not
need person namespaces because ownership is supplied by package path and full instance ID. This
avoids permanent labels such as `person_2_left_hand`.

Implemented contracts include ranked promotion, per-instance S02–S09 execution, co-subject
protection, S09.5 reconciliation, reciprocal contact bands, QC-035–038, image-level splitting,
per-instance CVAT tasks plus overview, coverage/leaderboard context, and ComfyUI `person_index`.

Annotation and package counts scale per promoted instance, not source image. A three-person photo
contributes three gold packages only after independent review. Shared overview and reciprocal
contact review add overhead. G1 must be measured separately for `solo`, `duo`, and `small_group`.

Production remains NO-GO until 10–20 governed real 2–4-person images complete the full pipeline
and Kevin's SOP-1 through SOP-6 review. Every instance must pass package QA; QC-035/036 must be
clean; contact records must be reciprocal; G9 cross-instance bleed must be zero. These are
`MF-P8-10.01..06` and `MF-P8-EXIT`; fixtures cannot substitute for that evidence.
