#!/usr/bin/env bash
set -euo pipefail
PY=/home/kevin/miniforge3/envs/maskfactory/bin/python
"$PY" - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device", torch.cuda.get_device_name(0))
import detectron2
print("detectron2", detectron2.__version__)
from densepose import add_densepose_config
print("densepose ok")
PY
