import json
from pathlib import Path

import pytest
import yaml

from maskfactory.ontology_v2_baseline import (
    DEFAULT_SNAPSHOT,
    V1BaselineError,
    build_v1_baseline,
    verify_v1_baseline,
    write_v1_baseline,
)


def _fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "configs").mkdir(parents=True)
    (root / "data" / "cvat").mkdir(parents=True)
    (root / "models").mkdir()
    (root / "src" / "maskfactory" / "schemas").mkdir(parents=True)
    representative = (
        root
        / "data"
        / "packages"
        / "img_2ca794d19be9"
        / "instances"
        / "p0"
        / "annotations"
        / "draft_baseline"
    )
    representative.mkdir(parents=True)
    ontology = {
        "mask_ontology_version": "body_parts_v1",
        "labels": [
            {"id": index, "name": "background" if index == 0 else f"part_{index}", "map": "part"}
            for index in range(56)
        ],
    }
    (root / "configs" / "ontology.yaml").write_text(yaml.safe_dump(ontology), encoding="utf-8")
    for relative in (
        "configs/derived.yaml",
        "configs/viz.yaml",
        "configs/cvat.yaml",
        "data/cvat/label_mapping.json",
    ):
        path = root / relative
        path.write_text("fixture\n", encoding="utf-8")
    (root / "models" / "model_registry.json").write_text(
        json.dumps({"models": [{"key": "v1", "role": "champion_bodypart", "sha256": "a" * 64}]}),
        encoding="utf-8",
    )
    (root / "src" / "maskfactory" / "schemas" / "manifest.schema.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (representative / "manifest.json").write_text("{}\n", encoding="utf-8")
    (representative / "label_map_part.png").write_bytes(b"representative-v1-map")
    return root


def test_v1_baseline_is_deterministic_and_tamper_evident(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    first = build_v1_baseline(root=root)
    second = build_v1_baseline(root=root)
    assert first == second
    assert first["part_class_count_including_background"] == 56
    assert first["part_mapping"][0] == {"id": 0, "name": "background"}
    assert first["part_mapping"][-1] == {"id": 55, "name": "part_55"}
    assert first["champion_pointers"] == [
        {"key": "v1", "role": "champion_bodypart", "sha256": "a" * 64}
    ]

    snapshot = tmp_path / "baseline.json"
    write_v1_baseline(snapshot, root=root)
    assert verify_v1_baseline(snapshot, root=root)["valid"] is True
    (root / "configs" / "ontology.yaml").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(V1BaselineError, match="configs/ontology.yaml"):
        verify_v1_baseline(snapshot, root=root)


def test_live_v1_snapshot_proves_tracked_v1_bytes_and_mapping_unchanged() -> None:
    snapshot = json.loads(DEFAULT_SNAPSHOT.read_text(encoding="utf-8"))
    ontology = yaml.safe_load(Path("configs/ontology.yaml").read_text(encoding="utf-8"))
    mapping = [
        {"id": label["id"], "name": label["name"]}
        for label in ontology["labels"]
        if label["map"] == "part"
    ]
    assert snapshot["part_mapping"] == mapping
    assert snapshot["part_class_count_including_background"] == 56
    assert snapshot["active_ontology"] == "body_parts_v1"
    assert snapshot["activation_status"] == "v2_not_active"
