"""Automatic package checks, beginning with the P1 QC-001..007 hard-block subset."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from ..derive import DeriveError, compute_derivations
from ..io.png_strict import read_mask
from ..ontology import OntologyError, get_ontology
from ..validation import validate_document


@dataclass(frozen=True)
class QcResult:
    qc_id: str
    name: str
    passed: bool
    detail: str
    severity: str = "BLOCK"


def run_format_integrity(package_root: Path) -> tuple[QcResult, ...]:
    """Run QC-001 through QC-007 against one package directory."""
    package_root = Path(package_root)
    manifest_path = package_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        manifest = None
        manifest_detail = str(exc)
    else:
        issues = validate_document(manifest, "manifest")
        manifest_detail = "valid" if not issues else "; ".join(str(issue) for issue in issues)

    binaries = _binary_paths(package_root)
    source_size = _source_size(package_root, manifest)
    results = [
        _qc001(binaries, source_size),
        _qc002(binaries),
        _qc003(binaries),
        _qc004(binaries),
        (
            QcResult(
                "QC-005",
                "manifest_schema_valid",
                manifest is not None and not issues,
                manifest_detail,
            )
            if manifest is not None
            else QcResult("QC-005", "manifest_schema_valid", False, manifest_detail)
        ),
        _qc006(package_root, manifest),
        _qc007(package_root, binaries),
    ]
    return tuple(results)


def run_qc001_010(package_root: Path) -> tuple[QcResult, ...]:
    """Run the complete P1 hard-block package battery."""
    package_root = Path(package_root)
    manifest_path = package_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = None
    return (
        *run_format_integrity(package_root),
        _qc008(manifest),
        _qc009(package_root),
        _qc010(package_root, manifest),
    )


def _qc001(paths: tuple[Path, ...], source_size: tuple[int, int] | None) -> QcResult:
    if source_size is None:
        return QcResult("QC-001", "dimensions_match_source", False, "source dimensions unavailable")
    wrong = []
    for path in paths:
        with Image.open(path) as image:
            if image.size != source_size:
                wrong.append(path.name)
    return QcResult(
        "QC-001",
        "dimensions_match_source",
        not wrong,
        "all match" if not wrong else "wrong dimensions: " + ", ".join(wrong),
    )


def _qc002(paths: tuple[Path, ...]) -> QcResult:
    wrong = []
    for path in paths:
        with Image.open(path) as image:
            values = set(np.unique(np.asarray(image)).tolist())
        if not values.issubset({0, 255}):
            wrong.append(path.name)
    return QcResult(
        "QC-002",
        "binary_values_only",
        not wrong,
        "all binary" if not wrong else "nonbinary: " + ", ".join(wrong),
    )


def _qc003(paths: tuple[Path, ...]) -> QcResult:
    wrong = []
    for path in paths:
        magic = path.read_bytes()[:8]
        with Image.open(path) as image:
            if image.mode != "L" or magic != b"\x89PNG\r\n\x1a\n":
                wrong.append(path.name)
    return QcResult(
        "QC-003",
        "png_mode",
        not wrong,
        "all mode L PNG" if not wrong else "invalid mode/magic: " + ", ".join(wrong),
    )


def _qc004(paths: tuple[Path, ...]) -> QcResult:
    ontology = get_ontology()
    wrong = []
    for path in paths:
        try:
            ontology.label(path.stem, require_enabled=True)
        except OntologyError:
            wrong.append(path.name)
    return QcResult(
        "QC-004",
        "filename_ontology_match",
        not wrong,
        "all ontology labels" if not wrong else "unknown/disabled: " + ", ".join(wrong),
    )


def _qc006(package_root: Path, manifest: dict | None) -> QcResult:
    if manifest is None or not isinstance(manifest.get("files"), dict):
        return QcResult("QC-006", "hash_integrity", False, "manifest files mapping unavailable")
    expected = manifest["files"]
    actual_paths = {
        path.relative_to(package_root).as_posix(): path
        for path in package_root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    missing = sorted(set(expected).difference(actual_paths))
    untracked = sorted(set(actual_paths).difference(expected))
    mismatched = sorted(
        relative
        for relative in set(expected).intersection(actual_paths)
        if _sha256(actual_paths[relative]) != expected[relative]
    )
    passed = not (missing or untracked or mismatched)
    detail = (
        "all hashes match"
        if passed
        else f"missing={missing}, untracked={untracked}, mismatch={mismatched}"
    )
    return QcResult("QC-006", "hash_integrity", passed, detail)


def _qc007(package_root: Path, binaries: tuple[Path, ...]) -> QcResult:
    try:
        ontology = get_ontology()
        part = read_mask(package_root / "label_map_part.png").astype(np.uint16)
        material = read_mask(package_root / "label_map_material.png").astype(np.uint8)
        mismatched = []
        for label in (
            *ontology.labels_for_map("part", enabled_only=True),
            *ontology.labels_for_map("material", enabled_only=True),
        ):
            if label.map == "part":
                directory = (
                    "protected" if label.id == 0 or label.mask_type == "protected_qa" else "masks"
                )
                authority = part
            else:
                directory = "masks_material"
                authority = material
            path = package_root / directory / f"{label.name}.png"
            if not path.is_file():
                mismatched.append(path.relative_to(package_root).as_posix() + " (missing)")
                continue
            actual = read_mask(path)
            if not np.array_equal(actual, (authority == label.id).astype(np.uint8) * 255):
                mismatched.append(path.relative_to(package_root).as_posix())
    except Exception as exc:  # noqa: BLE001 - check reports rather than raises
        return QcResult("QC-007", "map_binary_consistency", False, str(exc))
    return QcResult(
        "QC-007",
        "map_binary_consistency",
        not mismatched,
        "exact regeneration" if not mismatched else "mismatch: " + ", ".join(mismatched),
    )


def _qc008(manifest: dict | None) -> QcResult:
    if manifest is None or not isinstance(manifest.get("parts"), dict):
        return QcResult("QC-008", "required_states_complete", False, "manifest parts unavailable")
    ontology = get_ontology()
    required = {
        label.name for label in ontology.labels if label.enabled and label.map != "material"
    }
    parts = manifest["parts"]
    allowed = {
        "visible",
        "partially_visible",
        "occluded",
        "cropped_out",
        "not_visible",
        "ambiguous_do_not_use",
        "n/a",
    }
    missing = sorted(required.difference(parts))
    invalid = sorted(
        name
        for name in required.intersection(parts)
        if not isinstance(parts[name], dict) or parts[name].get("visibility") not in allowed
    )
    passed = not missing and not invalid
    return QcResult(
        "QC-008",
        "required_states_complete",
        passed,
        (
            "all enabled non-material labels have states"
            if passed
            else f"missing={missing}, invalid={invalid}"
        ),
    )


def _qc009(package_root: Path) -> QcResult:
    manifest_path = package_root / "masks_derived" / "manifest.json"
    try:
        evidence = json.loads(manifest_path.read_text(encoding="utf-8"))
        computed, formulas, input_hashes = compute_derivations(package_root)
        records = evidence["derivations"]
        wrong = []
        for name, mask in computed.items():
            path = package_root / "masks_derived" / f"{name}.png"
            record = records.get(name, {})
            actual = read_mask(path)
            if (
                record.get("formula") != formulas[name]
                or record.get("inputs") != input_hashes
                or record.get("output_sha256") != _sha256(path)
                or not np.array_equal(actual, mask.astype(np.uint8) * 255)
            ):
                wrong.append(name)
    except (OSError, KeyError, ValueError, DeriveError) as exc:
        return QcResult("QC-009", "derived_not_hand_authored", False, str(exc))
    return QcResult(
        "QC-009",
        "derived_not_hand_authored",
        not wrong,
        "all formulas reproduce" if not wrong else "not reproducible: " + ", ".join(wrong),
    )


def _qc010(package_root: Path, manifest: dict | None) -> QcResult:
    transforms = sorted((package_root / "crops").glob("*transform*.json"))
    if not transforms:
        return QcResult("QC-010", "crop_transform_valid", True, "no crop transforms present")
    source_size = _source_size(package_root, manifest)
    if source_size is None:
        return QcResult("QC-010", "crop_transform_valid", False, "source size unavailable")
    source_width, source_height = source_size
    wrong = []
    for path in transforms:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            issues = validate_document(document, "crop_transform")
            full_extent = document["crop_size"] / document["scale"]
            in_bounds = (
                document["x0"] + full_extent <= source_width + 1e-6
                and document["y0"] + full_extent <= source_height + 1e-6
            )
            get_ontology().label(document["part"], require_enabled=True)
            if issues or not in_bounds:
                wrong.append(path.name)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, OntologyError):
            wrong.append(path.name)
    return QcResult(
        "QC-010",
        "crop_transform_valid",
        not wrong,
        "all transforms valid" if not wrong else "invalid: " + ", ".join(wrong),
    )


def _binary_paths(package_root: Path) -> tuple[Path, ...]:
    paths = []
    for directory in (
        "masks",
        "masks_material",
        "masks_regions",
        "masks_derived",
        "projected",
        "protected",
    ):
        paths.extend(sorted((package_root / directory).glob("*.png")))
    return tuple(paths)


def _source_size(package_root: Path, manifest: dict | None) -> tuple[int, int] | None:
    if manifest is not None and isinstance(manifest.get("source"), dict):
        source = manifest["source"]
        width, height = source.get("source_width"), source.get("source_height")
        if isinstance(width, int) and isinstance(height, int):
            return width, height
    for name in ("source.png", "source.jpg"):
        path = package_root / name
        if path.is_file():
            with Image.open(path) as image:
                return image.size
    return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
