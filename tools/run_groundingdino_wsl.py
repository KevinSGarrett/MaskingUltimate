"""Production multi-prompt GroundingDINO box proposals in pinned WSL source env."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import types
from collections.abc import Mapping, Sequence
from pathlib import Path

# GroundingDINO imports YAPF only for SLConfig.pretty_text. On managed Windows,
# YAPF's platformdirs lookup can block on an inaccessible user-profile API.
# Inference never calls pretty_text, so provide the exact no-op formatting API
# before importing the pinned source package.
yapf_module = types.ModuleType("yapf")
yapflib_module = types.ModuleType("yapf.yapflib")
yapf_api_module = types.ModuleType("yapf.yapflib.yapf_api")
yapf_api_module.FormatCode = lambda text, **kwargs: (text, False)
sys.modules.setdefault("yapf", yapf_module)
sys.modules.setdefault("yapf.yapflib", yapflib_module)
sys.modules.setdefault("yapf.yapflib.yapf_api", yapf_api_module)

import groundingdino  # noqa: E402
from groundingdino.util.inference import load_image, load_model, predict  # noqa: E402
from PIL import Image  # noqa: E402

SOURCE_REVISION = "856dde20aee659246248e20734ef9ba5214f5e44"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_prompts_and_thresholds(
    prompts: tuple[str, ...], box_threshold: float, text_threshold: float
) -> None:
    if not all(isinstance(prompt, str) and prompt.strip() for prompt in prompts) or len(
        set(prompts)
    ) != len(prompts):
        raise ValueError("prompts must be unique non-empty strings")
    if not 0 <= box_threshold <= 1 or not 0 <= text_threshold <= 1:
        raise ValueError("thresholds must be in 0..1")


def _predict_one(
    model: object,
    image_path: Path,
    prompts: tuple[str, ...],
    *,
    box_threshold: float,
    text_threshold: float,
) -> tuple[list[int], list[dict]]:
    _, image = load_image(str(image_path))
    with Image.open(image_path) as opened:
        width, height = opened.size
    proposals = []
    for prompt in prompts:
        boxes, logits, phrases = predict(
            model=model,
            image=image,
            caption=prompt + " .",
            box_threshold=box_threshold,
            text_threshold=text_threshold,
            device="cpu",
        )
        for box, score, phrase in zip(
            boxes.detach().cpu().numpy(),
            logits.detach().cpu().numpy(),
            phrases,
            strict=True,
        ):
            cx, cy, box_width, box_height = box
            left = max(0.0, float((cx - box_width / 2) * width))
            top = max(0.0, float((cy - box_height / 2) * height))
            right = min(float(width), float((cx + box_width / 2) * width))
            bottom = min(float(height), float((cy + box_height / 2) * height))
            if right <= left or bottom <= top:
                continue
            proposals.append(
                {
                    "prompt": prompt,
                    "bbox_xyxy": [left, top, right, bottom],
                    "box_score": float(score),
                    "text_score": float(score),
                    "phrase": phrase,
                    "authority": "proposal_only",
                }
            )
    return [width, height], proposals


def run(
    checkpoint: Path,
    image_path: Path,
    prompts: tuple[str, ...],
    *,
    box_threshold: float,
    text_threshold: float,
) -> dict:
    _validate_prompts_and_thresholds(prompts, box_threshold, text_threshold)
    package = Path(groundingdino.__file__).resolve().parent
    config = package / "config" / "GroundingDINO_SwinT_OGC.py"
    model = load_model(str(config), str(checkpoint), device="cpu")
    try:
        image_size, proposals = _predict_one(
            model,
            image_path,
            prompts,
            box_threshold=box_threshold,
            text_threshold=text_threshold,
        )
    finally:
        del model
    return {
        "protocol_version": 1,
        "schema_version": "1.0.0",
        "checkpoint_sha256": _sha256(checkpoint),
        "source_revision": SOURCE_REVISION,
        "device_type": "cpu",
        "device": platform.processor() or "cpu",
        "model_load_count": 1,
        "prompts": list(prompts),
        "box_threshold": box_threshold,
        "text_threshold": text_threshold,
        "image_size": image_size,
        "authority": "proposal_boxes_only",
        "may_write_final_masks": False,
        "proposals": proposals,
    }


def run_batch(
    checkpoint: Path,
    records: Sequence[Mapping[str, object]],
    prompts: tuple[str, ...],
    *,
    box_threshold: float,
    text_threshold: float,
) -> dict:
    """Run up to 256 hash-bound images through one governed model load."""

    _validate_prompts_and_thresholds(prompts, box_threshold, text_threshold)
    if not 1 <= len(records) <= 256:
        raise ValueError("batch must contain 1..256 records")
    package = Path(groundingdino.__file__).resolve().parent
    config = package / "config" / "GroundingDINO_SwinT_OGC.py"
    model = load_model(str(config), str(checkpoint), device="cpu")
    outputs = []
    seen = set()
    try:
        for record in records:
            sample_id = record.get("sample_id")
            source_sha256 = record.get("source_sha256")
            image_path_value = record.get("image_path")
            if not isinstance(sample_id, str) or not sample_id or sample_id in seen:
                raise ValueError("batch sample_id is invalid or duplicated")
            if (
                not isinstance(source_sha256, str)
                or len(source_sha256) != 64
                or any(character not in "0123456789abcdef" for character in source_sha256)
            ):
                raise ValueError("batch source_sha256 is invalid")
            if not isinstance(image_path_value, str) or not image_path_value:
                raise ValueError("batch image_path is invalid")
            image_path = Path(image_path_value)
            if not image_path.is_file() or _sha256(image_path) != source_sha256:
                raise ValueError(f"batch source hash mismatch:{sample_id}")
            seen.add(sample_id)
            image_size, proposals = _predict_one(
                model,
                image_path,
                prompts,
                box_threshold=box_threshold,
                text_threshold=text_threshold,
            )
            outputs.append(
                {
                    "sample_id": sample_id,
                    "source_sha256": source_sha256,
                    "image_size": image_size,
                    "proposals": proposals,
                }
            )
    finally:
        del model
    result = {
        "protocol_version": 2,
        "schema_version": "maskfactory.groundingdino_batch.v1",
        "checkpoint_sha256": _sha256(checkpoint),
        "source_revision": SOURCE_REVISION,
        "device_type": "cpu",
        "device": platform.processor() or "cpu",
        "model_load_count": 1,
        "record_count": len(outputs),
        "prompts": list(prompts),
        "box_threshold": box_threshold,
        "text_threshold": text_threshold,
        "authority": "proposal_boxes_only",
        "may_write_final_masks": False,
        "records": outputs,
    }
    result["output_sha256"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--image", type=Path)
    inputs.add_argument("--images-manifest", type=Path)
    parser.add_argument("--prompts-json", required=True)
    parser.add_argument("--box-threshold", type=float, required=True)
    parser.add_argument("--text-threshold", type=float, required=True)
    args = parser.parse_args()
    prompts = tuple(json.loads(args.prompts_json))
    if args.image is not None:
        result = run(
            args.checkpoint,
            args.image,
            prompts,
            box_threshold=args.box_threshold,
            text_threshold=args.text_threshold,
        )
    else:
        manifest = json.loads(args.images_manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != (
            "maskfactory.groundingdino_image_batch.v1"
        ):
            raise ValueError("batch manifest schema is invalid")
        records = manifest.get("records")
        if not isinstance(records, list):
            raise ValueError("batch manifest records are invalid")
        result = run_batch(
            args.checkpoint,
            records,
            prompts,
            box_threshold=args.box_threshold,
            text_threshold=args.text_threshold,
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
