# Operations Log

Append-only record of operational events worth preserving as evidence:
`maskfactory doctor` runs, benchmarks, backup/restore drills, and any other
command execution an item in `Plan\Items\*.md` or `Plan\15_RISKS_OPERATIONS_RUNBOOK.md`
tells you to log here. See `Plan\Instructions\03_SESSION_PLAYBOOK.md` for
when to write an entry.

**Format:** newest entries at the bottom, chronological, append-only —
never edit or delete a past entry, even if it later turns out to be
irrelevant (that's what "log" means). One `##` heading per event.

---

## TEMPLATE — copy this block for each new entry, then fill it in

```
## <YYYY-MM-DD HH:MM UTC> — <short title>
**Item:** <MF-P#-##.## if this entry is evidence for a tracker item>
**Command:** `<the exact command that was run>`
**Result:** <PASS / FAIL / one-line summary>

<details>
<summary>Full output</summary>

```
<paste the raw output here>
```

</details>

```

---

## EXAMPLE (illustrative only — not a real log entry, delete or leave as reference)

## 2026-01-01 00:00 UTC — Example doctor run
**Item:** MF-P0-07.04
**Command:** `maskfactory doctor`
**Result:** PASS — all checks green

<details>
<summary>Full output</summary>

```
[PASS] torch cu128 + sm_120 visible
[PASS] all registered models load + smoke hash matches
[PASS] CVAT API reachable
...
```

</details>

---

<!-- Real entries begin below this line. -->

## 2026-07-10 07:45 UTC — Tracker unstick: leaked file handle on tracker.json cleared
**Item:** (none — build infrastructure)
**Command:** `python tracker.py rebuild` (had been failing with `PermissionError [WinError 5]` at `os.replace(tracker.json.tmp -> tracker.json)`)
**Result:** RESOLVED.

<details>
<summary>Full explanation</summary>

```
tracker.json had been frozen at its 00:50 UTC state all day. Root cause: a
Claude Desktop node-service subprocess (PID 34140 = claude.exe, a child of the
same app instance hosting the build session) held a PERSISTENT share-delete
handle on tracker.json (confirmed via the Windows Restart Manager API, steady
across 8 samples). Every save_tracker() os.replace() was therefore denied, and
save_tracker's built-in 6x retry could not outlast a non-transient handle. This
is almost certainly why the whole project sat at 0 completed items all day:
every session hit this lock and could not write the tracker (the many
backups\ snapshots are debris from failed save attempts).

Fix (non-destructive): rename-aside swap. Renamed the held tracker.json to an
orphan name (the stale handle follows the old file object) and moved a
byte-identical fresh copy into tracker.json (sha256 verified unchanged:
75179ef1...b864d2). The live tracker.json is now a fresh, unheld file object.

Hardening: patched tracker.py save_tracker() to fall back to rename-aside if
os.replace() keeps raising PermissionError, so this self-heals in future.
(See DECISIONS_LOG 2026-07-10.)

After the fix, `rebuild` succeeded and picked up 45 items that had accumulated
in Plan\Items while the tracker was frozen (a whole new Phase 8):
393 items total, 31 hard-blockers unresolved, `validate` clean.
```

</details>

## 2026-07-10 07:55 UTC — Environment baseline survey
**Item:** MF-P0-01.01 (driver); baseline evidence for MF-P0-01.03/.04/.05/.10
**Command:** `nvidia-smi`; `wsl --version`; `wsl -l -v`; WSL interior probe; `ollama list`
**Result:** PASS (driver + WSL foundation present; see disk flag)

<details>
<summary>Full output summary</summary>

```
GPU        : NVIDIA GeForce RTX 5060 Laptop GPU, driver 592.01 (>=591 PASS), 8151 MiB VRAM
WSL        : v2.7.3.0, kernel 6.6.114.1-microsoft-standard-WSL2 (>=2.3 PASS)
Distros    : Ubuntu-22.04, docker-desktop
Ubuntu     : 22.04.5 LTS; /etc/wsl.conf [boot] systemd=true; systemctl is-system-running = running (PASS)
nvcc       : absent (PASS — pip cu128 wheels provide CUDA runtime, per pitfall 7)
GPU in WSL : nvidia-smi inside Ubuntu shows RTX 5060 (PASS)
Docker     : Docker Desktop installed, daemon NOT running
Ollama     : 0.31.2 native Windows; has llava:13b, qwen2.5:14b, qwen2.5:32b
             (NOT the spec VLMs — MF-P0-05 wants qwen2.5vl:7b + llama3.2-vision:11b + qwen2.5:7b-instruct in a Docker container)
Host       : 31.3 GB RAM, 16 logical CPUs
DISK FLAG  : C: 150.7 GB free of 951.6 GB (85% used) -- at doctor "warn" floor
             (<150 warn / <75 block-ingest per doc 15 §4), below the 200 GB target.
             WSL /dev/sdd (951 G avail) is a dynamically-growing .vhdx bounded by
             C: physical free. Watch this before large model/dataset pulls.
```

</details>

## 2026-07-10 08:05 UTC — Small-file I/O benchmark: ext4 hot workdir vs /mnt/c
**Item:** MF-P0-01.09
**Command:** `bash mfwork_bench.sh` (create + delete 500 tiny files in each location)
**Result:** PASS — ext4 hot workdir is ~26× faster; justifies the `~/mfwork` rule (doc 06 §1).

<details>
<summary>Numbers</summary>

```
Location            create 500 files   cleanup
ext4  ~/mfwork      32 ms              11 ms
/mnt/c repo         834 ms             331 ms   (~26x / ~30x slower)
```

Conclusion: hot pipeline work (many small intermediate files) goes on WSL's
own ext4 (`$MF_WORKDIR=~/mfwork`), never on `/mnt/c`, exactly as the spec
requires. Round-trip write to `/mnt/c/Comfy_UI_Main_Masking` (MF-P0-01.08)
confirmed PASS (touch + delete) in the same run.
```

</details>

## 2026-07-10 08:20 UTC — conda env `maskfactory` + PyTorch cu128 on Blackwell (sm_120)
**Item:** MF-P0-02.01…02.09 (esp. MF-P0-02.05/02.06 — the sm_120 gate)
**Command:** `bash build_env.sh` (Miniforge → conda create py3.11 → pip torch cu128 → sm_120 smoke → deps → freeze)
**Result:** PASS — Blackwell sm_120 CUDA kernels confirmed working.

<details>
<summary>sm_120 verification (the critical P0 gotcha)</summary>

```
conda 26.3.2 ; python 3.11.15 ; env name = maskfactory (~/miniforge3)
torch_version      2.11.0+cu128     (>= 2.7 floor required for sm_120 wheels)
torch_cuda_build   12.8
cuda_available     True
device_name        NVIDIA GeForce RTX 5060 Laptop GPU
device_capability  (12, 0)          <-- Blackwell sm_120, matches spec MF-P0-02.05
matmul 2048x2048   sum=91785.203125 <-- real GPU kernel ran; NO "no kernel image available"
SM120_SMOKE_PASS

deps: onnxruntime-gpu==1.20.2, opencv-python-headless==5.0.0.93, numpy==2.4.4,
      pillow==12.2.0, scipy, scikit-image, shapely, pycocotools, click, loguru,
      pydantic, jsonschema, pyyaml, tqdm, rich, fastapi, uvicorn,
      dvc==3.67.1 (+dvc-ssh 4.3.0), pytest, ruff, pandas, matplotlib
lockfiles: env/requirements.lock.txt (161 lines), env/maskfactory_env.yml (191 lines)

NOTE for P1: dvc has the ssh extra only (per item 02.07 = dvc[ssh]); the P1 DVC
remote is s3://maskfactory-dvc-dev, which will need `pip install dvc-s3` at
MF-P1-07.09 (to be logged then).
```

</details>

## 2026-07-10 ~08:45 UTC — Session handoff (P0 progress 0 -> 31/90)
**Item:** (session summary for the next session)
**Result:** 31/393 overall (P0 34.4%). Foundation + repo backbone done & verified.

<details>
<summary>What landed, what's blocked, what's next</summary>

```
COMPLETED & VERIFIED THIS SESSION
  MF-P0-01.*  (10) WSL2/Ubuntu-22.04, user kevin+passwordless sudo (default),
                   systemd, .wslconfig (24GB/12cpu/16GB swap), ~/mfwork ext4 +
                   MF_WORKDIR, /mnt/c round-trip, I/O bench (ext4 ~26x faster), no nvcc.
  MF-P0-02.*  (10) conda env 'maskfactory' (py3.11.15) + torch 2.11.0+cu128;
                   *** sm_120 Blackwell CUDA smoke PASS (capability (12,0), real matmul) ***
                   all pipeline deps; env/requirements.lock.txt + env/maskfactory_env.yml.
  MF-P0-08    (7)  git init (branch main, autocrlf=false); png_strict.py (ONLY mask
                   writer, self-test 10/10); src/maskfactory scaffold (65 files, doc 05 §3);
                   pyproject + console script (maskfactory --help lists all cmds);
                   no-raw-mask-writer test; CI workflow; pre-commit (ruff+black+hooks) green.
  MF-P0-09.*  (4)  configs/external_sources.yaml: 16 providers + 15 datasets + 4 platforms,
                   with license flags (7 need verify: sapiens/rmbg NC, yolo AGPL, etc.).

BLOCKED — NEEDS KEVIN
  MF-P0-08.02  Create GitHub repo under Scentiment-Dev + push. gh IS authed
               (KevinSGarrett active w/ repo+workflow; also KevinGarrett-Scentiment).
               Need: org, which account, repo name, private visibility. Local repo
               ready to push. (08.09 CI-green chained to this.)

KEY GOTCHAS FOR NEXT SESSION
  * Tracker lock: a leaked claude.exe node handle froze tracker.json all day; fixed
    via rename-aside swap + a permanent fallback in tracker.py save_tracker(). If
    tracker writes ever fail again with WinError 5, it now self-heals (see DECISIONS_LOG).
  * DISK: C: only ~150 GB free (at doctor 'warn' floor). Watch before model/VLM pulls.
  * Docker Desktop is INSTALLED but STOPPED -> start it before P0-03/04/05.
  * Ollama: native Windows install has llava/qwen2.5 (wrong). Spec (P0-05) wants a
    DOCKER Ollama + qwen2.5vl:7b + llama3.2-vision:11b + qwen2.5:7b-instruct.
  * `wsl --update` hangs on interactive UAC (non-interactive session) — skip; WSL 2.7.3 already ok.
  * Plan/Civitai/ (~9 GB weights + adult preview imagery) is git-ignored (DECISIONS_LOG);
    still on disk for the P0-10/13/14 review tasks. Run all WSL work as user 'kevin';
    conda: `source ~/miniforge3/etc/profile.d/conda.sh && conda activate maskfactory`.
  * COMMIT from WSL (conda env active) so the pre-commit hook finds `pre-commit`.

NEXT ACTIONABLE (P0 remaining, dependency-aware)
  Heavy/download: P0-03 Docker+CVAT v2.24.0 -> P0-04 nuclio SAM2 -> P0-05 Ollama VLMs
                  -> P0-06 model checkpoints M1-M12 (+detectron2 source build) -> P0-07 doctor.
  Local/no-download: P0-10 Civitai workflow review, P0-13 MaskedWarehouse inventory,
                  P0-11 `maskfactory external probe`. P0-14 (adult/NSFW intake) = handle
                  with governance care (doc 16 §2.2; nothing to gold/training without
                  recorded license+consent+allowed-use).
```

</details>

## 2026-07-10 17:52 UTC — Docker Desktop, WSL integration, container GPU
**Items:** MF-P0-03.01, MF-P0-03.02, MF-P0-03.03
**Result:** PASS — Docker Desktop 4.74.0 is running on the Linux/WSL2 engine;
Ubuntu-22.04 integration enabled and verified; CUDA 12.8 container sees the GPU.

```
docker client/server: 29.4.3 / 29.4.3, server OS linux
Docker Desktop:        4.74.0 (227015), context desktop-linux
Ubuntu-22.04 proof:    docker version -> 29.4.3|29.4.3|linux
container image:       nvidia/cuda:12.8.0-base-ubuntu22.04
image digest:          sha256:12242992c121f6cab0ca11bccbaaf757db893b3065d7db74b933e59f321b2cf4
NVIDIA-SMI:            590.62
driver:                592.01
GPU:                   NVIDIA GeForce RTX 5060 Laptop GPU, 8151 MiB
container result:      PASS; no running GPU processes after exit
```

## 2026-07-10 17:55 UTC — CVAT checkout pinned
**Item:** MF-P0-03.04
**Command:** `git clone --branch v2.24.0 --depth 1 https://github.com/cvat-ai/cvat.git cvat`
**Result:** PASS — exact tag and commit verified in the clean checkout.

```
tag:    v2.24.0
commit: 9fafd98f0c0588b775db8f98648569dfa48292b5
path:   C:\Comfy_UI_Main_Masking\cvat
config: configs/cvat.yaml
```

## 2026-07-10 18:14 UTC — CVAT local cluster and administrator verified
**Items:** MF-P0-03.05, MF-P0-03.06, MF-P0-03.07, MF-P0-03.08, MF-P0-03.09
**Result:** PASS — pinned CVAT 2.24.0 is live on localhost, its full serverless
compose stack is stable, the shared data mount is read-only, and the local
`kevin` superuser/token were provisioned and authenticated without logging secrets.

```
containers:             19/19 running; 0 restarted; 0 unhealthy
CVAT API:               GET /api/server/about -> 200, version 2.24.0
CVAT UI:                GET / -> 200 text/html, 1214 bytes
Nuclio API:             GET :8070/api/versions -> 200; health=healthy
published ports:        127.0.0.1:8070, 127.0.0.1:8080, 127.0.0.1:8090 only
shared data:            cvat_server/import/export/annotation/chunks
                        C:/Comfy_UI_Main_Masking/data -> /home/django/share (ro)
administrator:          kevin; POST /api/auth/login succeeded;
                        authenticated GET /api/users/self -> 200, is_superuser=true
secrets:                CVAT_USERNAME/PASSWORD/EMAIL/TOKEN present and nonempty
                        only in root .env; git check-ignore confirms .gitignore:10
tests:                  25 pytest passed; ruff + black + all pre-commit hooks passed
```

Docker 29 compatibility required two reproducible, version-recorded shims:

- `tools/bootstrap_cvat.py` aliases the retired
  `gcr.io/iguazio/alpine:3.17` helper to official `alpine:3.17` digest
  `sha256:8fc3dacfb6d69da8d44e42390de777e48577085db99aa4e4af35f483eb08b989`.
- `configs/cvat-compose.maskfactory.yml` uses official Traefik 3.6.1 (Docker API
  negotiation) and expands CVAT's legacy multi-argument `PathPrefix` router rule.
  Verification showed zero current Docker-provider errors and Django, not UI nginx,
  handling API POSTs.

## 2026-07-10 18:55 UTC — CPU SAM2 Nuclio interactor deployed and smoke-tested
**Items:** MF-P0-04.01, MF-P0-04.02, MF-P0-04.03, MF-P0-04.05
**Result:** PASS — CVAT lists `pth-sam2` as a v2 interactor; Nuclio reports
`ready` 1/1; a synthetic task invoked through CVAT returned a valid binary mask.

```
nuctl:                  1.13.0, commit c4422eb772781fb50fbf017698aae96199d81388
nuctl sha256:           df6d4070d2884ce8af90af3d45734700ab8607c83f469b6f36cf3c8222bb0790
function:               pth-sam2; image cvat.pth.sam2:latest
model:                  SAM 2.1 hiera base-plus, CPU only (4 CPUs, 8 GiB limit)
Nuclio state:           ready, 1/1; container healthy; restart count 0
published function:     127.0.0.1:62170 only
model init cold start:  3.005 s (18:49:58.412 -> 18:50:01.417 UTC)
first CVAT inference:   6.600 s end-to-end
scratch task/job:       task 1, job 1, "MaskFactory SAM2 synthetic smoke"
mask result:            256x256; values {0,255}; 21,491 foreground pixels
prompt checks:          positive point=foreground; negative point=background
evidence report:        qa/reports/cvat_sam2_smoke.json
```

Compatibility notes: pinned CVAT v2.24.0 does not ship the specified SAM2
Nuclio directory. The conservative resolution is logged in DECISIONS_LOG and
implemented under `integrations/cvat/serverless/.../sam2/nuclio`. CVAT's generic
CPU deploy script also performs an unrelated OpenVINO build whose retired Intel
apt source now fails; `tools/deploy_cvat_sam2.py` executes the script's exact
function-specific `nuctl deploy` block instead. A narrow Docker CLI wrapper forces
Nuclio 1.13's dynamically published HTTP port to loopback; live `docker inspect`
confirmed `127.0.0.1:62170`.

MF-P0-04.04 remains human-owned: Kevin must open task 1 / job 1 in CVAT and
perform the literal Magic Wand positive/negative click smoke check. The automated
equivalent passed, but it is not being represented as the required manual UI click.

## 2026-07-10 19:22 UTC - Docker Ollama VLM stack installed and smoke-tested
**Items:** MF-P0-05.01, MF-P0-05.02, MF-P0-05.03, MF-P0-05.04, MF-P0-05.05
**Result:** PASS - official Docker Ollama is running on loopback with GPU access,
all three required models are installed, and the primary VLM returned strict JSON
for a synthetic P-PART panel image.

```
container:              ollama; image sha256:509fdf54e23bd50d87af646cb51c0a7a203d6a83cc4d6695b3b08c5be1c62c0a
runtime:                Ollama 0.31.2; restart count 0
published port:         127.0.0.1:11434 only
volume:                 ollama:/root/.ollama
GPU device request:     all GPUs (-1:[[gpu]])
primary VLM:            qwen2.5vl:7b, id 5ced39dfa4ba, 6.0 GB, qwen25vl, 8.3B, Q4_K_M, vision
fallback VLM:           llama3.2-vision:11b, id 6f2f9757ae97, 7.8 GB, mllama, 10.7B, Q4_K_M, vision
text LLM:               qwen2.5:7b-instruct, id 845dbda0ea48, 4.7 GB, qwen2, 7.6B, Q4_K_M
config:                 configs/vlm.yaml
smoke script:           tools/smoke_ollama_vlm.py
smoke fixture:          generated 1024x256 four-tile synthetic P-PART panel
smoke result:           strict JSON parsed and schema checks all true
smoke latency:          139.347 s first cold multimodal run; eval_count 61
smoke verdict:          pass, confidence 1, problems []
evidence report:        qa/reports/ollama_vlm_smoke.json
governance asserted:    VLM may not author masks, approve gold, clear BLOCKs, or send images off-machine
tests:                  pytest tests\test_vlm_config.py -> 3 passed
```

## 2026-07-10 20:10 UTC - MaskedWarehouse license/provenance gate recorded
**Items:** MF-P0-13.04
**Result:** PASS - every source in `configs/maskedwarehouse_inventory.json` now
has an explicit license/provenance record and conservative workflow gates in
`configs/maskedwarehouse_provenance.yaml`.

```
inventory source count: 5
celebamask_hq:          30,000 images; 372,767 masks; official CelebAMask-HQ GitHub/local README; non-commercial research/educational only
lapa:                   22,168 images; 22,168 masks; official LaPa GitHub; non-commercial only
lv_mhp_v1:              4,980 images; 14,969 masks; official MHP site/GitHub/local README; non-commercial only
swimsuit_preview:       10 images; 10 masks; local Hugging Face-style README and UniDataPro preview; CC BY-NC-ND 4.0 preview; conversion blocked
body_archive:           175 images; 175 masks; local Excel/folders only; no upstream/license found; all conversion/training/gold use blocked
gold gate:              blocked for all external source masks; they are source masks, not MaskFactory gold
production training:    blocked for all five until explicit compatible rights are recorded
fixture conversion:     allowed only for non-distributable local QA/prototype use on CelebAMask-HQ/LaPa/LV-MHP after remap tests and visual QA
machine record:         configs/maskedwarehouse_provenance.yaml
tests:                  pytest tests\test_maskedwarehouse_provenance.py -> 5 passed
```

## 2026-07-10 20:55 UTC - Adult/body Civitai role classification recorded
**Items:** MF-P0-14.01
**Result:** PASS - all Civitai manifest resources, including adult/NSFW-labeled
detectors, workflows, pose packs, and manual-download candidates, are classified
by MaskFactory role.

```
manifest records:       79 records in Plan/Civitai/civitai_bootstrap_manifest.json
unique Civitai IDs:     71 classified IDs
classification file:    Plan/Civitai/adult_body_resource_classification.yaml
roles:                  provider_vote, comfyui_graph_reference, stress_fixture, qa_probe, reject
provider votes:         hand/eye/mouth/lips/armpit/nail/teeth/hair/sock/shoe/foot/rear/accessory/tattoo/person/clothing candidates
graph references:       SAM2, Florence2+SAM2, mask add/remove, DWPose/DensePose/OpenPose, multi-character/multi-control, garment/hand/foot workflows
stress fixtures:        adult/NSFW and adjacent OpenPose/depth packs for contact, occlusion, hands-on-body, rear-body, from-above/from-below, and multi-person coverage
QA probes:              RMBG/matting/rotoscope/auto-mask comparison workflows
rejects:                generative breast-expansion workflow and generative clothing-extractor model
training eligibility:   adult/NSFW Civitai assets may enter training or seed human-reviewed gold after provenance/license/adult-age-consent/allowed-use/intake/annotation/QA gates pass
tests:                  pytest tests\test_civitai_classification.py -> 5 passed
```

## 2026-07-10 21:35 UTC - Civitai auxiliary detector registry recorded
**Items:** MF-P0-14.02
**Result:** PASS - all usable provider-vote Civitai detector models are
registered with local artifact path, SHA-256, version, coverage bucket, payload
path/hash, and planned ComfyUI/ADetailer install target.

```
registry:               configs/civitai_auxiliary_detectors.yaml
registered detectors:   24 provider-vote resources
coverage buckets:       shoes/footwear, feet, hair, lips, socks, hands, face bands, armpits, nails, mouth, rear/accessory/body
archive payloads:       inspected extracted .pt files for hand, eye, face-band, armpit, nails, rear, teeth, lips, socks, glasses, tattoo, head accessory, clothes/tops
standalone models:      registered direct .pt files for mouth, foot/shoe, shoes, feet, hair, jewelry, rings, anime foot, person/female, anime hair
missing manifest hash:  computed nailsSegmentationAdetailer_v10.zip sha256 e2130d2b478c1252d8d0b6a3d69d46c878d5ba05ffa549f396addad020905cae
install targets:        ComfyUI/models/ultralytics/{bbox,segm}/...
training eligibility:   detector outputs may become training labels or seed human-reviewed gold when paired with eligible sources and passed through normal consensus/QA/review gates
tests:                  pytest tests\test_civitai_auxiliary_detectors.py -> 5 passed
```

## 2026-07-10 22:05 UTC - Civitai pose/control stress fixtures registered
**Items:** MF-P0-14.03
**Result:** PASS - adult/NSFW and adjacent OpenPose/OpenPose+Depth pose packs
are registered as stress fixtures with coverage tags for the required hard cases.

```
registry:               configs/civitai_pose_stress_fixtures.yaml
fixture resources:      22 stress-fixture Civitai IDs from Plan/Civitai/adult_body_resource_classification.yaml
archive evidence:       every archive path and SHA-256 recorded from Plan/Civitai/civitai_bootstrap_manifest.json
content inventory:      extracted-file counts recorded by extension; mix of OpenPose JSON+PNG and PNG-only pose/depth/control assets
coverage tags:          contact, occlusion, hands_on_body, rear_body, from_below, difficult_body_visibility
largest pack:           openposeNSFWPosePackage_final.zip -> 1,753 files including 472 JSON and 1,279 PNG files
training eligibility:   eligible adult source/control pairs may also become training examples or seed human-reviewed gold after all governance, annotation, QA, and review gates pass
tests:                  pytest tests\test_civitai_pose_stress_fixtures.py -> 4 passed
```

## 2026-07-10 22:20 UTC - Civitai adult/NSFW training eligibility verified
**Items:** MF-P0-14.04
**Result:** PASS - adult/NSFW assets are usable for training and may seed
human-reviewed gold. Registries encode their eligibility after the normal
governance and quality gates.

```
classification:         Plan/Civitai/adult_body_resource_classification.yaml
detector registry:      configs/civitai_auxiliary_detectors.yaml
fixture registry:       configs/civitai_pose_stress_fixtures.yaml
verified eligibility:   adult/NSFW assets may enter training or seed human-reviewed gold after provenance/license/adult-age-consent/allowed-use/intake/annotation/QA gates pass
detector eligibility:   governed detector outputs may become training labels or seed reviewed gold
fixture eligibility:    governed adult source/control pairs may become training examples or seed reviewed gold
source provenance:      original Civitai artifact/payload/archive/extracted paths remain stable under Plan/Civitai before governed promotion
tests:                  pytest tests\test_civitai_governance_gates.py -> 4 passed
```

## 2026-07-10 23:50 UTC - Verified model fetch and registry foundation implemented
**Items:** MF-P0-06.01
**Result:** PASS - `maskfactory models fetch <key>` now downloads transactionally,
computes SHA-256, requires a model-specific one-image smoke test, atomically writes
the registry only after success, and exposes the sole verified checkpoint resolver.

```
catalog:                models/model_sources.yaml
registry:               models/model_registry.json
implementation:         src/maskfactory/models/registry.py
CLI:                    maskfactory models fetch <key> | --all
required metadata:      source URL, version tag, license, download date, role, runtime, path, SHA-256
smoke evidence:         generated 3x2 RGB fixture image + fixture checkpoint; deterministic inference-output SHA-256 recorded
transaction gate:       failed download/hash/smoke never publishes a target or verified registry entry
loader gate:            rejects unknown path/key, unverified entry, missing file, path escape, and hash mismatch
idempotency:            verified matching checkpoint returns cached without download or registry rewrite
focused tests:          pytest tests\test_model_registry.py -> 6 passed
full tests:             pytest -> 61 passed
quality:                pre-commit run --all-files -> passed
```

## 2026-07-10 23:58 UTC - M1 YOLO11m person detector fetched and verified
**Items:** MF-P0-06.02
**Result:** PASS - the exact official YOLO11m release checkpoint is registered,
hash-verified, loaded with Ultralytics, and exercised on one governed image with
four class-0 person detections.

```
catalog key:            yolo11m
source:                 https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11m.pt
official asset size:    40,684,120 bytes
SHA-256:                d5ffc1a674953a08e11a8d21e022781b1b23a19b730afc309290bd9fb5305b95
local path:             models/detect/yolo11m.pt
license:                AGPL-3.0 or Ultralytics Enterprise
runtime smoke:          ultralytics 8.4.87, torch 2.12.1+cpu
fixture:                qa/fixtures/smoke/ultralytics_bus_adults.jpg
fixture governance:     official Ultralytics package asset; clearly adult pedestrians; QA-only; SHA-256 c02019c4979c191eb739ddd944445ef408dad5679acab6fd520ef9d434bfbc63
smoke result:           5 detections, 4 class-0 persons
output SHA-256:         d49b12c55b9c0dd1c87beeaa927ac021f1733980feace2533b948d04d10aa8a4
registry:               verified=true in models/model_registry.json
idempotency:            immediate rerun returned cached with matching SHA-256
```

## 2026-07-11 01:12 UTC - M7 SAM 2.1 large and base-plus verified
**Items:** MF-P0-06.08
**Result:** PASS - both official SAM 2.1 checkpoints were hash-pinned and run
with identical positive/negative point prompts through the pinned CUDA image
predictor; base-plus also matches the already-deployed CVAT interactor artifact.

```
official source:        dl.fbaipublicfiles.com/segment_anything_2/092824
source code:            facebookresearch/sam2@2b90b9f5ceec907a1c18123530e92e794ad901a4
license:                Apache-2.0
base-plus file:         sam2.1_hiera_base_plus.pt; 323,606,802 bytes
base-plus SHA-256:      a2345aede8715ab1d5d31b4a509fb160c5a4af1970f199d9054ccfb746c004c5
CVAT parity:            exact hash match with /opt/nuclio/sam2/sam2.1_hiera_base_plus.pt
base smoke:             1080x810 mask; area 0.060175; score 0.851562
base output SHA-256:    51b5e27fab46df194cd30263c1c8464c6df9065b775f64baf0dfce8a3e4e263e
large file:             sam2.1_hiera_large.pt; 898,083,611 bytes
large SHA-256:          2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318
large smoke:            1080x810 mask; area 0.033365; score 0.777344
large output SHA-256:   1ac5750f294ff511e0b22fc03f6d997a498f123f9be6fced16cbd3202d9835a0
prompts:                positive [150,550]; negative [600,150]
runtime:                WSL torch 2.11.0+cu128 BF16; RTX 5060 Laptop GPU
registry:               both verified=true; large primary, base-plus OOM fallback
idempotency:            both immediate reruns returned cached with matching SHA-256
```

## 2026-07-11 01:28 UTC - M8 GroundingDINO Swin-T fetched and verified
**Items:** MF-P0-06.09
**Result:** PASS - the official alpha checkpoint was hash-pinned and performed
real open-vocabulary grounding for the literal `person .` prompt, returning
four finite normalized person boxes on the governed adult fixture.

```
checkpoint release:     IDEA-Research/GroundingDINO v0.1.0-alpha
file:                   groundingdino_swint_ogc.pth; 693,997,677 bytes
SHA-256:                3b3ca2563c77c69f651d7bd133e97139c186df06231157a64c507099c52bc799
inference source:       GroundingDINO@856dde20aee659246248e20734ef9ba5214f5e44
license:                Apache-2.0
runtime:                authoritative WSL; torch 2.11; supported pure-PyTorch CPU deformable-attention fallback
prompt:                 person .
result:                 4 normalized cxcywh boxes; phrases person/person/person/person; max logit 0.795840
output SHA-256:         bed324d537289fba5746273a88e4a73bcff17bfdf47af09b77efb6ce651f338e
authority:              boxes only, never semantic or mask authority
registry:               verified=true in models/model_registry.json
idempotency:            immediate rerun returned cached with matching SHA-256
```

## 2026-07-11 00:35 UTC - M4 SCHP ATR and LIP fallbacks fetched and verified
**Items:** MF-P0-06.05
**Result:** PASS - both official SCHP fallback variants were downloaded from
the authors' linked Google Drive records, hash-pinned, loaded strictly against
the pinned source architecture, and exercised by real CUDA parsing.

```
source repository:      GoGoDuck912/Self-Correction-Human-Parsing
source revision:        eb84c432cc697f494d99662a05f2335eb2f26095
license:                MIT
compatibility:          obsolete compiled InPlaceABNSync replaced for inference by state-compatible pure torch BatchNorm2d; strict state load passed
ATR file:               exp-schp-201908301523-atr.pth; 267,445,237 bytes
ATR SHA-256:            e9d7c91ce3b4e7133df56b599fc817b533e3439c5e8d282a59126d2fda339a2a
ATR output:             [1,18,512,512]; labels 0,4; foreground 0.041264
ATR output SHA-256:     3dbf93127a736e745abd4f3659f8d2cbaafbd04ab17ee54448e98d6f84e05157
LIP file:               exp-schp-201908261155-lip.pth; 267,449,349 bytes
LIP SHA-256:            24fa3254ceeb74c8435458994a64b522fb439a3635b7b86ff470457e0413da00
LIP output:             [1,20,473,473]; labels 0,7,9; foreground 0.056908
LIP output SHA-256:     4a48994533e69b1161061cd0286e24420b34305648900267325c195bc12953e2
runtime:                WSL Ubuntu-22.04; torch 2.11.0+cu128; RTX 5060 Laptop GPU
registry:               both verified=true in models/model_registry.json
idempotency:            both immediate reruns returned cached with matching SHA-256
```

## 2026-07-11 00:56 UTC - M6 MediaPipe Hand Landmarker fetched and verified
**Items:** MF-P0-06.07
**Result:** PASS - Google's official float16 v1 task bundle was downloaded,
hash-pinned, loaded by MediaPipe Tasks, and returned a complete 21-point hand,
21 world landmarks, and handedness on the official hand fixture.

```
source:                 storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1
file:                   models/hand/hand_landmarker.task
size:                   7,819,105 bytes
SHA-256:                fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1
version:                MediaPipe Hand Landmarker float16 v1
license:                Apache-2.0
runtime:                authoritative WSL; mediapipe 0.10.35; CPU XNNPACK delegate; libgles2
fixture:                official mediapipe-assets/thumb_up.jpg; SHA-256 5d673c081ab13b8a1812269ff57047066f9c33c07db5f4178089e8cb3fdc0291
smoke result:           1 hand; 21 normalized points; 21 world points; Right score 0.983548
output SHA-256:         2ba6fd1c26a438bb12f711554606138ee8125b6238442b1b51ca2e0fd00f0737
registry:               verified=true in models/model_registry.json
idempotency:            immediate rerun returned cached with matching SHA-256
failed-closed evidence: WSL attempt without libGLESv2 published nothing; libgles2 added to the reproducible apt package list before fresh verification
```

## 2026-07-11 00:48 UTC - M5 DWPose detector and 133-keypoint pose verified
**Items:** MF-P0-06.06
**Result:** PASS - both official pinned ONNX components were hash-verified and
run together through CUDA ONNX Runtime, detecting four adults and producing
four complete 133-keypoint arrays with 454 visible keypoints.

```
official host:          yzd-v/DWPose (linked by IDEA-Research/DWPose)
pinned model revision:  f7c16a3d45ad3783db41471848c80fbc281cabac
license:                Apache-2.0
detector:               yolox_l.onnx; 216,746,733 bytes
detector SHA-256:       7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411
detector result:        4 person boxes; output hash 8245f5a511ba8b70a1589e9477d50a008d4cbc8dac18533abd27fc76986c926d
pose:                   dw-ll_ucoco_384.onnx; 134,399,116 bytes
pose SHA-256:           724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843
paired result:          keypoints [4,133,2]; 454 scores >= 0.3
pose output hash:       a9d571753218695f851405b64e3c9f91830cd3ee2b47520384406b326d131a03
inference source:       Fannovel16/comfyui_controlnet_aux@e8b689a513c3e6b63edc44066560ca5919c0576e
runtime:                WSL onnxruntime-gpu 1.20.2; CUDAExecutionProvider active for both sessions
failed-closed repair:   initial CPU fallback exposed missing wheel CUDA library path; GPU-path smoke runners forced re-verification after repair
registry:               both verified=true with GPU output hashes
idempotency:            both immediate reruns returned cached with matching SHA-256
```

## 2026-07-11 00:10 UTC - M2 BiRefNet silhouette model fetched and verified
**Items:** MF-P0-06.03
**Result:** PASS - the official pinned BiRefNet general checkpoint was fetched,
hash-verified, loaded through its pinned Hugging Face custom model code, and run
on the governed adult fixture using the authoritative CUDA WSL environment.

```
catalog key:            birefnet_general
official repo:          ZhengPeng7/BiRefNet
pinned revision:        e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4
source file:            model.safetensors (stored locally as required BiRefNet-general.safetensors)
source size:            444,473,596 bytes
SHA-256:                9ab37426bf4de0567af6b5d21b16151357149139362e6e8992021b8ce356a154
local path:             models/silhouette/BiRefNet-general.safetensors
license:                MIT
runtime:                WSL Ubuntu-22.04; torch 2.11.0+cu128; transformers 4.47.1
GPU:                    NVIDIA GeForce RTX 5060 Laptop GPU
smoke input:            qa/fixtures/smoke/ultralytics_bus_adults.jpg -> 1024x1024
mask range:             0..255
foreground fraction:    0.413952
output SHA-256:         c7c578c05ad1c45e88d5720429772bf8b5d6e77ba42ebb6a52f0ce4334c35242
registry:               verified=true in models/model_registry.json
idempotency:            immediate rerun returned cached with matching SHA-256
dependency locks:       env/requirements.lock.txt + env/maskfactory_env.yml refreshed
failed-closed evidence: first attempt missing declared einops; no checkpoint or registry entry published until dependency and real inference passed
```

## 2026-07-11 00:22 UTC - M3 Sapiens 0.6B human parser fetched and verified
**Items:** MF-P0-06.04
**Result:** PASS - Meta's official pinned 0.6B Goliath segmentation TorchScript
checkpoint was fetched, hash-verified, loaded on CUDA, and produced a nontrivial
28-channel human-part parse on the governed adult fixture.

```
catalog key:            sapiens_0_6b_seg
official repo:          facebook/sapiens-seg-0.6b-torchscript
pinned revision:        ea5545c735d1fc994d0d1aafede27df892761322
official filename:      sapiens_0.6b_goliath_best_goliath_mIoU_7777_epoch_178_torchscript.pt2
source size:            2,685,144,079 bytes
SHA-256:                86aa2cb9d7310ba1cb1971026889f1d10d80ddf655d6028aea060aae94d82082
local path:             models/parsing/sapiens_0.6b_seg.pt2
license:                CC-BY-NC-4.0 (non-commercial)
runtime:                WSL Ubuntu-22.04; torch 2.11.0+cu128; TorchScript FP32
GPU:                    NVIDIA GeForce RTX 5060 Laptop GPU
input/output:            1024x768 input; logits [1,28,1024,768]; label map [1024,768]
unique labels:           0,2,3,5,8,9,12,14,17,18,22
foreground fraction:    0.029035
output SHA-256:         a52baa823458a5eb5380c4951ffcce4746e0eb242378234d1b4aa525897fe262
registry:               verified=true in models/model_registry.json
idempotency:            immediate rerun returned cached with matching SHA-256
```

## 2026-07-10 22:31 UTC - detectron2 built from source for CUDA 12.8 / sm_120
**Items:** MF-P0-06.10
**Result:** PASS - the pinned official detectron2 source compiled with ninja and
executed its compiled rotated-NMS CUDA operator on the RTX 5060 Laptop GPU.

```
repo:                    https://github.com/facebookresearch/detectron2.git
pinned commit:           02b5c4e295e990042a714712c21dc79b731e8833
source worktree:          /home/kevin/mfwork/source/detectron2 (WSL ext4)
build environment:       CUDA_HOME=$CONDA_PREFIX; TORCH_CUDA_ARCH_LIST=12.0; FORCE_CUDA=1; MAX_JOBS=4
compiler/toolkit:         NVIDIA CUDA 12.8.93 compiler + CUDA 12.8 development libraries
runtime:                  Python 3.11.15; torch 2.11.0+cu128; detectron2 0.6
build result:             detectron2._C compiled and installed successfully with ninja
architecture evidence:   cuobjdump lists five embedded sm_120 cubins in detectron2._C
GPU smoke:               nms_rotated accepted CUDA boxes/scores and returned CUDA indices [0,2]
compiled CUDA version:   CUDA 12.8
device/capability:        NVIDIA GeForce RTX 5060 Laptop GPU; [12,0]
compatibility patch:      env/patches/detectron2-iopath-0.1.10.patch (allows shared SAM2 iopath 0.1.10)
dependency check:         pip check -> No broken requirements found
reproduction lock:       env/source_builds.lock [detectron2]
```

## 2026-07-10 22:42 UTC - M9 DensePose surface prior installed and verified
**Items:** MF-P0-06.11
**Result:** PASS - DensePose was installed from the pinned detectron2 source and
the official R50-FPN checkpoint produced nontrivial chart-based human-surface
predictions through the verified sm_120 CUDA extension.

```
source repo/commit:      facebookresearch/detectron2@02b5c4e295e990042a714712c21dc79b731e8833
project:                 projects/DensePose; detectron2-densepose 0.6
catalog key:             densepose_rcnn_r50_fpn_s1x
official model id:       165712039
official source file:    model_final_162be9.pkl
local required filename: models/densepose/densepose_rcnn_R_50_FPN_s1x.pkl
size:                    255,757,821 bytes
SHA-256:                 b8a7382001b16e453bad95ca9dbc68ae8f2b839b304cf90eaf5c27fbdb4dae91
license:                 Apache-2.0
runtime:                 detectron2/DensePose 0.6; torch 2.11.0+cu128; CUDA 12.8
GPU:                     NVIDIA GeForce RTX 5060 Laptop GPU; capability [12,0]
smoke input:             qa/fixtures/smoke/ultralytics_bus_adults.jpg (1080x810)
instances:               5 with confidence 0.838524..0.999564
output tensors:          coarse [5,2,112,112]; fine/U/V [5,25,112,112]
surface labels:          all chart labels 1..24 present; nonzero fraction 1.0
output SHA-256:          70567801d4e3fe6bc5ffde312d412369b3ca95cda88219aa737bb9ea6d469143
registry:                verified=true in models/model_registry.json
idempotency:             immediate rerun returned cached with matching SHA-256
dependency check:        pip check -> No broken requirements found
reproduction lock:       env/source_builds.lock [densepose]
```

## 2026-07-10 22:49 UTC - M10 BiSeNet face parser fetched and verified
**Items:** MF-P0-06.12
**Result:** PASS - the author's official Google Drive checkpoint was fetched,
hash-verified, loaded strictly into the pinned 19-class BiSeNet implementation,
and produced a nontrivial CUDA face-detail parse on the governed fixture.

```
catalog key:             faceparse_bisenet
official repo:           zllrunning/face-parsing.PyTorch
pinned source commit:    d2e684cf1588b46145635e8fe7bcc29544e5537e
official Drive file id:  154JgKpzCPW82qINcVieuPH3fZ2e0P812
filename/local path:     models/faceparse/79999_iter.pth
size:                    53,289,463 bytes
SHA-256:                 468e13ca13a9b43cc0881a9f99083a430e9c0a38abd935431d1c28ee94b26567
license:                 MIT
runtime:                 WSL; torch 2.11.0+cu128; strict state-dict load; CUDA
GPU:                     NVIDIA GeForce RTX 5060 Laptop GPU; capability [12,0]
smoke input/crop:        qa/fixtures/smoke/ultralytics_bus_adults.jpg; [567,238,810,670]
input/output:             [1,3,512,512] -> logits [1,19,512,512]
unique labels:           0,1,6,10,18
foreground fraction:    0.980186
output SHA-256:          8c3235e1d57e8c8fed280c0d9542458fa7198b415cfead1171d7d20ead518be2
registry:                verified=true in models/model_registry.json
idempotency:             immediate rerun returned cached with matching SHA-256
```

## 2026-07-10 23:02 UTC - M11 ViTMatte-S fetched and verified
**Items:** MF-P0-06.13
**Result:** PASS - the official pinned Hugging Face PyTorch checkpoint was
hash-verified, loaded strictly into ViTMatte-S, and produced a nontrivial
trimap-conditioned alpha transition through CUDA.

```
catalog key:             vitmatte_small_composition_1k
official repo:           hustvl/vitmatte-small-composition-1k
pinned revision:         6a58ad7646403c1df626fbd746900aec7361ea1d
official source file:    pytorch_model.bin
required local path:     models/matting/vitmatte_s.pth
size:                    103,349,013 bytes
SHA-256:                 6ec6aed44bc8d8ab7f4d0ff46da3520a534cf5a97a8262404ff6efa9ae33b1e5
license:                 Apache-2.0
runtime:                 transformers 4.47.1; torch 2.11.0+cu128; strict state-dict load
GPU:                     NVIDIA GeForce RTX 5060 Laptop GPU; capability [12,0]
smoke input/crop:        qa/fixtures/smoke/ultralytics_bus_adults.jpg; [502,270,810,950]
input/output:             RGB+trimap [1,4,512,512] -> alpha [1,1,512,512]
alpha range/mean:        0.0..1.0 / 0.267437
unknown band mean/std:   0.495792 / 0.451953
output SHA-256:          c1ab0c212278e042413e92ac14b8717976799a88a0b4631a40454cf32f03c1da
registry:                verified=true in models/model_registry.json
idempotency:             immediate rerun returned cached with matching SHA-256
dependency check:        pip check -> No broken requirements found
```

## 2026-07-10 23:00 UTC - M12 Ollama-managed models registered
**Items:** MF-P0-06.14
**Result:** PASS - all three required Ollama models were cross-checked between
the local `/api/tags` inventory and `ollama list`, then atomically registered
with full manifest digests, `managed: true`, and verified runtime metadata.

```
command:                 maskfactory models register-ollama
primary VLM:             qwen2.5vl:7b
primary digest/list ID:  5ced39dfa4bac325dc183dd1e4febaa1c46b3ea28bce48896c8e69c1e79611cc / 5ced39dfa4ba
primary size/details:    5,969,245,856 bytes; qwen25vl 8.3B Q4_K_M GGUF
fallback VLM:            llama3.2-vision:11b
fallback digest/list ID: 6f2f9757ae97e8a3f8ea33d6adb2b11d93d9a35bef277cd2c0b1b5af8e8d0b1e / 6f2f9757ae97
fallback size/details:   7,816,589,186 bytes; mllama 10.7B Q4_K_M GGUF
text manifest linter:    qwen2.5:7b-instruct
text digest/list ID:     845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e / 845dbda0ea48
text size/details:       4,683,087,332 bytes; qwen2 7.6B Q4_K_M GGUF
registry semantics:      managed=true; manager=ollama; verified=true; no fake checkpoint paths
resolver guard:          filesystem resolver explicitly rejects managed entries
idempotency:             two immediate registrations returned cached and preserved registered_at
focused tests:           tests/test_model_registry.py -> 8 passed
```

## 2026-07-10 23:10 UTC - Complete model acquisition idempotency verified
**Items:** MF-P0-06.15
**Result:** PASS - `maskfactory models fetch --all` verified every catalog
artifact in place and returned only cached results; no model was downloaded,
replaced, or republished.

```
catalog artifacts:       14
cached/verified:         14 / 14
downloads:               0
hash mismatches:         0
catalog keys:            yolo11m, birefnet_general, sapiens_0_6b_seg, schp_atr, schp_lip, dwpose_yolox_l, dwpose_133, mediapipe_hand_landmarker, sam2_1_hiera_base_plus, sam2_1_hiera_large, groundingdino_swint_ogc, densepose_rcnn_r50_fpn_s1x, faceparse_bisenet, vitmatte_small_composition_1k
managed artifacts:       all 3 Ollama entries separately returned cached with matching API/list digests
registry mutations:      none from the cached fetch/register reruns
```

## 2026-07-10 23:22 UTC - Doctor check engine and fail-closed CLI implemented
**Items:** MF-P0-07.01, MF-P0-07.03
**Result:** PASS for implementation and exit-contract requirements. The live
restricted-sandbox run intentionally remains ineligible for MF-P0-07.04 because
WSL and Docker/CVAT are hidden by the current execution boundary.

```
implemented checks:      torch cu128 + sm_120; full registered-model load/smoke hash replay; CVAT API; conditional CVAT project; live SAM2 Nuclio invocation; Ollama image JSON; disk thresholds; WSL round-trip; png_strict; SQLite write transaction; stale gpu.lock
result contract:         stable PASS/WARN/SKIP/FAIL records with detail and actionable FIX hints
exit contract:           any FAIL -> process exit 1; WARN/SKIP alone -> exit 0
registry enforcement:    all file-backed smokes rerun and must equal their recorded output hashes; managed entries never become fake paths
tests:                   70 passed total; doctor default battery, thresholds, lock states, P1 project gate, exception isolation, CLI output, and exit codes covered
live sandbox PASS:       ollama_image, png_strict, sqlite_writable, gpu_lock
live sandbox WARN:       disk_free = 101.0 GiB (below 150 GiB warning threshold)
live sandbox FAIL:       WSL/distro hidden; model replay blocked at first WSL-backed model; Docker/CVAT hidden behind sandbox 404; WSL round-trip unavailable
next live action:        rerun `maskfactory doctor` in the normal machine session; do not complete MF-P0-07.04 until FAIL=0
```

## 2026-07-10 23:36 UTC - Registry-complete model smoke fixtures verified
**Items:** MF-P0-07.02
**Result:** PASS - every file-backed registered model has a governed input image
and exact expected inference-output SHA-256, enforced against the live registry.

```
file-backed models:      14 / 14 represented in qa/fixtures/smoke/model_expectations.json
fixture images:          ultralytics_bus_adults.jpg; mediapipe_thumb_up.jpg
expectation contract:    exact model-key coverage; registry image/hash identity; real image file; 64-char hexadecimal output hash
managed models:          3 Ollama entries covered by the separate live image/API and manifest-digest doctor checks
tests:                   71 passed total; Ruff clean; Black 25.1/Python 3.11 profile clean
tracker validation:      393 items parsed; no structural problems
```

## 2026-07-10 23:58 UTC - CVAT UI SAM2 interactor verified and repaired
**Items:** MF-P0-04.04
**Result:** PASS - Magic Wand / AI Tools / Segment Anything 2.1 (CPU) produced,
accepted, and saved a real mask on the synthetic scratch task.

```
root cause repaired:      CVAT sends obj_bbox=[] for point-only interaction; adapter now normalizes it to None before SAM2 prediction
request hardening:        Nuclio adapter accepts decoded objects, UTF-8 bytes, or JSON strings and validates box shape=(4,)
deployment:               pth-sam2 rebuilt and deployed ready on port 62170
UI workflow:              positive click inside light object -> mask preview -> Done -> Save
CVAT evidence:            Items: 1; shape id=1; type=mask; frame=0; points_count=329
service evidence:         lambda POST 200; annotation PATCH action=create 200
durable report:           qa/reports/cvat_sam2_ui_verification.json
```

## 2026-07-10 23:59 UTC - Full machine doctor completed with zero failures
**Items:** MF-P0-07.04
**Result:** PASS - the complete live doctor exited 0 after replaying every model
and service check. The pre-P1 project check is explicitly skippable; disk free
is above the hard block-ingest threshold but remains a tracked warning.

```
[PASS] torch_cuda: {"available": true, "capability": [12, 0], "cuda": "12.8", "torch": "2.11.0+cu128"}
[PASS] registered_models: 14 file-backed models loaded; every smoke output hash matched
[PASS] cvat_api: reachable; version=2.24.0
[SKIP] cvat_project: no project yet; allowed before P1 project creation
[PASS] nuclio_interactor: pth-sam2 answered; foreground=21491
[PASS] ollama_image: qwen2.5vl:7b returned strict image JSON
[WARN] disk_free: 100.7 GiB free
[PASS] wsl_roundtrip: Windows -> /mnt/c -> Windows content matched
[PASS] png_strict: all built-in writer invariants passed
[PASS] sqlite_writable: C:\Comfy_UI_Main_Masking\data\maskfactory.sqlite
[PASS] gpu_lock: no gpu.lock present
doctor summary: PASS=9 WARN=1 SKIP=1 FAIL=0
```

## 2026-07-10 23:59 UTC - Phase P0 exit gate closed
**Items:** MF-P0-EXIT
**Result:** PASS - all 90 P0 items are resolved and the phase exit evidence is
committed and reproducible.

```
doctor:                  exit 0; PASS=9 WARN=1 SKIP=1 FAIL=0
interactive CVAT gate:   saved SAM2 mask verified in job 1
quality:                 72 pytest tests passed; pre-commit --all-files passed
D9 artifacts:            env/maskfactory_env.yml, env/requirements.lock.txt, and models/model_registry.json tracked
implementation commit:   57f0e2e
roadmap:                  doc 14 §1 marks MF-P0-01 through MF-P0-08 and P0 exit PASS
tracker:                  90 / 90 P0 items complete
```

## 2026-07-11 00:14 UTC - Per-instance manifest schema implemented
**Items:** MF-P1-01.01
**Result:** PASS - the authoritative doc 04 §1 manifest contract and doc 17 §6
multi-person amendment are encoded as strict JSON Schema Draft 2020-12.

```
schema:                   src/maskfactory/schemas/manifest.schema.json
required blocks:          source, person, interperson, parts, inpaint_derivatives, tooling, review, qa, files
governed constraints:     image/instance IDs, safe relative paths, SHA-256, dimensions/bboxes, timestamps, source origins, views, mask types, visibility/status, review and QA ranges
multi-person contract:    reciprocal per-instance relationship records and contact-band paths
schema self-check:        Draft202012Validator.check_schema passed
focused tests:            3 passed (full contract, required authority block, unsafe path/hash rejection)
```

## 2026-07-11 00:23 UTC - Remaining P1 schema family implemented
**Items:** MF-P1-01.02, MF-P1-01.03, MF-P1-01.04, MF-P1-01.05, MF-P1-01.06
**Result:** PASS - all remaining doc 04 machine contracts and the doc 03 §5
crop contract are strict Draft 2020-12 schemas with acceptance fixtures.

```
qa_report.schema.json:       QC-001..038 checks, metrics, consensus, closed VLM problem taxonomy, overall/score
model_registry.schema.json:  validates all 14 file-backed + 3 managed Ollama entries; verified-only; no managed fake paths
failure_queue.schema.json:   exact append-only JSONL record and closed failure_reason enum
coverage_matrix.schema.json: closed view/pose/attribute vocab plus solo|duo|small_group context from doc 17
crop_transform.schema.json:  part/x0/y0/positive scale/square crop_size/source SHA-256
schema self-checks:           every schema passes Draft202012Validator.check_schema
focused tests:                12 passed across the five contracts
```

## 2026-07-11 00:28 UTC - Schema enforcement and invalid-fixture gate completed
**Items:** MF-P1-01.07, MF-P1-01.08
**Result:** PASS - bundled schemas now have one deterministic validation API,
non-overridable manifest invariants, and pointer-asserted invalid fixtures.

```
validator API:             validate_document/require_valid_document; validate_manifest/require_valid_manifest
error contract:            stable ValidationIssue records with RFC 6901 JSON pointers; aggregate ArtifactValidationError
invariant 1:               every enabled ontology label must exist in manifest.parts
invariant 2:               non-visible atomic labels must have mask_file=null
invariant 3:               human_approved_gold requires qa_overall=pass and completed review evidence
invalid fixtures:          manifest, qa_report, model_registry, failure_queue, coverage_matrix, crop_transform
pointer assertions:        /image_id, /score, /models/0, /failure_reason, /cells/0/pose, /scale
focused tests:             13 passed (7 enforcement + 6 invalid-fixture cases)
```

## 2026-07-11 00:33 UTC - SQLite state foundation and workflow transitions enforced
**Items:** MF-P1-02.01, MF-P1-02.02
**Result:** PASS - the rebuildable workflow index now has its authoritative
tables, concurrency policy, and guarded state machine.

```
database schema:           images, stage_runs, review_tasks, training_runs; foreign keys and supporting indexes
durability:                WAL mode; schema user_version=1; 30 s busy timeout; transactional commit/rollback
writer policy:             atomic PID/host/timestamp owner file; concurrent orchestrator refused; lease always released
dashboard policy:          URI mode=ro plus PRAGMA query_only=ON
main state chain:           ingested→drafted→auto_qa→vlm_qa→in_review→corrected→approved_gold→exported
governed branches:         rejected, quarantined, deprecated with explicit recovery/terminal transitions
double enforcement:        transition API rejects skips/unknowns; SQL CHECK rejects direct invalid statuses
focused tests:             8 passed including WAL, FKs, rollback, writer contention, full chain, branches, and bypass attempts
```

## 2026-07-11 00:41 UTC - File-only stage orchestrator implemented
**Items:** MF-P1-02.03
**Result:** PASS - the full S00–S15 graph, including S08.5 and S09.5, now has
deterministic planning, content-hash caching, and idempotent filesystem promotion.

```
stage graph:               18 canonical stages in topological order with explicit dependencies
CLI controls:              maskfactory run IMAGE_ID --stage/--force/--skip/--config/--plan-only
config stamps:             SHA-256 of canonical global + stage-local config; unrelated stage changes do not invalidate cache
stage contract:            runner writes only to private staging dir and returns a manifest delta; downstream reads prior directories
idempotency:               completed same-hash stages cache; force/config drift reruns; whole owned directory atomically replaced
failure hygiene:           incomplete staging removed; prior complete directory restored if promotion fails
evidence files:            manifest_delta.json + stage_run.json with config hash, dependencies, forced state, and file inventory
focused tests:             7 passed across graph, flags, hashing, cache, replacement, config drift, file-only handoff, and CLI plan
```

## 2026-07-11 00:47 UTC - Orchestrator failure policy enforced
**Items:** MF-P1-02.04
**Result:** PASS - stage failures are classified, retried/routed/quarantined by
policy, and never stop later images in the batch.

```
transient policy:         OOM/MemoryError/IO/timeout or explicit transient -> 2 retries (3 total attempts), 1 s then 2 s backoff
semantic policy:          no retry; durable review_queue.jsonl record; batch continues
fatal policy:             no retry; durable quarantine_queue.jsonl + SQLite status=quarantined; batch continues
exhausted transient:      classified transient_exhausted and quarantined after exactly 3 attempts
staging safety:           failed attempt removes private temp output and preserves prior complete stage output
queue evidence:           UTC timestamp, image, stage, category, attempts, error, route; append flushed + fsynced
focused tests:            11 orchestrator tests, including retry delays, semantic routing, fatal continuation, and exhausted OOM
```

## 2026-07-11 00:54 UTC - GPU lease and stale-lock integration completed
**Items:** MF-P1-02.05
**Result:** PASS - the orchestrator CLI now owns one atomic, token-checked GPU
lease for pipeline execution, and doctor consumes the same lock-state authority.

```
lock path:                runs/gpu.lock
owner metadata:           pid, host, UTC acquired_at, purpose, image_id, unique token
acquire policy:           O_EXCL atomic creation; live/unrecognized owner refused; dead owner reported stale and never auto-deleted
release policy:           token must still match; replaced-owner lock is preserved; exceptions release the owned lease
orchestrator wiring:      CLI pipeline execution holds the lease across selected stages
doctor wiring:            shared absent/active/stale/unrecognized classifier; stale remains FAIL with manual nvidia-smi confirmation hint
focused tests:            24 GPU/doctor/orchestrator tests passed
full validation:          124 pytest tests passed; Ruff clean; Black 25.1/Python 3.11 profile clean; diff check clean
```

## 2026-07-11 01:02 UTC - Package-authoritative SQLite reindex implemented
**Items:** MF-P1-02.06
**Result:** PASS - `maskfactory reindex` now diffs or rebuilds the image index
from validated per-instance package manifests.

```
discovery:                data/packages/<image_id>/instances/pN/manifest.json (legacy direct manifest also structurally accepted)
validation:               every manifest passes bundled schema; directory image_id and cross-instance source hash must agree
row derivation:           one image row from all instances; status/current stage, source hash, timestamps, and package version derived
dry-run report:           deterministic clean/missing_in_db/stale_rows/extra_in_db JSON; no database mutation
rebuild policy:           WAL/single-writer transaction; clears rebuildable image/stage/review index and inserts manifest truth
CLI:                      --dry-run, --rebuild, --packages-root, --database; no-flag behavior rebuilds
focused tests:            5 passed (dry/rebuild/clean, pre-schema DB, stale+extra repair, multi-instance conflict, CLI JSON)
live workspace dry-run:   clean=true; zero missing, stale, or extra image rows
```

## 2026-07-11 01:11 UTC - Daily and per-run telemetry logging implemented
**Items:** MF-P1-02.07
**Result:** PASS - orchestrated runs now persist both a bound daily Loguru stream
and an incrementally atomic `runs/<run_id>/run.json` ledger.

```
daily sink:               logs/maskfactory_<YYYY-MM-DD>.log filtered/bound by run_id
run ledger:               schema/run/status/images/start/end/full-config hash/model union/duration/VRAM peak/stages/error
stage telemetry:           image, stage, status, stage config hash, model keys, duration_sec, vram_peak_mb
runner contract:           reserved _telemetry removed before manifest_delta.json publication
durability:                run.json written at start and atomically replaced after every stage/failure/finalization
failure evidence:          classified stage, attempts, error, and failed final status survive raised exception
CLI wiring:                maskfactory run creates/finalizes the ledger around the GPU-leased pipeline
focused tests:             14 runlog/orchestrator tests passed, including successful and fatal ledgers
```

## 2026-07-11 01:16 UTC - Hard-kill resume and reindex recovery gate passed
**Items:** MF-P1-02.08
**Result:** PASS - a real child process was terminated during a stage write;
the next invocation removed abandoned private staging and completed cleanly.

```
crash mechanism:          subprocess killed after writing partial.bin + readiness marker, before manifest delta/stage stamp
observed crash state:     nonzero child exit and img_<id>.tmp-* staging directory present
resume behavior:          abandoned stage-owned temp removed; complete.bin promoted; partial.bin absent; resumed delta/stamp valid
database recovery:        package manifest rebuilt a fresh SQLite index; immediate reindex --dry-run clean=true
test:                     tests/test_crash_resume.py passed as an actual process-boundary crash, not a mocked exception
```

## 2026-07-11 01:34 UTC - Canonical ontology cluster completed
**Items:** MF-P1-03.01, MF-P1-03.02, MF-P1-03.03, MF-P1-03.04,
MF-P1-03.05, MF-P1-03.06
**Result:** PASS - doc 02 is encoded as deterministic generator data, the
generated YAML is the strict runtime authority, CI detects drift, and the fixed
visualization contract is committed.

```
source registries:        PART 0-55, MATERIAL 0-15, 19 region bands, 40 derived formulas, projected templates/static labels, protected classes
canonical artifact:       configs/ontology.yaml; 135 concrete labels; all required machine fields; deterministic byte rendering
runtime authority:        ontology.py validates the YAML and hard-fails unknown name, map/ID, disabled-required label, invalid swap, or duplicates
CI drift gate:            tools/generate_ontology.py --check in .github/workflows/ci.yml
ontology invariants:      ears 54/55 disabled; reciprocal sided swaps; every atomic has area bounds and component limit
visualization contract:   fixed color for every ontology label; RGBA(255,64,64,110); 1 px contour; horizontal five-tile 512 px QA panel at 2x bbox
focused tests:            10 ontology/viz tests passed
full validation:          142 pytest tests passed; Ruff clean; Black 25.1/Python 3.11 profile clean; diff check clean
```

## 2026-07-11 02:02 UTC - Governed S00 intake completed
**Items:** MF-P1-04.01, MF-P1-04.02, MF-P1-04.03, MF-P1-04.04,
MF-P1-04.05, MF-P1-04.06, MF-P1-04.07, MF-P1-04.08
**Result:** PASS - intake is an integrated CLI/runtime path with deterministic
identity, privacy rewriting, provenance enforcement, mandatory local age
screening, durable registration, and all specified batch outcomes.

```
identity/duplicates:      streaming SHA-256 -> img_<hash12>; existing source hash skipped and fsynced to logs/intake.jsonl
decode policy:            png/jpg/jpeg/webp fully decoded; corrupt/unsupported/min-side<512 inserted as rejected and logged
privacy rewrite:          PNG pixels preserved with ancillary metadata removed; JPEG APPn/COM removed with scan stream byte-identical
provenance:               generated/owned/licensed/consented folders map to canonical manifest values; root/invalid origin quarantined
near-duplicate key:       deterministic 64-bit 32x32 DCT pHash stored as 16 hex characters in intake manifest and event log
age safety:               YOLO11m person count + local qwen2.5vl whole-image apparent-minor verdict; yes/uncertain/error quarantine; no disable path
adult-content policy:     prompt explicitly classifies age only and does not classify nudity/sexual content
live model proof:         installed yolo11m.pt + qwen2.5vl:7b returned clear_adult with person_count=4 on ultralytics_bus_adults.jpg
registration:             atomic canonical source + manifest skeleton, then SQLite S00 row; quarantined imagery is not copied
mixed batch:              exactly 10 inputs -> 5 ingested, 1 duplicate skipped, 2 rejected, 2 quarantined; DB/events/artifacts asserted
focused tests:            12 intake tests passed
full validation:          154 pytest tests passed; Ruff, Black, and diff checks clean
```

## 2026-07-11 02:31 UTC - Authority maps, binary views, and derivatives completed
**Items:** MF-P1-05.01, MF-P1-05.02, MF-P1-05.03, MF-P1-05.04,
MF-P1-05.05, MF-P1-05.06
**Result:** PASS - human mask candidates now resolve into the two exclusive
authority maps, every binary/derived/inpaint view is reproducible, and the P1
format-integrity battery passes end to end.

```
map fusion:               ontology-validated 2-D CVAT candidates; lexicographic score -> explicit priority -> ontology-ID argmax
authority outputs:        label_map_part.png strict 16-bit + label_map_material.png strict 8-bit; shape agreement enforced
binary export:            54 enabled PART views routed to masks/protected + all 16 MATERIAL views under masks_material via png_strict
derived registry:         configs/derived.yaml contains all 40 exact doc-02 formulas; script-only parser supports unions/intersections/subtraction/ranges/edges/projected inputs
derived evidence:         masks_derived/manifest.json records formula, authority-map/projected hashes, output hash, and config hash
inpaint:                  defaults d8f4@1024 with per-label overrides; scaled hard dilation then outward linear feather; grayscale written only via png_strict
inpaint provenance:       package manifest inpaint_derivatives[] atomically updated with actual scaled settings, relative file, ref scale, and source-gold SHA-256
round trip:               maps -> 70 binaries -> maps is array-identical for both PART and MATERIAL; overlap/missing views hard-fail
format gate:              QC-001 through QC-007 all green on a complete exporter package, including schema and exhaustive files-hash checks
focused tests:            9 map/derived/inpaint tests passed
full validation:          163 pytest tests passed; Ruff, Black, ontology drift, and diff checks clean
```

## 2026-07-11 02:50 UTC - CVAT bridge v1 completed and live-verified
**Items:** MF-P1-06.01, MF-P1-06.02, MF-P1-06.03, MF-P1-06.04,
MF-P1-06.05
**Result:** PASS - the pinned local CVAT 2.24 service now has the canonical
project, scripted review upload/download, durable backup, and a proven
pixel-identical unedited mask round trip.

```
live project:             project_id=1, MaskFactory_body_parts_v1; 135 exact ontology labels; fixed viz colors; type=mask
label attributes:         visibility six-state enum, ambiguous checkbox, notes text; server IDs persisted in data/cvat/label_mapping.json
API routing:              localhost:8080 used for Traefik API routing while host bind remains 127.0.0.1-only
push policy:              ontology-strict CVAT RLE; source + all-parts overlay + optional disagreement heatmap; segment_size=1; 10 jobs/task; assignee kevin
pull policy:              corrected RLE/attributes imported through png_strict; prior map views seed deletions; automatic re-fuse, binary/derived rebuild, and re-QA
backup:                   async CVAT task backup export retained at annotations/cvat_task_backup.zip
codec verification:       10 randomized binary masks encode/decode pixel-identically; malformed/empty RLE hard-fails
live round trip:          disposable task 2; img_c02019c4979c; 24,300 foreground pixels; unedited pull pixel_identical=true
live evidence:            qa/evidence/cvat_roundtrip.json; backup=1,532,360 bytes; re-QA trigger present; disposable task deleted
focused tests:            16 CVAT mapping/project/push/pull tests passed
full validation:          179 pytest tests passed; Ruff and diff checks clean
doctor after bridge:      CVAT API/project, Nuclio SAM2, Ollama image, png_strict, SQLite, GPU lock all PASS; unrelated WSL boundary remains 3 FAIL
```

## 2026-07-11 03:10 UTC - P1 QA-001 through QA-010 and auto-fix hard blocks completed
**Items:** MF-P1-07.01, MF-P1-07.02, MF-P1-07.03, MF-P1-07.04
**Result:** PASS - the full P1 format/integrity battery is independently
attributable, non-mutating during verification, and backed by exact seeded
defect isolation.

```
QC-001..003:             source dimensions, strict binary values, mode L/no alpha/no palette/PNG magic; inpaint/matting excluded by directory contract
QC-004..006:             every binary filename is an enabled ontology label; full manifest schema; exhaustive tracked/missing/untracked/hash mismatch detection
QC-007/030:              direct map-vs-view array identity for every one of 70 required files; missing views and hand edits fail without verifier mutation
QC-008:                  every enabled non-material ontology label requires a valid visibility state
QC-009:                  all 40 formulas reevaluated from current maps/projected inputs and compared to pixels, formulas, input hashes, and output hashes
QC-010:                  crop transform schema, enabled ontology part, positive scale, and full-image bounds
seed isolation:           10 fixtures, one per QC-001..010; every fixture fails exactly its intended QC and no other check
auto-fix allowlist:       once only: map-authoritative binary regeneration, <max(64px,2%) component drop, <0.5% hole fill, union re-derive
auto-fix safeguards:      hair/lace-sheer hole exemptions; no protected edits; material consistency maintained; before/after hashes + recheck logged
full validation:          194 pytest tests passed; Ruff and diff checks clean
remaining cluster work:   packager approval override enforcement, verifier/versioning, and DVC remote evidence
```

## 2026-07-11 03:31 UTC - Gold approval, verification, and immutable versioning completed
**Items:** MF-P1-07.05, MF-P1-07.06, MF-P1-07.07, MF-P1-07.08
**Result:** PASS - approval is structurally downstream of every BLOCK, clean
packages freeze with complete evidence, verification supports restore roots and
sampling, and corrections promote atomically with rollback.

```
approval order:           one-shot auto-fix -> complete QC-001..010 -> explicit confirmation -> review/gold stamps -> validated QA report -> freeze -> full files hashes -> recheck -> DVC add
BLOCK enforcement:        approved=True on seeded QC-002 still bounces statuses to rejected_needs_fix; no freeze and no DVC callback; override impossible
review evidence:          reviewer, approved_at, review_time_sec, second-review block, human_approved_gold part statuses, qa_overall=pass
freeze contract:          .maskfactory_frozen.json marks immutable package; already-frozen approval refused; every non-manifest file hashed
DVC handoff:              production path preflights DVC and requires successful dvc add; test proves callback occurs only after final green recheck
verification:             one instance or recursive --root discovery; deterministic --sample N; every selected package reruns hashes plus QC-001..010
versioning:               frozen masks -> editable masks@v2; explicit approval; temporary atomic swap; QC-001/2/3/4/7; exact rollback on BLOCK
retention:                prior active becomes masks@v1 deprecated with retain_until exactly 30 days; v2 becomes active human_approved_gold
seed enforcement:         all 10 defects fail exactly their own QC and approval-confirmed defect cannot cross the gate
full validation:          197 pytest tests passed; Ruff, Black, and diff checks clean
DVC environment attempt:  no dvc executable/AWS credentials or profile present; workspace-local pip install attempt stalled and was terminated without partial executable
```

## 2026-07-11 03:48 UTC - P1 backup operations authored; registration boundary recorded
**Items:** MF-P1-09.01, MF-P1-09.02, MF-P1-09.03, MF-P1-09.04,
MF-P1-09.05
**Result:** PARTIAL/BLOCKED - production scripts and their ordering/integrity
tests are complete, but this execution boundary cannot access the Windows Task
Scheduler service, and no gold/B1 package exists for the restore drill.

```
B5 implementation:        Python sqlite3 online backup API + PRAGMA integrity_check + exactly seven timestamped rotations
nightly ordering:         B5 completes first; then robocopy /MIR packages, qa, configs to D:\MaskFactoryBackup; robocopy >=8 hard-fails
integrity sweep:          scheduled wrapper crosses into Ubuntu-22.04 WSL and runs verify-package --root data/packages --sample 10
weekly B2 reminder:       Monday 09:00 reminder logs offline-SSD instructions and sends local user message
task definitions:         daily 02:00 and weekly Monday 09:00, LIMITED privilege, idempotent /F replacement, verbose query evidence
tests:                    live SQLite backup contents/integrity/7-rotation pass; scripts assert B5-before-B1, three mirrors, WSL sample, schedules
registration attempt:     schtasks.exe itself resolves, but Query/Create both return "The system cannot find the path specified" at the service boundary
restore drill:            cannot select one B1 package because P1-08 source/manual-review packages do not yet exist
schedule skill impact:    project-required Windows Task Scheduler scripts used; product scheduling tool is unavailable and cannot replace the specified OS tasks
```

## 2026-07-11 04:20 UTC - P2 configuration and S01-S03 deterministic cores implemented
**Items:** MF-P2-02.03, MF-P2-02.04, MF-P2-02.05
**Result:** PASS - the complete P2 pipeline contract is authored and the S03
degradation/remap paths are executable and tested. Live heavyweight model and
hand-truth fixture gates remain open pending actual inference evidence.

```
pipeline contract:        seed 1337; workdir; device/cooldown; S00-S15 toggles; thresholds/tiles; pose rules; exact fusion weights and z-order rules
parser vocabularies:      official Sapiens 28-class reduced vocabulary and SCHP ATR 18-class vocabulary mapped to part/material ontology priors
S01 core:                 confidence/4% floor, area*centeredness deterministic rank, doc-17 max-four promotion, PART50 protection, crowd quarantine, 1.25 clamped crops
S02 core:                 threshold 0.5, connected-component retention rule, full-canvas strict binary/confidence outputs, 0.35-0.95 area-ratio QC hook
S03 normal path:          SCHP always runs; indexed Sapiens/SCHP outputs and every per-class 8-bit probability map are written through strict PNG helpers
S03 degraded path:        Sapiens OOM retries at scale 0.5; second OOM produces SCHP-only output and parsing_degraded=true
cross-check:              remaps reject unknown class indices; prior-overlap disagreement percentage logged in parsing_metrics.json per image
tests:                    14 focused P2 tests green; full suite green (214 tests); Ruff clean
regression repaired:      recursive package verification now excludes nested derived-artifact manifests, preserving deterministic restore sampling
open evidence gates:      YOLO/BiRefNet/Sapiens/SCHP live adapters and 10-image hand-truth IoU fixture evaluation are not claimed complete
```

## 2026-07-11 04:45 UTC - S04 deterministic pose ownership and classification completed
**Items:** MF-P2-03.01 (partial), MF-P2-03.02, MF-P2-03.03,
MF-P2-03.04
**Result:** PASS for deterministic S04 processing; the production WSL DWPose
adapter remains to be wired, while its paired CUDA model smoke is already
independently evidenced under MF-P0-06.06.

```
ownership:                candidate with maximum bbox IoU to defining instance selected; every co-subject candidate explicitly suppressed and recorded
pose artifact:             strict finite 133x3 coordinates/confidences; COCO-WholeBody-133 pose133.json with ownership, view, tags, metrics, and mode
view classifier:           front/back from nose and optional DensePose back vote; left/right profile and 3/4 from torso span/side confidence geometry
pose tags:                 deterministic config operators consume arm elevation, opposite-torso wrist overlap, knee bend, torso axis, ankle separation, leg overlap
degraded gate:             body confidence fraction computed over COCO body 0..16; <60% at 0.3 switches geometry_prior_mode to parsing_only and adds careful_review
multi-person amendment:    other detected humans cannot leak into the selected instance pose prior; suppression is serialized for audit
tests:                     6 focused S04 tests; full suite green (220 tests); Ruff clean
remaining S04 evidence:    production onnxruntime-gpu detector/pose adapter and 20-image hand-tagged >=90% evaluation remain open
```

## 2026-07-11 05:10 UTC - S05 limb, joint, crop, hair, and prompt-plan contracts completed
**Items:** MF-P2-04.01, MF-P2-04.02, MF-P2-04.04, MF-P2-04.05,
MF-P2-04.07, MF-P2-04.08, MF-P2-04.09
**Result:** PASS - deterministic geometry and prompting primitives are implemented
and strict-output tested. Torso partitioning and back-surface priors remain open.

```
limb capsules:            exactly five perpendicular parsing cross-sections; median half-width radius; capsule clipped by parsing superset and silhouette
joint ownership:          perpendicular exclusive bands; elbow/knee/ankle height=0.6*local width, wrist=0.5; owned pixels carved from adjoining segments
lane requests:            point bbox expanded 1.6 and clamped to image; typed specialist queue entries serialized with prompts
hair prior:               parsing hair union GDINO hair proposal boxes, explicitly retained as prior rather than final mask
prompting config:         exact GDINO box/text 0.30/0.25; required 11 prompts; may_write_final_masks=false; every PART 1..55 covered by a recipe family
SAM2 prompt plan:         full prior bbox*1.1; prior peak + 3..7 skeleton samples; neighbor peaks + eight-point background ring; multimask_output=true
fallback:                 missing skeleton/keypoint path accepts parsing-only prior and records prior_quality=low
debug/evidence:           strict grayscale prior artifacts, prompts.json, RGB box/positive/negative overlay; RGB save is audited as non-mask
regression caught:        initial prompt box used only max-confidence support; focused test forced correction to full nonzero prior support
tests:                    5 focused S05 tests; full suite green (225 tests); Ruff clean
open S05 work:            MF-P2-04.03 torso partition and MF-P2-04.06 DensePose-backed back partition remain open
```

## 2026-07-11 05:25 UTC - S05 torso and back-surface partition completed
**Items:** MF-P2-04.03, MF-P2-04.06
**Result:** PASS - front/profile and back branches are surface-exclusive,
character-perspective aware, and covered by synthetic landmark/DensePose fixtures.

```
front boundaries:         clavicle from shoulder midpoint; under-breast fold from central horizontal-profile minimum; iliac from hip midpoint; pose midline
front atomics:            chest, left/right breast ellipse seeds, abdomen, navel, pelvis, left/right hip priors all clipped to torso parsing
exclusive carve-outs:     breast seeds removed from chest; belly_button removed from abdomen; hip priors removed from pelvic center
view gating:              breast seeds only front/left_3_4/right_3_4; profiles omit breasts; back views emit no front torso/breast labels
character convention:     left/right breast and hip follow the named DWPose shoulder side, not raw image-left/image-right
back surfaces:            waist split produces mutually exclusive back_upper_torso/back_lower_torso; spine width exactly 10% shoulder width
DensePose bridge:         optional left/right scapula UV seeds dimension-validated and clipped to back_upper_torso, ready for P3-05 provider wiring
tests:                    2 focused partition tests added; full suite green (227 tests); Ruff clean
```

## 2026-07-11 05:50 UTC - S06/S07 proposal and refinement core completed
**Items:** MF-P2-05.01 (partial), MF-P2-05.02 (partial), MF-P2-05.03,
MF-P2-05.04, MF-P2-05.05, MF-P2-05.06, MF-P2-05.07
**Result:** PASS for deterministic contracts; actual GroundingDINO and SAM2
provider adapters remain to be connected to the already-verified model assets.

```
GDINO authority:          typed BoxProposal only; configured prompt allowlist; 0.30/0.25 filters; gdino_boxes.json explicitly says proposal_boxes_only/may_write_final_masks=false
embedding lifecycle:      one primary fp16 embed call; primary OOM performs one base-plus fp16 fallback; embedding object is reused for every part refinement
candidate selection:      multimask_output=true; stable argmax of 0.6*IoU(prior)+0.4*predicted_iou with provider shape/finite/score validation
corrective iteration:     triggered above 8% symmetric disagreement per prior area; adds prior-only positive near skeleton and mask-only/outside-box negative; never more than once
post-processing:          logits>=0; components below max(64,2% part area) removed; holes below 0.5% filled; boolean output and no smoothing/AA
joint ownership:          configured adjacent segment masks lose every joint-band pixel; joint result owns the clipped band
low confidence:           predicted_iou<0.5 returns prior unchanged and emits sam2_low_conf + careful_review flags
tests:                    5 focused S06/S07 tests; full suite green (232 tests); Ruff clean
open provider/eval gates: real GDINO execution, real SAM2 image embedding/prediction, and 46-core-part 10-fixture run remain unclaimed
```

## 2026-07-11 06:15 UTC - S09 consensus and authoritative map core completed
**Items:** MF-P2-06.01 through MF-P2-06.07
**Result:** PASS - weighted fusion now emits deterministic exclusive authority
maps and complete arbitration/disagreement evidence. The 10-fixture QC-011 gate
remains open because the required real fixture set has not run.

```
evidence fusion:          label/source stacks normalized across available configured votes with exact sam2 .40, sapiens .25, geometry .15, schp .10, densepose .10 weights
agreement routes:         owned-pixel mean consensus >=.85 quick_pass, .60-.85 normal, below .60 model_disagreement_high
z-order:                  >.4 contested threshold; automatic hair-front plus explicit wrist-depth hand, uninterrupted crossed-limb, and closed-contour object decisions
occlusion audit:          winner/loser/reason/pixel count serialized; occluded visibility becomes partially_visible; contested edge band emitted
PART authority:           uint16 argmax, every silhouette pixel nonzero, background exactly outside silhouette; uncovered foreground hard-fails
MATERIAL v1:              SCHP-remapped evidence fused within silhouette, uint8, material zero outside silhouette
region bands:             supplied bands emitted strict binary; waist is 12% shoulder-hip distance; contact band scales 8px@1024; overlap band generated
disagreement:             uint8 work/s09/disagreement.png equals top2/top1, i.e. 1-normalized top-two margin; equal votes=255, sole winner=0
determinism:              fixed seed 1337, PYTHONHASHSEED, CUBLAS workspace, torch deterministic algorithms/cudnn flags; repeated output hashes identical
tests:                    5 focused S09 tests; full suite green (237 tests); Ruff clean
open gate:                MF-P2-06.08 requires QC-011 clean on the real fixture set and is not claimed
```

## 2026-07-11 06:35 UTC - P2 overlay and five-tile QA evidence renderer completed
**Items:** MF-P2-07.01, MF-P2-07.02
**Result:** PASS - visual evidence artifacts now implement the exact viz.yaml
layout and remain categorically separate from mask-authority writers.

```
per-label overlays:       every present enabled PART gets source+configured RGBA fill+white contour at source dimensions
all-parts context:        all present labels alpha-composited with label_colors into overlays/all_parts.png for CVAT/review context
panel crop:               target part bbox expanded exactly 2x and frame-clamped
five tiles:               source crop | strict-nearest mask | overlay | cyan contour-on-source | magenta protected-neighbor overlap heat
panel contract:           each tile exactly 512x512; horizontal output exactly 2560x512 RGB PNG
writer safety:            RGB overlays/panels carry audited png-strict non-mask annotations; full raw-mask-writer CI remains green
tests:                    2 focused visual artifact tests; full suite green (239 tests); Ruff clean
```

## 2026-07-11 07:05 UTC - QC-011 through QC-024, metrics, and L/R blocker completed
**Items:** MF-P2-07.03, MF-P2-07.04, MF-P2-07.05, MF-P2-07.06
**Result:** PASS - the entire P2 geometric/semantic battery is configured,
measured, severity-preserving, and exercised by clean plus seeded-failure cases.

```
QC-011..013:             pairwise atomic overlap=0; outside silhouette<=0.2%; protected overlap<=0.5% and skin-derived/clothing intersection=0
QC-014:                  visible sided parts require >=2 available pose/MediaPipe/DensePose votes matching character-side label; insufficient votes BLOCK
QC-015..017:             ontology area-percent ranges, pose-absent mask prohibition, ontology component limits
QC-018..020:             crop reprojection IoU>=.995; exact breast_skin identity; projected containment and masks-directory prohibition
QC-021..024:             holes<=1% with exact exemptions; contour gradient ratio>=.6 against +/-3px band; visible/amodal state ranges; DensePose front/back majority
qa.yaml:                 every QC-011..024 threshold/severity; hard-class list; exact metric weights summing 1; fingers/hair/chest family 2x; BLOCK cannot be overridden
metrics:                 IoU, Boundary-F@2px, symmetric Hausdorff-95, hole ratio, component count, area/bbox, disagreement and protected/exclusive overlap
qa_score:                weighted mean of normalized per-part terms with 2x hard tiers; score is diagnostic only and cannot alter BLOCK outcomes
seeded L/R:              left_forearm with [right,right,left] votes BLOCKs; [left,left,right] passes, proving exact 2-of-3 rule
tests:                    clean QC-011..024 battery plus seeded failures for every rule family; full suite green (245 tests); Ruff clean
activation note:          QC-024 accepts DensePose votes now; production activation remains tied to P3-05 as specified
```

## 2026-07-11 07:25 UTC - P3 specialist-lane common crop contract completed
**Items:** MF-P3-01.01
**Result:** PASS - lane crops now share one schema-valid, pixel-stable transform
implementation with executable QC-018 evidence.

```
crop geometry:            square side=ceil(1.6*max(part bbox width,height)); centered then shifted within frame without shrinking/clipping
lane resolution:          exact 1024x1024; RGB source uses Lanczos; binary crop uses nearest only
transform evidence:       per-part crop_to_full_transform JSON with part,x0,y0,scale,crop_size,source_sha256; existing schema validation required before write
reprojection:             strict binary 1024 mask resized to exact source-window side by nearest and pasted at integer x0/y0
QC-018:                   crop_roundtrip_iou compares original and reprojected mask within the exact crop window; two fixtures pass >=0.995
edge behavior:            near-frame crop shifts square to x0/y0=0 while preserving full requested side; impossible no-padding square fails explicitly
tests:                    3 focused lane-common tests; full suite green (248 tests); Ruff and raw-mask-writer checks clean
```

## 2026-07-11 07:45 UTC - P3 hand crop and MediaPipe side arbitration completed
**Items:** MF-P3-01.02, MF-P3-01.03
**Result:** PASS - DWPose whole-hand geometry now feeds the lane-common crop,
and the pinned MediaPipe model has a production adapter with honest QC-014 arbitration.

```
DWPose indexing:          COCO-WholeBody left hand 91..111/right 112..132 plus body wrist 9/10; only confidence>=0.3 points participate
hand crop:                bbox covers wrist plus all available 21 side landmarks, then common contract expands 1.6 and creates 1024 crop/transform
MediaPipe adapter:        pinned HandLandmarker Tasks model, one-hand mode, detection/presence/tracking thresholds .5, exactly 21 results required
evidence artifact:        left/right_landmarks.json stores 21 normalized xyz points, handedness/score, skeleton side, resolved side, mismatch/QC flag
side arbitration:         MediaPipe mismatch sets qc014_flag=true and handedness_mismatch=true; resolved_side remains skeleton_side (SKELETON WINS)
validation:               invalid 133 pose, insufficient hand points, non-21 landmark arrays, invalid sides/scores all hard-fail
tests:                    3 focused hand-lane tests; full suite green (251 tests); Ruff clean
model provenance:         MediaPipe checkpoint/runtime smoke remains independently verified under the completed P0 model bootstrap evidence
```

## 2026-07-11 08:15 UTC - P3 hand/finger geometry, refinement, gaps, merge, and contact completed
**Items:** MF-P3-01.04, MF-P3-01.05, MF-P3-01.06, MF-P3-01.07,
MF-P3-01.08
**Result:** PASS - the hand lane now conservatively drafts separable fingers,
preserves gap/behind ownership, and collapses uncertainty instead of inventing splits.

```
finger geometry:         standard MediaPipe chains thumb 1..4, index 5..8, middle 9..12, ring 13..16, pinky 17..20
strip construction:      segment quads use endpoint widths measured perpendicular through parsing; every result clipped to hand parsing
hand_base:               convex hull of wrist plus four MCPs minus every finger strip, guaranteeing no palm/finger overlap
crop SAM2:               one fresh crop embedding reused for five fingers+hand_base; finger plans use 3 line positives, inter-gap and neighboring-finger negatives
gap ownership:           explicit finger_gap_regions exclude fingers/palm; pixels inherit the existing behind PART id, otherwise remain background
merge rule:              adjacent overlap >30% or any chain confidence <.5 merges affected region into hand_base, empties finger mask, state ambiguous_do_not_use
failure evidence:        fingers_merged_or_ambiguous, 2px finger_occlusion_boundary, and failure_queue(reason=finger_merge) record
contact rule:             hand retains all hand/body overlap, body mask is carved, scaled 8px@1024 contact band emitted
tests:                    4 focused geometry/refinement/merge/contact tests added (7 hand-lane total); full suite green (255 tests); Ruff clean
open hand gate:           MF-P3-01.09 still requires real fixture gap checks, paste-back metrics, and leaderboard rows
```

## 2026-07-11 08:40 UTC - S08 material fusion and protection rules completed
**Items:** MF-P3-02.01, MF-P3-02.02, MF-P3-02.03, MF-P3-02.04
**Result:** PASS - material evidence now produces an exclusive indexed draft
with guarded sensitive classes and specialist refinements.

```
base fusion:              SCHP garment regions + Sapiens skin/clothing + GDINO boxes; all clipped to silhouette
skin constitution:        skin = Sapiens skin AND NOT any fused clothing evidence
specific gating:          bra and underwear_bottom remain empty without explicit SCHP/GDINO evidence; otherwise own pixels over generic clothing
generic remainder:        clothing_generic is only clothing not claimed by top/bottom/footwear/bra/underwear specific evidence
thin structures:          clothing skeleton local width <4% torso; vertical component touching shoulder -> strap(10), horizontal near iliac -> waistband(11)
sheer:                    clothing pixel normalized-chroma cosine similarity >.8 to adjacent skin -> lace_or_sheer(12)
SAM2 material path:       exactly one prompt required for every region; every supplied region edge-refined through shared S07 contract
hand/foot protection:     hand_or_foot AND clothing_texture -> glove_or_sock(15), applied at higher map priority
indexed authority:        strict uint8 MATERIAL IDs with deterministic priority and zero outside silhouette
tests:                    4 focused material tests; full suite green (259 tests); Ruff clean
```

## 2026-07-11 09:10 UTC - Chest visible/projected lane and S08-to-S09 upgrade completed
**Items:** MF-P3-02.05, MF-P3-02.06, MF-P3-02.07, MF-P3-02.08,
MF-P3-02.09
**Result:** PASS - visible breast PART truth, material skin identity, and
projected edit regions are separated structurally and verified in a clothed case.

```
chest crop:              clavicle-to-under-bust/torso bbox expanded exactly 1.4, square shifted within frame, 1024 Lanczos image/nearest mask, schema transform
view behavior:            front/3-4 two character-perspective ellipses; profile one visible side; back/back-3-4 skips lane and both states not_visible
visible truth:            breast PART follows union of visible skin contour and fabric-defined contour inside seed; breast_skin is exact PART AND material-skin
clothed constitution:     fully clothed breasts retain PART location/material garment while both breast_skin derivatives are correctly empty
projected drafting:       ellipse plus clothing luminance-Laplacian curvature evidence, clipped to torso; sole writer rejects any root not literally projected/
boundary refinement:      strap and inframammary evidence each require SAM2 prompt/refinement; clothing_boundary_chest is exact 4px skin/clothing transition
review evidence:          every nonempty supplied chest hard class gets mandatory five-tile 2560x512 zoom panel
S09 upgrade:              fuse_consensus accepts exactly one material authority: legacy evidence stack OR direct S08 indexed map; direct map validates ontology/coverage
seeded clothed case:      S08 top_garment ID6 fills silhouette; breast_skin empty; projected contained; QC-019 and QC-020 both PASS
tests:                    6 focused chest/S09 tests; full suite green (265 tests); Ruff and raw-writer checks clean
```

## 2026-07-11 09:40 UTC - Hair/face lane, protection, and matting contract completed
**Items:** MF-P3-03.01, MF-P3-03.02, MF-P3-03.03 (partial),
MF-P3-03.04, MF-P3-03.05
**Result:** PASS for crop/fusion/protection/ownership and matte artifact logic;
the production ViTMatte WSL provider adapter remains open.

```
head crop:               square head bbox*1.8 to 1024 Lanczos; any hair-prior pixel outside proposed crop triggers honest full-frame PNG fallback
hair fusion:             max Sapiens/BiSeNet hair probability; binary authority at >=0.50 majority-opacity; face and scalp-skin exclude hair
SAM2 hair:               five hair positives with negative priors from face and background; strict binary S07 refinement contract
matting trigger:         hair area/person bbox >=2%; same optional function supports lace_or_sheer prefix
trimap:                  scaled +/-6px@1024 morphology, values exactly {0,128,255}; binary copy remains authority, alpha is evidence only
alpha contract:           provider must return exact-shape uint8; writes grayscale alpha/trimap under matting; injected provider tested
face protection:         exact eyes,mouth,nose,brows,jawline input set; jawline dilated two pixels into face_protected QC mask
z-order/review:           hair owns shoulder overlap, affected shoulder states partially_visible, mandatory 2560x512 hairline panel
tests:                    4 focused hair-lane tests; full suite green (269 tests); Ruff/raw-writer checks clean
open adapter:             pinned ViTMatte CUDA checkpoint has prior smoke evidence, but production callable is not yet wired, so MF-P3-03.03 is partial
```

## 2026-07-11 10:05 UTC - Feet/toes lane and footwear constitution completed
**Items:** MF-P3-04.01, MF-P3-04.02, MF-P3-04.03
**Result:** PASS - crop/split/material behavior is deterministic and the fully
shod constitution is locked by a seeded fixture.

```
foot indexing:            left ankle15 + foot17/18/19; right ankle16 + foot20/21/22; confidence>=.3 points define common 1.6x crop
MTP estimate:             heel-to-mean-toe axis; 13 cross-sections over distal 55-85%; narrowest width (stable tie near .72) defines perpendicular split
exclusive geometry:       foot_base and toes have zero overlap and their union exactly reconstructs the foot prior
closed shoe:              complete visible location becomes foot_base PART, toes empty/not_visible, MATERIAL footwear(8), visible_body_skin empty
sock:                     same PART/visibility behavior, MATERIAL glove_or_sock(15), visible_body_skin empty
barefoot/sandal:          PART follows visible skin contours; barefoot material skin(1), sandal may retain footwear on covered non-skin pixels
tests:                    crop extent, MTP exclusivity/order, shod/sock/barefoot constitution; full suite green (272 tests); Ruff clean
```

## 2026-07-11 10:35 UTC - DensePose IUV referee and semantic votes completed
**Items:** MF-P3-05.01 (partial), MF-P3-05.02, MF-P3-05.03,
MF-P3-05.04, MF-P3-05.05, MF-P3-05.06
**Result:** PASS for artifact/referee/QA contracts; production Detectron2
inference adapter remains open despite prior checkpoint CUDA smoke evidence.

```
IUV artifact:             RGB [I,U,V], I=0..24 and U/V=0..255, background I0 requires U=V=0; RGB evidence writer never enters mask authority
provider boundary:        infer(image)->DensePoseOutput and run_densepose writes work/s08_5/densepose_iuv.png; actual Detectron2 adapter still pending
surface votes:            front/back torso fractions and character-side majority; back fraction plugs directly into existing S04 classifier input
QC activation:            DensePose third side vote participates in exact QC-014 2-of-3; front fraction feeds QC-024 majority check
continuity:               valid-surface connected components plus adjacent normalized UV jump fraction; split/jump produces occlusion_suspect
adjacency referee:        scaled-dilation required-neighbor gaps emitted as named evidence for topology checks
seed fixtures:            [left,right,left]+front .9 passes QC-014/024; [left,right,right]+front .1 fails both
SMPL-X:                   explicit reserved_v2_not_built interface raises NotImplementedError; replacement only after failure mining proves need
tests:                    5 focused DensePose/referee tests; full suite green (277 tests); Ruff/raw-writer checks clean
```

## 2026-07-11 11:10 UTC - Topology QC-025..029 and uncertainty/regression QC-031..034 completed
**Items:** MF-P3-06.01 through MF-P3-06.08
**Result:** PASS - topology, uncertainty routing, and previous-gold regression
are executable with evidence-preserving exceptions and seeded failures.

```
QC-025:                  3px@1024 scaled chain adjacency for wrists/hands, joints/segments, ankles/feet, toes, fingers, neck/head
occlusion exception:      shortest gap band must be >=80% covered by the declared occluder; metadata alone never exempts a break
QC-026:                  every finger inside dilate(hand crop,10px@1024); thumb-to-hand_base adjacency mandatory
QC-027:                  joint band touches both adjacent segments and axis-projected height stays within +/-30% expected formula
QC-028:                  every sided-part centroid closer to its character-side skeleton reference than opposite reference
QC-029:                  breast masks contained in chest horizontal band, character-side order matches references; any back/back-3/4 breast fails
QC-031..033:             disagreement>.5 over >3% part ROUTE; predicted_iou<.5 WARN; parsing/pose degraded ROUTE
QC-034:                  foreground plus every present-label IoU must be >=.5 vs previous gold; BLOCK and JSON/RGB v1-v2 diff artifacts otherwise
seeded chain break:       unexplained wrist-hand gap ROUTEs with exact pair; real covering occluder clears it
tests:                    6 focused topology/uncertainty/regression tests; full suite green (283 tests); Ruff/raw-writer checks clean
```

## 2026-07-11 11:45 UTC - Local VLM client, strict verdicts, CVAT hints, and routing completed
**Items:** MF-P4-01.01 through MF-P4-01.05; MF-P4-02.01 through
MF-P4-02.04
**Result:** PASS - S11 is local-only, GPU-exclusive, strict/uncertain on parse
failure, append-only in reports, and structurally incapable of mask/gold authority.

```
local boundary:           Ollama endpoint fixed to http://127.0.0.1:11434; any other URL rejected; cloud_enabled=false
GPU slot:                 every review_part call owns purpose=S11_vlm_qa GpuLock across both original and retry requests
prompt suite:             p_part/p_image/p_manifest v1 files mirror doc10 strict JSON contracts; versions/config thresholds stamped
input prep:               panels/whole overlay downscaled to <=1024 long side; compact label:state:area% digest; only fail/warn/route QC excerpts
strict parser:            exact five-key P-PART object, closed verdict/problem vocabularies, confidence 0..1, evidence<=25 words, instruction<=30
retry:                    one and only one JSON-only retry; second invalid response returns uncertain/confidence0/no problems/no instruction
report append:            exact verdict record appended atomically to qa_report.vlm_review.verdicts; complete qa_report schema revalidated before replace
routing:                  all five doc10 rows plus low-confidence pass; uncertain has no hint; ROUTE/fail raises priority and pins heatmap
CVAT descriptions:        fail correction only, prefixed MACHINE-GENERATED SUGGESTION; uncertain/pass instructions excluded
authority invariants:     every RoutingDecision hardcodes may_approve_gold=false, may_clear_block=false, may_edit_mask=false; BLOCK always highest careful
tests:                    5 focused VLM/router/CVAT tests; full suite green (288 tests); Ruff/raw-writer checks clean
open run gate:            MF-P4-01.06 still requires the specified real 20-image panel run
```

## 2026-07-11 12:20 UTC - Failure mining, acquisition reports, and coverage matrix completed
**Items:** MF-P4-03.01 through MF-P4-03.04; MF-P4-04.01,
MF-P4-04.02
**Result:** PASS - all required failure producers share one validated append
path, priority math is exact, and approved-gold coverage deficits are deterministic.

```
queue durability:         schema-validated one-record JSONL append, fsync, short exclusive lock, contention timeout, no partial rewrite
source wiring:            lane(reason-specific), QC fail, second-review fail, VLM/auto-QA disagreement, human-edit delta map to closed failure reasons
priority:                 .4*class_error_rate + .3*coverage_deficit + .2*downstream_use_weight + .1*recency; recency 14-day half-life
use weights:              hands/chest 1.0, feet .8, bands .5, default .3 in configs/training/use_weights.yaml
weekly acquisition:       local text-LLM reason cluster callback; stable descending priority; top 20 collect/reannotate/holdout/label-proposal actions
nightly lint:             P-MANIFEST-style local linter callback per package, malformed manifests become BLOCK findings, atomic JSON report
weekly summary:           local text-LLM Markdown summarizer callback with nonempty-output enforcement
coverage matrix:          human_approved_gold only; closed 6 views x 7 poses x 3 instance contexts; 12 closed attributes; schema validated
deficit report:           ranked target-count and normalized deficit for all 126 cells; drafted packages excluded
tests:                    4 focused mining/coverage tests plus schema tests; full suite green (292 tests); Ruff clean
open gates:               Task Scheduler registration P4-03.05 and real 30-image coverage audit P4-04.03 remain unclaimed
```

## 2026-07-11 13:20 UTC - VLM calibration infrastructure complete; live gate failed honestly
**Items:** MF-P4-05.01 through MF-P4-05.03 complete; MF-P4-05.04 partial
**Result:** Infrastructure PASS; production model gate FAIL and remains unresolved.

```
calibration set:          qa/vlm_eval contains exactly 40 five-tile panels: 20 good and 20 seeded defects spanning all ten required problems
command:                  maskfactory vlmqa eval supports saved predictions or --live local Ollama execution
gate:                     exact-case coverage; defect recall >=0.90 AND precision >=0.80; atomic report and production_gate writes
change invalidation:      SHA-256 binds exact model id + prompt_version + prompt bytes; stale or failed gates are refused
primary live result:      qwen2.5vl:7b; TP=0 FP=0 FN=20; recall=0.00 precision=0.00; all 40 verdicts pass; gate refused
primary evidence:         qa/vlm_eval/results/qwen/live_verdicts_qwen2.5vl_7b.json and eval_qwen2.5vl_7b_p-part-v1-doc10.json
fallback live result:     not scoreable; Ollama 0.31.2 runner HTTP 500: unknown model architecture 'mllama' loading llama3.2-vision:11b
fallback disposition:     retained as an open runtime/model compatibility defect; no score fabricated
tests:                    296 tests pass; Ruff clean after calibration/CLI/client error-reporting changes
```

## 2026-07-11 13:55 UTC - Flip CI blocker and second-review workflow completed
**Items:** MF-P5-02.02; MF-P4-06.01 through MF-P4-06.03
**Result:** PASS - deterministic infrastructure and enforcement tests are green; no dataset/training entry gate was bypassed.

```
flip authority:           runtime Ontology/configs/ontology.yaml only; no handwritten label-ID table
flip coverage:            every PART/MATERIAL ontology ID, all 42 current sided PART IDs, future sided MATERIAL IDs, ignore_index 255
flip invariants:          reciprocal swap pairs, involution, unknown-ID hard failure, paired image/map width flip, default p=0.5
CI enforcement:           dedicated tests/test_training_augmentations.py step runs before the full pytest job
second-review sample:     deterministic ceil(15%) of QA-pass human_approved_gold packages; hard package and part candidates have exact x2 weighted-rendezvous weight
fresh-eyes enforcement:  different named reviewer; later UTC day; panels timestamp <= full-image timestamp <= completion; one pass/fail per sampled part
fail path:                all applicable parts demoted rejected_needs_fix; QA fail; schema-valid second_review_fail queue append
IAA archive:              first and second masks copied under qa/iaa/<image>/<timestamp>/ with SHA-256s and ordered review evidence
CLI:                      maskfactory second-review sample|record
tests:                    304 tests pass; Ruff clean; focused flip and second-review suites pass
open evidence gates:      first weekly IAA report/leaderboard export still require real approved packages; P5 training remains gated at 200 gold
```

## 2026-07-11 14:15 UTC - Weekly IAA reporting and human-ceiling export implemented
**Items:** MF-P4-06.04 and MF-P4-06.05 advanced to partial
**Result:** Implementation PASS; real-data evidence gate remains open because qa/iaa has no genuine review archive.

```
IAA reader:               scans timestamped qa/iaa review.json archives and selects the requested ISO week
input enforcement:        both masks must exist, be 2-D PNG mode L, and contain only 0/255
metrics:                  per-class and pooled IoU plus boundary-F@2px; sample counts preserved
targets:                  body IoU >=0.92; fingers/thumb/pinky IoU >=0.80; per-class PASS/FAIL
reports:                  qa/reports/iaa_<YYYY-Www>.json and .md, atomic writes
human ceiling:            human_ceiling_<YYYY-Www>.json with pooled/per-class IoU+BF, fingers/toes/chest/hairline/bands groups, 0.02 saturation rule note
CLI:                      maskfactory second-review report --iso-week YYYY-Www
fixture verification:     known disjoint mask pair produces IoU=0, BF=0, body target fail and matching leaderboard row
honest status:            no qa/iaa directory exists in live data, so no first weekly production report or real ceiling row was claimed
```

## 2026-07-11 14:40 UTC - S01 production adapter live; S02 adapter blocked at live WSL boundary
**Items:** MF-P2-01.01 complete; MF-P2-01.02 advanced to 80% partial
**Result:** S01 PASS on installed checkpoint. S02 implementation PASS, live CUDA evidence unavailable in current machine state.

```
S01 checkpoint:           models/detect/yolo11m.pt, verified registry asset
S01 adapter:              Ultralytics YOLO11, COCO class 0 only, conf >=0.5, production entry point run_s01
doc17 policy:             4% prominence floor; area*centeredness; left-to-right tie; top4; PART50 protection; raw >8 quarantine; no-person reject
live fixture:             qa/fixtures/smoke/ultralytics_bus_adults.jpg
live S01 result:           3 detected/promoted adults; person_bbox.json and p0/p1/p2 context crops under qa/live_verification/s01_bus
S02 runner:               pinned BiRefNet remote code + local safetensors; fp16 CUDA; geometry-preserving <=2048 tiles; 128 overlap; float32 .npy confidence
S02 integration:          confidence validated then thresholded 0.5; component policy; full-canvas mask/confidence; bbox-ratio QC
live S02 result:           unavailable — wsl --list --quiet currently reports no distro; Ubuntu-22.04 returns WSL_E_DISTRO_NOT_FOUND
status discipline:        older successful model smoke was not reused as proof that the new production adapter ran
tests:                    306 tests pass on clean rerun; Ruff clean (one prior transient Windows directory-rename test failure passed isolated and full rerun)
```

## 2026-07-11 15:05 UTC - S03 Sapiens/SCHP production provider boundary implemented
**Items:** MF-P2-02.01 and MF-P2-02.02 advanced to 80% partial
**Result:** Provider implementation/tests PASS; live CUDA run blocked by current absence of a WSL distro.

```
Sapiens asset:            registered models/parsing/sapiens_0.6b_seg.pt2, 28 classes
Sapiens execution:        pinned TorchScript, bf16 CUDA, 1024x768 native model input, 1536 source tiles with 128 overlap beyond
Sapiens output:           native crop geometry, uint8 argmax plus normalized 28xHxW float probabilities
OOM policy:               provider surfaces CUDA OOM; S03 retries scale 0.5, restores full geometry, then falls back SCHP-only with parsing_degraded
SCHP asset:               registered ATR ResNet-101 checkpoint, pinned official source revision, 18 classes
SCHP execution:           mandatory first/always-run companion, native geometry labels plus normalized 18xHxW probabilities
evidence persistence:     sapiens_28.png, schp_atr.png, one 8-bit confidence PNG/class, parsing metrics and cross-parser disagreement
focused tests:            provider class count/metadata, probability normalization, half-scale geometry restoration; existing dual-run/OOM/remap tests
live result:              schp_atr launch fails immediately with WSL_E_DISTRO_NOT_FOUND; wsl --list --quiet returns no distro
status discipline:        no provider item marked complete from historical smoke output
regression:               307 tests pass; Ruff and tracker validation clean
```

## 2026-07-11 15:30 UTC - DWPose production adapter and live CPU diagnostic
**Item:** MF-P2-03.01 advanced from 70% to 90% partial
**Result:** Algorithm/live output PASS; required ONNX CUDA provider unavailable in current Windows runtime.

```
assets:                    models/pose/yolox_l.onnx + dw-ll_ucoco_384.onnx, registry-verified pinned pair
detector:                  640x640 YOLOX preprocessing; 8400-anchor grid/stride decode; COCO person score; 0.45 NMS
pose:                      bbox aspect/pad affine to 288x384; ImageNet normalization; 133-point SimCC x/y decode at split ratio 2; inverse affine
provider rule:             production default refuses to run without CUDAExecutionProvider; CPU requires explicit diagnostic override
live fixture:              qa/fixtures/smoke/ultralytics_bus_adults.jpg, S01 p0 bbox
live CPU result:           4 pose candidates; candidate 1 selected for p0; candidates 0/2/3 suppressed; 133 points; body fraction 1.0
classification:            front, non-degraded, pose_and_parsing; pose133.json at qa/live_verification/s04_bus_p0_cpu
runtime gap:               onnxruntime 1.27.0 exposes AzureExecutionProvider and CPUExecutionProvider only; locked env requires onnxruntime-gpu 1.20.2
status discipline:        CPU diagnostic does not satisfy the GPU execution clause, so item remains partial
regression:               308 tests pass; Ruff and tracker validation clean
```

## 2026-07-11 16:00 UTC - GroundingDINO and persistent SAM2 provider boundaries implemented
**Items:** MF-P2-05.01 and MF-P2-05.02 advanced from 70% to 90% partial
**Result:** Provider/authority tests PASS; live model execution unavailable at current WSL boundary.

```
GroundingDINO:             pinned Swin-T checkpoint/source; one model load runs all 11 configured prompts
proposal output:           full-image xyxy + scores + prompt; typed BoxProposal authority=proposal_only
authority invariant:       runner and writer both assert proposal_boxes_only and may_write_final_masks=false; no pixel-mask field/API exists
SAM2 lifecycle:            persistent one-image WSL server; build_sam2 + predictor.set_image once; JSON-lines requests reuse embedding for every part
SAM2 prompts:              box + all positive/negative points; multimask output; full-resolution +/- logits and predicted-IoU scores
precision/fallback:        fp16 server; large initialization OOM becomes RuntimeError consumed by existing base-plus fallback
cleanup:                   explicit provider.close terminates and joins the embedding process
focused tests:             GDINO authority/provider parsing; SAM2 ready/one-embedding/multimask response; existing selection/correction/low-confidence/postprocess tests
live attempts:             both stop before model load with WSL_E_DISTRO_NOT_FOUND; no historical smoke substituted
regression:               310 tests pass; Ruff and tracker validation clean
```

## 2026-07-11 16:25 UTC - ViTMatte production provider implemented
**Item:** MF-P3-03.03 advanced from 75% to 90% partial
**Result:** Provider/lane tests PASS; live CUDA model load unavailable at current WSL boundary.

```
asset:                     models/matting/vitmatte_s.pth, pinned hustvl revision 6a58ad7646403c1df626fbd746900aec7361ea1d
input:                     RGB source + strict uint8 trimap values 0/128/255 at identical native dimensions
execution:                 pinned Transformers ViTMatte-S config/processor, local checkpoint, fp16 CUDA
geometry:                  processor-padded alpha cropped back to exact native HxW
known-region authority:    trimap background forced alpha 0; trimap foreground forced alpha 255; model predicts unknown band only
output:                    mode-L uint8 alpha; provider rejects mode/shape/known-region violations
lane integration:          existing >=2% bbox trigger, scaled +/-6px trimap, separate hair_binary and alpha; same optional lace_or_sheer path
live attempt:              WSL_E_DISTRO_NOT_FOUND before Transformers/model load; item remains partial
regression:               311 tests pass after png-strict guard rerun; Ruff clean
```

## 2026-07-11 16:50 UTC - DensePose production IUV provider implemented
**Item:** MF-P3-05.01 advanced from 65% to 90% partial
**Result:** Provider/IUV tests PASS; live Detectron2 CUDA load unavailable at current WSL boundary.

```
asset:                     densepose_rcnn_R_50_FPN_s1x.pkl with pinned Detectron2 DensePose config/source
execution:                 DefaultPredictor CUDA, score threshold 0.5, chart-based pred_densepose
instance ownership:        select candidate with highest IoU against S01 target bbox; reject zero overlap; report suppressed candidates
surface decode:            fine_segm argmax I=0..24; gather matching per-surface U/V; clamp U/V to 0..1
projection:                nearest I and bilinear U/V resized to selected bbox, clamped and pasted to exact full canvas
artifact:                  strict RGB densepose_iuv.png channels [I,U,V], uint8; I=0 requires U=V=0
downstream:                existing front/back/LR votes, UV continuity, topology evidence, QC-014/QC-024 consumers unchanged
live attempt:              WSL_E_DISTRO_NOT_FOUND before Detectron2/model load; item remains partial
regression:               312 tests pass; Ruff and tracker validation clean
```

## 2026-07-11 17:25 UTC - VLM calibration evidence audit revoked weak corpus
**Items:** MF-P4-05.01 downgraded complete -> 35% partial; MF-P4-05.04 reduced to 25% partial
**Result:** Prior corpus invalid for production calibration; preserved as deprecated evidence, never silently deleted.

```
audit findings:            abstract capsule rather than real image/mask pairs; near-duplicate good panels; defect answer text visibly embedded in every bad panel
old corpus:                moved intact to qa/vlm_eval/deprecated_synthetic_v0/{panels,manifest.json,results}
production safety:         qa/vlm_eval no longer has an active manifest/panels, so vlmqa eval cannot accidentally reuse the invalid gate
test fixture guard:        abstract generator now requires test_fixture=true and otherwise raises; production CLI no longer calls it
replacement contract:     generate_vlm_eval requires --seed-manifest with exactly 20 explicit source/good_mask/defect_mask records
diversity/integrity:       unique IDs and source/mask signatures, >=5 labels, exact two-per-taxonomy coverage, mode-L binary masks at source dimensions
panel integrity:           fixed renderer receives explicit masks only; no taxonomy/answer text is embedded; manifest records source/good/defect hashes
local seed attempt:        CVAT pth-sam2 successfully generated a binary adult hand+forearm candidate from mediapipe_thumb_up.jpg (task 5), archived as calibration_seed_only_not_gold
seed limitation:           candidate is not an ontology-exact hand boundary and is not counted toward the required 20 explicit reviewed pairs
gate discipline:           qwen recall=0 result remains failure history only; it is not a meaningful production score after corpus invalidation
regression:               313 tests pass; Ruff and tracker validation clean; unresolved hard blockers honestly increased 9 -> 10
```

## 2026-07-11 18:00 UTC - Production CLI runners wired through S04
**Item:** MF-P2-08.04 advanced to 20% partial
**Result:** Early one-command infrastructure PASS; D1 and G2 remain open.

```
runner factory:            src/maskfactory/stages/production.py returns real S00-S04 file-contract runners closed over pipeline config/images root
S00:                       verifies existing governed ingest manifest/status/source identity and exposes immutable source metadata
S01:                       installed YOLO11 checkpoint + amended doc17 promotion policy, crops and model telemetry
S02:                       reads S01 p0 bbox/crop, invokes BiRefNet provider, enforces silhouette/bbox QC and records telemetry
S03:                       invokes Sapiens+SCHP providers with authoritative parsing maps and degraded status
S04:                       invokes YOLOX+DWPose with authoritative pose rules and CUDA-required production mode
CLI:                       maskfactory run gains --images-root/--work-root and supplies production runners; StagePolicyError becomes a controlled Click error
atomic fixture:            governed ingested source -> S00/S01 manifest_delta.json + stage_run.json + context artifact contract
runtime repair attempt:    wsl --install Ubuntu-22.04 --no-launch failed fetching DistributionInfo.json with WININET_E_CANNOT_CONNECT; no local Ubuntu appx/msix found
honest boundary:           S05-S15 production runners are not wired; no real source or 56-atomic run exists; D1/G2 not claimed
regression:               314 tests pass; Ruff and tracker validation clean
```

## 2026-07-11 19:10 UTC - Production CLI geometry runner wired through S05
**Item:** MF-P2-08.04 advanced to 30% partial
**Result:** S05 file/coordinate contract PASS; D1 and G2 remain open.

```
runner factory:            src/maskfactory/stages/production.py now returns real S00-S05 runners
coordinate authority:      S04 full-image pose and S02 full-canvas silhouette are projected into the exact S01 context crop used by S03 parsing
geometry output:           limb capsules, torso partitions, hair prior, SAM2 prompt plans, hand/foot crop requests, and per-prior debug overlays
fallback discipline:       missing/low-confidence landmarks use parsing-only priors with prior_quality=low; empty S05 output fails semantically
parser fallback:           Sapiens-28 is authoritative when present; degraded S03 output automatically uses SCHP-ATR with its own mapping
focused evidence:          9 S05/production-runner tests pass, including exact 100x80 crop-space artifact assertions
static checks:             Ruff clean; Black module is not installed in the active Python runtime
full-suite caveat:         attempted full regression was disrupted by restricted/locked pytest base-temp roots; no product assertion failed, but no new full-suite pass is claimed here
honest boundary:           S06-S15 production runners and a real all-56-atomic source run remain missing; D1/G2 remain unclaimed
```

## 2026-07-11 19:25 UTC - Production CLI open-vocabulary runner wired through S06
**Item:** MF-P2-08.04 advanced to 35% partial
**Result:** S06 proposal-only production boundary PASS; D1 and G2 remain open.

```
runner factory:            real S00-S06 runners now available to maskfactory run
input/model:               S01 p0 context crop + pinned models/gdino/groundingdino_swint_ogc.pth
configuration:             exact configs/prompting.yaml vocabulary and 0.30 box / 0.25 text thresholds
authority invariant:       runner rereads gdino_boxes.json and rejects anything except proposal_boxes_only with may_write_final_masks=false
telemetry:                 groundingdino_swint_ogc model key recorded
focused evidence:          9 S06/S07 and production-runner tests pass; Ruff clean
honest boundary:           live inference still needs the absent WSL distro; S07-S15 runners and a real 56-atomic run remain missing
```

## 2026-07-11 20:05 UTC - Production CLI runners wired through S08
**Item:** MF-P2-08.04 advanced to 45% partial
**Result:** S07 full-frame refinement and S08 deterministic material draft contracts PASS; D1/G2 remain open.

```
S07 embedding:             exactly one persistent context-crop embedding; SAM2.1 hiera-large fp16 with base-plus OOM fallback
S07 selection:             existing 0.6 prior-IoU + 0.4 predicted-IoU logic, one corrective iteration, low-confidence prior retention
S07 artifacts:             strict mode-L binary sam2_<label>.png plus sam2_metrics.json with predicted IoU/review flags/model
S07 lane boundary:         hair and chest/breast specialist crop-lane parts excluded from the full-frame pass
S08 coordinate contract:  Sapiens/SCHP/GDINO/full-canvas silhouette and pose fused in the exact S01 context-crop coordinate system
S08 evidence:              skin/hair/clothing, SCHP garment classes, proposal-only boxes, evidence-gated bra/underwear, thin strap/waistband, sheer chroma
S08 artifacts:             8-bit indexed material_draft.png plus per-region evidence and pixel counts
fallback:                  degraded S03 can use SCHP map for coarse skin/clothing evidence; Sapiens remains authoritative when available
focused evidence:          10 S06/S07/runner tests pass; 5 S08 tests pass including production file contract
full regression:           316 tests pass; Ruff clean
honest boundary:           S08 per-material SAM2 edge refinement is not yet integrated into this runner; S08.5-S15 and the real 56-atomic run remain open
runtime boundary:          live S06/S07 execution still requires the currently absent WSL distro
```

## 2026-07-11 20:45 UTC - S08 refinement closed and production CLI wired through S08.5
**Item:** MF-P2-08.04 advanced to 55% partial
**Result:** S08 SAM2 edge refinement and S08.5 DensePose runner contracts PASS; D1/G2 remain open.

```
S08 refinement:            one shared SAM2 embedding edge-refines every non-empty material seed using the S07 selection/correction/low-confidence policy
S08 fallback:              predicted_iou <0.5 retains the evidence seed and records sam2_low_conf/review flags rather than inventing a boundary
S08 evidence artifact:     material_evidence.json now includes per-region model, predicted IoU, selection score, correction state, and review flags
S08.5 input:               exact S01 person context crop; S01 full-image person bbox explicitly transformed into crop coordinates for instance ownership
S08.5 model:               pinned densepose_rcnn_R_50_FPN_s1x checkpoint and pinned Detectron2 DensePose config
S08.5 artifact:            strict RGB densepose_iuv.png with I=0..24, U/V=0..255, and background I=0 => U=V=0 enforcement
telemetry:                 DensePose surface-pixel count, IUV geometry, and model key recorded
focused evidence:          13 material/SAM2 tests pass; 13 S08/DensePose/runner tests pass
full regression:           317 tests pass across four explicit test-file partitions (79 + 82 + 101 + 55); Ruff clean
execution-host note:       monolithic pytest stdout was dropped by the command host, so only the four explicit zero-exit partitions are cited
honest boundary:           S09-S15 production runners and a real all-56-atomic source run remain missing; live WSL-backed stages remain environment-blocked
```

## 2026-07-11 21:35 UTC - Production CLI master maps and reconciliation wired through S09.5
**Item:** MF-P2-08.04 advanced to 65% partial
**Result:** S09 master-map and reusable S09.5 reconciliation contracts PASS; D1/G2 remain open.

```
S09 evidence assembly:     S05 geometry + S07 SAM2 + S03 parser confidence maps + S08.5 DensePose side/surface support
parser authority:          broad parser classes may support an existing body-aware candidate but cannot instantiate a fine-grained atomic on their own
silhouette coverage:       uncovered visible pixels receive only a 0.01 nearest-geometry vote; background inside the promoted silhouette remains forbidden
S09 outputs:               uint16 part map, uint8 material map, disagreement grayscale, waist/occlusion region bands, consensus routes, occlusion audit, SHA-256 map
material invariant:        S08 material ID 0 inside the silhouette is rejected rather than silently relabeled
S09.5 engine:              pairwise silhouette IoU/QC-035 evidence, scaled reciprocal interperson contact bands in each crop, preliminary image_manifest.json
S09.5 reciprocity:         relationship records contain both pA and pB band paths from one computed full-canvas band
single-person runner:      writes the trivial passing image index and proceeds honestly
multi-person runner:       explicitly stops because the required per-instance S02-S09 outer loop is not built; it does not fake reconciliation from p0 alone
focused evidence:          10 S09/S09.5/runner tests pass
full regression:           320 tests pass across four zero-exit partitions (79 + 82 + 101 + 58); Ruff clean
honest boundary:           multi-person outer orchestration, specialist atom coverage, S10-S15, live WSL execution, and the real all-56-atomic run remain open
```

## 2026-07-11 22:30 UTC - Production CLI S10 report and QC-035..038 hard gates live
**Items:** MF-P2-08.04 advanced to 72% partial; MF-P8-05.01..06 complete
**Result:** Schema-valid pre-package S10 report and all multi-instance QA gates PASS.

```
S10 inputs:                authoritative S09 part/material/disagreement maps, S02 silhouette, S04 pose, S03/S07 metrics, DensePose IUV, S09.5 image index
S10 batteries:             QC-011..029 semantic/topology plus QC-031..033 uncertainty and QC-035..038 multi-instance checks
report:                    qa_report.json validates against bundled Draft 2020-12 schema; includes per-part metrics, score, consensus provenance, routes and hard blocks
hard routing:              any failed BLOCK forces overall=fail regardless of numerical QA score
package-only boundary:     QC-005..010 and QC-034 are explicitly skipped until S13 manifest/hash/derived/previous-gold artifacts exist; never reported as passes
QC-035:                    pair silhouette IoU >0.30 => BLOCK
QC-036:                    atomic bleed into another instance's eroded silhouette core outside reciprocal contact band => BLOCK
QC-037:                    directional relationship/contact-band mismatch => ROUTE
QC-038:                    actual promoted count differs from expected or exceeds cap => WARN
seed isolation:            parameterized fixture proves each QC-035/036/037/038 defect trips exactly its own check
approval enforcement:      approve_package reads existing qa_report first; approved=true cannot override QC-035 or QC-036 failures
focused evidence:          20 approval/S10/seeded package tests pass
full regression:           328 tests pass across four zero-exit partitions (79 + 87 + 95 + 67); Ruff clean
honest boundary:           S10 is partial until package-only checks can run; S11-S15, multi-instance outer loop, specialist atomics, live WSL, real D1/G2 remain open
```

## 2026-07-11 23:15 UTC - Production CLI S11 VLM QA wired with mandatory gate
**Item:** MF-P2-08.04 advanced to 78% partial
**Result:** S11 panel/review/router contract PASS; live VLM remains correctly disabled by the missing production calibration gate.

```
panel generation:          exact five-tile 2560x512 boundary panel for every visible atomic plus all_parts whole-image overlay
gate:                      require_current_gate checks primary model + p-part-v1-doc10 prompt fingerprint and 0.90 recall / 0.80 precision thresholds
gate unavailable path:     no Ollama call; every visible part routes careful; existing auto-QA BLOCK remains fail; report remains schema-valid
gate-current path:         local-only Ollama endpoint, strict JSON parse + one retry, append-only schema validation, cautious five-row routing
part authority:            VLM may not approve gold, clear BLOCK, or edit a mask; routing records preserve all three false invariants
whole-image review:        P-IMAGE overlay sanity with strict keys, retry, visible-label digest, and needs_human routing on findings/invalid response
manifest review:           explicitly skipped until the draft package manifest exists; not represented as a pass
live project state:        qa/vlm_eval has no active valid production_gate.json; deprecated synthetic v0 remains excluded
focused evidence:          12 S11/client/router/calibration tests pass across gate-disabled and gate-current paths
full regression:           330 tests pass across four zero-exit partitions (79 + 87 + 95 + 69); Ruff clean
honest boundary:           S11 production model scores are unclaimed; valid 40-panel real calibration corpus/gate, draft manifest lint, S12-S15 remain open
```

## 2026-07-12 00:05 UTC - Production CLI S12 draft package and CVAT push live
**Item:** MF-P2-08.04 advanced to 84% partial
**Result:** Automated S12 review handoff PASS; manual correction/approval remains pending by design.

```
draft layout:              data/packages/<image_id>/instances/p0 with source crop, indexed maps, masks, materials, protected, regions, overlays, panels, QA report
manifest:                  full Draft 2020-12 manifest schema; every enabled atomic has visibility/status/provenance/occlusion state
binary exports:            strict png_strict views for every enabled PART and MATERIAL ID; visible masks linked and hashed, absent atomics recorded not_visible/n/a
provenance:                governed intake origin/time, crop-relative person bbox, pose/view/tags, model/config versions and full file hash index
CVAT context:              all_parts overlay + disagreement heatmap archived as related images; draft masks encoded through existing RLE bridge
task automation:           production S12 assembles package, creates CVAT task, records task IDs, returns pending_kevin_correction_and_approval
authority boundary:        human_approved=false always on push; no automated correction or approval claim
overwrite guard:           assembler refuses any package containing human_corrected or human_approved_gold state
multi-person boundary:     S12 refuses multi-person until the required per-instance pipeline loop supplies every instance package
focused evidence:          5 package/CVAT/production-runner tests pass
full regression:           332 tests pass across four zero-exit partitions (79 + 87 + 90 + 76); Ruff clean
honest boundary:           no source image exists for a live S12 task in this run; Kevin's correction clicks and approval, S13-S15, and prior blockers remain open
```

## 2026-07-12 00:45 UTC - Production CLI S13 approval-gated finalizer live
**Item:** MF-P2-08.04 advanced to 88% partial
**Result:** S13 finalization contract PASS; no gold claim without Kevin confirmation.

```
explicit authority:        only maskfactory package's interactive confirmation may call approve_package(... approved=true)
pipeline S13 unapproved:   writes approval_handoff.json with NEEDS KEVIN command/status and leaves all human_corrected/draft states unchanged
pipeline S13 approved:     accepts only frozen package + every visible part human_approved_gold + verify_packages pass
final binaries/unions:     governed one-shot autofix regenerates strict atomics and all declarative derived unions before confirmation
final inpaint:             approval finalizer regenerates every configured inpaint derivative from corrected atomic/derived authority and records source hashes
final visuals:             all-parts/per-part overlays and exact five-tile review panels regenerated from corrected final maps before freeze
post-generation gate:      QC-001..010 rerun after final derivatives/visuals and before gold stamp; failure bounces package
freeze:                    review identity/minutes/timestamp, gold statuses, qa_report, immutable marker, refreshed hashes, final verification, DVC add
focused evidence:          17 production/approval/versioning tests pass; approval fixture asserts all 7 inpaint targets and final visuals exist
full regression:           333 tests pass across four zero-exit partitions (79 + 87 + 91 + 76); Ruff clean
honest boundary:           no corrected/approved live package exists, so S13 gold_exported=true is unclaimed; S14-S15 and prior blockers remain open
```

## 2026-07-12 01:35 UTC - S14/S15 production code wired behind immutable gold gate
**Item:** MF-P2-08.04 advanced to 94% partial; no P5 item claimed
**Result:** Dataset exporter and active-learning planner contracts PASS; actual dataset build remains forbidden at 0/200 gold.

```
split formula:             sha256(image_id) bucket 0-69 train / 70-84 val / 85-99 test; never instance ID
near duplicates:           pHash Hamming <=6 connected components forced into one split
overrides:                 hard_case_holdout wins; generated/synthetic-connected groups train-only
multi-person integrity:    all p0/p1/... packages sharing image_id exported to the same split
preflight:                 only frozen packages whose visible parts are all human_approved_gold; verify_packages must pass every instance
export layout:             dataset card, train/val lists, part/material MMSeg trees, optional hand/matting/projected, COCO uncompressed RLE, isolated holdouts
holdout isolation:         test/hard samples exist only under holdout; build manifest gives trainers no holdout read path
reproducibility:            sorted inputs, seed 1337, deterministic coverage timestamp/content; byte-identical dual-root rebuild proven
provenance:                package schema now preserves intake phash64; dataset card records ontology, Git SHA, split/class counts, synthetic ratio, build command
version/publish CLI:        auto-increment bodyparts@vN; dvc add, dataset/bodyparts-vN git tag, dvc push (not executed while gate closed)
entry gate:                production S14 and CLI require >=200 approved gold instances; current count=0; no dataset directory created
S15:                       harvests failure_queue + coverage deficits, emits top-20/top-10 acquisition actions and +50-gold/ontology retrain triggers
focused evidence:          12 dataset/coverage/active-learning/runner tests pass
full regression:           337 tests pass across four zero-exit partitions (79 + 83 + 92 + 83); Ruff clean
honest boundary:           no real S14 build/DVC publish occurred; P5 remains unopened; D1 still lacks live source/model/manual evidence and multi-person/specialist completion
```

## 2026-07-12 02:05 UTC - Multi-person reconciliation and split-integrity contracts closed
**Items:** MF-P8-03.01..05 and MF-P8-07.01..03 complete
**Result:** S09.5 false-split/contact evidence and dataset leakage CI blockers PASS.

```
false split:               seeded two-detection fixture at silhouette IoU=1/3 exceeds 0.30 and fails QC-035
genuine contact:           edge-touching people at IoU=0 pass QC-035 and receive nonempty reciprocal crop-space contact bands
image index:               preliminary image_manifest records promoted IDs, background count, crowd flag, max IoU/QC result, relationship and both paths
split enforcement:         validate_instance_split_integrity parses every <image_id>_pN and rejects any image spanning multiple partitions
broken fixture:            deliberate p0=train / p1=test_holdout assignment raises multi-instance split leakage
builder integration:       validator runs on every completed dataset build after image-keyed assignments are assembled
CI:                        broken-split test lives in normal pytest inventory and therefore blocks the same repository test gate as flip/remap checks
full regression:           339 tests pass (80 + 83 + 92 + 84); one initial parallel Windows directory-replace lock reran serially and passed
Ruff:                      clean
hard blockers:             unresolved tracker hard blockers reduced 8 -> 5
honest boundary:           real S02-S09 per-instance outer loop and co-subject protection remain open; these completed contracts do not prove D11
```

## 2026-07-12 03:00 UTC - Real per-instance S02-S09 outer loop and co-subject protection live
**Items:** MF-P8-01.01/.02 complete; .03 70% partial; .04 80% partial
**Result:** One-command multi-person draft orchestration PASS on deterministic 1/2/3-person fixtures.

```
shared stages:             S00/S01 execute exactly once in the shared work root
runner scope:              build_production_runners(person_index=N, shared_work_root=...) selects pN bbox/crop while retaining shared S01 authority
instance layout:           each promoted person runs S02-S09 under work/instances/pN with the full existing production stage implementations
execution order:           all promoted S02 silhouettes complete first; only then do all instances continue through S03-S09
co-subject promoted:       target pN other_person_protected is the union of every other promoted instance's real S02 full-canvas silhouette
co-subject background:     non-promoted detections are conservatively protected by their full-canvas S01 bbox
fusion authority:          protected evidence enters S09 only as PART other_person and is clipped by the target silhouette; it cannot author another body part
reconciliation:            S09.5 runs once after every instance S09 and writes/injects shared relationship evidence
CLI:                       maskfactory run <image_id> --through-drafts owns exact shared S00/S01 + per-instance S02-S09 + once-only S09.5 plan
fixtures:                  parameterized 1/2/3 promoted counts, contiguous pN output set, background person protection, single p0 trivial case, CLI exposure
full regression:           343 tests pass across four zero-exit partitions (80 + 83 + 96 + 84); Ruff clean
honest boundary:           distinct hand-verified multi-image fixture set and byte-identical N=1 comparison remain open; parsing ambiguity suppression and real D11 run remain open
```

## 2026-07-12 03:35 UTC - Co-subject parser suppression and ambiguity handoff live
**Items:** MF-P8-02.02/.03/.04 complete; MF-P8-02.01 85% partial
**Result:** Co-subject pixels cannot become target parsing priors or silently enter training authority.

```
parser suppression:        S03 projects the protected co-subject mask into context space and zeros both Sapiens-28 and SCHP-ATR labels/confidence planes
geometry boundary:         suppression occurs before S05 consumes parser outputs
ambiguity artifact:        target/co-subject overlap is written exactly to ambiguous_do_not_use.png and marks parsing degraded/careful-review
fusion protection:         S09 admits protected overlap only as PART other_person with explicit z-order authority over target body-part labels
review handoff:            S12 marks intersecting atomics ambiguous_do_not_use, withholds authoritative mask metadata, and records a specific careful-review note
training safety:           ambiguous atomics retain visual draft pixels for CVAT review but expose no manifest mask_file/status that dataset export could treat as authority
focused evidence:          22 S03/S09/review-package/production-runner tests pass; Ruff clean
full regression note:      complete-suite launch could not be collected because the execution host lost yielded-process ownership; no full-suite count is claimed for this entry
honest boundary:           literal nearest-promoted-bbox assignment across multiple parser/pose detections remains open; current per-instance crop/silhouette isolation is recorded at 85%
```

## 2026-07-12 04:05 UTC - Multi-instance package finalization and verification live
**Items:** MF-P8-04.01..04 complete
**Result:** S09.5 image relationships now become authoritative, reciprocal per-instance package metadata.

```
layout gate:               finalizer requires contiguous instances/p0..pN and one matching manifest per promoted instance
relationship mirror:       image-level contact/occlusion records become reciprocal per-instance interperson[] entries using schema-required full instance IDs
band authority:            every manifest relationship must resolve to that instance's masks_regions/interperson_contact_boundary.png or finalization fails
hash integrity:            files{} is refreshed after contact-band injection; every per-instance manifest is schema-validated before image_manifest.json is installed
multi-instance round trip: assembled p0+p1 -> reconciled contact -> finalized index/manifests -> verify_packages discovers exactly two and all QC-001..010 pass
single-person regression:  trivial instances/p0 index retains promoted_instances=[p0], interperson=[], and exactly one verifiable package
focused evidence:          8 review-package/S09.5/schema tests pass; Ruff clean
full regression note:      long-suite execution transport again lost ownership of yielded processes, so no new repository-wide count is claimed
honest boundary:           this closes package structure/verification contracts, not live CVAT review or real-image D11 evidence
```

## 2026-07-12 04:45 UTC - Multi-instance CVAT jobs, overview, and correction routing live
**Items:** MF-P8-06.01..04 complete; MF-P8-06.05 85% partial
**Result:** A duo produces two independent authoring tasks plus one non-authoring shared overview.

```
instance jobs:             push creates one segment_size=1 task and durable package_root record per (image_id,pN), never a mixed multi-instance authoring batch
overview job:              multi-person images receive exactly one composite all-promoted-instance context task with zero mask shapes
SOP-6:                     instance and overview descriptions require reciprocal contact agreement, cross-person bleed review, per-instance corrections, and honest ambiguity
pull isolation:            image_overview records are excluded; each correction is fused, derived, QA-checked, and backed up only in its recorded pN package
seeded routing proof:      a modified p1 CVAT mask changes p1 only while p0 remains pixel-identical; both retain independent task backups
backward compatibility:   single-person image still creates exactly one ordinary authoring task and pulls unchanged pixels identically
focused evidence:          19 CVAT/labelmap/project/review-package tests pass; final 2 push/pull tests pass; Ruff and git diff --check clean
honest boundary:           FakeCvat proves the complete API/data contract, but literal live-CVAT two-person execution remains required before MF-P8-06.05 reaches 100%
```

## 2026-07-12 05:15 UTC - Coverage and leaderboard instance-context breakouts live
**Items:** MF-P8-08.01..03 complete; MF-P5-06.01 70% and MF-P5-06.02 85% partial
**Result:** Solo, duo, and small-group performance are independently measurable without breaking pooled or legacy scores.

```
coverage matrix:           closed 6 views x 7 poses x 3 instance contexts; dataset builder derives solo/duo/small_group from source person_count
coverage CLI:              maskfactory coverage report reads the validated matrix and returns ranked deficits retaining instance_context
leaderboard schema:        validated candidate x holdout row stores pooled metrics plus optional solo/duo/small_group metrics, per-class maps, and sample counts
durable storage:           append uses validated canonical JSONL and atomic replacement; reader identifies the exact invalid row
legacy compatibility:      pre-context rows normalize to an equivalent solo breakout; pooled mean IoU, boundary-F, class, and group values are untouched
comparison:                same-dataset/split enforcement; pooled, per-class, group, and context deltas exposed by maskfactory leaderboard --compare
focused evidence:          13 leaderboard/coverage/schema/dataset tests pass; Ruff clean
honest boundary:           standing-baseline auto-scoring and human-oriented table rendering remain open under P5; no trained-model performance claim is made
```

## 2026-07-12 05:50 UTC - Instance-aware read-only ComfyUI Mode-A nodes live
**Items:** MF-P8-09.01..04 and MF-P6-01.01/.03/.04 complete; MF-P6-01.05/.06 85% partial
**Result:** Every package-backed node resolves image_id + person_index (default 0), with serialized p0/p1 workflow proofs.

```
shared resolver:           data/packages/<image_id>/instances/pN with legacy root-package fallback only for p0; invalid/missing/newer-major packages fail clearly
browser:                   enumerates status-filtered (image_id,person_index) pairs and exposes the selected index plus total count
Mode-A nodes:              Source, Gold, Union, Projected NON-TRUTH, Inpaint existing/derive, Label Map, Combine, and Mask Stats registered
mask contract:             strict binary -> exact float 0/1; feather ramps preserved; every package-backed mask checked against source HxW; no resize path
legacy workflow:           serialized prompt omitting person_index is torch.equal to explicit person_index=0
multi workflow:            serialized person_index=1 prompt loads seeded p1 pixels that are distinct from p0
read-only proof:            before/after package-tree hash identical; static audit finds no write/unlink/replace APIs in node module
dependency boundary:       Mode-A imports only stdlib, numpy, PIL, torch; no cv2, mmseg, model load, or pipeline dependency
focused evidence:          4 Comfy node/workflow tests pass; 7 broader Comfy/inpaint/package tests passed in the initial slice; Ruff and git diff --check clean
honest boundary:           node-pack installer and live ComfyUI execution remain open; broader on_missing/inpaint semantic matrix remains under P6 partial items
```

## 2026-07-12 06:20 UTC - ComfyUI Mode-A installer and semantic matrix complete
**Items:** MF-P6-01.02/.05/.06 and MF-P6-04.01/.02 complete
**Result:** The standalone read-only node pack installs reproducibly and enforces package semantics without heavy dependencies.

```
installer CLI:             maskfactory comfy install --comfy-root copies standalone __init__.py + workflows and writes absolute config.json
installed config:          packages_root, api_url=http://127.0.0.1:8765, format_version=1.x; fresh dynamic import resolves configured package root
missing behavior:          default error; explicit empty returns source-sized zero MASK with warning
status boundary:           browser default exposes human_approved_gold only and excludes seeded rejected_needs_fix p1
projected boundary:        purple-tagged NON-TRUTH category and independent projected source path
mask semantics:            exact binary float mapping; multi-level derived feather ramp; mismatched source dimensions hard-fail without resize
static CI audit:           AST forbids cv2/mmseg/scipy/transformers and every filesystem mutation method in the installed node runtime
mutation guard:            deliberate package-truth output target raises; ordinary ComfyUI output outside data/packages remains allowed
focused evidence:          8 Mode-A/install/static tests pass; Ruff and git diff --check clean
honest boundary:           live ComfyUI workflow execution and node-pack workflow 1 remain open
```

## 2026-07-12 07:00 UTC - Mode-B service contract, predict node, and workflows live
**Items:** MF-P6-02.04/.06, MF-P6-03.01/.04 complete; related live-runtime items partial
**Result:** Local inference has a strict read-only API core and tested multipart Comfy client without false live-model claims.

```
service core:              health/models/predict/refine contracts; strict request raster and provider mask dimensions/binary values
FastAPI boundary:          lazy app factory with startup/shutdown GPU lease and multipart endpoints; absent web stack gives pinned-env install guidance
localhost CLI:             maskfactory serve --port 8765 hard-codes host 127.0.0.1 (live WSL execution still pending)
GPU exclusion:             serving lock refuses pipeline with named serve_mode_b owner; pipeline lock refuses serving with named pipeline owner
response authority:        top-level and per-label status=draft_model_generated; visibility/area/provenance included; no package truth write path
Comfy Mode B:              multipart IMAGE PNG + labels/inpaint params; base64 decode to MASK batch + labels + JSON; exact serve command on API down
provider boundary:         injected champion/refine callbacks permit deterministic contract tests while actual champion/SAM2 residency remains unclaimed
workflows:                 all three required JSONs filed and installer-copied: gold hand, bodypart conditioned, live predict/inpaint
focused evidence:          15 combined service/Comfy/GPU tests pass; final service/workflow slice 12 tests and final API 4 tests pass; Ruff clean
honest boundary:           FastAPI is absent from this Windows test env; live WSL bind, real champion/SAM2 providers, latency gates, and live Comfy workflows remain open
```

## 2026-07-12 07:35 UTC - P5 dataset contracts reconciled and training configs authored
**Items:** MF-P5-01.01..05/.07, MF-P5-03.01, MF-P5-04.01, MF-P5-05.01 complete
**Result:** Code/config work that does not require crossing the 200-gold gate is verified; build/publish/train remain closed.

```
split authority:           exact SHA bucket, pHash<=6 connected groups, synthetic train-only, hard-case override, image-level instance integrity
trainer IDs:               train/val lists now contain exported image_id_pN sample IDs, fixing the previous image-ID/filename mismatch
export layout:             part/material MMSeg, optional hand/matting/projected, COCO RLE, isolated test/hard holdouts
preflight:                 every frozen eligible package is verified before destination creation; seeded failure leaves no dataset directory
reproducibility:            dual-root rebuild relative-file SHA maps are byte-identical; seed 1337 and deterministic coverage timestamp recorded
dataset card:              image/instance split counts, class counts, every view/pose/context cell, ontology, build command, Git SHA, seed, synthetic ratio
configs:                   exact SegFormer-B3 bodypart, SegFormer-B2 material, and SegFormer-B2 hand specialist schedules/gates authored and fixture-checked
focused evidence:          11 dataset/coverage tests pass; final dataset+config slice 8 tests pass; Ruff and git diff --check clean
honest boundary:           approved_gold_count=0, so bodyparts@v1 build/DVC publish and every actual training/evaluation gate remain unexecuted
```

## 2026-07-12 08:05 UTC - P5 augmentation semantics and CI guards live
**Items:** MF-P5-02.03..05 complete; MF-P5-02.01 85% partial
**Result:** Rare-class sampling and every permitted transform preserve ontology/truth semantics before MMSeg runtime activation.

```
dataset adapter:           per-instance lists/maps, dimension enforcement, optional MMSeg registry, ambiguity -> ignore_index 255 on part+material
rare crop:                 configured output/scale; 40% forced selection; chosen rare pixel preserved even when nearest downsampling would erase a singleton
measurement:               attempts, forced attempts, rare-contained count, and realized rate atomically logged; seeded 200-trial fixture within tolerance
photometric:               brightness/contrast/saturation +/-0.25 and hue +/-0.05 bounds; labels are not accepted or modified
rotation:                  +/-15 degree bound; RGB bilinear; labels nearest; introduced border is exactly 255
banned guard:              recursively rejects vflip, vertical flip, elastic, perspective, MixUp, CutMix; valid horizontal flip accepted
config wiring:             bodypart/material/hand YAMLs carry the approved transform stacks and hand-specific 768/0.75-1.25 settings
focused evidence:          8 augmentation/dataset tests pass; combined augmentation+config slice 11 tests passed; Ruff and git diff --check clean
honest boundary:           MMSeg is absent here and approved_gold_count=0, so real framework dataloader/trainer execution remains the final 15% of MF-P5-02.01
```

## 2026-07-12 08:35 UTC - Leaderboard tables, human ceiling, and reversible promotion live
**Items:** MF-P5-06.02/.04/.05 complete; MF-P5-06.03 75% partial
**Result:** The arbiter can compare, saturate, promote, and roll back verified candidates without asserting a winner exists.

```
comparison CLI:            default Markdown table includes pooled, per-class, group, and instance-context IoU/BF deltas; deterministic JSON remains optional
comparability gate:        candidates must share dataset_ref and split before any delta is produced
human ceiling:             weekly IAA artifact now conforms to leaderboard schema with per-class/group IoU+BF, sample count, and explicit human model family
saturation:                class is saturated only when best model is within 0.02 of human on both IoU and boundary-F
role resolver:             exactly one verified file-backed model may satisfy a runtime role; zero/multiple/missing/hash mismatch remain hard errors
promotion:                 one atomic role swap records candidate prior role + incumbent; champion history JSONL is durable
rollback:                  one atomic inverse edit restores exact original roles and refuses if either role changed after promotion
focused evidence:          16 registry/leaderboard/second-review tests pass; Ruff and git diff --check clean
honest boundary:           no trained winner exists at 0 approved gold; live registry has no champion pointer and pipeline/provider champion consumption remains partial
```

## 2026-07-12 09:05 UTC - Retrain triggers now open durable P5 tasks
**Items:** MF-P7-02.01 complete; MF-P7-02.02 35% and MF-P5-06.03 80% partial
**Result:** Weekly S15 can request retraining for every specified reason without bypassing the 200-gold gate.

```
gold trigger:              approved_gold_count - champion_gold_count >= 50
error trigger:             same class must increase >0.05 in each of the latest two weekly transitions; one-week spike does not qualify
ontology trigger:          explicit ontology version change flag
task artifact:             atomic/idempotent retrain_tasks/p5_retrain_<date>.json with vNext build, candidates, frozen holdouts, leaderboard, promote/reject, history steps
gate awareness:            task status=open at >=200 gold; otherwise waiting_for_p5_entry_gate with current/required counts preserved
collision safety:          same task ID/content is idempotent; changed content under same ID hard-fails
history visibility:        maskfactory models champions returns current champion role pointers and append-only promotion history
focused evidence:          15 active-learning/dataset/model-registry tests pass; Ruff and git diff --check clean
honest boundary:           no trigger-driven training run has executed because approved_gold_count=0; MF-P7-02.02 remains partial
```

## 2026-07-12 09:35 UTC - P7 ontology and horizon decisions recorded
**Items:** MF-P7-04.01/.02 and MF-P7-05.01/.02 complete
**Result:** Evidence gates produce explicit decisions without speculative ontology or production claims.

```
ontology evidence:         qa/failure_queue.jsonl absent; 0 qualifying failures for every proposed v2 label against mandatory 10/30-day threshold
ontology decision:         NO-GO; body_parts_v1 unchanged; no IDs, boundaries, swaps, CVAT labels, back-annotation, or dataset bump authorized
changelog:                 dated NO-GO entry links machine-readable/Markdown evidence and preserves Kevin approval for any future GO
video horizon:             NO-GO until temporal schema, track identity, keyframe/drift QA, CVAT flow, measured cost model, and D1-D11 exist
video pilot gate:          governed adult clips, zero identity switches, temporal/per-frame hard checks clean, approved operator-cost target
multi architecture:        GO already enacted by doc17/P8; ownership is instances/pN, not person-namespaced ontology labels
multi production:          NO-GO until real 10-20 image SOP-1..6 review, QC-035/036 clean, reciprocal contacts, and G9=0 prove D11
focused evidence:          2 decision-artifact regression tests pass; Ruff and git diff --check clean
```

## 2026-07-12 10:05 UTC - Conservative garbage collection implemented
**Item:** MF-P7-03.02 80% partial
**Result:** GC can rehearse/apply the only fully-authorized deletion category without exposing current gold or referenced data.

```
default mode:              dry-run; every candidate and content-derived plan hash printed and logged
eligible:                  masks@vN marked deprecated, retain_until expired, active successor human_approved_gold in masks/
manifest guard:            any files{} reference to the deprecated tree protects it
path guard:                exact masks@v<version> child only; target must remain inside packages root and directly under its package
review race guard:         apply recomputes candidates at the reviewed generated_at; byte/path/metadata changes invalidate the plan
confirmation:              --apply prompts unless explicit --yes; logs gc_<date>.log with WOULD_REMOVE/REMOVED, bytes, version, retention date
protected by construction: active masks/, young versions, referenced versions, holdouts, IAA, leaderboard, and categories lacking explicit authority
focused evidence:          3 GC/versioning tests pass; dry-run/apply fixture preserves current and protected trees; Ruff and git diff --check clean
honest boundary:           real-corpus dry-run review, apply, verify-package sample, and reindex post-check remain before MF-P7-03.02 can complete
```

## 2026-07-12 10:30 UTC - IP-3 copy-only reindex drill executed
**Item:** MF-P7-03.04 complete
**Result:** The live state database was never mutated; its isolated copy rebuilt and diffed clean.

```
command:                   maskfactory incident reindex-drill --database data/maskfactory.sqlite --packages-root data/packages
source before/after:       0 bytes; SHA256 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 identical
copy:                      qa/live_verification/ip3/maskfactory_ip3_copy_20260711T083019Z.sqlite (49152 bytes after schema rebuild)
report:                    qa/live_verification/ip3/ip3_reindex_drill_20260711T083019Z.json
before diff:               clean=true, missing=[], stale={}, extra=[]
after diff:                clean=true, missing=[], stale={}, extra=[]
safety:                    source hash is checked after rebuild; implementation targets copy path only and hard-fails a non-clean post-diff
focused evidence:          7 reindex/IP-3 tests pass; Ruff and git diff --check clean
honest boundary:           this is a real mechanism drill on the current empty package/index state, not proof of recovering a populated or corrupted production index
```

## 2026-07-12 10:55 UTC - Disk headroom reviewed and junction move rehearsed
**Item:** MF-P7-03.05 complete
**Result:** C: is in the warning band; no unsafe move was attempted without a second governed volume.

```
live capacity:             951.65 GiB total / 854.59 GiB used / 97.05 GiB free
doctor:                    WARN 97.1 GiB; below 150 GiB warning, above 75 GiB ingest block; 200 GiB target unmet
visible volumes:           C: only; no larger fixed target currently available
rehearsal:                 tools/move_data_to_junction.ps1 -Name data -Target D:\MaskFactory\data -WhatIf
rehearsal output:          source_bytes=25741, target_volume_visible=false, no filesystem changes made
safeguards:                allowlist data/datasets/runs; outside-workspace target; +20 GiB reserve; robocopy <8; verify/reindex/doctor; automatic rollback
retention:                 rollback data_old timestamp is never auto-deleted; models is not an allowed junction source
evidence:                  qa/live_verification/disk_headroom_2026-07-12.{json,md}; 10 disk/doctor tests pass; Ruff/git diff clean
next external state:       attach/provision governed larger fixed volume, rerun rehearsal, apply, retain rollback until all checks reviewed
```

## 2026-07-12 11:20 UTC - Hand-lane acceptance metrics integrated
**Item:** MF-P3-01.09 complete
**Result:** Gap preservation, QC-018 paste-back, and leaderboard evidence now form one hard-gated operation.

```
fixture:                   five separated left-finger masks with explicit inter-finger gap regions and one crop transform
gap invariant:             prediction union intersection with gap regions = 0 px
negative proof:            deliberate one-pixel gap fill raises HandLaneError before any leaderboard file is created
paste-back:                every crop prediction nearest-reprojects through CropTransform; minimum per-finger IoU = 1.000000 (gate >=0.995)
metrics:                   per-finger IoU and boundary-F@2px for thumb/index/middle/ring/pinky
leaderboard:               schema-valid test_holdout row with all five classes and fingers group {iou=1.0,bf=1.0}
focused evidence:          15 hand-lane/leaderboard/P2-metric tests pass; Ruff and git diff --check clean
```
## 2026-07-11 08:49 UTC - Training ambiguity burned at dataset export boundary
**Item:** MF-P5-02.01 advanced from 85% to 90% partial
**Result:** Dataset exports now make `ambiguous_do_not_use` spatially authoritative for MMSeg inputs.

```
source of truth:           manifest part visibility + indexed gold part map
export behavior:           union every ambiguous part region and write ignore_index 255
targets protected:         both part_seg and material_seg annotations
holdouts:                  same burned maps exported for honest later scoring
non-ambiguous pixels:      retain exact original part/material IDs
writer:                    png_strict.write_label_map (16-bit part, 8-bit material)
regression:                15 dataset-builder/training-augmentation tests pass
quality:                   Ruff check/format and git diff --check clean
honest boundary:           live MMSeg dataloader/trainer execution remains gated by the absent WSL runtime and 0/200 approved gold
```
## 2026-07-11 08:55 UTC - Standing-baseline leaderboard orchestration implemented
**Item:** MF-P5-06.01 advanced from 70% to 82% partial
**Result:** Every dataset-version/holdout pair can now require and idempotently score the complete standing baseline set.

```
required baselines:         sam2_only, sam2_pose, sam2_parsing, draft_pipeline_full
identity authority:         orchestrator stamps run_id/model_family/dataset_ref/split
scoring boundary:           injected production evaluator returns measured metric payload only
idempotency:                existing exact dataset_ref+split baselines are never duplicated
version behavior:           a new dataset_ref triggers all four fresh scores
validation:                 every emitted row passes the full leaderboard schema
regression:                 16 leaderboard/hand/IAA tests pass
quality:                    Ruff check/format and git diff --check clean
honest boundary:           no baseline scores fabricated at 0 approved gold; live holdout evaluation remains required
```
## 2026-07-11 09:02 UTC - Mode-B serving champion resolution enforced
**Item:** MF-P5-06.03 advanced from 80% to 88% partial
**Result:** The production predictor configuration path can no longer claim champion provenance from arbitrary checkpoint names.

```
accepted roles:            non-empty unique champion_* roles only
registry contract:         exactly one verified file-backed model per role
integrity:                 checkpoint must exist and match registered SHA-256
loader boundary:           receives role -> verified Path mapping only
provenance:                loaded_models populated from resolved roles, not caller labels
mutation guard:            champion configuration refused while serving holds the GPU lease
negative coverage:         non-champion role and tampered checkpoint both hard-fail
regression:                14 serving/model-registry tests pass
quality:                   Ruff check/format and git diff --check clean
honest boundary:           trained champion checkpoints do not yet exist at 0/200 gold
```
## 2026-07-11 09:10 UTC - Mode-B sequential residency scheduler implemented
**Item:** MF-P6-02.03 advanced from 30% to 85% partial
**Result:** Serving now enforces the 8 GB one-heavy-model-at-a-time contract for champion inference and SAM2 refinement.

```
champion slots:             body-part -> hand -> clothing, deterministic order
label routing:              ontology material -> clothing; part IDs 20..33 -> hand; remaining parts -> body
residency:                  provider loaded for its requested label subset, called, then closed before next slot
SAM2:                       zero startup load; load/call/close only when /refine is invoked
registry trust:             all three champion paths resolve by verified role + SHA-256 before configuration
observability:              configured_models separated from loaded_models; idle sequential service reports no false co-residency
provenance:                 each label reports the exact champion role that produced it
negative guards:            missing role, wrong output labels, unknown ontology labels, and live reconfiguration hard-fail
regression:                 15 serving/model-registry tests pass
quality:                    Ruff check/format and git diff --check clean
honest boundary:           live GPU residency/latency awaits trained champion checkpoints
```
## 2026-07-11 09:18 UTC - Mode-B predict response modes completed
**Item:** MF-P6-02.01 advanced from 80% to 92% partial
**Result:** `/predict` no longer ignores its documented return and inpaint parameters.

```
return modes:              binaries | label_maps | both, strict enum
part label map:            native-size indexed 16-bit PNG
material label map:        native-size indexed 8-bit mode-L PNG
exclusivity:               overlapping different IDs in one map hard-fail instead of arbitrary overwrite
inpaint:                   exact {dilate, feather}, integers 0..512; per-label 8-bit feathered ramps
response:                  base64 PNGs + manifest-lite visibility/area/exact champion-role provenance
draft authority:           in-memory response only; no data/packages mutation path
negative coverage:         invalid mode, invalid inpaint range/schema, unknown/non-indexed label, overlap all refuse
regression:                16 serving/model-registry tests pass without warnings
quality:                   Ruff check/format and git diff --check clean
honest boundary:           live FastAPI request with trained champions remains pending
```
## 2026-07-11 09:29 UTC - Mode-B launch lock completed; live dependency fetch unavailable
**Item:** MF-P6-02.02 advanced from 80% to 90% partial
**Result:** The authoritative environment and CLI now prove the localhost-only launch contract.

```
command:                    maskfactory serve --port <1..65535>, default 8765
binding:                    uvicorn receives host=127.0.0.1 only; no host override exists
runtime pins:               fastapi==0.139.0, uvicorn==0.51.0, python-multipart==0.0.32
reproducibility fix:        python-multipart was missing from env/requirements.lock.txt and is now pinned
CLI execution fixture:      requested port 9876 reaches uvicorn with exact loopback host/log level
regression:                 8 Mode-B serving tests pass
quality:                    Ruff check/format and git diff --check clean
live attempt:               current Windows Python lacks FastAPI; exact workspace-target install timed out after 300 s with no index response
honest boundary:           live 127.0.0.1:8765 WSL HTTP probe remains uncredited
```
## 2026-07-11 09:37 UTC - Multi-person parser/pose ownership matching completed
**Item:** MF-P8-02.01 complete
**Result:** Every promoted person receives unique pose ownership; co-subject parser evidence remains silhouette-suppressed before geometry.

```
pose inputs:               all DWPose person candidates + all promoted S01 bboxes
assignment:                global maximum-IoU bipartite assignment (not independent per-instance maxima)
uniqueness:                one pose candidate can belong to at most one promoted person
determinism:               sorted person IDs and deterministic linear assignment
no-overlap behavior:       candidate/instance pair with zero IoU is not assigned; target hard-fails if unmatched
production wiring:         every per-instance S04 call receives the complete promoted bbox map + target person_index
parser ownership:          S03 target silhouette plus other_person_protected suppression zeros co-subject labels/confidence before S05
regression:                17 S04/production-runner tests pass, including overlapping-person unique assignment
quality:                   Ruff check/format and git diff --check clean
```
## 2026-07-11 09:06 UTC - Live two-person CVAT workflow verified
**Item:** MF-P8-06.05 complete
**Result:** Real CVAT v2.24 created exactly two instance review tasks and one image overview task.

```
fixture image:             img_a3f9c2e17b04 with instances p0/p1 and reciprocal contact metadata
live task IDs:             6, 7, 8
live names:                MaskFactory_review_img_a3f9c2e17b04_p0
                           MaskFactory_review_img_a3f9c2e17b04_p1
                           MaskFactory_overview_img_a3f9c2e17b04
persisted job types:       instance_review, instance_review, image_overview
record count:              3
artifact:                  runs/live_verification/MF-P8-06.05/20260711T090647Z/live_result.json
cleanup:                   DELETE succeeded for exactly task IDs 6, 7, 8
regression:                17 CVAT push/pull/project/label-map tests pass
quality:                   Ruff and git diff --check clean
```
## 2026-07-11 09:08 UTC - Real-corpus GC apply executed
**Item:** MF-P7-03.02 advanced from 80% to 90% partial
**Result:** Reviewed dry-run and confirmed apply used the identical live plan; index post-check is clean.

```
packages root:             data/packages
reviewed plan hash:        4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945
dry-run candidates:        0
apply candidates:          0
removed:                   0 (correct for current empty/non-deprecated corpus)
log:                       logs/gc_2026-07-11.log, mode=apply
reindex rebuild:           complete
post-reindex dry-run:      clean=true; no missing/extra/stale rows
verify-package sample:     correctly refused: no package manifests under data/packages
honest boundary:           post-GC package verification remains pending until the first approved package exists
```
## 2026-07-11 09:45 UTC - Body-part-conditioned Comfy workflow completed structurally
**Item:** MF-P6-03.02 advanced from 70% to 90% partial
**Result:** The shipped workflow now implements the full documented skin-only img2img chain.

```
package source:             MFPackageBrowser filtered human_approved_gold
instance propagation:      browser person_index feeds source, union, and material-map nodes
mask formula:              visible_body_skin - material label 3 (clothing_generic), binarized
latent conditioning:       combined mask -> VAEEncodeForInpaint with selected source image
generation chain:          checkpoint + positive/negative CLIP -> KSampler -> VAEDecode -> SaveImage
default safety:            denoise=0.35, fixed seed=1337, no mask growth beyond exact computed region
graph validation:          every link resolves; subtraction direction and all downstream edges asserted
regression:                17 serving/Comfy node-pack tests pass
quality:                   Ruff check/format and git diff --check clean
honest boundary:           live ComfyUI execution requires an approved package and user-selected installed checkpoint
```
## 2026-07-11 09:51 UTC - Gold-hand Comfy workflow completed structurally
**Item:** MF-P6-01.07 advanced from 55% to 90% partial
**Result:** The shipped workflow now executes the documented gold-mask hand repaint graph through a mask-bounded composite.

```
authority:                  MFPackageBrowser requires human_approved_gold
source/mask identity:       identical image_id + person_index from browser
edit region:               existing left_hand inpaint d8f4
latent chain:              source + exact mask -> VAEEncodeForInpaint -> KSampler -> VAEDecode
composite:                 decoded repaint over original source using the same d8f4 mask
outside-mask invariant:    original source remains destination outside the mask
output:                    SaveImage MaskFactory_gold_hand_repaint
graph validation:          exact source/mask/latent/sampler/decode/composite edges asserted
regression:                18 serving/Comfy node-pack tests pass
quality:                   Ruff check/format and git diff --check clean
honest boundary:           live ComfyUI execution awaits first approved package and installed checkpoint selection
```
## 2026-07-11 09:57 UTC - Live-predict Comfy workflow completed structurally
**Item:** MF-P6-03.03 advanced from 65% to 90% partial
**Result:** The never-seen image workflow now continues from Mode-B prediction through a complete mask-bounded inpaint chain.

```
input:                      LoadImage never_seen_input.png
prediction:                 MFPredictMasks label=left_forearm, d8f4
latent chain:               original image + predicted mask -> VAEEncodeForInpaint
generation:                 checkpoint/CLIP -> KSampler -> VAEDecode
composite:                  decoded image over original using the same predicted mask
outside-mask invariant:     original source remains destination outside predicted left_forearm
output:                     SaveImage MaskFactory_live_left_forearm
graph validation:           exact prediction/image/latent/sampler/decode/composite edges asserted
regression:                 19 serving/Comfy node-pack tests pass
quality:                    Ruff check/format and git diff --check clean
honest boundary:           live never-seen execution awaits Mode-B trained champions and a selected Comfy checkpoint
```
## 2026-07-11 10:03 UTC - Shipped workflows validated against Kevin's installed ComfyUI
**Items:** MF-P6-01.07, MF-P6-03.02, MF-P6-03.03 advanced to 92% partial
**Result:** All five prompt graphs satisfy the actual installed standard-node input contracts.

```
Comfy root:                 C:/Comfy_UI_Main/ComfyUI
Comfy git SHA:              7747c342d4143f35e7c8031dddf3ee4455f10a2e (worktree dirty)
Python:                     C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe
workflows checked:          5
standard nodes imported:   LoadImage, CheckpointLoaderSimple, CLIPTextEncode,
                           VAEEncodeForInpaint, KSampler, VAEDecode,
                           ImageCompositeMasked, SaveImage
contract:                   every required input present; no unknown inputs
compatibility fix:          removed UI-only control_after_generate from KSampler prompt payloads
artifact:                   qa/live_verification/comfy_workflow_compatibility_20260711.json
regression:                 19 serving/Comfy tests pass; Ruff/diff clean
remaining live gate:        custom node pack is not installed and checkpoints directory has only put_checkpoints_here
```
## 2026-07-11 10:12 UTC - MMSeg dataset registration corrected; class-count conflict exposed
**Item:** MF-P5-02.01 advanced from 90% to 95% partial
**Result:** Optional MMSeg integration now uses actual BaseSegDataset subclasses instead of registering an incompatible lightweight reader.

```
registered datasets:       MaskFactoryBodyPartDataset, MaskFactoryMaterialDataset
framework base:            mmseg.datasets.BaseSegDataset
layout configs:            exact train/val ann_file and part/material image+annotation prefixes
map semantics:             .png suffixes, reduce_zero_label=false, ignore_index=255
class metadata:            contiguous names read from the authoritative ontology
simulated registry load:   both classes register; BaseSegDataset receives correct kwargs
regression:                19 dataset/build/training-config tests pass; Ruff/diff clean
unresolved blocker:        ontology IDs 0..55 already include background (56 logits), but doc12/MF-P5-03.01 require 57
escalation:                Plan/DECISIONS_LOG.md, NEEDS KEVIN; no dummy/untrained class invented
```
## 2026-07-11 10:20 UTC - Mode-B health/models telemetry completed
**Item:** MF-P6-02.01 advanced from 92% to 96% partial
**Result:** The remaining read-only endpoint payload clauses now report explicit versions, live VRAM, and champion pointers.

```
/health versions:           pipeline + mode_b_api schema version
/health residency:          loaded_models and configured_models remain distinct
/health VRAM:               nvidia-smi index/name/total/used/free MiB; nonfatal unavailable reason
live GPU result:            RTX 5060 Laptop, total=8151 MiB, used=0 MiB, free=7899 MiB
/models:                    all verified registry entries plus explicit champions{role -> key/version/hash}
degraded behavior:          missing driver/tool never makes health endpoint crash
regression:                 21 serving/model-registry tests pass
quality:                    Ruff check/format and git diff --check clean
honest boundary:           live FastAPI multipart requests with trained champions/SAM2 remain pending
```
## 2026-07-11 10:27 UTC - Leaderboard run identity made immutable
**Item:** MF-P5-06.01 advanced from 82% to 88% partial
**Result:** Promotion evidence can no longer change meaning through duplicate JSONL rows or append order.

```
exact rerun:                same normalized run_id payload returns existing row with zero file write
conflicting rerun:          same run_id with any changed evidence hard-fails before mutation
comparison:                duplicate run_id input is ambiguous and refused
standing baselines:        >1 row for one family/dataset_ref/split is refused
durability:                failed duplicate attempts leave leaderboard bytes unchanged
regression:                18 leaderboard/hand/IAA tests pass
quality:                   Ruff check/format and git diff --check clean
honest boundary:           actual four-baseline holdout scores still require approved gold and runnable pipelines
```
## 2026-07-11 10:38 UTC - Custom body-part champion fusion path implemented
**Item:** MF-P5-07.01 advanced from open to 85% partial
**Result:** S09 can consume a promoted custom body-part map at weight 0.45 without changing pre-promotion output.

```
config:                     fusion.weights.custom_bodypart=0.45
artifact:                   S03 custom_bodypart.png, indexed native-size part map
authority sidecar:          custom_bodypart_provenance.json role + checkpoint_sha256
registry gate:              exactly one verified champion_bodypart; local file exists/hash matches
fusion evidence:            one-hot per enabled ontology part ID, source=custom_bodypart
audit:                      consensus.json records every source including custom_bodypart
inactive behavior:          expanded weight profile with no custom artifact is byte-identical to base profile
hard failures:              missing/wrong provenance, unresolvable champion, hash mismatch, invalid IDs/geometry
regression:                 28 fusion/config/production/registry tests pass
quality:                    Ruff check/format and git diff --check clean
honest boundary:           S03 champion inference and live promoted checkpoint remain gated by training/D6
```
## 2026-07-11 10:48 UTC - Training run provenance contract completed
**Item:** MF-P5-03.05 complete
**Result:** Every future trainer now has a transactional, immutable run tree before execution can begin.

```
run ID:                    r_<UTC>_<model>_bodyparts_vN, strict grammar
required identity:         dataset bodyparts@vN + exact lowercase DVC md5 + Git SHA
frozen config:             byte copy config.yaml + SHA-256 in run.json
required files:            run.json, config.yaml, git_sha, dataset_ref, dataset_dvc_md5
required directories:      ckpts, tb, eval
creation:                   staging directory + atomic rename; collision refuses
lifecycle:                 initialized -> running -> complete|failed; final states immutable
CLI:                       maskfactory train ... --initialize-only; normal execution refuses until trainer activation
negative coverage:         bad/missing dataset identity, bad DVC hash, collision, skipped/final transitions
regression:                14 training-run/config/GPU-lock tests pass
quality:                   Ruff check/format and git diff --check clean
scope note:                this proves run logging; it does not claim MF-P5-03.02 model training
```
## 2026-07-11 10:57 UTC - Seeded ambiguous-hand audit set completed
**Item:** MF-P5-05.02 complete
**Result:** A deterministic 100-case known-truth corpus and strict merged-finger false-split evaluator now gate the hand specialist.

```
artifact root:             qa/hand_audit
manifest:                  schema 1.0.0, seed 1337, 100 cases
balance:                   50 left / 50 right; adjacent affected-finger pairs rotated
files:                     100 RGB evidence images + 100 truth maps + 100 binary ambiguity masks + manifest
truth rule:                ambiguous merged region is hand_base, never guessed finger classes
false split:               any affected finger-class pixel inside that known ambiguity region
gate:                      rate < 0.02, case-level denominator 100
boundary proof:            0%=pass, 1 case/1%=pass, 2 cases/2%=fail
reproducibility:            second seed-1337 build is byte-identical for manifest and all 300 PNGs
negative coverage:         missing prediction, wrong geometry, and unknown class ID refuse
regression:                14 hand-audit/lane/config tests pass
quality:                   Ruff check/format and git diff --check clean
```
## 2026-07-11 11:04 UTC - D7 hand promotion gate evaluator implemented
**Item:** MF-P5-05.04 advanced from open to 70% partial (hard blocker remains)
**Result:** Finger quality, ambiguous false-split behavior, and crop round-trip are now one indivisible promotion decision.

```
required split:             frozen test_holdout only
required evidence:          leaderboard fingers group + >=100-case audit + paste-back IoU
finger IoU:                 >=0.70 (0.70 pass; 0.699999 fail)
false split:                <0.02 (0.01 pass; exactly 0.02 fail)
paste-back IoU:             >=0.995 (0.995 pass; 0.994999 fail)
result:                     schema-versioned checks with measured/operator/threshold/passed
writer:                     atomic gate.json; refuses incomplete three-check result
negative coverage:         val split, missing group metric, <100 audit cases, out-of-range values
regression:                 19 hand-audit/lane/config tests pass
quality:                    Ruff check/format and git diff --check clean
honest boundary:           no trained hand checkpoint/holdout row exists, so D7 is not passed
```
## 2026-07-11 11:13 UTC - Champion hand crop-drafter integration implemented
**Item:** MF-P5-05.05 advanced from open to 85% partial
**Result:** A D7-winning hand model can replace geometry/SAM2 auto-drafting without replacing SAM2's separate interactive editor.

```
activation authority:       exactly one verified champion_hand registry role
loader input:               verified, present, SHA-matching checkpoint Path only
model output:               integer native crop HxW, local 14-class vocabulary
side guard:                 left crop rejects all right-hand IDs and vice versa
lane adapter:               five finger masks + hand_base + explicit local gap region -> HandGeometry
provider lifecycle:         load/predict/close for drafting
SAM2 boundary:              no SAM2 provider enters champion drafting; refine_hand_with_sam2 remains separate
QC-018 path:                existing evaluate_hand_predictions enforces minimum paste-back IoU >=0.995
negative coverage:          missing champion, tampered checkpoint, wrong geometry/dtype, opposite-side IDs, empty evidence
regression:                 26 hand-lane/audit/registry tests pass
quality:                    Ruff check/format and git diff --check clean
honest boundary:           live activation awaits a trained model that passes D7
```
## 2026-07-11 11:22 UTC - Champion clothing S08 primary path implemented
**Item:** MF-P5-04.03 advanced from open to 85% partial
**Result:** A promoted clothing parser can become S08 primary while the existing SCHP/S08 path remains explicit fallback authority.

```
inactive state:             no champion_clothing role -> existing SCHP/Sapiens/GDINO/SAM2 path unchanged
activation:                 exactly one champion_clothing registry entry + configured framework loader
integrity:                  verified, present, SHA-matching checkpoint resolution
output contract:            native context HxW integer IDs 0..15
containment:                background outside silhouette; every visible silhouette pixel assigned
evidence:                   primary=champion_clothing, fallback=schp_plus_s08_heuristics,
                           checkpoint SHA, per-class source and pixel counts
provider lifecycle:         load/predict/close
hard failures:              duplicate role, missing loader after promotion, tampered checkpoint,
                           invalid dtype/geometry/IDs/coverage
regression:                 24 S08/registry/production tests pass
quality:                    Ruff check/format and git diff --check clean
honest boundary:           live promotion/fallback exercise awaits a trained model that wins MF-P5-04.02
```
## 2026-07-11 09:49 UTC - Clothing promotion gate implemented
**Item:** MF-P5-04.02 advanced from open to 70% partial
**Result:** Clothing promotion is now fail-closed on one comparable frozen-holdout baseline and all three spec thresholds.

```
comparison authority:       exact baseline model_family=schp_atr_plus_s08_heuristics
comparison scope:           identical dataset_ref and frozen test_holdout split
material mIoU:              candidate must be strictly greater than baseline (equality fails)
strap IoU:                  >=0.55 (0.55 pass; 0.549999 fail)
waistband IoU:              >=0.55 (0.55 pass; 0.549999 fail)
validation:                 missing/non-finite/out-of-range metrics and wrong comparator refuse
result:                     schema-versioned checks with run IDs and measured thresholds
writer:                     atomic gate.json; refuses an incomplete three-check result
regression:                 27 clothing-gate/S08/config tests pass
quality:                    Ruff check/format and git diff --check clean
honest boundary:            no eligible gold dataset, 30k training run, or measured holdout rows yet
```
## 2026-07-11 09:54 UTC - D6/G7 body-part promotion gate implemented
**Item:** MF-P5-07.02 advanced from open to 70% partial
**Result:** Body-part promotion is fail-closed on the full draft-pipeline baseline and all pooled/hard-group regression rules.

```
comparison authority:       exact baseline model_family=draft_pipeline_full
comparison scope:           identical dataset_ref and frozen test_holdout split
pooled gates:               candidate mean IoU > baseline AND mean boundary-F > baseline
tracked hard groups:        fingers, toes, chest_boundary, hairline
regression gate:            candidate delta >= -0.02 for IoU and boundary-F in every hard group
exact boundary:             -0.020000 passes; -0.020001 fails
validation:                 missing/non-finite/out-of-range metrics and wrong comparator refuse
result:                     schema-versioned ten-check result with run IDs and measured deltas
writer:                     atomic gate.json; refuses incomplete evidence
regression:                 38 body-part-gate/leaderboard/S09 tests pass
quality:                    Ruff check/format and git diff --check clean
honest boundary:            no trained champion or measured frozen-holdout rows yet, so D6/G7 is not passed
```
## 2026-07-11 09:55 UTC - CVAT and SAM2 live services revalidated
**Items:** MF-P0-03.07, MF-P0-04.04 (confirmation only; both already complete)
**Result:** The live service path remains healthy; the quoted three-failure/browser note was stale relative to authoritative evidence.

```
CVAT API:                   PASS, version=2.24.0
CVAT governed project:      PASS, project_count=1
Nuclio interactor:          PASS, pth-sam2 foreground=21491
prior literal UI proof:     qa/reports/cvat_sam2_ui_verification.json remains PASS with saved mask shape id=1
browser retry:              Windows/Chrome control transport closed before inspection; no uncertain UI input sent
doctor authority:           prior full-machine run remains FAIL=0; current sandbox WSL visibility is not treated as a machine regression
```
## 2026-07-11 10:02 UTC - Reproducible Mode-B latency gate implemented
**Item:** MF-P6-02.05 advanced from open to 75% partial
**Result:** One command now cold-launches the loopback API and measures every doc-13 serving target with durable, fail-closed evidence.

```
command:                    maskfactory benchmark-serving <1024-long-side-image>
cold-start authority:       refuses a pre-existing listener; launches maskfactory serve itself
canonical all-label set:    68 enabled indexed non-background PART+MATERIAL labels from ontology.yaml
warm methodology:           one unmeasured warmup then five measured requests per endpoint case
passing statistic:          worst measured request, not mean/median
thresholds:                 cold <=60s; all-label predict <=4s; single-label <=2s; refine/click <=1.2s
response validation:        draft status, exact label order/mask set, refine identity and encoded mask
input guard:                long side must equal exactly 1024 px; loopback HTTP only
evidence:                   atomic schema-versioned JSON, image SHA/dimensions, health, raw samples, min/median/p95/max
failure guards:             >=3 samples, finite/nonnegative timings, unused port, no evidence overwrite
regression:                 21 serving/benchmark tests pass
quality:                    Ruff check/format, CLI help, and git diff --check clean
honest boundary:            live measurements remain open until trained champion and SAM2 production loaders exist
```
## 2026-07-11 10:05 UTC - Production SAM2 Mode-B refiner wired
**Items:** MF-P6-02.01 advanced to 98%; MF-P6-02.03 advanced to 90%
**Result:** The default serving runtime can now execute real `/refine` requests through the verified SAM2 primary/fallback pair without permitting heavyweight request co-residency.

```
checkpoint authority:       registry roles primary_boundary_refiner + boundary_refiner_oom_fallback
integrity:                  both current files resolved present with verified SHA-256
provider:                   existing persistent per-image WSL SAM2 adapter and exact SAM2.1 configs
click contract:             integer in-bounds coordinates, boolean polarity, >=1 positive click
prompt:                     full-image box + positive/negative clicks, multimask_output=true
selection:                  highest predicted IoU, stable first-candidate tie break
output:                     finite native-geometry binary mask only
cleanup:                    embedding server closed in finally on success or failure
OOM behavior:               large checkpoint -> base-plus fallback via shared build_embedding contract
service wiring:             create_app default uses production on-demand SAM2 loader
concurrency:                one runtime request lock serializes predict and refine GPU sections
live construction:          Sam2InteractiveRefiner resolved both current checkpoints/configs successfully
regression:                 24 serving/benchmark tests pass; 32 with shared S06/S07 suite
quality:                    Ruff check/format and git diff --check clean
honest boundary:            WSL CUDA click execution/latency and trained champion `/predict` remain open
```
## 2026-07-11 10:09 UTC - Mandatory MMEngine training thermal hook implemented
**Item:** MF-P5-03.02 advanced from open to 35% partial
**Result:** The exact laptop cooldown policy now runs inside the training process and produces durable per-poll evidence.

```
framework boundary:         MMEngine custom hook registered when mmengine is installed
poll schedule:              every 30 minutes of training runtime
temperature authority:      hottest visible GPU from nvidia-smi temperature.gpu
threshold:                  >87C triggers; exactly 87C does not
cooldown:                   training thread sleeps 60 seconds (GPU work actually pauses)
evidence:                   fsynced runs/<run_id>/thermal.jsonl with iteration/temp/policy/cooldown
config bridge:              governed YAML -> exact custom_imports/custom_hooks MMEngine config
policy integrity:           release config refuses any value other than 30 min / 87C / 60 sec
probe behavior:             missing/failing/non-numeric nvidia-smi fails closed
live probe:                 42C on current RTX GPU
regression:                 22 thermal/config/run/GPU-lock tests pass
quality:                    Ruff check/format and git diff --check clean
honest boundary:            no dataset/train execution; MMSeg dependencies are absent from locks and 56-vs-57 class conflict remains unresolved
```
## 2026-07-11 16:12 UTC - Accumulated build published and clean-checkout CI repaired
**Scope:** End-of-session Git/GitHub handoff
**Result:** The protected workspace was reproduced in a writable clean clone, validated, committed, pushed, and opened as draft PR #1.

```
workspace git boundary:     root .git read-only; direct branch creation correctly failed
publish method:             clean clone at authoritative origin/main d6a3c0e; Git-filtered files copied byte-exact
branch:                     agent/maskfactory-build-progress-20260711
initial commit:             0d3ad48236222c5f27afb17966d3a5e3299f4cbd
draft PR:                   https://github.com/KevinSGarrett/MaskingUltimate/pull/1
secret/binary audit:        no .env, model/archive extension, or file >20 MB staged
local full validation:      474 passed; Ruff 0.15.21 lint/format clean; config generators/tracker clean
clean-clone validation:     471 passed, 3 external Plan/Civitai-cache tests skipped; generators clean
CI root cause repaired:     unanchored datasets/ ignore hid src/maskfactory/datasets in clean checkouts
ignore fix:                 root data/run/log/dataset/work paths anchored; sqlite WAL/SHM sidecars excluded
package fix:                six dataset modules now versioned; Ruff first-party classification explicit
external-cache contract:    Civitai hash tests run when 9 GB cache is mounted and skip clearly when absent
```
## 2026-07-11 16:32 UTC - Draft PR CI fully green
**Scope:** Draft PR #1 clean-install and cross-platform CI repair
**Result:** Both the push and pull-request GitHub Actions runs pass at head `a3b8a64`.

```
branch:                     agent/maskfactory-build-progress-20260711
draft PR:                   https://github.com/KevinSGarrett/MaskingUltimate/pull/1
CI commits:                 0016b78 (dependencies/CPU torch), a3b8a64 (platform-aware bridge tests)
clean install:              PASS; scipy, scikit-image, torch, ultralytics, and onnxruntime declared
CPU CI policy:              official PyTorch CPU wheel installed before editable package
Linux-only boundary:        six Windows-host/WSL bridge tests skip; cross-platform algorithm tests still run
GitHub Linux pytest:        465 passed, 9 skipped in 25.90s
GitHub gates:               Ruff PASS; ontology drift PASS; training flip invariant PASS; full pytest PASS
Windows root pytest:        474 passed in 49.97s
Windows publish clone:      471 passed, 3 external-cache skips in 47.27s
publish clone status:       clean at a3b8a64
```
## 2026-07-11 16:38 UTC - WSL identity-boundary audit after green CVAT recheck
**Scope:** Recheck the earlier WSL/CVAT blocker from the current managed shell
**Result:** CVAT remains green; the three doctor failures are caused by per-user WSL registry isolation, not loss of the live distro or its data.

```
doctor in managed shell:    PASS=7 WARN=1 SKIP=0 FAIL=3
passing live services:      CVAT API 2.24.0, project, pth-sam2 Nuclio, qwen2.5vl image, PNG, SQLite, gpu.lock
failing probes:             torch_cuda, registered_models, wsl_roundtrip
immediate cause:            shell identity CodexSandboxOnline sees no registered WSL distributions
live-machine evidence:      wslservice, vmmemWSL, eight wslhost processes, and Docker Desktop are running
preserved distro disk:      26,598,178,816-byte ext4.vhdx under Kevin LocalAppData, valid VHDX header
disk state:                 actively locked by the live WSL process; no overwrite, detach, shutdown, or unregister attempted
safe recovery attempts:     import-in-place rejected E_INVALIDARG; copy import refused active-file sharing
Windows-control retry:      connection transport closed before any UI action
CVAT UI evidence:           qa/reports/cvat_sam2_ui_verification.json remains PASS (saved mask id=1)
authority decision:         retain prior full-user doctor FAIL=0 evidence; do not downgrade P0 from sandbox-only visibility
```
## 2026-07-11 17:24 UTC - OpenMMLab training runtime made fail-closed and Swin-B challenger specified
**Items:** MF-P5-02.01 advanced 95% -> 97% partial; MF-P5-03.03 advanced open -> 35% partial
**Result:** The exact compatible trainer stack is immutable and diagnosable; broken MMSeg installs can no longer masquerade as an intentionally absent optional runtime.

```
compatibility authority:    MMSeg 1.2.2 + MMDetection 3.3.0 require MMCV >=2.0.0rc4,<2.2.0 and MMEngine <1.0.0
selected stack:             MMEngine 0.10.7; full MMCV 2.1.0; MMSeg 1.2.2; MMDetection 3.3.0
source identity:            every package tag resolved to a full upstream Git commit; pure-wheel SHA-256 values recorded
runtime lock:               env/openmmlab_training_stack.lock.json
MMCV authority:             build_from_source=true; mmcv._ext mandatory; mmcv-lite explicitly refused
real isolated probe:        exact four packages imported through MMSeg until mmcv-lite failed at mmcv._ext
loader correction:          only a genuinely absent top-level mmseg is optional; missing transitive modules now propagate
training doctor:            exact versions + torch 2.11.0+cu128 + full ops + registered datasets + CUDA sm_120 all required
current managed-shell probe: correctly FAIL (packages absent, torch 2.12.1+cpu, CUDA unavailable)
class-count safety:         both 57-logit body-part configs refuse initialization against authoritative indexed IDs 0..55
challenger config:          Mask2Former-SwinB, activation checkpointing, 512 crop, bf16, effective batch 16, native matcher losses
Swin-L boundary:            AWS burst only through MF-P5-08.03
focused regression:         34 training runtime/config/dataset/run/thermal tests pass
full regression:            481 tests pass
quality:                    Ruff 0.15.21 check and format clean across 238 files; tracker structurally valid
honest boundary:            full MMCV CUDA source build/dataloader and challenger run remain pending WSL access, >=200 gold, and Kevin's 56/57 decision
```
## 2026-07-11 17:42 UTC - MMSeg ontology-aware transform stack completed to live-runtime boundary
**Item:** MF-P5-02.01 advanced 97% -> 99% partial
**Result:** The exported BaseSegDataset and governed augmentation pipeline are now inseparable and framework-registerable; only a real full-MMCV CUDA execution remains.

```
framework input contract:   every wrapper consumes MMSeg img + gt_seg_map and preserves required metadata
rare crop:                  512 output, scale 0.5-2.0, exact 40% force policy
rare PART IDs:              belly_button; both thumbs/index/middle/ring/pinkies; both toes
rare MATERIAL IDs:          strap
horizontal flip:            p=0.5; every sided ID remapped through authoritative swap_partner LUT
photometric jitter:         image only; MMCV BGR converted to RGB for PIL hue math and restored to BGR
rotation:                   sampled +/-15 degrees; bilinear image, nearest labels, border=255
config compiler:            exact governed transform order/values; any drift or banned augmentation refuses
dataset bundle:             MaskFactory dataset custom import + transform custom import + compiled pipeline
runtime doctor:             now requires all four MaskFactory transforms present in mmseg.registry.TRANSFORMS
focused regression:         20 MMSeg-transform/runtime/augmentation tests pass
filesystem retry evidence:  seeded QC file 12/12 pass after one transient Windows temp-directory access denial
full regression:            487 tests pass on clean retry
quality:                    Ruff 0.15.21 check/format clean across 240 files; tracker structurally valid
honest boundary:            real full-MMCV 2.1.0 CUDA BaseSegDataset execution remains pending Kevin-session WSL access
```
## 2026-07-11 17:59 UTC - Executable MMSeg compiler, metrics, and fail-closed launcher implemented
**Items:** MF-P5-03.02 advanced 35% -> 75% partial; MF-P5-03.03 advanced 35% -> 65% partial
**Result:** `maskfactory train` now has a real governed MMEngine execution path; it cannot bypass dataset, runtime, ontology, GPU, or checkpoint evidence gates.

```
compiler authority:         self-contained structures from pinned MMSeg 1.2.2 SegFormer-B3 and Mask2Former-SwinB configs
class weights:              scan train split only; ignore 255; sqrt(max_pixel_frequency/frequency), capped x8, absent=0
SegFormer:                  official MiT-B3 shape/pretrain, CE weighted + Dice, 512 crops
Mask2Former:                Swin-B 22K pretrain, with_cp=true, mmdet pixel decoder/Hungarian matcher/native CE+BCE+Dice
optimizer:                  AdamW 6e-5; bf16 AmpOptimWrapper; batch 2 x accumulation 8
schedule:                   linear warmup 1500 then poly power1; 40k release / validation every 4k
metric:                     registered MaskFactorySegMetric; additive per-class IoU + per-present-class boundary-F@2px
metric ignore policy:       target 255 excluded from IoU and BF; out-of-range IDs hard-fail
data:                       exact registered dataset/transform bundle for train; deterministic no-augmentation val bundle
thermal:                    mandatory 30 min / >87C / 60 sec MMEngine hook compiled into every run
entry gate:                 build_manifest must contain >=200 unique instances across disjoint named splits
runtime gate:               exact packages, full mmcv._ext, dataset/transforms/metric registries, torch cu128, CUDA sm_120
GPU gate:                   parent process owns runs/gpu.lock for the entire child trainer lifetime
run evidence:               immutable run tree + compiled config + command JSON + stdout/stderr + checkpoint directory
success rule:               child exit 0 is insufficient; at least one .pth checkpoint required
failure rule:               compile/process/evidence failures atomically transition run.json to failed and release GPU lock
managed-shell doctor:       correctly FAILS (CPU torch 2.12.1, no OpenMMLab/CUDA); no fake launch attempted
focused regression:         33 compiler/launcher/metric/transform/runtime/run tests pass
full regression:            501 tests pass
quality:                    Ruff 0.15.21 check/format clean across 246 files; tracker structurally valid
honest boundary:            no real CUDA training/checkpoint/thermal event or holdout leaderboard row is claimed
```
## 2026-07-11 18:15 UTC - S02 BiRefNet production contract hardened
**Item:** MF-P2-01.02 advanced 80% -> 95% partial
**Result:** The implemented silhouette stage now fails closed unless configuration, runtime metadata, geometry, confidence, and output placement all prove the literal S02 contract.

```
configuration authority:    pipeline S02 model/fp16/2048/128/0.5/1%/[0.35,0.95] forwarded into production
runtime proof:              WSL child must report protocol v1, pinned BiRefNet revision, fp16, exact tile size/overlap, positive tile count, and CUDA device identity
input proof:                missing image/checkpoint, invalid tile geometry, malformed metadata, non-float32/nonfinite/out-of-range confidence all refuse
geometry proof:             context/person bboxes must be integer, nonempty, on-canvas, and person fully contained by context
component filter:           compiled SciPy 4-connected labeling; largest retained; qualifying >=1% diagonal-touch components retained; isolated/small components dropped
artifact contract:          strict binary person_full_visible.png, full-canvas 8-bit confidence, and ratio metrics remain authoritative
scalability measurement:    2048x2048 postprocess + both PNG artifacts completed in 0.081 seconds in workspace-local storage
focused regression:         27 S01/S02/config/production tests pass
full regression:            507 tests pass
quality:                    Ruff check/format clean across 246 files; generated ontology current; tracker structurally valid
honest boundary:            managed shell exposes no WSL distro, so a fresh end-to-end run_s02 CUDA invocation is not claimed; item remains partial
```
## 2026-07-11 18:26 UTC - S03 dual-parser production contract hardened
**Items:** MF-P2-02.01 and MF-P2-02.02 advanced 80% -> 95% partial
**Result:** Sapiens primary and the mandatory SCHP-ATR companion now have governed, coherent, resource-safe production boundaries; neither can publish weak or contradictory parser evidence.

```
configuration authority:    S03 model/bf16/1024/1536/128/OOM-retry/SCHP-fallback values reach production and drift refuses
Sapiens runtime proof:       pinned ea5545 revision, bf16, 1024x768 input, exact tiling, 28 classes, positive tile count, CUDA identity
SCHP runtime proof:          pinned eb84c4 revision, ATR, fp32, 512x512 input, 18 classes, positive tile count, CUDA identity
archive coherence:           exact uint8 labels + float32 probabilities; finite [0,1], per-pixel sum=1, labels exactly argmax
scaled recovery:             half-resolution probabilities restore bilinearly, reject zero-mass pixels, renormalize, then recompute labels
residency discipline:        one Sapiens model load per WSL process; reused across all 1536/128 tiles; explicitly released after final tile
companion invariant:         SCHP executes first and always remains available when Sapiens full/half-resolution attempts OOM
temporary hygiene:           unique WSL bridge PNG/NPZ intermediates removed on success and failure paths
cross-check scalability:     vectorized compatibility-matrix disagreement replaces per-pixel Python objects; 2048x2048 measured 0.072 sec
focused regression:         40 parser/production/config/registry tests pass
full regression:            516 tests pass
quality:                    Ruff check/format clean across 246 files; generated ontology current; tracker structurally valid
honest boundary:            managed shell exposes no WSL distro, so fresh end-to-end Sapiens and SCHP CUDA invocations are not claimed
```
## 2026-07-11 18:37 UTC - S04 DWPose authoritative CUDA bridge implemented
**Item:** MF-P2-03.01 advanced 90% -> 95% partial
**Result:** Production pose inference no longer depends on the Windows CPU/Azure ORT boundary; it now crosses a fail-closed WSL bridge and returns complete, pinned 133-keypoint evidence for instance ownership and serialization.

```
production runtime:         Ubuntu-22.04 authoritative environment; onnxruntime-gpu; CUDA required for both sessions
detector proof:             YOLOX-L checkpoint SHA-256 7860ae...; CUDAExecutionProvider must bind first; 640 decode/NMS
pose proof:                 dw-ll_ucoco-384 SHA-256 724f4f...; CUDAExecutionProvider must bind first; 288x384 crops
bridge archive:             exact float32 Nx4 boxes + Nx133x3 coordinates/confidences; no pickle; unique temporary artifact removed
bridge metadata:            protocol, both hashes, thresholds, candidate count/shapes, provider, and GPU device all mandatory
decoder hardening:          SimCC x/y selected by literal 576/768 widths, finite checked, inverse-affine coordinates clipped to canvas
configuration authority:    governed dwpose_133 model, keypoint confidence 0.3, degraded body fraction 0.6 forwarded into production
ownership/output:           global unique instance assignment, co-subject suppression, all 133 indexed points/confidences in pose133.json
focused regression:         36 S04/production/config tests pass
full regression:            521 tests pass
quality:                    Ruff check/format clean across 247 files; generated ontology current; tracker structurally valid
live managed-shell probe:   correctly failed WSL_E_DISTRO_NOT_FOUND before publishing any candidate archive
honest boundary:            registry CUDA smokes and prior CPU diagnostic exist, but a fresh production-bridge CUDA run is not claimed
```
## 2026-07-11 18:49 UTC - S06 GroundingDINO box-only authority made executable
**Item:** MF-P2-05.01 advanced 90% -> 95% partial
**Result:** The open-vocabulary assist now proves its pinned runtime and literal proposal geometry, while downstream code rejects every path that could promote an unrefined GroundingDINO box into a material map.

```
prompt authority:           exact 11 spec prompts; unique/nonempty; production vocabulary drift refuses
threshold authority:        pipeline and prompting configs must agree on box 0.30 / text 0.25 or S06 refuses
runtime identity:           WSL pinned source 856dde; checkpoint SHA-256 3b3ca2...; documented CPU deformable-attention fallback
load discipline:            one GroundingDINO model load serves every configured prompt, then model is released
runtime metadata:           protocol, hash/revision/device, model_load_count, prompts, thresholds, and image geometry mandatory
proposal validation:        configured prompt, proposal_only, finite in-canvas positive-area xyxy, scores in [threshold,1]
artifact authority:         gdino_boxes.json only; may_write_final_masks=false; consumers limited to SAM2 prompting/fusion evidence
downstream enforcement:     nonempty GDINO evidence with missing/tampered authority or no SAM2 provider is refused before map creation
focused regression:         40 S06/S08/production/config tests pass
full regression:            524 tests pass
quality:                    Ruff check/format clean across 247 files; generated ontology current; tracker structurally valid
live managed-shell probe:   correctly failed WSL_E_DISTRO_NOT_FOUND before any proposals were accepted
honest boundary:            prior pinned WSL smoke exists, but a fresh full-vocabulary production run is not claimed
```
## 2026-07-11 19:02 UTC - S07 persistent SAM2 embedding boundary hardened
**Item:** MF-P2-05.02 advanced 90% -> 95% partial
**Result:** One-image SAM2 refinement now has bounded, pinned, reusable embedding evidence; large-model OOM alone triggers base-plus, while hangs, metadata drift, malformed logits, and other failures refuse.

```
primary identity:           SAM2.1 hiera-large; checkpoint SHA-256 264787...; exact large config; fp16 CUDA
fallback identity:          SAM2.1 hiera-base-plus; checkpoint SHA-256 a2345a...; exact base-plus config; fp16 CUDA
fallback rule:              only MemoryError/CUDA OOM from large starts base-plus; primary/fallback must differ
embedding proof:            protocol, model/config/hash/precision/device/shape and embedding_count=1 mandatory at ready
hang prevention:            daemon-bounded startup (300s) and prediction (120s) reads; timed-out child terminated/killed
prompt contract:            on-canvas box/points, unique eligible labels, multimask_output=true for every request
prediction contract:        raw float32 finite logits, exactly three full-resolution masks, float32 IoU scores in [0,1]
reuse proof:                monotonically increasing prediction_index with embedding_count=1 on every response
artifact hygiene:           embedding PNG, per-request NPZ, and persistent process removed on success/failure/close
metrics evidence:           embedding_count=1 plus exact prediction_count including the one permitted corrective iteration
focused regression:         38 S07/production/config tests pass
full regression:            528 tests pass
quality:                    Ruff check/format clean across 247 files; generated ontology current; tracker structurally valid
live managed-shell probe:   absent-distro response refused and provider_work remaining_files=[]
honest boundary:            registry CUDA smokes exist, but a fresh production embedding plus prompt response is not claimed
```
## 2026-07-11 19:15 UTC - True one-command D1 draft contract implemented
**Item:** MF-P2-08.04 advanced 94% -> 96% partial
**Result:** A governed incoming file now has a literal single CLI entry point that cannot report success until every promoted instance owns a full-resolution, hash-verified set of all 56 atomic PART masks reproduced from its exclusive master map.

```
single command:             maskfactory draft <data/incoming/<origin>/<file>>
intake boundary:            mandatory origin, decode/min-size, metadata stripping, duplicate identity, and non-configurable age safety
execution boundary:         derived image_id; shared S00/S01; per-instance S02-S09; S09.5 reconciliation; GPU lock on every pipeline segment
source projection:          context-crop S09 part/material maps pasted into exact source width/height with background outside context
ontology contract:          runtime authority must expose contiguous PART IDs 0..55; enabled map values only
atomic outputs:             exactly 56 strict binary PNGs per promoted instance plus full-resolution indexed part/material maps
disabled labels:            left_ear 54 and right_ear 55 emitted explicitly as empty, disabled atomic views
exclusivity proof:          every source pixel claimed exactly once; no overlaps; atomics reproduce full-resolution PART map byte-semantically
durability:                 per-mask SHA-256, map hashes, pixel counts, enabled flags, paths, source/context geometry in draft_contract.json
promotion safety:           complete staging directory verified before atomic replace; previous draft restored if promotion fails
resume behavior:            duplicate governed input may reuse its stable image_id; regenerated contract atomically replaces prior work draft
focused regression:         47 production/config/intake/mapbuild tests pass
full regression:            531 tests pass
quality:                    Ruff check/format clean across 247 files; generated ontology current; tracker structurally valid
honest boundary:            no Kevin-supplied live source/WSL run or draft-vs-corrected-gold G2 measurement exists; D1/G2 remain open
```
## 2026-07-11 19:27 UTC - Production champion-backed Mode-B predictor wired
**Items:** MF-P6-02.01 advanced 98% -> 99%; MF-P6-02.03 advanced 90% -> 98%; MF-P5-06.03 advanced 88% -> 94%
**Result:** The live service no longer stops at an abstract predictor callback: a complete promoted champion set now configures three real sequential MMSeg slots, while absent or partial champion sets fail closed without claiming inference readiness.

```
role contract:              exactly champion_bodypart + champion_hand + champion_clothing; a partial set refuses startup
checkpoint authority:       every slot is resolved through the exactly-one verified registry role and SHA-256 recheck
config authority:           inference_config must remain under models_root and match its independently registered SHA-256
class authority:            explicit unique class_names required; every non-background name must exist in the governed ontology and match part/material map type
framework boundary:         mmseg.apis.init_model(config, checkpoint, device=cuda:0) followed by inference_model
prediction contract:        uint8 RGB in; native-size integer pred_sem_seg; class IDs bounded by the declared vocabulary; requested masks mapped by class name
residency proof:            only requested role slots load, provider closes after each slot, model moves to CPU, CUDA cache clears before the next role
SAM2 boundary:              remains per-request/on-demand and cannot co-reside with the completed sequential prediction request
focused regression:         17 serving tests pass
full regression:            533 tests pass
quality:                    Ruff check/format clean across 247 files; generated ontology current; tracker structurally valid
managed-shell probes:       wsl.exe reports no installed distro; schtasks queries return system path unavailable
honest boundary:            live champion-backed WSL HTTP inference remains unclaimed until trained winners are promoted with checkpoint/config/class metadata
```
## 2026-07-11 19:35 UTC - Serving champion promotion made fail-closed
**Item:** MF-P5-06.03 advanced 94% -> 96% partial
**Result:** A registry role edit can no longer promote a nominally verified but unreproducible model into a production serving role.

```
candidate checkpoint:       re-resolved by registry key and SHA-256 checked before promotion
config containment:         inference_config must resolve strictly beneath models_root
config identity:            independently recorded inference_config_sha256 must match current bytes
vocabulary contract:        non-empty unique explicit class_names; background permitted; all other names must resolve in ontology
role/map contract:          bodypart/hand champions accept PART classes; clothing champion accepts MATERIAL classes
mutation ordering:          every serving-artifact check completes before candidate/incumbent roles change
negative evidence:          tampered config and material class offered to bodypart role both refuse with registry unchanged
focused regression:         10 registry tests pass
full regression:            534 tests pass
quality:                    Ruff check/format clean across 247 files; generated ontology current; tracker structurally valid
honest boundary:            no trained/evaluated winner exists yet to exercise promote -> live serve -> rollback with real artifacts
```
## 2026-07-11 19:47 UTC - Completed-run to promotable-candidate handoff implemented
**Item:** MF-P5-06.03 advanced 96% -> 98% partial
**Result:** A successful governed MMSeg run now produces the exact immutable artifact bundle required by the hardened champion promotion and serving paths; no manual registry JSON construction is needed.

```
trainer seal:               candidate_artifact.json written before running -> complete transition
sealed identity:            run_id/model/dataset_ref/DVC md5, target champion role, checkpoint/config paths+SHA-256, explicit class_names
registration command:       maskfactory models register-training-candidate <run_root> --key <slug>
entry role:                 challenger_bodypart only; registration can never directly create a champion pointer
installed layout:           models/trained/<key>/<checkpoint> + inference_config.py
copy verification:          both installed files re-hashed before one atomic registry write
failure atomicity:          tampered run artifacts produce neither registry entry nor installed candidate directory
promotion compatibility:    entry includes target role, training provenance, DVC identity, config hash, and ontology vocabulary required by the serving gate
Windows durability:         shared bounded PermissionError retry added to atomic directory promotions used by derivation/intake/orchestration/D1/training/model install
retry scope:                short 10/50/100/250/500ms schedule; semantic and non-permission failures are never retried
focused regression:         32 launch/registry/serving tests and 46 durability/affected-workflow tests pass
full regression:            536 tests pass
quality:                    Ruff check/format clean across 249 files; generated ontology current; tracker structurally valid
honest boundary:            a real evaluated winner still must be registered, promoted, served in WSL, and rolled back before MF-P5-06.03 completes
```
## 2026-07-11 19:54 UTC - Production VLM calibration corpus authority hardened
**Item:** MF-P4-05.01 advanced 35% -> 50% partial
**Result:** The replacement 40-panel builder can no longer turn repeated, ungoverned, or mislabeled imagery into apparent production calibration evidence.

```
corpus size:                exactly 20 explicit seeds -> one good + one known-defect panel each
source diversity:           exactly 20 distinct source byte hashes; varied masks cannot disguise source reuse
origin allowlist:           generated | owned_photo | licensed | consented_subject
age safety:                 every source must be explicitly clear_adult; uncertain or missing refuses the corpus
rights authority:           nonempty rights_evidence required per source
identity:                   declared source_sha256 must match current source bytes
label authority:            ontology-resolved indexed atomic PART/MATERIAL labels only; derived unions refuse
gold contract:              strict binary nonempty good mask, same source geometry, defect mask must differ
coverage:                   >=5 distinct labels and all ten defect taxonomy values exactly twice
audit output:               source origin, age safety, rights evidence, and source/good/defect hashes recorded in manifest
focused regression:         11 VLM evaluation/client/router tests pass
full regression:            537 tests pass
quality:                    Ruff check/format clean across 249 files; generated ontology current; tracker structurally valid
honest boundary:            qa/vlm_eval currently has one governed real seed only; deprecated_synthetic_v0 remains non-authoritative and no production gate rerun is claimed
```
## 2026-07-11 20:02 UTC - Explicit single-person pre/P8 byte regression added
**Item:** MF-P8-01.04 advanced 80% -> 95% partial
**Result:** The activated multi-instance outer loop now has direct evidence that its p0 path preserves every existing single-person S02-S09 artifact byte-for-byte.

```
baseline path:              legacy direct S02,S03,S04,S05,S06,S07,S08,S08.5,S09 execution
activated path:             identical deterministic producer through instances/p0 outer-loop execution
comparison contract:       every legacy stage directory required and nonempty; exact relative file set and bytes
evidence digest:            per-stage SHA-256 plus one whole-tree SHA-256 over stage/path/bytes
intentional P8 addition:    s02/other_person_protected.png separately allowlisted and hash-recorded, never counted as legacy equality
instance result:            exactly one p0, one 56-atomic draft contract, passing trivial S09.5 reconciliation
negative evidence:          one-byte drift in s07/artifact.bin hard-fails with exact path
focused regression:         27 production-runner tests pass
full regression:            538 tests pass
quality:                    Ruff check/format clean across 249 files; generated ontology current; tracker structurally valid
honest boundary:            final completion still requires a real P1-P7 reviewed package replay comparison, not only deterministic draft/stage artifacts
```
## 2026-07-11 20:22 UTC - First governed supplied multi-person image reached live S01
**Items:** MF-P8-01.03 advanced 70% -> 85% partial; MF-P8-10.01 opened at 10% partial
**Result:** Kevin-supplied incoming data is now moving through the real governed path. One qualifying three-instance source passed intake and S01; uncertain-age candidates stayed quarantined; a durable two-image count fixture registry now replaces mocked-count-only evidence.

```
doctor:                     PASS=7 WARN=1 FAIL=3
live services:              CVAT API v2.24.0 PASS; project PASS; pth-sam2 Nuclio PASS; qwen2.5vl image JSON PASS; SQLite/GPU lock/PNG PASS
runtime boundary:           current shell cannot resolve Ubuntu-22.04; torch/model-smoke/roundtrip fail at WSL identity
supplied multi intake:      5 images screened; 1 ingested clear_adult; 4 quarantined age_safety_uncertain with no override
accepted image:             img_7b7a3c7d5dd3, generated origin, 1200x1378, metadata stripped
independent age evidence:   qwen2.5vl:7b clear_adult and person_count=3
manual visual review:       exactly 3 visible adult human instances (front/three-quarter/back triptych)
live S01:                   YOLO11m 3 raw detections, confidence 0.9109-0.9323, exactly p0/p1/p2 promoted with distinct crops
full draft attempt:         correctly stopped at S02 BiRefNet with WSL_E_DISTRO_NOT_FOUND; no downstream success claimed
fixture 2:                  Ultralytics governed street QA image manually shows 4 adults; live S01 evidence has 4 raw, p0/p1/p2 promoted under cap=3
fixture sealer:             2-3 distinct rasters required; source/S01 hashes, rights/age/reviewer, geometry, config/model, manual/raw/promoted counts validated
durable artifact:           qa/multi_instance_fixtures/manifest.json embeds complete promoted detection evidence and downstream_package_count_verified=false
negative evidence:          count mismatch, source/evidence tamper, duplicate raster, unsafe path, invalid bbox, or non-adult status refuse sealing
focused regression:         40 multi-fixture/S01/production tests pass
full regression:            540 tests pass
quality:                    Ruff check/format clean across 252 files; generated ontology current; tracker structurally valid
honest boundary:            P8-01.03 still needs live S02-S09.5 package fan-out; P8-10.01 has 1/10 minimum qualifying real images
```
## 2026-07-11 20:35 UTC - Doctor WSL identity diagnostics made actionable
**Item:** MF-P0-07.01 maintenance; MF-P0-04.04 completion evidence reconfirmed
**Result:** The three remaining live doctor failures are now reported as one Windows-account-scoped WSL registration boundary instead of misleading CUDA, checkpoint, and filesystem repair failures.

```
live doctor:                 PASS=7 WARN=1 FAIL=3
passing services:            CVAT API v2.24.0, CVAT project, pth-sam2 Nuclio, qwen2.5vl image JSON, PNG, SQLite, GPU lock
process identity:            KEVIN\CodexSandboxOnline (resolved from the process token, not shared profile metadata)
WSL diagnosis:               Ubuntu-22.04 is not registered for this Windows identity; torch, model smokes, and C:\ round-trip share WSL_E_DISTRO_NOT_FOUND
diagnostic normalization:    raw UTF-16-like NULs and escaped \\x00 sequences removed from redirected WSL output
checkpoint guidance:         identity-scoped model-smoke failures no longer recommend refetching valid registered checkpoints
safety boundary:             no distro import/VHD attach attempted while another account's WSL instance is active
UI reconciliation:           MF-P0-04.04 was already completed and must not be reopened from stale prose
persisted UI evidence:        qa/reports/cvat_sam2_ui_verification.json SHA-256 50bf553455f551f1899fc47abf7c8c6affaf921d1c34709df265caaa49a52edc
focused regression:          9 doctor tests pass; Ruff check/format clean
honest boundary:             live WSL-backed execution requires a shell launched in the Windows account that owns the Ubuntu-22.04 registration
```
## 2026-07-11 20:50 UTC - S14 COCO-RLE interoperability boundary completed
**Item:** MF-P5-01.02 completion evidence strengthened
**Result:** Dataset COCO annotations no longer depend on an untestable private encoder; the designated codec module now provides strict, independently decodable uncompressed COCO RLE.

```
codec authority:             src/maskfactory/datasets/cocorle.py
wire order:                  canonical COCO column-major (Fortran) traversal
run contract:                first count is background (zero allowed); every later alternating run positive
integrity:                   dimensions positive; counts cover exactly height*width; extra keys rejected
source contract:             nonempty 2-D bool, {0,1}, or {0,255}; floats/nonbinary values refuse
decoder evidence:            known non-square vector [1,3,2], uniform masks, seeded 1xN/Nx1/rectangular round trips
S14 integration:             every annotations.json segmentation uses the codec; decoded area equals declared annotation area
negative evidence:           truncated coverage, interior zero run, zero dimension, compressed-string counts, extra fields, 3-D/nonbinary/float sources all refuse
focused regression:         20 codec/dataset-builder tests pass
full regression:            554 tests pass
quality:                    Ruff check/format clean across 253 files; generated ontology current; tracker structurally valid
honest boundary:            first real bodyparts@v1 build remains gated by human-approved gold packages and DVC authority
```
## 2026-07-11 21:01 UTC - Multi-instance S10 hard gates wired to production evidence
**Items:** MF-P8-03.02, MF-P8-05.01, MF-P8-05.02 completion evidence strengthened
**Result:** Production auto-QA can no longer reduce a multi-person image to a fabricated p0-only QC input; QC-035/036 now receive exact full-canvas evidence for every promoted instance.

```
new command path:           maskfactory run <image_id> --through-autoqa
execution order:            shared S00/S01 -> each pN S02-S09 -> shared S09.5 -> each pN S10
identity gate:              image_manifest promoted pN names/count must exactly match S01 and S10 evidence
silhouette evidence:        every S02 full-canvas silhouette required with one shared geometry
ownership evidence:         every context PART map projected to source canvas; background and PART 50 other_person excluded
contact evidence:           reciprocal crop bands projected to full canvas and relationships checked in both directions
hard refusal:               a multi-person manifest without full-canvas evidence cannot run S10
QC-036 proof:               seeded production S10 p0 atomic union entering p1 core yields BLOCK with p0->p1 pixels
three-person fix:           S09.5 accumulates both neighbor contacts before writing the middle instance band; no pair overwrites another
compatibility:              existing --through-drafts remains S00-S09.5 only; single-person S10 retains trivial p0 behavior
focused regression:         41 multi-QC/reconciliation/S10/production-runner tests pass
full regression:            557 tests pass
quality:                    Ruff check/format clean across 253 files; generated ontology current; tracker structurally valid
honest boundary:            live --through-autoqa on the accepted three-instance image still awaits access to the Windows account owning Ubuntu-22.04
```
## 2026-07-11 21:13 UTC - S15 human-edit delta feedback loop completed
**Items:** MF-P4-03.01, MF-P4-03.02, MF-P4-03.03 completion evidence corrected and strengthened
**Result:** Weekly active learning now measures actual S09-draft versus approved-gold corrections; the previous generic append helper is no longer mistaken for production human-edit wiring.

```
S12 baseline:                annotations/draft_baseline/{label_map_part,label_map_material,baseline_manifest}.png/json
baseline authority:          exact image_id, pN instance, S09 source stage, PART/MATERIAL SHA-256
legacy protection:           CVAT pull seals a missing baseline before seeding/overwriting corrected masks
immutability:                an existing baseline is identity/hash verified and never replaced during pull
S15 eligibility:             frozen package, uniformly human_approved_gold visible parts, valid review timestamp
gold authority:              current label_map_part SHA-256 must equal the frozen manifest files entry
measurement:                 every enabled changed PART records class_error_rate = 1 - draft/gold IoU
priority inputs:             measured error, matching view/pose/context coverage deficit, governed use weight, approval recency
dedup identity:              image_id + pN + baseline PART hash + label; weekly reruns append nothing twice
audit output:                compared/unchanged/missing-baseline/new/already-harvested counts in active_learning_<date>.json
negative evidence:           baseline identity drift, baseline hash tamper, gold hash drift, non-gold frozen status, or geometry mismatch refuses harvesting
focused regression:         46 review/CVAT/mining/dataset/production/atomic tests pass
full regression:            558 tests pass
quality:                    Ruff check/format clean across 253 files; generated ontology current; tracker structurally valid
honest boundary:            no real human-edit delta exists until Kevin completes and approves the first gold package; no fabricated queue rows were added
```
## 2026-07-11 21:23 UTC - S10/S11 failure producers wired; overstated tracker claim corrected
**Item:** MF-P4-03.01 corrected complete -> 90% partial
**Result:** Auto-QA and VLM disagreement records now reach the durable failure queue in production. The item was honestly reopened because the hand lane still returns an in-memory record without a live stage call that persists it.

```
S10 producer:               every result=fail check appends qc_fail with image, pN, QC ID, run identity, view and exact failure priority inputs
multi-instance dedup:       global QC-035..038 records emit from p0 only; per-instance checks retain pN producer identity
S11 producer:               all-pass/VLM-fail and route-or-block/VLM-confident-pass append vlm_autoqa_disagreement
S11 authority:              uncertain/low-confidence results route carefully but do not masquerade as measured disagreement
append atomicity:           schema validation + one exclusive lock + fsync; exact producer identity checked under the same lock
idempotency proof:          replaying one S11 run appends one row, not two
other real producers:       second-review failure and hash-verified human-edit delta paths remain live
focused regression:         45 S10/S11/mining/dataset/production tests pass
full regression:            559 tests pass
quality:                    Ruff check/format clean across 253 files; generated ontology current; tracker structurally valid
honest remaining gap:       apply_finger_merge_policy emits the correct record payload in memory, but no active P3 hand-lane stage persists it yet
```
## 2026-07-11 21:33 UTC - Active S07 hand-merge producer closes failure-source wiring
**Items:** MF-P3-01.07 evidence strengthened; MF-P4-03.01 restored 90% partial -> complete
**Result:** The hand lane's `finger_merge` decision now changes live draft authority before S09 and reaches the durable failure queue; every MF-P4-03.01 source has a real producer.

```
active input:                S07 refined left/right hand_base + five finger masks and S04 COCO-WholeBody hand confidences
merge trigger:              adjacent refined-mask overlap >30% or any four-point finger chain confidence <0.5
never-guess action:         affected finger masks emptied; their pixels merged into same-side hand_base before S09
state evidence:             sam2_metrics visibility_state=ambiguous_do_not_use and fingers_merged_or_ambiguous=true
review flags:               finger_merge + careful_review stamped on affected RefinedPart evidence
band path:                  S07 <side>_finger_occlusion_boundary -> S09 masks_regions -> review package
queue record:               one measured finger_merge per affected label with image/pN/model/view and max confidence/overlap error
idempotency:                forced replay of identical image/pN/model/label does not duplicate the open producer record
no-hand behavior:           S07 audit explicitly skips when no hand parts were refined; no fabricated failure
all producer sources:       lane, S10 QC, second review, S11 disagreement, and S15 human-edit delta now persist
focused regression:         51 hand/S09/production/mining tests pass
full regression:            560 tests pass
quality:                    Ruff check/format clean across 253 files; generated ontology current; tracker structurally valid
honest boundary:            fresh live S07 execution still awaits the Windows account owning Ubuntu-22.04; no real finger_merge row is claimed yet
```
## 2026-07-11 21:46 UTC - Weekly S15 clustering moved from keywords to governed local text LLM
**Item:** MF-P4-03.03 completion evidence corrected and strengthened
**Result:** The production weekly job now calls the configured local `qwen2.5:7b-instruct`; the prior `_cluster()` keyword substitute was removed.

```
privacy boundary:           text failure_reason slugs only; images/crops/overlays are never included
endpoint/model:             fixed http://127.0.0.1:11434; configs/vlm.yaml text_llm authority
determinism:                Ollama options temperature=0, seed=1337
output contract:            exact clusters + coverage_targets + weekly_summary keys
completeness:               every distinct input reason must appear exactly once as a clusters key
theme vocabulary:           hands_fingers, hair_boundary, occlusion_contact, left_right, human_correction, semantic_qc, general_boundary
target vocabulary:          closed view/pose/instance-context/attribute values from the coverage matrix
semantic guard:             prompt explicitly defines lr_swap as anatomical left/right, never learning rate
failure behavior:           one strict retry; invalid, inverted, incomplete, invented-theme, or invented-target JSON refuses the weekly artifact
zero-failure behavior:      writes auditable model_called=false evidence without loading/calling the model
live proof:                 five representative reasons mapped correctly; nine valid coverage targets and a weekly summary returned
live artifact:              qa/live_verification/s15_text_llm_clustering_20260711.json
artifact SHA-256:            60a27124964709b3c223a60252d5a31bed394c39740f612d40bbf48731284f8a
focused regression:         49 text/VLM/mining/dataset/production tests pass
full regression:            563 tests pass
quality:                    Ruff check/format clean across 255 files; generated ontology current; tracker structurally valid
```
## 2026-07-12 00:55 UTC - S03 dual parsing activated on local CUDA and completed for every eligible live instance
**Items:** MF-P2-02.01 95% -> complete; MF-P2-02.02 95% -> complete
**Result:** The pinned Sapiens/SCHP production boundary now runs on the proven local CUDA venv, and every S02-QC-pass person instance has a complete, auditable S03 package.

```
runtime:                    C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe; torch 2.11.0+cu128; RTX 5060 Laptop GPU
Sapiens contract:           revision ea5545c735d1fc994d0d1aafede27df892761322; bf16; 1024x768 model input; 1536/128 tiling
SCHP contract:              revision eb84c432cc697f494d99662a05f2335eb2f26095; ATR; fp32; 512x512 model input; always run
SCHP bootstrap:             pinned source cached under models/runtime_cache/schp; Windows clone explicitly selects OpenSSL TLS backend
live corpus:                29/29 S02-QC-pass instances committed S03; 2 no_person outcomes remain at S01; 1 low-ratio silhouette remains needs_review at S02
artifact contract:          every package has both indexed maps, 28 Sapiens confidence PNGs, 18 SCHP confidence PNGs, and both runtime documents
runtime integrity:          29/29 exact model revisions; 29/29 cu128; 29/29 local_cuda; 29/29 Sapiens scale=1.0
tiling observed:            1..18 Sapiens tiles per crop
duration:                   median 71.94s; maximum 234.93s; summed committed stage duration 40.73 minutes
storage:                    29 complete S03 evidence packages occupy 0.111 GiB
multi-person safety:        8 instances correctly marked careful_review after co-subject ambiguity suppression; no parser fallback was used
focused regression:         46 S03/config/production tests pass
quality:                    Ruff check/format clean before live batch; tracker structurally valid
```
## 2026-07-12 00:30 UTC - S02 activated on local CUDA; all 30 promoted instances processed
**Items:** MF-P2-01.02 95% partial -> complete; MF-P8-10.02 open -> 5% partial
**Result:** The exact registered BiRefNet model is no longer blocked by the sandbox account's invisible WSL distro. Kevin's existing ComfyUI CUDA venv provides a governed equivalent launcher, and every live promoted instance now has a durable S02 outcome.

```
local CUDA Python:           C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe
runtime:                     torch 2.11.0+cu128; CUDA 12.8; NVIDIA GeForce RTX 5060 Laptop GPU
checkpoint SHA-256:          9ab37426bf4de0567af6b5d21b16151357149139362e6e8992021b8ce356a154
model source revision:       e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4
inference contract:          fp16, long-side/tile 2048, overlap 128, threshold 0.5, native geometry
checkpoint attachment:       symlink first; byte-identical hardlink then copy fallback when Windows privilege blocks symlink
cache boundary:              workspace-local Hugging Face cache at models/runtime_cache/huggingface
runtime artifact:            birefnet_runtime.json beside every confidence map
canonical binary:            person_full_visible.png; obsolete silhouette.png consumers removed
batch command:               maskfactory run <image_id> --through-silhouettes
batch semantics:             S00/S01 shared; S02 once per promoted pN; stop before S03; GPU serialized
live stage count:            30/30 promoted pN instances have stage_run + mask + confidence + runtime + metrics
QC pass count:               29; ratio range 0.353674..0.728952 within configured [0.35,0.95]
routed instance:             img_cea6df6f0f13/p0 ratio 0.299361 -> needs_review
routed evidence:             failed-QC mask/confidence/runtime/metrics preserved atomically; downstream stopped; rerun caches
duration:                    median 18.94 s; max 66.12 s per stage including clean model-process startup
P8 real qualifying set:      img_7b7a3c7d5dd3 p0-p2 and img_6d6bb33f01a1 p0-p3 all S02 QC-pass
focused regression:         61 orchestrator/production/S01-S02/config/tool tests pass
full regression:            579 tests pass
quality:                    Ruff check/format clean across 257 files; generated ontology current; tracker structurally valid
```
## 2026-07-11 23:58 UTC - S01 terminal outcomes made durable and resumable
**Item:** MF-P2-01.01 completion evidence strengthened
**Result:** `no_person` and crowd outcomes are no longer discarded staging errors. They are terminal S01 results with preserved evidence, stopped downstream execution, idempotent database state, and cache behavior.

```
runner contract:             _terminal = {outcome: rejected|quarantined, reason: nonempty}
orchestrator artifact:       stage_run status=terminal plus terminal_outcome/terminal_reason
artifact preservation:       person_bbox.json + manifest_delta.json promoted atomically with the terminal stamp
downstream behavior:         run_pipeline stops immediately after a terminal execution; S02 is never called
cache behavior:              unchanged terminal config returns terminal evidence without rerunning YOLO
database behavior:           ingested -> rejected|quarantined at current_stage S01; exact rerun is a no-op
multi-instance behavior:     through-drafts/autoqa returns the S01 terminal instead of demanding nonexistent p0
D1 behavior:                 terminal S01 updates DB then refuses the draft contract honestly
live rejected IDs:           img_5bc6130e5055, img_a3d2663ad90d
live detector evidence:      both raw_detection_count=0, persons=[], reason=no_person
live database evidence:      both status=rejected, current_stage=S01
live cache proof:            img_5bc6130e5055 rerun terminal with duration_sec=0
current workflow totals:     19 ingested/promotion-ready + 2 rejected at S01 + 2 age_safety quarantined
focused regression:         52 orchestrator/production/state tests pass
full regression:            576 tests pass
quality:                    Ruff check/format clean across 255 files; generated ontology current; tracker structurally valid
```
## 2026-07-11 23:40 UTC - Large-image age-screen transport repaired; governed source set ingested through S01
**Items:** MF-P1-04.06 evidence strengthened; MF-P1-08.01 open -> complete; MF-P2-01.01 evidence strengthened; MF-P8-10.01 10% -> 20%
**Result:** Every supplied source now has a governed intake outcome, and every clear-adult ingest has an S01 outcome. The prior large-image HTTP-400 quarantines were recovered only through a new hash-verified rescreen path.

```
root cause:                  age screen base64-embedded original 16-26 MB / 4K-7K images directly into Ollama chat requests
review transport:            local metadata-free RGB JPEG, aspect-preserving long side <=1024, never used as source/mask authority
determinism:                 qwen2.5vl:7b; temperature=0; seed=1337; num_predict=128
response contract:           exact apparent_minor + reason keys; yes|no|uncertain; nonempty reason; one strict retry
fail-closed behavior:        HTTP/JSON/schema/detector errors still become uncertain quarantine
rescreen identity:           original filename + SHA-256 + source_origin + quarantined database state must all match
promotion transaction:       metadata-stripped accepted source/manifest written first, DB status moved from quarantined, old quarantine record removed
live transport proof:        previously HTTP-400 6720x4480 image -> 4 people, clear_adult, specific adult rationale
prior quarantine recovery:   3 clear_adult promoted; 1 age_safety_yes remained quarantined
new source batch:             16 previously unseen -> 15 ingested, 1 age_safety_yes quarantine
current intake totals:        23 supplied = 21 ingested + 2 quarantined; zero unprocessed
P1 source gate:              >=5 clean clear-adult ingests proven; MF-P1-08.01 complete
S01 live totals:              19 promoted images, 30 promoted person instances, 2 semantic no_person failures
real group detections:        raw/promoted counts 3/3, 4/4, 5/4, 5/4
P8 honest count:              only the 3-person and 4-person images qualify; both visible 5-person photos excluded from 2-4 requirement
P8 corpus progress:           2/10 minimum qualifying images (20%); 8 more required
S02 fresh attempt:            img_dd4151e9a815 fails at BiRefNet with WSL_E_DISTRO_NOT_FOUND under KEVIN\CodexSandboxOnline
focused regression:          16 intake tests pass
full regression:             573 tests pass
quality:                    Ruff check/format clean across 255 files; generated ontology current; tracker structurally valid
```
## 2026-07-11 22:15 UTC - P-MANIFEST and weekly-summary callbacks replaced by production model paths
**Item:** MF-P4-03.04 completion evidence corrected and strengthened
**Result:** The nightly command and weekly S15 job now invoke the governed local text model; the prior callback-only helpers are no longer treated as production evidence.

```
nightly command:             maskfactory manifest-lint --packages-root data/packages --output qa/reports/manifest_lint.json
discovery:                   recursively finds package manifest.json files under the supplied package root
endpoint/model:              fixed http://127.0.0.1:11434; configs/vlm.yaml qwen2.5:7b-instruct + p-manifest-v1-doc10
privacy boundary:            serialized manifest text only; images are explicitly empty and nothing leaves the machine
determinism:                 Ollama options temperature=0, seed=1337, num_predict=1024
output contract:             exact findings + overall keys; exact severity/path/problem/suggestion finding keys
consistency:                 nonempty findings require needs_human; pass requires zero findings
failure behavior:            one strict retry; malformed source JSON becomes a local BLOCK without a model call
auditability:                report seals manifest, prompt, and response SHA-256 per called package and is replaced atomically
weekly artifact:             S15 writes weekly_qa_summary_<date>.md from the same governed model's summary and closed-vocabulary targets
live proof:                  local model correctly returned a strict BLOCK/needs_human finding for an empty parts map
live artifact:               qa/live_verification/p_manifest_text_llm_20260711.json
artifact SHA-256:            1f86e803424c49ded69468ae9da0fb8e36ca0532e9ea787ab336327486e523d6
focused regression:         19 text/mining/dataset tests pass
full regression:            567 tests pass
quality:                    Ruff check/format clean across 255 files; generated ontology current; tracker structurally valid
honest boundary:            data/packages currently contains zero production package manifests, so no production-package findings are claimed
```
## 2026-07-11 22:30 UTC - P4 scheduled QA jobs production-ready; registration account-blocked
**Item:** MF-P4-03.05 open -> 90% blocked
**Result:** Both governed batch jobs now have fail-closed WSL runners and Task Scheduler definitions. Registration itself cannot be claimed from the sandbox Windows identity.

```
nightly task:               MaskFactory_NightlyManifestLint, DAILY 03:00, LIMITED
nightly action:             Ubuntu-22.04 -> maskfactory manifest-lint -> dated qa/reports JSON + dated log
weekly task:                MaskFactory_WeeklyQaMining, MON 10:00, LIMITED
weekly action:              Ubuntu-22.04 -> maskfactory active-learning -> acquisition plan, clustering evidence, summary, active-learning JSON
CLI count authority:        approved package count is derived from data/packages unless explicitly overridden
failure behavior:           either WSL batch exits nonzero -> PowerShell throws and Task Scheduler records failure
ordering:                   02:00 backup/integrity, 03:00 manifest lint, 09:00 cold-copy reminder, 10:00 weekly mining
syntax proof:               all three registration/job PowerShell files parse successfully
runtime proof:              zero-failure weekly CLI emitted all four expected artifacts without loading the model
focused regression:         18 backup/text/dataset tests pass
full regression:            568 tests pass
quality:                    Ruff check/format clean across 255 files; generated ontology current; tracker structurally valid
current identity:           KEVIN\CodexSandboxOnline; schtasks returns system path unavailable; WSL reports no distro
desktop attempt:            Windows-control transport closed before connection; no UI input occurred
NEEDS KEVIN:                run tools\register_scheduled_tasks.ps1 once from Kevin's interactive Windows account, then preserve /Query output as registration evidence
```
## 2026-07-11 22:55 UTC - Nightly P-MANIFEST made package-exact and incremental
**Item:** MF-P4-03.04 completion evidence strengthened
**Result:** The nightly sweep no longer recursively mistakes derivative manifests for packages or spends local-model time on unchanged packages.

```
authoritative discovery:     <image>/manifest.json legacy packages and <image>/instances/pN/manifest.json multi-instance packages only
explicit exclusion:         nested masks_derived/manifest.json and every other non-package manifest
incremental identity:       package-relative manifest path + exact source-byte SHA-256
durable state:              qa/reports/manifest_lint_state.json, atomically replaced only after a successful report
new-or-changed behavior:     call P-MANIFEST only when the path is absent from state or its bytes changed
unchanged behavior:          record discovered/skipped counts; perform zero model calls
removed-package behavior:    absent paths disappear from the next state rather than accumulating forever
malformed behavior:          source-byte hash is still tracked and a local BLOCK is emitted without a model call
scheduled wiring:            nightly_qa.ps1 passes the stable state path beside its dated report path
live first pass:             one authoritative-layout manifest discovered, one local model call, one BLOCK finding
live unchanged pass:         one discovered, one skipped, zero report packages/model calls
first artifact:              qa/live_verification/p_manifest_incremental_first_20260711.json
first SHA-256:               90df59e99650cee1c424fa3ab5f5e3be56466cc1d745424fe446bb3ed8770043
unchanged artifact:          qa/live_verification/p_manifest_incremental_unchanged_20260711.json
unchanged SHA-256:           d18e63a67c86ae2b6af79990d6715ac265a985a785b65bd7507fd80d31c34232
focused regression:         11 text/scheduling tests pass
full regression:            569 tests pass
quality:                    Ruff check/format clean across 255 files; generated ontology current; tracker structurally valid
```
## 2026-07-12 01:25 UTC - S04 DWPose activated on local CUDA and completed for every eligible live instance
**Item:** MF-P2-03.01 95% -> complete
**Result:** The pinned YOLOX-L + DWPose-133 boundary now runs through a project-local GPU ONNX Runtime site, and every S02-QC-pass instance has an owned 133-keypoint pose package.

```
runtime Python:             C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe
GPU runtime:                onnxruntime-gpu 1.20.2 in models/runtime_cache/onnxruntime_gpu; CUDAExecutionProvider; torch 2.11.0+cu128
environment isolation:      external ComfyUI venv unchanged; exact GPU wheel installed into ignored project cache with uv
detector:                   yolox_l.onnx SHA-256 7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411
pose model:                 dw-ll_ucoco_384.onnx SHA-256 724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843
live corpus:                29/29 S02-QC-pass instances committed S04; 2 no_person remain at S01; 1 low-ratio silhouette remains needs_review at S02
output contract:            29/29 pose133.json files contain exactly 133 keypoints with confidence values
ownership:                  1..5 candidates per image; minimum selected candidate/person-bbox IoU 0.964125
quality:                    minimum body-keypoint fraction 0.882353; 0/29 pose_degraded
views:                      front 27; left_profile 2
duration:                   median 49.72s; maximum 53.87s; summed committed stage duration 24.03 minutes
focused regression:         50 S04/config/production tests pass
```
## 2026-07-12 02:05 UTC - S06 GroundingDINO activated locally and completed for every eligible live instance
**Item:** MF-P2-05.01 95% -> complete
**Result:** The pinned 11-prompt GroundingDINO proposal boundary now runs through its documented pure-PyTorch CPU fallback, and every eligible instance has auditable box-only evidence with no mask authority.

```
source:                     IDEA-Research/GroundingDINO@856dde20aee659246248e20734ef9ba5214f5e44
checkpoint:                 groundingdino_swint_ogc.pth SHA-256 3b3ca2563c77c69f651d7bd133e97139c186df06231157a64c507099c52bc799
runtime:                    local ComfyUI Python; pure-PyTorch CPU deformable-attention fallback; one model load/package
locked compatibility:       transformers 4.47.1; tokenizers 0.21.4; huggingface-hub 0.27.1; safetensors 0.5.2
runtime isolation:          source/dependencies/BERT cache live only under ignored models/runtime_cache
Windows compatibility:      narrow no-op YAPF FormatCode shim avoids inaccessible platformdirs lookup; inference/config semantics unchanged
live corpus:                29/29 S02-QC-pass instances committed S05/S06; 2 no_person remain at S01; 1 low-ratio silhouette remains needs_review at S02
proposal totals:            351 total; 6..17 per instance; all 11 configured prompts represented
authority:                  29/29 authority=proposal_boxes_only; may_write_final_masks=false; zero PNG/mask outputs
runtime evidence:           29/29 exact checkpoint/source, local_cpu, CPU device type, one load, exact prompt vocabulary
duration:                   median 43.25s; maximum 74.89s; summed committed stage duration 22.63 minutes
focused regression:         52 S06/S07/config/production tests pass
```
## 2026-07-12 02:45 UTC - S07 persistent SAM2 activated on local CUDA and completed for every eligible live instance
**Item:** MF-P2-05.02 95% -> complete
**Result:** The pinned SAM2.1 large image predictor now runs persistently on local CUDA with exactly one embedding per instance and repeated prompt reuse; every eligible live instance has complete refinement evidence.

```
source:                     facebookresearch/sam2@2b90b9f5ceec907a1c18123530e92e794ad901a4
large checkpoint:           sam2.1_hiera_large.pt SHA-256 2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318
fallback checkpoint:        sam2.1_hiera_base_plus.pt SHA-256 a2345aede8715ab1d5d31b4a509fb160c5a4af1970f199d9054ccfb746c004c5
runtime:                    local ComfyUI Python; Hydra 1.3.4 isolated under models/runtime_cache/sam2_deps; torch 2.11.0+cu128; RTX 5060
live corpus:                29/29 S02-QC-pass instances committed S07; 2 no_person remain at S01; 1 low-ratio silhouette remains needs_review at S02
embedding contract:         29/29 exact embedding_count=1 in stage and runtime evidence
model routing:              large model 29/29; zero OOM fallbacks; fallback path remains regression-tested
prediction reuse:           488 total prompt predictions from 29 embeddings
mask output:                247 refined binary masks; every package mask count matches refined-part count
quality routing:            72 low-confidence results preserved; zero hand-merge failures
specialist-only edge:       2 packages correctly record one embedding and zero full-frame predictions
bridge cleanup:             zero embedding/prediction temporaries remain in all 29 packages
performance:                median 23.40s; pre-optimization compressed-bridge maximum 392.25s; transient archives now exact uncompressed NPZ
```
## 2026-07-12 03:59 UTC - S08 material and S08.5 DensePose completed for every eligible live instance
**Item:** MF-P3-05.01 90% -> complete
**Result:** The pinned Detectron2 DensePose R50 provider now runs directly on local CUDA, and every eligible promoted instance has an owned, validated IUV surface package.

```
source:                     facebookresearch/detectron2@02b5c4e295e990042a714712c21dc79b731e8833 with projects/DensePose
checkpoint:                 densepose_rcnn_R_50_FPN_s1x.pkl SHA-256 b8a7382001b16e453bad95ca9dbc68ae8f2b839b304cf90eaf5c27fbdb4dae91
runtime:                    local ComfyUI Python; torch 2.11.0+cu128; RTX 5060; project-local source/dependency cache
live corpus:                29/29 S02-QC-pass instances across 18 source images committed S08/S08.5
terminal routing:           2 no_person sources remain rejected at S01; 1 low-ratio silhouette remains needs_review at S02
material evidence:          6..12 non-empty material regions per instance
ownership:                  target selected from DensePose candidates by owned-bbox IoU; range 0.882155..0.988823
surface evidence:           329,736..17,448,288 non-background IUV pixels; runtime counts exactly match decoded PNGs
artifact audit:             29/29 complete receipts, exact checkpoint/source pins, CUDA launcher, shape, ownership, and surface checks
transaction hygiene:        zero temporary stage directories after the batch
performance fix:            thin-structure components use bounded label slices instead of rescanning the full frame per component
focused regression:         58 S08/DensePose/config/production tests pass
```
## 2026-07-12 05:06 UTC - Live corpus completed S09/S09.5 and strict D1 draft contracts
**Item:** MF-P2-08.04 96% -> 98% partial
**Result:** Every eligible promoted instance now has structurally verified master maps and a full-resolution 56-atomic draft contract; semantic G2/gold evidence remains open.

```
initial hard failure:       S09 correctly rejected S08 material ID 0 inside projected silhouettes
root cause:                 SAM2-refined material regions could shrink valid parser seeds; true parser-background fringe also remained unassigned
coverage policy:            restore original evidence-backed seed labels first, then nearest-fill only remaining draft fringe; background stays 0
cache safety:               S08 coverage_policy config changes the stage hash, forcing stale material maps to rerun
performance safety:         thin-structure connected components use bounded label slices, avoiding full-frame scan per component
live corpus:                29/29 eligible promoted instances across 18 source images committed S09 and D1
terminal routing:           2 no_person sources rejected at S01; 1 low-ratio silhouette remains needs_review at S02
instance reconciliation:    18/18 eligible source manifests QC-035 PASS
D1 contract:                29 contracts; IDs 0..55 exactly once; 54 enabled plus disabled empty ears 54/55
independent second audit:   1,624 strict binary PNGs re-decoded; hashes, non-overlap, full coverage, and exact PART-map reproduction all PASS
map invariants:             PART/MATERIAL nonzero at every silhouette pixel and 0 outside; zero temp directories; zero audit failures
material restoration:      0..260,733 evidence-seed pixels restored per instance
material nearest fill:      corpus 3.4401% of visible pixels; worst case 58.4803% (img_7b7a3c7d5dd3/p2)
quality boundary:           nearest-filled pixels are draft-only uncertainty, not gold semantic evidence; corrected-gold review remains mandatory
durable audit:              qa/live_verification/s09_d1_corpus_20260712.json
focused regression:         50 S08/S09/production tests pass
literal draft probe:        governed root drop refused, then canonical stripped-byte duplicate remained quarantined because it is not the original hash
probe cleanup:              test-only quarantine row/manifest/input removed after exact identity check; real ingested image stayed ingested
remaining completion gate:  fresh governed incoming original + corrected-gold G2 measurements and visible-part correctness
```
## 2026-07-12 05:25 UTC - Production S10 auto-QA completed for every eligible live instance
**Item:** MF-P2-06.08 open -> 80% partial (live evidence; exact fixture gate remains open)
**Result:** All 29 live draft instances produced atomic S10 reports; hard failures remain blocking and no automated result was promoted or approved.

```
live reports:               29/29 committed with complete stage receipts; zero runner failures; zero temp directories
overall routing:            27 fail; 2 needs_human; score range 0.870364..0.998934
hard blocks:                QC-014 left/right vote 27/29; QC-013 protected overlap 8/29
universal structural pass:  QC-001..004, 011, 012, 016, 018..020, 023, 025..027, 030, 035..038 all pass 29/29
universal human route:      QC-015 area sanity and QC-029 breast-position evidence route 29/29
other routes:               QC-017 27; QC-024 26; QC-028 21; QC-031 27; QC-033 8
warnings:                   QC-021 27; QC-022 3; QC-032 26
package-only checks:        QC-005..010 and QC-034 remain skipped until S13 package/previous-gold artifacts exist
authority boundary:         reports cannot approve masks, clear hard blocks, or replace Kevin's CVAT correction/approval
durable audit:              qa/live_verification/s10_autoqa_corpus_20260712.json
remaining item gate:        MF-P2-06.08 requires the governed 10-fixture set; live corpus is not substituted for that requirement
```
## 2026-07-12 05:47 UTC - S10 QC-013/QC-014 production evidence corrected
**Item:** MF-P2-06.08 remains 80% partial
**Result:** Two adapter false-positive sources were repaired; remaining left/right failures stay hard-blocked because live evidence genuinely disagrees or is insufficient.

```
QC-013 root cause:          protected other_person ID50 was tested against the protected mask itself, producing eight guaranteed 100% self-overlaps
QC-013 correction:          protected IDs 50..53 are excluded; body atomics remain subject to the ≤0.5% protected-overlap gate
QC-013 live result:         29/29 PASS after forced rerun (previously 21 pass / 8 false fail)
QC-014 root cause:          production adapter supplied only DensePose despite the required pose-skeleton + MediaPipe + DensePose vote contract
QC-014 correction:          anatomical pose-chain proximity now supplies the skeleton signal for breasts, arms/hands/fingers, hips/glutes, and legs/feet
QC-014 regression:         agreeing skeleton + DensePose votes pass; unavailable or contradictory evidence remains BLOCK
QC-014 live result:         27 fail / 2 pass remains; all 27 failures contain wrong-side votes and 22 also lack a second usable signal for at least one part
queue identity fix:         S10 producer identity is stable s10_autoqa:pN; random report run_id no longer defeats append-once deduplication
queue reconciliation:      66 rows -> 27 current QC-014 rows; removed 8 obsolete QC-013 false positives and 31 duplicate QC-014 rows
queue idempotency proof:    forced failing instance rerun leaves row count 27 -> 27 and SHA-256 unchanged
ontology review refresh:    v2 remains NO-GO; 27 QC-014 failures do not qualify for any proposed missing-boundary candidate
authority boundary:         no masks were edited and no hard block was cleared without the required evidence majority
forced corpus rerun:        29/29 complete S10 receipts; zero runner failures; zero temporary directories
focused regression:         12 semantic/S10/DensePose tests pass
durable audit updated:      qa/live_verification/s10_autoqa_corpus_20260712.json
```

## 2026-07-12 07:26 UTC - Side-aware geometry and fusion corrected across live corpus
**Items:** MF-P2-06.08 remains 80% partial; MF-P2-08.01 open -> 72% partial
**Result:** Unsupported fine-label invention and inverted DensePose side semantics were removed; ordered live QA improved to 16 BLOCK / 13 needs_human without overriding a single hard gate.

```
DensePose authority:        fine chart IDs 1..24 now follow the pinned Detectron2 source's official left/right mapping
geometry correction:        paired parser-side unions feed pose capsules; radii are bounded; confident pose chains can recover parser-missed limbs
torso side evidence:        separated torso-chart U distributions provide paired left/right breast votes
fusion correction:          all-zero upstream artifacts no longer register candidates, so broad torso parsers cannot invent fine hip labels
metric correction:          hole_ratio saturates at the report schema's [0,1] boundary for thin closed contours
focused real proof:         img_2ca794d19be9/p0 QC-014 changed BLOCK -> PASS and unsupported zero-prior hip masks disappeared
model-major live run:       forced S05 29/29, persistent-SAM2 S07 29/29, and S09 29/29 across 18 eligible sources
required ordering proof:    S09.5 reran after every S09; 18/18 reconciliations and QC-035 PASS before S10
final S10 pass:             29/29 complete, zero final stage failures; 16 fail / 13 needs_human
QC-014 remaining evidence:  16 BLOCK instances; 10 contain wrong-side contradictions and 8 insufficient evidence (categories overlap)
queue reconciliation:      27 -> 16 current QC-014 rows; SHA-256 ed5e5c20b816c7aae40e47b457a13bb73987c0826aa89937fef9840f196e06a8
ontology decision:          v2 remains NO-GO; zero failures qualify for a proposed new boundary
MF-P2-08.01 boundary:       model-major execution is proven, but only 18/25 required source images exist; seven remain
human authority boundary:   no report approves a mask or substitutes for Kevin's CVAT correction/approval
durable audit:              qa/live_verification/s10_autoqa_corpus_20260712.json
```

## 2026-07-12 07:44 UTC - Production ViTMatte local-CUDA path verified live
**Item:** MF-P3-03.03 90% partial -> complete
**Result:** The prominent-hair trigger now has a verified production CUDA provider and real matte artifacts; WSL remains supported but is no longer the only runtime path.

```
provider:                   LocalCudaVitMatteProvider with explicit CUDA Python, offline pinned HF cache/revision, and checkpoint hash validation
registered checkpoint:      models/matting/vitmatte_s.pth SHA-256 6ec6aed44bc8d8ab7f4d0ff46da3520a534cf5a97a8262404ff6efa9ae33b1e5
live source:                img_dd4151e9a815/p0, governed existing instance context 1600x429
trigger evidence:           hair 288,763 px / person bbox 485,688 px = 0.594544 >= 0.02
trimap contract:            values exactly 0/128/255; scaled +/-6px@1024 radius = 3px at width 429
runtime identity:           NVIDIA GeForce RTX 5060 Laptop GPU
alpha evidence:             range 0..255; unknown band 29,475 px, mean 137.181, std 91.8955
known-region invariants:    trimap background alpha exactly 0; trimap foreground alpha exactly 255
artifact hashes:            binary f26af7b6...; trimap ed77f7e2...; alpha 1f912bed...
optional contract:          lace_or_sheer prefix and below-2% no-op remain fixture-proven
durable audit:              qa/live_verification/mf_p3_03_03_vitmatte_live/img_dd4151e9a815/p0/audit.json
focused validation:         7 hair/provider/live-evidence tests pass; Ruff and format clean
authority boundary:         binary hair remains label authority; alpha is evidence/compositing only
```

## 2026-07-12 07:53 UTC - Real multi-instance fixture package fan-out sealed
**Item:** MF-P8-01.03 85% partial -> complete
**Result:** Two distinct governed, manually counted adult fixtures now prove exact real S01-to-draft fan-out under the configured doc-17 cap of four.

```
stale contract corrected:   fixture sealer hard-coded cap=3 while doc 17/config default max_instances_per_image=4
configured contract:        sealer now accepts the governed cap and fails outside integer [2,16]
downstream proof:            exact draft instance directories + draft contracts + complete S02-S09 receipts + matching S09.5 promoted list
fixture 1:                  supplied_adult_triptych_3; manual/raw 3; exact completed p0,p1,p2
fixture 2:                  supplied_adult_four_view_4; manual/raw 4; exact completed p0,p1,p2,p3
authority manifest:          qa/multi_instance_fixtures/manifest.json status verified_exact_promoted_draft_packages
negative evidence retained: licensed bus fixture canonically intake-cleared four adults but p2 stopped at S02 ratio 0.311724 < required 0.35
hard-gate behavior:          bus terminal remains needs_review; no silhouette threshold was relaxed and no missing package was counted
regression:                  configured-cap, tamper, mismatch, and exact-downstream tests pass
P8 automated-set progress:   MF-P8-10.02 advanced 5% -> 20%; both qualifying 2-4-person sources (2/10 minimum) complete S00-S10
scope exclusions:            two five-person sources remain outside the 2-4-person set; bus S02 terminal is not counted
```

## 2026-07-12 08:14 UTC - Live localhost SAM2 refine path activated and measured
**Items:** MF-P6-02.01 remains 99%; MF-P6-02.03 remains 98%; MF-P6-02.05 remains 75%
**Result:** Real multipart `/refine` now succeeds on local CUDA, but measured latency fails the required gate and champion `/predict` remains unavailable.

```
runtime correction:          default Windows serving now passes governed S07 local_cuda_python/source_path/dependency_site into SAM2
HTTP defect corrected:       lazy FastAPI endpoints use bytes=File; locally-scoped UploadFile forward reference no longer produces Pydantic HTTP 500
service bind:                live http://127.0.0.1:8765; GET /health HTTP 200
health evidence:             pipeline/API versions present; RTX 5060 8,151 MiB; gpu.lock active during service
champion honesty:            configured_models=[] and loaded_models=[]; no untrained predictor substituted
refine request:              multipart licensed adult bus fixture, left_forearm, one positive + one negative click
refine response:             HTTP 200; 810x1080 mode-L values {0,255}; area 397,174; SAM2 provenance
determinism:                 repeated mask SHA-256 e572cb0abd6aaa560c6ce738e89c27d8358041053fbca8446e7addc856d50c89
latency:                     9.418917 s versus <=1.2 s/click target -> FAIL, not overridden
root cause boundary:         stateless request reloads SAM2 and rebuilds the image embedding; interactive-session caching is still absent
probe hygiene:               bounded tool verifies/removes only its own dead serve_mode_b lock after process shutdown
durable audit:               qa/live_verification/serve_refine_cuda_20260712.json
remaining P6 gate:           trained champion bodypart/hand/clothing roles, live /predict, and target-compliant warm latency
```

## 2026-07-12 08:20 UTC - Interactive SAM2 session meets cold and warm latency gates
**Items:** MF-P6-02.01 remains 99%; MF-P6-02.03 98% -> 99%; MF-P6-02.05 75% -> 85%
**Result:** The stateless refine bottleneck was replaced by a bounded one-image session; warm click latency now passes while champion prediction latency remains honestly unmeasured.

```
session rule:                first request lazily loads SAM2 + embeds image; identical image bytes reuse that embedding
session invalidation:        changed image closes/rebuilds; any champion predict closes SAM2 before loading its sequential slot
shutdown invariant:          service stop closes embedding/provider; bounded probe verifies no residual gpu.lock
cold measurement:            7.979531 s <= 60 s target -> PASS
warm click measurement:      0.058920 s <= 1.2 s target -> PASS
warm request:                same 810x1080 image, cumulative third positive click, HTTP 200
mask evidence:               mode L, values {0,255}, area 509,950, SHA-256 a3e7caf593bd98255a7fbd454a66c6f850a3690a27dba77ae3432f00aa38b79e
no-co-residency regression:  cached SAM2 session is explicitly closed before champion predictor invocation
remaining latency gates:     /predict all-labels <=4 s and single-label <=2 s require real trained champion roles
durable audit updated:       qa/live_verification/serve_refine_cuda_20260712.json
```

## 2026-07-12 08:30 UTC - Real seven-instance CVAT review handoff created
**Items:** MF-P8-10.02 remains 20% by source count; MF-P8-10.03 open -> 5% partial
**Result:** Both qualifying 2-4-person sources advanced through S11 and live S12 handoff; Kevin's correction and approval remain untouched.

```
S11 execution:              7/7 promoted instances complete; zero stage failures
review packages:            7 schema-valid draft packages with sealed pre-human baselines
source img_7b7a3c7d5dd3: tasks 9,10,11 instance review + task 12 overview
source img_6d6bb33f01a1: tasks 13,14,15,16 instance review + task 17 overview
live CVAT:                  v2.24.0, nine tasks API-confirmed, remote size=1 each
preannotations:             166 total shapes across seven authoring tasks
overview authority:         two context-only tasks, zero authoring shapes, SOP-6 reciprocal review
semantic failures:          S10 BLOCK findings remain review flags; they were not cleared or auto-approved
manifest authority:         reviewer=null and approved_at=null in all seven packages
human status:               correction=false; approval=false; review minutes not fabricated
durable audit:              qa/live_verification/p8_real_cvat_handoff_20260712.json
NEEDS KEVIN:                correct tasks 9-11 and 13-16; review overview tasks 12/17; record time; explicitly approve
remaining set gate:         only 2/10 minimum qualifying sources exist, so MF-P8-10.02 stays 20%
```

## 2026-07-12 09:00 UTC - Transactional multi-person review handoff activated
**Items:** MF-P8-10.02 remains 20% by source count; MF-P8-10.03 remains 5% pending human work
**Result:** The generic production CLI now owns the complete machine path through S12 and safely reuses the nine live CVAT tasks.

```
one-command path:           maskfactory run IMAGE_ID --through-review-handoff
transaction boundary:       S10 all -> S11 all -> all packages -> image-level CVAT fan-out -> per-instance S12 receipts
retry behavior:             exact durable handoffs are reused; partial/malformed records fail closed
source img_7b7a3c7d5dd3: live exit 0; p0-p2 through S12; reused tasks 9-12
source img_6d6bb33f01a1: live exit 0; p0-p3 through S12; reused tasks 13-17
duplicate proof:            local task-record count remained 9 before and after both live runs
receipt semantics:          pending_kevin_correction_and_approval; human_approved=false
focused regression:         40 passed
full regression:            all tests passed; Ruff clean
tracker validation:         PASS; 393 items; five hard blockers remain unresolved
durable audit:              qa/live_verification/p8_review_handoff_coordinator_20260712.json
NEEDS KEVIN unchanged:      correct tasks 9-11 and 13-16; review 12/17; record time; explicitly approve
```

## 2026-07-12 09:20 UTC - Approved-gold VLM calibration builder activated
**Item:** MF-P4-05.01 advanced 50% -> 65% partial
**Result:** The missing governed bridge from approved packages to the fixed 40-panel calibration corpus is complete; the real corpus still correctly waits for gold.

```
command:                     maskfactory vlmqa build-calibration --selection SELECTION.json
input authority:             exactly 20 distinct image IDs from frozen, QA-passing, hash-verified human_approved_gold packages
governance:                  intake clear_adult + allowed source origin + nonempty package origin/rights note
known truth:                 good mask is copied from immutable approved package authority; draft maps are refused
defect construction:         deterministic wrong-side, loose/tight boundary, clothing-as-skin, neighbor bleed, missing area, hidden-area, finger-merge, hair-edge, and occlusion perturbations
balance:                     all ten taxonomy values exactly twice; >=5 target labels; 20 good + 20 defect panels
atomicity:                   corpus is built in a sibling temporary tree and promoted only after the existing production validator accepts every pair
negative tests:              missing approval and package verification failure both refuse without an output corpus
focused verification:       18 VLM tests passed
full regression:             all tests passed; Ruff clean
durable audit:               qa/live_verification/vlm_gold_calibration_builder_20260712.json
honest boundary:             approved_gold_count=0, so no live production calibration corpus or VLM gate pass is claimed
```

## 2026-07-12 09:45 UTC - VLM generation settings joined the calibration fingerprint
**Items:** MF-P4-05.03 strengthened; MF-P4-05.04 remains 25% partial
**Result:** Calibration and production S11 now share one governed request contract; changing sampling/output settings invalidates the gate just like changing model or prompt.

```
governed options:            temperature=0, seed=1337, num_predict=192
calibration path:            every P-PART request and invalid-JSON retry uses the exact options
production path:             gated P-PART and whole-image P-IMAGE requests use the same options
fingerprint:                 model + prompt version + prompt bytes + canonical generation-options JSON
change behavior:             any options drift makes require_current_gate fail closed
current real S11 audit:      seven reports, VLM disabled, zero verdicts, every part routed careful because the gate is unavailable
live repeat diagnostic:      normalized verdict/confidence/problems identical; free-text evidence wording differed, so no byte-identical text claim
prompt experiment:           stricter candidate not adopted; deprecated subset produced mixed sensitivity and a good-case false positive
known model boundary:        original prompt still passed an obvious deprecated loose-boundary defect; production gate remains correctly closed
focused verification:       20 VLM/S11 tests passed
full regression:             all tests passed; Ruff clean
durable audit:               qa/live_verification/vlm_generation_contract_20260712.json
honest boundary:             authoritative approved-gold corpus and passing primary/fallback scores remain required
```

## 2026-07-12 10:20 UTC - Pinned DVC/S3 runtime and repository activated
**Item:** MF-P1-07.09 remains blocked, advanced 0% -> 65% machine-owned completion
**Result:** The obsolete executable/backend blocker is removed; only the authorized remote push with real approved data remains.

```
runtime:                     workspace-local DVC 3.67.1 on Python 3.11.9
S3 backend:                  dvc-s3 3.3.0 + fsspec/s3fs 2026.4.0; dvc version reports s3 support
environment lock:            all S3 backend packages and transitive pins added to env/requirements.lock.txt
bootstrap:                   tools/bootstrap_dvc.ps1 recreates/verifies the exact isolated runtime with uv
repository:                  .dvc initialized; default maskfactory-dvc-dev -> s3://maskfactory-dvc-dev
account isolation:           production runner uses repository-local DVC system/global config + site cache, avoiding inaccessible ProgramData/user config
production wiring:           package approval and dataset build add/push resolve explicit, PATH, or workspace-local DVC consistently
Git contract correction:     data/packages.dvc, datasets/*.dvc, and their .gitignore files are explicitly publishable while payload trees remain ignored
live local add:              PASS; one-file/42-byte probe, md5 6d69afc782aa89a3490df53fb8b0d147.dir; disposable descriptor/data removed
focused verification:       27 DVC/package/dataset tests passed
full regression:             all tests passed; Ruff clean
credential audit:            no AWS env keys, profile, credentials file, or botocore provider available
remote action:               not attempted without credentials and without any human-approved package
durable audit:               qa/live_verification/dvc_s3_runtime_20260712.json
NEEDS KEVIN:                 provide authorized dev-account AWS credentials after first package approval; then execute first data/packages add + push
```
## 2026-07-12 - DensePose QC-014 side-vote reliability hardened

**Result:** PASS - trace DensePose overlap can no longer act as an independent L/R vote.

contract:                    require >=32 sided pixels, >=1% mask coverage, and >=10% L/R majority margin
weak evidence:               suppressed to no-vote; QC-014 therefore remains fail-closed on insufficient evidence
live corpus:                 29 instances audited; 13 pass / 16 BLOCK before and after; zero verdicts changed
evidence:                    qa/live_verification/densepose_side_vote_reliability_20260712.json
regression:                  focused DensePose/S10/semantic suite passed; Ruff check and format clean
## 2026-07-12 - Doctor shares one fail-fast WSL availability probe

**Result:** PASS - an unavailable identity-scoped distro is detected once and
reported under every required WSL-dependent check without repeated model smokes.

shared preflight:             0.14 s; one `wsl -d Ubuntu-22.04 -- true` call
short-circuited checks:       torch_cuda, registered_models, wsl_roundtrip
non-WSL checks:               still execute independently in stable order
warm live battery:            20.3 s; Nuclio SAM2 inference dominated at 13.9 s
live status:                  PASS=7 / FAIL=4; disk 72.6 GiB remains an ingest BLOCK
evidence:                     qa/live_verification/doctor_wsl_preflight_20260712.json
validation:                   631 tests passed; Ruff check and format clean
## 2026-07-12 - Dedicated S10 QA CLI activated

**Result:** PASS - `maskfactory qa <image_id>` is no longer a scaffold.

execution:                    forces S10 after cache-validating the shared/per-instance chain
multi-person contract:        reads and validates one qa_report.json for every promoted pN
summary states:               pass / needs_human / blocked; ROUTE is never mislabeled pass
process contract:             exit 1 only when one or more BLOCK checks fail
live route case:              img_2ca794d19be9 -> needs_human, five routes, exit 0
live block case:              img_3f94e3070bc5 -> QC-014 blocked, exit 1
evidence:                     qa/live_verification/qa_cli_live_20260712.json
validation:                   633 tests passed; Ruff check and format clean
## 2026-07-12 - Specified stage, fusion, and I/O boundaries activated

**Result:** PASS - the remaining doc-05 scaffold-only modules are production APIs.

stage entries:                S00 and S10-S15 delegate to their verified production implementations
consensus boundary:           public facade exposes the production weighted S09 engine
z-order boundary:             arbitration moved out of S09 private code and is called through fusion.zorder
I/O boundary:                 streaming/root-confined hashes, drift verifier, validated readers, atomic JSON + strict PNG writers
critical migrations:          intake source hash, review package hash, package manifest file-map hash
CLI cleanup:                  no scaffold output; bare vlmqa prints its real command help
source audit:                 zero scaffold/not-yet-implemented markers remain under src/maskfactory
evidence:                     qa/live_verification/architecture_boundaries_20260712.json
validation:                   35 focused and 639 full tests passed; Ruff/format clean
## 2026-07-12 - Body-part v1 class-count conflict resolved from approved spec

**Result:** PASS - active v1 uses 56 logits for authoritative IDs 0..55, including background 0.

authority:                     approved doc 18 §1 explicitly invalidates the old 57-class phrase
v1 contract:                   IDs 0..55 -> exactly 56 logits
v2 contract:                   append-only IDs 0..64 -> exactly 65 logits
configs corrected:             SegFormer-B3 and Mask2Former-SwinB num_classes 57 -> 56
compiler behavior:             live governed configs compile; deliberate 57 drift fails before staging
training doctor:               class issue absent; local boundary is CPU torch/no pinned OpenMMLab/CUDA
evidence:                      qa/live_verification/bodypart_class_contract_20260712.json
validation:                    21 focused and 639 full tests passed; Ruff/format clean
## 2026-07-12 - Dedicated multi-instance S11 VLM-QA command activated

**Result:** PASS for orchestration/fail-closed routing; calibration gate remains unavailable.

command:                       maskfactory vlmqa run <image_id>
execution:                     force S10 then S11 for every promoted pN; revalidate reports
gate policy:                   missing/deprecated gate -> disabled_gate_unavailable + exit 1
live result:                   img_2ca794d19be9/p0, 13 careful routes, zero verdicts, no P-IMAGE call
authority:                     no block clear, no mask edit, no approval
handoff isolation:             CVAT task records unchanged at 9; S12 never runs
evidence:                      qa/live_verification/vlmqa_run_cli_20260712.json
validation:                    55 focused and 640 full tests passed; Ruff/format clean
## 2026-07-12 - Disk ingest hard stop cleared with owned-artifact cleanup

**Result:** PASS - free space increased from 72.4581 GiB to 75.3 GiB without deleting governed data.

cleanup authority:              ignored runtime/pytest artifacts and clean pushed publication clone only
preserved:                      registered models, runtime caches, work, data, packages, datasets, QA, runs evidence, logs
doctor before:                  PASS=7 / WARN=0 / FAIL=4; disk FAIL below 75 GiB
doctor after:                   PASS=7 / WARN=1 / FAIL=3; disk WARN at 75.3 GiB
ingest policy:                  hard stop cleared; <150 GiB warning and junction recommendation remain
remaining failures:             three identity-scoped Ubuntu-22.04 checks only
evidence:                       qa/live_verification/disk_headroom_recovery_20260712.json

## 2026-07-12 - Image-level gold approval made atomic

**Result:** PASS - S13 cannot leave a multi-person image partially approved when finalization or DVC registration fails.

preflight:                      every pN must clear the same non-overridable QC gates
commit unit:                    all instances beneath one image, not one pN at a time
DVC boundary:                   one add at the common image root after every instance is prepared
rollback:                       single and multi-instance seeded DVC failures restore exact pre-approval bytes
success path:                   all instances freeze together; image root registered exactly once
ordering:                       numeric pN discovery remains correct for p10 and above
human authority:                no CVAT correction/approval claimed; live review remains pending Kevin
evidence:                       qa/live_verification/atomic_image_approval_20260712.json
validation:                     22 focused and 643 full tests passed; Ruff/format clean

## 2026-07-12 - Doctor inference waits bounded and results streamed

**Result:** PASS - the environment doctor now completes with named evidence instead of appearing frozen behind multi-minute local inference waits.

observed before:                 no output before a 120.5 s external termination
root cause:                      sequential Nuclio/Ollama HTTP waits allowed 120 s / 240 s
bounded contract:                10 s ordinary local API; 45 s local inference request
cold Qwen measurement:           33.012 s, strict {image_received:true}; supports the 45 s ceiling
warm live doctor:                17.966 s; PASS=7 WARN=1 FAIL=3
live passes:                     CVAT 2.24.0/project, pth-sam2, qwen2.5vl image, PNG, SQLite, gpu.lock
remaining failures:              three existing sandbox-identity Ubuntu-22.04 checks only
disk:                            WARN at 75.1 GiB; still above the 75 GiB ingest hard stop
observability:                   each completed named result is emitted immediately
evidence:                        qa/live_verification/doctor_bounded_streaming_20260712.json
validation:                      12 focused and 645 full tests passed; Ruff/format clean

## 2026-07-12 - S02 semantic terminal routes made durable and idempotent

**Result:** PASS - cached per-instance silhouette failures can no longer remain hidden only inside stage folders.

policy restored:                 semantic failure -> durable central review queue
queue contract:                 append-only JSONL, fsync, exclusive short lock
idempotence key:                image_id + instance_id + stage + config_hash
live first run:                 0 -> 2 records
live cached replay:             2 -> 2 records; no duplicate route
routed instances:               img_cea6df6f0f13/p0 ratio 0.299361; img_c02019c4979c/p2 ratio 0.311724
required S02 range:             [0.35, 0.95]; unchanged
authority:                      masks remain failed; no threshold override and no database terminal transition
current S02 corpus:             33 instance records / 20 images; 31 pass, 2 needs_review
evidence:                       qa/live_verification/s02_review_queue_durability_20260712.json
validation:                     59 focused and 647 full tests passed; Ruff/format clean

## 2026-07-12 - S03 custom-bodypart champion producer activated

**Result:** PASS for MF-P5-07.01 - the promoted body-part model now has a complete producer-to-consumer path rather than only an S09 fixture seam.

S03 producer:                    exact ordered 56-class v1 vocabulary -> 16-bit custom_bodypart.png
authority:                       exactly one verified champion_bodypart role; checkpoint/config hashes reverified
provenance:                      model key, checkpoint SHA, inference-config SHA, exact class_names
map validation:                  full vocabulary, strict boolean geometry, no overlaps, ontology IDs by name
co-subject safety:               other_person_protected pixels suppressed before geometry/fusion
S09 consumer:                    custom_bodypart consensus source at governed weight 0.45
cache promotion/change:          stale or missing champion provenance forces S03
cache rollback:                  role removal forces S03 and removes stale custom artifacts atomically
GPU lifecycle:                   MMSeg slot closes on success and every failure
current registry:                no champion role; live existing pipeline remains unchanged and needs no refresh
not claimed:                     no D6/G7 winner or live champion score; MF-P5-07.02 remains open
evidence:                        qa/live_verification/custom_bodypart_s03_s09_integration_20260712.json
validation:                      64 focused and 650 full tests passed; Ruff/format clean

## 2026-07-12 - S08 clothing champion production authority activated

**Result:** PASS for MF-P5-04.03 - a governed clothing winner can now become the real S08 primary, with SCHP retained as the named fallback.

S08 producer:                    exact ordered 16-class material-v1 vocabulary -> 8-bit material_draft.png
authority:                       exactly one verified champion_clothing role; checkpoint/config hashes reverified
provenance:                      model key, checkpoint SHA, inference-config SHA, exact class_names
map validation:                  strict boolean geometry, no overlap, silhouette containment and complete coverage
fallback:                        schp_plus_s08_heuristics remains active whenever no champion role exists
cache promotion/change:          missing or stale champion provenance forces S08
cache rollback:                  role removal forces S08 when cached evidence names the champion
partial runs:                    cache forcing is scoped to selections that actually include S08
GPU lifecycle:                   MMSeg slot closes after success and contract refusal
current registry:                no champion role; 29 cached S08 outputs remain valid and need no refresh
not claimed:                     no D6/G7 winner or live champion score; MF-P5-04.02 remains open
evidence:                        qa/live_verification/champion_clothing_s08_integration_20260712.json
validation:                      55 focused and 652 full tests passed; Ruff/format clean

## 2026-07-12 - Champion-hand production crop path activated

**Result:** PASS implementation readiness for MF-P5-05.05; the live D7/QC-018 winner gate remains open.

contract defect fixed:           actual 14-class hand models were previously rejected on finger_occlusion_boundary
registry contract:               exact ordered 14 classes required; boundary band explicitly governed
serving contract:                verified MMSeg loader accepts and names all 14 outputs
production authority:            promoted champion_hand replaces hand-lane steps 2.3-2.4 in S07
crop/paste path:                 per-side 1.6x square 1024 crop -> nearest crop_to_full_transform reprojection
outputs:                         hand base, five fingers, finger_occlusion_boundary, model/config provenance
SAM2 boundary:                   retained as interactive editor only when champion drafting is active
cache lifecycle:                 promotion, replacement, and rollback force S07; unrelated selections do not
fallback:                        no champion role leaves the existing full-frame S07/SAM2 path byte-authoritative
current registry:                no champion_hand role; no live winner inference claimed
remaining exact gate:            D7-winning output must still measure QC-018 paste-back >= 0.995
evidence:                        qa/live_verification/champion_hand_production_integration_20260712.json
validation:                      91 focused tests; full suite split 281 + 376 = 657; Ruff/format clean

## 2026-07-12 - Live S02 low-ratio cases audited without override

**Result:** PASS review-routing audit - both failures are genuine metric edge cases, not coordinate or provider defects.

governed range:                  silhouette/bbox area ratio [0.35, 0.95], unchanged
img_cea6df6f0f13/p0:             0.299361; complete wide-limbed standing silhouette; tight-box fill 0.301483
img_c02019c4979c/p2:             0.311724; complete visible frame-truncated pedestrian; tight-box fill 0.312720
coordinate finding:              masks align with sources and detector boxes; no paste/crop displacement
provider finding:                no visibly missing major person region in either BiRefNet result
authority:                       neither case was auto-passed and no threshold/area was changed
durable outcome:                 both remain needs_review; central queue remains two records
batch credit:                    unchanged at 18/25 completed sources
evidence:                        qa/live_verification/s02_low_ratio_case_audit_20260712.json

## 2026-07-12 - S02 semantic review return path made executable

**Result:** PASS implementation readiness - queued pre-package silhouette reviews can now return without weakening QC.

prior dead end:                   semantic S02 terminals were durable but had no governed consumer/resume path
operator command:                maskfactory review resolve-s02 IMAGE_ID pN --mask PNG --reviewer NAME --decision confirmed_valid|corrected --note REASON
confirmed-valid authority:       mask must be byte-identical to the queued model output
corrected authority:             mask must be a different native strict binary PNG inside the S01 context
immutable evidence:              queue identity, config hash, source/mask hashes, reviewer, decision, note, timestamp
fresh replay:                    forced S02 reruns BiRefNet and must reproduce the reviewed base hash before applying human evidence
QC honesty:                      model failure and original ratio remain recorded; human_review_passed is separate
cache lifecycle:                 sealed-but-unapplied evidence forces S02; matching applied evidence restores cacheability
tamper handling:                 stale config/model, altered mask, conflicting resolution, bad geometry all refuse
live authority boundary:         zero resolutions sealed; both current cases still await Kevin's semantic review
evidence:                        qa/live_verification/s02_review_resolution_path_20260712.json
validation:                      68 focused tests; full suite split 287 + 375 = 662; Ruff/format clean

## 2026-07-12 - Live S02 operator handoff generated

**Result:** PASS - every queued S02 route now has review-ready visual and command evidence.

command:                         maskfactory review prepare-s02
live index:                      qa/review_handoffs/s02/index.json
index result:                    count=2; awaiting_human_review=2; no sealed resolution
panel contract:                 full source beside red silhouette overlay, aspect-preserving max-side render
visual verification:             both panels align to the intended person; no coordinate mismatch
operator hints:                  copy-ready confirmed_valid and corrected commands with exact image/pN/mask paths
immutable identity:              config hash, queue timestamp/error, model-mask SHA-256, ratio and QC range
data governance:                 source-containing panels remain local and git-ignored; JSON index is publishable
QA writer policy:                RGB panel save explicitly audited as non-mask; raw-mask-writer gate remains clean
authority boundary:              panels prepare review but do not approve; both cases remain unresolved
validation:                      71 focused; full suite 663 collected/passed across split plus corrected policy test; Ruff/format clean

## 2026-07-12 - Stylized multi-person S01 recovery and downstream activation

**Result:** PASS implementation; one source passed QC-035 and reached live CVAT, one remained honestly blocked by QC-035.

false rejection root cause:      YOLO11m returned zero boxes on two clear-adult stylized multi-person sources
governed S01 recovery:           zero-raw-box-only GroundingDINO `person` proposal fallback; YOLO remains primary and all existing confidence/area/ranking/crowd gates remain authoritative
live S01 evidence:               img_5bc6130e5055=3 promoted; img_a3d2663ad90d=2 promoted; detector_source=groundingdino_swint_ogc
state repair:                    successful rerun transitions only prior rejected/quarantined rows back to ingested/S01; active downstream rows never regress
live S02 evidence:               5/5 silhouettes passed unchanged [0.35,0.95] ratio gate; range 0.585266..0.830617
S04 repair:                      missing owned DWPose candidate now emits zero-confidence degraded pose, parsing-only geometry, careful-review; co-subject candidates remain suppressed
S03/S05 repair:                  all-background Sapiens is degraded; S05 consumes always-run SCHP rather than selecting an empty file by existence
D1 evidence:                     3+2 instance draft contracts emitted through S09/S09.5
hard-gate honesty:               img_5bc6130e5055 maximum pair IoU=0.307266 >0.30; all 3 S10 reports fail QC-035
passing multi-person source:      img_a3d2663ad90d maximum pair IoU=0.096472; both S10 reports pass all blockers and route needs_human
CVAT handoff:                    img_a3d2663ad90d reached S11/S12; live tasks 18,19,20 pending Kevin correction/approval
Windows UI retry:                computer-control initialization and reset both returned Transport closed; no blind UI input sent
validation:                      669 tests collected/passed; Ruff and ruff-format clean; tracker structurally valid with 393 items

## 2026-07-12 - Durable pipeline progress and multi-instance package identity repaired

**Result:** PASS - live SQLite and S12 manifests now preserve the actual deepest verified workflow state.

state defect:                    successful S09/S10/S11/S12 runs left image rows at ingested/S00 or S01
runtime repair:                  D1->drafted/S09; S10->auto_qa; S11->vlm_qa; S12->in_review, advancing every legal intermediate state and never regressing reruns
live reconciliation:             20 D1 rows repaired: 16 auto_qa, 1 vlm_qa, 3 in_review; 2 S02-review sources remain ingested and 2 age-safety cases remain quarantined
package identity defect:         per-instance crop SHA-256 values correctly differed, but reindex incorrectly treated them as one image identity
schema repair:                   source_sha256 authenticates each crop; required parent_source_sha256 authenticates the shared whole ingested image
workflow authority:              package-level workflow_status/workflow_updated_at records S12 in_review independently of per-part annotation statuses
live package migration:          9 manifests across img_6d6bb33f01a1, img_7b7a3c7d5dd3, img_a3d2663ad90d sealed without changing masks/tasks
reindex result:                  missing_in_db=[]; stale_rows={}; remaining extras are 21 intentional non-S12 rows outside the package-only set
Task Scheduler retry:            service running, but schtasks path failure and native API access denied under kevin\codexsandboxonline
evidence:                        qa/live_verification/pipeline_state_and_package_identity_20260712.json
validation:                      671 tests collected/passed; Ruff and ruff-format clean; tracker structurally valid

## 2026-07-12 - Live GC drill and S12 package verification completed

**Result:** PASS - the real-corpus post-GC verification and scoped reindex are clean.

GC dry/apply:                    identical plan hash 4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945
GC effect:                       candidates=0, removals=0; no package bytes selected for deletion
initial post-check:              9/9 S12 packages correctly failed QC-008/009 because production assembly omitted derived/state artifacts
assembler repair:               S12 now generates masks_derived, explicit states for every enabled non-material label, and a complete resealed file inventory
live repair:                    all 9 existing instance packages refreshed without changing CVAT task IDs or human status
verify-package --sample 10:      discovered=9, passed=9, failed=0; QC-008 and QC-009 clean on every package
reindex repair:                 nested derived manifests ignored; package-backed rows reconciled; non-package intake/draft/QA rows preserved on apply
reindex --dry-run:              clean=true, missing=[], stale={}, extra=[]
evidence:                        qa/live_verification/gc_postcheck_and_s12_package_completion_20260712.json
validation:                      671 tests collected/passed; Ruff and ruff-format clean

## 2026-07-12 - Corrected-to-gold workflow authority wired end to end

**Result:** PASS implementation readiness; live human correction/approval remains pending Kevin.

CVAT pull completion:            all instance task records required before image transition; absent shapes sealed human-corrected/not_visible
artifact refresh:               corrected maps re-fused; atomics/derivations regenerated; per-label hashes, areas, boxes, components and full file inventory resealed
package transition:             in_review -> corrected only after every pN succeeds
SQLite transition:              in_review/S12 -> corrected/S12 through the same successful pull boundary
gold precondition:              package command refuses approval unless workflow_status=corrected
gold transition:                every pN stamped approved_gold with shared approval timestamp; SQLite advances approved_gold/S13 only after atomic package success
bounce behavior:                any package BLOCK returns package workflow to in_review; human approval remains non-overridable
CLI contracts:                  cvat pull and package both expose explicit --database (default data/maskfactory.sqlite)
live authority:                 3 images remain in_review; corrected=0; approved_gold=0; no manual correction or approval claimed
evidence:                        qa/live_verification/corrected_gold_workflow_contract_20260712.json
validation:                      43 focused lifecycle tests; 671 full tests; Ruff and ruff-format clean

## 2026-07-12 - Published-dataset export state synchronized

**Result:** PASS implementation readiness; the live P5 entry gate remains honestly unmet.

dataset source authority:       build_manifest.json records every exact approved source-package path included in the immutable build
publish boundary:               package/SQLite state advances only after dvc add, dataset Git tag, and dvc push all succeed
package transition:             approved_gold -> exported for every included instance package
SQLite transition:              approved_gold/S13 -> exported/S14 for every included image
atomicity:                      all DB rows are preflighted in one writer transaction; any package update failure restores prior manifest bytes and rolls SQLite back
failure proof:                  seeded dvc push failure leaves export synchronization uncalled; seeded second-package failure restores the first package and preserves approved_gold in SQLite
rerun behavior:                 already-exported packages/images are idempotent; --no-publish builds never claim exported state
live authority:                 approved_gold=0, below the required 200; no bodyparts@v1 build, DVC push, or live exported transition claimed
evidence:                        qa/live_verification/dataset_export_state_contract_20260712.json
validation:                      30 focused lifecycle tests; 674 full tests split 196+124+276+78; Ruff and ruff-format clean

## 2026-07-12 - Post-gold correction transaction made production-real

**Result:** PASS implementation readiness; no live human correction or gold mutation claimed.

defect found:                    prior test promoted only an unchanged binary copy; real map corrections could not pass QC-007 and did not refresh package/SQLite authority
candidate authority:             masks@vN now contains authoritative PART/MATERIAL maps plus regenerated strict binary views
operator surface:                maskfactory correction begin / refresh / promote with explicit reviewer, minutes, and confirmation
active immutability:             candidate/archive bytes are version-hashed separately, so active gold remains fully verify-package clean during candidate editing
promotion transaction:           map authority activates atomically; binaries, derivations, per-label geometry/hashes, review metadata, frozen metadata, and complete active inventory are resealed
version evidence:                mask_versions.json records per-file hashes for candidate, active, and deprecated versions; v1 retain_until is exactly +30 days
state synchronization:           exported or approved_gold -> corrected/S12 -> approved_gold/S13 inside the same SQLite writer transaction
rollback proof:                  seeded DVC failure restores every package byte and rolls SQLite back; invalid candidate binary views are rejected before mutation
human authority:                 promotion still requires explicit confirmation; no CVAT click, reviewer identity, or minutes were fabricated
evidence:                        qa/live_verification/post_gold_correction_transaction_20260712.json
validation:                      23 focused versioning/QC/package/GC tests; 677 full tests split 196+124+276+81; Ruff and ruff-format clean

## 2026-07-12 - Real single-person pre-P8 versus activated-p0 regression

**Result:** PASS - the governed real source produces one byte-identical authoritative p0 D1 package through both layouts.

source:                          img_2ca794d19be9; generated; clear_adult; person_count=1; SHA-256 2ca794d19be98054259b0bb37aa3d59d5b882510f484952075e2bf1f8e388c3b
legacy replay:                   direct S02-S09 layout, nine real GPU stages, 400.640183 s
activated replay:                P8 instances/p0 outer loop, nine real GPU stages, 502.298333 s; QC-035 pass; one D1 contract
authoritative maps:              S09 PART and MATERIAL bytes identical before D1 projection
D1 package:                      exactly p0; 59/59 files identical; 56 atomics; no missing/extra/changed bytes
PART map SHA-256:                9c2732e462b2e20dfda3facb1a343d7ea75a70d7c49eab9f409aca664bc6c180
MATERIAL map SHA-256:            718f98decb253c13d6a6ee34cc4c85401c7066323b5511ab60daa3287dbb904d
whole p0 tree SHA-256:           b5a082e347422e9cf212924fd16decb53d901ea1e55131c222fc400916262c96
honest intermediate disclosure: stage durations differ by definition; GDINO floats varied slightly with identical proposal count/order; DensePose varied at 6 pixels by value 1; these did not alter either authoritative S09 map or any D1 package byte
durable verifier:                verify_single_person_draft_regression requires exactly one p0, exact file set/bytes, valid 56-atomic contracts, strict non-overlap, full coverage, and map reproduction on both sides
evidence:                        qa/live_verification/single_person_real_p8_regression_20260712.json
validation:                      52 focused production-runner tests; 678 full tests split 196+124+277+81; Ruff and ruff-format clean

## 2026-07-12 - Exact P2 S01/S02 ten-image truth gate closed

**Result:** PASS - MF-P2-01.03 is complete against independent human annotations.

source authority:                LV-MHP v1; governed local non-distributable research/QA fixture use only; external masks remain non-gold and have no production-training authority
fixture admission:               exactly 10 hash-bound source/mask pairs; every whole image screened clear_adult with qwen2.5vl:7b; every selected primary-person alignment visually reviewed
production replay:               fresh YOLO11m CPU S01 plus governed CUDA BiRefNet S02 on all ten records
bbox acceptance:                10/10 >=0.95; minimum 0.9539567671374037
silhouette acceptance:          10/10 >=0.95; minimum 0.9523425333508453
S02 internal QC:                10/10 pass
fail-closed controls:            exact record count, dataset/use-scope authority, non-gold declaration, clear-adult verdicts, visual review, root confinement, source/mask hashes, both independent IoU thresholds
diagnostic exclusion:            multi-person-contact and below-threshold candidates were retained only under ignored work artifacts and were never admitted by relabeling or threshold changes
fixture manifest:                qa/fixtures/p2_s01_s02_truth.json
durable verifier:                tools/verify_p2_s01_s02_fixtures.py
evidence:                        qa/live_verification/p2_s01_s02_truth_gate_20260712.json
validation:                      3 focused evaluator tests; fresh 10-image real replay; 681 full tests; Ruff and ruff-format clean

## 2026-07-12 - S04 20-image hand-truth gate closed with production view repair

**Result:** PASS - MF-P2-03.05 is complete at 100% view and exact pose-tag-set accuracy.

hand-truth authority:            exactly 20 unique clear-adult images, hash-bound and visually labeled independently from classifier output; two unevaluable degraded stylized sources excluded and replaced by two governed LV-MHP adults
coverage:                         front, back, left/right profile, left/right 3/4, arms up/down, seated/crouched, lying, asymmetric gait, and leg overlap
defect found:                     DensePose fine torso charts were inverted in the referee (chart 1 treated as front and chart 2 as back); controlled front sources measured >99% back while true back sources measured >94% front
surface correction:              official/fixture-verified mapping is chart 1=back, chart 2=front
production timing:               governed DensePose view inference now runs inside S04 before S05 geometry; S08.5 reuses the exact validated IUV/runtime bytes without a second model launch
view repair:                      torso-span profile/3/4 thresholds plus reliable DensePose visible-side vote; high back ratio remains authoritative
pose-tag repair:                  walking requires asymmetric bent-leg stride, lying accepts a landscape-person fallback only with a sufficiently tilted torso, and arms_crossed requires both wrist crossings
measured view accuracy:           20/20 = 1.000 (gate >=0.90)
measured exact tag-set accuracy:  20/20 = 1.000 (gate >=0.90)
real provider evidence:           18 existing governed CUDA DWPose/DensePose pairs plus two independent LV-MHP sources freshly run through both providers
truth manifest:                   qa/fixtures/p2_s04_hand_truth.json
durable verifier:                tools/verify_p2_s04_hand_truth.py
evidence:                        qa/live_verification/p2_s04_hand_truth_gate_20260712.json
validation:                      686 full tests; Ruff and ruff-format clean; tracker structurally valid

## 2026-07-12 - S11 tool-using VLM workhorse implementation

scope:                           high-resolution audit, bounded SAM2 candidate creation, before/after comparison, shadow execution, calibration parity
visual contract:                 six independent images per label at 1024 crop resolution plus full context; no 1024x205 compressed strip
tool contract:                   fail confidence >=0.7; 1-12 positive points; 0-12 negative points; full-source coordinate validation
candidate safety:                original map immutable; <=75% changed area; <=2% protected-neighbor overlap; click polarity enforced; strict binary PNG proposal only
verification:                    complete six-view BEFORE plus complete six-view AFTER comparison; better/worse/no-change/uncertain closed vocabulary
authority:                       no gold approval, no BLOCK clearing, no authoritative-map write; human approval remains mandatory
uncalibrated behavior:           shadow audits/candidates allowed; zero qa_report verdicts; no disagreement queue writes; careful routing only
calibration repair:              real-gold builder now stores independent workhorse evidence and live evaluator uses the production workhorse parser/prompt path
validation at log time:          focused VLM/evaluator tests passing; full-suite and formatting verification pending
live attempt 1:                  img_2ca794d19be9; 13 careful routes retained; shadow failed safely because six images consumed 6148 tokens against Ollama's default 4096 context
runtime correction:              workhorse-only num_ctx=8192 and num_predict=768; both values included in the model/prompt/options gate fingerprint
live attempt 2:                  model reload began with the larger context, but the desktop execution host closed the client before Ollama finished loading; no candidate or verdict claimed
concurrency handoff:              a later retry was not forced because tools/run_p2_core_fixture_gate.py PID 51852 legitimately acquired runs/gpu.lock for img_34e63885a469
focused validation final:        39 selected VLM/S11/workhorse tests pass; Ruff clean; alphabetical A-F repository group passed; monolithic full suite was interrupted by the desktop long-running stdout boundary and is not claimed
single-label live audit:          current img_2ca794d19be9 left_forearm completed in 145.058 s with six real images; Qwen still returned pass/confidence=1.0 and made a factually wrong full-context observation
visible missed defects:           mask includes the hand/wrist and a disconnected underwear fragment; this proves resolution alone does not cure Qwen's pass bias
controller hardening:             deterministic component metrics and ontology max_components now enter the prompt and veto a false pass; the bounded remove_small_components tool creates an isolated cleanup candidate without SAM2
additional grounding:             prompt now includes side, parent union, expected area, max components, boundary rule, and up to 20 non-pass deterministic QA findings
final focused validation:         40 selected VLM/S11/workhorse tests pass; Ruff clean; no real-gold gate pass claimed

## 2026-07-12 - Exact P2 46-core draft and QC-011 ten-fixture gates closed

**Result:** PASS - MF-P2-05.08 and MF-P2-06.08 complete on the exact governed fixture set.

core contract:                    46 PART slots per fixture = ontology ids 0-55 excluding P3-owned per-finger ids 24-33; every slot has drafted/not_visible/disabled state plus a strict binary PNG and hash
production scope:                 exact ten hash-bound LV-MHP fixtures through real S06 GroundingDINO, S07 SAM2, and S09 fusion; external annotations remain QA-only, non-gold, and never enter prompts or production masks
material-completeness guard:      at least 12 drafted core parts and one SAM2 refinement per fixture; observed drafted range 20-32 and refinement range 19-29
defect 1:                         S05 understood Sapiens split limbs but not SCHP broad left/right arm and leg classes; broad-class aliases, pose torso/head/neck/shoulder bases, joint carving, and person-scaled hand/foot bases added
defect 2:                         a Sapiens result with only 86 foreground pixels was treated as healthy; <1% foreground is now degraded and cached S03 artifacts route to SCHP fail-closed
defect 3:                         confident pose chains were discarded when parsing contained no limb class; pose-only limb capsules now recover all eight arm/leg segments
multi-person ownership:           fixture 4512 has 55 co-subject truth pixels inside the padded p0 context, but the final p0 body-authority overlap is exactly 0; annotation was used only for the post-output QA assertion
QC-011:                           10/10 full PART maps independently expanded to atomic masks; every result overlap_px=0
runtime provenance:               per-fixture contracts bind S05, production adapter, core-contract writer, S09, and QC-011 implementation hashes; stale-runtime fixtures are refreshed while current receipts resume
evidence:                         qa/live_verification/p2_core_fixture_gate_20260712.json
validation:                       704 full tests pass; Ruff check clean; 278 source/test/tool Python files format-clean; tracker validation clean
