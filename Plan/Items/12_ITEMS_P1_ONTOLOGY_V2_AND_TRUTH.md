# ITEMS — Phase P1 Ontology-v2 Authority and Truth-Tier Packaging (docs 18, 20, 22, SAM 3.1 handoff)

> **Completion-profile scope (doc 24):** these rows remain truthfully tracked for their named
> ontology/truth lane. An exact completed deterministic row may be reused when it is explicitly in
> the `core_autonomous_runtime` dependency closure, but the phase's optional human-anchor/CVAT, corpus,
> training, or independent-accuracy gates are not inherited and cannot block or revoke core.

Goal: make ontology v2 and explicit truth authority machine-verifiable without changing active v1 until every activation gate passes.

## MF-P1-10 — Ontology-v2 generator and machine authority (spec: 18 checklist B)
- [ ] MF-P1-10.01 Import ten proposed labels append-only from `ontology_v2_additions.yaml` · Verify: generated inactive v2 preserves IDs 0..55 and appends exactly 56..65 · Blocked by: MF-P0-15.02
- [ ] MF-P1-10.02 Add boundary rules for areola ring, nipple carve-out, external vulva, shaft/glans, scrotal midline, and visible external anal opening · Verify: every new atomic references a validated rule and unknown rules fail generation · Blocked by: MF-P1-10.01
- [ ] MF-P1-10.03 Add reciprocal swaps for areolae, nipples, and scrotal regions · Verify: generator rejects missing/nonreciprocal character-side pairs · Blocked by: MF-P1-10.01
- [ ] MF-P1-10.04 Add alias resolution with warnings/provenance while forbidding aliases in maps/manifests · Verify: canonical, alias, union-alias, and unknown tests pass · Blocked by: MF-P1-10.01
- [ ] MF-P1-10.05 Add all v2 derived formulas and regenerate the active `configs/derived.yaml` only at activation · Verify: inactive `derived_v2.yaml` is drift-clean before activation and active derived output changes atomically with the ontology switch · Blocked by: MF-P7-06.06
- [ ] MF-P1-10.06 Extend visualization colors with distinct, accessible, stable values · Verify: all new atomics/unions have unique fixed colors and v1 colors are unchanged · Blocked by: MF-P1-10.01
- [ ] MF-P1-10.07 Generate `configs/ontology_v2.yaml` while retaining active v1 until activation · Verify: generator check is clean and artifact declares approved-but-inactive status · Blocked by: MF-P1-10.01
- [ ] MF-P1-10.08 Wire CI to prove IDs 0..55 unchanged and 56..65 contiguous · Verify: deliberate prefix or gap drift fails CI · Blocked by: MF-P1-10.07 · HARD BLOCKER
- [ ] MF-P1-10.09 Prove exactly 66 class names including background and correct flips · Verify: production loader tests exact order/count and every reciprocal swap · Blocked by: MF-P1-10.03, MF-P1-10.07

## MF-P1-11 — Ontology-v2 visibility, manifest, and migration (spec: 18 checklist C)
- [ ] MF-P1-11.01 Add `occluded_by_clothing`, `not_applicable`, and `unreviewed_for_v2` to the v2 schema only · Verify: v1 vocabulary remains byte-compatible and v2 schema accepts only canonical states · Blocked by: MF-P1-10.07
- [ ] MF-P1-11.02 Implement v2 state/mask invariants from doc 18 §4 · Verify: visible/nonvisible/ambiguous positive and negative schema/custom-validator fixtures pass · Blocked by: MF-P1-11.01
- [ ] MF-P1-11.03 Add `reviewed_ontology_version` and per-label review authority · Verify: v2 manifests require reviewer, time, source, ontology, and state provenance · Blocked by: MF-P1-11.01
- [ ] MF-P1-11.04 Implement idempotent v1→v2 migration with unchanged pixels and ten unreviewed additions · Verify: rerun is byte-identical and source package remains unchanged · Blocked by: MF-P1-11.01, MF-P1-11.03
- [ ] MF-P1-11.05 Never auto-convert unreviewed labels to absent, not-visible, or not-applicable · Verify: migration/schema tests fail every implicit-negative conversion · Blocked by: MF-P1-11.04
- [ ] MF-P1-11.06 Refuse v2 gold/dataset inclusion while any appended label remains unreviewed · Verify: packager and frozen-dataset discovery reject without mutating the package · Blocked by: MF-P1-11.02, MF-P1-11.03 · HARD BLOCKER
- [ ] MF-P1-11.07 Add migration dry-run report, hashes, collision detection, backup, and rollback · Verify: collision/drift fixtures fail and rollback restores exact source bytes · Blocked by: MF-P1-11.04
- [ ] MF-P1-11.08 Test every v2 state including ambiguity and clothing occlusion · Verify: parameterized schema/semantic tests cover all canonical states and forbidden combinations · Blocked by: MF-P1-11.02

## MF-P1-12 — Ontology-v2 optional CVAT and autonomous authority surface (spec: 18 checklist D)
- [ ] MF-P1-12.01 Create a versioned v2 CVAT project without mutating open v1 tasks · Verify: project IDs/labels differ and v1 task hashes remain unchanged · Blocked by: MF-P1-10.07
- [ ] MF-P1-12.02 Add canonical v2 labels and visibility attributes · Verify: exact label/attribute contract round-trips through the CVAT API · Blocked by: MF-P1-12.01
- [ ] MF-P1-12.03 Surface aliases as help/search text only · Verify: aliases cannot be exported as canonical labels · Blocked by: MF-P1-12.02
- [ ] MF-P1-12.04 Update task descriptions with the doc-18 SOP and character-perspective reminder · Verify: created task description contains versioned SOP/hash and side authority · Blocked by: MF-P1-12.01
- [ ] MF-P1-12.05 Add chest/pelvic review crop presets · Verify: fixture coordinates remain source-bound and reversible · Blocked by: MF-P1-12.01
- [ ] MF-P1-12.06 Push migrated tasks with additions explicitly unreviewed · Verify: every appended label starts unreviewed and no negative is fabricated · Blocked by: MF-P1-11.04, MF-P1-12.02
- [ ] MF-P1-12.07 Pull exact v2 states/masks and reject aliases/unknown values · Verify: round-trip and rejection fixtures pass · Blocked by: MF-P1-12.02
- [ ] MF-P1-12.08 Block export when visible masks are absent or null-mask states contain masks · Verify: CVAT export negative fixtures fail before package mutation · Blocked by: MF-P1-11.02, MF-P1-12.07 · HARD BLOCKER
- [ ] MF-P1-12.09 Build a 20–30 real-image authority pilot from `C:\Comfy_UI_Main\MaskedWarehouse` plus retrieval/coverage evidence from `F:\Reference_Images\Ultimate_Masking_Reference_Images` and their RunPod mirrors · Verify: hash-bound distinct-image manifest covers every v2 state/applicable class without synthetic positives or mandatory human anchors · Blocked by: MF-P1-10.07
- [ ] MF-P1-12.10 Record autonomous pilot latency, ambiguity/abstention outcomes, correction loops, and guideline changes before scale processing · Verify: signed pilot report links source hashes, authority records, decisions, timings, ambiguity outcomes, and SOP revision · Blocked by: MF-P1-12.09

## MF-P1-13 — Explicit truth tiers, package authority, and routing (spec: 20 §§1,5; 22 §5; SAM handoff Truth Tiers/Gates)
- [ ] MF-P1-13.01 Schema-validate distinct `human_anchor_gold`, `autonomous_certified_gold`, `weighted_pseudo_label`, and `machine_candidate` tiers · Verify: forbidden renames/collapses and unknown tiers fail · Blocked by: none · HARD BLOCKER
- [ ] MF-P1-13.02 Require any optional human anchors to declare train, calibration, or holdout partition and enforce image-disjoint identity/pHash groups · Verify: cross-partition leakage fixtures fail · Blocked by: MF-P1-13.01 · HARD BLOCKER
- [ ] MF-P1-13.03 Keep calibration/holdout anchors out of training, pseudo-label generation, model selection, threshold tuning, and certificate fitting as applicable · Verify: every forbidden reader path has a negative test · Blocked by: MF-P1-13.02 · HARD BLOCKER
- [ ] MF-P1-13.04 Bind autonomous-certified packages to an active unrevoked risk certificate, exact pipeline fingerprint, lifecycle sidecar, winner hash, and complete hard-QA result · Verify: missing/stale/mismatched evidence prevents finalization · Blocked by: MF-P4-11.10 · HARD BLOCKER
- [ ] MF-P1-13.05 Permit weighted pseudo-labels only in train partitions with configured reduced loss weight; never satisfy gold, volume, coverage, P5, D5, validation, or holdout gates · Verify: builder/gate negative fixtures pass · Blocked by: MF-P1-13.01
- [ ] MF-P1-13.06 Keep machine candidates non-authoritative and route only to repair or residual review · Verify: package/CVAT/serving paths cannot label them gold or certified · Blocked by: MF-P1-13.01
- [ ] MF-P1-13.07 Finalize certified packages atomically with immutable files map, provenance, certificate scope, truth tier, and audit eligibility · Verify: interruption/hash-drift tests leave no partially certified package · Blocked by: MF-P1-13.04
- [ ] MF-P1-13.08 Route certificate-covered instances to zero-routine-review output while sending residual cases and preselected audits to CVAT/batch panels · Verify: routing fixtures bind decisions to current certificate and fingerprint · Blocked by: MF-P4-11.10, MF-P4-11.13
- [ ] MF-P1-13.09 Preserve backward readers for historical human-gold and SAM2-era manifests without rewriting old provenance · Verify: compatibility fixtures load read-only and emit original authority/model identities · Blocked by: MF-P1-13.01
