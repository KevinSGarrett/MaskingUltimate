import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.io.png_strict import read_mask, write_label_map
from maskfactory.training.handseg.audit import (
    CLASS_ID,
    HandAuditError,
    build_ambiguous_hand_audit,
    evaluate_hand_promotion_gate,
    evaluate_merged_finger_false_splits,
    write_hand_promotion_gate,
)


def test_seeded_ambiguous_hand_corpus_is_reproducible_and_balanced(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    build_ambiguous_hand_audit(first)
    build_ambiguous_hand_audit(second)
    a = json.loads((first / "manifest.json").read_text())
    b = json.loads((second / "manifest.json").read_text())
    assert a == b
    assert a["seed"] == 1337 and a["case_count"] == 100
    assert sum(case["side"] == "left" for case in a["cases"]) == 50
    assert sum(case["side"] == "right" for case in a["cases"]) == 50
    for case in a["cases"]:
        ambiguity = read_mask(first / case["ambiguity_mask"]) > 0
        truth = read_mask(first / case["truth"])
        assert ambiguity.any()
        assert set(np.unique(truth[ambiguity])) == {CLASS_ID[case["truth_class"]]}
        for relative in (case["image"], case["truth"], case["ambiguity_mask"]):
            assert (first / relative).read_bytes() == (second / relative).read_bytes()


def test_false_split_rate_has_strict_two_percent_boundary(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    predictions = tmp_path / "predictions"
    predictions.mkdir()
    manifest_path = build_ambiguous_hand_audit(audit)
    manifest = json.loads(manifest_path.read_text())
    for case in manifest["cases"]:
        shutil.copy2(audit / case["truth"], predictions / f"{case['case_id']}.png")
    clean = evaluate_merged_finger_false_splits(audit, predictions)
    assert clean["passed"] and clean["false_split_rate"] == 0
    for index in (0, 1):
        case = manifest["cases"][index]
        path = predictions / f"{case['case_id']}.png"
        prediction = np.asarray(Image.open(path)).copy()
        ambiguity = read_mask(audit / case["ambiguity_mask"]) > 0
        prediction[ambiguity] = CLASS_ID[case["affected_fingers"][0]]
        write_label_map(path, prediction, bits=8)
        result = evaluate_merged_finger_false_splits(audit, predictions)
        assert result["false_split_count"] == index + 1
        assert result["passed"] is (index == 0)  # 1% passes; strict 2% does not


def test_false_split_audit_refuses_missing_or_unknown_predictions(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    predictions = tmp_path / "predictions"
    predictions.mkdir()
    manifest = json.loads(build_ambiguous_hand_audit(audit).read_text())
    with pytest.raises(HandAuditError, match="missing"):
        evaluate_merged_finger_false_splits(audit, predictions)
    for case in manifest["cases"]:
        shutil.copy2(audit / case["truth"], predictions / f"{case['case_id']}.png")
    first = predictions / f"{manifest['cases'][0]['case_id']}.png"
    bad = np.asarray(Image.open(first)).copy()
    bad[0, 0] = 200
    write_label_map(first, bad, bits=8)
    with pytest.raises(HandAuditError, match="unknown"):
        evaluate_merged_finger_false_splits(audit, predictions)


def _leaderboard(finger_iou: float = 0.70) -> dict:
    return {
        "run_id": "r_hand_fixture",
        "dataset_ref": "bodyparts@v7",
        "split": "test_holdout",
        "group_scores": {"fingers": {"iou": finger_iou, "bf": 0.8}},
    }


@pytest.mark.parametrize(
    ("finger_iou", "false_rate", "paste_iou", "passed"),
    [
        (0.70, 0.01, 0.995, True),
        (0.699999, 0.01, 0.995, False),
        (0.70, 0.02, 0.995, False),
        (0.70, 0.01, 0.994999, False),
    ],
)
def test_d7_hand_gate_requires_all_three_exact_thresholds(
    tmp_path: Path,
    finger_iou: float,
    false_rate: float,
    paste_iou: float,
    passed: bool,
) -> None:
    result = evaluate_hand_promotion_gate(
        _leaderboard(finger_iou),
        {"case_count": 100, "false_split_rate": false_rate},
        paste_back_iou=paste_iou,
    )
    assert result["passed"] is passed
    path = write_hand_promotion_gate(tmp_path / "gate.json", result)
    assert json.loads(path.read_text()) == result


def test_d7_hand_gate_refuses_nonholdout_or_incomplete_audit() -> None:
    row = _leaderboard()
    row["split"] = "val"
    with pytest.raises(HandAuditError, match="test_holdout"):
        evaluate_hand_promotion_gate(
            row, {"case_count": 100, "false_split_rate": 0}, paste_back_iou=1
        )
    with pytest.raises(HandAuditError, match="at least 100"):
        evaluate_hand_promotion_gate(
            _leaderboard(), {"case_count": 99, "false_split_rate": 0}, paste_back_iou=1
        )
