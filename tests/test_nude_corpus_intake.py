from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from maskfactory.nude_corpus_intake import (
    NudeCorpusIntakeError,
    build_project_registry_manifest,
    canonical_sha256,
    rasterize_coco_segmentation,
    validate_shard,
)


def _shard() -> dict:
    payload = {
        "artifact_type": "tournament_sample_set",
        "schema_version": "maskfactory.nude_batch_shard.v1",
        "platform": "local",
        "batch_lane": "polygon_external_supervision",
        "batch_number": 1,
        "sample_count": 1,
        "ordered_sample_ids": ["nude_fixture"],
        "samples": [
            {
                "sample_id": "nude_fixture",
                "source_path_readonly": r"C:\fixture.png",
                "source_sha256": "a" * 64,
                "source_family": "fixture",
                "collection_id": "fixture-lineage",
                "source_role": "polygon_external_supervision",
                "source_split": "train",
                "annotation_ref": "fixture/_annotations.coco.json",
                "source_labels": ["penis"],
            }
        ],
    }
    payload["self_sha256"] = canonical_sha256(payload)
    return payload


def test_polygon_rasterizer_materializes_exact_binary_pixels() -> None:
    mask = rasterize_coco_segmentation([[1, 1, 4, 1, 4, 4, 1, 4]], width=6, height=6)
    assert mask.dtype == np.bool_
    assert mask.shape == (6, 6)
    assert int(mask.sum()) == 16


@pytest.mark.parametrize(
    "segmentation,error",
    [
        ({"counts": "rle"}, "polygon_segmentation_required"),
        ([[0, 0, 1, 1]], "polygon_coordinates_invalid"),
        ([[0, 0, 8, 0, 0, 2]], "polygon_coordinates_out_of_bounds"),
        ([[0, 0, float("nan"), 1, 1, 2]], "polygon_coordinates_invalid"),
    ],
)
def test_polygon_rasterizer_rejects_non_polygon_degenerate_or_unsafe_geometry(
    segmentation: object, error: str
) -> None:
    with pytest.raises(NudeCorpusIntakeError, match=error):
        rasterize_coco_segmentation(segmentation, width=4, height=4)


def test_shard_contract_is_hash_bound_and_ordered(tmp_path: Path) -> None:
    shard = _shard()
    path = tmp_path / "shard.json"
    path.write_text(json.dumps(shard), encoding="utf-8")
    assert (
        validate_shard(path, expected_lane="polygon_external_supervision", platform="local")[
            "self_sha256"
        ]
        == shard["self_sha256"]
    )

    drifted = deepcopy(shard)
    drifted["samples"][0]["source_sha256"] = "b" * 64
    path.write_text(json.dumps(drifted), encoding="utf-8")
    with pytest.raises(NudeCorpusIntakeError, match="shard_contract_invalid"):
        validate_shard(path, expected_lane="polygon_external_supervision", platform="local")


def test_shard_contract_rejects_reordered_or_duplicate_samples(tmp_path: Path) -> None:
    shard = _shard()
    shard["ordered_sample_ids"] = ["wrong"]
    shard["self_sha256"] = canonical_sha256(shard)
    path = tmp_path / "shard.json"
    path.write_text(json.dumps(shard), encoding="utf-8")
    with pytest.raises(NudeCorpusIntakeError, match="shard_coverage_invalid"):
        validate_shard(path, expected_lane="polygon_external_supervision", platform="local")


def test_project_registry_preserves_exact_dataset_rows_and_denies_authority(tmp_path: Path) -> None:
    for name in ("dataset_policy.json", "ontology_crosswalk.json", "batch_policy.json"):
        (tmp_path / name).write_text("{}\n", encoding="utf-8")
    row = {
        "dataset_id": "fixture",
        "path": r"C:\fixture",
        "annotation_format": "coco_bbox",
        "annotation_files": [{"path": "train/_annotations.coco.json", "categories": ["genital"]}],
        "source_url": "https://example.invalid/source",
        "license_claim": "declared fixture",
        "lineage_group": "fixture-family",
        "primary_role": "bbox_prompt_supervision",
        "record_count": 1,
        "version_policy": "active",
    }
    rows = [dict(row, dataset_id=f"fixture-{index}") for index in range(16)]
    intake = {
        "intake_root": tmp_path,
        "registry": {
            "self_sha256": "a" * 64,
            "record_count": 81_910,
            "role_counts": {"bbox_prompt_supervision": 81_910},
            "datasets": rows,
        },
        "index": {"self_sha256": "b" * 64},
    }
    manifest = build_project_registry_manifest(intake)
    assert manifest["datasets"] == sorted(rows, key=lambda item: item["dataset_id"])
    assert manifest["dataset_count"] == 16
    assert manifest["authority"]["external_annotations_are_human_gold"] is False
    assert manifest["self_sha256"] == canonical_sha256(manifest)
