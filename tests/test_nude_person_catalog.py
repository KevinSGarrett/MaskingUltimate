from __future__ import annotations

import hashlib

import pytest

from maskfactory.nude_person_catalog import (
    NudePersonCatalogError,
    build_person_catalog_stage_receipt,
    compare_person_proposal_catalogs,
    validate_person_catalog_stage_receipt,
    validate_person_proposal_catalog_report,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _proposal(box: list[float]) -> dict:
    return {
        "bbox_xyxy": box,
        "confidence": 0.9,
        "label": "person",
        "authority": "proposal_only",
    }


def _provider(provider: str, family: str, boxes: list[list[float]]) -> dict:
    return {
        "provider_id": provider,
        "family_id": family,
        "revision": "rev-1",
        "artifact_sha256": _sha(provider),
        "source_sha256": _sha("source"),
        "proposals": [_proposal(box) for box in boxes],
    }


def _compare(providers: list[dict]) -> dict:
    return compare_person_proposal_catalogs(
        sample_id="sample-1",
        source_sha256=_sha("source"),
        image_size=[200, 100],
        provider_records=providers,
    )


def test_reordered_independent_catalogs_get_stable_spatial_indexes() -> None:
    result = _compare(
        [
            _provider("yolo11m", "yolo", [[110, 5, 190, 95], [5, 5, 90, 95]]),
            _provider("groundingdino", "groundingdino", [[2, 3, 92, 97], [108, 4, 195, 96]]),
        ]
    )
    assert result["status"] == "pass"
    assert result["person_count"] == 2
    left_members = {
        member["family_id"]: member["bbox_xyxy"][0] for member in result["catalog"][0]["members"]
    }
    assert left_members == {"groundingdino": 2.0, "yolo": 5.0}
    assert result["production_mask_authority"] is False
    assert len(result["report_sha256"]) == 64
    assert validate_person_proposal_catalog_report(result) == result

    receipt = build_person_catalog_stage_receipt(result)
    assert receipt["stage"] == "person_catalog_comparison"
    assert receipt["operational_certificate_issued"] is False
    assert validate_person_catalog_stage_receipt(receipt) == receipt


def test_count_disagreement_abstains() -> None:
    result = _compare(
        [
            _provider("yolo11m", "yolo", [[5, 5, 90, 95]]),
            _provider(
                "groundingdino",
                "groundingdino",
                [[2, 3, 92, 97], [108, 4, 195, 96]],
            ),
        ]
    )
    assert result["status"] == "abstain"
    assert result["reasons"] == ["person_count_disagreement"]
    assert result["person_count"] is None


def test_ambiguous_spatial_matching_abstains() -> None:
    result = _compare(
        [
            _provider("yolo11m", "yolo", [[0, 0, 100, 100], [50, 0, 150, 100]]),
            _provider(
                "groundingdino",
                "groundingdino",
                [[25, 0, 125, 100], [25, 0, 125, 100]],
            ),
        ]
    )
    assert result["status"] == "abstain"
    assert result["reasons"] == ["person_spatial_matching_ambiguous"]


def test_zero_person_consensus_is_not_a_pass() -> None:
    result = _compare(
        [_provider("yolo11m", "yolo", []), _provider("groundingdino", "groundingdino", [])]
    )
    assert result["status"] == "abstain"
    assert result["reasons"] == ["no_person_consensus"]


@pytest.mark.parametrize("mutation", ["authority", "source", "bounds", "family"])
def test_proposal_truth_or_provenance_drift_fails_closed(mutation: str) -> None:
    providers = [
        _provider("yolo11m", "yolo", [[5, 5, 90, 95]]),
        _provider("groundingdino", "groundingdino", [[2, 3, 92, 97]]),
    ]
    if mutation == "authority":
        providers[0]["proposals"][0]["authority"] = "gold"
    elif mutation == "source":
        providers[1]["source_sha256"] = _sha("other")
    elif mutation == "bounds":
        providers[0]["proposals"][0]["bbox_xyxy"] = [0, 0, 201, 100]
    else:
        providers[1]["family_id"] = "yolo"
    with pytest.raises(NudePersonCatalogError):
        _compare(providers)


def test_catalog_stage_receipt_rejects_authority_tamper() -> None:
    report = _compare(
        [
            _provider("yolo11m", "yolo", [[5, 5, 90, 95]]),
            _provider("groundingdino", "groundingdino", [[2, 3, 92, 97]]),
        ]
    )
    receipt = build_person_catalog_stage_receipt(report)
    receipt["production_mask_authority"] = True
    with pytest.raises(NudePersonCatalogError, match="stage_evidence_drift"):
        validate_person_catalog_stage_receipt(receipt)
