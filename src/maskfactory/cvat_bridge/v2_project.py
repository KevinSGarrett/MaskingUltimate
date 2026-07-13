"""Provision the isolated, inactive body_parts_v2 CVAT pilot project."""

from __future__ import annotations

import json
import os
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import yaml

from ..ontology_v2 import DEFAULT_VIZ_V2
from .client import CvatClient
from .v2_common import (
    DEFAULT_V2_CONFIG,
    V2_ATTRIBUTE_NAMES,
    V2_VISIBILITY_ORDER,
    CvatV2Error,
    V2CvatLabelMap,
    load_v2_cvat_config,
    load_v2_ontology,
)


def v2_project_label_spec(viz_path: Path | str = DEFAULT_VIZ_V2) -> list[dict[str, Any]]:
    ontology = load_v2_ontology()
    try:
        viz = yaml.safe_load(Path(viz_path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CvatV2Error(f"cannot load CVAT v2 colors: {exc}") from exc
    colors = viz.get("label_colors") if isinstance(viz, dict) else None
    if not isinstance(colors, dict):
        raise CvatV2Error("CVAT v2 viz config requires label_colors")
    attributes = [
        {
            "name": "visibility",
            "mutable": True,
            "input_type": "select",
            "default_value": "unreviewed_for_v2",
            "values": list(V2_VISIBILITY_ORDER),
        },
        {
            "name": "review_complete",
            "mutable": True,
            "input_type": "checkbox",
            "default_value": "false",
            "values": [],
        },
        {
            "name": "notes",
            "mutable": True,
            "input_type": "text",
            "default_value": "",
            "values": [],
        },
    ]
    result = []
    for label in ontology.labels_for_map("part"):
        color = colors.get(label.name)
        if not isinstance(color, str) or not color.startswith("#"):
            raise CvatV2Error(f"CVAT v2 color missing for {label.name!r}")
        result.append(
            {
                "name": label.name,
                # "any" permits one state tag plus zero-or-more mask shapes for the
                # same canonical label; null-mask states must still be representable.
                "type": "any",
                "color": color,
                "attributes": [dict(attribute) for attribute in attributes],
            }
        )
    if len(result) != 65:
        raise CvatV2Error("CVAT v2 project spec must contain exactly 65 PART labels")
    return result


def init_v2_project(
    client: CvatClient,
    *,
    config_path: Path | str = DEFAULT_V2_CONFIG,
    viz_path: Path | str = DEFAULT_VIZ_V2,
) -> dict[str, Any]:
    config = load_v2_cvat_config(config_path)
    project_config = config["project"]
    project_name = str(project_config["name"])
    projects = client.paginated("/api/projects?" + urllib.parse.urlencode({"name": project_name}))
    exact = [project for project in projects if project.get("name") == project_name]
    if len(exact) > 1:
        raise CvatV2Error(f"multiple CVAT v2 projects named {project_name!r}")
    expected = v2_project_label_spec(viz_path)
    if exact:
        project = client.request("GET", f"/api/projects/{exact[0]['id']}")
    else:
        project = client.request(
            "POST", "/api/projects", payload={"name": project_name, "labels": expected}
        )
    if not isinstance(project, dict) or "id" not in project:
        raise CvatV2Error("CVAT v2 project response is invalid")
    labels = project.get("labels")
    if not isinstance(labels, list):
        labels = client.paginated(f"/api/labels?project_id={project['id']}&page_size=500")
    _validate_live_labels(labels, expected)
    mapping = V2CvatLabelMap(labels)
    mapping_path = Path(config["_mapping_path"])
    _write_json_atomic(
        mapping_path,
        mapping.as_document(project_id=int(project["id"]), project_name=project_name),
    )
    return {
        "project_id": int(project["id"]),
        "project_name": project_name,
        "created": not exact,
        "mapping": mapping_path,
        "label_count": 65,
        "v1_project_untouched": True,
    }


def _validate_live_labels(labels: list[dict[str, Any]], expected: list[dict[str, Any]]) -> None:
    wanted = {entry["name"]: entry for entry in expected}
    actual = {str(entry.get("name")): entry for entry in labels}
    if set(actual) != set(wanted):
        raise CvatV2Error("existing CVAT v2 project label set differs from ontology-v2")
    for name, specification in wanted.items():
        current = actual[name]
        if (
            current.get("type") != "any"
            or str(current.get("color", "")).upper() != str(specification["color"]).upper()
        ):
            raise CvatV2Error(f"existing CVAT v2 label drift for {name!r}")
        wanted_attributes = {
            item["name"]: (item["input_type"], tuple(item["values"]))
            for item in specification["attributes"]
        }
        current_attributes = {
            str(item.get("name")): (
                item.get("input_type"),
                tuple(value for value in item.get("values", ()) if value != ""),
            )
            for item in current.get("attributes", [])
        }
        if (
            set(current_attributes) != set(V2_ATTRIBUTE_NAMES)
            or current_attributes != wanted_attributes
        ):
            raise CvatV2Error(f"existing CVAT v2 attribute drift for {name!r}")


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
