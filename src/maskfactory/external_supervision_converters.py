"""Role-aware MaskedWarehouse remap converters (STATIC / fixture authority).

Converts external source labels into MaskFactory PART/MATERIAL maps while
preserving coarse and ``split_required`` uncertainty as ignore (255). Never
fabricates atomic PART truth, never admits gold/calibration/holdout, and never
claims source admission or production training volume.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from .external_supervision import TRAIN_PARTITION
from .ontology import Ontology, load_ontology
from .truth_tiers import WEIGHTED_PSEUDO_LABEL

IGNORE_PIXEL = 255
PROOF_TIER = "STATIC_PASS"
AUTHORITY = "external_supervision_converter_static_only_no_admission"

MATERIAL_NAME_ALIASES = {
    "none/background": "none_background",
    "none_background": "none_background",
}

BLOCKED_SOURCES = frozenset({"swimsuit_preview", "body_archive"})
SPLIT_OR_AMBIGUOUS_ACTIONS = frozenset({"split_required", "ambiguous_do_not_use", "ignore"})


class ExternalSupervisionConverterError(ValueError):
    """Remap plan or conversion input is invalid for STATIC converter use."""


@dataclass(frozen=True)
class ConversionResult:
    part_map: np.ndarray
    material_map: np.ndarray
    ignore_mask: np.ndarray
    source: str
    ignored_source_labels: tuple[str, ...]
    mapped_source_labels: tuple[str, ...]
    training_authority: Mapping[str, Any]
    proof_tier: str = PROOF_TIER
    authority: str = AUTHORITY
    admission_ready: bool = False


def load_remap_plan(path: Path | str) -> dict[str, Any]:
    plan_path = Path(path)
    try:
        document = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ExternalSupervisionConverterError(f"remap_plan_load_failed:{exc}") from exc
    if not isinstance(document, Mapping):
        raise ExternalSupervisionConverterError("remap_plan_root_invalid")
    return dict(document)


def assert_converter_training_authority(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    source = plan.get("source")
    if not isinstance(source, str) or not source:
        raise ExternalSupervisionConverterError("remap_source_missing")
    if source in BLOCKED_SOURCES or plan.get("training_allowed") is not True:
        raise ExternalSupervisionConverterError(f"source_blocked_for_conversion:{source}")
    authority = plan.get("training_authority")
    if not isinstance(authority, Mapping):
        raise ExternalSupervisionConverterError("training_authority_missing")
    if authority.get("truth_tier") != WEIGHTED_PSEUDO_LABEL:
        raise ExternalSupervisionConverterError("training_authority_truth_tier_invalid")
    if authority.get("truth_partition") != TRAIN_PARTITION:
        raise ExternalSupervisionConverterError("training_authority_partition_invalid")
    if authority.get("holdout_eligible") is not False:
        raise ExternalSupervisionConverterError("training_authority_holdout_not_false")
    if authority.get("counts_as_human_anchor_gold") not in {None, False}:
        raise ExternalSupervisionConverterError("training_authority_gold_claim")
    if authority.get("counts_as_autonomous_certified_gold") not in {None, False}:
        raise ExternalSupervisionConverterError("training_authority_gold_claim")
    return authority


def _part_id_by_name(ontology: Ontology) -> dict[str, int]:
    return {
        label.name: int(label.id)
        for label in ontology.labels
        if label.map == "part" and label.id is not None
    }


def _material_id_by_name(ontology: Ontology) -> dict[str, int]:
    return {
        label.name: int(label.id)
        for label in ontology.labels
        if label.map == "material" and label.id is not None
    }


def _resolve_material_name(name: str) -> str:
    return MATERIAL_NAME_ALIASES.get(name, name)


def _mapping_entry(plan: Mapping[str, Any], key: str | int) -> Mapping[str, Any]:
    mappings = plan.get("mappings")
    if not isinstance(mappings, Mapping):
        raise ExternalSupervisionConverterError("mappings_missing")
    if key in mappings:
        entry = mappings[key]
    elif str(key) in mappings:
        entry = mappings[str(key)]
    else:
        raise ExternalSupervisionConverterError(f"mapping_key_unknown:{key}")
    if not isinstance(entry, Mapping):
        raise ExternalSupervisionConverterError(f"mapping_entry_invalid:{key}")
    return entry


def _apply_entry(
    *,
    entry: Mapping[str, Any],
    source_label: str,
    pixels: np.ndarray,
    part_map: np.ndarray,
    material_map: np.ndarray,
    ignore_mask: np.ndarray,
    part_ids: Mapping[str, int],
    material_ids: Mapping[str, int],
    ignored: list[str],
    mapped: list[str],
) -> None:
    action = entry.get("action")
    if not isinstance(action, str):
        raise ExternalSupervisionConverterError(f"mapping_action_invalid:{source_label}")
    parts = entry.get("part")
    materials = entry.get("material")
    if not isinstance(parts, list) or not parts:
        raise ExternalSupervisionConverterError(f"mapping_part_invalid:{source_label}")
    if not isinstance(materials, list) or not materials:
        raise ExternalSupervisionConverterError(f"mapping_material_invalid:{source_label}")

    if action in SPLIT_OR_AMBIGUOUS_ACTIONS or len(parts) != 1:
        part_map[pixels] = IGNORE_PIXEL
        ignore_mask[pixels] = True
        ignored.append(source_label)
    else:
        part_name = parts[0]
        if part_name not in part_ids:
            raise ExternalSupervisionConverterError(f"part_unknown:{part_name}")
        part_map[pixels] = part_ids[part_name]
        mapped.append(source_label)

    if len(materials) == 1:
        material_name = _resolve_material_name(str(materials[0]))
        if material_name not in material_ids:
            raise ExternalSupervisionConverterError(f"material_unknown:{material_name}")
        material_map[pixels] = material_ids[material_name]
    else:
        # Multi-material without an atomic decision stays ignore on material too.
        material_map[pixels] = IGNORE_PIXEL
        ignore_mask[pixels] = True


def convert_indexed_mask(
    plan: Mapping[str, Any],
    indexed: np.ndarray,
    *,
    ontology: Ontology | None = None,
) -> ConversionResult:
    """Convert an 8-bit indexed source map (LaPa / LV-MHP) with ignore-255 rules."""
    authority = assert_converter_training_authority(plan)
    ontology = ontology or load_ontology()
    array = np.asarray(indexed)
    if array.ndim != 2:
        raise ExternalSupervisionConverterError("indexed_mask_rank_invalid")
    if array.dtype.kind not in {"u", "i"}:
        raise ExternalSupervisionConverterError("indexed_mask_dtype_invalid")

    part_ids = _part_id_by_name(ontology)
    material_ids = _material_id_by_name(ontology)
    part_map = np.full(array.shape, IGNORE_PIXEL, dtype=np.uint8)
    material_map = np.full(array.shape, IGNORE_PIXEL, dtype=np.uint8)
    ignore_mask = np.ones(array.shape, dtype=bool)
    ignored: list[str] = []
    mapped: list[str] = []

    for value in sorted({int(v) for v in np.unique(array)}):
        entry = _mapping_entry(plan, value)
        source_label = str(entry.get("source_label") or value)
        pixels = array == value
        # Background starts as ignore; direct background mapping clears ignore.
        _apply_entry(
            entry=entry,
            source_label=source_label,
            pixels=pixels,
            part_map=part_map,
            material_map=material_map,
            ignore_mask=ignore_mask,
            part_ids=part_ids,
            material_ids=material_ids,
            ignored=ignored,
            mapped=mapped,
        )
        if entry.get("action") == "direct" and list(entry.get("part") or []) == ["background"]:
            ignore_mask[pixels] = False

    # Recompute ignore from part == 255 for honesty after all writes.
    ignore_mask = part_map == IGNORE_PIXEL
    return ConversionResult(
        part_map=part_map,
        material_map=material_map,
        ignore_mask=ignore_mask,
        source=str(plan["source"]),
        ignored_source_labels=tuple(dict.fromkeys(ignored)),
        mapped_source_labels=tuple(dict.fromkeys(mapped)),
        training_authority=dict(authority),
    )


def convert_component_mask(
    plan: Mapping[str, Any],
    component_name: str,
    binary_mask: np.ndarray,
    *,
    ontology: Ontology | None = None,
) -> ConversionResult:
    """Convert one CelebAMask-HQ-style binary component into PART/MATERIAL maps."""
    authority = assert_converter_training_authority(plan)
    ontology = ontology or load_ontology()
    mask = np.asarray(binary_mask)
    if mask.ndim != 2:
        raise ExternalSupervisionConverterError("component_mask_rank_invalid")
    foreground = mask.astype(bool)
    part_ids = _part_id_by_name(ontology)
    material_ids = _material_id_by_name(ontology)
    part_map = np.full(mask.shape, IGNORE_PIXEL, dtype=np.uint8)
    material_map = np.full(mask.shape, IGNORE_PIXEL, dtype=np.uint8)
    ignore_mask = np.ones(mask.shape, dtype=bool)
    ignored: list[str] = []
    mapped: list[str] = []
    entry = _mapping_entry(plan, component_name)
    _apply_entry(
        entry=entry,
        source_label=component_name,
        pixels=foreground,
        part_map=part_map,
        material_map=material_map,
        ignore_mask=ignore_mask,
        part_ids=part_ids,
        material_ids=material_ids,
        ignored=ignored,
        mapped=mapped,
    )
    ignore_mask = part_map == IGNORE_PIXEL
    # Background remains ignore; only foreground decisions are written.
    return ConversionResult(
        part_map=part_map,
        material_map=material_map,
        ignore_mask=ignore_mask,
        source=str(plan["source"]),
        ignored_source_labels=tuple(dict.fromkeys(ignored)),
        mapped_source_labels=tuple(dict.fromkeys(mapped)),
        training_authority=dict(authority),
    )


__all__ = [
    "AUTHORITY",
    "ConversionResult",
    "ExternalSupervisionConverterError",
    "IGNORE_PIXEL",
    "PROOF_TIER",
    "assert_converter_training_authority",
    "convert_component_mask",
    "convert_indexed_mask",
    "load_remap_plan",
]
