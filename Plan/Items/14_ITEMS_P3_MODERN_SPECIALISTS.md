# ITEMS — Phase P3 Modern Specialist Challenger Lanes (SAM 3.1 handoff)

> **Completion-profile scope (doc 24):** these specialist and comparative-benchmark rows are not a
> full-library prerequisite for core. Exact completed runtime-contract evidence may be reused by an
> eligible route; human-anchor benchmarks qualify only optional independent-accuracy claims. An
> absent/unqualified specialist is filtered out or produces typed abstention and cannot block or revoke
> `core_autonomous_runtime`.

Goal: make each specialist family a measurable, reversible challenger rather than an assumed upgrade.

## MF-P3-08 — Modern specialist integration and role-specific evidence (spec: SAM handoff Retained Providers/Benchmark Matrix)
- [ ] MF-P3-08.01 Add SAM 3.1 discovery/refinement candidates to hand/finger, chest/pelvic, hair, feet/toes, clothing, accessory, and repeated-instance lanes · Verify: each lane emits isolated strict candidates with exact provenance · Blocked by: MF-P2-11.03, MF-P2-11.04
- [ ] MF-P3-08.02 Evaluate SAM3-LiteText only as an optional lower-memory experiment and never a substitute for official SAM 3.1 · Verify: registry state/role tests prevent silent substitution · Blocked by: governed optional installation
- [ ] MF-P3-08.03 Benchmark BiRefNet Dynamic/HR/HR-matting against BiRefNet-general and ViTMatte for silhouette, hair edge, and matting roles · Verify: frozen role-specific metrics include boundary quality, leakage, latency, VRAM, and determinism · Blocked by: MF-P2-11.08 and human-anchor holdout
- [ ] MF-P3-08.04 Benchmark RTMW-X/RTMO against DWPose for whole-body, hands/feet, rear, contact, occlusion, and crowded scenes · Verify: per-joint/side/context metrics and fallback evidence are complete · Blocked by: MF-P2-11.06 and human-anchor holdout
- [ ] MF-P3-08.05 Benchmark SAM 3D Body against DensePose for geometry priors, contact/occlusion, rear/front, and multi-person identity · Verify: geometry-to-image consistency, bleed, side, latency, and OOM metrics are complete · Blocked by: MF-P2-11.07 and human-anchor holdout
- [ ] MF-P3-08.06 Keep MediaPipe Hands as an independent handedness/landmark vote and measure its incremental value · Verify: vote-ablation benchmark and side-swap fixtures pass · Blocked by: human-anchor hand set
- [ ] MF-P3-08.07 Preserve specialist outputs as independent provenance-bearing tournament candidates rather than collapsing correlated variants into one independent-source count · Verify: source-family deduplication tests pass · Blocked by: MF-P4-11.03
- [ ] MF-P3-08.08 Define role-specific non-inferiority margins for every hard specialist class/context before opening benchmark results · Verify: frozen benchmark manifest contains margins and cannot be edited post-results · Blocked by: MF-P2-11.13
- [ ] MF-P3-08.09 Promote no specialist from model card/download/smoke alone; require measured winner, complete license/content/runtime hashes, reliable 8 GB operation or approved alternate runtime, and rollback · Verify: promotion negative fixtures reject every missing prerequisite · Blocked by: MF-P0-16.11, MF-P3-08.08 · HARD BLOCKER
- [ ] MF-P3-08.10 Publish specialist overlays, disagreements, correction-pixel deltas, and review-time impact to the leaderboard/evidence package · Verify: evidence schema and frozen benchmark report cover every enabled lane · Blocked by: MF-P3-08.03 through MF-P3-08.06
