from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.mapping import (
    OntologySnapshotError,
    build_v1_ontology_snapshot,
    build_v2_ontology_snapshot,
    publish_ontology_snapshot,
    publish_v2_ontology_snapshot,
)
from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "configs" / "ontology.yaml"
ONTOLOGY_V2 = ROOT / "configs" / "ontology_v2.yaml"


def test_v1_snapshot_comes_from_canonical_loader_and_is_deterministic() -> None:
    first = build_v1_ontology_snapshot(ONTOLOGY)
    second = build_v1_ontology_snapshot(ONTOLOGY)
    assert first == second
    assert validate_document(first, "daz_ontology_snapshot") == ()
    assert first["ontology_version"] == "body_parts_v1"
    assert [label["id"] for label in first["part_labels"]] == list(range(56))
    assert first["enabled_part_label_count"] == 54
    assert first["disabled_part_labels"] == ["left_ear", "right_ear"]
    assert [label["id"] for label in first["material_labels"]] == list(range(16))
    assert first["material_labels"][1]["name"] == "skin"
    assert first["part_labels"][5]["name"] == "left_breast"
    assert first["part_labels"][5]["swap_partner"] == "right_breast"
    assert first["part_labels"][5]["boundary_rule_text"]
    source = yaml.safe_load(ONTOLOGY.read_text(encoding="utf-8"))
    source_names = [
        label["name"]
        for label in source["labels"]
        if label["map"] == "part" and label["id"] is not None
    ]
    assert [label["name"] for label in first["part_labels"]] == source_names


def test_v2_and_noncontiguous_part_ids_fail_closed(tmp_path: Path) -> None:
    source = yaml.safe_load(ONTOLOGY.read_text(encoding="utf-8"))
    v2 = copy.deepcopy(source)
    v2["mask_ontology_version"] = "body_parts_v2"
    path = tmp_path / "v2.yaml"
    path.write_text(yaml.safe_dump(v2, sort_keys=False), encoding="utf-8")
    with pytest.raises(OntologySnapshotError, match="ontology_version_invalid"):
        build_v1_ontology_snapshot(path)

    broken = copy.deepcopy(source)
    broken["labels"][10]["id"] = 99
    path.write_text(yaml.safe_dump(broken, sort_keys=False), encoding="utf-8")
    with pytest.raises(OntologySnapshotError, match="part_id_contract_invalid"):
        build_v1_ontology_snapshot(path)


def test_snapshot_publication_is_atomic_immutable_and_idempotent(tmp_path: Path) -> None:
    snapshot = build_v1_ontology_snapshot(ONTOLOGY)
    target, published = publish_ontology_snapshot(snapshot, tmp_path)
    assert published is True
    assert json.loads(target.read_text(encoding="utf-8")) == snapshot
    assert publish_ontology_snapshot(snapshot, tmp_path) == (target, False)
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(OntologySnapshotError, match="snapshot_immutable_conflict"):
        publish_ontology_snapshot(snapshot, tmp_path)


def test_snapshot_publication_rejects_schema_and_digest_tamper(tmp_path: Path) -> None:
    snapshot = build_v1_ontology_snapshot(ONTOLOGY)
    digest_tamper = copy.deepcopy(snapshot)
    digest_tamper["part_labels"][5]["name"] = "tampered"
    with pytest.raises(OntologySnapshotError, match="snapshot_digest_invalid"):
        publish_ontology_snapshot(digest_tamper, tmp_path)

    schema_tamper = copy.deepcopy(snapshot)
    schema_tamper["material_label_count"] = 15
    with pytest.raises(OntologySnapshotError, match="snapshot_schema_invalid"):
        publish_ontology_snapshot(schema_tamper, tmp_path)


def test_v2_inactive_snapshot_has_appended_ids_and_no_mapping_authority() -> None:
    snapshot = build_v2_ontology_snapshot(ONTOLOGY_V2)
    assert validate_document(snapshot, "daz_ontology_v2_snapshot") == ()
    assert snapshot["ontology_version"] == "body_parts_v2"
    assert snapshot["activation_status"] == "approved_design_not_active"
    assert snapshot["mapping_authority"] is False
    assert [label["id"] for label in snapshot["part_labels"]] == list(range(65))
    assert snapshot["appended_part_ids"] == list(range(56, 65))
    assert snapshot["disabled_part_labels"] == ["left_ear", "right_ear"]
    assert snapshot["snapshot_id"].startswith("ontology_v2_")


def test_v2_snapshot_refuses_v1_source_and_v1_path_leakage(tmp_path: Path) -> None:
    with pytest.raises(OntologySnapshotError, match="ontology_version_invalid"):
        build_v2_ontology_snapshot(ONTOLOGY)
    with pytest.raises(OntologySnapshotError, match="ontology_version_invalid"):
        build_v1_ontology_snapshot(ONTOLOGY_V2)

    snapshot = build_v2_ontology_snapshot(ONTOLOGY_V2)
    v1_root = tmp_path / "body_parts_v1" / "ontology_snapshots"
    with pytest.raises(OntologySnapshotError, match="v2_v1_path_leakage"):
        publish_v2_ontology_snapshot(snapshot, v1_root)

    target, published = publish_v2_ontology_snapshot(
        snapshot, tmp_path / "body_parts_v2" / "ontology_snapshots"
    )
    assert published is True
    assert target.is_file()
    assert publish_v2_ontology_snapshot(
        snapshot, tmp_path / "body_parts_v2" / "ontology_snapshots"
    ) == (target, False)

    authority_tamper = copy.deepcopy(snapshot)
    authority_tamper["mapping_authority"] = True
    with pytest.raises(OntologySnapshotError, match="v2_mapping_authority_forbidden"):
        publish_v2_ontology_snapshot(
            authority_tamper, tmp_path / "body_parts_v2" / "leak_authority"
        )


def test_cli_publishes_and_returns_stable_error_code(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "daz",
            "mappings",
            "ontology-snapshot",
            "--source",
            str(ONTOLOGY),
            "--output",
            str(tmp_path / "snapshots"),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["snapshot"]["part_label_count"] == 56
    assert Path(payload["data"]["publication"]["path"]).is_file()

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("mask_ontology_version: wrong\nlabels: []\n", encoding="utf-8")
    refused = runner.invoke(
        main,
        [
            "daz",
            "mappings",
            "ontology-snapshot",
            "--source",
            str(invalid),
            "--output",
            str(tmp_path / "refused"),
        ],
    )
    assert refused.exit_code == 86
    assert json.loads(refused.output)["code"] == 86
