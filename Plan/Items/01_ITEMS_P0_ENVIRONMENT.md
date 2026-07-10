# ITEMS — Phase P0: Environment & Foundation (Days 1–3)

Every atomic item to complete P0. Check `[x]` only when the verify clause passes. Parent task IDs from doc 14 §1.

## MF-P0-01 — WSL2 Ubuntu 22.04 + systemd + hot workdir (spec: 06 §1)
- [ ] MF-P0-01.01 Confirm NVIDIA driver ≥ 591 on Windows host (`nvidia-smi` → 592.01) · record in `Plan\OPS_LOG.md` (create the file)
- [ ] MF-P0-01.02 Install WSL2 + distro: `wsl --install -d Ubuntu-22.04` → reboot → create Linux user `kevin`
- [ ] MF-P0-01.03 `wsl --update` · verify WSL kernel ≥ 2.3 (`wsl --version`) for CUDA 12.8 passthrough
- [ ] MF-P0-01.04 Verify GPU inside WSL: `nvidia-smi` shows RTX 5060 Laptop GPU
- [ ] MF-P0-01.05 Enable systemd: `/etc/wsl.conf` → `[boot] systemd=true` · `wsl --shutdown` · verify `systemctl is-system-running`
- [ ] MF-P0-01.06 Create `C:\Users\kevin\.wslconfig`: `[wsl2] memory=24GB processors=12 swap=16GB` (tune to installed RAM) · restart WSL
- [ ] MF-P0-01.07 Create hot workdir `~/mfwork` on ext4 · export `MF_WORKDIR` in `~/.bashrc` (pipeline `io.workdir`)
- [ ] MF-P0-01.08 Verify `/mnt/c/Comfy_UI_Main_Masking/` read/write from WSL (touch + delete test file)
- [ ] MF-P0-01.09 Benchmark small-file I/O `/mnt/c` vs `~/mfwork` · record numbers in OPS_LOG (justifies hot-workdir rule)
- [ ] MF-P0-01.10 Confirm NO system CUDA toolkit installed in WSL (`which nvcc` → empty; pitfall 7 — wheels provide runtime)

## MF-P0-02 — conda env `maskfactory` + PyTorch 2.7 cu128 (spec: 06 §2)
- [ ] MF-P0-02.01 `sudo apt update && sudo apt install -y build-essential ninja-build cmake libgl1 libglib2.0-0 ffmpeg`
- [ ] MF-P0-02.02 Install Miniforge (`Miniforge3-Linux-x86_64.sh -b`) · `conda init bash` · reopen shell
- [ ] MF-P0-02.03 `conda create -n maskfactory python=3.11 -y` · `conda activate maskfactory`
- [ ] MF-P0-02.04 `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128`
- [ ] MF-P0-02.05 Verify: `torch.cuda.is_available()` True · device name RTX 5060 · `get_device_capability() == (12, 0)`
- [ ] MF-P0-02.06 Run a real CUDA matmul (sm_120 kernel smoke) — must NOT raise "no kernel image available"
- [ ] MF-P0-02.07 Install pipeline deps: numpy opencv-python-headless pillow scipy scikit-image shapely pycocotools click loguru pydantic jsonschema pyyaml tqdm rich onnxruntime-gpu==1.20.* fastapi uvicorn dvc[ssh] pytest ruff pandas matplotlib
- [ ] MF-P0-02.08 Freeze: `pip freeze > env/requirements.lock.txt`
- [ ] MF-P0-02.09 Export: `conda env export > env/maskfactory_env.yml`
- [ ] MF-P0-02.10 Create `env/source_builds.lock` scaffold (header + format) for pinned source-build commits (pitfall 2)

## MF-P0-03 — Docker Desktop + CVAT v2.24.0 pinned (spec: 06 §4)
- [ ] MF-P0-03.01 Install Docker Desktop (latest), WSL2 backend
- [ ] MF-P0-03.02 Settings → Resources → WSL integration → enable Ubuntu-22.04
- [ ] MF-P0-03.03 Verify container GPU: `docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi`
- [ ] MF-P0-03.04 Clone CVAT into `C:\Comfy_UI_Main_Masking\cvat` · `git checkout v2.24.0` · record exact tag in OPS_LOG + later `configs\cvat.yaml`
- [ ] MF-P0-03.05 Edit compose ports to bind `127.0.0.1:8080:8080` (localhost only — doc 05 §7)
- [ ] MF-P0-03.06 Add bind mount of `/mnt/c/Comfy_UI_Main_Masking/data` into the CVAT share volume (direct import path)
- [ ] MF-P0-03.07 `docker compose -f docker-compose.yml -f components/serverless/docker-compose.serverless.yml up -d` · all containers healthy in `docker ps`
- [ ] MF-P0-03.08 `docker exec -it cvat_server python3 manage.py createsuperuser` (user `kevin`) · login at http://localhost:8080 works
- [ ] MF-P0-03.09 Create `.env` (git-ignored) holding CVAT credentials/token — never in configs or code

## MF-P0-04 — nuclio serverless SAM2 interactor, CPU build (spec: 06 §4)
- [ ] MF-P0-04.01 Install `nuctl` CLI matching the serverless compose version
- [ ] MF-P0-04.02 Deploy CPU interactor: `./serverless/deploy_cpu.sh serverless/pytorch/facebookresearch/sam2/nuclio` (decision: CPU — pipeline owns the GPU)
- [ ] MF-P0-04.03 `nuctl get functions` → SAM2 function state `ready`
- [ ] MF-P0-04.04 In CVAT UI on a scratch task: Magic Wand → interactor → SAM2 click-segment produces a mask
- [ ] MF-P0-04.05 Record interactor cold-start time in OPS_LOG (~60 s is normal — troubleshooting baseline, 15 §7)

## MF-P0-05 — Ollama + local VLM stack (spec: 06 §5, 10 §1)
- [ ] MF-P0-05.01 `docker run -d --name ollama --gpus all -v ollama:/root/.ollama -p 127.0.0.1:11434:11434 ollama/ollama`
- [ ] MF-P0-05.02 `docker exec ollama ollama pull qwen2.5vl:7b` (primary VLM, Q4)
- [ ] MF-P0-05.03 `docker exec ollama ollama pull llama3.2-vision:11b` (fallback VLM)
- [ ] MF-P0-05.04 `docker exec ollama ollama pull qwen2.5:7b-instruct` (text LLM for manifest lint)
- [ ] MF-P0-05.05 Smoke: send P-PART-style prompt + a sample image to 127.0.0.1:11434 → response parses as strict JSON

## MF-P0-06 — Model checkpoints M1–M12 + registry (spec: 06 §3, 04 §3)
- [ ] MF-P0-06.01 Implement `maskfactory models fetch <key>`: download → `models\<family>\` · SHA-256 · registry entry {url, version, license, date} · 1-image smoke test · `verified: true` · loader refuses unregistered paths
- [ ] MF-P0-06.02 Fetch M1 person detector `yolo11m.pt` (ultralytics)
- [ ] MF-P0-06.03 Fetch M2 silhouette `BiRefNet-general.safetensors`
- [ ] MF-P0-06.04 Fetch M3 parsing `sapiens_0.6b_seg.pt2` (HF facebook/sapiens-seg-0.6b torchscript)
- [ ] MF-P0-06.05 Fetch M4 fallback parsing SCHP `exp-schp-201908301523-atr.pth` + LIP variant
- [ ] MF-P0-06.06 Fetch M5 pose `dw-ll_ucoco_384.onnx` + `yolox_l.onnx` (DWPose)
- [ ] MF-P0-06.07 `pip install mediapipe` · fetch M6 `hand_landmarker.task`
- [ ] MF-P0-06.08 `pip install "git+https://github.com/facebookresearch/sam2"` · fetch M7 `sam2.1_hiera_large.pt` + `sam2.1_hiera_base_plus.pt` (auto-fallback pair)
- [ ] MF-P0-06.09 Fetch M8 `groundingdino_swint_ogc.pth` (Grounded-SAM-2 repo, boxes only)
- [ ] MF-P0-06.10 Build detectron2 from source on cu128 (`export TORCH_CUDA_ARCH_LIST="12.0"`, ninja, 15–30 min) · pin commit into `env/source_builds.lock`
- [ ] MF-P0-06.11 Install DensePose project · fetch M9 `densepose_rcnn_R_50_FPN_s1x.pkl`
- [ ] MF-P0-06.12 Fetch M10 face-parsing BiSeNet `79999_iter.pth`
- [ ] MF-P0-06.13 Fetch M11 `vitmatte_s.pth` (hustvl/ViTMatte-S)
- [ ] MF-P0-06.14 Register M12 (Ollama-managed VLMs) in registry with `ollama list` digests, `managed: true`
- [ ] MF-P0-06.15 Verify idempotency: rerun `models fetch --all` → no-op, all hashes match

## MF-P0-07 — `maskfactory doctor` (spec: 06 §9)
- [ ] MF-P0-07.01 Implement doctor checks: torch cu128 + sm_120 · every registered model loads + smoke output hash matches reference · CVAT API reachable (+ project-exists check, skippable pre-P1) · nuclio interactor answers · Ollama answers an image test · disk free ≥ 200 GB (warn <150 / block-ingest <75 per 15 §4) · WSL↔C:\ round-trip write · png_strict self-test · SQLite writable · stale `runs\gpu.lock` detection
- [ ] MF-P0-07.02 Create smoke fixtures `qa\fixtures\smoke\` (1 image per model + expected output hashes)
- [ ] MF-P0-07.03 Doctor exits non-zero on any FAIL, printing a fix hint per check
- [ ] MF-P0-07.04 Run doctor on this machine → ALL GREEN · paste output into OPS_LOG

## MF-P0-08 — Repo, quality rails, CI (spec: 05 §3, 06 §2/§8)
- [ ] MF-P0-08.01 `git init` at project root · `.gitignore` (models/, data/, runs/, logs/, datasets/, .env, mfwork) · `core.autocrlf=false`
- [ ] MF-P0-08.02 Create GitHub repo under Scentiment-Dev · push · enable Actions
- [ ] MF-P0-08.03 Author `src\maskfactory\io\png_strict.py` — the ONLY mask writer (mode L, optimize=False, asserts values ⊆ {0,255} for gold paths, asserts dims) + built-in self-test
- [ ] MF-P0-08.04 Add lint/CI rule banning `cv2.imwrite` (and raw `Image.save`) for mask paths outside png_strict (pitfall 5 / QC-030 parity) · fixture violation fails CI
- [ ] MF-P0-08.05 pre-commit: ruff + black + EOF/whitespace hooks installed and passing
- [ ] MF-P0-08.06 GitHub Actions workflow: ruff + pytest on push/PR
- [ ] MF-P0-08.07 Scaffold `src\maskfactory\` exactly per doc 05 §3: cli.py, orchestrator.py, io\, ontology.py, stages\s00…s15 stubs, lanes\{hand,chest,hair,feet,prior3d}.py, fusion\{consensus,zorder,mapbuild}.py, qa\{checks,metrics,panels,topology}.py, vlm\{client,router,prompts\}, cvat_bridge\{push,pull,labelmap}.py, datasets\{builder,splits,coverage,cocorle}.py, training\{mask2former,segformer,handseg,clothparse,hairmatte,leaderboard.py}, serve\{api,comfy_export}.py, schemas\
- [ ] MF-P0-08.08 `pyproject.toml` with console script `maskfactory = maskfactory.cli:main` · `pip install -e .` · `maskfactory --help` lists all doc-05 commands (stubs OK)
- [ ] MF-P0-08.09 CI green on the scaffold

## P0 Exit Gate
- [ ] MF-P0-EXIT Doctor all green end-to-end · `env\` lockfiles + populated `model_registry.json` committed (D9 provable on paper) · phase checkboxes in doc 14 §1 updated
