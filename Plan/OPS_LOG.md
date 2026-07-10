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

## 2026-07-10 22:20 UTC - Civitai adult/NSFW governance gates verified
**Items:** MF-P0-14.04
**Result:** SUPERSEDED 2026-07-10 - Kevin clarified that adult/NSFW assets must
be usable for training and may seed human-reviewed gold. Registries now encode
conditional eligibility after the normal governance and quality gates.

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
