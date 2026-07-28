#!/usr/bin/env bash
set -euo pipefail

runtime=/home/kevin/mfenvs/rfdetr-1.7.1
source_root=/mnt/c/Comfy_UI_Main_Masking/models/runtime_cache/rfdetr_source_1.7.1
bootstrap_python=/home/kevin/mfenvs/sam31-5dd401d1/bin/python

if [[ -e "$runtime" ]]; then
    echo "refusing to replace existing runtime: $runtime" >&2
    exit 2
fi
if [[ ! -f "$source_root/pyproject.toml" ]]; then
    echo "frozen RF-DETR source is missing: $source_root" >&2
    exit 3
fi

"$bootstrap_python" -m venv "$runtime"
"$runtime/bin/python" -m pip install --upgrade \
    pip==25.3 setuptools==80.9.0 wheel==0.46.3
"$runtime/bin/python" -m pip install \
    --index-url https://download.pytorch.org/whl/cu128 \
    torch==2.11.0 torchvision==0.26.0
"$runtime/bin/python" -m pip install "$source_root"
"$runtime/bin/python" -m pip check

"$runtime/bin/python" - <<'PY'
import json

import rfdetr
import torch
import torchvision

print(
    json.dumps(
        {
            "capability": list(torch.cuda.get_device_capability(0))
            if torch.cuda.is_available()
            else None,
            "cuda": torch.cuda.is_available(),
            "rfdetr": getattr(rfdetr, "__version__", "unknown"),
            "torch": torch.__version__,
            "torchvision": torchvision.__version__,
        },
        sort_keys=True,
    )
)
PY
