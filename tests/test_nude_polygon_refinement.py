from __future__ import annotations

import numpy as np
import pytest

from maskfactory.nude_polygon_refinement import (
    NudePolygonRefinementError,
    refine_polygon_mask,
)


def test_graphcut_refinement_is_bounded_and_draft_only() -> None:
    image = np.full((96, 96, 3), 20, dtype=np.uint8)
    image[28:72, 32:68] = np.array([190, 130, 100], dtype=np.uint8)
    source = np.zeros((96, 96), dtype=bool)
    source[25:75, 29:71] = True
    refined, report = refine_polygon_mask(image, source)
    assert refined.shape == source.shape
    assert report["outcome"] in {
        "draft_refined_candidate",
        "no_progress",
        "no_progress_boundary_not_improved",
        "rejected_refinement_regression",
    }
    assert report["source_iou"] >= report["thresholds"]["minimum_source_iou"]
    assert report["authority"] == "deterministic_refiner_draft_only"
    assert report["independent_provider_comparison_passed"] is False
    assert report["operational_certificate_eligible"] is False
    if report["outcome"] != "draft_refined_candidate":
        assert np.array_equal(refined, source)
        assert report["parent_preserved"] is True


def test_refinement_is_deterministic_for_same_pixels() -> None:
    image = np.full((64, 64, 3), 30, dtype=np.uint8)
    image[16:48, 18:46] = 210
    source = np.zeros((64, 64), dtype=bool)
    source[14:50, 16:48] = True
    first, first_report = refine_polygon_mask(image, source)
    second, second_report = refine_polygon_mask(image, source)
    assert np.array_equal(first, second)
    assert first_report["refined_mask_sha256"] == second_report["refined_mask_sha256"]
    assert first_report["proposal_mask_sha256"] == second_report["proposal_mask_sha256"]


def test_uniform_pixels_cannot_claim_boundary_improvement() -> None:
    image = np.full((64, 64, 3), 100, dtype=np.uint8)
    source = np.zeros((64, 64), dtype=bool)
    source[16:48, 16:48] = True
    selected, report = refine_polygon_mask(image, source)
    assert report["outcome"] != "draft_refined_candidate"
    assert report["parent_preserved"] is True
    assert report["changed_pixels"] == 0
    assert np.array_equal(selected, source)


def test_invalid_shape_small_mask_and_iterations_fail_closed() -> None:
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    small = np.zeros((32, 32), dtype=bool)
    small[1:3, 1:3] = True
    with pytest.raises(NudePolygonRefinementError, match="too_small"):
        refine_polygon_mask(image, small)
    with pytest.raises(NudePolygonRefinementError, match="shape_mismatch"):
        refine_polygon_mask(image, np.zeros((31, 32), dtype=bool))
    source = np.zeros((32, 32), dtype=bool)
    source[8:24, 8:24] = True
    with pytest.raises(NudePolygonRefinementError, match="iterations_out_of_bounds"):
        refine_polygon_mask(image, source, iterations=6)
