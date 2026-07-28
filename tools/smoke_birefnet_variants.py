from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as functional
from PIL import Image
from torchvision.transforms.functional import normalize, pil_to_tensor
from transformers import AutoModelForImageSegmentation

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg"
OUTPUT = ROOT / "qa" / "live_verification" / "birefnet_variants_runtime_20260714.json"
VARIANTS = {
    "birefnet_dynamic": {
        "path": ROOT / "models" / "bv" / "dyn",
        "revision": "280306042f57b7a33854319da62fd86aaa89ec4c",
        "checkpoint_sha256": "e3d2e4884e51ff30f0cd630edc6b1e41b06b7f23a0a2a5169f7b7cb33a711c2d",
        "output": "silhouette_and_soft_matte",
        "requested_resolution": None,
    },
    "birefnet_hr": {
        "path": ROOT / "models" / "bv" / "hr",
        "revision": "a7a562f6fd16021180f2f4348f4de003a2d3d1e1",
        "checkpoint_sha256": "9d678bafec0b0019fbb073b7fd02f05ede25dc4b15254f23b2fb0be333200c0d",
        "output": "silhouette",
        "requested_resolution": 2048,
    },
    "birefnet_hr_matting": {
        "path": ROOT / "models" / "bv" / "hrm",
        "revision": "5d6b6f8adcb5b417c871b1d84ceaae9871355b7f",
        "checkpoint_sha256": "a5a4de698739ea5e0e8bbab28e1b293dde95092b87a442d566cbc585c53cef55",
        "output": "soft_alpha_and_thresholded_silhouette",
        "requested_resolution": 2048,
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _person_crop() -> tuple[Image.Image, tuple[int, int, int, int]]:
    image = Image.open(FIXTURE).convert("RGB")
    # Fixed RF-DETR/YOLO-agreed left-person box expanded 1.25 like S01.
    left, top, right, bottom = 49.75, 398.25, 247.625, 905.5
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    width, height = (right - left) * 1.25, (bottom - top) * 1.25
    box = (
        max(0, int(center_x - width / 2)),
        max(0, int(center_y - height / 2)),
        min(image.width, int(np.ceil(center_x + width / 2))),
        min(image.height, int(np.ceil(center_y + height / 2))),
    )
    return image.crop(box), box


def _tensor(image: Image.Image, resolution: int | None) -> torch.Tensor:
    if resolution is not None:
        image = image.resize((resolution, resolution), Image.Resampling.BILINEAR)
    value = pil_to_tensor(image).float().div_(255)
    value = normalize(value, [0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    if resolution is None:
        pad_height = (-value.shape[-2]) % 32
        pad_width = (-value.shape[-1]) % 32
        if pad_height or pad_width:
            value = functional.pad(value, (0, pad_width, 0, pad_height), mode="replicate")
    return value.unsqueeze(0).to("cuda")


def _predict(
    model,
    tensor: torch.Tensor,
    shape: tuple[int, int],
    *,
    square_input: bool,
) -> tuple[np.ndarray, float]:
    started = time.perf_counter()
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
        prediction = model(tensor)[-1].sigmoid().float()
        if square_input:
            prediction = functional.interpolate(
                prediction,
                size=shape,
                mode="bilinear",
                align_corners=False,
            )
        prediction = prediction[0, 0, : shape[0], : shape[1]]
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    return prediction.cpu().numpy(), elapsed


def main() -> int:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    np.random.seed(0)
    crop, crop_box = _person_crop()
    crop_bytes = np.asarray(crop, dtype=np.uint8).tobytes()
    records: dict[str, Any] = {}

    for key, variant in VARIANTS.items():
        model_dir = Path(variant["path"])
        if _sha256(model_dir / "model.safetensors") != variant["checkpoint_sha256"]:
            raise RuntimeError(f"{key} checkpoint hash drift")
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        load_started = time.perf_counter()
        model = AutoModelForImageSegmentation.from_pretrained(
            model_dir,
            trust_remote_code=True,
            local_files_only=True,
        ).eval()
        model.to("cuda")
        torch.cuda.synchronize()
        load_seconds = time.perf_counter() - load_started
        requested_resolution = variant["requested_resolution"]
        effective_resolution = requested_resolution
        oom_fallback = False
        try:
            tensor = _tensor(crop, effective_resolution)
            first, first_seconds = _predict(
                model,
                tensor,
                (crop.height, crop.width),
                square_input=effective_resolution is not None,
            )
        except torch.cuda.OutOfMemoryError:
            if requested_resolution != 2048:
                raise
            del tensor
            torch.cuda.empty_cache()
            effective_resolution = 1024
            oom_fallback = True
            tensor = _tensor(crop, effective_resolution)
            first, first_seconds = _predict(
                model,
                tensor,
                (crop.height, crop.width),
                square_input=True,
            )
        second, second_seconds = _predict(
            model,
            tensor,
            (crop.height, crop.width),
            square_input=effective_resolution is not None,
        )
        first_hash = hashlib.sha256(first.tobytes()).hexdigest()
        second_hash = hashlib.sha256(second.tobytes()).hexdigest()
        if first_hash != second_hash:
            raise RuntimeError(f"{key} confidence output is nondeterministic")
        binary = second >= 0.5
        foreground_fraction = float(binary.mean())
        fractional_fraction = float(((second > 0.001) & (second < 0.999)).mean())
        if not np.isfinite(second).all() or second.min() < 0 or second.max() > 1:
            raise RuntimeError(f"{key} confidence is not finite 0..1")
        if not 0.01 < foreground_fraction < 0.99:
            raise RuntimeError(f"{key} thresholded silhouette is degenerate")
        if key == "birefnet_hr_matting" and fractional_fraction <= 0.001:
            raise RuntimeError("HR-matting did not preserve a soft alpha boundary")
        records[key] = {
            "repo_revision": variant["revision"],
            "checkpoint_sha256": variant["checkpoint_sha256"],
            "output_contract": variant["output"],
            "shape": list(second.shape),
            "confidence_min": float(second.min()),
            "confidence_max": float(second.max()),
            "confidence_sha256": second_hash,
            "binary_sha256": hashlib.sha256(binary.astype(np.uint8).tobytes()).hexdigest(),
            "foreground_fraction": foreground_fraction,
            "fractional_alpha_fraction": fractional_fraction,
            "requested_resolution": requested_resolution or "native_divisible_by_32",
            "effective_resolution": effective_resolution or "native_divisible_by_32",
            "oom_fallback": oom_fallback,
            "load_seconds": round(load_seconds, 6),
            "inference_seconds": [round(first_seconds, 6), round(second_seconds, 6)],
            "deterministic": True,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        }
        del tensor, model
        torch.cuda.empty_cache()

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "result": "pass",
        "fixture": {
            "path": FIXTURE.relative_to(ROOT).as_posix(),
            "sha256": _sha256(FIXTURE),
            "person_context_bbox_xyxy": list(crop_box),
            "crop_size": list(crop.size),
            "crop_pixel_sha256": hashlib.sha256(crop_bytes).hexdigest(),
        },
        "runtime": {
            "python": str(Path(torch.__file__).parents[1]),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "device": torch.cuda.get_device_name(0),
            "capability": list(torch.cuda.get_device_capability(0)),
        },
        "variants": records,
        "authority": {
            "lifecycle_state": "installed",
            "shadow_only": True,
            "incumbent": "birefnet_general",
            "promotion_claimed": False,
        },
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
