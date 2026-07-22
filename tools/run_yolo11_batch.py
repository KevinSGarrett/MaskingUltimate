"""Resumable hash-bound YOLO11M person proposals for one governed nude shard."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


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


def _load_shard(path: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("nude shard is not an object")
    sealed = dict(document)
    self_sha256 = sealed.pop("self_sha256", None)
    samples = document.get("samples")
    ordered = document.get("ordered_sample_ids")
    lane = document.get("batch_lane")
    if (
        document.get("schema_version") != "maskfactory.nude_batch_shard.v1"
        or document.get("artifact_type") != "tournament_sample_set"
        or self_sha256 != _canonical_sha256(sealed)
        or not isinstance(lane, str)
        or not isinstance(samples, list)
        or not isinstance(ordered, list)
        or not 1 <= len(samples) <= 256
        or document.get("sample_count") != len(samples)
        or ordered != [sample.get("sample_id") for sample in samples]
        or len(ordered) != len(set(ordered))
    ):
        raise ValueError("nude shard contract is invalid")
    records = []
    for sample in samples:
        if not isinstance(sample, Mapping) or sample.get("source_role") != lane:
            raise ValueError("nude shard sample role is invalid")
        if lane == "reference_and_tournament_input" and (
            sample.get("annotation_ref") is not None
            or sample.get("source_labels") != []
            or sample.get("source_split") != "unsplit_reference"
        ):
            raise ValueError("reference shard inherited source truth")
        records.append(
            {
                "sample_id": sample.get("sample_id"),
                "source_sha256": sample.get("source_sha256"),
                "image_path": sample.get("source_path_readonly"),
            }
        )
    return records, {
        "schema_version": "maskfactory.nude_shard_binding.v1",
        "shard_self_sha256": self_sha256,
        "batch_lane": lane,
        "batch_number": document.get("batch_number"),
        "platform": document.get("platform"),
        "sample_count": len(samples),
    }


def _checkpoint(
    *, run_policy_sha256: str, planned: int, records: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "maskfactory.yolo11_person_batch_checkpoint.v1",
        "run_policy_sha256": run_policy_sha256,
        "planned_record_count": planned,
        "completed_record_count": len(records),
        "complete": len(records) == planned,
        "records": list(records),
    }
    return {**body, "self_sha256": _canonical_sha256(body)}


def _resume(
    path: Path, *, run_policy_sha256: str, records: Sequence[Mapping[str, object]]
) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("YOLO checkpoint is not an object")
    sealed = dict(document)
    self_sha256 = sealed.pop("self_sha256", None)
    completed = document.get("records")
    if (
        self_sha256 != _canonical_sha256(sealed)
        or document.get("schema_version") != "maskfactory.yolo11_person_batch_checkpoint.v1"
        or document.get("run_policy_sha256") != run_policy_sha256
        or document.get("planned_record_count") != len(records)
        or not isinstance(completed, list)
        or document.get("completed_record_count") != len(completed)
        or len(completed) > len(records)
        or document.get("complete") is not (len(completed) == len(records))
    ):
        raise ValueError("YOLO checkpoint policy mismatch")
    for index, output in enumerate(completed):
        if (
            not isinstance(output, dict)
            or output.get("sample_id") != records[index]["sample_id"]
            or output.get("source_sha256") != records[index]["source_sha256"]
            or not isinstance(output.get("proposals"), list)
        ):
            raise ValueError("YOLO checkpoint contiguous lineage mismatch")
    return list(completed)


def run_batch(
    *,
    checkpoint: Path,
    shard_path: Path,
    confidence_min: float = 0.5,
    device: str = "cpu",
    microbatch_size: int = 8,
    progress_path: Path | None = None,
) -> dict[str, Any]:
    if not 0 <= confidence_min <= 1:
        raise ValueError("confidence_min must be in 0..1")
    if device not in {"cpu", "0"}:
        raise ValueError("device must be exactly cpu or 0")
    if not 1 <= microbatch_size <= 32:
        raise ValueError("microbatch_size must be in 1..32")
    records, shard_binding = _load_shard(shard_path)
    normalized = []
    for record in records:
        sample_id = record.get("sample_id")
        source_sha256 = record.get("source_sha256")
        image_path_value = record.get("image_path")
        if not isinstance(sample_id, str) or not sample_id:
            raise ValueError("sample_id is invalid")
        if (
            not isinstance(source_sha256, str)
            or len(source_sha256) != 64
            or any(character not in "0123456789abcdef" for character in source_sha256)
        ):
            raise ValueError("source_sha256 is invalid")
        if not isinstance(image_path_value, str) or not image_path_value:
            raise ValueError("image_path is invalid")
        image_path = Path(image_path_value)
        if not image_path.is_file() or _sha256(image_path) != source_sha256:
            raise ValueError(f"source hash mismatch:{sample_id}")
        normalized.append(
            {"sample_id": sample_id, "source_sha256": source_sha256, "image_path": str(image_path)}
        )
    checkpoint_sha256 = _sha256(checkpoint)
    policy: dict[str, object] = {
        "provider": "yolo11m_person",
        "checkpoint_sha256": checkpoint_sha256,
        "shard_binding": shard_binding,
        "confidence_min": confidence_min,
        "device": device,
        "microbatch_size": microbatch_size,
        "records": normalized,
    }
    policy_sha256 = _canonical_sha256(policy)
    outputs: list[dict] = []
    if progress_path is not None and progress_path.is_file():
        outputs = _resume(progress_path, run_policy_sha256=policy_sha256, records=normalized)
    resumed = len(outputs)
    pending = normalized[resumed:]
    model_load_count = 0
    if pending:
        from ultralytics import YOLO

        model = YOLO(str(checkpoint), task="detect")
        model_load_count = 1
        for offset in range(0, len(pending), microbatch_size):
            batch = pending[offset : offset + microbatch_size]
            results = model.predict(
                source=[str(record["image_path"]) for record in batch],
                conf=confidence_min,
                imgsz=640,
                device=device,
                classes=[0],
                batch=microbatch_size,
                verbose=False,
            )
            if len(results) != len(batch):
                raise RuntimeError("YOLO batch result count mismatch")
            for record, result in zip(batch, results, strict=True):
                if result.boxes is None or result.names.get(0) != "person":
                    raise RuntimeError("YOLO person class contract mismatch")
                proposals = []
                for class_id, confidence, bbox in zip(
                    result.boxes.cls.tolist(),
                    result.boxes.conf.tolist(),
                    result.boxes.xyxy.tolist(),
                    strict=True,
                ):
                    if int(class_id) != 0:
                        raise RuntimeError("YOLO classes=[0] returned a non-person")
                    proposals.append(
                        {
                            "bbox_xyxy": [float(value) for value in bbox],
                            "confidence": float(confidence),
                            "label": "person",
                            "authority": "proposal_only",
                        }
                    )
                outputs.append(
                    {
                        "sample_id": record["sample_id"],
                        "source_sha256": record["source_sha256"],
                        "proposals": proposals,
                    }
                )
                if progress_path is not None:
                    _write_json_atomic(
                        progress_path,
                        _checkpoint(
                            run_policy_sha256=policy_sha256,
                            planned=len(normalized),
                            records=outputs,
                        ),
                    )
    report: dict[str, Any] = {
        "schema_version": "maskfactory.yolo11_person_batch.v1",
        "provider": "yolo11m_person",
        "provider_family": "yolo",
        "checkpoint_sha256": checkpoint_sha256,
        "shard_binding": shard_binding,
        "run_policy_sha256": policy_sha256,
        "record_count": len(outputs),
        "resumed_record_count": resumed,
        "processed_record_count": len(pending),
        "model_load_count": model_load_count,
        "confidence_min": confidence_min,
        "device": device,
        "microbatch_size": microbatch_size,
        "authority": "proposal_boxes_only",
        "may_write_final_masks": False,
        "records": outputs,
    }
    report["output_sha256"] = _canonical_sha256(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--nude-shard", type=Path, required=True)
    parser.add_argument("--confidence-min", type=float, default=0.5)
    parser.add_argument("--device", choices=("cpu", "0"), default="cpu")
    parser.add_argument("--microbatch-size", type=int, default=8)
    parser.add_argument("--progress-path", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run_batch(
                checkpoint=args.checkpoint,
                shard_path=args.nude_shard,
                confidence_min=args.confidence_min,
                device=args.device,
                microbatch_size=args.microbatch_size,
                progress_path=args.progress_path,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
