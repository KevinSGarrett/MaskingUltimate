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
