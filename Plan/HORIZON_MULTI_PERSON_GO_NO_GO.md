# Multi-Person Promotion Horizon Decision

Date: 2026-07-12

> **Doc-24 supersession (2026-07-17):** this historical horizon decision no longer defines
> `core_autonomous_runtime`. D11/G9 real-reviewed-image, Kevin SOP, CVAT, source-volume, labor, and
> independent real-accuracy requirements below are retained only for the optional
> `independent_real_accuracy` or post-core `scale_daz_maturity` claim. Core multi-person eligibility
> is governed by MF-P6-08..12: exact instance/character ownership, silhouette exclusivity,
> cross-instance-bleed/contact/occlusion hard vetoes, executable transforms, qualified autonomous
> critics, bounded repair or typed abstention, exact operational certificates, revocation, and the
> adopted MaskFactory↔ComfyUI release. Human review cannot block or revoke that route.

Architecture decision: **GO — already promoted into normative Phase P8 / document 17.**

Historical Production promotion decision: **NO-GO until D11/G9 pass on real reviewed images.**
That sentence remains authoritative only for an independent real-image accuracy or legacy
human/training-gold claim. Core production is eligible only through the doc-24 autonomous
certificate and bridge gates and is not blocked by D11/G9 human evidence.

Document 17 replaced the old horizon question with a complete design: process each promoted
person as an independent `instances/pN` package under one image. Atomic ontology names do not
need person namespaces because ownership is supplied by package path and full instance ID. This
avoids permanent labels such as `person_2_left_hand`.

Implemented contracts include ranked promotion, per-instance S02–S09 execution, co-subject
protection, S09.5 reconciliation, reciprocal contact bands, QC-035–038, image-level splitting,
optional per-instance CVAT tasks plus overview, coverage/leaderboard context, and ComfyUI
`person_index`. CVAT availability is not part of the core runtime path.

Legacy annotation and training-gold counts scale per promoted instance, not source image. A
three-person photo contributes three human/training-gold packages only after its optional exact
truth-tier review; an `operationally_certified_artifact` remains operational, never gold. Shared
overview/contact review overhead and G1 measurements are optional accuracy/scale evidence and are
reported separately for `solo`, `duo`, and `small_group`.

Optional independent real-accuracy/scale promotion remains NO-GO until 10–20 governed real
2–4-person images complete its declared pipeline and Kevin's SOP-1 through SOP-6 review. That
evidence is tracked by `MF-P8-10.01..06` and `MF-P8-EXIT` and fixtures cannot substitute for its
claim. Separately, core must pass the single-/multi-person Mode A and Mode B vertical slices plus the
cross-project fault matrix in MF-P6-12; every consumed instance must pass operational package QA,
QC-035/036 must be clean, reciprocal contact/ownership must be unambiguous, and failures must repair,
abstain, revoke, or block the dependent DAG scope without mandatory human routing.
