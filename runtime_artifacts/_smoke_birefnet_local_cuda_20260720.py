"""One-shot BiRefNet local-CUDA smoke (Windows-safe: copy weights, no symlink)."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import torch
from huggingface_hub import snapshot_download
from PIL import Image
from torchvision import transforms
from transformers import AutoModelForImageSegmentation

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_ID = "ZhengPeng7/BiRefNet"
REVISION = "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4"


def main() -> int:
    checkpoint = (REPO_ROOT / "models/silhouette/BiRefNet-general.safetensors").resolve()
    image_path = REPO_ROOT / "qa/fixtures/smoke/ultralytics_bus_adults.jpg"
    source = snapshot_download(
        repo_id=REPO_ID,
        revision=REVISION,
        ignore_patterns=["*.safetensors", "*.bin", "*.pth", "*.onnx"],
    )
    with tempfile.TemporaryDirectory(prefix="maskfactory-birefnet-") as temporary:
        model_dir = Path(temporary) / "model"
        shutil.copytree(source, model_dir, symlinks=False)
        shutil.copy2(checkpoint, model_dir / "model.safetensors")
        model = AutoModelForImageSegmentation.from_pretrained(
            model_dir,
            trust_remote_code=True,
            local_files_only=True,
        ).eval()
        device = torch.device("cuda")
        model.to(device)
        image = Image.open(image_path).convert("RGB")
        transform = transforms.Compose(
            [
                transforms.Resize((1024, 1024)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )
        tensor = transform(image).unsqueeze(0).to(device)
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
            prediction = model(tensor)[-1].sigmoid().float().cpu()[0, 0]
        mask = (prediction.numpy().clip(0, 1) * 255).round().astype(np.uint8)
        foreground_fraction = float((mask >= 128).mean())
        output_hash = hashlib.sha256(mask.tobytes()).hexdigest()
        del tensor, prediction, model
        torch.cuda.empty_cache()
    passed = bool(mask.min() < mask.max() and 0.01 < foreground_fraction < 0.99)
    result = {
        "passed": passed,
        "output_sha256": output_hash if passed else "",
        "mask_shape": list(mask.shape),
        "mask_min": int(mask.min()),
        "mask_max": int(mask.max()),
        "foreground_fraction": round(foreground_fraction, 6),
        "torch": torch.__version__,
        "device": torch.cuda.get_device_name(0),
        "runtime": "local_cuda_comfyui_venv_copy_not_symlink",
        "family": "birefnet_general",
    }
    out = REPO_ROOT / "qa/live_verification/_birefnet_local_cuda_20260720T0956.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
