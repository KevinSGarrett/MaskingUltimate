"""Strict loader for the generated ontology; the only runtime label authority."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .ontology_generator import DEFAULT_OUTPUT


class OntologyError(ValueError):
    """Raised when ontology data or a label reference is invalid."""


@dataclass(frozen=True)
class Label:
    id: int | None
    name: str
    mask_type: str
    map: str
    side: str
    parent_union: str | None
    enabled: bool
    expected_area_pct_range: tuple[float, float] | None
    max_components: int | None
    exclusivity_group: str | None
    swap_partner: str | None
    visibility_default: str
    boundary_rule: str | None = None
    formula: str | None = None


class Ontology:
    """Validated immutable ontology with hard-failing label lookups."""

    def __init__(self, document: dict[str, Any], *, source: Path) -> None:
        self.source = source
        self.version = _required_string(document, "mask_ontology_version")
        raw_labels = document.get("labels")
        if not isinstance(raw_labels, list) or not raw_labels:
            raise OntologyError("ontology labels must be a non-empty list")

        labels = tuple(_parse_label(item) for item in raw_labels)
        self._by_name = _unique_index(labels, lambda label: label.name, "label name")
        self._by_map_id: dict[tuple[str, int], Label] = {}
        for label in labels:
            if label.id is None:
                continue
            key = (label.map, label.id)
            if key in self._by_map_id:
                raise OntologyError(f"duplicate map/id pair: {label.map}/{label.id}")
            self._by_map_id[key] = label
        for label in labels:
            if label.swap_partner is not None and label.swap_partner not in self._by_name:
                raise OntologyError(
                    f"label {label.name!r} has unknown swap_partner {label.swap_partner!r}"
                )
        self.labels = labels
        raw_boundary_rules = document.get("boundary_rules", {})
        if not isinstance(raw_boundary_rules, dict):
            raise OntologyError("ontology boundary_rules must be an object")
        self._boundary_rules: dict[str, str] = {}
        for name, record in raw_boundary_rules.items():
            if (
                not isinstance(name, str)
                or not isinstance(record, dict)
                or not isinstance(record.get("rule"), str)
                or not record["rule"].strip()
            ):
                raise OntologyError(f"invalid ontology boundary rule: {name!r}")
            self._boundary_rules[name] = record["rule"].strip()
        for label in labels:
            if label.boundary_rule is not None and label.boundary_rule not in self._boundary_rules:
                raise OntologyError(
                    f"label {label.name!r} has unknown boundary_rule {label.boundary_rule!r}"
                )

    def label(self, name: str, *, require_enabled: bool = False) -> Label:
        """Resolve a label name or raise; unknown labels are never tolerated."""
        try:
            label = self._by_name[name]
        except KeyError as exc:
            raise OntologyError(f"unknown ontology label: {name!r}") from exc
        if require_enabled and not label.enabled:
            raise OntologyError(f"ontology label is disabled: {name!r}")
        return label

    def label_for_id(self, map_name: str, label_id: int) -> Label:
        """Resolve an indexed-map ID or raise."""
        try:
            return self._by_map_id[(map_name, label_id)]
        except KeyError as exc:
            raise OntologyError(f"unknown ontology map/id: {map_name}/{label_id}") from exc

    def labels_for_map(self, map_name: str, *, enabled_only: bool = False) -> tuple[Label, ...]:
        labels = tuple(label for label in self.labels if label.map == map_name)
        if not labels:
            raise OntologyError(f"unknown or empty ontology map: {map_name!r}")
        return tuple(label for label in labels if label.enabled) if enabled_only else labels

    def boundary_rule_text(self, name: str | None) -> str | None:
        """Resolve a boundary-rule code to the human-readable semantic contract."""
        if name is None:
            return None
        try:
            return self._boundary_rules[name]
        except KeyError as exc:
            raise OntologyError(f"unknown ontology boundary rule: {name!r}") from exc


def _required_string(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise OntologyError(f"ontology {key!r} must be a non-empty string")
    return value


def _parse_label(raw: Any) -> Label:
    if not isinstance(raw, dict):
        raise OntologyError("every ontology label must be an object")
    try:
        area = raw["expected_area_pct_range"]
        parsed_area = None if area is None else (float(area[0]), float(area[1]))
        return Label(
            id=raw["id"],
            name=raw["name"],
            mask_type=raw["mask_type"],
            map=raw["map"],
            side=raw["side"],
            parent_union=raw["parent_union"],
            enabled=raw["enabled"],
            expected_area_pct_range=parsed_area,
            max_components=raw["max_components"],
            exclusivity_group=raw["exclusivity_group"],
            swap_partner=raw["swap_partner"],
            visibility_default=raw["visibility_default"],
            boundary_rule=raw.get("boundary_rule"),
            formula=raw.get("formula"),
        )
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise OntologyError(f"invalid ontology label record: {raw!r}") from exc


def _unique_index(labels: tuple[Label, ...], key: Any, description: str) -> dict[Any, Label]:
    result: dict[Any, Label] = {}
    for label in labels:
        value = key(label)
        if value in result:
            raise OntologyError(f"duplicate {description}: {value!r}")
        result[value] = label
    return result


def load_ontology(path: Path | str = DEFAULT_OUTPUT) -> Ontology:
    """Load and validate an ontology YAML file."""
    source = Path(path)
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OntologyError(f"cannot load ontology {source}: {exc}") from exc
    if not isinstance(document, dict):
        raise OntologyError(f"ontology root must be an object: {source}")
    return Ontology(document, source=source)


@lru_cache(maxsize=1)
def get_ontology() -> Ontology:
    """Return the canonical runtime ontology singleton."""
    return load_ontology(DEFAULT_OUTPUT)
