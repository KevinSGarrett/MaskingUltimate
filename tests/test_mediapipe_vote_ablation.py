import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from maskfactory.providers.mediapipe_ablation import (
    DEFAULT_POLICY_PATH,
    POLICY_SHA256,
    MediapipeAblationError,
    build_report,
    load_policy,
    validate_policy,
    verify_report,
)
from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]


def _sha256(value) -> str:
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _landmarks() -> list[list[float]]:
    return [[(index + 1) / 22, (index + 1) / 44, -index / 100] for index in range(21)]


def _mirrored(points: list[list[float]]) -> list[list[float]]:
    return [[1.0 - x, y, z] for x, y, z in points]


def _vote(side: str | None, seed: str) -> dict:
    return {
        "side": side,
        "evidence_sha256": _sha256(seed.encode()) if side is not None else None,
    }


def _case(
    case_id: str,
    *,
    truth_side: str,
    skeleton: str,
    densepose: str | None,
    mediapipe: str,
    score: float = 0.99,
    kind: str = "human_anchor",
    pair_id: str | None = None,
    landmarks: list[list[float]] | None = None,
) -> dict:
    label = f"{truth_side}_hand_base"
    return {
        "case_id": case_id,
        "kind": kind,
        "mirror_pair_id": pair_id,
        "image_id": f"image-{case_id}",
        "package_id": f"package-{case_id}",
        "truth_label": label,
        "truth_side": truth_side,
        "source_image_sha256": _sha256(f"source-{case_id}".encode()),
        "truth_mask_sha256": _sha256(f"truth-{case_id}".encode()),
        "pose_skeleton": _vote(skeleton, f"skeleton-{case_id}"),
        "densepose_surface": _vote(densepose, f"densepose-{case_id}"),
        "mediapipe_handedness": {
            **_vote(mediapipe, f"mediapipe-{case_id}"),
            "score": score,
            "landmarks": landmarks or _landmarks(),
        },
    }


def _mirror_fixture(case: dict, case_id: str) -> dict:
    mirrored = copy.deepcopy(case)
    mirrored["case_id"] = case_id
    mirrored["image_id"] = f"image-{case_id}"
    mirrored["package_id"] = f"package-{case_id}"
    mirrored["truth_side"] = "right" if case["truth_side"] == "left" else "left"
    mirrored["truth_label"] = f"{mirrored['truth_side']}_hand_base"
    mirrored["source_image_sha256"] = _sha256(f"source-{case_id}".encode())
    mirrored["truth_mask_sha256"] = _sha256(f"truth-{case_id}".encode())
    for field in ("pose_skeleton", "densepose_surface", "mediapipe_handedness"):
        side = case[field]["side"]
        mirrored[field]["side"] = None if side is None else ("right" if side == "left" else "left")
        if side is not None:
            mirrored[field]["evidence_sha256"] = _sha256(f"{field}-{case_id}".encode())
    mirrored["mediapipe_handedness"]["landmarks"] = _mirrored(
        case["mediapipe_handedness"]["landmarks"]
    )
    return mirrored


def _fixture(tmp_path: Path, *, incremental: bool = True) -> tuple[dict, Path]:
    truth_manifest = tmp_path / "human_anchor_holdout.json"
    truth_manifest.write_text('{"partition":"holdout","tier":"human_anchor_gold"}\n')
    human = [
        _case(
            "anchor-rescue",
            truth_side="left",
            skeleton="left",
            densepose=None,
            mediapipe="left" if incremental else "right",
        ),
        _case(
            "anchor-stable",
            truth_side="right",
            skeleton="right",
            densepose="right",
            mediapipe="right",
        ),
    ]
    left_fixture = _case(
        "flip-left",
        truth_side="left",
        skeleton="left",
        densepose=None,
        mediapipe="left",
        kind="side_swap_fixture",
        pair_id="flip-pair-1",
    )
    right_fixture = _mirror_fixture(left_fixture, "flip-right")
    document = {
        "schema_version": "1.0.0",
        "benchmark_id": "mediapipe-ablation-fixture-v1",
        "results_opened_at": "2026-07-15T07:00:00Z",
        "policy_sha256": POLICY_SHA256,
        "truth_tier": "human_anchor_gold",
        "truth_partition": "holdout",
        "truth_manifest_sha256": hashlib.sha256(truth_manifest.read_bytes()).hexdigest(),
        "pipeline_fingerprint_sha256": "c" * 64,
        "hand_landmarker_artifact_sha256": (
            "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"
        ),
        "cases": [*human, left_fixture, right_fixture],
    }
    document["sha256"] = _sha256(document)
    return document, truth_manifest


def _reseal(document: dict) -> None:
    document["sha256"] = _sha256({key: value for key, value in document.items() if key != "sha256"})


def test_frozen_policy_is_schema_valid_hash_locked_and_source_current() -> None:
    policy = load_policy()
    assert DEFAULT_POLICY_PATH == (
        ROOT / "qa/governance/benchmark_matrices/mediapipe_vote_ablation_v1.json"
    )
    assert policy["sha256"] == POLICY_SHA256
    assert not validate_document(policy, "mediapipe_vote_ablation_policy")


def test_policy_edit_fails_even_after_resealing() -> None:
    policy = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    policy["mediapipe_minimum_score"] = 0.1
    _reseal(policy)
    with pytest.raises(MediapipeAblationError, match="locked hash"):
        validate_policy(policy)


def test_vote_ablation_counts_safe_incremental_rescue_and_excludes_flip_cases(
    tmp_path: Path,
) -> None:
    cases, truth_manifest = _fixture(tmp_path)
    report = build_report(cases, truth_manifest_path=truth_manifest)

    assert not validate_document(report, "mediapipe_vote_ablation_report")
    assert report["result"] == "pass"
    assert report["human_anchor_case_count"] == 2
    assert report["side_swap_pair_count"] == 1
    assert report["baseline_metrics"] == {
        "total": 2,
        "correct": 1,
        "wrong_side": 0,
        "abstain": 1,
        "decided": 1,
        "coverage": 0.5,
        "accuracy_when_decided": 1.0,
        "wrong_side_rate": 0.0,
    }
    assert report["with_mediapipe_metrics"]["correct"] == 2
    assert report["delta"] == {
        "correct": 1,
        "wrong_side": 0,
        "abstain": -1,
        "coverage": 0.5,
    }
    verify_report(report, cases, truth_manifest_path=truth_manifest)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("unswapped_vote", "vote was not swapped"),
        ("unswapped_landmark", "geometry is not an exact x mirror"),
        ("reused_evidence", "reused unswapped evidence"),
        ("missing_pair", "must contain exactly two cases"),
    ],
)
def test_each_side_swap_invariant_fails_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    cases, truth_manifest = _fixture(tmp_path)
    right = cases["cases"][-1]
    left = cases["cases"][-2]
    if mutation == "unswapped_vote":
        right["mediapipe_handedness"]["side"] = left["mediapipe_handedness"]["side"]
    elif mutation == "unswapped_landmark":
        right["mediapipe_handedness"]["landmarks"][0][0] = left["mediapipe_handedness"][
            "landmarks"
        ][0][0]
    elif mutation == "reused_evidence":
        right["pose_skeleton"]["evidence_sha256"] = left["pose_skeleton"]["evidence_sha256"]
    elif mutation == "missing_pair":
        cases["cases"].pop()
    _reseal(cases)
    with pytest.raises(MediapipeAblationError, match=expected):
        build_report(cases, truth_manifest_path=truth_manifest)


def test_low_confidence_mediapipe_vote_is_not_counted(tmp_path: Path) -> None:
    cases, truth_manifest = _fixture(tmp_path)
    rescue = cases["cases"][0]
    rescue["mediapipe_handedness"]["score"] = 0.49
    _reseal(cases)
    report = build_report(cases, truth_manifest_path=truth_manifest)
    assert report["result"] == "fail"
    assert report["case_results"][0]["mediapipe_used"] is False
    assert report["findings"] == ["no_incremental_correct_decision"]
    verify_report(
        report,
        cases,
        truth_manifest_path=truth_manifest,
        require_pass=False,
    )
    with pytest.raises(MediapipeAblationError, match="did not show safe incremental value"):
        verify_report(report, cases, truth_manifest_path=truth_manifest)


def test_new_wrong_side_decision_is_a_zero_tolerance_regression(tmp_path: Path) -> None:
    cases, truth_manifest = _fixture(tmp_path, incremental=False)
    cases["cases"][0]["pose_skeleton"]["side"] = "right"
    _reseal(cases)
    report = build_report(cases, truth_manifest_path=truth_manifest)
    assert report["result"] == "fail"
    assert report["delta"]["wrong_side"] == 1
    assert report["findings"] == [
        "no_incremental_correct_decision",
        "incremental_wrong_side_regression",
    ]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("truth_tier", "human_anchor_gold"),
        ("results_opened_at", "predate frozen policy"),
        ("policy_sha256", "policy hash mismatch"),
        ("hand_landmarker_artifact_sha256", "artifact hash mismatch"),
    ],
)
def test_authority_and_pre_result_bindings_fail_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    cases, truth_manifest = _fixture(tmp_path)
    if mutation == "truth_tier":
        cases[mutation] = "autonomous_certified_gold"
    elif mutation == "results_opened_at":
        cases[mutation] = "2026-07-15T06:25:00Z"
    else:
        cases[mutation] = "d" * 64
    _reseal(cases)
    with pytest.raises(MediapipeAblationError, match=expected):
        build_report(cases, truth_manifest_path=truth_manifest)


def test_truth_manifest_drift_and_duplicate_hand_case_fail(tmp_path: Path) -> None:
    cases, truth_manifest = _fixture(tmp_path)
    truth_manifest.write_text("drift\n", encoding="utf-8")
    with pytest.raises(MediapipeAblationError, match="truth manifest hash mismatch"):
        build_report(cases, truth_manifest_path=truth_manifest)

    cases, truth_manifest = _fixture(tmp_path)
    duplicate = copy.deepcopy(cases["cases"][0])
    duplicate["case_id"] = "duplicate-case-id"
    cases["cases"].append(duplicate)
    _reseal(cases)
    with pytest.raises(MediapipeAblationError, match="duplicate human-anchor image/hand"):
        build_report(cases, truth_manifest_path=truth_manifest)


def test_report_tamper_cannot_survive_recomputation(tmp_path: Path) -> None:
    cases, truth_manifest = _fixture(tmp_path)
    report = build_report(cases, truth_manifest_path=truth_manifest)
    report["delta"]["correct"] = 99
    report["sha256"] = _sha256({key: value for key, value in report.items() if key != "sha256"})
    with pytest.raises(MediapipeAblationError, match="recomputation mismatch"):
        verify_report(report, cases, truth_manifest_path=truth_manifest)


def test_one_command_tool_builds_and_verifies_hash_sealed_report(tmp_path: Path) -> None:
    cases, truth_manifest = _fixture(tmp_path)
    cases_path = tmp_path / "cases.json"
    report_path = tmp_path / "report.json"
    cases_path.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    command = [
        sys.executable,
        str(ROOT / "tools/evaluate_mediapipe_vote_ablation.py"),
        str(cases_path),
        "--truth-manifest",
        str(truth_manifest),
        "--output",
        str(report_path),
    ]
    built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert built.returncode == 0, built.stderr
    verified = subprocess.run(
        [*command, "--verify"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert verified.returncode == 0, verified.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["result"] == "pass"
