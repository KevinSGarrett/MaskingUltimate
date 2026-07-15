"""The complete, deliberately narrow one-shot automatic correction policy."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from ..derive import derive_package
from ..fusion.mapbuild import export_binaries
from ..io.png_strict import read_mask, write_label_map
from ..ontology import get_ontology
from .checks import run_qc001_010


class AutoFixError(RuntimeError):
    """The governed auto-fix cannot safely execute."""


def run_autofix_once(package_root: Path) -> dict[str, Any]:
    """Attempt exactly the four allowed fixes once, log, and re-check."""
    package_root = Path(package_root)
    log_path = package_root / "qa" / "autofix.json"
    if log_path.is_file():
        existing = json.loads(log_path.read_text(encoding="utf-8"))
        if existing.get("attempted") is True:
            return existing
    part_path = package_root / "label_map_part.png"
    material_path = package_root / "label_map_material.png"
    before = _governed_hashes(package_root)
    part = read_mask(part_path).astype(np.uint16)
    material = read_mask(material_path).astype(np.uint8)
    if part.shape != material.shape:
        raise AutoFixError("authority map dimensions differ")
    component_pixels = 0
    hole_pixels = 0
    ontology = get_ontology()
    for label in ontology.labels_for_map("part", enabled_only=True):
        if label.id == 0 or label.mask_type == "protected_qa":
            continue
        foreground = part == label.id
        area = int(foreground.sum())
        if area == 0:
            continue
        component_threshold = max(64, int(np.ceil(0.02 * area)))
        for component in _components(foreground):
            if len(component) < component_threshold:
                ys, xs = zip(*component, strict=True)
                ys_array, xs_array = np.asarray(ys), np.asarray(xs)
                part[ys_array, xs_array] = 0
                material[ys_array, xs_array] = 0
                component_pixels += len(component)
        foreground = part == label.id
        area = int(foreground.sum())
        if area == 0 or label.name == "hair" or np.any(foreground & (material == 12)):
            continue
        max_hole = int(np.floor(0.005 * area))
        if max_hole < 1:
            continue
        for hole in _holes(foreground):
            if len(hole) <= max_hole:
                ys, xs = zip(*hole, strict=True)
                ys_array, xs_array = np.asarray(ys), np.asarray(xs)
                fillable = part[ys_array, xs_array] == 0
                part[ys_array[fillable], xs_array[fillable]] = int(label.id)
                label_materials = material[foreground]
                nonzero_materials = label_materials[label_materials > 0]
                if len(nonzero_materials):
                    dominant = int(np.bincount(nonzero_materials).argmax())
                    material[ys_array[fillable], xs_array[fillable]] = dominant
                hole_pixels += int(fillable.sum())
    write_label_map(part_path, part, bits=16)
    # Material is intentionally not geometrically changed by this P1 policy.
    write_label_map(material_path, material, bits=8)
    binary_outputs = export_binaries(package_root)
    derived_outputs = derive_package(package_root)
    results = run_qc001_010(package_root)
    after = _governed_hashes(package_root)
    document = {
        "schema_version": "1.0.0",
        "attempted": True,
        "policy": [
            "regenerate_binaries_from_maps",
            "drop_components_lt_max_64px_or_2pct_part",
            "fill_holes_lt_0_5pct_part",
            "rederive_unions",
        ],
        "changes": {
            "component_pixels_dropped": component_pixels,
            "hole_pixels_filled": hole_pixels,
            "binary_views_regenerated": len(binary_outputs),
            "derived_masks_regenerated": len(derived_outputs),
        },
        "before": before,
        "after": after,
        "recheck": [asdict(result) for result in results],
    }
    _write_json_atomic(log_path, document)
    return document


def _components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    visited = np.zeros(mask.shape, dtype=bool)
    results = []
    height, width = mask.shape
    for y, x in zip(*np.nonzero(mask), strict=True):
        if visited[y, x]:
            continue
        stack = [(int(y), int(x))]
        visited[y, x] = True
        component = []
        while stack:
            cy, cx = stack.pop()
            component.append((cy, cx))
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not visited[ny, nx]:
                    visited[ny, nx] = True
                    stack.append((ny, nx))
        results.append(component)
    return results


def _holes(foreground: np.ndarray) -> list[list[tuple[int, int]]]:
    ys, xs = np.nonzero(foreground)
    if len(xs) == 0:
        return []
    top, bottom = int(ys.min()), int(ys.max())
    left, right = int(xs.min()), int(xs.max())
    background = ~foreground[top : bottom + 1, left : right + 1]
    holes = []
    for component in _components(background):
        touches_edge = any(
            y == 0 or x == 0 or y == background.shape[0] - 1 or x == background.shape[1] - 1
            for y, x in component
        )
        if not touches_edge:
            holes.append([(y + top, x + left) for y, x in component])
    return holes


def _governed_hashes(package_root: Path) -> dict[str, str]:
    paths = []
    for name in ("label_map_part.png", "label_map_material.png"):
        path = package_root / name
        if path.is_file():
            paths.append(path)
    for directory in ("masks", "masks_material", "protected", "masks_derived"):
        paths.extend(sorted((package_root / directory).glob("*.png")))
    return {
        path.relative_to(package_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


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
