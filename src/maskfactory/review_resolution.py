"""Immutable human resolution of early semantic review routes."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .io.png_strict import read_mask, write_binary_mask


class ReviewResolutionError(ValueError):
    """A review resolution is absent, stale, or violates its authority contract."""


def create_s02_review_resolution(
    image_id: str,
    instance_id: str,
    reviewed_mask: Path,
    *,
    reviewer: str,
    decision: str,
    note: str,
    work_root: Path = Path("work"),
    images_root: Path = Path("data/images"),
    timestamp: str | None = None,
) -> Path:
    """Seal one Kevin-reviewed S02 mask against its exact queued terminal and model output."""
    _validate_identity(image_id, instance_id)
    if decision not in {"confirmed_valid", "corrected"}:
        raise ReviewResolutionError("decision must be confirmed_valid or corrected")
    if not reviewer.strip() or not note.strip():
        raise ReviewResolutionError("reviewer and review note are required")
    work_root = Path(work_root)
    queue_record = _queued_s02_record(work_root, image_id, instance_id)
    stage_dir = work_root / "instances" / instance_id / "s02" / image_id
    model_mask_path = stage_dir / "person_full_visible.png"
    if not model_mask_path.is_file():
        raise ReviewResolutionError("queued S02 model mask is missing")
    manifest_path = Path(images_root) / image_id / "manifest.json"
    manifest = _read_json(manifest_path, "source manifest")
    source = manifest.get("source", {})
    full_size = (int(source.get("source_width", 0)), int(source.get("source_height", 0)))
    if min(full_size) < 1:
        raise ReviewResolutionError("source manifest has invalid dimensions")
    reviewed = _strict_binary_mask(Path(reviewed_mask), full_size=full_size)
    model = _strict_binary_mask(model_mask_path, full_size=full_size)
    model_sha = _sha256(model_mask_path)
    reviewed_sha = _sha256(Path(reviewed_mask))
    if decision == "confirmed_valid" and reviewed_sha != model_sha:
        raise ReviewResolutionError("confirmed_valid requires the byte-identical queued model mask")
    if decision == "corrected" and np.array_equal(reviewed, model):
        raise ReviewResolutionError("corrected review mask must differ from the queued model mask")
    person_document = _read_json(
        work_root / "s01" / image_id / "person_bbox.json", "S01 person evidence"
    )
    persons = person_document.get("persons", ())
    index = int(instance_id[1:])
    if index >= len(persons) or int(persons[index].get("person_index", -1)) != index:
        raise ReviewResolutionError("S01 person evidence does not contain the requested instance")
    context_bbox = tuple(int(value) for value in persons[index]["context_bbox_xyxy"])
    _require_inside_context(reviewed, context_bbox)
    destination = _resolution_dir(work_root, image_id, instance_id)
    document = {
        "schema_version": "1.0.0",
        "stage": "S02",
        "image_id": image_id,
        "instance_id": instance_id,
        "config_hash": queue_record["config_hash"],
        "queue_timestamp": queue_record["ts"],
        "queue_error": queue_record["error"],
        "decision": decision,
        "reviewer": reviewer.strip(),
        "note": note.strip(),
        "reviewed_at": timestamp or datetime.now(UTC).isoformat(),
        "source_sha256": source.get("source_sha256"),
        "source_size": list(full_size),
        "context_bbox_xyxy": list(context_bbox),
        "base_model_mask_sha256": model_sha,
        "reviewed_mask_sha256": reviewed_sha,
        "model_ratio_qc_remains_failed": True,
        "pipeline_gate_satisfied_by": "human_semantic_review",
        "authority": "human_semantic_review",
    }
    if destination.exists():
        existing = _read_json(destination / "resolution.json", "existing S02 resolution")
        stable = {key: value for key, value in document.items() if key != "reviewed_at"}
        existing_stable = {key: value for key, value in existing.items() if key != "reviewed_at"}
        if stable == existing_stable and _sha256(destination / "reviewed_mask.png") == reviewed_sha:
            return destination / "resolution.json"
        raise ReviewResolutionError("an immutable different S02 review resolution already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.mkdir()
        (temporary / "reviewed_mask.png").write_bytes(Path(reviewed_mask).read_bytes())
        (temporary / "resolution.json").write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            for child in temporary.iterdir():
                child.unlink(missing_ok=True)
            temporary.rmdir()
    return destination / "resolution.json"


def apply_s02_review_resolution(
    *,
    work_root: Path,
    image_id: str,
    instance_id: str,
    output_dir: Path,
    config_hash: str,
    person_bbox_xyxy: tuple[int, int, int, int],
    full_size: tuple[int, int],
) -> dict[str, Any] | None:
    """Apply matching human authority after fresh model inference reproduces the queued mask."""
    path = _resolution_dir(Path(work_root), image_id, instance_id)
    if not path.is_dir():
        return None
    document = _read_json(path / "resolution.json", "S02 review resolution")
    if document.get("config_hash") != config_hash:
        raise ReviewResolutionError("S02 review resolution config hash is stale")
    model_mask_path = Path(output_dir) / "person_full_visible.png"
    if _sha256(model_mask_path) != document.get("base_model_mask_sha256"):
        raise ReviewResolutionError("fresh S02 model mask differs from the reviewed base mask")
    reviewed_path = path / "reviewed_mask.png"
    if _sha256(reviewed_path) != document.get("reviewed_mask_sha256"):
        raise ReviewResolutionError("S02 reviewed mask hash mismatch")
    reviewed = _strict_binary_mask(reviewed_path, full_size=full_size)
    _require_inside_context(reviewed, tuple(document["context_bbox_xyxy"]))
    write_binary_mask(model_mask_path, reviewed, source_size=full_size)
    left, top, right, bottom = person_bbox_xyxy
    bbox_area = (right - left) * (bottom - top)
    area = int(np.count_nonzero(reviewed))
    ratio = area / bbox_area if bbox_area else 0.0
    metrics_path = Path(output_dir) / "silhouette_metrics.json"
    metrics = _read_json(metrics_path, "fresh S02 metrics")
    metrics.update(
        {
            "model_qc_passed": bool(metrics.get("qc_passed")),
            "model_silhouette_bbox_ratio": metrics.get("silhouette_bbox_ratio"),
            "area_px": area,
            "silhouette_bbox_ratio": ratio,
            "qc_passed": True,
            "human_review_passed": True,
            "review_decision": document["decision"],
            "reviewer": document["reviewer"],
        }
    )
    metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    resolution_bytes = (path / "resolution.json").read_bytes()
    (Path(output_dir) / "s02_review_resolution.json").write_bytes(resolution_bytes)
    return {
        "decision": document["decision"],
        "reviewer": document["reviewer"],
        "silhouette_bbox_ratio": ratio,
        "resolution_sha256": hashlib.sha256(resolution_bytes).hexdigest(),
    }


def s02_review_refresh_required(
    work_root: Path, image_id: str, instance_id: str, output_dir: Path
) -> bool:
    """Force cached S02 exactly when a sealed resolution is not reflected in its output."""
    resolution = _resolution_dir(Path(work_root), image_id, instance_id) / "resolution.json"
    if not resolution.is_file():
        return False
    applied = Path(output_dir) / "s02_review_resolution.json"
    return not applied.is_file() or _sha256(applied) != _sha256(resolution)


def _resolution_dir(work_root: Path, image_id: str, instance_id: str) -> Path:
    return Path(work_root) / "review_resolutions" / image_id / instance_id / "S02"


def _queued_s02_record(work_root: Path, image_id: str, instance_id: str) -> dict[str, Any]:
    path = Path(work_root) / "queues" / "review_queue.jsonl"
    if not path.is_file():
        raise ReviewResolutionError("review queue is missing")
    matches = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if (
            record.get("image_id") == image_id
            and record.get("instance_id") == instance_id
            and record.get("stage") == "S02"
            and record.get("terminal_outcome") == "needs_review"
        ):
            matches.append(record)
    if len(matches) != 1:
        raise ReviewResolutionError("expected exactly one queued S02 review route")
    return matches[0]


def _strict_binary_mask(path: Path, *, full_size: tuple[int, int]) -> np.ndarray:
    with Image.open(path) as opened:
        if opened.format != "PNG" or opened.mode != "L" or opened.size != full_size:
            raise ReviewResolutionError("review mask must be native-size mode-L PNG")
    mask = read_mask(path)
    if mask.dtype != np.uint8 or not set(np.unique(mask).tolist()).issubset({0, 255}):
        raise ReviewResolutionError("review mask must be strict uint8 {0,255}")
    if not np.any(mask):
        raise ReviewResolutionError("review mask cannot be empty")
    return mask


def _require_inside_context(mask: np.ndarray, bbox: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = bbox
    inside = np.zeros(mask.shape, dtype=bool)
    inside[top:bottom, left:right] = True
    if np.any((mask > 0) & ~inside):
        raise ReviewResolutionError("review mask has pixels outside the S01 context crop")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewResolutionError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(document, dict):
        raise ReviewResolutionError(f"{label} must be a JSON object")
    return document


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_identity(image_id: str, instance_id: str) -> None:
    if not image_id.startswith("img_") or not image_id[4:].isalnum():
        raise ReviewResolutionError("image_id must be a safe img_* identifier")
    if not instance_id.startswith("p") or not instance_id[1:].isdigit():
        raise ReviewResolutionError("instance_id must be pN")
