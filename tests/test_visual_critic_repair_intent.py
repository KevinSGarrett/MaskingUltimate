from __future__ import annotations

from copy import deepcopy

import pytest

from maskfactory.vlm.repair_intent import RepairIntentError, parse_repair_intent
from maskfactory.vlm.target_contract import target_contract_sha256

PANEL = "d" * 64


def _contract() -> dict:
    contract = {
        "schema_version": "1.0.0",
        "contract_id": "repair-target",
        "source": {"image_id": "image-1", "sha256": "a" * 64, "width": 100, "height": 100},
        "owner": {
            "person_index": 0,
            "character_instance_id": "character-1",
            "person_mask_sha256": "b" * 64,
        },
        "target": {
            "label_id": "left_hand",
            "expected_presence": "visible_nonempty",
            "minimum_area_pixels": 1,
            "maximum_area_pixels": 2000,
            "allowed_roi_xyxy": [10, 10, 90, 90],
            "inclusion_rule": "visible_pixels_only",
            "exclusion_rule": "exclude_occluded_outside_owner_and_named_labels",
        },
        "candidate": {
            "mask_sha256": "c" * 64,
            "width": 100,
            "height": 100,
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


def _response() -> dict:
    contract = _contract()
    return {
        "schema_version": "1.0.0",
        "verdict": "defect",
        "target_contract_sha256": contract["contract_sha256"],
        "panel_set_sha256": "e" * 64,
        "findings": [
            {
                "defect_type": "missing_area",
                "bbox_xyxy": [20, 20, 30, 30],
                "evidence_panel_sha256": PANEL,
                "confidence": 0.9,
            }
        ],
        "repair_plan": {
            "operations": [
                {
                    "operation": "add_point",
                    "label_id": "left_hand",
                    "roi_xyxy": [15, 15, 40, 40],
                    "parameters": {"x": 25, "y": 25, "polarity": "positive"},
                }
            ],
            "max_rounds": 2,
            "max_seconds": 120,
        },
    }


def _parse(response: dict):
    return parse_repair_intent(
        response,
        target_contract=_contract(),
        panel_set_sha256="e" * 64,
        allowed_panel_sha256={PANEL, "f" * 64},
    )


def test_bounded_localization_and_repair_intent_pass_without_pixel_authority() -> None:
    result = _parse(_response())
    assert result["verdict"] == "defect"
    assert result["critic_pixel_authority"] is False
    assert len(result["repair_intent_sha256"]) == 64


@pytest.mark.parametrize("forbidden", ["mask", "pixels", "raw_mask", "tool_call"])
def test_raw_pixels_masks_or_tools_are_rejected(forbidden: str) -> None:
    response = _response()
    response[forbidden] = "forbidden"
    with pytest.raises(RepairIntentError, match="pixel-bearing"):
        _parse(response)


def test_out_of_scope_label_or_roi_is_rejected() -> None:
    response = _response()
    response["repair_plan"]["operations"][0]["label_id"] = "right_hand"
    with pytest.raises(RepairIntentError, match="changes target label"):
        _parse(response)
    response = _response()
    response["findings"][0]["bbox_xyxy"] = [0, 0, 5, 5]
    with pytest.raises(RepairIntentError, match="escapes target ROI"):
        _parse(response)


def test_unknown_panel_citation_is_rejected() -> None:
    response = _response()
    response["findings"][0]["evidence_panel_sha256"] = "1" * 64
    with pytest.raises(RepairIntentError, match="unknown panel"):
        _parse(response)


def test_unbounded_round_time_operation_or_threshold_is_rejected() -> None:
    response = _response()
    response["repair_plan"]["max_rounds"] = 99
    with pytest.raises(RepairIntentError, match="rounds exceed"):
        _parse(response)
    response = _response()
    response["repair_plan"]["max_seconds"] = 999
    with pytest.raises(RepairIntentError, match="time exceeds"):
        _parse(response)
    response = _response()
    response["repair_plan"]["operations"] *= 9
    with pytest.raises(RepairIntentError, match="operation count"):
        _parse(response)
    response = _response()
    response["repair_plan"]["operations"][0] = {
        "operation": "threshold_adjust",
        "label_id": "left_hand",
        "roi_xyxy": [15, 15, 40, 40],
        "parameters": {"delta": 0.9},
    }
    with pytest.raises(RepairIntentError, match="delta is unbounded"):
        _parse(response)


def test_pass_or_abstain_cannot_smuggle_repairs() -> None:
    for verdict in ("pass", "abstain"):
        response = _response()
        response["verdict"] = verdict
        with pytest.raises(RepairIntentError, match="cannot carry repair"):
            _parse(response)


def test_clean_pass_is_closed_and_empty() -> None:
    response = _response()
    response["verdict"] = "pass"
    response["findings"] = []
    response["repair_plan"]["operations"] = []
    result = _parse(response)
    assert result["verdict"] == "pass"
    assert result["repair_plan"]["operations"] == []


def test_hash_drift_fails_closed() -> None:
    response = deepcopy(_response())
    response["target_contract_sha256"] = "f" * 64
    with pytest.raises(RepairIntentError, match="target contract hash drifted"):
        _parse(response)
