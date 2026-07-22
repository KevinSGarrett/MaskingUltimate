from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from maskfactory.nude_corpus_intake import (
    NudeCorpusIntakeError,
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
