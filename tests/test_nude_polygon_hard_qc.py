from __future__ import annotations

import numpy as np
import pytest

from maskfactory.nude_polygon_hard_qc import NudePolygonQcError, evaluate_polygon_annotation
from maskfactory.providers.disagreement import binary_mask_sha256


def _crosswalk() -> dict[str, object]:
    return {
        "anatomy_aliases": {
            "breast": {"canonical_candidate": "breast_region", "kind": "coarse_anatomy"},
            "nipple": {"canonical_candidate": "nipple", "kind": "anatomy"},
            "mystery": {"canonical_candidate": "not_in_policy", "kind": "anatomy"},
        },
        "scene_and_action_labels": {"Sex": "sexual_activity_scene"},
        "context_aliases": {
            "toy": {"context_candidate": "sex_toy_object", "kind": "context_object"}
        },
    }


def test_real_polygon_contract_materializes_binary_hash_and_preserves_coarse_label() -> None:
    result = evaluate_polygon_annotation(
        {
            "segmentation": [[1, 1, 5, 1, 5, 5, 1, 5]],
            "bbox": [1, 1, 5, 5],
        },
        raw_label="breast",
        width=8,
        height=8,
        crosswalk=_crosswalk(),
    )
    assert result["raw_label"] == "breast"
    assert result["candidate_label"] == "breast_region"
    assert result["mask_pixels"] == 25
    assert len(result["mask_sha256"]) == 64
    assert result["production_authority"] is False


def test_binary_mask_identity_binds_canvas_geometry() -> None:
    assert binary_mask_sha256(np.zeros((2, 8), dtype=bool)) != binary_mask_sha256(
        np.zeros((4, 4), dtype=bool)
    )


@pytest.mark.parametrize(
    ("label", "expected"),
    (
        ("Sex", "action_or_scene_label"),
        ("unknown", "polygon_label_unmapped"),
        ("toy", "non_anatomy_context"),
    ),
)
def test_action_and_unmapped_labels_cannot_be_pixel_truth(label: str, expected: str) -> None:
    with pytest.raises(NudePolygonQcError, match=expected):
        evaluate_polygon_annotation(
            {"segmentation": [[1, 1, 5, 1, 5, 5, 1, 5]], "bbox": [1, 1, 5, 5]},
            raw_label=label,
            width=8,
            height=8,
            crosswalk=_crosswalk(),
        )


def test_polygon_bbox_alignment_failure_is_hard_block() -> None:
    with pytest.raises(NudePolygonQcError, match="polygon_bbox_alignment_failed"):
        evaluate_polygon_annotation(
            {"segmentation": [[1, 1, 5, 1, 5, 5, 1, 5]], "bbox": [0, 0, 8, 8]},
            raw_label="nipple",
            width=8,
            height=8,
            crosswalk=_crosswalk(),
        )


def test_one_pixel_raster_quantization_is_accepted_without_lowering_iou_gate() -> None:
    result = evaluate_polygon_annotation(
        {"segmentation": [[1, 1, 2, 1, 2, 2, 1, 2]], "bbox": [1, 1, 1, 1]},
        raw_label="breast",
        width=4,
        height=4,
        crosswalk=_crosswalk(),
    )
    assert result["bbox_iou"] == 0.25
    assert result["maximum_bbox_edge_delta_px"] == 1.0
    assert result["bbox_alignment_method"] == "raster_quantization_edge_tolerance"


def test_compressed_rle_is_materialized_as_pixel_truth_candidate() -> None:
    result = evaluate_polygon_annotation(
        {
            "segmentation": {"size": [2, 3], "counts": "132"},
            "bbox": [0, 0, 2, 2],
            "area": 3,
        },
        raw_label="breast",
        width=3,
        height=2,
        crosswalk=_crosswalk(),
    )
    assert result["mask_pixels"] == 3
    assert result["segmentation_encoding"] == "coco_rle"
    assert result["binary_mask_materialized"] is True


def test_stale_rle_source_area_is_preserved_as_advisory_not_mask_authority() -> None:
    result = evaluate_polygon_annotation(
        {
            "segmentation": {"size": [2, 3], "counts": "132"},
            "bbox": [0, 0, 2, 2],
            "area": 4,
        },
        raw_label="breast",
        width=3,
        height=2,
        crosswalk=_crosswalk(),
    )
    assert result["mask_pixels"] == 3
    assert result["source_annotation_area"] == 4.0
    assert result["source_annotation_area_matches_decoded_mask"] is False


def test_fine_anatomy_whole_person_substitution_is_hard_blocked() -> None:
    with pytest.raises(NudePolygonQcError, match="image_area_implausible"):
        evaluate_polygon_annotation(
            {
                "segmentation": [[4, 4, 59, 4, 59, 59, 4, 59]],
                "bbox": [4, 4, 56, 56],
            },
            raw_label="nipple",
            width=64,
            height=64,
            crosswalk=_crosswalk(),
        )


def test_every_pixel_label_requires_explicit_scale_policy() -> None:
    with pytest.raises(NudePolygonQcError, match="scale_policy_missing"):
        evaluate_polygon_annotation(
            {
                "segmentation": [[4, 4, 11, 4, 11, 11, 4, 11]],
                "bbox": [4, 4, 8, 8],
            },
            raw_label="mystery",
            width=64,
            height=64,
            crosswalk=_crosswalk(),
        )


def test_mask_hash_contract_is_current_shape_bound_boolean_identity() -> None:
    result = evaluate_polygon_annotation(
        {
            "segmentation": [[1, 1, 5, 1, 5, 5, 1, 5]],
            "bbox": [1, 1, 5, 5],
        },
        raw_label="breast",
        width=8,
        height=8,
        crosswalk=_crosswalk(),
    )
    expected = np.zeros((8, 8), dtype=bool)
    expected[1:6, 1:6] = True
    assert result["mask_sha256"] == binary_mask_sha256(expected)
