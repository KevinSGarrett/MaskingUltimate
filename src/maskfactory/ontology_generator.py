"""Deterministically generate configs/ontology.yaml from ontology_source.py."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .ontology_source import (
    BOUNDARY_RULES,
    DERIVED_FORMULAS,
    DERIVED_UNIONS,
    LEFT_RIGHT_CONVENTION,
    MATERIAL_LABELS,
    ONTOLOGY_VERSION,
    PART_LABELS,
    PROJECTED_REGISTRY,
    PROTECTED_CLASSES,
    REGION_BANDS,
    VISIBILITY_STATES,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "configs" / "ontology.yaml"


def _side(name: str) -> str:
    if name.startswith("left_"):
        return "left"
    if name.startswith("right_"):
        return "right"
    return "center"


def _swap(name: str) -> str | None:
    if name.startswith("left_"):
        return "right_" + name.removeprefix("left_")
    if name.startswith("right_"):
        return "left_" + name.removeprefix("right_")
    return None


def _source_label(label: Any) -> dict[str, Any]:
    result = asdict(label)
    area = result["expected_area_pct_range"]
    result["expected_area_pct_range"] = list(area) if area is not None else None
    return result


def _registry_label(
    name: str,
    mask_type: str,
    *,
    enabled: bool = True,
    max_components: int | None = None,
    boundary_rule: str,
    formula: str | None = None,
) -> dict[str, Any]:
    result = {
        "id": None,
        "name": name,
        "mask_type": mask_type,
        "map": "none",
        "side": _side(name),
        "parent_union": None,
        "enabled": enabled,
        "expected_area_pct_range": None,
        "max_components": max_components,
        "exclusivity_group": None,
        "swap_partner": _swap(name),
        "visibility_default": "n/a",
        "boundary_rule": boundary_rule,
    }
    if formula is not None:
        result["formula"] = formula
    return result


def build_ontology() -> dict[str, Any]:
    labels = [_source_label(label) for label in (*PART_LABELS, *MATERIAL_LABELS)]
    for entry in REGION_BANDS:
        labels.append(
            _registry_label(
                entry["name"],
                "region_band",
                enabled="optional" not in entry["definition"],
                max_components=8,
                boundary_rule="visible_contour",
            )
        )
    for name in DERIVED_UNIONS:
        labels.append(
            _registry_label(
                name,
                "derived_union",
                boundary_rule="script_formula",
                formula=DERIVED_FORMULAS[name],
            )
        )
    for entry in PROJECTED_REGISTRY:
        if entry["kind"] == "template":
            continue
        labels.append(
            _registry_label(
                entry["name"],
                "projected_amodal",
                max_components=4,
                boundary_rule="geometry_projected",
            )
        )
    names = [label["name"] for label in labels]
    if len(names) != len(set(names)):
        raise ValueError("ontology source produces duplicate label names")
    return {
        "config_version": "1.0.0",
        "mask_ontology_version": ONTOLOGY_VERSION,
        "left_right_convention": LEFT_RIGHT_CONVENTION,
        "visible_pixel_only": True,
        "visibility_states": list(VISIBILITY_STATES),
        "labels": labels,
        "protected_classes": list(PROTECTED_CLASSES),
        "boundary_rules": BOUNDARY_RULES,
        "projected_templates": [
            entry["name"] for entry in PROJECTED_REGISTRY if entry["kind"] == "template"
        ],
    }


def render_ontology() -> str:
    return yaml.safe_dump(build_ontology(), sort_keys=False, allow_unicode=True, width=100)


def generate_ontology(path: Path = DEFAULT_OUTPUT) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_ontology(), encoding="utf-8")
    return path


def ontology_is_current(path: Path = DEFAULT_OUTPUT) -> bool:
    path = Path(path)
    return path.is_file() and path.read_text(encoding="utf-8") == render_ontology()
