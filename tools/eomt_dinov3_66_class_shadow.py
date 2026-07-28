"""Run a hash-bound, non-authoritative EoMT-DINOv3 66-class GPU shadow check."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

import numpy as np
import torch
import yaml
from PIL import Image
from transformers import AutoImageProcessor, EomtDinov3Config, EomtDinov3ForUniversalSegmentation

ROOT = Path(__file__).resolve().parents[1]


class ShadowBindingError(RuntimeError):
    """The sealed shadow binding or its admission conditions are invalid."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _self_hash(value: dict[str, Any]) -> str:
    copy = dict(value)
    copy.pop("self_sha256", None)
    return hashlib.sha256(_canonical(copy)).hexdigest()


def _relative_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise ShadowBindingError(f"binding path escapes project root: {value}") from exc
    return path


def _read_binding(binding_path: Path) -> dict[str, Any]:
    path = binding_path.resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise ShadowBindingError("binding is outside the project root") from exc
    binding = json.loads(path.read_text(encoding="utf-8"))
    if binding.get("schema_version") != "maskfactory.eomt_dinov3_66_class_shadow_binding.v1":
        raise ShadowBindingError("unexpected binding schema")
    if binding.get("self_sha256") != _self_hash(binding):
        raise ShadowBindingError("binding self hash drift")
    return binding


def _verify_file(spec: dict[str, str], label: str) -> Path:
    path = _relative_path(spec["path"])
    if not path.is_file():
        raise ShadowBindingError(f"{label} is missing: {spec['path']}")
    if _sha256(path) != spec["sha256"]:
        raise ShadowBindingError(f"{label} hash drift: {spec['path']}")
    return path


def _verify_runtime(binding: dict[str, Any]) -> None:
    runtime = binding["runtime"]
    expected_python = runtime["python_executable"]
    if sys.executable != expected_python:
        raise ShadowBindingError(
            f"wrong interpreter: expected {expected_python}, observed {sys.executable}"
        )
    receipt_path = _verify_file(runtime["clean_closure_receipt"], "clean closure receipt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("self_sha256") != runtime["clean_closure_receipt_self_sha256"]:
        raise ShadowBindingError("clean closure receipt self hash drift")
    expected_status = runtime.get("clean_closure_pass_status")
    if expected_status:
        if receipt.get("status") != expected_status:
            raise ShadowBindingError("clean closure receipt status is not the bound pass status")
    elif receipt.get("result") != "pass":
        raise ShadowBindingError("clean closure receipt is not a pass")


def _verify_admission() -> dict[str, Any]:
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "0":
        raise ShadowBindingError("CUDA_VISIBLE_DEVICES must be exactly 0")
    gpu = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip().splitlines()
    if len(gpu) != 1 or "NVIDIA RTX 6000 Ada Generation" not in gpu[0] or "49140 MiB" not in gpu[0]:
        raise ShadowBindingError(f"unexpected GPU inventory: {gpu}")
    processes = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    if processes:
        raise ShadowBindingError("GPU has pre-existing compute processes")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ShadowBindingError("exactly one CUDA device is required")
    if "NVIDIA RTX 6000 Ada Generation" not in torch.cuda.get_device_name(0):
        raise ShadowBindingError("torch CUDA device does not match the binding")
    return {"nvidia_smi": gpu[0], "torch_device": torch.cuda.get_device_name(0)}


def _verify_contract_and_inputs(binding: dict[str, Any]) -> tuple[Path, Path, list[str]]:
    code_path = _verify_file(binding["code"], "shadow tool")
    if code_path.resolve() != Path(__file__).resolve():
        raise ShadowBindingError("executed shadow tool differs from the bound tool")
    for filename, spec in binding["snapshot"].items():
        if Path(spec["path"]).name != filename:
            raise ShadowBindingError(f"snapshot filename mismatch: {filename}")
        _verify_file(spec, f"snapshot {filename}")
    fixture = _verify_file(binding["fixture"], "governed fixture")
    target = binding["target_head"]
    training_config = _verify_file(target["training_config"], "EoMT training config")
    _verify_file(target["v2_contract"], "body-parts v2 contract")
    ontology_path = _verify_file(target["ontology"], "body-parts v2 ontology")
    training = yaml.safe_load(training_config.read_text(encoding="utf-8"))
    configured_target = training.get("target_head", {})
    if (
        training.get("lifecycle_state") != "installed"
        or training.get("authority") != "trainable_shadow_challenger_only"
        or training.get("pretraining", {}).get("maskfactory_label_authority") is not False
        or configured_target.get("ontology_version") != "body_parts_v2"
        or configured_target.get("class_count") != 66
        or configured_target.get("class_names_sha256") != target["class_names_sha256"]
        or configured_target.get("ignore_index") != 255
        or configured_target.get("initialization") != "random_new_segmentation_head"
        or training.get("selection", {}).get("active") is not None
        or training.get("selection", {}).get("rollback") is not None
        or training.get("selection", {}).get("pretraining_output_may_author_gold") is not False
    ):
        raise ShadowBindingError("bound 66-class training contract drift")
    ontology = yaml.safe_load(ontology_path.read_text(encoding="utf-8"))
    class_names = [
        label["name"]
        for label in sorted(
            [label for label in ontology["labels"] if label.get("map") == "part" and label.get("id") is not None],
            key=lambda label: int(label["id"]),
        )
    ]
    if (
        class_names != target["class_names"]
        or len(class_names) != 66
        or hashlib.sha256(json.dumps(class_names, separators=(",", ":")).encode()).hexdigest()
        != target["class_names_sha256"]
    ):
        raise ShadowBindingError("bound body-parts v2 vocabulary drift")
    return _relative_path(binding["model_directory"]), fixture, class_names


def _head_hash(model: EomtDinov3ForUniversalSegmentation) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.class_predictor.state_dict().items()):
        digest.update(name.encode("utf-8"))
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def _write_receipt(path: Path, document: dict[str, Any]) -> None:
    document["self_sha256"] = _self_hash(document)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _failure_document(binding: dict[str, Any] | None, error: BaseException) -> dict[str, Any]:
    return {
        "schema_version": "maskfactory.eomt_dinov3_66_class_shadow_failure.v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "result": "failure",
        "binding_self_sha256": None if binding is None else binding.get("self_sha256"),
        "error_type": type(error).__name__,
        "error": str(error),
        "traceback": traceback.format_exc(),
        "authority": {
            "shadow_only": True,
            "may_author_gold": False,
            "promotion_claimed": False,
            "semantic_mask_claimed": False,
        },
    }


def run(binding_path: Path) -> dict[str, Any]:
    binding: dict[str, Any] | None = None
    failure_path: Path | None = None
    try:
        binding = _read_binding(binding_path)
        outputs = binding["outputs"]
        success_path = _relative_path(outputs["success_receipt"])
        failure_path = _relative_path(outputs["failure_receipt"])
        if success_path.exists() or failure_path.exists():
            raise ShadowBindingError("terminal receipt already exists; binding is single-use")
        if success_path.parent.exists() and not success_path.parent.is_dir():
            raise ShadowBindingError("shadow output parent is not a directory")
        success_path.parent.mkdir(parents=True, exist_ok=True)
        _verify_runtime(binding)
        admission = _verify_admission()
        model_directory, fixture_path, class_names = _verify_contract_and_inputs(binding)
        torch.manual_seed(binding["execution"]["seed"])
        torch.cuda.manual_seed_all(binding["execution"]["seed"])
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        processor = AutoImageProcessor.from_pretrained(model_directory, local_files_only=True)
        config = EomtDinov3Config.from_pretrained(model_directory, local_files_only=True)
        config.id2label = {index: name for index, name in enumerate(class_names)}
        config.label2id = {name: index for index, name in enumerate(class_names)}
        if config.num_labels != 66:
            raise ShadowBindingError("target config did not resolve to 66 labels")
        started = time.perf_counter()
        model = EomtDinov3ForUniversalSegmentation.from_pretrained(
            model_directory,
            config=config,
            local_files_only=True,
            ignore_mismatched_sizes=True,
            dtype=torch.float16,
        ).cuda().eval()
        if model.class_predictor.out_features != 67:
            raise ShadowBindingError("target classifier does not include 66 labels plus no-object")
        random_head_sha256 = _head_hash(model)
        torch.cuda.synchronize()
        load_seconds = time.perf_counter() - started
        with Image.open(fixture_path) as opened:
            image = opened.convert("RGB")
        inputs = processor(images=image, return_tensors="pt")
        inputs = {
            key: (value.cuda().half() if value.is_floating_point() else value.cuda())
            if isinstance(value, torch.Tensor)
            else value
            for key, value in inputs.items()
        }
        calls = []
        for _ in range(2):
            started = time.perf_counter()
            with torch.inference_mode():
                outputs = model(**inputs)
            torch.cuda.synchronize()
            processed = processor.post_process_panoptic_segmentation(
                outputs, target_sizes=[(image.height, image.width)]
            )[0]
            segmentation = np.asarray(processed["segmentation"].cpu(), dtype=np.int32)
            segments = [
                {
                    "id": int(record["id"]),
                    "label_id": int(record["label_id"]),
                    "score": round(float(record["score"]), 8),
                    "was_fused": bool(record.get("was_fused", False)),
                }
                for record in processed["segments_info"]
            ]
            if any(segment["label_id"] < 0 or segment["label_id"] >= 66 for segment in segments):
                raise ShadowBindingError("target output contains a label outside the 66-class head")
            payload = {
                "segmentation_sha256": hashlib.sha256(segmentation.tobytes()).hexdigest(),
                "segments": segments,
            }
            calls.append(
                {
                    "payload_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
                    "segment_count": len(segments),
                    "seconds": round(time.perf_counter() - started, 6),
                }
            )
        if len({call["payload_sha256"] for call in calls}) != 1:
            raise ShadowBindingError("shadow output is nondeterministic")
        document = {
            "schema_version": "maskfactory.eomt_dinov3_66_class_shadow_receipt.v1",
            "captured_at": datetime.now(UTC).isoformat(),
            "result": "structural_runtime_pass",
            "binding_self_sha256": binding["self_sha256"],
            "fixture": binding["fixture"],
            "snapshot": binding["snapshot"],
            "runtime": {
                "python": sys.executable,
                "torch": torch.__version__,
                "cuda": torch.version.cuda,
                "device": torch.cuda.get_device_name(0),
                "admission": admission,
                "precision": "float16",
                "load_seconds": round(load_seconds, 6),
                "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
            },
            "target_head": {
                "class_count": 66,
                "class_names_sha256": binding["target_head"]["class_names_sha256"],
                "pretrained_head_disposition": "discarded_coco_panoptic_head",
                "initialization": "random_new_segmentation_head",
                "classifier_out_features": model.class_predictor.out_features,
                "random_head_sha256": random_head_sha256,
            },
            "shadow_execution": {
                "repeats": 2,
                "deterministic": True,
                "calls": calls,
                "mask_artifact_written": False,
                "semantic_acceptance_evaluated": False,
            },
            "authority": {
                "lifecycle_state": "trainable_shadow_challenger_only",
                "shadow_only": True,
                "may_author_gold": False,
                "promotion_claimed": False,
                "semantic_mask_claimed": False,
                "visual_acceptance_claimed": False,
            },
        }
        _write_receipt(success_path, document)
        return document
    except BaseException as error:
        if failure_path is not None and not failure_path.exists():
            _write_receipt(failure_path, _failure_document(binding, error))
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        binding = _read_binding(args.binding)
        outputs = binding["outputs"]
        if _relative_path(outputs["success_receipt"]).exists() or _relative_path(outputs["failure_receipt"]).exists():
            raise ShadowBindingError("terminal receipt already exists; binding is single-use")
        _verify_runtime(binding)
        admission = _verify_admission()
        model_directory, fixture, class_names = _verify_contract_and_inputs(binding)
        print(json.dumps({"preflight": "pass", "binding_self_sha256": binding["self_sha256"], "admission": admission, "model_directory": str(model_directory.relative_to(ROOT)), "fixture": str(fixture.relative_to(ROOT)), "class_count": len(class_names)}, sort_keys=True))
        return 0
    print(json.dumps(run(args.binding), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
