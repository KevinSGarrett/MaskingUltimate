"""Fail-closed body_parts_v2 CVAT pull and manifest review staging."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from ..io.hashing import sha256_file
from ..io.png_strict import write_binary_mask
from ..ontology_v2_manifest import (
    V2_NULL_MASK_STATES,
    V2_VISIBLE_STATES,
    require_valid_v2_manifest,
)
from ..qa.metrics import component_count, mask_bbox
from .client import CvatClient
from .labelmap import decode_mask_rle
from .pull import _export_backup
from .v2_common import (
    DEFAULT_V2_CONFIG,
    V2_ATTRIBUTE_NAMES,
    V2_ONTOLOGY_VERSION,
    CvatV2Error,
    V2CvatLabelMap,
    canonical_v2_state,
    load_v2_cvat_config,
    load_v2_mapping,
    v2_part_names,
)

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class V2ReviewedLabel:
    visibility: str
    notes: str
    mask: np.ndarray | None
    ambiguity: np.ndarray | None


@dataclass(frozen=True)
class V2ReviewedFrame:
    labels: dict[str, V2ReviewedLabel]
    width: int
    height: int


def pull_v2_images(
    client: CvatClient,
    image_ids: tuple[str, ...],
    *,
    config_path: Path | str = DEFAULT_V2_CONFIG,
    task_records: Path | str | None = None,
) -> tuple[int, ...]:
    config = load_v2_cvat_config(config_path)
    project_id, mapping = load_v2_mapping(config)
    records_root = (
        Path(config["_task_records_dir"]) if task_records is None else Path(task_records).resolve()
    )
    if records_root.resolve() == (ROOT / "data" / "cvat" / "tasks").resolve():
        raise CvatV2Error("CVAT v2 pull refuses v1 task-record storage")
    selected = set(image_ids)
    records = []
    for path in sorted(records_root.glob("task_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CvatV2Error(f"cannot load CVAT v2 task record {path}: {exc}") from exc
        if (
            isinstance(record, dict)
            and record.get("ontology_version") == V2_ONTOLOGY_VERSION
            and record.get("job_type") == "v2_instance_review"
            and any(frame.get("image_id") in selected for frame in record.get("frames", []))
        ):
            records.append(record)
    if not records:
        raise CvatV2Error("no isolated CVAT v2 task records match the requested images")
    completed = []
    reviewer = str(config["project"]["assignee"])
    for record in records:
        if int(record.get("project_id", -1)) != project_id:
            raise CvatV2Error("CVAT v2 task record project differs from v2 mapping")
        task_id = int(record["task_id"])
        annotations = client.request("GET", f"/api/tasks/{task_id}/annotations")
        if not isinstance(annotations, dict):
            raise CvatV2Error(f"CVAT v2 task {task_id} returned invalid annotations")
        backup = _export_backup(client, task_id)
        _pull_v2_task(record, mapping, annotations, reviewer=reviewer, backup=backup)
        completed.append(task_id)
    return tuple(completed)


def _pull_v2_task(
    record: Mapping[str, Any],
    mapping: V2CvatLabelMap,
    annotations: Mapping[str, Any],
    *,
    reviewer: str,
    backup: bytes,
    reviewed_at: str | None = None,
) -> tuple[dict[str, Any], ...]:
    frames = record.get("frames")
    if not isinstance(frames, list) or len(frames) != 1:
        raise CvatV2Error("CVAT v2 task must contain exactly one package frame")
    if annotations.get("tracks") not in (None, []):
        raise CvatV2Error("CVAT v2 pull rejects tracks; canonical PART review uses tags and masks")
    timestamp = reviewed_at or datetime.now(UTC).isoformat()
    reports = []
    for frame_record in frames:
        package = Path(str(frame_record["package_root"])).resolve()
        manifest_path = package / "manifest.json"
        before = manifest_path.read_bytes()
        expected = record.get("manifest_sha256_at_push")
        actual = hashlib.sha256(before).hexdigest()
        if actual != expected:
            raise CvatV2Error(
                f"CVAT v2 package changed after push; stale task pull refused: {package}"
            )
        reviewed = parse_v2_frame(
            annotations,
            mapping,
            frame=int(frame_record["frame"]),
            shape=(int(frame_record["height"]), int(frame_record["width"])),
        )
        reports.append(
            apply_v2_review(
                package,
                reviewed,
                task_id=int(record["task_id"]),
                reviewer=reviewer,
                reviewed_at=timestamp,
                raw_annotations=annotations,
                backup=backup,
            )
        )
    return tuple(reports)


def parse_v2_frame(
    annotations: Mapping[str, Any],
    mapping: V2CvatLabelMap,
    *,
    frame: int,
    shape: tuple[int, int],
) -> V2ReviewedFrame:
    height, width = shape
    if height < 1 or width < 1:
        raise CvatV2Error("CVAT v2 frame dimensions must be positive")
    tags = annotations.get("tags", [])
    shapes = annotations.get("shapes", [])
    if not isinstance(tags, list) or not isinstance(shapes, list):
        raise CvatV2Error("CVAT v2 annotations require tag and shape lists")
    state_by_name: dict[str, tuple[str, str]] = {}
    for tag in tags:
        if not isinstance(tag, Mapping):
            raise CvatV2Error("CVAT v2 tag must be an object")
        if int(tag.get("frame", -1)) != frame:
            raise CvatV2Error("CVAT v2 task contains a state tag on an unexpected frame")
        name = mapping.ontology_name(int(tag.get("label_id", -1)))
        if name in state_by_name:
            raise CvatV2Error(f"CVAT v2 label has duplicate state tags: {name}")
        values = _annotation_attributes(tag, mapping, name)
        state = canonical_v2_state(values["visibility"])
        review_complete = values["review_complete"].lower()
        if review_complete not in {"true", "false"}:
            raise CvatV2Error(f"CVAT v2 review_complete is invalid for {name}")
        if review_complete != "true" or state == "unreviewed_for_v2":
            raise CvatV2Error(f"CVAT v2 export blocked: {name} is not explicitly reviewed")
        state_by_name[name] = (state, values["notes"])
    expected_names = set(v2_part_names())
    missing_tags = sorted(expected_names - set(state_by_name))
    if missing_tags:
        raise CvatV2Error("CVAT v2 export blocked; missing state tags: " + ", ".join(missing_tags))
    extra_tags = sorted(set(state_by_name) - expected_names)
    if extra_tags:
        raise CvatV2Error("CVAT v2 export contains unknown labels: " + ", ".join(extra_tags))

    masks_by_name: dict[str, np.ndarray] = {}
    for raw_shape in shapes:
        if not isinstance(raw_shape, Mapping):
            raise CvatV2Error("CVAT v2 shape must be an object")
        if int(raw_shape.get("frame", -1)) != frame:
            raise CvatV2Error("CVAT v2 task contains a mask on an unexpected frame")
        if raw_shape.get("type") != "mask":
            raise CvatV2Error("CVAT v2 pull accepts mask shapes only")
        if raw_shape.get("attributes") not in (None, []):
            raise CvatV2Error("CVAT v2 state attributes must live on the unique state tag")
        name = mapping.ontology_name(int(raw_shape.get("label_id", -1)))
        decoded = decode_mask_rle(raw_shape.get("points", []), shape=shape)
        if not np.any(decoded):
            raise CvatV2Error(f"CVAT v2 mask is empty: {name}")
        previous = masks_by_name.get(name)
        masks_by_name[name] = decoded if previous is None else np.maximum(previous, decoded)

    reviewed: dict[str, V2ReviewedLabel] = {}
    regular_masks: dict[str, np.ndarray] = {}
    for name in v2_part_names():
        state, notes = state_by_name[name]
        mask = masks_by_name.get(name)
        if state in V2_VISIBLE_STATES and mask is None:
            raise CvatV2Error(f"CVAT v2 export blocked: visible mask absent for {name}")
        if state in V2_NULL_MASK_STATES and mask is not None:
            raise CvatV2Error(f"CVAT v2 export blocked: null-mask state contains mask for {name}")
        if state == "ambiguous_do_not_use":
            if mask is None:
                raise CvatV2Error(f"CVAT v2 ambiguity state requires an ignore region: {name}")
            if not notes.strip():
                raise CvatV2Error(f"CVAT v2 ambiguity state requires a specific note: {name}")
            reviewed[name] = V2ReviewedLabel(state, notes, None, mask)
            continue
        if state in {"not_applicable", "occluded_by_clothing"} and not notes.strip():
            raise CvatV2Error(f"CVAT v2 state {state} requires human evidence in notes: {name}")
        regular = mask if state in V2_VISIBLE_STATES or state == "occluded" else None
        if regular is not None:
            regular_masks[name] = regular
        reviewed[name] = V2ReviewedLabel(state, notes, regular, None)
    _require_atomic_exclusivity(regular_masks)
    return V2ReviewedFrame(reviewed, width, height)


def _annotation_attributes(
    annotation: Mapping[str, Any], mapping: V2CvatLabelMap, name: str
) -> dict[str, str]:
    raw = annotation.get("attributes", [])
    if not isinstance(raw, list):
        raise CvatV2Error(f"CVAT v2 attributes are invalid for {name}")
    by_id: dict[int, str] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise CvatV2Error(f"CVAT v2 attribute is invalid for {name}")
        try:
            spec_id = int(item["spec_id"])
            value = str(item["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CvatV2Error(f"CVAT v2 attribute is invalid for {name}") from exc
        if spec_id in by_id:
            raise CvatV2Error(f"CVAT v2 attribute is duplicated for {name}")
        by_id[spec_id] = value
    expected = {mapping.attribute_id(name, key): key for key in V2_ATTRIBUTE_NAMES}
    if set(by_id) != set(expected):
        raise CvatV2Error(f"CVAT v2 attributes are incomplete or unknown for {name}")
    return {key: by_id[attribute_id] for attribute_id, key in expected.items()}


def _require_atomic_exclusivity(masks: Mapping[str, np.ndarray]) -> None:
    owner: np.ndarray | None = None
    for name, mask in masks.items():
        binary = mask.astype(bool)
        if owner is None:
            owner = np.zeros(binary.shape, dtype=bool)
        if np.any(owner & binary):
            raise CvatV2Error(f"CVAT v2 atomic masks overlap at export: {name}")
        owner |= binary


def apply_v2_review(
    package: Path,
    reviewed: V2ReviewedFrame,
    *,
    task_id: int,
    reviewer: str,
    reviewed_at: str,
    raw_annotations: Mapping[str, Any],
    backup: bytes,
) -> dict[str, Any]:
    package = Path(package).resolve()
    manifest_path = package / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CvatV2Error(f"cannot load CVAT v2 package manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise CvatV2Error("CVAT v2 package manifest root must be an object")
    require_valid_v2_manifest(manifest)
    if manifest.get("mask_ontology_version") != V2_ONTOLOGY_VERSION:
        raise CvatV2Error("CVAT v2 pull refuses a non-v2 package")
    if (
        int(manifest["source"]["source_width"]) != reviewed.width
        or int(manifest["source"]["source_height"]) != reviewed.height
    ):
        raise CvatV2Error("CVAT v2 reviewed frame dimensions differ from manifest")

    stage = package / "annotations" / f".cvat_v2_stage_{uuid.uuid4().hex}"
    staged: dict[str, tuple[Path, str]] = {}
    try:
        for name, label in reviewed.labels.items():
            array = label.ambiguity if label.ambiguity is not None else label.mask
            if array is None:
                continue
            kind = "ambiguity" if label.ambiguity is not None else "part_masks"
            relative = f"annotations/cvat_v2/{kind}/{name}.png"
            output = stage / kind / f"{name}.png"
            write_binary_mask(output, array, source_size=(reviewed.width, reviewed.height))
            staged[name] = (output, relative)

        result = json.loads(json.dumps(manifest))
        files = result.get("files")
        if not isinstance(files, dict):
            raise CvatV2Error("CVAT v2 manifest files authority is missing")
        for relative in list(files):
            if relative.startswith("annotations/cvat_v2/part_masks/") or relative.startswith(
                "annotations/cvat_v2/ambiguity/"
            ):
                del files[relative]
        for name, label in reviewed.labels.items():
            entry = result["parts"][name]
            entry["visibility"] = label.visibility
            entry["status"] = "human_corrected"
            entry["notes"] = label.notes
            entry["review_authority"] = {
                "reviewed": True,
                "reviewer": reviewer,
                "reviewed_at": reviewed_at,
                "source": "human_review",
                "ontology_version": V2_ONTOLOGY_VERSION,
            }
            if label.mask is not None:
                staged_path, relative = staged[name]
                digest = sha256_file(staged_path)
                entry["mask_file"] = relative
                entry["mask_sha256"] = digest
                entry["mask_area_px"] = int(np.count_nonzero(label.mask))
                bbox = mask_bbox(label.mask)
                entry["mask_bbox"] = list(bbox) if bbox is not None else None
                entry["components"] = component_count(label.mask)
                entry.pop("ambiguity_file", None)
                entry.pop("ambiguity_sha256", None)
                files[relative] = digest
            elif label.ambiguity is not None:
                staged_path, relative = staged[name]
                digest = sha256_file(staged_path)
                entry["mask_file"] = None
                entry["mask_sha256"] = None
                entry["mask_area_px"] = 0
                entry["mask_bbox"] = None
                entry["components"] = 0
                entry["ambiguity_file"] = relative
                entry["ambiguity_sha256"] = digest
                files[relative] = digest
            else:
                entry["mask_file"] = None
                entry["mask_sha256"] = None
                entry["mask_area_px"] = 0
                entry["mask_bbox"] = None
                entry["components"] = 0
                entry.pop("ambiguity_file", None)
                entry.pop("ambiguity_sha256", None)
        result["reviewed_ontology_version"] = V2_ONTOLOGY_VERSION
        result["workflow_status"] = "corrected"
        result["workflow_updated_at"] = reviewed_at
        require_valid_v2_manifest(result)

        audit = package / "annotations" / "cvat_v2" / "audit"
        audit.mkdir(parents=True, exist_ok=True)
        manifest_backup = audit / f"task_{task_id}_manifest_before.json"
        raw_path = audit / f"task_{task_id}_annotations.json"
        zip_path = audit / f"task_{task_id}_backup.zip"
        for path in (manifest_backup, raw_path, zip_path):
            if path.exists():
                raise CvatV2Error(f"CVAT v2 audit artifact already exists: {path}")
        manifest_backup.write_bytes(manifest_path.read_bytes())
        raw_path.write_text(
            json.dumps(raw_annotations, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        zip_path.write_bytes(backup)
        for staged_path, relative in staged.values():
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_path, target)
        _write_json_atomic(manifest_path, result)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return {
        "schema_version": "1.0.0",
        "task_id": task_id,
        "image_id": result["image_id"],
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "ontology_version": V2_ONTOLOGY_VERSION,
        "reviewed_label_count": 65,
        "visible_mask_count": sum(label.mask is not None for label in reviewed.labels.values()),
        "ambiguity_region_count": sum(
            label.ambiguity is not None for label in reviewed.labels.values()
        ),
        "workflow_status": "corrected",
        "gold_approved": False,
    }


def _write_json_atomic(path: Path, document: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
