import json
from pathlib import Path

from maskfactory.cvat_bridge.project import init_project, project_label_spec


class FakeCvat:
    def __init__(self, existing: bool = False) -> None:
        self.existing = existing
        self.posts = []
        self.labels = []
        for index, spec in enumerate(project_label_spec()):
            self.labels.append(
                {
                    **spec,
                    "id": index + 1,
                    "attributes": [
                        {**attribute, "id": index * 3 + offset + 1}
                        for offset, attribute in enumerate(spec["attributes"])
                    ],
                }
            )

    def paginated(self, path: str):
        if path.startswith("/api/projects?"):
            return [{"id": 42, "name": "MaskFactory_body_parts_v1"}] if self.existing else []
        if path.startswith("/api/labels?"):
            return self.labels
        raise AssertionError(path)

    def request(self, method: str, path: str, *, payload=None):
        if method == "POST":
            self.posts.append(payload)
            return {"id": 42, "name": payload["name"], "labels": self.labels}
        assert method == "GET" and path == "/api/projects/42"
        return {"id": 42, "name": "MaskFactory_body_parts_v1", "labels": self.labels}


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "cvat.yaml"
    path.write_text(
        "api_url: http://localhost:8080\n"
        "project:\n"
        "  name: MaskFactory_body_parts_v1\n"
        f"  label_mapping_file: '{(tmp_path / 'mapping.json').as_posix()}'\n",
        encoding="utf-8",
    )
    return path


def test_project_spec_has_all_labels_colors_mask_type_and_attributes() -> None:
    labels = project_label_spec()
    assert len(labels) == 135
    assert all(label["type"] == "mask" for label in labels)
    assert all(label["color"].startswith("#") for label in labels)
    assert all(
        [attribute["name"] for attribute in label["attributes"]]
        == ["visibility", "ambiguous", "notes"]
        for label in labels
    )
    visibility = labels[0]["attributes"][0]
    assert visibility["values"] == [
        "visible",
        "partially_visible",
        "occluded",
        "cropped_out",
        "not_visible",
        "ambiguous_do_not_use",
    ]


def test_init_project_creates_once_then_validates_and_persists_mapping(tmp_path: Path) -> None:
    config = _config(tmp_path)
    created_client = FakeCvat(existing=False)
    result = init_project(created_client, config_path=config)
    assert result["created"] is True
    assert len(created_client.posts) == 1
    mapping = json.loads((tmp_path / "mapping.json").read_text(encoding="utf-8"))
    assert mapping["project_id"] == 42
    assert len(mapping["labels"]) == 135

    existing_client = FakeCvat(existing=True)
    result = init_project(existing_client, config_path=config)
    assert result["created"] is False
    assert existing_client.posts == []
