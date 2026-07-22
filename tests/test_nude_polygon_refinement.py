from __future__ import annotations

import numpy as np
import pytest

from maskfactory.nude_polygon_hard_qc import NudePolygonQcError
from maskfactory.nude_polygon_refinement import (
    NudePolygonRefinementError,
    autotune_polygon_refinement,
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


def test_autotune_selects_best_safe_unique_proposal_with_bounded_attempts() -> None:
    image = np.zeros((96, 96, 3), dtype=np.uint8)
    image[30:70, 35:65] = 255
    source = np.zeros((96, 96), dtype=bool)
    source[28:72, 33:67] = True
    selected, report = autotune_polygon_refinement(image, source, candidate_label="breast_region")
    assert report["outcome"] == "draft_refined_candidate_autotuned"
    assert not np.array_equal(selected, source)
    tuning = report["autotune"]
    assert tuning["attempt_count"] == 5
    assert tuning["attempt_budget"] == 5
    assert tuning["safe_proposal_count"] >= 1
    assert 1 <= tuning["unique_proposal_count"] <= 5
    chosen = next(
        attempt
        for attempt in tuning["attempts"]
        if attempt["iterations"] == tuning["selected_iterations"]
    )
    assert chosen["proposal_mask_sha256"] == report["selected_mask_sha256"]
    assert chosen["proposal_boundary_alignment_score"] == max(
        attempt["proposal_boundary_alignment_score"]
        for attempt in tuning["attempts"]
        if attempt["outcome"] == "draft_refined_candidate"
    )
    assert report["operational_certificate_eligible"] is False


def test_autotune_abstains_and_preserves_parent_when_no_attempt_is_safe() -> None:
    image = np.full((64, 64, 3), 100, dtype=np.uint8)
    source = np.zeros((64, 64), dtype=bool)
    source[16:48, 16:48] = True
    selected, report = autotune_polygon_refinement(image, source, candidate_label="breast_region")
    assert report["outcome"] == "abstained_no_safe_refinement"
    assert report["parent_preserved"] is True
    assert report["changed_pixels"] == 0
    assert report["autotune"]["safe_proposal_count"] == 0
    assert np.array_equal(selected, source)


@pytest.mark.parametrize("attempts", ((), (1, 1), (0, 1), (1, 6), (1, 2, 3, 4, 5, 6)))
def test_autotune_attempt_policy_fails_closed(attempts: tuple[int, ...]) -> None:
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    source = np.zeros((32, 32), dtype=bool)
    source[8:24, 8:24] = True
    with pytest.raises(NudePolygonRefinementError, match="attempt_iterations_invalid"):
        autotune_polygon_refinement(
            image,
            source,
            candidate_label="breast_region",
            attempt_iterations=attempts,
        )


def test_autotune_cannot_bypass_label_scale_hard_qc() -> None:
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    image[4:60, 4:60] = 255
    source = np.zeros((64, 64), dtype=bool)
    source[4:60, 4:60] = True
    with pytest.raises(NudePolygonQcError, match="image_area_implausible"):
        autotune_polygon_refinement(image, source, candidate_label="nipple")
