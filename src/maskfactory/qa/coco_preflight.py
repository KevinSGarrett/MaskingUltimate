"""Fail-closed, CPU-safe preflight and raster evidence for polygon COCO corpora.

This module prepares deterministic input and raster-QA records.  It deliberately
does not assign truth, acceptance, gold, or promotion authority to those records.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw


class CocoPreflightError(ValueError):
    """A COCO source violates the deterministic CPU preflight contract."""


def canonical_sha256(document: Mapping[str, Any]) -> str:
    """Return a stable digest for JSON-compatible COCO content."""
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a file without retaining its full contents in memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_coco_document(path: Path) -> dict[str, Any]:
    """Load a JSON object or raise an evidence-preserving contract error."""
    try:
        parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CocoPreflightError(f"cannot read COCO document {path}: {error}") from error
    if not isinstance(parsed, dict):
        raise CocoPreflightError("COCO document root must be an object")
    return parsed


def build_cpu_safe_coco_preflight(
    coco: Mapping[str, Any],
    image_root: Path,
    *,
    max_images: int,
) -> dict[str, Any]:
    """Validate a polygon COCO document and return a compact replay manifest.

    Only selected images are decoded and hashed, but every image/category/annotation
    record is structurally and geometrically checked before a selection is emitted.
    Segmentation coordinates are intentionally excluded from the compact manifest;
    rasterization must receive the original hash-bound COCO document again.
    """
    if max_images < 1:
        raise CocoPreflightError("max_images must be at least one")
    root = Path(image_root).resolve()
    if not root.is_dir():
        raise CocoPreflightError(f"image root is not a directory: {root}")

    images = _required_list(coco, "images")
    categories = _required_list(coco, "categories")
    annotations = _required_list(coco, "annotations")
    if not images or not categories or not annotations:
        raise CocoPreflightError("images, categories, and annotations must all be non-empty")

    image_by_id: dict[str, Mapping[str, Any]] = {}
    source_file_names: set[str] = set()
    for image in images:
        if not isinstance(image, Mapping):
            raise CocoPreflightError("every images entry must be an object")
        identifier = _identifier(image.get("id"), "image id")
        if identifier in image_by_id:
            raise CocoPreflightError(f"duplicate image id: {identifier}")
        filename = image.get("file_name")
        if not isinstance(filename, str) or not filename.strip():
            raise CocoPreflightError(f"image {identifier} has no non-empty file_name")
        if filename in source_file_names:
            raise CocoPreflightError(f"duplicate image file_name: {filename}")
        source_file_names.add(filename)
        _safe_image_path(root, filename)
        _positive_integral(image.get("width"), f"image {identifier} width")
        _positive_integral(image.get("height"), f"image {identifier} height")
        image_by_id[identifier] = image

    category_by_id: dict[str, Mapping[str, Any]] = {}
    for category in categories:
        if not isinstance(category, Mapping):
            raise CocoPreflightError("every categories entry must be an object")
        identifier = _identifier(category.get("id"), "category id")
        if identifier in category_by_id:
            raise CocoPreflightError(f"duplicate category id: {identifier}")
        name = category.get("name")
        if not isinstance(name, str) or not name.strip():
            raise CocoPreflightError(f"category {identifier} has no non-empty name")
        category_by_id[identifier] = category

    annotations_by_image: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    annotation_ids: set[str] = set()
    for annotation in annotations:
        if not isinstance(annotation, Mapping):
            raise CocoPreflightError("every annotations entry must be an object")
        annotation_id = _identifier(annotation.get("id"), "annotation id")
        if annotation_id in annotation_ids:
            raise CocoPreflightError(f"duplicate annotation id: {annotation_id}")
        annotation_ids.add(annotation_id)
        image_id = _identifier(annotation.get("image_id"), f"annotation {annotation_id} image_id")
        category_id = _identifier(
            annotation.get("category_id"), f"annotation {annotation_id} category_id"
        )
        if image_id not in image_by_id:
            raise CocoPreflightError(f"annotation {annotation_id} refers to absent image {image_id}")
        if category_id not in category_by_id:
            raise CocoPreflightError(
                f"annotation {annotation_id} refers to absent category {category_id}"
            )
        image = image_by_id[image_id]
        width = _positive_integral(image.get("width"), f"image {image_id} width")
        height = _positive_integral(image.get("height"), f"image {image_id} height")
        bbox = _validated_bbox(annotation.get("bbox"), width, height, annotation_id)
        polygons = _validated_polygons(annotation.get("segmentation"), width, height, annotation_id)
        for polygon in polygons:
            _verify_polygon_within_bbox(polygon, bbox, annotation_id)
        annotations_by_image[image_id].append(annotation)

    ordered_images = sorted(
        image_by_id.items(), key=lambda item: (str(item[1]["file_name"]), item[0])
    )[:max_images]
    selected_images: list[dict[str, Any]] = []
    for image_id, image in ordered_images:
        source_path = _safe_image_path(root, str(image["file_name"]))
        if not source_path.is_file():
            raise CocoPreflightError(f"selected source image is missing: {source_path}")
        width = _positive_integral(image.get("width"), f"image {image_id} width")
        height = _positive_integral(image.get("height"), f"image {image_id} height")
        _verify_image_dimensions(source_path, width, height)
        image_annotations = annotations_by_image.get(image_id, [])
        if not image_annotations:
            raise CocoPreflightError(f"selected image {image_id} has no polygon annotations")
        selected_images.append(
            {
                "annotation_count": len(image_annotations),
                "annotations": [
                    {
                        "annotation_id": _identifier(annotation["id"], "annotation id"),
                        "bbox_xywh": [float(value) for value in annotation["bbox"]],
                        "category_id": _identifier(annotation["category_id"], "category id"),
                    }
                    for annotation in sorted(
                        image_annotations, key=lambda record: _identifier(record["id"], "annotation id")
                    )
                ],
                "file_name": str(image["file_name"]),
                "height": height,
                "image_id": image_id,
                "source_sha256": sha256_file(source_path),
                "width": width,
            }
        )

    return {
        "annotation_document_canonical_sha256": canonical_sha256(coco),
        "artifact_type": "maskfactory.cpu_safe_coco_preflight.v1",
        "authority_claimed": False,
        "category_count": len(category_by_id),
        "image_count": len(image_by_id),
        "mask_policy": {
            "empty_masks_permitted": False,
            "full_masks_permitted": False,
            "format": "PNG-L-foreground-255",
            "source_of_truth": "original_hash_bound_coco_polygon_document",
        },
        "selected_images": selected_images,
        "selected_image_count": len(selected_images),
        "selection_policy": {"max_images": max_images, "order": "file_name_ascending_then_image_id"},
        "total_annotation_count": len(annotations),
    }


def rasterize_authoritative_polygons(
    coco: Mapping[str, Any],
    preflight: Mapping[str, Any],
    image_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Rasterize selected polygon annotations only when all source hashes still match."""
    expected_document_hash = preflight.get("annotation_document_canonical_sha256")
    actual_document_hash = canonical_sha256(coco)
    if expected_document_hash != actual_document_hash:
        raise CocoPreflightError("COCO document hash drifted after preflight; rasterization refused")
    selected = preflight.get("selected_images")
    if not isinstance(selected, list) or not selected:
        raise CocoPreflightError("preflight has no selected image records")

    root = Path(image_root).resolve()
    image_by_id = {
        _identifier(image.get("id"), "image id"): image
        for image in _required_list(coco, "images")
        if isinstance(image, Mapping)
    }
    annotations_by_image: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for annotation in _required_list(coco, "annotations"):
        if not isinstance(annotation, Mapping):
            raise CocoPreflightError("every annotations entry must be an object")
        annotations_by_image[_identifier(annotation.get("image_id"), "annotation image_id")].append(annotation)

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    masks: list[dict[str, Any]] = []
    for selected_image in selected:
        if not isinstance(selected_image, Mapping):
            raise CocoPreflightError("preflight selected image record must be an object")
        image_id = _identifier(selected_image.get("image_id"), "preflight image_id")
        image = image_by_id.get(image_id)
        if image is None:
            raise CocoPreflightError(f"preflight image {image_id} is absent from COCO document")
        file_name = str(image.get("file_name", ""))
        if file_name != selected_image.get("file_name"):
            raise CocoPreflightError(f"preflight filename drifted for image {image_id}")
        source_path = _safe_image_path(root, file_name)
        if sha256_file(source_path) != selected_image.get("source_sha256"):
            raise CocoPreflightError(f"source image hash drifted for {file_name}; rasterization refused")
        width = _positive_integral(image.get("width"), f"image {image_id} width")
        height = _positive_integral(image.get("height"), f"image {image_id} height")
        if (width, height) != (selected_image.get("width"), selected_image.get("height")):
            raise CocoPreflightError(f"preflight dimensions drifted for image {image_id}")

        mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask)
        image_annotations = annotations_by_image.get(image_id, [])
        if not image_annotations:
            raise CocoPreflightError(f"selected image {image_id} has no polygon annotations")
        for annotation in image_annotations:
            annotation_id = _identifier(annotation.get("id"), "annotation id")
            _validated_bbox(annotation.get("bbox"), width, height, annotation_id)
            for polygon in _validated_polygons(
                annotation.get("segmentation"), width, height, annotation_id
            ):
                draw.polygon([(polygon[index], polygon[index + 1]) for index in range(0, len(polygon), 2)], fill=255)

        foreground_pixels = mask.histogram()[255]
        total_pixels = width * height
        if foreground_pixels == 0 or foreground_pixels == total_pixels:
            raise CocoPreflightError(
                f"raster mask for {file_name} is {'empty' if foreground_pixels == 0 else 'full'}"
            )
        relative_output = Path(file_name).with_suffix(".png")
        output_path = _safe_output_path(destination, relative_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mask.save(output_path, format="PNG")
        masks.append(
            {
                "coverage_fraction": foreground_pixels / total_pixels,
                "file_name": file_name,
                "height": height,
                "image_id": image_id,
                "mask_path": str(relative_output.as_posix()),
                "mask_sha256": sha256_file(output_path),
                "width": width,
            }
        )

    coverages = [entry["coverage_fraction"] for entry in masks]
    return {
        "artifact_type": "maskfactory.cpu_safe_coco_raster_qa.v1",
        "authority_claimed": False,
        "mask_count": len(masks),
        "masks": masks,
        "source_preflight_sha256": canonical_sha256(preflight),
        "summary": {
            "empty_mask_count": 0,
            "full_mask_count": 0,
            "max_coverage_fraction": max(coverages),
            "min_coverage_fraction": min(coverages),
        },
    }


def write_json_atomically(path: Path, document: Mapping[str, Any]) -> Path:
    """Write a new JSON artifact atomically and refuse to overwrite evidence."""
    target = Path(path)
    if target.exists():
        raise CocoPreflightError(f"refusing to overwrite existing artifact: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _required_list(document: Mapping[str, Any], field: str) -> list[Any]:
    value = document.get(field)
    if not isinstance(value, list):
        raise CocoPreflightError(f"COCO field {field!r} must be a list")
    return value


def _identifier(value: Any, label: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value):
        raise CocoPreflightError(f"{label} must be a non-empty string or integer")
    return str(value)


def _positive_integral(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CocoPreflightError(f"{label} must be a positive integer")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise CocoPreflightError(f"{label} must be finite numeric")
    return float(value)


def _validated_bbox(value: Any, width: int, height: int, annotation_id: str) -> tuple[float, float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise CocoPreflightError(f"annotation {annotation_id} bbox must contain four coordinates")
    x, y, box_width, box_height = tuple(
        _number(component, f"annotation {annotation_id} bbox") for component in value
    )
    if x < 0 or y < 0 or box_width <= 0 or box_height <= 0 or x + box_width > width or y + box_height > height:
        raise CocoPreflightError(f"annotation {annotation_id} bbox lies outside image bounds")
    return x, y, box_width, box_height


def _validated_polygons(value: Any, width: int, height: int, annotation_id: str) -> list[tuple[float, ...]]:
    if not isinstance(value, list) or not value:
        raise CocoPreflightError(f"annotation {annotation_id} requires non-empty polygon segmentation")
    polygons: list[tuple[float, ...]] = []
    for index, raw_polygon in enumerate(value):
        if not isinstance(raw_polygon, list) or len(raw_polygon) < 6 or len(raw_polygon) % 2:
            raise CocoPreflightError(f"annotation {annotation_id} polygon {index} has invalid coordinate count")
        polygon = tuple(
            _number(coordinate, f"annotation {annotation_id} polygon {index}")
            for coordinate in raw_polygon
        )
        for x, y in zip(polygon[::2], polygon[1::2], strict=True):
            if x < 0 or y < 0 or x > width or y > height:
                raise CocoPreflightError(f"annotation {annotation_id} polygon {index} lies outside image bounds")
        area_twice = abs(
            sum(
                polygon[offset] * polygon[(offset + 3) % len(polygon)]
                - polygon[(offset + 1) % len(polygon)] * polygon[(offset + 2) % len(polygon)]
                for offset in range(0, len(polygon), 2)
            )
        )
        if area_twice == 0:
            raise CocoPreflightError(f"annotation {annotation_id} polygon {index} has zero area")
        polygons.append(polygon)
    return polygons


def _verify_polygon_within_bbox(
    polygon: Sequence[float], bbox: tuple[float, float, float, float], annotation_id: str
) -> None:
    x, y, width, height = bbox
    epsilon = 1e-6
    for point_x, point_y in zip(polygon[::2], polygon[1::2], strict=True):
        if point_x < x - epsilon or point_x > x + width + epsilon or point_y < y - epsilon or point_y > y + height + epsilon:
            raise CocoPreflightError(f"annotation {annotation_id} polygon falls outside declared bbox")


def _verify_image_dimensions(path: Path, width: int, height: int) -> None:
    try:
        with Image.open(path) as image:
            image.load()
            actual = image.size
    except (OSError, ValueError) as error:
        raise CocoPreflightError(f"cannot decode selected source image {path}: {error}") from error
    if actual != (width, height):
        raise CocoPreflightError(f"source dimensions {actual} disagree with COCO {(width, height)}: {path}")


def _safe_image_path(root: Path, file_name: str) -> Path:
    relative = Path(file_name)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        raise CocoPreflightError(f"unsafe COCO file_name: {file_name!r}")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise CocoPreflightError(f"COCO file_name escapes image root: {file_name!r}") from error
    return candidate


def _safe_output_path(root: Path, relative: Path) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise CocoPreflightError(f"mask output escapes destination: {relative}") from error
    return candidate
