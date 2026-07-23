# Document 06: Environment & Installation Manual

> **Installation-profile amendment (doc 24):** CVAT, its serverless interactor, and human-review
> services are optional installations for `independent_real_accuracy`/training work. A core release
> doctor must report them separately and may be green when they are absent, provided all required
> autonomous-runtime, certificate, bridge, and recovery capabilities pass. The full proposed model
> library is likewise deferred; only the release's installed qualified capability snapshot is routed.

Target machine: Windows 11, NVIDIA RTX 5060 Laptop GPU 8 GB (Blackwell sm_120), driver 592.01.
**Blackwell constraint (critical):** sm_120 kernels require CUDA 12.8+ builds → PyTorch ≥ 2.7
`cu128` wheels. Older torch builds will fail with "no kernel image available". Everything below
is chosen to fit 8 GB VRAM in fp16/bf16 or 4-bit.

---

## 1. Layer 0 — Windows Host

1. NVIDIA driver ≥ 591 (already 592.01 ✔). Keep Studio/GRD current.
2. Enable WSL2 + install Ubuntu 22.04: `wsl --install -d Ubuntu-22.04` → reboot → create user `kevin`.
3. `wsl --update` (WSL kernel ≥ 2.3 for CUDA 12.8 passthrough). Verify inside WSL: `nvidia-smi`.
4. Docker Desktop (latest) with WSL2 backend; Settings → Resources → WSL integration → enable Ubuntu-22.04; enable GPU support (verify `docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi`).
5. `.wslconfig` in `C:\Users\kevin\`: `[wsl2] memory=24GB processors=12 swap=16GB` (tune to machine RAM).
6. Git for Windows + git in WSL; configure `core.autocrlf=false` in the repo (masks/scripts are byte-sensitive).

## 2. Layer 1 — WSL2 Pipeline Environment (conda env `maskfactory`)

```bash
# inside Ubuntu-22.04
sudo apt update && sudo apt install -y build-essential ninja-build cmake libgl1 libgles2 libglib2.0-0 ffmpeg
curl -L -o mf.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh && bash mf.sh -b
conda create -n maskfactory python=3.11 -y && conda activate maskfactory
# PyTorch 2.7+ cu128 (Blackwell)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
python -c "import torch;print(torch.__version__, torch.cuda.get_device_name(0), torch.cuda.is_available())"
pip install numpy opencv-python-headless pillow scipy scikit-image shapely pycocotools \
    click loguru pydantic jsonschema pyyaml tqdm rich onnxruntime-gpu==1.20.* \
    fastapi uvicorn dvc[ssh] pytest ruff pandas matplotlib
```
Freeze after first success: `pip freeze > env/requirements.lock.txt` + `conda env export > env/maskfactory_env.yml`. These two files + this doc = full env reproducibility (Definition of Done D9).

## 3. Layer 2 — Perception Models (install + register every one in `models\model_registry.json`)

| # | Component | Package/Repo | Checkpoint (→ `models\…`) | 8 GB note |
|---|-----------|--------------|---------------------------|-----------|
| M1 | Person detector | `ultralytics` (YOLO11) or RT-DETR-L via ultralytics | `yolo11m.pt` (person cls only) | 1.2 GB |
| M2 | Silhouette | BiRefNet — `pip install birefnet` or HF `ZhengPeng7/BiRefNet` | `BiRefNet-general.safetensors` | fp16, tile ≥ 2048 px inputs |
| M3 | Human parsing (primary) | Meta **Sapiens** seg — HF `facebook/sapiens-seg-0.6b(-torchscript)` | `sapiens_0.6b_seg.pt2` (28-class Goliath) | 0.6B fits; 1B only if headroom proves out; bf16 |
| M4 | Human parsing (fallback) | **SCHP** github `GoGoDuck912/Self-Correction-Human-Parsing` | `exp-schp-201908301523-atr.pth` (ATR 18-cls) + LIP variant | 1.5 GB; also feeds clothing lane |
| M5 | Whole-body pose | **DWPose** ONNX (`dw-ll_ucoco_384.onnx` + `yolox_l.onnx`) via onnxruntime-gpu | 133-kp COCO-WholeBody incl. 21×2 hand, 6 foot, face | 1.5 GB |
| M6 | Hand landmarks (crop lane) | MediaPipe Tasks `pip install mediapipe` | `hand_landmarker.task` | CPU-capable |
| M7 | Boundary refiner | **SAM 2.1** — `pip install "git+https://github.com/facebookresearch/sam2"` | `sam2.1_hiera_large.pt` + `sam2.1_hiera_base_plus.pt` (auto-fallback) | large fp16 ≈4.5 GB |
| M8 | Open-vocab boxes | Grounded-SAM-2 repo (GroundingDINO Swin-T) | `groundingdino_swint_ogc.pth` | boxes only, never final masks |
| M9 | 3D surface prior | detectron2 + DensePose (`pip install 'git+https://github.com/facebookresearch/detectron2'` then densepose project) | `densepose_rcnn_R_50_FPN_s1x.pkl` | build from source on cu128 — see §8 pitfalls |
| M10 | Hair/face parsing | Sapiens covers hair/face classes; face-parsing BiSeNet (`zllrunning/face-parsing.PyTorch`) as detail fallback | `79999_iter.pth` | tiny |
| M11 | Matting | **ViTMatte** (hustvl/ViTMatte-S via HF) seeded by trimap | `vitmatte_s.pth` | small |
| M12 | Local VLM | Ollama: `qwen2.5vl:7b` (Q4) — verified fallback `llava:13b`; text `qwen2.5:7b-instruct` | managed by Ollama | runs alone in slot |

Download procedure (uniform): `maskfactory models fetch <key>` → downloads to `models\<family>\`,
computes SHA-256, writes registry entry with url/version/license/date, runs a 1-image smoke test,
sets `verified: true`. **Nothing loads unless verified.**

## 4. Layer 3 — CVAT + Serverless SAM2 (Docker)

```bash
cd /mnt/c/Comfy_UI_Main_Masking/cvat
git clone https://github.com/cvat-ai/cvat . && git checkout v2.24.0   # pin; record actual tag in registry
export CVAT_HOST=localhost
docker compose -f docker-compose.yml -f components/serverless/docker-compose.serverless.yml up -d
# nuclio CLI (nuctl) then deploy SAM2 interactor:
./serverless/deploy_gpu.sh serverless/pytorch/facebookresearch/sam2/nuclio
docker exec -it cvat_server python3 manage.py createsuperuser   # user: kevin
```
- UI at `http://localhost:8080`; bind 127.0.0.1 only (edit compose ports `127.0.0.1:8080:8080`).
- Data volume bind: mount `/mnt/c/Comfy_UI_Main_Masking/data` into cvat share for direct import.
- If the GPU serverless SAM2 fights the pipeline for VRAM: deploy CPU build of the interactor
  (slower but fine for click-refine) — decision default: **CPU interactor**, pipeline owns the GPU.
- Label setup is scripted, never manual: `maskfactory cvat init-project` creates the project with
  all ontology labels/colors/attributes from `ontology.yaml` via CVAT REST (doc 11 §2).
- Alternative (fallback only, decision made): Label Studio + `label-studio-ml-backend` SAM2 —
  used ONLY if CVAT serverless proves unstable on this machine; switch procedure runbook §9.

## 5. Layer 4 — Ollama (VLM QA)

`docker run -d --name ollama --gpus all -v ollama:/root/.ollama -p 127.0.0.1:11434:11434 ollama/ollama`
then `docker exec ollama ollama pull qwen2.5vl:7b`. Pipeline talks to `http://127.0.0.1:11434`
(config `vlm.yaml`). VLM slot rule: orchestrator stops other GPU stages while S11 runs (doc 05 §5).

## 6. Layer 5 — Training Stack (used from P5)

`pip install mmengine "mmcv>=2.1" mmsegmentation mmdet` (mmcv compiled for cu128 — build from
source if wheel missing, §8) — OR detectron2 Mask2Former project (already built for M9).
Decision: **primary trainer = MMSegmentation** (Mask2Former & SegFormer configs both available),
detectron2 kept for DensePose only. Swin-L or other high-memory runs use a
selected RunPod tier, with all
inputs, checkpoints, and evidence on persistent storage. AWS is read-only
inventory only and is never a training or artifact-publish target.

## 7. ComfyUI Side (native Windows)

No changes to Kevin's existing install; the node pack (doc 13) is a folder copied into
`ComfyUI\custom_nodes\maskfactory_nodes\` reading directly from `C:\Comfy_UI_Main_Masking\data\packages\`.

## 8. Known Pitfalls (pre-answered)

1. **sm_120 mismatch**: any "no kernel image" error → wrong wheel; reinstall cu128 index. For source
   builds: `export TORCH_CUDA_ARCH_LIST="12.0"`.
2. detectron2/mmcv on cu128 may lack prebuilt wheels → build from source with ninja (15–30 min);
   pin commit hashes into `env/source_builds.lock`.
3. WSL2 I/O on `/mnt/c` is slow for many small files → pipeline writes hot intermediates to
   `~/mfwork` (ext4) and syncs packages to `/mnt/c/...` at stage end (`io.workdir` config).
4. Docker Desktop + WSL GPU is legacy local integration only. Production GPU
   work runs directly on the selected RunPod without GPU/VRAM governance.
5. PNG strictness: Pillow must save mode `L`, `optimize=False`; `png_strict.py` is the single
   writer used by all code — direct `cv2.imwrite` for masks is banned by lint rule.
6. Laptop thermals: long batches at 100% GPU → set `pipeline.yaml: gpu_cooldown_sec: 3` between
   heavy images; keep laptop on AC + elevated.
7. `nvidia-smi` in WSL shows driver 592 but CUDA runtime comes from wheels — do NOT apt-install
   a system CUDA toolkit (conflicts); only `cuda-compat` if a tool insists.

## 9. Verification Checklist (run after install — maps to task MF-P0-07)

`maskfactory doctor` prints PASS/FAIL for: torch cu128 + sm_120 visible · each registered model
loads + 1-image smoke output hash matches reference · CVAT API reachable + project exists ·
nuclio/interactor answers · Ollama answers with image test · disk free ≥ 200 GB · WSL↔C:\ path
round-trip write test · png_strict self-test · SQLite writable.
