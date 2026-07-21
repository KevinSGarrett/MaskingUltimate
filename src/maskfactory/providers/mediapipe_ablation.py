"""Frozen MediaPipe handedness-vote ablation and flip/swap verification."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..validation import ArtifactValidationError, require_valid_document

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY_PATH = (
    ROOT / "qa" / "governance" / "benchmark_matrices" / "mediapipe_vote_ablation_v1.json"
)
POLICY_SHA256 = "240a8baf54d146a45f35502570c9a9802456a82f2a0eacf45c7baa43b7ff60b7"
SOURCE_FILES = (
    "configs/pipeline.yaml",
    "configs/qa.yaml",
    "models/model_registry.json",
    "src/maskfactory/lanes/hand.py",
)
SIDES = frozenset({"left", "right"})
HAND_SWAP_PARTNERS = {
    "left_hand_base": "right_hand_base",
    "right_hand_base": "left_hand_base",
    "left_hand": "right_hand",
    "right_hand": "left_hand",
    "left_thumb": "right_thumb",
    "right_thumb": "left_thumb",
    "left_index_finger": "right_index_finger",
    "right_index_finger": "left_index_finger",
    "left_middle_finger": "right_middle_finger",
    "right_middle_finger": "left_middle_finger",
    "left_ring_finger": "right_ring_finger",
    "right_ring_finger": "left_ring_finger",
    "left_pinky": "right_pinky",
    "right_pinky": "left_pinky",
}


class MediapipeAblationError(ValueError):
    """The frozen vote-ablation input, report, or flip pair is invalid."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise MediapipeAblationError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise MediapipeAblationError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _opposite(side: str | None) -> str | None:
    if side is None:
        return None
    if side not in SIDES:
        raise MediapipeAblationError("side must be left, right, or null")
    return "right" if side == "left" else "left"


def validate_policy(
    document: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_sha256: str | None = POLICY_SHA256,
) -> None:
    """Validate the pre-result policy, locked hash, and every governing source byte."""
    try:
        require_valid_document(document, "mediapipe_vote_ablation_policy")
    except ArtifactValidationError as exc:
        raise MediapipeAblationError(str(exc)) from exc
    claimed = document["sha256"]
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if claimed != _canonical_sha256(payload):
        raise MediapipeAblationError("MediaPipe ablation policy hash mismatch")
    if expected_sha256 is not None and claimed != expected_sha256:
        raise MediapipeAblationError("MediaPipe ablation policy differs from locked hash")
    _timestamp(document["frozen_at"], "frozen_at")
    if document["eligible_truth"] != {
        "partition": "holdout",
        "tier": "human_anchor_gold",
    }:
        raise MediapipeAblationError("only human-anchor holdout truth is eligible")
    if document["baseline_vote_sources"] != ["densepose_surface", "pose_skeleton"]:
        raise MediapipeAblationError("baseline vote sources drifted")
    if document["full_vote_sources"] != [
        "densepose_surface",
        "mediapipe_handedness",
        "pose_skeleton",
    ]:
        raise MediapipeAblationError("full vote sources drifted")
    if document["decision_rule"] != {
        "minimum_matching_votes": 2,
        "on_no_majority": "abstain",
        "perspective": "character",
    }:
        raise MediapipeAblationError("QC-014 decision rule drifted")
    if document["pass_requirements"] != {
        "maximum_incremental_wrong_side_decisions": 0,
        "minimum_incremental_correct_decisions": 1,
        "require_side_swap_fixture": True,
    }:
        raise MediapipeAblationError("incremental-value pass requirements drifted")
    source_hashes = document["source_hashes"]
    if set(source_hashes) != set(SOURCE_FILES):
        raise MediapipeAblationError("MediaPipe ablation source hash set is incomplete")
    for relative in SOURCE_FILES:
        source = Path(root) / relative
        if not source.is_file() or _file_sha256(source) != source_hashes[relative]:
            raise MediapipeAblationError(f"governing source hash drift: {relative}")


def load_policy(path: Path = DEFAULT_POLICY_PATH, *, root: Path = ROOT) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise MediapipeAblationError("MediaPipe ablation policy is not an object")
    validate_policy(document, root=root)
    return document


def _validate_vote(vote: Mapping[str, Any], field: str, *, nullable: bool = False) -> None:
    side = vote.get("side")
    if side not in SIDES and not (nullable and side is None):
        raise MediapipeAblationError(f"{field}.side is invalid")
    evidence = vote.get("evidence_sha256")
    if side is None:
        if evidence is not None:
            raise MediapipeAblationError(f"{field} null vote carries evidence")
    elif not _is_sha256(evidence):
        raise MediapipeAblationError(f"{field}.evidence_sha256 is invalid")


def _validate_landmarks(value: Any, field: str) -> tuple[tuple[float, float, float], ...]:
    if not isinstance(value, list) or len(value) != 21:
        raise MediapipeAblationError(f"{field} must contain exactly 21 landmarks")
    points: list[tuple[float, float, float]] = []
    for row in value:
        if (
            not isinstance(row, list)
            or len(row) != 3
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in row)
        ):
            raise MediapipeAblationError(f"{field} must be finite 21x3 coordinates")
        point = tuple(float(item) for item in row)
        if not all(math.isfinite(item) for item in point) or not (
            0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0
        ):
            raise MediapipeAblationError(f"{field} contains invalid normalized coordinates")
        points.append(point)
    return tuple(points)


def _validate_case(case: Mapping[str, Any]) -> None:
    side = case["truth_side"]
    label = case["truth_label"]
    if side not in SIDES or label not in HAND_SWAP_PARTNERS or not label.startswith(f"{side}_"):
        raise MediapipeAblationError("truth label and character-side disagree")
    for field in ("case_id", "image_id", "package_id"):
        if not isinstance(case[field], str) or not case[field]:
            raise MediapipeAblationError(f"{field} is missing")
    for field in ("source_image_sha256", "truth_mask_sha256"):
        if not _is_sha256(case[field]):
            raise MediapipeAblationError(f"{field} is invalid")
    _validate_vote(case["pose_skeleton"], "pose_skeleton")
    _validate_vote(case["densepose_surface"], "densepose_surface", nullable=True)
    mediapipe = case["mediapipe_handedness"]
    _validate_vote(mediapipe, "mediapipe_handedness")
    score = mediapipe["score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
        raise MediapipeAblationError("mediapipe_handedness.score is invalid")
    _validate_landmarks(mediapipe["landmarks"], "mediapipe_handedness.landmarks")
    kind = case["kind"]
    pair_id = case["mirror_pair_id"]
    if kind == "human_anchor" and pair_id is not None:
        raise MediapipeAblationError("human-anchor performance cases cannot be mirror fixtures")
    if kind == "side_swap_fixture" and (not isinstance(pair_id, str) or not pair_id):
        raise MediapipeAblationError("side-swap fixture lacks mirror_pair_id")


def _validate_mirror_pair(first: Mapping[str, Any], second: Mapping[str, Any]) -> None:
    if first["truth_label"] != HAND_SWAP_PARTNERS[second["truth_label"]]:
        raise MediapipeAblationError("side-swap truth labels are not reciprocal")
    if first["truth_side"] != _opposite(second["truth_side"]):
        raise MediapipeAblationError("side-swap truth sides are not reciprocal")
    for field in ("pose_skeleton", "densepose_surface", "mediapipe_handedness"):
        if first[field]["side"] != _opposite(second[field]["side"]):
            raise MediapipeAblationError(f"side-swap {field} vote was not swapped")
        if first[field]["side"] is not None and (
            first[field]["evidence_sha256"] == second[field]["evidence_sha256"]
        ):
            raise MediapipeAblationError(f"side-swap {field} reused unswapped evidence")
    for field in ("source_image_sha256", "truth_mask_sha256"):
        if first[field] == second[field]:
            raise MediapipeAblationError(f"side-swap pair reused {field}")
    first_mp = first["mediapipe_handedness"]
    second_mp = second["mediapipe_handedness"]
    if float(first_mp["score"]) != float(second_mp["score"]):
        raise MediapipeAblationError("side-swap MediaPipe score changed")
    first_points = _validate_landmarks(first_mp["landmarks"], "first landmarks")
    second_points = _validate_landmarks(second_mp["landmarks"], "second landmarks")
    for original, mirrored in zip(first_points, second_points, strict=True):
        expected = (1.0 - original[0], original[1], original[2])
        if any(abs(left - right) > 1e-9 for left, right in zip(expected, mirrored, strict=True)):
            raise MediapipeAblationError("side-swap landmark geometry is not an exact x mirror")


def _majority(votes: Sequence[str | None], minimum_matching_votes: int) -> str | None:
    counts = Counter(vote for vote in votes if vote in SIDES)
    winners = [side for side, count in counts.items() if count >= minimum_matching_votes]
    return winners[0] if len(winners) == 1 else None


def _outcome(decision: str | None, truth: str) -> str:
    if decision is None:
        return "abstain"
    return "correct" if decision == truth else "wrong_side"


def _metrics(outcomes: Sequence[str]) -> dict[str, Any]:
    counts = Counter(outcomes)
    total = len(outcomes)
    decided = counts["correct"] + counts["wrong_side"]
    return {
        "total": total,
        "correct": counts["correct"],
        "wrong_side": counts["wrong_side"],
        "abstain": counts["abstain"],
        "decided": decided,
        "coverage": decided / total,
        "accuracy_when_decided": counts["correct"] / decided if decided else 0.0,
        "wrong_side_rate": counts["wrong_side"] / total,
    }


def build_report(
    cases_document: Mapping[str, Any],
    *,
    truth_manifest_path: Path,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Build a deterministic report; fixture cases never enter performance denominators."""
    policy_document = dict(policy) if policy is not None else load_policy(root=root)
    validate_policy(policy_document, root=root)
    try:
        require_valid_document(cases_document, "mediapipe_vote_ablation_cases")
    except ArtifactValidationError as exc:
        raise MediapipeAblationError(str(exc)) from exc
    payload = {key: value for key, value in cases_document.items() if key != "sha256"}
    if cases_document["sha256"] != _canonical_sha256(payload):
        raise MediapipeAblationError("MediaPipe ablation case manifest hash mismatch")
    if cases_document["policy_sha256"] != policy_document["sha256"]:
        raise MediapipeAblationError("MediaPipe ablation case policy hash mismatch")
    if cases_document["truth_tier"] != policy_document["eligible_truth"]["tier"] or (
        cases_document["truth_partition"] != policy_document["eligible_truth"]["partition"]
    ):
        raise MediapipeAblationError("only human-anchor holdout truth is eligible")
    opened = _timestamp(cases_document["results_opened_at"], "results_opened_at")
    if opened <= _timestamp(policy_document["frozen_at"], "frozen_at"):
        raise MediapipeAblationError("MediaPipe ablation results predate frozen policy")
    truth_manifest_path = Path(truth_manifest_path)
    if (
        not truth_manifest_path.is_file()
        or _file_sha256(truth_manifest_path) != cases_document["truth_manifest_sha256"]
    ):
        raise MediapipeAblationError("human-anchor truth manifest hash mismatch")
    if (
        cases_document["hand_landmarker_artifact_sha256"]
        != policy_document["hand_landmarker_artifact_sha256"]
    ):
        raise MediapipeAblationError("MediaPipe HandLandmarker artifact hash mismatch")

    cases = cases_document["cases"]
    case_ids: set[str] = set()
    human_keys: set[tuple[str, str]] = set()
    human_cases: list[Mapping[str, Any]] = []
    mirror_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for case in cases:
        _validate_case(case)
        if case["case_id"] in case_ids:
            raise MediapipeAblationError("duplicate ablation case_id")
        case_ids.add(case["case_id"])
        if case["kind"] == "human_anchor":
            hand_key = (case["image_id"], case["truth_label"])
            if hand_key in human_keys:
                raise MediapipeAblationError("duplicate human-anchor image/hand case")
            human_keys.add(hand_key)
            human_cases.append(case)
        else:
            mirror_groups[str(case["mirror_pair_id"])].append(case)
    if not human_cases:
        raise MediapipeAblationError("human-anchor hand set is empty")
    if not mirror_groups:
        raise MediapipeAblationError("side-swap fixture is missing")
    for pair_id, pair in mirror_groups.items():
        if len(pair) != 2:
            raise MediapipeAblationError(f"side-swap pair {pair_id} must contain exactly two cases")
        _validate_mirror_pair(pair[0], pair[1])

    threshold = float(policy_document["mediapipe_minimum_score"])
    required_votes = int(policy_document["decision_rule"]["minimum_matching_votes"])
    rows: list[dict[str, Any]] = []
    baseline_outcomes: list[str] = []
    full_outcomes: list[str] = []
    for case in human_cases:
        baseline = _majority(
            [case["pose_skeleton"]["side"], case["densepose_surface"]["side"]],
            required_votes,
        )
        mediapipe = case["mediapipe_handedness"]
        mediapipe_vote = mediapipe["side"] if float(mediapipe["score"]) >= threshold else None
        full = _majority(
            [
                case["pose_skeleton"]["side"],
                case["densepose_surface"]["side"],
                mediapipe_vote,
            ],
            required_votes,
        )
        baseline_outcome = _outcome(baseline, case["truth_side"])
        full_outcome = _outcome(full, case["truth_side"])
        baseline_outcomes.append(baseline_outcome)
        full_outcomes.append(full_outcome)
        rows.append(
            {
                "case_id": case["case_id"],
                "truth_side": case["truth_side"],
                "baseline_decision": baseline,
                "full_decision": full,
                "baseline_outcome": baseline_outcome,
                "full_outcome": full_outcome,
                "mediapipe_used": mediapipe_vote is not None,
            }
        )
    baseline_metrics = _metrics(baseline_outcomes)
    full_metrics = _metrics(full_outcomes)
    delta = {
        "correct": full_metrics["correct"] - baseline_metrics["correct"],
        "wrong_side": full_metrics["wrong_side"] - baseline_metrics["wrong_side"],
        "abstain": full_metrics["abstain"] - baseline_metrics["abstain"],
        "coverage": full_metrics["coverage"] - baseline_metrics["coverage"],
    }
    findings: list[str] = []
    requirements = policy_document["pass_requirements"]
    if delta["correct"] < requirements["minimum_incremental_correct_decisions"]:
        findings.append("no_incremental_correct_decision")
    if delta["wrong_side"] > requirements["maximum_incremental_wrong_side_decisions"]:
        findings.append("incremental_wrong_side_regression")
    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "benchmark_id": cases_document["benchmark_id"],
        "evaluated_at": cases_document["results_opened_at"],
        "policy_sha256": policy_document["sha256"],
        "source_cases_sha256": cases_document["sha256"],
        "truth_manifest_sha256": cases_document["truth_manifest_sha256"],
        "pipeline_fingerprint_sha256": cases_document["pipeline_fingerprint_sha256"],
        "hand_landmarker_artifact_sha256": cases_document["hand_landmarker_artifact_sha256"],
        "human_anchor_case_count": len(human_cases),
        "distinct_image_count": len({case["image_id"] for case in human_cases}),
        "side_swap_pair_count": len(mirror_groups),
        "baseline_metrics": baseline_metrics,
        "with_mediapipe_metrics": full_metrics,
        "delta": delta,
        "case_results": rows,
        "findings": findings,
        "result": "pass" if not findings else "fail",
    }
    report["sha256"] = _canonical_sha256(report)
    require_valid_document(report, "mediapipe_vote_ablation_report")
    return report


def verify_report(
    report: Mapping[str, Any],
    cases_document: Mapping[str, Any],
    *,
    truth_manifest_path: Path,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
    require_pass: bool = True,
) -> None:
    """Recompute the complete report and optionally require measured incremental value."""
    try:
        require_valid_document(report, "mediapipe_vote_ablation_report")
    except ArtifactValidationError as exc:
        raise MediapipeAblationError(str(exc)) from exc
    expected = build_report(
        cases_document,
        truth_manifest_path=truth_manifest_path,
        policy=policy,
        root=root,
    )
    if dict(report) != expected:
        raise MediapipeAblationError("MediaPipe ablation report recomputation mismatch")
    if require_pass and report["result"] != "pass":
        raise MediapipeAblationError(
            "MediaPipe ablation did not show safe incremental value: "
            + ", ".join(report["findings"])
        )


__all__ = [
    "DEFAULT_POLICY_PATH",
    "HAND_SWAP_PARTNERS",
    "MediapipeAblationError",
    "POLICY_SHA256",
    "build_report",
    "load_policy",
    "validate_policy",
    "verify_report",
]
