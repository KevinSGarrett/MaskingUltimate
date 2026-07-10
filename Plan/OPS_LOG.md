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
