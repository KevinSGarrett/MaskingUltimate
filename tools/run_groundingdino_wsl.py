"""Production multi-prompt GroundingDINO box proposals in pinned WSL source env."""

from __future__ import annotations

import argparse
import contextlib
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


def _canonical_sha256(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _checkpoint_document(
    *, run_policy_sha256: str, planned_record_count: int, records: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "maskfactory.groundingdino_batch_checkpoint.v1",
        "run_policy_sha256": run_policy_sha256,
        "planned_record_count": planned_record_count,
        "completed_record_count": len(records),
        "complete": len(records) == planned_record_count,
        "records": list(records),
    }
    return {**body, "self_sha256": _canonical_sha256(body)}


def _load_checkpoint(
    path: Path,
    *,
    run_policy_sha256: str,
    records: Sequence[Mapping[str, object]],
) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("batch checkpoint is not an object")
    sealed = dict(document)
    self_sha256 = sealed.pop("self_sha256", None)
    if self_sha256 != _canonical_sha256(sealed):
        raise ValueError("batch checkpoint seal mismatch")
    completed = document.get("records")
    if (
        document.get("schema_version") != "maskfactory.groundingdino_batch_checkpoint.v1"
        or document.get("run_policy_sha256") != run_policy_sha256
        or document.get("planned_record_count") != len(records)
        or not isinstance(completed, list)
        or document.get("completed_record_count") != len(completed)
        or len(completed) > len(records)
        or document.get("complete") is not (len(completed) == len(records))
    ):
        raise ValueError("batch checkpoint policy mismatch")
    normalized = []
    for index, output in enumerate(completed):
        expected = records[index]
        if (
            not isinstance(output, dict)
            or output.get("sample_id") != expected["sample_id"]
            or output.get("source_sha256") != expected["source_sha256"]
            or not isinstance(output.get("image_size"), list)
            or not isinstance(output.get("proposals"), list)
        ):
            raise ValueError("batch checkpoint contiguous lineage mismatch")
        normalized.append(output)
    return normalized


def _load_nude_shard(path: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("nude shard is not an object")
    sealed = dict(document)
    self_sha256 = sealed.pop("self_sha256", None)
    samples = document.get("samples")
    ordered = document.get("ordered_sample_ids")
    if (
        document.get("schema_version") != "maskfactory.nude_batch_shard.v1"
        or document.get("artifact_type") != "tournament_sample_set"
        or self_sha256 != _canonical_sha256(sealed)
        or not isinstance(samples, list)
        or not isinstance(ordered, list)
        or document.get("sample_count") != len(samples)
        or ordered != [sample.get("sample_id") for sample in samples]
    ):
        raise ValueError("nude shard contract is invalid")
    records = [
        {
            "sample_id": sample.get("sample_id"),
            "source_sha256": sample.get("source_sha256"),
            "image_path": sample.get("source_path_readonly"),
        }
        for sample in samples
    ]
    binding = {
        "schema_version": "maskfactory.nude_shard_binding.v1",
        "shard_self_sha256": self_sha256,
        "batch_lane": document.get("batch_lane"),
        "batch_number": document.get("batch_number"),
        "platform": document.get("platform"),
        "sample_count": len(samples),
    }
    return records, binding


def _validate_prompts_and_thresholds(
    prompts: tuple[str, ...], box_threshold: float, text_threshold: float, device: str
) -> None:
    if not all(isinstance(prompt, str) and prompt.strip() for prompt in prompts) or len(
        set(prompts)
    ) != len(prompts):
        raise ValueError("prompts must be unique non-empty strings")
    if not 0 <= box_threshold <= 1 or not 0 <= text_threshold <= 1:
        raise ValueError("thresholds must be in 0..1")
    if device not in {"cpu", "cuda"}:
        raise ValueError("device must be exactly cpu or cuda")


def _predict_one(
    model: object,
    image_path: Path,
    prompts: tuple[str, ...],
    *,
    box_threshold: float,
    text_threshold: float,
    device: str,
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
            device=device,
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
    device: str = "cpu",
) -> dict:
    _validate_prompts_and_thresholds(prompts, box_threshold, text_threshold, device)
    package = Path(groundingdino.__file__).resolve().parent
    config = package / "config" / "GroundingDINO_SwinT_OGC.py"
    with contextlib.redirect_stdout(sys.stderr):
        model = load_model(str(config), str(checkpoint), device=device)
    try:
        image_size, proposals = _predict_one(
            model,
            image_path,
            prompts,
            box_threshold=box_threshold,
            text_threshold=text_threshold,
            device=device,
        )
    finally:
        del model
    return {
        "protocol_version": 1,
        "schema_version": "1.0.0",
        "checkpoint_sha256": _sha256(checkpoint),
        "source_revision": SOURCE_REVISION,
        "device_type": device,
        "device": platform.processor() or "cpu" if device == "cpu" else "cuda",
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
    device: str = "cpu",
    checkpoint_path: Path | None = None,
    input_binding: Mapping[str, object] | None = None,
) -> dict:
    """Run up to 256 hash-bound images through one governed model load."""

    _validate_prompts_and_thresholds(prompts, box_threshold, text_threshold, device)
    if not 1 <= len(records) <= 256:
        raise ValueError("batch must contain 1..256 records")
    normalized_records = []
    seen = set()
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
        normalized_records.append(
            {
                "sample_id": sample_id,
                "source_sha256": source_sha256,
                "image_path": str(image_path),
            }
        )
    checkpoint_sha256 = _sha256(checkpoint)
    run_policy: dict[str, object] = {
        "checkpoint_sha256": checkpoint_sha256,
        "source_revision": SOURCE_REVISION,
        "device": device,
        "prompts": list(prompts),
        "box_threshold": box_threshold,
        "text_threshold": text_threshold,
        "records": normalized_records,
        "input_binding": dict(input_binding or {}),
    }
    run_policy_sha256 = _canonical_sha256(run_policy)
    outputs: list[dict] = []
    if checkpoint_path is not None and checkpoint_path.is_file():
        outputs = _load_checkpoint(
            checkpoint_path,
            run_policy_sha256=run_policy_sha256,
            records=normalized_records,
        )
    resumed_record_count = len(outputs)
    pending = normalized_records[resumed_record_count:]
    model_load_count = 0
    if pending:
        package = Path(groundingdino.__file__).resolve().parent
        config = package / "config" / "GroundingDINO_SwinT_OGC.py"
        with contextlib.redirect_stdout(sys.stderr):
            model = load_model(str(config), str(checkpoint), device=device)
        model_load_count = 1
        try:
            for record in pending:
                sample_id = str(record["sample_id"])
                source_sha256 = str(record["source_sha256"])
                image_path = Path(str(record["image_path"]))
                image_size, proposals = _predict_one(
                    model,
                    image_path,
                    prompts,
                    box_threshold=box_threshold,
                    text_threshold=text_threshold,
                    device=device,
                )
                outputs.append(
                    {
                        "sample_id": sample_id,
                        "source_sha256": source_sha256,
                        "image_size": image_size,
                        "proposals": proposals,
                    }
                )
                if checkpoint_path is not None:
                    _write_json_atomic(
                        checkpoint_path,
                        _checkpoint_document(
                            run_policy_sha256=run_policy_sha256,
                            planned_record_count=len(normalized_records),
                            records=outputs,
                        ),
                    )
        finally:
            del model
    result = {
        "protocol_version": 2,
        "schema_version": "maskfactory.groundingdino_batch.v1",
        "checkpoint_sha256": checkpoint_sha256,
        "source_revision": SOURCE_REVISION,
        "device_type": device,
        "device": platform.processor() or "cpu" if device == "cpu" else "cuda",
        "model_load_count": model_load_count,
        "resumed_record_count": resumed_record_count,
        "processed_record_count": len(pending),
        "checkpointing_enabled": checkpoint_path is not None,
        "run_policy_sha256": run_policy_sha256,
        "input_binding": dict(input_binding or {}),
        "record_count": len(outputs),
        "prompts": list(prompts),
        "box_threshold": box_threshold,
        "text_threshold": text_threshold,
        "authority": "proposal_boxes_only",
        "may_write_final_masks": False,
        "records": outputs,
    }
    if checkpoint_path is not None:
        if not checkpoint_path.is_file():
            _write_json_atomic(
                checkpoint_path,
                _checkpoint_document(
                    run_policy_sha256=run_policy_sha256,
                    planned_record_count=len(normalized_records),
                    records=outputs,
                ),
            )
        result["checkpoint_self_sha256"] = json.loads(checkpoint_path.read_text(encoding="utf-8"))[
            "self_sha256"
        ]
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
    inputs.add_argument("--nude-shard", type=Path)
    parser.add_argument("--prompts-json", required=True)
    parser.add_argument("--box-threshold", type=float, required=True)
    parser.add_argument("--text-threshold", type=float, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--checkpoint-path", type=Path)
    args = parser.parse_args()
    prompts = tuple(json.loads(args.prompts_json))
    if args.image is not None:
        if args.checkpoint_path is not None:
            raise ValueError("checkpoint-path is supported only for batch inputs")
        result = run(
            args.checkpoint,
            args.image,
            prompts,
            box_threshold=args.box_threshold,
            text_threshold=args.text_threshold,
            device=args.device,
        )
    elif args.images_manifest is not None:
        manifest = json.loads(args.images_manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != (
            "maskfactory.groundingdino_image_batch.v1"
        ):
            raise ValueError("batch manifest schema is invalid")
        records = manifest.get("records")
        if not isinstance(records, list):
            raise ValueError("batch manifest records are invalid")
        input_binding = {
            "schema_version": manifest["schema_version"],
            "manifest_sha256": _sha256(args.images_manifest),
            "record_count": len(records),
        }
        result = run_batch(
            args.checkpoint,
            records,
            prompts,
            box_threshold=args.box_threshold,
            text_threshold=args.text_threshold,
            device=args.device,
            checkpoint_path=args.checkpoint_path,
            input_binding=input_binding,
        )
    else:
        records, input_binding = _load_nude_shard(args.nude_shard)
        result = run_batch(
            args.checkpoint,
            records,
            prompts,
            box_threshold=args.box_threshold,
            text_threshold=args.text_threshold,
            device=args.device,
            checkpoint_path=args.checkpoint_path,
            input_binding=input_binding,
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
