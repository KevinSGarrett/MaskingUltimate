"""Idempotent MaskFactory CVAT project provisioning."""

from __future__ import annotations

import json
import os
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import yaml

from ..ontology import get_ontology
from .client import DEFAULT_CONFIG, CvatApiError, CvatClient, load_cvat_config
from .labelmap import CvatLabelMap

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VIZ = ROOT / "configs" / "viz.yaml"


def project_label_spec(viz_path: Path = DEFAULT_VIZ) -> list[dict[str, Any]]:
    ontology = get_ontology()
    viz = yaml.safe_load(Path(viz_path).read_text(encoding="utf-8"))
    colors = viz.get("label_colors") if isinstance(viz, dict) else None
    if not isinstance(colors, dict):
        raise CvatApiError("viz config requires label_colors")
    visibility = [
        "visible",
        "partially_visible",
        "occluded",
        "cropped_out",
        "not_visible",
        "ambiguous_do_not_use",
    ]
    attributes = [
        {
            "name": "visibility",
            "mutable": True,
            "input_type": "select",
            "default_value": "not_visible",
            "values": visibility,
        },
        {
            "name": "ambiguous",
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
    return [
        {
            "name": label.name,
            "color": colors[label.name],
            "type": "mask",
            "attributes": attributes,
        }
        for label in ontology.labels
    ]


def init_project(
    client: CvatClient,
    *,
    config_path: Path = DEFAULT_CONFIG,
    viz_path: Path = DEFAULT_VIZ,
) -> dict[str, Any]:
    config = load_cvat_config(config_path)
    project_name = str(config["project"]["name"])
    projects = client.paginated("/api/projects?" + urllib.parse.urlencode({"name": project_name}))
    exact = [project for project in projects if project.get("name") == project_name]
    if len(exact) > 1:
        raise CvatApiError(f"multiple CVAT projects named {project_name!r}")
    if exact:
        project = client.request("GET", f"/api/projects/{exact[0]['id']}")
    else:
        project = client.request(
            "POST",
            "/api/projects",
            payload={"name": project_name, "labels": project_label_spec(viz_path)},
        )
    labels = project.get("labels") if isinstance(project, dict) else None
    if not isinstance(labels, list):
        labels = client.paginated(f"/api/labels?project_id={project['id']}&page_size=500")
    expected = {entry["name"]: entry for entry in project_label_spec(viz_path)}
    actual = {entry["name"]: entry for entry in labels}
    if set(actual) != set(expected):
        raise CvatApiError("existing CVAT project label set differs from ontology")
    for name, wanted in expected.items():
        current = actual[name]
        if (
            current.get("color", "").upper() != wanted["color"].upper()
            or current.get("type") != "mask"
        ):
            raise CvatApiError(f"existing CVAT label drift for {name!r}")
        wanted_attributes = {
            item["name"]: (item["input_type"], tuple(item["values"]))
            for item in wanted["attributes"]
        }
        current_attributes = {
            item["name"]: (
                item.get("input_type"),
                tuple(value for value in item.get("values", ()) if value != ""),
            )
            for item in current.get("attributes", [])
        }
        if current_attributes != wanted_attributes:
            raise CvatApiError(f"existing CVAT attribute drift for {name!r}")
    mapping = CvatLabelMap(labels)
    mapping_path = Path(config["project"]["label_mapping_file"])
    if not mapping_path.is_absolute():
        mapping_path = ROOT / mapping_path
    document = {"project_id": int(project["id"]), **mapping.as_document()}
    _write_json_atomic(mapping_path, document)
    return {"project_id": int(project["id"]), "created": not exact, "mapping": mapping_path}


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
