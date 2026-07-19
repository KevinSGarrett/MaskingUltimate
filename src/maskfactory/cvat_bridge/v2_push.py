"""Push migrated body_parts_v2 packages to isolated CVAT pilot tasks."""

from __future__ import annotations

import hashlib
import io
import json
import os
import urllib.parse
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

from ..io.png_strict import read_mask
from ..ontology_v2_manifest import require_valid_v2_manifest
from .client import CvatClient
from .labelmap import encode_mask_rle
from .v2_common import (
    DEFAULT_V2_CONFIG,
    V2_ATTRIBUTE_NAMES,
    V2_ONTOLOGY_VERSION,
    V2_REVIEW_STATES,
    CvatV2Error,
    V2CvatLabelMap,
    load_v2_cvat_config,
    load_v2_mapping,
    v2_alias_help_text,
    v2_part_names,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGES = ROOT / "data" / "packages"


@dataclass(frozen=True)
class V2ReviewInstance:
    image_id: str
    instance_id: str
    package_root: Path
    source: Path
    manifest: dict[str, Any]


def v2_task_description(instance: V2ReviewInstance) -> str:
    additions = ", ".join(instance.manifest["ontology_migration"]["added_labels"])
    return "\n".join(
        (
            "MaskFactory body_parts_v2 PILOT — Document 18 human review SOP.",
            "This is a separate v2 task. Never copy approval from an open body_parts_v1 task.",
            "Select exactly one visibility state and set review_complete=true for every canonical PART label 0..64.",
            "Character perspective is authoritative: left/right means the character's left/right, not the viewer's.",
            "Work at 400-800% for areola/nipple and pelvic boundaries; label exposed visible surface only.",
            "Areola excludes nipple; breast excludes both. Shaft excludes visible glans. Pelvic region excludes IDs 60-64.",
            "Clothing owns covered pixels: use occluded_by_clothing with no anatomy mask; never infer through fabric.",
            "If a boundary or scrotal side is not defensible, use ambiguous_do_not_use and draw only the ignore region.",
            "not_applicable requires human evidence. unreviewed_for_v2 can never be approved or exported.",
            f"Migrated additions start explicitly unreviewed: {additions}.",
            "Aliases are search/help only and must never be labels or exported manifest keys: "
            + v2_alias_help_text(),
            "Automatic masks are drafts only. This task cannot approve gold; normal QA and package approval remain required.",
        )
    )


def push_v2_images(
    client: CvatClient,
    image_ids: tuple[str, ...],
    *,
    config_path: Path | str = DEFAULT_V2_CONFIG,
    packages_root: Path | str = DEFAULT_PACKAGES,
    task_records: Path | str | None = None,
) -> tuple[int, ...]:
    config = load_v2_cvat_config(config_path)
    project_id, mapping = load_v2_mapping(config)
    from ..ontology_v2_inactive_gates import (
        OntologyV2InactiveGateError,
        require_inactive_v2_authority,
    )

    try:
        require_inactive_v2_authority(
            {
                "activation_status": "approved_design_not_active",
                "ontology_version": "body_parts_v2",
                "active_runtime_ontology": "body_parts_v1",
                "production_activation_performed": False,
                "pilot_complete": False,
                "kevin_pilot_sources_authorized": False,
                "mapping_authority": False,
            }
        )
    except OntologyV2InactiveGateError as exc:
        raise CvatV2Error(str(exc)) from exc
    records_root = (
        Path(config["_task_records_dir"]) if task_records is None else Path(task_records).resolve()
    )
    v1_records = (ROOT / "data" / "cvat" / "tasks").resolve()
    if records_root.resolve() == v1_records:
        raise CvatV2Error("CVAT v2 push refuses v1 task-record storage")
    assignee_id = _assignee_id(client, str(config["project"]["assignee"]))
    instances = [
        instance
        for image_id in image_ids
        for instance in _discover_v2_instances(Path(packages_root), image_id)
    ]
    if not instances:
        raise CvatV2Error("no migrated v2 package instances selected")
    task_ids = []
    for instance in instances:
        task_ids.append(
            _push_v2_instance(
                client,
                instance,
                project_id=project_id,
                project_name=str(config["project"]["name"]),
                assignee_id=assignee_id,
                mapping=mapping,
                config=config,
                task_records=records_root,
            )
        )
    return tuple(task_ids)


def _push_v2_instance(
    client: CvatClient,
    instance: V2ReviewInstance,
    *,
    project_id: int,
    project_name: str,
    assignee_id: int,
    mapping: V2CvatLabelMap,
    config: Mapping[str, Any],
    task_records: Path,
) -> int:
    task = client.request(
        "POST",
        "/api/tasks",
        payload={
            "name": f"MaskFactory_v2_review_{instance.image_id}_{instance.instance_id}",
            "description": v2_task_description(instance),
            "project_id": project_id,
            "assignee_id": assignee_id,
            "segment_size": 1,
            "overlap": 0,
        },
    )
    if not isinstance(task, dict) or "id" not in task:
        raise CvatV2Error("CVAT v2 task create response is invalid")
    task_id = int(task["id"])
    archive, frame_record = _review_archive(instance, config)
    upload = client.multipart(
        "POST",
        f"/api/tasks/{task_id}/data",
        fields={"image_quality": 100, "use_cache": "true", "sorting_method": "lexicographical"},
        files={
            "client_files[0]": (f"maskfactory_v2_task_{task_id}.zip", archive, "application/zip")
        },
        timeout=180,
    )
    if isinstance(upload, dict) and upload.get("rq_id"):
        client.wait_request(str(upload["rq_id"]), timeout=600)
    tags, shapes = initial_v2_annotations(instance, mapping)
    client.request(
        "PUT",
        f"/api/tasks/{task_id}/annotations",
        payload={"version": 0, "tags": tags, "shapes": shapes, "tracks": []},
        timeout=180,
    )
    frame_record["initial_states"] = {
        mapping.ontology_name(int(tag["label_id"])): _attribute_value(
            tag, mapping, mapping.ontology_name(int(tag["label_id"])), "visibility"
        )
        for tag in tags
    }
    manifest_bytes = (instance.package_root / "manifest.json").read_bytes()
    record = {
        "schema_version": "2.0.0",
        "ontology_version": V2_ONTOLOGY_VERSION,
        "job_type": "v2_instance_review",
        "task_id": task_id,
        "project_id": project_id,
        "project_name": project_name,
        "assignee_id": assignee_id,
        "manifest_sha256_at_push": hashlib.sha256(manifest_bytes).hexdigest(),
        "frames": [frame_record],
        "tag_count": len(tags),
        "shape_count": len(shapes),
        "v1_tasks_mutated": False,
    }
    _write_json_atomic(task_records / f"task_{task_id}.json", record)
    return task_id


def initial_v2_annotations(
    instance: V2ReviewInstance, mapping: V2CvatLabelMap
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parts = instance.manifest["parts"]
    tags: list[dict[str, Any]] = []
    shapes: list[dict[str, Any]] = []
    for name in v2_part_names():
        entry = parts[name]
        raw_state = entry.get("visibility")
        state = str(raw_state) if raw_state in V2_REVIEW_STATES else "unreviewed_for_v2"
        authority = entry.get("review_authority")
        complete = bool(
            isinstance(authority, Mapping)
            and authority.get("reviewed") is True
            and authority.get("source") == "human_review"
            and authority.get("ontology_version") == V2_ONTOLOGY_VERSION
        )
        notes = str(entry.get("notes", ""))
        tags.append(_state_tag(0, name, state, complete, notes, mapping))
        mask_path = _entry_mask_path(instance.package_root, entry, state)
        if mask_path is None:
            continue
        mask = read_mask(mask_path)
        if mask.shape != (
            int(instance.manifest["source"]["source_height"]),
            int(instance.manifest["source"]["source_width"]),
        ):
            raise CvatV2Error(f"CVAT v2 mask dimensions differ from source: {mask_path}")
        if not np.any(mask):
            raise CvatV2Error(f"CVAT v2 manifest references an empty mask: {mask_path}")
        shapes.append(
            {
                "type": "mask",
                "frame": 0,
                "label_id": mapping.cvat_id(name),
                "points": encode_mask_rle(mask),
                "occluded": state == "occluded",
                "outside": False,
                "z_order": 0,
                "rotation": 0,
                "attributes": [],
                "source": "auto",
            }
        )
    if len(tags) != 65:
        raise CvatV2Error("CVAT v2 push must create exactly one state tag per PART label")
    return tags, shapes


def _state_tag(
    frame: int,
    name: str,
    state: str,
    complete: bool,
    notes: str,
    mapping: V2CvatLabelMap,
) -> dict[str, Any]:
    values = {
        "visibility": state,
        "review_complete": "true" if complete else "false",
        "notes": notes,
    }
    return {
        "frame": frame,
        "label_id": mapping.cvat_id(name),
        "group": 0,
        "source": "auto",
        "attributes": [
            {"spec_id": mapping.attribute_id(name, attribute), "value": values[attribute]}
            for attribute in V2_ATTRIBUTE_NAMES
        ],
    }


def _attribute_value(
    annotation: Mapping[str, Any], mapping: V2CvatLabelMap, name: str, attribute: str
) -> str:
    wanted = mapping.attribute_id(name, attribute)
    values = {
        int(item["spec_id"]): str(item["value"])
        for item in annotation.get("attributes", [])
        if isinstance(item, Mapping) and "spec_id" in item and "value" in item
    }
    return values.get(wanted, "")


def _entry_mask_path(package: Path, entry: Mapping[str, Any], state: str) -> Path | None:
    key = "ambiguity_file" if state == "ambiguous_do_not_use" else "mask_file"
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise CvatV2Error(f"CVAT v2 {key} must be a relative path or null")
    path = _safe_package_path(package, value)
    if not path.is_file():
        raise CvatV2Error(f"CVAT v2 referenced mask is missing: {value}")
    return path


def _safe_package_path(package: Path, relative: str) -> Path:
    base = package.resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise CvatV2Error(f"CVAT v2 package path escapes root: {relative}") from exc
    return candidate


def _review_archive(
    instance: V2ReviewInstance, config: Mapping[str, Any]
) -> tuple[bytes, dict[str, Any]]:
    output = io.BytesIO()
    suffix = instance.source.suffix.lower()
    filename = f"000_{instance.image_id}_{instance.instance_id}{suffix}"
    crops = build_review_crops(instance, config)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, instance.source.read_bytes())
        related = f"related_images/{filename.replace('.', '_')}"
        context = []
        overlay = instance.package_root / "overlays" / "all_parts.png"
        if overlay.is_file():
            archive.writestr(f"{related}/all_parts_overlay.png", overlay.read_bytes())
            context.append("all_parts_overlay.png")
        for preset, crop in crops.items():
            archive.writestr(f"{related}/{preset}_review_crop.png", crop["png"])
            context.append(f"{preset}_review_crop.png")
    return output.getvalue(), {
        "frame": 0,
        "filename": filename,
        "image_id": instance.image_id,
        "instance_id": instance.instance_id,
        "package_root": str(instance.package_root.resolve()),
        "width": int(instance.manifest["source"]["source_width"]),
        "height": int(instance.manifest["source"]["source_height"]),
        "context": context,
        "review_crop_bboxes": {name: value["bbox_xyxy"] for name, value in crops.items()},
    }


def build_review_crops(
    instance: V2ReviewInstance, config: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    presets = config.get("review_crops")
    if not isinstance(presets, Mapping) or set(presets) != {"chest", "pelvic"}:
        raise CvatV2Error("CVAT v2 config requires exact chest/pelvic review crop presets")
    with Image.open(instance.source) as opened:
        source = opened.convert("RGB")
        width, height = source.size
        results = {}
        for name, raw in presets.items():
            if not isinstance(raw, Mapping):
                raise CvatV2Error(f"CVAT v2 crop preset is invalid: {name}")
            labels = raw.get("labels")
            fallback = raw.get("fallback_y_fraction")
            if not isinstance(labels, list) or not isinstance(fallback, list) or len(fallback) != 2:
                raise CvatV2Error(f"CVAT v2 crop preset is incomplete: {name}")
            union = np.zeros((height, width), dtype=bool)
            for label in labels:
                entry = instance.manifest["parts"].get(str(label), {})
                if not isinstance(entry, Mapping):
                    continue
                path = _entry_mask_path(
                    instance.package_root, entry, str(entry.get("visibility", "not_visible"))
                )
                if path is not None:
                    mask = read_mask(path)
                    if mask.shape != union.shape:
                        raise CvatV2Error(f"CVAT v2 crop mask dimensions differ: {path}")
                    union |= mask.astype(bool)
            if union.any():
                ys, xs = np.nonzero(union)
                left, top, right, bottom = (
                    int(xs.min()),
                    int(ys.min()),
                    int(xs.max()) + 1,
                    int(ys.max()) + 1,
                )
                padding = float(raw.get("padding_fraction", 0.2))
                pad_x = max(1, round((right - left) * padding))
                pad_y = max(1, round((bottom - top) * padding))
                bbox = (
                    max(0, left - pad_x),
                    max(0, top - pad_y),
                    min(width, right + pad_x),
                    min(height, bottom + pad_y),
                )
            else:
                first, second = float(fallback[0]), float(fallback[1])
                if not (0 <= first < second <= 1):
                    raise CvatV2Error(f"CVAT v2 fallback crop is invalid: {name}")
                bbox = (0, int(height * first), width, max(int(height * second), 1))
            buffer = io.BytesIO()
            source.crop(bbox).save(buffer, format="PNG")  # png-strict: allow - RGB review crop
            results[str(name)] = {"bbox_xyxy": list(bbox), "png": buffer.getvalue()}
    return results


def _discover_v2_instances(packages_root: Path, image_id: str) -> tuple[V2ReviewInstance, ...]:
    image_root = packages_root / image_id
    instances_root = image_root / "instances"
    roots = sorted(path for path in instances_root.glob("p*") if path.is_dir())
    if not roots and image_root.is_dir():
        roots = [image_root]
    result = []
    for index, package in enumerate(roots):
        manifest_path = package / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CvatV2Error(f"cannot load migrated v2 manifest {manifest_path}: {exc}") from exc
        if not isinstance(manifest, dict):
            raise CvatV2Error("migrated v2 manifest root must be an object")
        require_valid_v2_manifest(manifest)
        if manifest.get("mask_ontology_version") != V2_ONTOLOGY_VERSION:
            raise CvatV2Error(f"CVAT v2 push refuses non-v2 package: {package}")
        source_file = manifest.get("source", {}).get("source_file")
        if not isinstance(source_file, str):
            raise CvatV2Error(f"CVAT v2 package source_file is missing: {package}")
        source = _safe_package_path(package, source_file)
        if not source.is_file():
            raise CvatV2Error(f"CVAT v2 source is missing: {source}")
        instance_id = package.name if package != image_root else f"p{index}"
        result.append(V2ReviewInstance(image_id, instance_id, package, source, manifest))
    if not result:
        raise CvatV2Error(f"no migrated v2 package found for {image_id}")
    return tuple(result)


def _assignee_id(client: CvatClient, username: str) -> int:
    users = client.paginated("/api/users?" + urllib.parse.urlencode({"search": username}))
    exact = [user for user in users if str(user.get("username", "")).lower() == username.lower()]
    if len(exact) != 1:
        raise CvatV2Error(f"expected exactly one CVAT user {username!r}, found {len(exact)}")
    return int(exact[0]["id"])


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
