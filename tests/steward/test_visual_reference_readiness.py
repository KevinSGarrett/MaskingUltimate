from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from maskfactory.steward.visual_reference_readiness import (
    VisualReferenceReadinessError,
    build_visual_reference_readiness,
    validate_visual_reference_readiness,
)


def _json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _library(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE images(relative_path TEXT);
        CREATE TABLE pipeline_meta(key TEXT, value_json TEXT);
        CREATE TABLE selections(relative_path TEXT, tier TEXT);
        CREATE TABLE visual_index(
            relative_path TEXT,
            model_id TEXT,
            person_count TEXT,
            framing TEXT,
            view TEXT,
            pose TEXT,
            content_state TEXT,
            presentation TEXT,
            body_type TEXT,
            background TEXT,
            lighting TEXT,
            difficulty_score REAL,
            tags_json TEXT,
            status TEXT
        );
        """
    )
    connection.execute("INSERT INTO images VALUES ('sample.png')")
    meta = {
        "content_policy": {"content_state_is_organizational_only": True},
        "library_purpose": {
            "body_part_focus_tags": ["part_hand_fingers", "part_foot_toes"],
            "classifier_version": "test-v1",
        },
        "selection": {"sets_are_disjoint": True},
    }
    connection.executemany(
        "INSERT INTO pipeline_meta VALUES (?, ?)",
        [(key, json.dumps(value)) for key, value in meta.items()],
    )
    connection.execute("INSERT INTO selections VALUES ('sample.png', 'benchmark_reference')")
    connection.execute(
        """
        INSERT INTO visual_index VALUES(
            'sample.png', 'test-model', 'one', 'full_body', 'front',
            'standing', 'clothed', 'unclear', 'average', 'plain_studio',
            'even', 0.5, '["part_hand_fingers","part_foot_toes"]', 'valid'
        )
        """
    )
    connection.commit()
    connection.close()


def _inventory(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE images(relative_path TEXT, status TEXT);
        CREATE TABLE runs(id INTEGER);
        INSERT INTO images VALUES ('sample.png', 'valid');
        """
    )
    connection.commit()
    connection.close()


def _build(tmp_path: Path) -> dict:
    summary = tmp_path / "summary.json"
    inventory = tmp_path / "inventory.sqlite"
    library = tmp_path / "library.sqlite"
    registry = tmp_path / "registry.json"
    crosswalk = tmp_path / "crosswalk.json"
    _json(
        summary,
        {
            "total_images": 1,
            "status_counts": {"valid": 1, "invalid": 0},
            "source_files_modified": 0,
            "content_hint_is_organizational_only": True,
        },
    )
    _inventory(inventory)
    _library(library)
    source_root = tmp_path / "dataset"
    annotation = source_root / "annotations.json"
    source_root.mkdir()
    annotation.write_text("{}", encoding="utf-8")
    annotation_sha = hashlib.sha256(annotation.read_bytes()).hexdigest()
    _json(
        registry,
        {
            "schema_version": "test",
            "root": str(tmp_path),
            "datasets": [
                {
                    "path": str(source_root),
                    "annotation_files": [
                        {"path": "dataset/annotations.json", "sha256": annotation_sha}
                    ],
                    "bbox_annotations": 1,
                    "segmentation_annotations": 0,
                }
            ],
        },
    )
    _json(crosswalk, {"schema_version": "test"})
    return build_visual_reference_readiness(
        inventory_summary=summary,
        inventory_database=inventory,
        library_database=library,
        dataset_registry=registry,
        ontology_crosswalk=crosswalk,
        observed_at_utc="2026-07-27T00:00:00Z",
    )


def test_builds_hash_bound_reference_only_readiness(tmp_path: Path) -> None:
    receipt = _build(tmp_path)
    validate_visual_reference_readiness(receipt)
    assert receipt["authority_boundary"]["promotion_allowed"] is False
    assert receipt["readiness"]["ready_for_visual_qualification"] is False
    assert receipt["readiness"]["ready_for_source_bound_candidate_screening"]
    assert receipt["readiness"]["ready_for_source_bound_candidate_selection"] is False
    assert receipt["readiness"]["metadata_candidate_selection_requires_direct_visual_confirmation"]
    assert receipt["readiness"]["all_declared_body_part_focus_tags_represented"]
    assert receipt["annotation_registry"]["annotation_files_verified"] == 1
    assert receipt["reference_library"]["benchmark_body_part_tag_counts"] == {
        "part_foot_toes": 1,
        "part_hand_fingers": 1,
    }
    assert all(source["sha256"] and source["bytes"] > 0 for source in receipt["sources"].values())


def test_validator_rejects_authority_escalation(tmp_path: Path) -> None:
    receipt = _build(tmp_path)
    receipt["authority_boundary"]["promotion_allowed"] = True
    with pytest.raises(
        VisualReferenceReadinessError,
        match="self hash mismatch",
    ):
        validate_visual_reference_readiness(receipt)


def test_validator_rejects_critic_catalog_byte_drift(tmp_path: Path) -> None:
    receipt = _build(tmp_path)
    catalog_path = Path(receipt["sources"]["critic_catalog"]["path"])
    with pytest.raises(
        VisualReferenceReadinessError,
        match="critic catalog source drifted",
    ):
        validate_visual_reference_readiness(
            receipt,
            critic_catalog_bytes=catalog_path.read_bytes() + b"\n# drift\n",
        )


def test_builder_reports_missing_declared_tag(tmp_path: Path) -> None:
    receipt = _build(tmp_path)
    assert not receipt["reference_library"]["benchmark_missing_body_part_focus_tags"]
    database = Path(receipt["sources"]["library_database"]["path"])
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE pipeline_meta SET value_json = ? WHERE key = 'library_purpose'",
        (
            json.dumps(
                {
                    "body_part_focus_tags": [
                        "part_hand_fingers",
                        "part_foot_toes",
                        "part_missing",
                    ],
                    "classifier_version": "test-v1",
                }
            ),
        ),
    )
    connection.commit()
    connection.close()
    rebuilt = build_visual_reference_readiness(
        inventory_summary=Path(receipt["sources"]["inventory_summary"]["path"]),
        inventory_database=Path(receipt["sources"]["inventory_database"]["path"]),
        library_database=database,
        dataset_registry=Path(receipt["sources"]["dataset_registry"]["path"]),
        ontology_crosswalk=Path(receipt["sources"]["ontology_crosswalk"]["path"]),
        observed_at_utc="2026-07-27T00:00:00Z",
    )
    assert rebuilt["reference_library"]["benchmark_missing_body_part_focus_tags"] == [
        "part_missing"
    ]
    assert rebuilt["readiness"]["all_declared_body_part_focus_tags_represented"] is False


def test_builder_rejects_annotation_hash_drift(tmp_path: Path) -> None:
    receipt = _build(tmp_path)
    registry_path = Path(receipt["sources"]["dataset_registry"]["path"])
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["datasets"][0]["annotation_files"][0]["sha256"] = "f" * 64
    _json(registry_path, registry)
    with pytest.raises(
        VisualReferenceReadinessError,
        match="annotation hash mismatch",
    ):
        build_visual_reference_readiness(
            inventory_summary=Path(receipt["sources"]["inventory_summary"]["path"]),
            inventory_database=Path(receipt["sources"]["inventory_database"]["path"]),
            library_database=Path(receipt["sources"]["library_database"]["path"]),
            dataset_registry=registry_path,
            ontology_crosswalk=Path(receipt["sources"]["ontology_crosswalk"]["path"]),
            observed_at_utc="2026-07-27T00:00:00Z",
        )
