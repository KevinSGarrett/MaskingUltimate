import numpy as np
import pytest

from maskfactory.cvat_bridge.labelmap import (
    CvatLabelMap,
    CvatMappingError,
    decode_mask_rle,
    encode_mask_rle,
)
from maskfactory.ontology import get_ontology


def _server_labels() -> list[dict]:
    return [
        {
            "id": index + 100,
            "name": label.name,
            "color": "#123456",
            "attributes": [
                {"id": index * 3 + 1, "name": "visibility"},
                {"id": index * 3 + 2, "name": "ambiguous"},
                {"id": index * 3 + 3, "name": "notes"},
            ],
        }
        for index, label in enumerate(get_ontology().labels)
    ]


def test_label_map_is_exact_bidirectional_and_attribute_aware() -> None:
    mapping = CvatLabelMap(_server_labels())
    assert mapping.ontology_name(mapping.cvat_id("left_forearm")) == "left_forearm"
    assert mapping.attribute_id("left_forearm", "visibility") > 0
    assert len(mapping.as_document()["labels"]) == 135
    with pytest.raises(CvatMappingError, match="unknown CVAT label id"):
        mapping.ontology_name(999999)


def test_label_map_rejects_missing_labels_and_attribute_drift() -> None:
    labels = _server_labels()
    with pytest.raises(CvatMappingError, match="label drift"):
        CvatLabelMap(labels[:-1])
    labels = _server_labels()
    labels[0]["attributes"].pop()
    with pytest.raises(CvatMappingError, match="incorrect attributes"):
        CvatLabelMap(labels)


@pytest.mark.parametrize("seed", range(10))
def test_cvat_rle_roundtrip_is_pixel_identical(seed: int) -> None:
    random = np.random.default_rng(seed)
    mask = (random.random((31, 47)) > 0.82).astype(np.uint8) * 255
    mask[:2] = 0
    mask[:, :3] = 0
    assert np.array_equal(decode_mask_rle(encode_mask_rle(mask), shape=mask.shape), mask)


def test_cvat_rle_rejects_empty_and_bad_payloads() -> None:
    with pytest.raises(CvatMappingError, match="empty"):
        encode_mask_rle(np.zeros((3, 3), dtype=np.uint8))
    with pytest.raises(CvatMappingError, match="bbox area"):
        decode_mask_rle([1, 0, 0, 2, 2], shape=(3, 3))
