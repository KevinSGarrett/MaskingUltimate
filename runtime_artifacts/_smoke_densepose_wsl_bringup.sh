#!/usr/bin/env bash
# Run DensePose smoke from WSL ext4 to avoid /mnt/c cold-import hangs.
set -euo pipefail
PY=/home/kevin/miniforge3/envs/maskfactory/bin/python
REPO_WIN=/mnt/c/Comfy_UI_Main_Masking
WORKDIR=/home/kevin/mfwork/tmp_densepose_smoke
mkdir -p "$WORKDIR"
cp -f "$REPO_WIN/tools/smoke_densepose_wsl.py" "$WORKDIR/smoke_densepose_wsl.py"
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
# Keep CUDA visible; empty cache first if possible
"$PY" -c 'import torch; torch.cuda.empty_cache() if torch.cuda.is_available() else None; print("cuda_ok", torch.cuda.is_available(), flush=True)'
"$PY" "$WORKDIR/smoke_densepose_wsl.py" \
  --checkpoint "$REPO_WIN/models/densepose/densepose_rcnn_R_50_FPN_s1x.pkl" \
  --image "$REPO_WIN/qa/fixtures/smoke/ultralytics_bus_adults.jpg" \
  --config /home/kevin/mfwork/source/detectron2/projects/DensePose/configs/densepose_rcnn_R_50_FPN_s1x.yaml
