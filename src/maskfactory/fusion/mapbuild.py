"""Build authoritative label maps and regenerate their binary views."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
from PIL import Image

from ..io.png_strict import PngStrictError, read_mask, write_binary_mask, write_label_map
from ..ontology import Label, Ontology, OntologyError, get_ontology


class MapBuildError(ValueError):
    """Input masks cannot form one deterministic ontology label map."""


def priority_argmax(
    candidates: Mapping[str, np.ndarray],
    *,
    map_name: str,
    ontology: Ontology | None = None,
    priorities: Mapping[str, int] | None = None,
) -> np.ndarray:
    """Resolve candidate scores lexicographically by score, priority, then ontology ID."""
    authority = ontology or get_ontology()
    if map_name not in {"part", "material"}:
        raise MapBuildError(f"map_name must be part or material, got {map_name!r}")
    if not candidates:
        raise MapBuildError("at least one candidate mask is required")
    priorities = priorities or {}
    shape: tuple[int, int] | None = None
    prepared: list[tuple[Label, np.ndarray, int]] = []
    for name, raw in candidates.items():
        try:
            label = authority.label(name, require_enabled=True)
        except OntologyError as exc:
            raise MapBuildError(str(exc)) from exc
        if label.map != map_name or label.id is None:
            raise MapBuildError(f"label {name!r} does not belong to {map_name} map")
        score = np.asarray(raw)
        if score.ndim != 2:
            raise MapBuildError(f"candidate {name!r} must be 2-D, got {score.shape}")
        if shape is None:
            shape = score.shape
        elif score.shape != shape:
            raise MapBuildError(f"candidate {name!r} shape {score.shape} != {shape}")
        if score.dtype == np.bool_:
            normalized = score.astype(np.float32)
        elif np.issubdtype(score.dtype, np.integer):
            if score.min() < 0 or score.max() > 255:
                raise MapBuildError(f"candidate {name!r} integer values must be in 0..255")
            normalized = score.astype(np.float32) / 255.0
        else:
            normalized = score.astype(np.float32)
            if not np.isfinite(normalized).all() or normalized.min() < 0 or normalized.max() > 1:
                raise MapBuildError(f"candidate {name!r} scores must be finite in 0..1")
        prepared.append((label, normalized, int(priorities.get(name, label.id))))

    assert shape is not None
    output_dtype = np.uint16 if map_name == "part" else np.uint8
    output = np.zeros(shape, dtype=output_dtype)
    best_score = np.zeros(shape, dtype=np.float32)
    best_priority = np.full(shape, -1, dtype=np.int64)
    best_id = np.zeros(shape, dtype=np.int64)
    for label, score, priority in prepared:
        label_id = int(label.id)
        wins = (score > best_score) | (
            (score == best_score)
            & (score > 0)
            & ((priority > best_priority) | ((priority == best_priority) & (label_id > best_id)))
        )
        output[wins] = label_id
        best_score[wins] = score[wins]
        best_priority[wins] = priority
        best_id[wins] = label_id
    return output


def fuse_package(
    package_root: Path,
    *,
    part_masks: Path | None = None,
    material_masks: Path | None = None,
    priorities: Mapping[str, int] | None = None,
) -> tuple[Path, Path]:
    """Fuse human CVAT mask directories into the two package-authority maps."""
    package_root = Path(package_root)
    part_masks = Path(part_masks or package_root / "annotations" / "part_masks")
    material_masks = Path(material_masks or package_root / "annotations" / "material_masks")
    part = priority_argmax(
        _read_candidate_directory(part_masks),
        map_name="part",
        priorities=priorities,
    )
    material = priority_argmax(
        _read_candidate_directory(material_masks),
        map_name="material",
        priorities=priorities,
    )
    if part.shape != material.shape:
        raise MapBuildError(f"part map shape {part.shape} != material map shape {material.shape}")
    part_path = write_label_map(package_root / "label_map_part.png", part, bits=16)
    material_path = write_label_map(package_root / "label_map_material.png", material, bits=8)
    return part_path, material_path


def export_binaries(package_root: Path, *, ontology: Ontology | None = None) -> tuple[Path, ...]:
    """Regenerate every enabled indexed label as a strict binary view."""
    package_root = Path(package_root)
    authority = ontology or get_ontology()
    part = read_mask(package_root / "label_map_part.png").astype(np.uint16)
    material = read_mask(package_root / "label_map_material.png").astype(np.uint8)
    if part.shape != material.shape:
        raise MapBuildError(f"part map shape {part.shape} != material map shape {material.shape}")
    size = (part.shape[1], part.shape[0])
    outputs: list[Path] = []
    for label in authority.labels_for_map("part", enabled_only=True):
        target = _part_binary_path(package_root, label)
        outputs.append(write_binary_mask(target, part == label.id, source_size=size))
    for label in authority.labels_for_map("material", enabled_only=True):
        target = package_root / "masks_material" / f"{label.name}.png"
        outputs.append(write_binary_mask(target, material == label.id, source_size=size))
    return tuple(outputs)


def rebuild_map_from_binaries(
    package_root: Path, map_name: str, *, ontology: Ontology | None = None
) -> np.ndarray:
    """Rebuild a map from exported views, rejecting overlap or missing enabled files."""
    package_root = Path(package_root)
    authority = ontology or get_ontology()
    labels = authority.labels_for_map(map_name, enabled_only=True)
    output: np.ndarray | None = None
    claimed: np.ndarray | None = None
    for label in labels:
        path = (
            _part_binary_path(package_root, label)
            if map_name == "part"
            else package_root / "masks_material" / f"{label.name}.png"
        )
        if not path.is_file():
            raise MapBuildError(f"missing binary view: {path}")
        mask = read_mask(path)
        if mask.ndim != 2 or not set(np.unique(mask)).issubset({0, 255}):
            raise PngStrictError(f"invalid binary view: {path}")
        foreground = mask == 255
        if output is None:
            output = np.zeros(mask.shape, dtype=np.uint16 if map_name == "part" else np.uint8)
            claimed = np.zeros(mask.shape, dtype=bool)
        if mask.shape != output.shape:
            raise MapBuildError(f"binary shape mismatch: {path}")
        assert claimed is not None
        overlap = claimed & foreground
        if np.any(overlap):
            raise MapBuildError(f"binary views overlap by {int(overlap.sum())} pixels: {path}")
        output[foreground] = int(label.id)
        claimed |= foreground
    assert output is not None
    return output


def _part_binary_path(package_root: Path, label: Label) -> Path:
    directory = "protected" if label.id == 0 or label.mask_type == "protected_qa" else "masks"
    return package_root / directory / f"{label.name}.png"


def _read_candidate_directory(directory: Path) -> dict[str, np.ndarray]:
    if not directory.is_dir():
        raise MapBuildError(f"candidate directory does not exist: {directory}")
    paths = sorted(directory.glob("*.png"))
    if not paths:
        raise MapBuildError(f"candidate directory has no PNG masks: {directory}")
    result: dict[str, np.ndarray] = {}
    for path in paths:
        with Image.open(path) as image:
            result[path.stem] = np.asarray(image)
    return result
