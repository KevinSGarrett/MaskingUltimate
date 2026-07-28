# ITEMS — Phase P6 Ontology-v2 and Provider-Neutral Serving (docs 18, 21, 22, SAM 3.1 handoff)

> **Completion-profile scope (doc 24):** exact completed provider-neutral interfaces may be reused by
> core only through explicit dependencies and the new release/adoption contracts. Legacy human-gold,
> CVAT, trained-champion, full-library, or interactive confirmation requirements do not carry into
> the autonomous bridge and cannot block or revoke `core_autonomous_runtime`.

Goal: expose exact ontology/provider/truth authority through serving, ComfyUI, and CVAT without rewriting legacy evidence.

## MF-P6-05 — Ontology-v2 registry, serving, and ComfyUI (spec: 18 checklist H)
- [ ] MF-P6-05.01 Store ontology version, exact 65-name vocabulary, vocabulary digest, and artifact hashes in every v2 model entry · Verify: promotion revalidates exact ordered vocabulary and hashes · Blocked by: MF-P1-10.09, MF-P0-16.03
- [ ] MF-P6-05.02 Reject v2 labels unless the loaded champion declares the exact v2 vocabulary · Verify: v1 rejects v2-only labels and reordered/incomplete v2 entries fail · Blocked by: MF-P6-05.01
- [ ] MF-P6-05.03 Expose ontology version and vocabulary identity through health, models, predict, and manifest-lite outputs · Verify: API integration tests assert consistent values · Blocked by: MF-P6-05.01
- [ ] MF-P6-05.04 Add canonical v2 labels/unions to ComfyUI selectors and package browser · Verify: dependency-light node tests load exact package masks/unions · Blocked by: MF-P1-10.04, MF-P1-10.05
- [ ] MF-P6-05.05 Canonicalize UI/API aliases and return requested/canonical provenance · Verify: atomic and union aliases route only to their correct loaders · Blocked by: MF-P1-10.04
- [ ] MF-P6-05.06 Add anatomy and clothed-negative workflow fixtures · Verify: shipped workflows are complete, registered, and exercised by tests · Blocked by: MF-P6-05.04
- [ ] MF-P6-05.07 Re-run latency/residency and Mode A/Mode B end-to-end tests · Verify: live evidence binds champion, ontology, runtime, input, output, latency, and VRAM hashes · Blocked by: v2 promoted champion and reviewed v2 package

## MF-P6-06 — Provider-neutral runtime, truth provenance, and safe CVAT publication (spec: 21 §8; 22 §§2–3; SAM handoff Required Surfaces)
- [ ] MF-P6-06.01 Resolve active serving providers by role/lifecycle through the governed registry; never hard-code SAM/model family names in new runtime paths · Verify: provider swap tests use contracts and retain legacy aliases · Blocked by: MF-P2-11.01, MF-P0-16.11
- [ ] MF-P6-06.02 Expose model/provider lifecycle, benchmark certificate, content/license eligibility, truth tier, certificate scope, and residual/audit reason in API/ComfyUI provenance · Verify: response schemas and redaction tests pass · Blocked by: MF-P0-16.06 through MF-P0-16.10, MF-P1-13.01
- [ ] MF-P6-06.03 Select SAM 3.1 first on the RunPod production route; retain SAM2.1 only as a typed bounded fallback/benchmark/rollback and local `pth-sam2` only as optional CVAT assistance · Verify: production selection rejects SAM2-first routes and fallback/rollback requires exact failure evidence · Blocked by: MF-P2-11.15
- [ ] MF-P6-06.04 Route certificate-covered outputs to certified serving metadata and residual/audit outputs to review surfaces without presenting machine truth as human gold · Verify: routing/metadata negative fixtures pass · Blocked by: MF-P1-13.08
- [ ] MF-P6-06.05 Publish autonomous repair only as `machine_generated_review_draft_non_gold`, refusing completed/accepted/frozen/gold or human-edited tasks · Verify: task-state/manual-shape negative fixtures pass · Blocked by: existing MF-P4-08.06 · HARD BLOCKER
- [ ] MF-P6-06.06 Back up raw CVAT annotations, replace only untouched automatic PART shapes, verify exact semantic shapes, and roll back immediately on mismatch · Verify: write/verify/rollback integration fixtures pass · Blocked by: existing MF-P4-08.06
- [ ] MF-P6-06.07 Complete parallel CVAT upgrade migration/rollback and verify SAM2/SAM3 assistance against preserved task data · Verify: live versioned smoke and rollback evidence pass · Blocked by: MF-P0-17.12 and installed SAM 3.1
- [ ] MF-P6-06.08 Run provider-neutral Mode B prediction/refine and Mode A package workflows on unseen single/multi-person inputs, measuring warm/cold latency, VRAM, OOM, determinism, provenance, and rollback · Verify: live evidence satisfies frozen performance contracts · Blocked by: promoted role champions and governed unseen sources
