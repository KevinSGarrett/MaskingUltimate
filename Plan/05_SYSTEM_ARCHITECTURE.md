# Document 05: System Architecture

---

## 1. Architecture Overview

```
                        ┌──────────────────────────────────────────────────────────┐
                        │                    ORCHESTRATOR (CLI)                    │
                        │   maskfactory <cmd> · SQLite state · configs\*.yaml      │
                        └───────┬──────────────────────────────────────────┬───────┘
 data\incoming\ ─► S00 Intake ─►│                                          │
                                ▼                                          ▼
        ┌── PERCEPTION LAYER (GPU, sequential model slots) ──┐   ┌── SERVING LAYER ──┐
        │ S01 Person det (RT-DETR/YOLO11)                    │   │ FastAPI infer svc │
        │ S02 Silhouette (BiRefNet)                          │   │ (P6) + ComfyUI    │
        │ S03 Human parsing (Sapiens-0.6B seg, SCHP fallbk)  │   │ node pack (doc13) │
        │ S04 Pose (DWPose 133kp) + MediaPipe hands          │   └───────────────────┘
        │ S05 Geometry engine (capsule priors per part)      │
        │ S06 Open-vocab assist (GroundingDINO — boxes only) │
        │ S07 SAM2.1 refinement (full + crop lanes)          │
        │ S08 Clothing/material parse                        │
        │ S0X Specialist lanes: hand · chest · hair · feet   │
        │     + DensePose 3D prior (doc 08)                  │
        └───────────────┬────────────────────────────────────┘
                        ▼
        ┌── FUSION & TRUTH LAYER ─────────────────────────────┐
        │ S09 Consensus + z-order fusion → PART & MATERIAL    │
        │     maps → binary export → derived unions           │
        └───────────────┬─────────────────────────────────────┘
                        ▼
        ┌── QA LAYER ─────────────────────────────────────────┐
        │ S10 Auto-QA battery (34 checks, doc 09)             │
        │ S11 VLM QA (local Qwen2.5-VL via Ollama, doc 10)    │
        └───────────────┬─────────────────────────────────────┘
                        ▼
        ┌── HUMAN LAYER ──────────────────────────────────────┐
        │ S12 CVAT (Docker) — SAM2 serverless interactor,     │
        │     correction & approval workflow (doc 11)         │
        └───────────────┬─────────────────────────────────────┘
                        ▼
        S13 Gold export/packaging ─► S14 Dataset build (DVC) ─► S15 Active learning
                        │                                            │
                        └────────────► TRAINING LAYER (doc 12) ◄─────┘
                              5 fine-tuned models → model_registry → back into S03/S07/S0X
```

**AMENDED (doc 17 §5):** the PERCEPTION → FUSION → QA → HUMAN chain above (S01–S13) runs once
per **promoted person instance**, not once per image. S01 now enumerates and ranks all detected
persons before handing off; a new S09.5 "Instance Reconciliation" step runs once per image, after
every promoted instance's own S09 completes, before any instance's S10 auto-QA begins. A
single-person image is the trivial N=1 case of this same loop. See doc 17 for the full
multi-instance architecture; nothing else in this diagram changes.

## 2. Deployment Topology (single machine, three runtimes)

| Runtime | What runs there | Why |
|---------|-----------------|-----|
| WSL2 Ubuntu 22.04, conda env `maskfactory` | All pipeline stages, training, CLI | Linux-only deps (detectron2/DensePose, mmcv) build cleanly; CUDA via WSL2 |
| Docker Desktop (WSL2 backend) | CVAT + Postgres/Redis + nuclio serverless SAM2 interactor + Ollama container | Isolated services, one `docker compose up` |
| Native Windows | ComfyUI + MaskFactory node pack; File Explorer access to `C:\Comfy_UI_Main_Masking\` | Kevin's existing ComfyUI stays untouched |

Shared filesystem: `C:\Comfy_UI_Main_Masking\` ≡ `/mnt/c/Comfy_UI_Main_Masking/` (WSL2) ≡ bind-mounts into containers. One tree, three views. GPU is shared; §5 defines the VRAM schedule.

## 3. Module Boundaries (`src\maskfactory\`)

```
maskfactory/
  cli.py                 # click-based: ingest|run|fuse|export-binaries|derive|derive-inpaint|
                         # qa|vlmqa|cvat push/pull|package|verify-package|dataset build|
                         # coverage report|train|leaderboard|reindex|gc
  orchestrator.py        # stage graph, retries, SQLite state, per-stage config hash stamping
  io/ (readers, writers, hashing, png_strict.py enforcing doc 03 §1)
  ontology.py            # loads ontology.yaml; the ONLY label authority in code
  stages/ s00_intake.py … s15_active_learning.py   (one file per stage, doc 07 contracts)
  lanes/ hand.py chest.py hair.py feet.py prior3d.py (doc 08)
  fusion/ consensus.py zorder.py mapbuild.py
  qa/ checks.py (QC-001…034) metrics.py panels.py topology.py
  vlm/ client.py prompts/ router.py
  cvat_bridge/ push.py pull.py labelmap.py
  datasets/ builder.py splits.py coverage.py cocorle.py
  training/ mask2former/ segformer/ handseg/ clothparse/ hairmatte/ leaderboard.py
  serve/ api.py comfy_export.py
  schemas/ *.schema.json
```

Rules: stages communicate only via files + manifest deltas (no in-memory coupling), every stage is
idempotent (re-run overwrites its own `work\` outputs), and any stage can be forced/skipped via
`pipeline.yaml` or `--stage` flags.

## 4. Consensus Engine (the referee — detail in doc 07 S09)

Inputs per part: Sapiens parsing region, SCHP region, geometry capsule, SAM2 mask, DensePose
surface patch, (hands) landmark polygons, (clothing lanes) material parse. Method:
1. Rasterize all sources to full res; compute pairwise IoU matrix.
2. `agreement = mean pairwise IoU of top-k sources` (k=3, weights in `pipeline.yaml`:
   sam2 0.40, sapiens 0.25, geometry 0.15, schp 0.10, densepose 0.10; hand lane overrides).
   A promoted auxiliary specialist may add a bounded 0.05 vote for its explicitly mapped label;
   it is optional evidence and does not reduce the governed base profile globally.
3. `agreement ≥ 0.85` → auto-accept draft (still human-approved later, but pre-marked "quick pass").
   `0.60–0.85` → normal review. `< 0.60` → flagged `model_disagreement_high`, red in CVAT,
   disagreement heatmap saved to `qa_panels\`.
4. Per-pixel fusion for the map = weighted vote with z-order arbitration (S09), never averaging
   (no soft edges enter the map).

## 5. GPU / VRAM Schedule (8 GB discipline)

- Exactly one heavyweight model resident at a time; orchestrator runs stages **model-major**
  (batch all images through S03, then all through S04, …) to avoid reload thrash.
- Budgets (fp16/bf16): RT-DETR 1.2 GB · BiRefNet 2.5 GB · Sapiens-0.6B-seg 3.5 GB ·
  DWPose(onnxruntime-gpu) 1.5 GB · SAM2.1-hiera-large 4.5 GB (base-plus 2.8 GB fallback auto-selected
  if OOM) · DensePose R50 2.2 GB · Qwen2.5-VL-7B-Q4 ≈ 6 GB (runs alone in its slot).
- Global guard: torch `set_per_process_memory_fraction(0.9)`, OOM → auto-retry at tile/half-size →
  fallback checkpoint → hard fail into failure queue. Long-image tiling at 1536 px tiles, 128 px overlap.
- Training slot (doc 12) claims the whole GPU; orchestrator refuses concurrent pipeline runs.

## 6. Concurrency, Logging, Errors

- CPU-parallel where GPU-free (hashing, PNG export, panels): process pool = physical cores − 2.
- Logging: loguru → `logs\maskfactory_<date>.log` + per-run JSON in `runs\<run_id>\run.json`;
  every stage logs config hash, model keys, durations, VRAM peak.
- Error policy: transient (OOM/IO) → 2 retries with backoff; semantic (QC fail) → route queues;
  fatal → image status `quarantined`, never blocks the batch.

## 7. Security & Privacy Posture

Local-only data plane; CVAT bound to 127.0.0.1; no telemetry from pipeline; cloud LLM calls
(text-only, doc 10 §6) behind a reconciled teacher-subsystem enablement flag; actual image
transmission remains default-deny and requires exact-hash/rights/provider authorization; secrets
(CVAT token) in `.env` (git-ignored) — never in configs or code.
