from __future__ import annotations

import hashlib

import numpy as np
import pytest

from maskfactory.nude_person_ownership import (
    NudePersonOwnershipError,
    resolve_person_instance_ownership,
    validate_person_instance_ownership_report,
)
from maskfactory.providers.disagreement import binary_mask_sha256


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _report(provider: str, family: str, boxes: list[tuple[int, list[int]]]) -> dict:
    return {
        "provider_id": provider,
        "family_id": family,
        "source_sha256": _sha("source"),
        "report_sha256": _sha(provider),
        "persons": [
            {"person_index": index, "bbox_xyxy": bbox, "confidence": 0.9} for index, bbox in boxes
        ],
    }


def _resolve(mask: np.ndarray, reports: list[dict]) -> dict:
    return resolve_person_instance_ownership(
        mask,
        source_sha256=_sha("source"),
        mask_sha256=binary_mask_sha256(mask),
        candidate_label="breast_region",
        detector_reports=reports,
    )


def test_two_independent_detectors_verify_the_same_person() -> None:
    mask = np.zeros((100, 120), dtype=np.bool_)
    mask[20:40, 10:30] = True
    result = _resolve(
        mask,
        [
            _report("yolo11m", "yolo", [(0, [5, 5, 45, 90]), (1, [65, 5, 115, 95])]),
            _report("rf_detr_medium", "rfdetr", [(0, [3, 4, 47, 92]), (1, [63, 4, 118, 96])]),
        ],
    )
    assert result["status"] == "verified"
    assert result["person_index"] == 0
    assert result["owner_id"] == "person-0"
    assert result["scene_instance_id"].endswith("-p0")
    assert result["production_mask_authority"] is False


def test_cross_person_overlap_abstains_without_guessing() -> None:
    mask = np.zeros((100, 120), dtype=np.bool_)
    mask[20:40, 50:70] = True
    result = _resolve(
        mask,
        [
            _report("yolo11m", "yolo", [(0, [0, 0, 65, 100]), (1, [55, 0, 120, 100])]),
            _report("rf_detr_medium", "rfdetr", [(0, [0, 0, 68, 100]), (1, [52, 0, 120, 100])]),
        ],
    )
    assert result["status"] == "ambiguous"
    assert result["person_index"] is None
    assert result["owner_id"] is None
    assert result["reasons"] == ["person_instance_ownership_ambiguous"]


def test_detector_index_without_spatial_agreement_cannot_verify() -> None:
    mask = np.zeros((100, 120), dtype=np.bool_)
    mask[20:40, 10:30] = True
    result = _resolve(
        mask,
        [
            _report("yolo11m", "yolo", [(0, [5, 5, 45, 90])]),
            _report("rf_detr_medium", "rfdetr", [(0, [0, 0, 120, 100])]),
        ],
    )
    assert result["status"] == "ambiguous"


def test_detector_person_count_disagreement_cannot_merge_people_into_p0() -> None:
    mask = np.zeros((100, 120), dtype=np.bool_)
    mask[20:40, 10:30] = True
    result = _resolve(
        mask,
        [
            _report("yolo11m", "yolo", [(0, [0, 0, 120, 100])]),
            _report(
                "groundingdino",
                "groundingdino",
                [(0, [0, 0, 55, 100]), (1, [60, 0, 120, 100])],
            ),
        ],
    )
    assert result["status"] == "ambiguous"
    assert result["person_catalog_consensus"] is False
    assert result["person_index"] is None
    assert result["reasons"] == ["person_detector_catalog_disagreement"]


@pytest.mark.parametrize("mutation", ["same_family", "source", "mask_hash"])
def test_provenance_drift_fails_closed(mutation: str) -> None:
    mask = np.zeros((50, 50), dtype=np.bool_)
    mask[10:20, 10:20] = True
    reports = [
        _report("yolo11m", "yolo", [(0, [0, 0, 40, 45])]),
        _report("rf_detr_medium", "rfdetr", [(0, [0, 0, 42, 46])]),
    ]
    kwargs = {
        "source_sha256": _sha("source"),
        "mask_sha256": binary_mask_sha256(mask),
        "candidate_label": "nipple",
        "detector_reports": reports,
    }
    if mutation == "same_family":
        reports[1]["family_id"] = "yolo"
    elif mutation == "source":
        reports[1]["source_sha256"] = _sha("other")
    else:
        kwargs["mask_sha256"] = _sha("other-mask")
    with pytest.raises(NudePersonOwnershipError):
        resolve_person_instance_ownership(mask, **kwargs)


def test_single_detector_cannot_claim_verified_ownership() -> None:
    mask = np.zeros((50, 50), dtype=np.bool_)
    mask[10:20, 10:20] = True
    with pytest.raises(NudePersonOwnershipError, match="two_detector_families_required"):
        _resolve(mask, [_report("yolo11m", "yolo", [(0, [0, 0, 40, 45])])])


def test_terminal_replay_rejects_detector_box_drift() -> None:
    mask = np.zeros((100, 120), dtype=np.bool_)
    mask[20:40, 10:30] = True
    result = _resolve(
        mask,
        [
            _report("yolo11m", "yolo", [(0, [5, 5, 45, 90])]),
            _report("rf_detr_medium", "rfdetr", [(0, [3, 4, 47, 92])]),
        ],
    )
    result["detector_reports"][1]["persons"][0]["bbox_xyxy"] = [70, 5, 115, 95]
    with pytest.raises(NudePersonOwnershipError, match="ownership_report_drift"):
        validate_person_instance_ownership_report(
            result,
            mask,
            source_sha256=_sha("source"),
            mask_sha256=binary_mask_sha256(mask),
            candidate_label="breast_region",
        )
