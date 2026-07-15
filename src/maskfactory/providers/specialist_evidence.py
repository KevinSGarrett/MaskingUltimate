"""Complete, hash-bound specialist benchmark evidence packages."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..training.leaderboard import load_leaderboard
from ..validation import ArtifactValidationError, require_valid_document
from .benchmark_policy import (
    ROOT,
    SPECIALIST_ROLES,
    SpecialistBenchmarkPolicyError,
    validate_specialist_benchmark_results,
    validate_specialist_margin_manifest,
)

ROLE_EVIDENCE_KINDS = {
    "chest_pelvic_segmentation": "specialist_role_benchmark",
    "clothing_accessory_segmentation": "specialist_role_benchmark",
    "foot_toe_segmentation": "specialist_role_benchmark",
    "geometry_provider": "geometry_variant_benchmark",
    "hair_matting": "silhouette_variant_benchmark",
    "hand_finger_segmentation": "mediapipe_vote_ablation_report",
    "pose_provider": "pose_variant_benchmark",
    "repeated_instance_segmentation": "specialist_role_benchmark",
    "silhouette_provider": "silhouette_variant_benchmark",
}
REQUIRED_ARTIFACT_KINDS = frozenset({"correction_diff", "disagreement_heatmap", "overlay_montage"})


class SpecialistEvidenceError(ValueError):
    """A specialist package is incomplete, stale, inconsistent, or tampered."""


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


def _safe_artifact_path(root: Path, relative: str) -> Path:
    candidate = (Path(root) / relative).resolve()
    resolved_root = Path(root).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise SpecialistEvidenceError(f"specialist artifact path escapes root: {relative}") from exc
    if not candidate.is_file():
        raise SpecialistEvidenceError(f"specialist artifact is missing: {relative}")
    return candidate


def _require_finite(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecialistEvidenceError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise SpecialistEvidenceError(f"{field} must be a finite number >= {minimum}")
    return number


def _validate_derived_metrics(role: str, lane: Mapping[str, Any]) -> None:
    disagreement = lane["disagreement"]
    compared = int(disagreement["compared_pixels"])
    disagree = int(disagreement["disagree_pixels"])
    if compared <= 0 or disagree < 0 or disagree > compared:
        raise SpecialistEvidenceError(f"{role} disagreement denominator/count is invalid")
    expected_fraction = disagree / compared
    if not math.isclose(
        _require_finite(disagreement["fraction"], f"{role}.disagreement.fraction"),
        expected_fraction,
        rel_tol=0,
        abs_tol=1e-12,
    ):
        raise SpecialistEvidenceError(f"{role} disagreement fraction mismatch")

    correction = lane["correction_pixels"]
    predicted = int(correction["predicted_pixels"])
    changed = int(correction["changed_pixels"])
    if predicted <= 0 or changed < 0:
        raise SpecialistEvidenceError(f"{role} correction-pixel denominator/count is invalid")
    expected_changed = changed * 100_000 / predicted
    if not math.isclose(
        _require_finite(
            correction["changed_pixels_per_100k"],
            f"{role}.correction_pixels.changed_pixels_per_100k",
        ),
        expected_changed,
        rel_tol=0,
        abs_tol=1e-9,
    ):
        raise SpecialistEvidenceError(f"{role} changed-pixels-per-100k mismatch")

    review = lane["review_time"]
    case_count = int(review["case_count"])
    baseline = _require_finite(
        review["baseline_seconds"], f"{role}.review_time.baseline_seconds", minimum=0
    )
    challenger = _require_finite(
        review["challenger_seconds"],
        f"{role}.review_time.challenger_seconds",
        minimum=0,
    )
    if case_count <= 0:
        raise SpecialistEvidenceError(f"{role} review-time denominator is invalid")
    expected_delta = (challenger - baseline) / case_count
    if not math.isclose(
        _require_finite(
            review["delta_seconds_per_case"],
            f"{role}.review_time.delta_seconds_per_case",
        ),
        expected_delta,
        rel_tol=0,
        abs_tol=1e-12,
    ):
        raise SpecialistEvidenceError(f"{role} review-time delta mismatch")


def validate_package(
    document: Mapping[str, Any],
    *,
    benchmark_results: Mapping[str, Mapping[str, Any]],
    margin_manifest: Mapping[str, Any],
    artifact_root: Path = ROOT,
    policy_root: Path = ROOT,
) -> None:
    """Require all nine enabled lanes, exact artifacts, metrics, results, and leaderboard rows."""
    try:
        require_valid_document(document, "specialist_evidence_package")
    except ArtifactValidationError as exc:
        raise SpecialistEvidenceError(str(exc)) from exc
    claimed = document["sha256"]
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if claimed != _canonical_sha256(payload):
        raise SpecialistEvidenceError("specialist evidence package hash mismatch")
    try:
        validate_specialist_margin_manifest(margin_manifest, root=policy_root)
    except SpecialistBenchmarkPolicyError as exc:
        raise SpecialistEvidenceError(str(exc)) from exc
    if document["specialist_margin_manifest_sha256"] != margin_manifest["sha256"]:
        raise SpecialistEvidenceError("specialist evidence package margin hash mismatch")
    expected_roles = sorted(SPECIALIST_ROLES)
    if document["enabled_lanes"] != expected_roles or set(document["lanes"]) != set(expected_roles):
        raise SpecialistEvidenceError("specialist evidence package lane coverage is incomplete")
    if set(benchmark_results) != set(expected_roles):
        raise SpecialistEvidenceError("specialist benchmark result set is incomplete")

    leaderboard_path = _safe_artifact_path(artifact_root, document["leaderboard"]["path"])
    if _file_sha256(leaderboard_path) != document["leaderboard"]["sha256"]:
        raise SpecialistEvidenceError("specialist leaderboard file hash mismatch")
    leaderboard_rows = load_leaderboard(leaderboard_path)
    run_ids = [row["run_id"] for row in leaderboard_rows]
    if len(run_ids) != len(set(run_ids)):
        raise SpecialistEvidenceError("specialist leaderboard run IDs are ambiguous")
    indexed_runs = {row["run_id"]: row for row in leaderboard_rows}

    seen_artifacts: set[str] = set()
    for role in expected_roles:
        lane = document["lanes"][role]
        role_evidence = lane["role_evidence"]
        if lane["role"] != role or role_evidence["kind"] != ROLE_EVIDENCE_KINDS[role]:
            raise SpecialistEvidenceError(f"{role} specialist evidence kind is invalid")
        if lane["evaluation_set_sha256"] != document["evaluation_set_sha256"]:
            raise SpecialistEvidenceError(f"{role} evaluation-set hash mismatch")
        if lane["pipeline_fingerprint_sha256"] != document["pipeline_fingerprint_sha256"]:
            raise SpecialistEvidenceError(f"{role} pipeline fingerprint mismatch")
        if len(lane["provider_keys"]) != len(set(lane["provider_keys"])):
            raise SpecialistEvidenceError(f"{role} provider keys are duplicated")
        result = benchmark_results[role]
        try:
            validate_specialist_benchmark_results(
                result,
                margin_manifest=margin_manifest,
                root=policy_root,
            )
        except SpecialistBenchmarkPolicyError as exc:
            raise SpecialistEvidenceError(str(exc)) from exc
        if result["role"] != role or lane["benchmark_result_sha256"] != result["sha256"]:
            raise SpecialistEvidenceError(f"{role} benchmark result hash mismatch")
        if lane["sample_count"] <= 0 or lane["distinct_image_count"] <= 0:
            raise SpecialistEvidenceError(f"{role} sample/image denominator is invalid")
        if lane["distinct_image_count"] > lane["sample_count"]:
            raise SpecialistEvidenceError(f"{role} distinct images exceed samples")
        role_evidence_path = role_evidence["path"]
        if role_evidence_path in seen_artifacts:
            raise SpecialistEvidenceError("specialist artifact path is reused across lanes")
        seen_artifacts.add(role_evidence_path)
        evidence_path = _safe_artifact_path(artifact_root, role_evidence_path)
        if _file_sha256(evidence_path) != role_evidence["sha256"]:
            raise SpecialistEvidenceError(f"{role} role evidence hash mismatch")
        artifact_kinds = {artifact["kind"] for artifact in lane["artifacts"]}
        if artifact_kinds != REQUIRED_ARTIFACT_KINDS:
            raise SpecialistEvidenceError(f"{role} specialist artifacts are incomplete")
        for artifact in lane["artifacts"]:
            relative = artifact["path"]
            if relative in seen_artifacts:
                raise SpecialistEvidenceError("specialist artifact path is reused across lanes")
            seen_artifacts.add(relative)
            path = _safe_artifact_path(artifact_root, relative)
            if _file_sha256(path) != artifact["sha256"]:
                raise SpecialistEvidenceError(f"{role} specialist artifact hash mismatch")
        _validate_derived_metrics(role, lane)

        baseline_id = lane["leaderboard"]["baseline_run_id"]
        challenger_id = lane["leaderboard"]["challenger_run_id"]
        if (
            baseline_id == challenger_id
            or baseline_id not in indexed_runs
            or challenger_id not in (indexed_runs)
        ):
            raise SpecialistEvidenceError(f"{role} leaderboard run reference is missing")
        baseline_row = indexed_runs[baseline_id]
        challenger_row = indexed_runs[challenger_id]
        if (baseline_row["dataset_ref"], baseline_row["split"]) != (
            challenger_row["dataset_ref"],
            challenger_row["split"],
        ):
            raise SpecialistEvidenceError(f"{role} leaderboard rows use different evaluations")
        expected_dataset_ref = "sha256:" + document["evaluation_set_sha256"]
        if baseline_row["dataset_ref"] != expected_dataset_ref or (
            challenger_row["dataset_ref"] != expected_dataset_ref
        ):
            raise SpecialistEvidenceError(f"{role} leaderboard evaluation hash mismatch")


def seal_package(
    draft: Mapping[str, Any],
    *,
    benchmark_results: Mapping[str, Mapping[str, Any]],
    margin_manifest: Mapping[str, Any],
    artifact_root: Path = ROOT,
    policy_root: Path = ROOT,
) -> dict[str, Any]:
    """Seal a complete draft only after every external artifact verifies."""
    document = dict(draft)
    if "sha256" in document:
        raise SpecialistEvidenceError("specialist evidence draft is already sealed")
    document["sha256"] = _canonical_sha256(document)
    validate_package(
        document,
        benchmark_results=benchmark_results,
        margin_manifest=margin_manifest,
        artifact_root=artifact_root,
        policy_root=policy_root,
    )
    return document


__all__ = [
    "REQUIRED_ARTIFACT_KINDS",
    "ROLE_EVIDENCE_KINDS",
    "SpecialistEvidenceError",
    "seal_package",
    "validate_package",
]
