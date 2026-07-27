from __future__ import annotations

import numpy as np
import pytest

from maskfactory.providers.disagreement import (
    DisagreementError,
    NormalizedCandidate,
    binary_mask_sha256,
    build_all_pairwise_disagreements,
    build_pairwise_disagreement,
)


def _candidate(index: int, mask: np.ndarray, *, owner: int = 0) -> NormalizedCandidate:
    return NormalizedCandidate(
        proposal_id=f"proposal-{index}",
        family_id=f"family-{index}",
        source_sha256="a" * 64,
        target_contract_sha256="b" * 64,
        normalized_mask_sha256=binary_mask_sha256(mask),
        owner_person_index=owner,
        mask=mask,
    )


def test_known_overlap_and_omission_localize_to_expected_pixels() -> None:
    left = np.zeros((6, 6), dtype=np.bool_)
    right = np.zeros((6, 6), dtype=np.bool_)
    left[1:4, 1:4] = True
    right[2:5, 2:5] = True
    result = build_pairwise_disagreement(
        _candidate(1, left), _candidate(2, right), normalized_shape=(6, 6)
    )
    assert result.report["metrics"]["intersection_pixels"] == 4
    assert result.report["metrics"]["union_pixels"] == 14
    assert result.report["metrics"]["left_only_pixels"] == 5
    assert result.report["metrics"]["right_only_pixels"] == 5
    assert np.array_equal(result.disagreement, np.logical_xor(left, right))
    assert sum(region["pixel_count"] for region in result.report["regions"]) == 10


def test_boundary_disagreement_is_localized_and_hash_bound() -> None:
    left = np.zeros((7, 7), dtype=np.bool_)
    right = np.zeros((7, 7), dtype=np.bool_)
    left[1:6, 1:6] = True
    right[2:6, 1:6] = True
    result = build_pairwise_disagreement(
        _candidate(1, left), _candidate(2, right), normalized_shape=(7, 7)
    )
    assert result.report["metrics"]["boundary_disagreement_pixels"] > 0
    assert result.report["map_sha256"]["boundary_disagreement"] == binary_mask_sha256(
        result.boundary_disagreement
    )


def test_owner_disagreement_localizes_to_candidate_union() -> None:
    left = np.zeros((4, 4), dtype=np.bool_)
    right = np.zeros((4, 4), dtype=np.bool_)
    left[1:3, 1:3] = True
    right[2:4, 2:4] = True
    result = build_pairwise_disagreement(
        _candidate(1, left, owner=0),
        _candidate(2, right, owner=1),
        normalized_shape=(4, 4),
    )
    assert np.array_equal(result.ownership_disagreement, np.logical_or(left, right))
    assert result.report["metrics"]["ownership_disagreement_pixels"] == 7


def test_every_pair_binds_candidate_hashes() -> None:
    masks = []
    for index in range(3):
        mask = np.zeros((5, 5), dtype=np.bool_)
        mask[index : index + 2, index : index + 2] = True
        masks.append(mask)
    results = build_all_pairwise_disagreements(
        [_candidate(index + 1, mask) for index, mask in enumerate(masks)],
        normalized_shape=(5, 5),
    )
    assert len(results) == 3
    bound = {
        value
        for result in results
        for value in (
            result.report["left"]["normalized_mask_sha256"],
            result.report["right"]["normalized_mask_sha256"],
        )
    }
    assert bound == {binary_mask_sha256(mask) for mask in masks}


@pytest.mark.parametrize("field", ["source_sha256", "target_contract_sha256"])
def test_source_or_target_drift_fails_closed(field: str) -> None:
    mask = np.zeros((3, 3), dtype=np.bool_)
    left = _candidate(1, mask)
    values = left.__dict__ | {"proposal_id": "proposal-2", field: "f" * 64}
    right = NormalizedCandidate(**values)
    with pytest.raises(DisagreementError, match="identity differs"):
        build_pairwise_disagreement(left, right, normalized_shape=(3, 3))


def test_pixel_hash_drift_or_geometry_drift_fails_closed() -> None:
    left_mask = np.zeros((3, 3), dtype=np.bool_)
    right_mask = np.ones((3, 3), dtype=np.bool_)
    right = _candidate(2, right_mask)
    drifted = NormalizedCandidate(**(right.__dict__ | {"normalized_mask_sha256": "f" * 64}))
    with pytest.raises(DisagreementError, match="hash differs"):
        build_pairwise_disagreement(_candidate(1, left_mask), drifted, normalized_shape=(3, 3))
    with pytest.raises(DisagreementError, match="geometry"):
        build_pairwise_disagreement(_candidate(1, left_mask), right, normalized_shape=(4, 4))


def test_zero_union_metrics_are_finite() -> None:
    empty = np.zeros((2, 2), dtype=np.bool_)
    result = build_pairwise_disagreement(
        _candidate(1, empty), _candidate(2, empty), normalized_shape=(2, 2)
    )
    assert result.report["metrics"]["iou"] == 1.0
    assert result.report["metrics"]["disagreement_pixels"] == 0
