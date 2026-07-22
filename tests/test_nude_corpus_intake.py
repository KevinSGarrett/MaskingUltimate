from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from maskfactory.nude_corpus_intake import (
    NudeCorpusIntakeError,
    audit_full_corpus_crosswalk,
    build_project_registry_manifest,
    canonical_sha256,
    crosswalk_source_labels,
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
        ({"size": [4, 4], "counts": "rle"}, "coco_rle_counts_invalid"),
        ({"size": [5, 4], "counts": "044"}, "coco_rle_contract_invalid"),
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


@pytest.mark.parametrize("counts", ("132", [1, 3, 2]))
def test_coco_rle_rasterizer_supports_compressed_and_uncompressed_counts(counts: object) -> None:
    mask = rasterize_coco_segmentation({"size": [2, 3], "counts": counts}, width=3, height=2)
    assert mask.tolist() == [[False, True, False], [True, True, False]]


def test_compressed_coco_rle_multibyte_run_matches_canonical_mask_api() -> None:
    mask = rasterize_coco_segmentation({"size": [10, 10], "counts": "0T3"}, width=10, height=10)
    assert mask.all()


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
        "crosswalk_override_sha256": "c" * 64,
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
    assert manifest["adopted_source"]["project_crosswalk_override_sha256"] == "c" * 64
    assert manifest["self_sha256"] == canonical_sha256(manifest)


def test_project_crosswalk_adds_only_coarse_face_and_unsided_feet() -> None:
    crosswalk = {
        "anatomy_aliases": {
            "female face": {"canonical_candidate": "head_face", "kind": "coarse_anatomy"},
            "feet": {
                "canonical_candidate": "feet_region_unspecified",
                "kind": "ambiguous_coarse_anatomy",
            },
        },
        "scene_and_action_labels": {},
    }
    mapped, actions, unmapped = crosswalk_source_labels(("female face", "feet"), crosswalk)
    assert [row["candidate_label"] for row in mapped] == [
        "head_face",
        "feet_region_unspecified",
    ]
    assert actions == []
    assert unmapped == []
    assert not any(
        "left_" in row["candidate_label"] or "right_" in row["candidate_label"] for row in mapped
    )
    forbidden_fine_labels = {"areola", "nipple", "shaft", "glans", "scrotum", "glute"}
    assert not any(
        token in row["candidate_label"] for row in mapped for token in forbidden_fine_labels
    )


def test_full_crosswalk_audit_accounts_actions_unmapped_and_coarse_fine_invention() -> None:
    records = {
        "a": {"source_labels": ["female face", "Sex"]},
        "b": {"source_labels": ["feet", "unknown"]},
    }
    crosswalk = {
        "anatomy_aliases": {
            "female face": {"canonical_candidate": "head_face", "kind": "coarse_anatomy"},
            "feet": {
                "canonical_candidate": "feet_region_unspecified",
                "kind": "ambiguous_coarse_anatomy",
            },
        },
        "scene_and_action_labels": {"Sex": "sexual_activity_scene"},
    }
    report = audit_full_corpus_crosswalk(records, crosswalk)
    assert report["record_count"] == 2
    assert report["action_label_counts"] == {"sexual_activity_scene": 1}
    assert report["unmapped_label_counts"] == {"unknown": 1}
    assert report["coarse_fine_invention_counts"] == {}


def test_coarse_crosswalk_fails_closed_before_it_can_invent_a_fine_label() -> None:
    with pytest.raises(NudeCorpusIntakeError, match="fine_label_invented_from_coarse"):
        crosswalk_source_labels(
            ("feet",),
            {
                "anatomy_aliases": {
                    "feet": {
                        "canonical_candidate": "left_nipple",
                        "kind": "ambiguous_coarse_anatomy",
                    }
                },
                "scene_and_action_labels": {},
            },
        )
