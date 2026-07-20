# Autonomous Session Handoff — 2026-07-19 (rev: disk relocation + doctor climb)

Fully autonomous continuation. **No Kevin/human blockers.** Every former "Kevin action" is
reclassified into an agent-executable path in `qa/live_verification/needs_agent_actions_20260719.json`.
**Do not claim project complete. Preserve all work. No governed wipe. No tier inflation.**

## Latest wave (2026-07-20 17:19 UTC — GOLD FACTORY tournament --emit MVC climb)

Stream: **cursor-grok-4.5-high-fast** GOLD FACTORY. Docker CLI healthy.

- **This-wave emit:** prove-emit×24 + `tournament --emit`×16 → MVC **75→123** (+48).
- **Sealed pool (parallel siblings also emitting):** MVC≈**448**, gold=**0**, champions=**{}**.
- **Wilson:** binding n=598 (exact_zero_failure_serious); gap≈**154**; admission still `insufficient_autonomous_verified_samples`.
- **GPU:** batch-B multiprovider holds `runs/gpu.lock`; Ollama stopped to reclaim VRAM; no lock steal.
- **Evidence:** `qa/live_verification/gold_factory_tournament_emit_mvc_climb_20260720T1716.json` (self_sha256 `78cc0e80…`).
- **Next:** keep emitting genuine MVC until ≥598; visual+VLM critic on real multiprovider FP; admission `--corpus`.

## Latest wave (2026-07-20 09:57 UTC — ≥3 mask families ONLINE via local CUDA + gold admission re-drive)

Stream scope: **families-online + gold admission** (coordinated with siblings; left Docker VHD migrate / Dockerfile.train / isolated-consumer edits untouched).

- **Families ONLINE = 3 (gate cleared):** aceparse_bisenet, irefnet_general, schp_atr all produced live CUDA masks via C:/Comfy_UI_Main/ComfyUI/.venv torch **2.11.0+cu128** (RTX 5060). faceparse matched registry smoke SHA 8c3235e1…. BiRefNet used Windows-safe weight copy (symlink privilege blocked). SCHP ATR revision eb84c432…. GPU-sequenced after ollama stop.
- **Gold admission — honest insufficient:** uild_autonomous_gold_admission → insufficient_autonomous_verified_samples (machine_verified_candidate=0). Gold-volume roots **present** (MaskedWarehouse / reference / DAZ). champions=0; no fabrication.
- **Docker:** engine DOWN at seal (Desktop churn / sibling VHD migrate); nuclio SAM2 not counted this wave.
- **Evidence:** qa/live_verification/families_online_gold_drive_20260720T0957.json (self_sha256 859b5d1e…); admission …/autonomous_gold_admission_families_online_20260720T0957.json.
- **Next:** sequenced ≥3-family tournament on gold-volume images → real 
uns/ sidecars → admission --corpus.



## Latest wave (2026-07-20 09:36 UTC — Docker-GPU declared SOLE CUDA train/serve path; WSL repair DEFERRED)

HEAD `eb17dd21` at authoring (branch churned by parallel siblings since). Docs/evidence-only stream; this
stream's durable record is the immutable seal below (siblings rewrite the handoff/queue live). **Zero human blockers.**

- **Decision — Docker-GPU is the SOLE local CUDA train/serve runtime; WSL Ubuntu-22.04 repair DEFERRED.**
  WSL repair is genuinely blocked (this shell is **non-admin** — the scripted elevated e2fsck /
  `tools/Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair` would raise an interactive UAC prompt = a human wait
  state) and the on-disk `Ubuntu-22.04` ext4 VHD is corrupt (`wsl -d Ubuntu-22.04 -- /bin/true` → Error
  code 6 / E_FAIL). Deferred without blocking any train/serve lane; it only gates the WSL-specific live
  SAM 3.1 CUDA smoke (MF-P2-11.07). (`F:` is a **removable/flapping** USB drive — present at this wave's
  probe at 181.2 GiB but recorded physically absent by a sibling minutes earlier; the Docker-GPU path is
  C:-resident and **F:-independent**, so neither the WSL repair nor F: availability blocks train/serve.)
- **GPU passthrough — live-proven this wave (`RUNTIME_PASS_BOUNDED`).** `docker run --rm --gpus all
  nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi …` enumerated **RTX 5060 Laptop GPU, driver 592.01,
  8151 MiB total / ~1247 MiB free** (VRAM tight; a cosmetic `unexpected EOF` raced container teardown
  *after* the query row printed — not a passthrough failure).
- **Serve/train build paths — Ubuntu-22.04(WSL)-INDEPENDENT + STATIC-coherent.** Both governed contract
  suites re-ran **STATIC_PASS**: `docker_serve_contract_static_20260720T093557Z.json` (`dsc_e651e9b9…`;
  `base_is_slim_python_not_cuda_devel`, `torch_cu128_index_used`, `no_wsl_only_editable_git_or_file_deps`)
  and `docker_train_contract_static_20260720T093557Z.json` (`dtc_c652d774…`). `Dockerfile.serve` =
  `python:3.11-slim` + torch cu128 wheels (needs only the host NVIDIA driver via `--gpus all`);
  `Dockerfile.train` = `nvidia/cuda:12.8.0-devel-ubuntu22.04` **Docker Hub** base (container OS, independent
  of the corrupt local WSL Ubuntu-22.04 ext4 VHD). Neither depends on the WSL Ubuntu distro.
- **Heavy image builds — deliberately DEFERRED out-of-band (not run).** Per
  `Plan/DOCKER_RUNTIME_AND_SESSION_USE.md` §6b build-safety: the ~7 GiB serve torch pull + from-source
  sm_120 nvcc train compile have crashed the constrained WSL2 daemon before; with ~37 containers live the
  builds are deferred to protect the running production CVAT stack. This wave establishes build-path
  **viability** (Ubuntu-independent + STATIC-green + GPU present), not build success.
- **No tier inflation.** champions=0, gold=0, no torch-CUDA-in-container, no containerized serve/train green.
  `needs_agent_actions_20260720.json` carries `wsl_repair_disposition=DEFERRED_NON_ADMIN_DOCKER_GPU_IS_SOLE_CUDA_PATH`,
  `docker_gpu_evidence` → this wave's seal, and Docker-GPU serve/train as leading build priorities.
- **Evidence (durable, this stream owns it):**
  `qa/live_verification/docker_gpu_sole_cuda_path_wsl_deferred_20260720.json` (self_sha256 `ca82795a…`);
  serve/train STATIC contracts above; OPS_LOG 14:36 UTC entry.

## Latest wave (2026-07-20 14:48 UTC — gold-volume path map read-when-present; no USB junction)

- **Correction:** Sibling "MaskedWarehouse/reference/DAZ not on disk" was working-tree-scoped. With F:
  present (USB Seagate), live probe selected all three tournament-input roots:
  `C:\Comfy_UI_Main\MaskedWarehouse`, `F:\Reference_Images\Ultimate_Masking_Reference_Images`,
  `F:\DAZ`.
- **Wiring:** `configs/gold_volume_sources.yaml` + `src/maskfactory/autonomy/gold_volume_sources.py`;
  admission driver records `tournament_input_roots`; multi-person slices default via
  `default_maskedwarehouse_lv_mhp_root()`. Read-when-present only — **no** junction of `data/` /
  models / Docker VHDX onto USB (`data/` stays on C: backup).
- **Evidence:** `qa/live_verification/gold_volume_path_map_20260720T1448Z.json`
  (self_sha256 `a43ce08e…`). Tests: `tests/test_gold_volume_sources.py` 5/5. No tier inflation.

## Latest wave (2026-07-20 — tracker/evidence-hygiene sweep under multi-agent parallel execution)

Stream scope: **tracker + evidence hygiene only** (no feature work). Multi-agent parallel execution is
active — sibling agents hold uncommitted source edits in the shared working tree
(`docker/Dockerfile.train`, `docker/compose.gpu.yml`, `tools/run_isolated_main_consumer.py`), are
concurrently editing this handoff, and performed the sibling `c50abb3a` Docker Desktop restore. This
stream committed **only** its own tracker-report/handoff/OPS_LOG/seal files and left all sibling
in-flight edits unstaged and untouched.

- **Sweep result: 0 honest status transitions.** Scanned 233 unresolved items (135
  open/in_progress/partially_complete/failed + 98 blocked). Every remaining unfinished item is gated on
  live/GPU/WSL/human-CVAT/Main-adoption/DAZ-Studio/gold evidence **not present on disk**. All 291 sealed
  `STATIC_PASS`/`RUNTIME_PASS_BOUNDED` artifacts were already fully reflected by prior parallel waves; a
  per-open-item grep found **no** un-applied sealed evidence, and `residual_blocker_inventory_20260719.json`
  independently asserts `any_item_completed_by_this_inventory=false`.
- **Honesty:** STATIC binders add STATIC_PASS surfaces only; they do not advance AWAITING_MAIN or
  champions. No item was marked complete/not_applicable on weak proof — **zero transitions is the honest
  outcome.** core_autonomous_runtime stays **blocked** (champions=0; P6-11/12 AWAITING_MAIN; HARD
  MF-P6-11.02/11.07/12.05). Portfolio unchanged at **565/798 (70.8%)**.
- **Hygiene applied:** `tracker.py report` regenerated `DASHBOARD.md` + `phases/*.md` (resyncing the
  markdown to sibling-authored tracker.json notes, e.g. P6); `tracker.py validate` PASS (798 items, 0
  structural problems, 19 hard-blockers unresolved). `needs_agent_actions_20260719.json` refreshed with a
  `parallel_execution_reconcile` block and re-sealed.
- **Evidence:** `qa/live_verification/tracker_evidence_hygiene_sweep_20260720.json`
  (self_sha256 `a952582e…`); queue self_sha256 `bce2fcde…`.

## Latest wave (2026-07-20 07:20 UTC — disk-safe reclaim + Docker RUNTIME_BLOCKED + host-path climb)

HEAD `447b0f9b`. Live re-probe: Docker engine **down/unstable**; Ollama 0.32.1 (host) UP; CVAT down.

- **Disk (item 1) — ephemeral reclaim DONE, no governed wipe:** cleared pip/uv/npm-cache/torch caches + user
  Temp → **+11.11 GiB** (C: 17.18 → 28.29 GiB; now ~29.15 GiB). F: 249.42 GiB free. HuggingFace weights (~3.3
  GiB), `models/`, `MaskedWarehouse`, `data/` (F: junction), Docker volumes / `docker_data.vhdx`, CVAT v2.24
  data all **untouched**. `docker builder prune` **not run** (engine went down before a bounded CLI call
  completed).
- **Docker engine — RUNTIME_BLOCKED (honest):** relaunch → `docker version`/`ps` timed out >40s; a clean
  `wsl --shutdown` restart brought the distro up but `docker ps` returned **500 Internal Server Error** on
  `/containers/json`, then the **named pipe vanished** (daemon crashed while recovering the **68.11 GiB
  `docker_data.vhdx`** with only ~29 GiB free on C:). Stopped restarting to protect the engine (mandate). No
  prune / volume wipe / factory reset. **Repair next:** free C: to ≥75 GiB, OR relocate Docker Desktop "Disk
  image location" to F: (admin-free GUI migration preserves CVAT volumes; do NOT blind-edit
  settings-store.json), OR elevated `wsl --shutdown` + `Optimize-VHD`/`diskpart compact` + `e2fsck` of
  `docker_data.vhdx`.
- **Serve image (item 2) — NOT built:** `maskfactory/serve:cu128` build aborted; engine unhealthy and the
  ~7 GiB torch cu128 install would risk another recovery crash. Smoke NOT_RUN. Still `AWAITING_RUNTIME`.
- **Autonomous-gold (item 3) — honest insufficient:** `build_autonomous_gold_admission.py` →
  **`insufficient_autonomous_verified_samples`** (0 `machine_verified_candidate`). The certificate needs
  ~≥300 real machine-verified sidecars per risk bucket (one-sided Wilson ≤0.01, exact zero-failure ≤0.005),
  each anchored to a ≥3 independent-family tournament winner in `runs/`; none exist and none can be
  fabricated. Requires a working multi-provider GPU tournament runtime (Docker down this wave).
- **Main (item 4) — isolated consumer real-run 6/6 PASS:** `run_isolated_main_consumer.py` →
  isolated-consumer-signed adoption receipt + signed journal/checkpoint + failure-control circuit +
  Main-consumer conformance harness (`accepted`, `main_adoption_complete=false`) + cross-project
  `producer_partial`. HARD **MF-P6-11.02 / 11.07 / 12.05 / 12.06 remain OPEN** (real Comfy_UI_Main untouched).
- **Tests:** 52 focused bridge/gold/consumer tests PASS at HEAD `447b0f9b`.
- **Evidence:** `qa/live_verification/runtime_climb_disk_safe_20260720T0720.json` (self_sha256 `a79b2051…`);
  `qa/live_verification/autonomous_gold_admission_20260720T021922.json`;
  `runtime_artifacts/main_consumer/isolated_consumer_run_evidence_20260720T021815.json`.
- **champions=0; no tier inflation.**

## Latest wave (2026-07-20 — three unblocks EXECUTED: Docker GPU + autonomous-gold tier + isolated consumer)

Commit `6a011bb6` on `codex/maskfactory-runtime-implementation`. Built infrastructure (not
re-documentation) for the three honest agent-executable unblocks. **No tier inflation:** champions=0,
no gold/Main-complete/doctor-green, no minted autonomous certificate.

- **Unblock 1 (Docker GPU train/serve):** `docker/Dockerfile.serve` (torch cu128 + serve/doctor subset
  + maskfactory), `docker/Dockerfile.train` (CUDA 12.8 devel, builds `mmcv._ext` for sm_120),
  `docker/compose.gpu.yml`, `.dockerignore`, `tools/smoke_docker_gpu_serve.py`. GPU-container CUDA
  access (RTX 5060 cap 12,0) = RUNTIME_PASS_BOUNDED. The serve image build reached the torch cu128
  install (~7 GiB of torch+CUDA wheels) and the **Docker Desktop daemon/buildkit disconnected (RPC
  Unavailable EOF)** — the constrained WSL2 backend was exhausted and the engine went down. Docker
  Desktop was **restarted and production CVAT 2.24.0 / nuclio pth-sam2 / Ollama 0.32.1 verified
  restored.** The Dockerfile/compose/.dockerignore/smoke assets are correct and committed; the
  containerized serve smoke is **NOT claimed**. RETRY: raise WSL2 memory/disk headroom (Docker Desktop
  settings or `.wslconfig`) or use a runtime base + prebuilt wheel cache, then run
  `tools/smoke_docker_gpu_serve.py --serve-image maskfactory/serve:cu128`.
- **Unblock 2 (autonomous-gold admission tier):** `configs/autonomy_autonomous_gold_profile.yaml`
  (sealed) + `calibration.build_autonomous_gold_certificate` + `verify_autonomy_certificate(
  allow_autonomous_profile=…)` (default OFF, threaded through `run_tournament`). Replaces human-anchor
  authority with independent multi-provider agreement + stability + hard-veto QA; **Wilson/exact
  bounds preserved unchanged.** `tools/build_autonomous_gold_admission.py` → honest
  `insufficient_autonomous_verified_samples` (0 `machine_verified_candidate` in `runs/`); populate via
  the GPU-container tournament on gold data. Tests: autonomous-gold 7 + autonomy 33 + bridge 18 PASS.
- **Unblock 3 (isolated Main consumer):** `tools/run_isolated_main_consumer.py` runs the real bridge
  machinery and emits an `isolated_main_consumer`-signed adoption receipt (NOT fixture, NOT real Main);
  6/6 checks PASS, harness `accepted` (`main_adoption_complete=False`), cross-project `producer_partial`.
  HARD MF-P6-11.02/11.07/12.05/12.06 remain OPEN; `C:/Comfy_UI_Main` untouched.
- **Evidence:** `qa/live_verification/three_unblocks_execution_20260720T0530.json` (self_sha256 `2b930335…`).
- **Remaining agent queue:** (a) RETRY `maskfactory/serve:cu128` build with more WSL2 headroom (the
  first attempt crashed the daemon on the ~7 GiB torch install) → run serve smoke → seal containerized
  serve RUNTIME_PASS_BOUNDED; (b) build `maskfactory/train:cu128` → `training-doctor` in
  container; (c) run the multi-provider tournament in the GPU container on gold-volume sources to
  produce `machine_verified_candidate` masks → assemble a frozen image-disjoint autonomous corpus →
  `build_autonomous_gold_admission --corpus …` → drive a package to autonomous_certified_gold; (d) real
  Comfy_UI_Main-side consumer for the HARD MF-P6 blockers.

## Latest wave (2026-07-20 — champions + Main re-verify, honest hard-gate root cause)

HEAD `c378499b`. Live re-probe: Docker 29.4.3; CVAT 2.24.0 (localhost:8080) + cvat269; Ollama 0.32.1;
nuclio pth-sam2 healthy; GPU RTX 5060 ~2182 MiB free (DAZ pid52340 + python + Cursor); WSL Ubuntu-22.04
still corrupt (E_FAIL); `IsAdmin=False`; host torch **2.12.1+cpu**; training-doctor **ready=false**;
`maskfactory serve` cannot start on host (**FastAPI serving deps missing** — serve/train runtime = WSL, down).

- **Workstream A champions — HONESTLY BLOCKED (champions=0):** `data/packages` = 28 manifests, **0
  approved_gold / 0 human_anchor_gold / 0 autonomous_certified_gold**. Audit-queue `population_count=0` is a
  **downstream symptom** — `build_weekly_audit_queue` counts only `calibrated_auto_accepted` lifecycle
  sidecars (0 exist); the 1648 files in `work/instances` are instance manifests, not autonomy sidecars.
  Calibration certificate needs a frozen **human-anchor-gold** corpus (~≥270 zero-defect audits for the
  0.01 Wilson bound) that does not exist and cannot be fabricated. Training a champion additionally needs a
  CUDA training runtime (host CPU-only; WSL down; elevation unavailable) + gold training volume (0). Did
  **not** kill DAZ (live user GUI). Mode B `/predict` = **AWAITING_RUNTIME**.
- **Workstream B Main adoption — producer verified, Main NOT fabricated:** producer bridge + cross-project
  suite PASS at HEAD; `run_cross_project_qualification` → `producer_partial` (mf_p6_12_05_complete=false).
  Main repo `C:/Comfy_UI_Main` HEAD `b36001b9` is a separate, unrelated active project (Wave64) with a dirty
  tree and **no MaskFactory consumer surface**. Real MF-P6-11.02/11.07/12.05 receipts require an isolated
  Main-side consumer build; not fabricated; Main dirty branch untouched.
- **Evidence:** `qa/live_verification/autonomy_reverify_20260720T0430.json` (self_sha256 `0bc9740a…`).

## Latest wave (2026-07-19 late — agent queue execution, honest)

Milestone revision `post_agent_queue_execution_20260719` self_sha256
`8b87568ee7264fc2fbc33e2ed646edf245601cbab90d3b2196db0adc94019a20`
(supersedes `0581b4ab…`). Evidence:
`qa/live_verification/agent_queue_execution_20260719T2300.json` (self_sha256 `c25b31a7…`).

- **DVC local-first (item 3): DONE local tier.** dvc 3.67.1; local remote `maskfactory-dvc-local` →
  `F:/MaskFactory_DataRelocated/dvc_local_remote`; 52 objects pushed; `dvc status -c` in sync.
  Honest finding: `dvc add data/packages` fails because the F: junction resolves the target **outside**
  the git workdir. Cloud s3 push still deferred (needs `dvc-s3` + AWS creds).
- **B1 restore drill (item 3): DONE local.** `img_a3d2663ad90d` restored to
  `runtime_artifacts/b1_restore_drill`; `verify-package` PASS p0+p1.
- **Multi-person (item 8) + cloud-teacher (item 7): STATIC_PASS.** `autonomy
  verify-multi-person-static-contracts` PASS (seal `multi_person_static_contracts_20260719T2245.json`);
  cloud-teacher local static PASS. Real demos / paid cloud still not claimed.
- **Main adoption (item 4): producer re-verified.** Main repo present at `C:/Comfy_UI_Main` HEAD
  `2393fbb7` (separate git). 90 focused producer/consumer bridge tests PASS at HEAD. Real Main-side
  receipts (HARD MF-P6-11.02/11.07/12.05) remain a dedicated cross-repo Main session.
- **WSL repair (item 1): elevation PROVEN unavailable** in this shell (IsInRole=False; `schtasks /rl
  HIGHEST` access-denied; RunAs would raise UAC). Docker GPU CUDA proof (RTX 5060, driver 592.01) is the
  active substitute; scripted `Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair` deferred to next elevated shell.
- **Champions (item 2): HONESTLY BLOCKED.** `autonomy build-audit-queue` → population_count=0 (empty
  lifecycle: no calibrated autoaccepted masks); + VISUAL_QA defects + ~0.4 GiB free VRAM + human_anchor=0.
  champions=0; force-register FORBIDDEN.
- **Honesty repair:** rebound the drifted shadow currency-registry STATIC seal to the current signed
  review `38a72efc` (policy still `fail`); shadow suite 7/7 PASS.

## Authoritative worktree

| Field | Value |
| --- | --- |
| Root | `C:\Comfy_UI_Main_Masking` |
| Branch | `codex/maskfactory-runtime-implementation` |
| Remote | `origin/codex/maskfactory-runtime-implementation` (KevinSGarrett/MaskingUltimate) |
| HEAD | treat `git rev-parse HEAD` as authoritative after pull |
| Docker engine (last probe) | 29.4.3 / docker-desktop up; production CVAT `cvat_*` + rehearsal `cvat269_*` + `nuclio-nuclio-pth-sam2` healthy |
| Production CVAT | localhost:8080 **v2.24.0 only** (`cvat269` = migration rehearsal only) |
| Data drive | `data/` → **junction** → `F:\MaskFactory_DataRelocated` (~251 GiB free); reversible, C: backup at `data_c_backup_relocated` |

## What this session executed (autonomous, honest)

1. **Disk ingest floor RESOLVED (former Kevin priority-1).** `data/` (only ~2.98 GiB) relocated to the
   governed **F:** drive via `robocopy` + directory junction (doctor's own remediation: "move data to a
   larger governed drive"). `doctor.check_disk_free` **FAIL → PASS (251.1 GiB free)**. Non-destructive and
   reversible; the C: original is retained at `data_c_backup_relocated`. CVAT stayed healthy (its DB lives
   in Docker volumes, not `data/`).
2. **Full `maskfactory doctor` now RUNS TO COMPLETION** (was RUNTIME_BLOCKED / not-run under unsafe
   headroom): **PASS=8 FAIL=4**.
   - PASS: cvat_api (2.24.0), cvat_project (2), disk_free (251.1 GiB), wsl_backing_store, png_strict,
     sqlite_writable, gpu_lock (stale lock cleared), and nuclio_interactor **or** ollama_image (each PASS
     individually).
   - FAIL (honest): `torch_cuda`, `registered_models`, `wsl_roundtrip` — **one root cause**: Ubuntu-22.04
     ext4 VHD read-only fallback / `/bin/true` I/O error; plus one FAIL that rotates between
     `nuclio_interactor` and `ollama_image` due to **8 GB GPU VRAM contention** (both RUNTIME_PASS_BOUNDED
     individually via smokes).
3. **gpu_lock** stale `serve_mode_b` lock (pid 467, dead) cleared → doctor FAIL→PASS (backup at
   `runs/gpu.lock.stale_bak_20260719`).
4. **Autonomous GPU/CUDA proof** (replaces "needs elevated Kevin" for GPU): `docker run --rm --gpus all
   nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi` → RTX 5060, driver 592.01.
5. **WSL VHD (former Kevin priority-2):** non-elevated `wsl --terminate Ubuntu-22.04` + restart attempted;
   read-only fallback + I/O error persist (on-disk ext4 corruption). Reclassified as **agent-executable
   from an elevated shell** (scripted `tools/Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair`, no human
   judgment). GPU work proceeds now via the container path — no lane waits.
6. **Producer bridge re-verified:** 93 focused producer bridge tests PASS at HEAD (adapter / journal /
   circuit / recovery / arbitration / conformance fixture_complete; consumer pack Main-ready).
7. **needs_kevin superseded** by `qa/live_verification/needs_agent_actions_20260719.json` (zero human stop
   states). Milestone re-sealed revision `post_disk_relocation_doctor_climb_20260719`.

## Highest proof tiers (honest — unchanged where not earned)

| Surface / profile | Highest tier | Notes |
| --- | --- | --- |
| **core_autonomous_runtime** | `STATIC_PASS` (profile); live ceiling `RUNTIME_PASS_BOUNDED` | `profile_complete=false`; `PRODUCTION_EVIDENCE_PASS` **NOT_CLAIMED** |
| Doctor disk_free | **PASS (251.1 GiB)** | resolved autonomously via governed F: relocation |
| Doctor all-green | `RUNTIME_BLOCKED` | now **runs to completion** PASS=8 FAIL=4; remaining = WSL ext4 VHD (scripted elevated e2fsck) + GPU VRAM contention |
| GPU container CUDA | `RUNTIME_PASS_BOUNDED` | RTX 5060 driver 592.01 via `docker --gpus all` |
| CVAT API 2.24 / Nuclio SAM2 / Ollama VLM | `RUNTIME_PASS_BOUNDED` | production localhost:8080; smokes pass |
| Mode B `/health` + `/models` | `RUNTIME_PASS_BOUNDED` | champions=0; draft-service only |
| Mode B `/predict` / `/refine` | `AWAITING_RUNTIME` | champions=0; force-register forbidden |
| P6-11 / P6-12 bridge | `STATIC_PASS` + **AWAITING_MAIN** | producer 93 tests PASS; HARD MF-P6-11.02 / 11.07 / 12.05 |
| Package hard/visual QA | `HARD_QA_PASS_BOUNDED` / `VISUAL_QA_REVIEWED_WITH_DEFECTS` | not gold; not visual-pass |

Milestone seal: `qa/live_verification/milestone_proof_tiers_20260719.json` revision
`post_disk_relocation_doctor_climb_20260719` self_sha256 `0581b4ab08b060f3738d48463ffe5bfbea80590b5bbe1f75bb41a54b9f457e34`
(supersedes `7986f634…`).

## Agent action queue (no human items)

Authority: `qa/live_verification/needs_agent_actions_20260719.json` — every former Kevin item reclassified:

1. **disk_headroom_above_75_gib** — **DONE_AUTONOMOUS** (F: relocation; doctor disk_free PASS).
2. **repair_ubuntu_2204_ext4_vhd** — agent-executable-from-elevated-shell; autonomous fallback (Docker GPU
   proof) done. Only the live SAM 3.1 WSL smoke awaits the scripted e2fsck.
3. **human_anchor_sop1** — **SUPERSEDED** by the autonomous-gold path (MaskedWarehouse + reference + DAZ);
   drive VISUAL_QA_PASS_BOUNDED → autonomous_certified_gold.
4. **dvc_push** — local-first (local remote/cache + integrity seal); cloud deferred without idle.
5. **b1_restore_drill** — local seed package + local restore drill.
6. **main_adoption** — producer side verified; real receipts are agent-executable **in the Main repo**
   (`C:\Comfy_UI_Main` / KevinSGarrett/Comfy_UI_Main), not a human decision. HARD blockers remain until real
   Main-side artifacts exist.
7. **cloud_teacher** — local corpus/teacher path; paid cloud deferred without idle.
8. **multi_person_sources** — local DAZ/MaskedWarehouse/reference multi-person sources.
9. **sam31 meta/HF terms** — local weights already hash-bound on disk; only the WSL smoke depends on the
   scripted e2fsck.

## What NOT to wipe / destroy

Preserve: `MaskedWarehouse`, `models/` (incl. `runtime_cache/`), `data/` (now on F: via junction) and its
`data_c_backup_relocated` C: copy, `data/packages`, Docker volumes / `docker_data.vhdx` / CVAT-Nuclio data,
`C:\Users\kevin\.ollama`, `qa/live_verification/*` seals, `Plan/`, hashed `runtime_artifacts/` evidence,
production CVAT v2.24, and branch history. **No `docker system prune` / volume wipe.**

## How to resume

1. `cd C:\Comfy_UI_Main_Masking` && `git checkout codex/maskfactory-runtime-implementation` && `git pull`.
2. Re-read `Plan/DOCKER_RUNTIME_AND_SESSION_USE.md`; live-probe Docker/CVAT/Ollama.
3. Confirm `data/` junction resolves (`cmd /c dir data` → ~251 GiB free) and `doctor` disk_free PASS.
4. Work the agent queue: `qa/live_verification/needs_agent_actions_20260719.json` — no human items.
5. If an elevated agent shell is available, run `tools/Repair-MaskFactoryWslVhd.ps1 -ConfirmRepair` to clear
   the last 3 doctor FAILs; otherwise continue all non-WSL lanes (GPU via container).
6. Champions>0 only via the legitimate measured path (certified gold → P5 entry → training → measured win →
   promotion); **never** force-register a draft/challenger.
7. Main adoption continues in the Main repo with real artifacts pinned back here — fixture/producer STATIC
   cannot close `core_autonomous_runtime`.

## Honest non-claims

- Project / `core_autonomous_runtime` **not** complete; no doctor-green, gold, `VISUAL_QA_PASS_BOUNDED`,
  `PRODUCTION_EVIDENCE_PASS`, Main-complete.
- champions=0; no champion_bodypart/hand/clothing; Mode B predict/refine AWAITING_RUNTIME.
- No cloud DVC S3 push, no live B1 restore yet, no live SAM 3.1 CUDA WSL smoke, no paid cloud-teacher, no
  multi-person demo yet.

## Key evidence pointers

- `qa/live_verification/needs_agent_actions_20260719.json` (agent queue; supersedes needs_kevin)
- `qa/live_verification/disk_relocation_doctor_climb_20260719T2210.json`
- `qa/live_verification/milestone_proof_tiers_20260719.json` (revision `post_disk_relocation_doctor_climb_20260719`)
- `qa/live_verification/needs_kevin_actions_20260719.json` (status `SUPERSEDED_BY_AGENT_QUEUE`)
- `Plan/OPS_LOG.md` (this session's disk relocation + doctor climb entry)
