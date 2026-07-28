from __future__ import annotations

from copy import deepcopy

import numpy as np
import pytest

from maskfactory.vlm.panel_renderer import (
    PanelRenderError,
    render_target_panels,
    transform_sha256,
)
from maskfactory.vlm.target_contract import target_contract_sha256


def _contract() -> dict:
    contract = {
        "schema_version": "1.0.0",
        "contract_id": "panel-target",
        "source": {"image_id": "image-1", "sha256": "a" * 64, "width": 8, "height": 8},
        "owner": {
            "person_index": 0,
            "character_instance_id": "character-1",
            "person_mask_sha256": "b" * 64,
        },
        "target": {
            "label_id": "left_hand",
            "expected_presence": "visible_nonempty",
            "minimum_area_pixels": 1,
            "maximum_area_pixels": 32,
            "allowed_roi_xyxy": [1, 1, 7, 7],
            "inclusion_rule": "visible_pixels_only",
            "exclusion_rule": "exclude_occluded_outside_owner_and_named_labels",
        },
        "candidate": {
            "mask_sha256": "c" * 64,
            "width": 8,
            "height": 8,
            "binary_values": [0, 255],
        },
        "excluded_labels": ["right_hand"],
        "protected_regions": [],
        "transforms": {
            "source_to_candidate": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "candidate_to_source": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        },
        "contract_sha256": "",
    }
    contract["contract_sha256"] = target_contract_sha256(contract)
    return contract


def _render(**changes):
    contract = changes.pop("target_contract", _contract())
    source = np.arange(8 * 8 * 3, dtype=np.uint8).reshape(8, 8, 3)
    candidate = np.zeros((8, 8), dtype=np.bool_)
    candidate[2:5, 2:5] = True
    disagreement = np.zeros((8, 8), dtype=np.bool_)
    disagreement[4:6, 4:6] = True
    values = {
        "source_rgb": source,
        "candidate_mask": candidate,
        "disagreement_mask": disagreement,
        "target_contract": contract,
        "source_file_sha256": "a" * 64,
        "candidate_file_sha256": "c" * 64,
        "expected_target_contract_sha256": contract["contract_sha256"],
        "expected_transform_sha256": transform_sha256(contract),
        "crop_xyxy": (1, 1, 7, 7),
    }
    values.update(changes)
    return render_target_panels(**values)


def test_exact_target_aware_panel_set_is_deterministic_and_hash_bound() -> None:
    first = _render()
    second = _render()
    assert first.manifest == second.manifest
    assert first.png_bytes == second.png_bytes
    assert set(first.png_bytes) == {
        "source",
        "binary_mask",
        "overlay",
        "contour",
        "full_context",
        "uncertainty_zoom",
        "disagreement",
    }
    assert all(content.startswith(b"\x89PNG\r\n\x1a\n") for content in first.png_bytes.values())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_file_sha256", "f" * 64, "source hash"),
        ("candidate_file_sha256", "f" * 64, "candidate hash"),
        ("expected_target_contract_sha256", "f" * 64, "target contract hash"),
        ("expected_transform_sha256", "f" * 64, "transform hash"),
        ("crop_xyxy", (0, 0, 8, 8), "target ROI"),
    ],
)
def test_wrong_source_candidate_target_transform_or_crop_fails_before_review(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(PanelRenderError, match=message):
        _render(**{field: value})


def test_candidate_or_disagreement_outside_roi_fails() -> None:
    outside = np.zeros((8, 8), dtype=np.bool_)
    outside[0, 0] = True
    with pytest.raises(PanelRenderError, match="escape target ROI"):
        _render(candidate_mask=outside)
    with pytest.raises(PanelRenderError, match="escape target ROI"):
        _render(disagreement_mask=outside)


def test_tampered_target_contract_fails_canonical_authorization() -> None:
    contract = deepcopy(_contract())
    contract["target"]["label_id"] = "right_hand"
    with pytest.raises(PanelRenderError, match="canonical hash mismatch"):
        _render(target_contract=contract)
