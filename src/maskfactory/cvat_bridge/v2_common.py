"""Inactive body_parts_v2 CVAT authority shared by project, push, and pull.

The active production bridge remains body_parts_v1.  This module deliberately
uses separate configuration, mappings, task records, and a 66-label PART-only
scope so a pilot can never mutate or silently reuse an open v1 task.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..ontology import Ontology, load_ontology
from ..ontology_v2 import (
    DEFAULT_ONTOLOGY_V2,
    DEFAULT_PROPOSAL,
    load_v2_proposal,
)
from ..ontology_v2_manifest import V2_REVIEW_STATES
from .client import CvatApiError, load_cvat_config

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_V2_CONFIG = ROOT / "configs" / "cvat_v2.yaml"
V1_PROJECT_NAME = "MaskFactory_body_parts_v1"
V2_ONTOLOGY_VERSION = "body_parts_v2"
V2_ATTRIBUTE_NAMES = ("visibility", "review_complete", "notes")
V2_VISIBILITY_ORDER = (
    "visible",
    "partially_visible",
    "occluded",
    "occluded_by_clothing",
    "cropped_out",
    "not_visible",
    "not_applicable",
    "unreviewed_for_v2",
    "ambiguous_do_not_use",
)


class CvatV2Error(CvatApiError):
    """The isolated v2 project or annotation contract is unsafe."""


@dataclass(frozen=True)
class V2CvatLabel:
    id: int
    name: str
    color: str
    attributes: dict[str, int]


def load_v2_ontology(path: Path | str = DEFAULT_ONTOLOGY_V2) -> Ontology:
    ontology = load_ontology(path)
    if ontology.version != V2_ONTOLOGY_VERSION:
        raise CvatV2Error(f"CVAT v2 ontology must be {V2_ONTOLOGY_VERSION}")
    # Disabled v1 ears still occupy immutable IDs 54/55 and must receive an
    # explicit v2 review state; enabled_only would silently collapse the scope.
    parts = ontology.labels_for_map("part")
    if len(parts) != 66 or [label.id for label in parts] != list(range(66)):
        raise CvatV2Error("CVAT v2 requires exactly the append-only PART IDs 0..65")
    return ontology


def v2_part_names(ontology: Ontology | None = None) -> tuple[str, ...]:
    authority = ontology or load_v2_ontology()
    return tuple(label.name for label in authority.labels_for_map("part"))


def v2_alias_help() -> dict[str, dict[str, str | None]]:
    proposal = load_v2_proposal(DEFAULT_PROPOSAL)
    return {
        str(alias): {
            "canonical": str(record["canonical"]),
            "kind": str(record.get("kind", "atomic")),
            "warning": None if record.get("warning") is None else str(record["warning"]),
        }
        for alias, record in sorted(proposal["aliases"].items())
    }


def v2_alias_help_text() -> str:
    entries = []
    for alias, record in v2_alias_help().items():
        text = f"{alias} -> {record['canonical']}"
        if record["warning"]:
            text += f" ({record['warning']})"
        entries.append(text)
    return "; ".join(entries)


def resolve_root_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_v2_cvat_config(path: Path | str = DEFAULT_V2_CONFIG) -> dict[str, Any]:
    config_path = Path(path)
    config = load_cvat_config(config_path)
    project = config.get("project")
    if not isinstance(project, Mapping):
        raise CvatV2Error("CVAT v2 config requires a project mapping")
    project_name = project.get("name")
    if not isinstance(project_name, str) or not project_name.strip():
        raise CvatV2Error("CVAT v2 project requires a non-empty name")
    if project_name == V1_PROJECT_NAME or "body_parts_v2" not in project_name:
        raise CvatV2Error("CVAT v2 project name must be versioned and distinct from v1")
    exact = {
        "ontology_version": V2_ONTOLOGY_VERSION,
        "label_scope": "part_ids_0_65",
        "label_source": "configs/ontology_v2.yaml",
        "color_source": "configs/viz_v2.yaml",
    }
    for key, expected in exact.items():
        if project.get(key) != expected:
            raise CvatV2Error(f"CVAT v2 project {key} must equal {expected!r}")
    mapping = resolve_root_path(str(project.get("label_mapping_file", ""))).resolve()
    tasks = resolve_root_path(str(project.get("task_records_dir", ""))).resolve()
    v1_mapping = (ROOT / "data" / "cvat" / "label_mapping.json").resolve()
    v1_tasks = (ROOT / "data" / "cvat" / "tasks").resolve()
    if mapping == v1_mapping or tasks == v1_tasks:
        raise CvatV2Error("CVAT v2 mapping/task records must not reuse v1 storage")
    config["_config_path"] = str(config_path.resolve())
    config["_mapping_path"] = str(mapping)
    config["_task_records_dir"] = str(tasks)
    return config


class V2CvatLabelMap:
    """Strict canonical mapping for the 66 PART labels and v2 state attributes."""

    def __init__(self, labels: list[dict[str, Any]], *, ontology: Ontology | None = None) -> None:
        authority = ontology or load_v2_ontology()
        expected = set(v2_part_names(authority))
        aliases = set(v2_alias_help())
        by_name: dict[str, V2CvatLabel] = {}
        by_id: dict[int, V2CvatLabel] = {}
        for raw in labels:
            try:
                label_id = int(raw["id"])
                name = str(raw["name"])
                color = str(raw["color"])
                attributes = {
                    str(attribute["name"]): int(attribute["id"])
                    for attribute in raw.get("attributes", [])
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise CvatV2Error(f"invalid CVAT v2 label record: {raw!r}") from exc
            if name in aliases:
                raise CvatV2Error(f"CVAT v2 aliases may be help text only: {name!r}")
            if name in by_name or label_id in by_id:
                raise CvatV2Error(f"duplicate CVAT v2 label name/id: {name}/{label_id}")
            record = V2CvatLabel(label_id, name, color, attributes)
            by_name[name] = record
            by_id[label_id] = record
        missing = sorted(expected - set(by_name))
        extra = sorted(set(by_name) - expected)
        if missing or extra:
            raise CvatV2Error(f"CVAT v2 label drift; missing={missing}, extra={extra}")
        wrong = sorted(
            name
            for name, label in by_name.items()
            if set(label.attributes) != set(V2_ATTRIBUTE_NAMES)
        )
        if wrong:
            raise CvatV2Error("CVAT v2 attribute drift: " + ", ".join(wrong))
        self._by_name = by_name
        self._by_id = by_id

    def cvat_id(self, name: str) -> int:
        try:
            return self._by_name[name].id
        except KeyError as exc:
            raise CvatV2Error(f"unknown canonical CVAT v2 label: {name!r}") from exc

    def ontology_name(self, label_id: int) -> str:
        try:
            return self._by_id[int(label_id)].name
        except (KeyError, ValueError) as exc:
            raise CvatV2Error(f"unknown CVAT v2 label id: {label_id}") from exc

    def attribute_id(self, name: str, attribute: str) -> int:
        try:
            return self._by_name[name].attributes[attribute]
        except KeyError as exc:
            raise CvatV2Error(f"unknown CVAT v2 attribute {attribute!r} for {name!r}") from exc

    def as_document(self, *, project_id: int, project_name: str) -> dict[str, Any]:
        return {
            "schema_version": "2.0.0",
            "ontology_version": V2_ONTOLOGY_VERSION,
            "label_scope": "part_ids_0_65",
            "project_id": int(project_id),
            "project_name": project_name,
            "aliases_help_only": v2_alias_help(),
            "labels": {
                name: {
                    "cvat_id": label.id,
                    "color": label.color,
                    "attributes": label.attributes,
                }
                for name, label in sorted(self._by_name.items())
            },
        }


def mapping_from_document(document: Mapping[str, Any]) -> tuple[int, V2CvatLabelMap]:
    if (
        document.get("schema_version") != "2.0.0"
        or document.get("ontology_version") != V2_ONTOLOGY_VERSION
        or document.get("label_scope") != "part_ids_0_65"
    ):
        raise CvatV2Error("CVAT v2 mapping metadata is invalid")
    labels_document = document.get("labels")
    if not isinstance(labels_document, Mapping):
        raise CvatV2Error("CVAT v2 mapping labels are missing")
    labels = []
    for name, raw in labels_document.items():
        if not isinstance(raw, Mapping):
            raise CvatV2Error(f"CVAT v2 mapping entry is invalid: {name!r}")
        attributes = raw.get("attributes")
        if not isinstance(attributes, Mapping):
            raise CvatV2Error(f"CVAT v2 mapping attributes are invalid: {name!r}")
        labels.append(
            {
                "id": raw.get("cvat_id"),
                "name": name,
                "color": raw.get("color"),
                "attributes": [
                    {"name": attribute, "id": attribute_id}
                    for attribute, attribute_id in attributes.items()
                ],
            }
        )
    try:
        project_id = int(document["project_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CvatV2Error("CVAT v2 mapping project_id is invalid") from exc
    return project_id, V2CvatLabelMap(labels)


def load_v2_mapping(config: Mapping[str, Any]) -> tuple[int, V2CvatLabelMap]:
    path = Path(str(config["_mapping_path"]))
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CvatV2Error(f"cannot load CVAT v2 mapping {path}: {exc}") from exc
    if not isinstance(document, Mapping):
        raise CvatV2Error("CVAT v2 mapping root must be an object")
    return mapping_from_document(document)


def canonical_v2_state(value: Any) -> str:
    state = str(value)
    if state not in V2_REVIEW_STATES or state not in V2_VISIBILITY_ORDER:
        raise CvatV2Error(f"unknown or non-canonical CVAT v2 visibility state: {state!r}")
    return state
