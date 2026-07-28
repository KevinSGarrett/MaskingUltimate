import json
from pathlib import Path

import numpy as np
import pytest

from maskfactory.cvat_bridge.autonomy_publish import publish_autonomous_review_draft
from maskfactory.cvat_bridge.client import CvatApiError, load_cvat_config
from maskfactory.cvat_bridge.push import _load_mapping
from maskfactory.io.png_strict import write_label_map


def _draft(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    root.mkdir()
    label_map = np.zeros((20, 30), dtype=np.uint16)
    label_map[5:12, 8:16] = 18
    write_label_map(root / "label_map_part.png", label_map, bits=16)
    (root / "report.json").write_text(
        json.dumps(
            {
                "authority": "machine_generated_review_draft_non_gold",
                "authoritative_human_gold": False,
                "human_gold_approval_required": True,
                "promoted_for_human_review": True,
            }
        )
    )
    return root


class FakeClient:
    def __init__(self, annotations):
        self.annotations = annotations
        self.puts = []

    def request(self, method, path, *, payload=None, **_kwargs):
        if method == "GET" and path == "/api/tasks/23":
            return {"id": 23, "state": "annotation"}
        if method == "GET" and path == "/api/tasks/23/annotations":
            return self.annotations
        if method == "PUT" and path == "/api/tasks/23/annotations":
            self.puts.append(payload)
            self.annotations = payload
            return None
        raise AssertionError((method, path))


def test_autonomous_publication_backs_up_replaces_only_auto_parts_and_stays_non_gold(
    tmp_path: Path, monkeypatch
):
    _project, mapping = _load_mapping(load_cvat_config(Path("configs/cvat.yaml")))
    auto_part = {
        "type": "mask",
        "frame": 0,
        "label_id": mapping.cvat_id("left_forearm"),
        "points": [0, 1, 0, 0, 0, 0],
        "source": "auto",
    }
    retained = {
        "type": "mask",
        "frame": 0,
        "label_id": mapping.cvat_id("skin"),
        "points": [0, 1, 0, 0, 0, 0],
        "source": "manual",
    }
    client = FakeClient({"version": 7, "tags": [], "shapes": [auto_part, retained], "tracks": []})
    monkeypatch.setattr(
        "maskfactory.cvat_bridge.autonomy_publish._export_backup",
        lambda _client, _task_id: b"PK\x03\x04fixture",
    )

    result = publish_autonomous_review_draft(
        client,
        task_id=23,
        review_draft_dir=_draft(tmp_path),
        audit_dir=tmp_path / "audit",
        config_path=Path("configs/cvat.yaml"),
    )

    assert result["status"] == "published_reversible_non_gold_review_draft"
    assert result["authoritative_human_gold"] is False
    assert result["replaced_automatic_part_shape_count"] == 1
    assert retained in client.annotations["shapes"]
    assert any(
        shape["label_id"] == mapping.cvat_id("left_forearm") and shape["source"] == "auto"
        for shape in client.annotations["shapes"]
    )
    assert (tmp_path / "audit/task_23/task_backup_before.zip").is_file()
    assert len(client.puts) == 1


def test_autonomous_publication_refuses_to_overwrite_a_human_edited_part(tmp_path: Path):
    _project, mapping = _load_mapping(load_cvat_config(Path("configs/cvat.yaml")))
    client = FakeClient(
        {
            "version": 2,
            "tags": [],
            "shapes": [
                {
                    "type": "mask",
                    "frame": 0,
                    "label_id": mapping.cvat_id("left_forearm"),
                    "points": [0, 1, 0, 0, 0, 0],
                    "source": "manual",
                }
            ],
            "tracks": [],
        }
    )

    with pytest.raises(CvatApiError, match="human-edited"):
        publish_autonomous_review_draft(
            client,
            task_id=23,
            review_draft_dir=_draft(tmp_path),
            audit_dir=tmp_path / "audit",
            config_path=Path("configs/cvat.yaml"),
        )
    assert client.puts == []
