# Document 01: Project Charter & Scope
**MaskFactory — Ultimate Masking System** | Blueprint v1.0.0 | Active ontology `body_parts_v1`; approved inactive target `body_parts_v2` (doc 18)

---

## 1. Mission Statement

Build a local, production-grade **autonomous mask authority** that converts source character images
into complete, pixel-accurate, per-body-part binary segmentation masks—with honest handling of
clothing, occlusion, hidden anatomy, uncertainty, and abstention—then certifies exact eligible outputs
for MaskFactory-to-ComfyUI production use. Independent human-authored accuracy measurement, large-
corpus training, and DAZ expansion remain valuable but separately scoped optional maturity profiles.

## 2. Why It Exists (Problem Statement)

- Generic tools (raw SAM, ComfyUI segmentation nodes, VLM-drawn masks) produce inconsistent,
  non-reproducible, anatomically confused masks: wrong left/right, finger merging, breast/clothing
  boundary bleed, hair fuzz, masks that "see through" clothing, and silent format drift.
- Inpainting quality in ComfyUI is capped by mask quality. Precise, semantically-correct,
  visible-pixel-only masks with clean derived edit regions are the single highest-leverage input.
- No off-the-shelf model matches either governed vocabulary (active v1: 56 PART IDs including
  background; approved inactive v2: 65, doc 18, with per-finger/per-toe regions, joint bands,
  breast/chest and visible-anatomy carve-outs, and back regions) — so the system must manufacture its own
  training data and fine-tune its own models.

## 3. Goals (Measurable)

The goals below are legacy portfolio/research measurements. They do not collectively define core
completion. Doc 24 and `completion_track_registry.json` are authoritative: operational core is required;
independent real accuracy and scale/DAZ maturity are non-blocking profiles.

| ID | Goal | Metric | Target |
|----|------|--------|--------|
| G1 | Gold factory throughput | Human minutes per fully-approved image (all visible parts) | ≤ 25 min by end P3, ≤ 12 min by end P5 |
| G2 | Draft quality | Mean per-part IoU of auto-drafts vs gold (test holdout) | ≥ 0.85 body, ≥ 0.70 fingers/toes |
| G3 | Boundary quality | Boundary F-score @2px tolerance | ≥ 0.80 body, ≥ 0.65 fingers/hair |
| G4 | Format integrity | Gold packages passing all format checks | 100% (hard gate) |
| G5 | Left/right correctness | L/R swaps in approved gold | 0 (hard gate via QC-014 + review) |
| G6 | Dataset scale | Human-approved gold packages | 300 minimum, 500 target |
| G7 | Custom model win | Fine-tuned model beats draft pipeline on leaderboard | Yes, on frozen holdout |
| G8 | Reproducibility | Rebuild env + rerun pipeline → byte-identical label maps on same inputs | Yes (seeded) |
| G9 | Multi-person correctness | Cross-instance mask bleed rate in approved multi-person gold (doc 17) | 0 (hard gate via QC-035/036 + review) |

## 4. In Scope

1. **Multi-instance masking per image (doc 17):** every sufficiently-prominent person (2 to
   `max_instances_per_image`, default 4) is promoted to its own fully-masked instance — not just
   one primary subject. Non-promoted or non-target people are the `other_person` protected class,
   scoped per-instance (doc 02, doc 17 §6). A single-person image is the trivial N=1 case of this
   same scheme; nothing about the single-person build (docs 02–15, Items 01–08) changes.
2. Full atomic ontology (doc 02): 56 exclusive atomic parts + band regions + conditional classes + material/clothing layer + projected/amodal regions + protected QA classes + derived unions.
3. End-to-end pipeline: intake → detection → parsing → pose → geometry priors → refinement → clothing parse → fusion/panoptic resolution → hard QA → independent critics → bounded repair → autonomous certificate or abstention → MaskFactory bridge → ComfyUI serving. CVAT review, dataset packaging, active learning, and fine-tuning are optional profile lanes rather than core-runtime dependencies.
4. Specialist lanes: hands/fingers, chest/breast/clothing boundary, hair/face, feet/toes, 3D body prior sanity checks.
5. Local-first execution on the RTX 5060 laptop (8 GB VRAM), with optional AWS burst training (accounts already exist: prod 277361136276 / dev 548846591581).
6. Full reproducibility, hashing, versioning (git + DVC), and operations runbook.

## 5. Out of Scope (v1)

- Video segmentation/tracking (SAM2 supports it; deferred to v2 — architecture leaves the door open).
- Real-time (<1s) inference; v1 batch/interactive latency targets are seconds-per-image.
- Dense crowd scenes: images with more than `crowd_scene_threshold` (default 8) total detected
  people are quarantined as out of scope rather than partially processed (doc 17 §2, §4) — a
  distinct, larger economics problem from the 2–4 person case, which **is** in scope (see §4.1).
- Automatic identity/face recognition of any kind (never in scope).
- Cloud annotation crowdsourcing (all review is local/owner-controlled).

## 6. Design Principles

P1. **Honesty over coverage** — the system never claims to see what is not visible. Visible truth,
    projected regions, and amodal estimates are three different, separately-stored things.
P2. **Models propose, policy decides, checks enforce** — LLMs/VLMs may diagnose, route, and critique,
    but cannot waive hard checks, issue authority, or self-promote. The autonomous policy may certify
    only exact evidence-bound outputs or abstain. Human-authored truth remains independent accuracy
    authority when that optional profile is exercised.
P3. **Every correction is fuel** — all human edits enter the active-learning queue and coverage matrix.
P4. **Specialists beat generalists** — hard regions (fingers, chest boundary, hair) get their own
    crops, models, metrics, and review panels.
P5. **Exclusive-by-construction** — one master PART map + one MATERIAL map per image make overlap
    bugs structurally impossible; binary PNGs are generated views of the maps.
P6. **Config over code** — thresholds, band widths, dilation radii, model choices live in YAML.
P7. **Fail loud, abstain smart** — core ambiguity becomes a typed autonomous abstention/quarantine,
    never a silent guess. A prioritized human task exists only when the optional human-review profile
    is explicitly enabled.

## 7. Data Governance & Source Policy (Mandatory)

- Permitted sources: images Kevin owns or generated (ComfyUI outputs), licensed stock, or images
  collected with documented permission. `manifest.source_origin` records provenance
  for every image (`generated | owned_photo | licensed | consented_subject`).
- Every source follows the same provenance, rights, integrity, annotation, and QA path.
  Foundational platform safety remains external to this project-specific admission contract.
- No processing of real identifiable people without consent; the system is built for
  owned/generated character imagery.
- Projected/amodal regions are geometric edit regions for compositing/inpainting of owned content —
  they are explicitly not "x-ray" claims and are never exported as visible-anatomy truth.
- All data stays local (`C:\Comfy_UI_Main_Masking\data\`); cloud LLMs never receive source images
  (doc 10 §6), only non-sensitive text manifests when policy allows.

## 8. Stakeholders & Roles

| Role | Who | Responsibility |
|------|-----|----------------|
| Owner / Architect | Kevin | Decisions, approvals, gold review authority |
| Builder | AI coding agent (Claude/Cursor) executing doc 14 | Implementation |
| Annotator/Reviewer | Kevin (v1), optionally Quatavius (QA) later | CVAT correction & approval |
| Second reviewer | Kevin on 15% sample (different day) or Quatavius | Spot-check hard classes |

## 9. Constraints & Assumptions

- GPU: RTX 5060 Laptop, 8 GB VRAM, Blackwell sm_120 → PyTorch ≥ 2.7 + CUDA 12.8 wheels mandatory (doc 06).
- OS: Windows 11 + WSL2 Ubuntu 22.04 + Docker Desktop (CVAT + serverless SAM2 run in Docker; pipeline runs in WSL2 conda env; ComfyUI stays native Windows).
- Disk: reserve ≥ 500 GB on C: or move `data\` to a larger drive via junction (runbook §4).
- Single-machine v1; architecture allows moving CVAT or training to AWS later without redesign.
- 8 GB VRAM drives all model size choices (doc 06 §3) — every selected checkpoint fits in fp16/bf16 or 4-bit.

## 10. Success Criteria

Required system completion is `core_autonomous_runtime` in doc 24: human-free autonomous generation,
hard QA, independent critics, bounded repair, abstention, exact-output certification, revocation,
recovery, and adopted single-/multi-person ComfyUI integration all pass with hash-bound evidence.

The historical D1–D11/headline tests remain profile-scoped portfolio evidence. The 20-image
human-approved/blinded test supports `independent_real_accuracy`; 200/300/500-package, training,
full-library, DAZ, and soak targets support `scale_daz_maturity`. Neither is a prerequisite for core.
