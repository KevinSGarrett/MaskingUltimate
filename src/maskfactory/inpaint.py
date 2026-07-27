"""Generate explicitly non-gold dilated and feathered inpaint masks."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .io.png_strict import read_mask, write_grayscale
from .ontology import Ontology, get_ontology

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "inpaint.yaml"


class InpaintError(ValueError):
    """Inpaint settings or source masks violate the derivative contract."""


def derive_inpaint(
    package_root: Path,
    *,
    labels: tuple[str, ...] = (),
    config_path: Path = DEFAULT_CONFIG,
    ontology: Ontology | None = None,
) -> tuple[Path, ...]:
    package_root = Path(package_root)
    authority = ontology or get_ontology()
    config = _load_config(config_path)
    defaults = config["defaults"]
    requested = labels or tuple(config.get("targets", ()))
    if not requested:
        raise InpaintError("no inpaint target labels configured or requested")
    manifest_path = package_root / "manifest.json"
    if not manifest_path.is_file():
        raise InpaintError(f"package manifest is required: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise InpaintError("package manifest root must be an object")

    records_by_label = {
        str(record["label"]): record
        for record in manifest.get("inpaint_derivatives", [])
        if isinstance(record, dict) and "label" in record
    }
    outputs: list[Path] = []
    for name in requested:
        authority.label(name, require_enabled=True)
        source = _find_source(package_root, name)
        mask = read_mask(source)
        if mask.ndim != 2 or not set(np.unique(mask)).issubset({0, 255}):
            raise InpaintError(f"source gold is not strict binary: {source}")
        override = config.get("overrides", {}).get(name, {})
        dilate_ref = _setting(override, defaults, "dilate_px")
        feather_ref = _setting(override, defaults, "feather_px")
        ref_scale = _setting(override, defaults, "ref_scale")
        scale = max(mask.shape) / ref_scale
        dilate_px = max(0, round(dilate_ref * scale))
        feather_px = max(0, round(feather_ref * scale))
        ramp = feathered_dilation(mask > 0, dilate_px=dilate_px, feather_px=feather_px)
        relative = Path("inpaint") / f"inpaint_{name}_d{dilate_px}f{feather_px}.png"
        target = package_root / relative
        temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}.png")
        write_grayscale(temporary, ramp, source_size=(mask.shape[1], mask.shape[0]))
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, target)
        outputs.append(target)
        records_by_label[name] = {
            "label": name,
            "file": relative.as_posix(),
            "dilate_px": dilate_px,
            "feather_px": feather_px,
            "ref_scale": ref_scale,
            "source_gold_sha256": _sha256(source),
        }
    manifest["inpaint_derivatives"] = [records_by_label[name] for name in sorted(records_by_label)]
    _write_json_atomic(manifest_path, manifest)
    return tuple(outputs)


def feathered_dilation(mask: np.ndarray, *, dilate_px: int, feather_px: int) -> np.ndarray:
    """Dilate the hard core, then add an outward linear feather ramp."""
    if mask.ndim != 2 or dilate_px < 0 or feather_px < 0:
        raise InpaintError("mask must be 2-D and radii must be non-negative")
    core = _dilate(mask.astype(bool), dilate_px)
    result = core.astype(np.uint8) * 255
    previous = core
    for distance in range(1, feather_px + 1):
        expanded = _dilate(previous, 1)
        ring = expanded & ~previous
        value = round(255 * (feather_px - distance + 1) / (feather_px + 1))
        result[ring] = value
        previous = expanded
    return result


def _dilate(mask: np.ndarray, iterations: int) -> np.ndarray:
    result = mask.copy()
    for _ in range(iterations):
        padded = np.pad(result, 1)
        result = (
            padded[1:-1, 1:-1]
            | padded[:-2, 1:-1]
            | padded[2:, 1:-1]
            | padded[1:-1, :-2]
            | padded[1:-1, 2:]
        )
    return result


def _find_source(package_root: Path, label: str) -> Path:
    for directory in ("masks", "masks_derived", "masks_regions", "protected"):
        candidate = package_root / directory / f"{label}.png"
        if candidate.is_file():
            return candidate
    raise InpaintError(f"no gold/derived binary source found for label {label!r}")


def _setting(override: dict[str, Any], defaults: dict[str, Any], key: str) -> int:
    value = override.get(key, defaults.get(key))
    if not isinstance(value, int) or value < 0 or (key == "ref_scale" and value < 1):
        raise InpaintError(f"inpaint {key} must be a valid non-negative integer")
    return value


def _load_config(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("defaults"), dict):
        raise InpaintError(f"inpaint config must contain defaults: {path}")
    if not isinstance(document.get("overrides", {}), dict):
        raise InpaintError("inpaint overrides must be a mapping")
    return document


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
