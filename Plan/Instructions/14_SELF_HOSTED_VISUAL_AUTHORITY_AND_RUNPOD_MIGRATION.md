# 14 — Self-Hosted Visual Authority and RunPod Migration

Use this procedure with doc 25 whenever selecting a visual critic, approving
strict-VLM evidence, adding proposal/refinement providers, or reconciling
assets from AWS to RunPod.

## 1. Visual authority is earned, never named

1. Load critic roles from the governed registry/config. Do not infer authority
   from a model family, parameter count, download, or prior documentation.
2. Require a frozen, hash-bound calibration containing both valid masks and
   known defects. A reviewer that rejects every candidate is unavailable, not
   safe and not qualified.
3. Record positive-pass rate, defect recall, serious false-pass rate,
   abstention rate, schema compliance, latency, peak VRAM, runtime identity,
   prompt hash, and exact model artifact hashes.
4. Require the role-specific threshold and an independent-family juror where
   the route calls for one. Same-family variants do not create independence.
5. Deterministic format, topology, ownership, transform, provenance, and
   protected-region vetoes always run before critic arbitration and cannot be
   cleared by any model vote.
6. Legacy critics with the recorded zero-positive-pass result remain
   `VISUAL_CRITIC_BLOCKED` until a new frozen calibration proves otherwise.
7. For semantic role qualification, require real source pixels plus an exact
   real-source binding manifest. Use qualified labeled controls from
   `C:\Comfy_UI_Main\MaskedWarehouse` or exact qualified MaskFactory package
   bytes. Never use synthetic shapes, old draft packages, or rejected masks as
   valid semantic controls.
8. Use `F:\Reference_Images\Ultimate_Masking_Reference_Images` for real-image
   coverage, retrieval, benchmark, and hard-case selection. It supplies no
   mask truth by itself; pair it only with independently qualified masks when a
   labeled case is required.

## 2. Candidate generation and repair

1. Generate at least three genuinely different proposals when the required
   providers are available: concept/interactive segmentation, body-aware
   parsing/geometry, and silhouette/matting/refinement.
2. Normalize every proposal to exact source geometry and record provider,
   checkpoint, prompt, transform, source hash, and candidate hash.
3. Produce pairwise disagreement maps and per-region metrics before invoking a
   critic. Use them to target review and repair; do not average away ownership
   conflicts or deterministic failures.
4. Repair only the named label/ROI with a bounded plan. Recompose the complete
   map transactionally, rerun all hard QA, and keep the prior candidate for
   exact rollback.
5. A critic describes defects and bounded repair intent. It never authors
   authoritative pixels or expands its certificate scope.

## 3. RunPod execution and durability

1. Run workloads on the governed RunPod pod or its qualified successor, never
   on EC2.
2. Put models, datasets, caches, evidence, and resumable job state on the
   mounted persistent network volume. Treat the pod root overlay as ephemeral.
   The required corpus mirrors are `/workspace/assets/MaskedWarehouse` and
   `/workspace/assets/Reference_Images/Ultimate_Masking_Reference_Images`.
3. Before a long job, prove the mount identity, writable sentinel, free space,
   environment identity, GPU identity, output/checkpoint destination, and both required corpus
   roots. Use `tools\verify_runpod_persistence.py` plus
   `tools\verify_runpod_corpus_mirrors.py`; never rely on a chat statement that the assets were
   copied.
4. Resume from hash-verified checkpoints after interruption. Never relabel a
   partial download, interrupted transfer, or root-overlay file as durable.
5. A multi-GPU critic role requires a separately measured deployment; it does
   not become available merely because the model is cataloged.
6. SharedRunPodCoordinator v2 is the exclusive cross-project GPU admission
   authority. Before any new GPU work, request and validate a capacity lease,
   heartbeat it while the owned workload runs, and release it afterward.
   CPU-only work needs no lease. `runs/gpu.lock` remains internal to
   MaskFactory and cannot veto unrelated ComfyUI work. Never remove another
   project's lock, kill its process, steal its lease, or exceed the granted
   reservation; use cooperative yield when qualified peaks do not fit.

## 4. Read-only AWS inventory and governed migration

1. AWS access is inventory-only for this project: enumerate known EC2/EBS/AMI
   and S3 assets, sizes, timestamps, hashes/ETags where meaningful, and source
   lineage. Do not start instances, create volumes, mutate buckets, or execute
   MaskFactory workloads there.
2. Compare every discovered asset with the persistent RunPod inventory by
   semantic role, exact version, size, integrity evidence, license/allowed use,
   and existing local substitute.
3. Create a migration row only for a necessary, non-duplicate, lawfully usable
   asset. Record source URI, destination, expected bytes, expected hashes,
   transfer command, resumability, and rollback/cleanup plan.
4. Chunked transfers are incomplete until a sealed completion manifest proves
   the exact part count, total bytes, ordered hashes, successful assembly, and
   final artifact hash. A probe file or partial prefix is not completion.
5. Validate on RunPod before activation. Migration does not grant provider,
   benchmark, training, gold, or production authority.

## 5. Evidence and tracker discipline

- Store dated inventories, calibration reports, transfer manifests, and live
  smokes under `qa/live_verification/` or the governing evidence path.
- Include exact input/config/code/model/output hashes and distinguish planned,
  installed, benchmarked, promoted, blocked, and unavailable states.
- Update Items metadata only for a deliberate plan amendment. Update live item
  status only through `Plan/Tracker/tracker.py` with real evidence.
- Never close a runtime, migration, critic, or authority item from this
  instruction or a planning document alone.
