import numpy as np
import pytest

from maskfactory.datasets.cocorle import (
    CocoRleError,
    decode_binary_mask,
    encode_binary_mask,
    validate_rle,
)


def test_known_non_square_mask_uses_coco_column_major_order() -> None:
    mask = np.array([[0, 1, 0], [1, 1, 0]], dtype=np.uint8)

    encoded = encode_binary_mask(mask)

    assert encoded == {"size": [2, 3], "counts": [1, 3, 2]}
    assert np.array_equal(decode_binary_mask(encoded), mask.astype(bool))


@pytest.mark.parametrize(
    ("mask", "counts"),
    [
        (np.zeros((2, 2), dtype=bool), [4]),
        (np.ones((2, 2), dtype=np.uint8) * 255, [0, 4]),
    ],
)
def test_uniform_masks_keep_required_initial_background_run(mask, counts) -> None:
    encoded = encode_binary_mask(mask)
    assert encoded["counts"] == counts
    validate_rle(encoded)
    assert np.array_equal(decode_binary_mask(encoded), mask != 0)


@pytest.mark.parametrize(
    "document",
    [
        {"size": [2, 3], "counts": [1, 3, 1]},
        {"size": [2, 3], "counts": [1, 0, 5]},
        {"size": [0, 3], "counts": [0]},
        {"size": [2, 3], "counts": "1 3 2"},
        {"size": [2, 3], "counts": [1, 3, 2], "extra": True},
    ],
)
def test_malformed_or_noncanonical_rle_is_rejected(document) -> None:
    with pytest.raises(CocoRleError):
        validate_rle(document)


@pytest.mark.parametrize(
    "mask",
    [
        np.zeros((2, 2, 1), dtype=np.uint8),
        np.array([[0, 2]], dtype=np.uint8),
        np.array([[0.0, 1.0]], dtype=np.float32),
        np.zeros((0, 2), dtype=np.uint8),
    ],
)
def test_non_binary_or_non_2d_sources_are_rejected(mask) -> None:
    with pytest.raises(CocoRleError):
        encode_binary_mask(mask)


def test_seeded_masks_round_trip_without_geometry_or_area_drift() -> None:
    generator = np.random.default_rng(1337)
    for shape in ((1, 7), (7, 1), (13, 19), (19, 13)):
        mask = generator.random(shape) > 0.63
        decoded = decode_binary_mask(encode_binary_mask(mask))
        assert decoded.shape == mask.shape
        assert int(decoded.sum()) == int(mask.sum())
        assert np.array_equal(decoded, mask)
