"""Push source frames, context layers, and draft RLE masks into CVAT."""

from __future__ import annotations

import io
import json
import os
import urllib.parse
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from ..io.png_strict import read_mask
from .client import DEFAULT_CONFIG, CvatApiError, CvatClient, load_cvat_config
from .labelmap import CvatLabelMap, encode_mask_rle

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGES = ROOT / "data" / "packages"
DEFAULT_TASK_RECORDS = ROOT / "data" / "cvat" / "tasks"


@dataclass(frozen=True)
class ReviewInstance:
    image_id: str
    instance_id: str
    package_root: Path
    source: Path
    overlay: Path
    disagreement: Path | None


def push_images(
    client: CvatClient,
    image_ids: tuple[str, ...],
    *,
    config_path: Path = DEFAULT_CONFIG,
    packages_root: Path = DEFAULT_PACKAGES,
    task_records: Path = DEFAULT_TASK_RECORDS,
) -> tuple[int, ...]:
    config = load_cvat_config(config_path)
    project_id, mapping = _load_mapping(config)
    instances = [
        instance
        for image_id in image_ids
        for instance in _discover_instances(Path(packages_root), image_id)
    ]
    if not instances:
        raise CvatApiError("no package instances selected for CVAT push")
    assignee_id = _assignee_id(client, str(config["project"]["assignee"]))
    batch_size = int(config["project"].get("jobs_per_task", 10))
    if batch_size != 10:
        raise CvatApiError("CVAT jobs_per_task must remain 10 per doc 11")
    task_ids = []
    by_image = {
        image_id: [instance for instance in instances if instance.image_id == image_id]
        for image_id in image_ids
    }
    for image_id in image_ids:
        image_instances = by_image[image_id]
        for instance in image_instances:
            task_ids.append(
                _push_batch(
                    client,
                    [instance],
                    project_id=project_id,
                    assignee_id=assignee_id,
                    mapping=mapping,
                    task_records=Path(task_records),
                )
            )
        if len(image_instances) > 1:
            task_ids.append(
                _push_overview(
                    client,
                    image_instances,
                    project_id=project_id,
                    assignee_id=assignee_id,
                    task_records=Path(task_records),
                )
            )
    return tuple(task_ids)


def _push_batch(
    client: CvatClient,
    instances: list[ReviewInstance],
    *,
    project_id: int,
    assignee_id: int,
    mapping: CvatLabelMap,
    task_records: Path,
) -> int:
    names = [instance.instance_id for instance in instances]
    task = client.request(
        "POST",
        "/api/tasks",
        payload={
            "name": "MaskFactory_review_" + "_".join(names),
            "description": _task_description(instances),
            "project_id": project_id,
            "assignee_id": assignee_id,
            "segment_size": 1,
            "overlap": 0,
        },
    )
    task_id = int(task["id"])
    archive, frame_records = _review_archive(instances)
    upload = client.multipart(
        "POST",
        f"/api/tasks/{task_id}/data",
        fields={"image_quality": 100, "use_cache": "true", "sorting_method": "lexicographical"},
        files={"client_files[0]": (f"maskfactory_task_{task_id}.zip", archive, "application/zip")},
        timeout=180,
    )
    if isinstance(upload, dict) and upload.get("rq_id"):
        client.wait_request(str(upload["rq_id"]), timeout=600)
    shapes = []
    for frame, instance in enumerate(instances):
        frame_shapes = _instance_shapes(instance, frame, mapping)
        shapes.extend(frame_shapes)
        frame_records[frame]["pushed_labels"] = [
            mapping.ontology_name(int(shape["label_id"])) for shape in frame_shapes
        ]
    client.request(
        "PUT",
        f"/api/tasks/{task_id}/annotations",
        payload={"version": 0, "tags": [], "shapes": shapes, "tracks": []},
        timeout=180,
    )
    record = {
        "schema_version": "1.0.0",
        "job_type": "instance_review",
        "task_id": task_id,
        "project_id": project_id,
        "assignee_id": assignee_id,
        "frames": frame_records,
        "shape_count": len(shapes),
    }
    _write_json_atomic(task_records / f"task_{task_id}.json", record)
    return task_id


def _push_overview(
    client: CvatClient,
    instances: list[ReviewInstance],
    *,
    project_id: int,
    assignee_id: int,
    task_records: Path,
) -> int:
    """Create one non-authoring context task for cross-instance consistency review."""
    image_id = instances[0].image_id
    task = client.request(
        "POST",
        "/api/tasks",
        payload={
            "name": f"MaskFactory_overview_{image_id}",
            "description": _sop6_description(instances),
            "project_id": project_id,
            "assignee_id": assignee_id,
            "segment_size": 1,
            "overlap": 0,
        },
    )
    task_id = int(task["id"])
    overview = _overview_png(instances)
    upload = client.multipart(
        "POST",
        f"/api/tasks/{task_id}/data",
        fields={"image_quality": 100, "use_cache": "true", "sorting_method": "lexicographical"},
        files={"client_files[0]": (f"000_{image_id}_overview.png", overview, "image/png")},
        timeout=180,
    )
    if isinstance(upload, dict) and upload.get("rq_id"):
        client.wait_request(str(upload["rq_id"]), timeout=600)
    client.request(
        "PUT",
        f"/api/tasks/{task_id}/annotations",
        payload={"version": 0, "tags": [], "shapes": [], "tracks": []},
        timeout=180,
    )
    record = {
        "schema_version": "1.0.0",
        "job_type": "image_overview",
        "task_id": task_id,
        "project_id": project_id,
        "assignee_id": assignee_id,
        "frames": [
            {
                "frame": 0,
                "filename": f"000_{image_id}_overview.png",
                "image_id": image_id,
                "instance_ids": [instance.instance_id for instance in instances],
                "context": ["all_promoted_instances_overlay"],
            }
        ],
        "shape_count": 0,
    }
    _write_json_atomic(task_records / f"task_{task_id}.json", record)
    return task_id


def _overview_png(instances: list[ReviewInstance]) -> bytes:
    panels = []
    for instance in instances:
        with Image.open(instance.overlay) as opened:
            panels.append(opened.convert("RGB").copy())
    width = sum(panel.width for panel in panels)
    height = max(panel.height for panel in panels)
    overview = Image.new("RGB", (width, height), "black")
    left = 0
    for panel in panels:
        overview.paste(panel, (left, 0))
        left += panel.width
    output = io.BytesIO()
    overview.save(output, format="PNG")  # png-strict: allow - RGB context panel, never a mask
    return output.getvalue()


def _sop6_description(instances: list[ReviewInstance]) -> str:
    names = ", ".join(instance.instance_id for instance in instances)
    return (
        "MaskFactory SOP-6 image overview (context-only; do not author masks here).\n"
        f"Promoted instances: {names}.\n"
        "1. Compare every promoted instance together in this overview.\n"
        "2. Confirm both involved instance packages agree on each interperson contact zone.\n"
        "3. Confirm no body-part pixels bleed into another person's silhouette core.\n"
        "4. Resolve corrections in each instance review task; use ambiguous_do_not_use with a "
        "specific note when ownership cannot be decided honestly.\n"
        "5. Do not approve either instance until reciprocal contact bands agree."
    )


def _task_description(instances: list[ReviewInstance]) -> str:
    """Attach only fail-verdict suggestions, explicitly marked as machine-generated."""
    lines = ["MaskFactory human review task. Automatic/VLM findings cannot approve gold."]
    if any(_has_interperson(instance.package_root) for instance in instances):
        lines.extend(
            [
                "SOP-6: compare this instance with the shared image overview and its reciprocal task.",
                "Confirm contact bands agree and no body-part pixels bleed across people; never guess ownership.",
            ]
        )
    for instance in instances:
        path = instance.package_root / "qa_report.json"
        if not path.is_file():
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for verdict in report.get("vlm_review", {}).get("verdicts", []):
            if not isinstance(verdict, dict) or verdict.get("verdict") != "fail":
                continue
            instruction = str(verdict.get("correction_instruction", "")).strip()
            if instruction:
                lines.append(
                    f"{instance.instance_id}/{verdict.get('label', 'unknown')}: "
                    f"MACHINE-GENERATED SUGGESTION: {instruction}"
                )
    return "\n".join(lines)


def _has_interperson(package_root: Path) -> bool:
    path = package_root / "manifest.json"
    if not path.is_file():
        return False
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("interperson"))
    except (OSError, json.JSONDecodeError):
        return False


def _review_archive(instances: list[ReviewInstance]) -> tuple[bytes, list[dict[str, Any]]]:
    output = io.BytesIO()
    frames = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for frame, instance in enumerate(instances):
            suffix = instance.source.suffix.lower()
            filename = f"{frame:03d}_{instance.instance_id}{suffix}"
            archive.writestr(filename, instance.source.read_bytes())
            related = f"related_images/{filename.replace('.', '_')}"
            archive.writestr(f"{related}/all_parts_overlay.png", instance.overlay.read_bytes())
            context = ["all_parts_overlay.png"]
            if instance.disagreement is not None:
                archive.writestr(
                    f"{related}/disagreement_heatmap.png", instance.disagreement.read_bytes()
                )
                context.append("disagreement_heatmap.png")
            with Image.open(instance.source) as image:
                width, height = image.size
            frames.append(
                {
                    "frame": frame,
                    "filename": filename,
                    "image_id": instance.image_id,
                    "instance_id": instance.instance_id,
                    "package_root": str(instance.package_root.resolve()),
                    "width": width,
                    "height": height,
                    "context": context,
                }
            )
    return output.getvalue(), frames


def _instance_shapes(
    instance: ReviewInstance, frame: int, mapping: CvatLabelMap
) -> list[dict[str, Any]]:
    manifest_path = instance.package_root / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    )
    parts = manifest.get("parts", {}) if isinstance(manifest, dict) else {}
    shapes = []
    seen = set()
    for directory in ("masks", "masks_material", "masks_regions", "projected", "protected"):
        for path in sorted((instance.package_root / directory).glob("*.png")):
            name = path.stem
            if name in seen:
                raise CvatApiError(f"duplicate draft label across CVAT layers: {name}")
            seen.add(name)
            mask = read_mask(path)
            if mask.max(initial=0) == 0:
                continue
            entry = parts.get(name, {}) if isinstance(parts, dict) else {}
            visibility = str(entry.get("visibility", "visible"))
            notes = str(entry.get("notes", ""))
            ambiguous = visibility == "ambiguous_do_not_use" or bool(entry.get("ambiguous", False))
            shapes.append(
                {
                    "type": "mask",
                    "frame": frame,
                    "label_id": mapping.cvat_id(name),
                    "points": encode_mask_rle(mask),
                    "occluded": visibility == "occluded",
                    "outside": False,
                    "z_order": 0,
                    "rotation": 0,
                    "attributes": [
                        {"spec_id": mapping.attribute_id(name, "visibility"), "value": visibility},
                        {
                            "spec_id": mapping.attribute_id(name, "ambiguous"),
                            "value": "true" if ambiguous else "false",
                        },
                        {"spec_id": mapping.attribute_id(name, "notes"), "value": notes},
                    ],
                    "source": "auto",
                }
            )
    return shapes


def _discover_instances(packages_root: Path, image_id: str) -> tuple[ReviewInstance, ...]:
    image_root = packages_root / image_id
    instances_root = image_root / "instances"
    roots = sorted(path for path in instances_root.glob("p*") if path.is_dir())
    if not roots and image_root.is_dir():
        roots = [image_root]
    results = []
    for index, package in enumerate(roots):
        instance_id = (
            f"{image_id}_{package.name}" if package != image_root else f"{image_id}_p{index}"
        )
        source = next(
            (path for path in (package / "source.png", package / "source.jpg") if path.is_file()),
            None,
        )
        if source is None:
            raise CvatApiError(f"package source missing: {package}")
        overlay = package / "overlays" / "all_parts.png"
        if not overlay.is_file():
            raise CvatApiError(f"required all-parts context overlay missing: {overlay}")
        disagreement = package / "overlays" / "disagreement_heatmap.png"
        results.append(
            ReviewInstance(
                image_id,
                instance_id,
                package,
                source,
                overlay,
                disagreement if disagreement.is_file() else None,
            )
        )
    if not results:
        raise CvatApiError(f"no package found for {image_id}")
    return tuple(results)


def _load_mapping(config: dict[str, Any]) -> tuple[int, CvatLabelMap]:
    path = Path(config["project"]["label_mapping_file"])
    if not path.is_absolute():
        path = ROOT / path
    document = json.loads(path.read_text(encoding="utf-8"))
    labels = []
    for name, entry in document["labels"].items():
        labels.append(
            {
                "id": entry["cvat_id"],
                "name": name,
                "color": entry["color"],
                "attributes": [
                    {"id": attribute_id, "name": attribute}
                    for attribute, attribute_id in entry["attributes"].items()
                ],
            }
        )
    return int(document["project_id"]), CvatLabelMap(labels)


def _assignee_id(client: CvatClient, username: str) -> int:
    users = client.paginated("/api/users?" + urllib.parse.urlencode({"search": username}))
    exact = [user for user in users if user.get("username", "").lower() == username.lower()]
    if len(exact) != 1:
        raise CvatApiError(f"expected exactly one CVAT user {username!r}, found {len(exact)}")
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
