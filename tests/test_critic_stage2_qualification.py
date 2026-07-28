from __future__ import annotations

from copy import deepcopy

import pytest

from maskfactory.vlm.critic_protocol_v3 import PROTOCOL_ID
from maskfactory.vlm.critic_stage2_qualification import (
    CriticStage2QualificationError,
    evaluate_stage2_qualification,
    seal_stage2_board,
    seal_stage2_results,
)

HEX = "a" * 64


def _sha(index: int) -> str:
    return f"{index:064x}"


def _board() -> dict:
    cases = []
    for index in range(100):
        valid = index < 40
        cases.append(
            {
                "case_id": f"stage2-{index:03d}",
                "partition": "qualification_holdout",
                "label_id": "hair" if index % 2 else "neck",
                "expected_outcome": "valid_mask" if valid else "known_defect",
                "expected_severity": "none" if valid else "serious",
                "source_authority_tier": "external_labeled_reference",
                "source_sha256": _sha(index + 1),
                "target_contract_sha256": _sha(index + 101),
                "panel_set_sha256": _sha(index + 201),
            }
        )
    return seal_stage2_board(
        {
            "schema_version": "maskfactory.critic_stage2_board.v1",
            "board_id": "critic-stage2-hair-neck-v1",
            "frozen_at": "2026-07-23T00:00:00Z",
            "role_id": "primary_visual_critic",
            "protocol_id": PROTOCOL_ID,
            "registry_sha256": HEX,
            "corpus_sha256": "b" * 64,
            "execution_manifest_sha256": "c" * 64,
            "cases": cases,
            "board_sha256": "",
        }
    )


def _results(board: dict) -> dict:
    predictions = []
    for case in board["cases"]:
        defect = case["expected_outcome"] == "known_defect"
        predictions.append(
            {
                "case_id": case["case_id"],
                "verdict": "defect" if defect else "pass",
                "serious_dimensions": ["boundary"] if defect else [],
                "schema_valid": True,
                "deterministic_replay": True,
                "evidence_localization_coherent": True,
                "response_sha256": _sha(400 + len(predictions)),
            }
        )
    return seal_stage2_results(
        {
            "schema_version": "maskfactory.critic_stage2_results.v1",
            "board_sha256": board["board_sha256"],
            "model_id": "example-v3-model",
            "family_id": "example-family",
            "runtime_sha256": "d" * 64,
            "artifact_tree_sha256": "e" * 64,
            "prompt_sha256": "f" * 64,
            "predictions": predictions,
            "results_sha256": "",
        }
    )


def test_stage2_passes_only_with_wilson_bounds_and_zero_tolerance() -> None:
    board = _board()
    report = evaluate_stage2_qualification(board, _results(board))
    assert report["status"] == "pass"
    assert report["metrics"]["serious_defect_recall_wilson_lower_95"] >= 0.90
    assert report["metrics"]["valid_mask_pass_wilson_lower_95"] >= 0.80
    assert report["authority_claimed"] is False
    assert report["role_certificate_issuance_allowed"] is False


def test_stage2_rejects_a_serious_false_pass_even_when_wilson_recall_survives() -> None:
    board = _board()
    results = _results(board)
    results = deepcopy(results)
    results["predictions"][40]["verdict"] = "pass"
    results["predictions"][40]["serious_dimensions"] = []
    results = seal_stage2_results({**results, "results_sha256": ""})
    report = evaluate_stage2_qualification(board, results)
    assert report["status"] == "fail"
    assert "serious_false_passes_present" in report["failures"]


def test_stage2_rejects_boards_smaller_than_one_hundred_cases() -> None:
    value = _board()
    value = deepcopy(value)
    value["cases"] = value["cases"][:-1]
    with pytest.raises(CriticStage2QualificationError, match="fewer than 100"):
        seal_stage2_board({**value, "board_sha256": ""})


def test_stage2_rejects_incomplete_prediction_coverage() -> None:
    board = _board()
    results = _results(board)
    results = deepcopy(results)
    results["predictions"] = results["predictions"][:-1]
    results = seal_stage2_results({**results, "results_sha256": ""})
    with pytest.raises(CriticStage2QualificationError, match="cover the board exactly"):
        evaluate_stage2_qualification(board, results)
