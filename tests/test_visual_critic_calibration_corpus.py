from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest

from maskfactory.vlm.calibration_corpus import (
    DEFECT_TYPES,
    CalibrationCorpusError,
    calibration_corpus_sha256,
    panel_set_sha256,
    validate_calibration_corpus,
)
from maskfactory.vlm.target_contract import target_contract_sha256


def _contract(index: int) -> dict:
    def digest(name: str) -> str:
        return hashlib.sha256(f"{name}-{index}".encode()).hexdigest()

    contract = {
        "schema_version": "1.0.0",
        "contract_id": f"target-{index}",
        "source": {
            "image_id": f"image-{index}",
            "sha256": digest("source"),
            "width": 128,
            "height": 128,
        },
        "owner": {
            "person_index": 0,
            "character_instance_id": f"character-{index}",
            "person_mask_sha256": digest("person"),
        },
        "target": {
            "label_id": "left_hand",
            "expected_presence": "visible_nonempty",
            "minimum_area_pixels": 1,
            "maximum_area_pixels": 1000,
            "allowed_roi_xyxy": [0, 0, 128, 128],
            "inclusion_rule": "visible_pixels_only",
            "exclusion_rule": "exclude_occluded_outside_owner_and_named_labels",
        },
        "candidate": {
            "mask_sha256": digest("candidate"),
            "width": 128,
            "height": 128,
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


def _case(index: int, partition: str, outcome: str, defect: str | None) -> dict:
    contract = _contract(index)

    def digest(name: str) -> str:
        return hashlib.sha256(f"{name}-{index}".encode()).hexdigest()

    panels = {
        "source": contract["source"]["sha256"],
        "binary_mask": contract["candidate"]["mask_sha256"],
        "overlay": digest("overlay"),
        "contour": digest("contour"),
        "full_context": digest("context"),
        "uncertainty_zoom": digest("zoom"),
    }
    case = {
        "case_id": f"case-{index}",
        "partition": partition,
        "expected_outcome": outcome,
        "defect_type": defect,
        "target_contract": contract,
        "panels": panels,
        "panel_set_sha256": "",
    }
    case["panel_set_sha256"] = panel_set_sha256(case)
    return case


def _manifest() -> dict:
    defects = sorted(DEFECT_TYPES)
    cases = [_case(1, "calibration", "valid_mask", None)]
    cases += [
        _case(index + 2, "calibration", "known_defect", defect)
        for index, defect in enumerate(defects[:5])
    ]
    cases += [_case(20, "qualification_holdout", "valid_mask", None)]
    cases += [
        _case(index + 21, "qualification_holdout", "known_defect", defect)
        for index, defect in enumerate(defects[5:])
    ]
    manifest = {
        "schema_version": "1.0.0",
        "corpus_id": "visual-critic-calibration-v1",
        "frozen_at": "2026-07-21T00:00:00Z",
        "partitions": ["calibration", "qualification_holdout"],
        "defect_taxonomy": defects,
        "cases": cases,
        "corpus_sha256": "",
    }
    manifest["corpus_sha256"] = calibration_corpus_sha256(manifest)
    return manifest


def _reseal(manifest: dict) -> None:
    manifest["corpus_sha256"] = calibration_corpus_sha256(manifest)


def test_balanced_image_disjoint_exactly_bound_corpus_passes() -> None:
    validate_calibration_corpus(_manifest())


@pytest.mark.parametrize("keep", ["valid_mask", "known_defect"])
def test_all_good_or_all_bad_corpus_is_rejected(keep: str) -> None:
    manifest = _manifest()
    manifest["cases"] = [case for case in manifest["cases"] if case["expected_outcome"] == keep]
    _reseal(manifest)
    with pytest.raises(CalibrationCorpusError, match="both valid and defect"):
        validate_calibration_corpus(manifest)


def test_duplicate_panel_set_is_rejected() -> None:
    manifest = _manifest()
    duplicate = deepcopy(manifest["cases"][0])
    duplicate["case_id"] = "duplicate-case"
    manifest["cases"].append(duplicate)
    _reseal(manifest)
    with pytest.raises(CalibrationCorpusError, match="panel sets are duplicated"):
        validate_calibration_corpus(manifest)


def test_image_partition_leak_is_rejected() -> None:
    manifest = _manifest()
    leaked = manifest["cases"][-1]
    leaked["target_contract"]["source"] = deepcopy(
        manifest["cases"][0]["target_contract"]["source"]
    )
    leaked["target_contract"]["contract_sha256"] = target_contract_sha256(leaked["target_contract"])
    leaked["panels"]["source"] = leaked["target_contract"]["source"]["sha256"]
    leaked["panel_set_sha256"] = panel_set_sha256(leaked)
    _reseal(manifest)
    with pytest.raises(CalibrationCorpusError, match="leaks across"):
        validate_calibration_corpus(manifest)


def test_incomplete_target_contract_is_rejected_before_panel_use() -> None:
    manifest = _manifest()
    del manifest["cases"][0]["target_contract"]["owner"]
    _reseal(manifest)
    with pytest.raises(CalibrationCorpusError, match="target contract is incomplete"):
        validate_calibration_corpus(manifest)


def test_source_or_candidate_panel_hash_drift_is_rejected() -> None:
    manifest = _manifest()
    manifest["cases"][0]["panels"]["binary_mask"] = "f" * 64
    manifest["cases"][0]["panel_set_sha256"] = panel_set_sha256(manifest["cases"][0])
    _reseal(manifest)
    with pytest.raises(CalibrationCorpusError, match="panel hash drifted"):
        validate_calibration_corpus(manifest)
