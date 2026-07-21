# ITEMS — Phase P2 Ontology-v2 Drafting and Provider Modernization (docs 18, 22, SAM 3.1 handoff)

> **Completion-profile scope (doc 24):** an exact completed provider-contract row may be reused when
> explicitly named by the core dependency closure. Human-anchor comparisons, full challenger-library
> availability, and independent performance claims remain optional evidence and cannot block or
> revoke `core_autonomous_runtime`; unavailable providers cause route removal or typed abstention.

Goal: integrate modern challengers through provider-neutral contracts and shadow evidence before any role promotion.

## MF-P2-10 — Ontology-v2 drafting and fusion (spec: 18 checklist E)
- [ ] MF-P2-10.01 Add anatomy crop proposals without asserting hidden anatomy · Verify: proposals remain bounded priors and cannot become visible truth directly · Blocked by: MF-P1-10.07
- [ ] MF-P2-10.02 Add canonical open-vocabulary prompts governed only by ontology, source, and provider contracts · Verify: canonical prompt/provenance tests pass · Blocked by: MF-P1-10.04
- [ ] MF-P2-10.03 Route prompts through segmentation/fusion so detector boxes never become final masks directly · Verify: authority-boundary tests reject direct box-to-map writes · Blocked by: MF-P2-10.01
- [ ] MF-P2-10.04 Add same-side chest and pelvic geometry priors · Verify: character-perspective and midline fixtures pass · Blocked by: MF-P1-10.03
- [ ] MF-P2-10.05 Enforce breast and pelvic carve-outs before PART-map write · Verify: exclusivity/derived-surface identity tests pass · Blocked by: MF-P1-10.02, MF-P1-10.05
- [ ] MF-P2-10.06 Preserve ambiguity and clothing occlusion instead of forcing candidates · Verify: uncertain/covered fixtures remain nonpositive with ignore/null authority · Blocked by: MF-P1-11.02
- [ ] MF-P2-10.07 Produce v2 panels, provenance, confidence, and correction instructions · Verify: evidence bundles bind exact source/candidate/map hashes · Blocked by: MF-P2-10.03
- [ ] MF-P2-10.08 Test exposed, clothed, partial, distant, hair-occluded, side-view, and cropped fixtures · Verify: focused suite covers each named context and all hard QCs · Blocked by: MF-P2-10.01 through MF-P2-10.07

## MF-P2-11 — Provider-neutral discovery, segmentation, pose, and geometry architecture (spec: SAM handoff Provider-Neutral Architecture/Benchmark Matrix)
- [ ] MF-P2-11.01 Define versioned `PersonDetector`, `ConceptDetector`, `InteractiveSegmenter`, `GeometryProvider`, `PoseProvider`, `SilhouetteProvider`, and `VlmReviewer` contracts · Verify: conformance tests exercise incumbent and fake challenger implementations · Blocked by: none
- [ ] MF-P2-11.02 Add compatibility adapters for legacy SAM2 identifiers/manifests without mechanically renaming historical evidence · Verify: old manifests load with original provenance and new providers emit canonical contract metadata · Blocked by: MF-P2-11.01
- [ ] MF-P2-11.03 Integrate SAM 3.1 concept/text/exemplar discovery as a provenance-preserving shadow candidate source · Verify: installed artifact produces strict candidate evidence without changing active maps · Blocked by: MF-P0-17.04, MF-P2-11.01
- [ ] MF-P2-11.04 Integrate SAM 3.1 point/box/mask refinement and repair proposals behind `InteractiveSegmenter` · Verify: prompt polarity, geometry, strict PNG, hash, and containment tests pass · Blocked by: MF-P0-17.04, MF-P2-11.01
- [ ] MF-P2-11.05 Integrate RF-DETR person detection challenger behind `PersonDetector` while retaining YOLO11 incumbent/rollback · Verify: frozen detection comparison and role-switch rollback pass · Blocked by: governed RF-DETR installation
- [ ] MF-P2-11.06 Integrate RTMW-X whole-body and RTMO crowded-scene pose challengers behind `PoseProvider`, retaining DWPose/MediaPipe votes · Verify: exact joint vocabulary, character-side assignment, crowded-scene, and fallback tests pass · Blocked by: governed pose installations
- [ ] MF-P2-11.07 Integrate SAM 3D Body behind `GeometryProvider` while retaining DensePose fallback · Verify: coordinate/frame/identity mapping, OOM fallback, and provenance tests pass · Blocked by: governed SAM 3D Body installation
- [ ] MF-P2-11.08 Integrate BiRefNet Dynamic/HR/HR-matting behind `SilhouetteProvider` without displacing incumbents · Verify: strict-mask/matting outputs and fallback selection pass · Blocked by: governed BiRefNet variant installations
- [ ] MF-P2-11.09 Integrate Qwen3-VL challengers behind `VlmReviewer` in shadow mode while retaining Qwen2.5-VL · Verify: strict verdict schema, VRAM/latency, fallback, and model identity tests pass · Blocked by: governed Qwen3-VL installations
- [ ] MF-P2-11.10 Integrate EoMT/DINOv3 as a trainable challenger contract while retaining SegFormer/Mask2Former baselines · Verify: exact ontology vocabulary, checkpoint/config hashes, and isolated runtime contract pass · Blocked by: governed EoMT/DINOv3 environment
- [ ] MF-P2-11.11 Preserve original local GroundingDINO fallback and prohibit paid hosted substitution in the offline role · Verify: provider selection tests fail hosted-only configuration for the local fallback role · Blocked by: MF-P0-17.11
- [ ] MF-P2-11.12 Wire every challenger only into shadow tournaments until a current benchmark certificate and lifecycle promotion exist · Verify: planned/installed providers cannot own active roles · Blocked by: MF-P0-16.06, MF-P0-16.11 · HARD BLOCKER
- [ ] MF-P2-11.13 Build the frozen SAM/provider benchmark matrix covering SAM2.1, SAM3.1, hybrid discovery/refinement, RF-DETR routes, SAM 3D Body, BiRefNet, and pose variants · Verify: identical images/prompts/hardware/QA/truth and immutable matrix manifest · Blocked by: required challenger installations and human-anchor holdout
- [ ] MF-P2-11.14 Measure per-label IoU, boundary-F, small-part/instance recall, bleed, side/front-back errors, anatomy/clothing confusion, hallucinations, QA failures, correction pixels, audit time, VRAM, latency, crash/OOM, and determinism · Verify: every matrix row has complete finite metrics and artifact hashes · Blocked by: MF-P2-11.13
- [ ] MF-P2-11.15 Promote winners by role only after primary win/labor reduction plus every hard-label/high-risk non-inferiority margin, then prove one-command rollback · Verify: signed benchmark certificate and rollback evidence pass governance · Blocked by: MF-P2-11.14, MF-P5-10.09 · HARD BLOCKER
- [ ] MF-P2-11.16 Integrate SAM2Matting as a boundary/matting challenger without granting semantic-label authority · Verify: strict alpha/mask geometry, provenance, fallback, and boundary fixtures pass · Blocked by: MF-P2-11.01 and governed installation
- [ ] MF-P2-11.17 Integrate MatAnyone2 as a temporal/image-refinement challenger only where its exact contract applies · Verify: static-image and temporal capability tests prevent unsupported route selection and preserve rollback · Blocked by: MF-P2-11.01 and governed installation
- [ ] MF-P2-11.18 Integrate PDFNet or its qualified equivalent as an independent fine-boundary challenger · Verify: exact checkpoint/runtime evidence and boundary-focused fixtures pass without truth promotion · Blocked by: MF-P2-11.01 and governed installation
- [ ] MF-P2-11.19 Require at least three genuinely different proposal families for high-risk autonomous routes when available, with typed route removal/abstention when diversity is unavailable · Verify: correlated variants cannot satisfy the proposal-family count · Blocked by: MF-P2-11.01, MF-P2-11.12
- [ ] MF-P2-11.20 Produce pairwise disagreement maps and per-region metrics after exact-geometry normalization · Verify: known overlap, omission, ownership, and boundary disagreements localize to expected pixels and bind every candidate hash · Blocked by: MF-P2-11.19
- [ ] MF-P2-11.21 Define exact target contracts for label, instance, visible extent, exclusions, protected regions, source geometry, and transforms before criticism or repair · Verify: missing/ambiguous target fields fail closed before any critic call · Blocked by: MF-P2-11.01
- [ ] MF-P2-11.22 Execute bounded ROI/label repair from disagreement and critic plans, transactionally recompose the complete map, rerun hard QA, and retain exact rollback · Verify: success, no-progress, cap, hard-fail, and rollback fixtures pass · Blocked by: MF-P2-11.20, MF-P2-11.21, MF-P4-11.22
