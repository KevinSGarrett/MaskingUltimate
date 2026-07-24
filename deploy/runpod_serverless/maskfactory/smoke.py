"""Read-only GPU and shared-volume smoke used for endpoint acceptance."""

from __future__ import annotations

import json
from pathlib import Path

import torch

volume = Path("/workspace")
result = {
    "cuda_available": torch.cuda.is_available(),
    "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "network_volume_visible": volume.is_dir(),
    "maskfactory_visible": (volume / "maskfactory").is_dir(),
}
if not all(
    (
        result["cuda_available"],
        result["network_volume_visible"],
        result["maskfactory_visible"],
    )
):
    raise SystemExit(json.dumps(result, sort_keys=True))
print(json.dumps(result, sort_keys=True))
