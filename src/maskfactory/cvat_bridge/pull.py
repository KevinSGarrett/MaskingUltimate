"""Pull corrected CVAT masks/attributes, retain backup, then re-fuse and re-QA."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from ..derive import derive_package
from ..fusion.mapbuild import export_binaries, fuse_package
from ..io.png_strict import read_mask, write_binary_mask
from ..ontology import get_ontology
from ..qa.checks import run_format_integrity
from ..review_package import (
    refresh_review_package_derivations,
    snapshot_draft_baseline,
    update_package_workflow_status,
)
from ..state import persist_image_progress
from .client import DEFAULT_CONFIG, CvatApiError, CvatClient, load_cvat_config
from .labelmap import CvatLabelMap, decode_mask_rle
from .push import DEFAULT_TASK_RECORDS, _load_mapping


def pull_images(
    client: CvatClient,
    image_ids: tuple[str, ...],
    *,
    config_path: Path = DEFAULT_CONFIG,
    task_records: Path = DEFAULT_TASK_RECORDS,
    database: Path | None = None,
) -> tuple[int, ...]:
    config = load_cvat_config(config_path)
    _project_id, mapping = _load_mapping(config)
    selected = set(image_ids)
    records = []
    for path in sorted(Path(task_records).glob("task_*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("job_type", "instance_review") != "image_overview" and any(
            frame.get("image_id") in selected for frame in record.get("frames", [])
        ):
            records.append(record)
    if not records:
        raise CvatApiError("no pushed CVAT task records match the requested image IDs")
    completed = []
    for record in records:
        _pull_task(client, record, mapping)
        completed.append(int(record["task_id"]))
    if database is not None:
        _persist_corrected_images(records, database)
    return tuple(completed)


def _pull_task(client: CvatClient, record: dict[str, Any], mapping: CvatLabelMap) -> None:
    task_id = int(record["task_id"])
    annotations = client.request("GET", f"/api/tasks/{task_id}/annotations")
    shapes = annotations.get("shapes", []) if isinstance(annotations, dict) else []
    by_frame: dict[int, list[dict[str, Any]]] = {}
    for shape in shapes:
        if shape.get("type") != "mask":
            continue
        by_frame.setdefault(int(shape["frame"]), []).append(shape)
    backup = _export_backup(client, task_id)
    for frame_record in record["frames"]:
        package = Path(frame_record["package_root"])
        shape = (int(frame_record["height"]), int(frame_record["width"]))
        package_manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        snapshot_draft_baseline(
            package,
            image_id=str(package_manifest["image_id"]),
            instance_id=package.name if package.name.startswith("p") else "p0",
        )
        _seed_fusion_inputs(package)
        for name in frame_record.get("pushed_labels", []):
            _write_corrected(package, name, np.zeros(shape, dtype=np.uint8))
        attributes: dict[str, dict[str, str]] = {
            name: {"visibility": "not_visible", "ambiguous": "false", "notes": ""}
            for name in frame_record.get("pushed_labels", [])
        }
        for raw_shape in by_frame.get(int(frame_record["frame"]), []):
            name = mapping.ontology_name(int(raw_shape["label_id"]))
            mask = decode_mask_rle(raw_shape["points"], shape=shape)
            _write_corrected(package, name, mask)
            attributes[name] = _shape_attributes(raw_shape, name, mapping)
        _update_manifest_attributes(package, attributes)
        fuse_package(package)
        export_binaries(package)
        derive_package(package)
        qa_results = run_format_integrity(package)
        qa_path = package / "qa" / "cvat_pull_format.json"
        _write_json_atomic(
            qa_path,
            {
                "schema_version": "1.0.0",
                "trigger": "cvat_pull",
                "task_id": task_id,
                "results": [asdict(result) for result in qa_results],
            },
        )
        backup_path = package / "annotations" / "cvat_task_backup.zip"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_bytes(backup)
        refresh_review_package_derivations(package)
        update_package_workflow_status(package, "corrected")


def _persist_corrected_images(records: list[dict[str, Any]], database: Path) -> None:
    """Advance SQLite only after every recorded instance package reached corrected."""
    roots_by_image: dict[str, set[Path]] = {}
    for record in records:
        for frame in record.get("frames", []):
            roots_by_image.setdefault(str(frame["image_id"]), set()).add(
                Path(frame["package_root"]).resolve()
            )
    for image_id, recorded_roots in sorted(roots_by_image.items()):
        sample = next(iter(recorded_roots))
        if sample.parent.name == "instances":
            expected_roots = {
                path.parent.resolve()
                for path in sample.parent.glob("p*/manifest.json")
                if path.parent.name[1:].isdigit()
            }
        else:
            expected_roots = {sample}
        if recorded_roots != expected_roots:
            raise CvatApiError(
                f"CVAT pull records do not cover every package instance for {image_id}"
            )
        for root in expected_roots:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("workflow_status") != "corrected":
                raise CvatApiError(
                    f"CVAT pull did not correct every package instance for {image_id}"
                )
        persist_image_progress(database, image_id, "corrected")


def _seed_fusion_inputs(package: Path) -> None:
    export_binaries(package)
    part_dir = package / "annotations" / "part_masks"
    material_dir = package / "annotations" / "material_masks"
    part_dir.mkdir(parents=True, exist_ok=True)
    material_dir.mkdir(parents=True, exist_ok=True)
    ontology = get_ontology()
    for label in ontology.labels_for_map("part", enabled_only=True):
        source_dir = "protected" if label.id == 0 or label.mask_type == "protected_qa" else "masks"
        source = package / source_dir / f"{label.name}.png"
        write_binary_mask(part_dir / source.name, read_mask(source))
    for label in ontology.labels_for_map("material", enabled_only=True):
        source = package / "masks_material" / f"{label.name}.png"
        write_binary_mask(material_dir / source.name, read_mask(source))


def _write_corrected(package: Path, name: str, mask: np.ndarray) -> None:
    label = get_ontology().label(name, require_enabled=True)
    size = (mask.shape[1], mask.shape[0])
    if label.map == "part":
        target = package / "annotations" / "part_masks" / f"{name}.png"
    elif label.map == "material":
        target = package / "annotations" / "material_masks" / f"{name}.png"
    elif label.mask_type == "region_band":
        target = package / "masks_regions" / f"{name}.png"
    elif label.mask_type == "projected_amodal":
        target = package / "projected" / f"{name}.png"
    else:
        raise CvatApiError(f"CVAT may not author script-derived label {name!r}")
    write_binary_mask(target, mask, source_size=size)


def _shape_attributes(shape: dict[str, Any], name: str, mapping: CvatLabelMap) -> dict[str, str]:
    by_id = {
        int(attribute["spec_id"]): str(attribute["value"])
        for attribute in shape.get("attributes", [])
    }
    return {
        key: by_id.get(mapping.attribute_id(name, key), "")
        for key in ("visibility", "ambiguous", "notes")
    }


def _update_manifest_attributes(package: Path, attributes: dict[str, dict[str, str]]) -> None:
    path = package / "manifest.json"
    if not path.is_file():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    parts = manifest.get("parts", {})
    for name, values in attributes.items():
        if name not in parts or not isinstance(parts[name], dict):
            continue
        visibility = values["visibility"]
        if visibility:
            parts[name]["visibility"] = visibility
        parts[name]["notes"] = values["notes"]
        if values["ambiguous"].lower() == "true":
            parts[name]["visibility"] = "ambiguous_do_not_use"
        parts[name]["status"] = "human_corrected"
    _write_json_atomic(path, manifest)


def _export_backup(client: CvatClient, task_id: int) -> bytes:
    started = client.request("POST", f"/api/tasks/{task_id}/backup/export")
    if not isinstance(started, dict) or not started.get("rq_id"):
        raise CvatApiError(f"CVAT backup export did not return rq_id for task {task_id}")
    status = client.wait_request(str(started["rq_id"]), timeout=600)
    result_url = status.get("result_url")
    if not result_url:
        raise CvatApiError(f"CVAT backup request has no result_url for task {task_id}")
    result = client.request("GET", str(result_url), raw=True, timeout=300)
    if not isinstance(result, bytes) or not result.startswith(b"PK"):
        raise CvatApiError(f"CVAT backup for task {task_id} is not a ZIP")
    return result


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
