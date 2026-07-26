from __future__ import annotations

import copy

import numpy as np
import pytest

from maskfactory.steward.mask_hard_qa_campaign import (
    CHECK_NAMES,
    MaskHardQAError,
    MaskHardQALimits,
    evaluate_mask_campaign,
    evaluate_mask_candidate,
    evaluate_mask_record,
    validate_mask_campaign,
)


def _resources() -> dict:
    owner = np.zeros((16, 16), dtype=bool)
    owner[1:15, 1:15] = True
    side = np.zeros((16, 16), dtype=bool)
    side[:, :8] = True
    protected = np.zeros((16, 16), dtype=bool)
    protected[10:14, 10:14] = True
    complete_map = np.zeros((16, 16), dtype=np.uint16)
    complete_map[10:14, 10:14] = 2
    return {
        "owner": owner,
        "side": side,
        "protected": protected,
        "complete_map": complete_map,
    }


def _valid_mask() -> np.ndarray:
    mask = np.zeros((16, 16), dtype=np.uint8)
    mask[3:7, 3:7] = 255
    return mask


def _evaluate(mask: object, **kwargs: object) -> dict:
    result, _ = evaluate_mask_candidate(
        record_id="record-1",
        provider_id="provider-1",
        candidate_mask=mask,
        candidate_label_id=kwargs.pop("candidate_label_id", 1),
        resources=kwargs.pop("resources", _resources()),
        target_label_id=1,
        ontology_label_ids=[1, 2],
        limits=kwargs.pop(
            "limits",
            MaskHardQALimits(max_components=1, max_repair_attempts=0),
        ),
        **kwargs,
    )
    return result


def _check_status(result: dict, name: str) -> str:
    return next(
        row["status"] for row in result["initial_checks"] if row["name"] == name
    )


def test_valid_candidate_passes_every_hard_check_and_preserves_parent() -> None:
    mask = _valid_mask()
    before = mask.copy()

    result = _evaluate(mask)

    assert result["outcome"] == "PASS"
    assert [row["name"] for row in result["initial_checks"]] == list(CHECK_NAMES)
    assert all(row["status"] == "PASS" for row in result["initial_checks"])
    assert result["parent_preserved"] is True
    assert np.array_equal(mask, before)


@pytest.mark.parametrize(
    ("fault", "check"),
    [
        ("format", "format"),
        ("ontology", "ontology"),
        ("ownership", "ownership"),
        ("laterality", "laterality"),
        ("topology", "topology"),
        ("protected_region", "protected_region"),
        ("complete_map", "complete_map"),
    ],
)
def test_seeded_hard_qa_faults_veto_before_acceptance(
    fault: str,
    check: str,
) -> None:
    mask: object = _valid_mask()
    resources = _resources()
    candidate_label_id = 1
    if fault == "format":
        mask = np.full((16, 16), 0.5, dtype=np.float32)
    elif fault == "ontology":
        candidate_label_id = 99
    elif fault == "ownership":
        mask = _valid_mask()
        mask[0, 0] = 255
    elif fault == "laterality":
        mask = _valid_mask()
        mask[3:5, 12:14] = 255
        resources["owner"][3:5, 12:14] = True
    elif fault == "topology":
        mask = _valid_mask()
        mask[12:14, 3:5] = 255
    elif fault == "protected_region":
        mask = _valid_mask()
        mask[11:13, 11:13] = 255
        resources["owner"][11:13, 11:13] = True
        resources["side"][11:13, 11:13] = True
    elif fault == "complete_map":
        mask = _valid_mask()
        resources["complete_map"][4:6, 4:6] = 2

    result = _evaluate(
        mask,
        resources=resources,
        candidate_label_id=candidate_label_id,
    )

    assert result["outcome"] == "VETO"
    assert _check_status(result, check) == "BLOCK"


def test_hypothesis_distinct_repair_passes_without_mutating_parent() -> None:
    mask = _valid_mask()
    mask[11:13, 11:13] = 255
    before = mask.copy()
    resources = _resources()
    resources["owner"][11:13, 11:13] = True
    resources["side"][11:13, 11:13] = True

    result = _evaluate(
        mask,
        resources=resources,
        limits=MaskHardQALimits(max_components=1, max_repair_attempts=2),
    )

    assert result["outcome"] == "PASS_AFTER_REPAIR"
    assert result["repairs"][0]["hypothesis"] == "largest_component"
    assert result["repairs"][0]["before_sha256"] != result["repairs"][0]["after_sha256"]
    assert result["parent_preserved"] is True
    assert np.array_equal(mask, before)


def test_no_progress_repair_terminates_without_repeating_hypothesis() -> None:
    mask = _valid_mask()
    mask[11:13, 11:13] = 255
    resources = _resources()
    resources["owner"][11:13, 11:13] = True
    resources["side"][11:13, 11:13] = True

    result = _evaluate(
        mask,
        resources=resources,
        limits=MaskHardQALimits(max_components=1, max_repair_attempts=3),
        repairer=lambda _hypothesis, current, _resources, _label: current,
    )

    assert result["outcome"] == "NO_PROGRESS"
    assert len(result["repairs"]) == 1
    assert result["repairs"][0]["before_sha256"] == result["repairs"][0]["after_sha256"]


def test_repair_callback_failure_is_typed_and_fail_closed() -> None:
    mask = _valid_mask()
    mask[11:13, 11:13] = 255
    resources = _resources()
    resources["owner"][11:13, 11:13] = True
    resources["side"][11:13, 11:13] = True

    def fail_repair(
        _hypothesis: str,
        _current: np.ndarray,
        _resources: dict[str, np.ndarray],
        _label: int,
    ) -> np.ndarray:
        raise RuntimeError("private callback detail")

    with pytest.raises(MaskHardQAError, match="repair callback failed closed"):
        _evaluate(
            mask,
            resources=resources,
            limits=MaskHardQALimits(max_components=1, max_repair_attempts=1),
            repairer=fail_repair,
        )


def test_provider_disagreement_is_measured_deterministically() -> None:
    first = _valid_mask()
    second = np.zeros((16, 16), dtype=np.uint8)
    second[3:7, 4:8] = 255
    record = evaluate_mask_record(
        record_id="record-1",
        candidates=[
            {"provider_id": "a", "label_id": 1, "mask": first},
            {"provider_id": "b", "label_id": 1, "mask": second},
        ],
        resources=_resources(),
        target_label_id=1,
        ontology_label_ids=[1, 2],
        limits=MaskHardQALimits(
            max_components=1,
            max_repair_attempts=0,
            disagreement_iou_floor=0.75,
        ),
    )

    assert record["passed_candidate_count"] == 2
    assert record["disagreement"] == [
        {
            "left_provider_id": "a",
            "right_provider_id": "b",
            "iou": 0.6,
            "status": "DISAGREE",
        }
    ]


def test_bad_record_does_not_block_unrelated_record() -> None:
    good = {
        "record_id": "good",
        "candidates": [
            {"provider_id": "a", "label_id": 1, "mask": _valid_mask()}
        ],
        "resources": _resources(),
        "target_label_id": 1,
        "ontology_label_ids": [1, 2],
    }
    bad = copy.deepcopy(good)
    bad["record_id"] = "bad"
    bad["resources"] = {"missing": np.zeros((16, 16), dtype=bool)}

    campaign = evaluate_mask_campaign(
        [bad, good],
        limits=MaskHardQALimits(max_components=1, max_repair_attempts=0),
    )

    assert campaign["record_count"] == 2
    assert campaign["records"][0]["record_outcome"] == "ABSTAIN"
    assert campaign["records"][1]["record_outcome"] == "PASS"
    assert campaign["passed_record_count"] == 1
    assert validate_mask_campaign(
        campaign,
        records=[bad, good],
        limits=MaskHardQALimits(max_components=1, max_repair_attempts=0),
    ) == campaign


def test_rehashed_campaign_outcome_drift_is_rejected() -> None:
    record = {
        "record_id": "good",
        "candidates": [
            {"provider_id": "a", "label_id": 1, "mask": _valid_mask()}
        ],
        "resources": _resources(),
        "target_label_id": 1,
        "ontology_label_ids": [1, 2],
    }
    limits = MaskHardQALimits(max_components=1, max_repair_attempts=0)
    campaign = evaluate_mask_campaign([record], limits=limits)
    campaign["passed_record_count"] = 0
    campaign["campaign_sha256"] = "0" * 64
    campaign["campaign_sha256"] = __import__("hashlib").sha256(
        __import__("json").dumps(
            campaign,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(MaskHardQAError, match="differs from deterministic"):
        validate_mask_campaign(campaign, records=[record], limits=limits)
