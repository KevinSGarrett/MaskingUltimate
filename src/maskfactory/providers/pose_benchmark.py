"""Frozen RTMW-X/RTMO versus DWPose human-anchor benchmark contract."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..validation import ArtifactValidationError, require_valid_document
from .rtm_pose import COCO_WHOLEBODY_NAMES, CROWDPOSE_NAMES

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY_PATH = (
    ROOT / "qa" / "governance" / "benchmark_matrices" / "pose_variant_benchmark_v1.json"
)
POLICY_SHA256 = "3791ffe1f527a465d06d271aaca585fdf16253584667797a49b07adab10c8517"
CONTEXTS = (
    "whole_body",
    "hands",
    "feet",
    "rear",
    "contact",
    "occlusion",
    "crowded_scene",
)
PROVIDER_JOINTS = {
    "dwpose_133": COCO_WHOLEBODY_NAMES,
    "rtmw_x": COCO_WHOLEBODY_NAMES,
    "rtmo_crowd": CROWDPOSE_NAMES,
}
SOURCE_FILES = (
    "env/rtm_pose.lock.json",
    "models/model_registry.json",
    "qa/governance/benchmark_matrices/specialist_margins_v1.json",
    "src/maskfactory/providers/rtm_pose.py",
    "src/maskfactory/stages/s04_pose.py",
)


class PoseBenchmarkError(ValueError):
    """The frozen pose policy, observations, or report are invalid."""


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


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PoseBenchmarkError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise PoseBenchmarkError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _finite_number(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PoseBenchmarkError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise PoseBenchmarkError(f"{field} is not a finite value >= {minimum}")
    return result


def _count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PoseBenchmarkError(f"{field} must be a nonnegative integer")
    return value


def validate_policy(
    document: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_sha256: str | None = POLICY_SHA256,
) -> None:
    """Validate the pre-result policy, locked hash, and governing source bytes."""
    try:
        require_valid_document(document, "pose_variant_benchmark_policy")
    except ArtifactValidationError as exc:
        raise PoseBenchmarkError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != _canonical_sha256(payload):
        raise PoseBenchmarkError("pose benchmark policy hash mismatch")
    if expected_sha256 is not None and document["sha256"] != expected_sha256:
        raise PoseBenchmarkError("pose benchmark policy differs from locked hash")
    _timestamp(document["frozen_at"], "frozen_at")
    if document["eligible_truth"] != {
        "partition": "holdout",
        "tier": "human_anchor_gold",
    }:
        raise PoseBenchmarkError("only human-anchor holdout truth is eligible")
    if tuple(document["required_contexts"]) != CONTEXTS:
        raise PoseBenchmarkError("pose benchmark context vocabulary drifted")
    if document["normalization"] != {
        "distance": "euclidean_pixels_over_truth_person_bbox_diagonal",
        "pck_thresholds": [0.05, 0.1],
        "side_semantics": "character_anatomical_left_right",
    }:
        raise PoseBenchmarkError("pose benchmark normalization drifted")
    provider_specs = document["providers"]
    if set(provider_specs) != set(PROVIDER_JOINTS):
        raise PoseBenchmarkError("pose provider set drifted")
    for provider, joints in PROVIDER_JOINTS.items():
        if provider_specs[provider]["joint_vocabulary"] != list(joints):
            raise PoseBenchmarkError(f"{provider} joint vocabulary drifted")
    if document["comparison_roles"] != {
        "rtmo_crowd": ["crowded_scene"],
        "rtmw_x": list(CONTEXTS),
    }:
        raise PoseBenchmarkError("pose comparison roles drifted")
    if document["comparison_joint_rule"] != "exact_name_intersection_only":
        raise PoseBenchmarkError("pose comparison joint rule drifted")
    expected_requirements = {
        "max_cross_person_rate_delta": 0.0,
        "max_oom_or_crash_count": 0,
        "max_pck_010_drop": 0.02,
        "max_wrong_side_rate_delta": 0.0,
        "require_deterministic_repeats": 2,
        "require_fallback_to": "dwpose_133",
    }
    if document["pass_requirements"] != expected_requirements:
        raise PoseBenchmarkError("pose benchmark pass requirements drifted")
    if set(document["source_hashes"]) != set(SOURCE_FILES):
        raise PoseBenchmarkError("pose benchmark source hash set is incomplete")
    for relative in SOURCE_FILES:
        source = Path(root) / relative
        if not source.is_file() or _file_sha256(source) != document["source_hashes"][relative]:
            raise PoseBenchmarkError(f"governing source hash drift: {relative}")


def load_policy(path: Path = DEFAULT_POLICY_PATH, *, root: Path = ROOT) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise PoseBenchmarkError("pose benchmark policy is not an object")
    validate_policy(document, root=root)
    return document


def _metric_row(row: Mapping[str, Any], provider: str) -> tuple[str, str]:
    context, joint = row["context"], row["joint"]
    if context not in CONTEXTS or joint not in PROVIDER_JOINTS[provider]:
        raise PoseBenchmarkError(f"{provider} observation vocabulary is invalid")
    visible = _count(row["visible_count"], "visible_count")
    pck_005 = _count(row["correct_pck_005_count"], "correct_pck_005_count")
    pck_010 = _count(row["correct_pck_010_count"], "correct_pck_010_count")
    error_sum = _finite_number(row["normalized_error_sum"], "normalized_error_sum")
    if pck_005 > pck_010 or pck_010 > visible:
        raise PoseBenchmarkError("pose PCK counts violate nested denominators")
    if visible == 0 and error_sum != 0:
        raise PoseBenchmarkError("zero-visible pose row has nonzero error sum")
    return context, joint


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    visible = sum(int(row["visible_count"]) for row in rows)
    correct_005 = sum(int(row["correct_pck_005_count"]) for row in rows)
    correct_010 = sum(int(row["correct_pck_010_count"]) for row in rows)
    error_sum = sum(float(row["normalized_error_sum"]) for row in rows)
    return {
        "visible_count": visible,
        "correct_pck_005_count": correct_005,
        "correct_pck_010_count": correct_010,
        "normalized_error_sum": error_sum,
        "pck_005": _rate(correct_005, visible),
        "pck_010": _rate(correct_010, visible),
        "mean_normalized_error": _rate(error_sum, visible),
    }


def _validate_count_metrics(
    rows: Sequence[Mapping[str, Any]], field: str
) -> dict[str, Mapping[str, Any]]:
    mapped: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        context = row["context"]
        if context not in CONTEXTS or context in mapped:
            raise PoseBenchmarkError(f"{field} context coverage is invalid")
        eligible = _count(row["eligible_count"], f"{field}.eligible_count")
        correct = _count(row["correct_count"], f"{field}.correct_count")
        error = _count(row["error_count"], f"{field}.error_count")
        if correct + error != eligible:
            raise PoseBenchmarkError(f"{field} counts do not reconcile")
        mapped[context] = row
    if set(mapped) != set(CONTEXTS):
        raise PoseBenchmarkError(f"{field} does not cover every context")
    return mapped


def _validate_provider(
    provider: str,
    evidence: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> tuple[dict[tuple[str, str], Mapping[str, Any]], dict[str, Any], dict[str, Any]]:
    spec = policy["providers"][provider]
    if evidence["artifact_hashes"] != spec["artifact_hashes"]:
        raise PoseBenchmarkError(f"{provider} artifact identity mismatch")
    if evidence["runtime_fingerprint"] != spec["runtime_fingerprint"]:
        raise PoseBenchmarkError(f"{provider} runtime identity mismatch")
    observations: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in evidence["observations"]:
        key = _metric_row(row, provider)
        if key in observations:
            raise PoseBenchmarkError(f"duplicate {provider} context/joint observation")
        observations[key] = row
    expected = {(context, joint) for context in CONTEXTS for joint in PROVIDER_JOINTS[provider]}
    if set(observations) != expected:
        raise PoseBenchmarkError(f"{provider} context/joint coverage is incomplete")
    side = _validate_count_metrics(evidence["side_metrics"], f"{provider}.side_metrics")
    identity = _validate_count_metrics(evidence["identity_metrics"], f"{provider}.identity_metrics")
    runtime = evidence["runtime_metrics"]
    for field in ("cold_latency_ms", "warm_latency_ms", "peak_vram_bytes"):
        _finite_number(runtime[field], f"{provider}.{field}")
    for field in ("oom_count", "crash_count", "repeat_count"):
        _count(runtime[field], f"{provider}.{field}")
    hashes = runtime["deterministic_output_sha256"]
    if len(hashes) != runtime["repeat_count"] or len(set(hashes)) != 1:
        raise PoseBenchmarkError(f"{provider} deterministic repeat evidence failed")
    return observations, side, identity


def _context_summary(
    context: str,
    observations: Mapping[tuple[str, str], Mapping[str, Any]],
    side: Mapping[str, Mapping[str, Any]],
    identity: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    pose = _aggregate([row for (name, _joint), row in observations.items() if name == context])
    side_row, identity_row = side[context], identity[context]
    return {
        "context": context,
        **pose,
        "side_eligible_count": side_row["eligible_count"],
        "side_correct_count": side_row["correct_count"],
        "wrong_side_count": side_row["error_count"],
        "wrong_side_rate": _rate(side_row["error_count"], side_row["eligible_count"]),
        "identity_eligible_count": identity_row["eligible_count"],
        "identity_correct_count": identity_row["correct_count"],
        "cross_person_count": identity_row["error_count"],
        "cross_person_rate": _rate(identity_row["error_count"], identity_row["eligible_count"]),
    }


def build_report(
    cases_document: Mapping[str, Any],
    *,
    truth_manifest_path: Path,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Recompute every joint/context/side/identity metric and comparison."""
    policy_document = dict(policy) if policy is not None else load_policy(root=root)
    validate_policy(policy_document, root=root)
    try:
        require_valid_document(cases_document, "pose_variant_benchmark_cases")
    except ArtifactValidationError as exc:
        raise PoseBenchmarkError(str(exc)) from exc
    payload = {key: value for key, value in cases_document.items() if key != "sha256"}
    if cases_document["sha256"] != _canonical_sha256(payload):
        raise PoseBenchmarkError("pose benchmark cases hash mismatch")
    if cases_document["policy_sha256"] != policy_document["sha256"]:
        raise PoseBenchmarkError("pose benchmark cases policy hash mismatch")
    if (cases_document["truth_tier"], cases_document["truth_partition"]) != (
        "human_anchor_gold",
        "holdout",
    ):
        raise PoseBenchmarkError("only human-anchor holdout truth is eligible")
    if _timestamp(cases_document["results_opened_at"], "results_opened_at") <= _timestamp(
        policy_document["frozen_at"], "frozen_at"
    ):
        raise PoseBenchmarkError("pose benchmark results predate frozen policy")
    truth_manifest_path = Path(truth_manifest_path)
    if (
        not truth_manifest_path.is_file()
        or _file_sha256(truth_manifest_path) != cases_document["truth_manifest_sha256"]
    ):
        raise PoseBenchmarkError("human-anchor truth manifest hash mismatch")
    if set(cases_document["providers"]) != set(PROVIDER_JOINTS):
        raise PoseBenchmarkError("pose benchmark evidence provider set is incomplete")

    provider_rows: dict[str, dict[str, Any]] = {}
    for provider in PROVIDER_JOINTS:
        evidence = cases_document["providers"][provider]
        observations, side, identity = _validate_provider(provider, evidence, policy_document)
        joint_metrics = []
        for joint in PROVIDER_JOINTS[provider]:
            aggregate = _aggregate([observations[(context, joint)] for context in CONTEXTS])
            joint_metrics.append({"joint": joint, **aggregate})
        provider_rows[provider] = {
            "provider": provider,
            "joint_vocabulary": list(PROVIDER_JOINTS[provider]),
            "joint_metrics": joint_metrics,
            "context_metrics": [
                _context_summary(context, observations, side, identity) for context in CONTEXTS
            ],
            "overall_metrics": _aggregate(list(observations.values())),
            "runtime_metrics": evidence["runtime_metrics"],
        }

    requirements = policy_document["pass_requirements"]
    baseline = provider_rows["dwpose_133"]
    comparisons: list[dict[str, Any]] = []
    findings: list[str] = []
    for challenger in ("rtmw_x", "rtmo_crowd"):
        contexts = policy_document["comparison_roles"][challenger]
        challenger_contexts = {
            row["context"]: row for row in provider_rows[challenger]["context_metrics"]
        }
        baseline_contexts = {row["context"]: row for row in baseline["context_metrics"]}
        joint_set = set(PROVIDER_JOINTS[challenger]).intersection(PROVIDER_JOINTS["dwpose_133"])
        challenger_visible = challenger_correct = baseline_visible = baseline_correct = 0
        for context in contexts:
            for joint in joint_set:
                challenger_joint = next(
                    row
                    for row in cases_document["providers"][challenger]["observations"]
                    if row["context"] == context and row["joint"] == joint
                )
                baseline_joint = next(
                    row
                    for row in cases_document["providers"]["dwpose_133"]["observations"]
                    if row["context"] == context and row["joint"] == joint
                )
                challenger_visible += challenger_joint["visible_count"]
                challenger_correct += challenger_joint["correct_pck_010_count"]
                baseline_visible += baseline_joint["visible_count"]
                baseline_correct += baseline_joint["correct_pck_010_count"]
        challenger_pck = _rate(challenger_correct, challenger_visible)
        baseline_pck = _rate(baseline_correct, baseline_visible)
        challenger_side_eligible = sum(
            challenger_contexts[c]["side_eligible_count"] for c in contexts
        )
        challenger_side_errors = sum(challenger_contexts[c]["wrong_side_count"] for c in contexts)
        baseline_side_eligible = sum(baseline_contexts[c]["side_eligible_count"] for c in contexts)
        baseline_side_errors = sum(baseline_contexts[c]["wrong_side_count"] for c in contexts)
        challenger_identity_eligible = sum(
            challenger_contexts[c]["identity_eligible_count"] for c in contexts
        )
        challenger_identity_errors = sum(
            challenger_contexts[c]["cross_person_count"] for c in contexts
        )
        baseline_identity_eligible = sum(
            baseline_contexts[c]["identity_eligible_count"] for c in contexts
        )
        baseline_identity_errors = sum(baseline_contexts[c]["cross_person_count"] for c in contexts)
        pck_delta = challenger_pck - baseline_pck
        side_delta = _rate(challenger_side_errors, challenger_side_eligible) - _rate(
            baseline_side_errors, baseline_side_eligible
        )
        identity_delta = _rate(challenger_identity_errors, challenger_identity_eligible) - _rate(
            baseline_identity_errors, baseline_identity_eligible
        )
        runtime = provider_rows[challenger]["runtime_metrics"]
        challenger_findings: list[str] = []
        if pck_delta < -float(requirements["max_pck_010_drop"]):
            challenger_findings.append("pck_010_noninferiority_failed")
        if side_delta > float(requirements["max_wrong_side_rate_delta"]):
            challenger_findings.append("wrong_side_regression")
        if identity_delta > float(requirements["max_cross_person_rate_delta"]):
            challenger_findings.append("cross_person_regression")
        if runtime["oom_count"] + runtime["crash_count"] > requirements["max_oom_or_crash_count"]:
            challenger_findings.append("runtime_failure")
        if runtime["repeat_count"] != requirements["require_deterministic_repeats"]:
            challenger_findings.append("determinism_repeat_count_failed")
        fallback = next(
            (row for row in cases_document["fallback_drills"] if row["challenger"] == challenger),
            None,
        )
        if fallback is None:
            challenger_findings.append("fallback_drill_missing")
        elif (
            fallback["expected_provider"] != requirements["require_fallback_to"]
            or fallback["observed_provider"] != requirements["require_fallback_to"]
            or fallback["active_provider_after"] != "dwpose_133"
            or fallback["rollback_provider_after"] != "dwpose_133"
            or not fallback["output_sha256"]
        ):
            challenger_findings.append("fallback_drill_failed")
        findings.extend(f"{challenger}:{finding}" for finding in challenger_findings)
        comparisons.append(
            {
                "challenger": challenger,
                "contexts": contexts,
                "joint_intersection_count": len(joint_set),
                "challenger_visible_count": challenger_visible,
                "baseline_visible_count": baseline_visible,
                "challenger_pck_010": challenger_pck,
                "baseline_pck_010": baseline_pck,
                "pck_010_delta": pck_delta,
                "wrong_side_rate_delta": side_delta,
                "cross_person_rate_delta": identity_delta,
                "findings": challenger_findings,
                "result": "pass" if not challenger_findings else "fail",
            }
        )
    if len(cases_document["fallback_drills"]) != 2 or {
        row["challenger"] for row in cases_document["fallback_drills"]
    } != {"rtmw_x", "rtmo_crowd"}:
        raise PoseBenchmarkError("fallback drill set must cover each challenger exactly once")

    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "benchmark_id": cases_document["benchmark_id"],
        "evaluated_at": cases_document["results_opened_at"],
        "policy_sha256": policy_document["sha256"],
        "source_cases_sha256": cases_document["sha256"],
        "truth_manifest_sha256": cases_document["truth_manifest_sha256"],
        "pipeline_fingerprint_sha256": cases_document["pipeline_fingerprint_sha256"],
        "hardware_fingerprint_sha256": cases_document["hardware_fingerprint_sha256"],
        "providers": [provider_rows[name] for name in PROVIDER_JOINTS],
        "comparisons": comparisons,
        "fallback_drills": cases_document["fallback_drills"],
        "findings": findings,
        "result": "pass" if not findings else "fail",
        "authority": "benchmark_evidence_only_no_gold_or_production_authority",
    }
    report["sha256"] = _canonical_sha256(report)
    require_valid_document(report, "pose_variant_benchmark_report")
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
    """Recompute the report byte-for-byte and optionally require all frozen gates."""
    try:
        require_valid_document(report, "pose_variant_benchmark_report")
    except ArtifactValidationError as exc:
        raise PoseBenchmarkError(str(exc)) from exc
    expected = build_report(
        cases_document,
        truth_manifest_path=truth_manifest_path,
        policy=policy,
        root=root,
    )
    if dict(report) != expected:
        raise PoseBenchmarkError("pose benchmark report recomputation mismatch")
    if require_pass and report["result"] != "pass":
        raise PoseBenchmarkError("pose benchmark gates failed: " + ", ".join(report["findings"]))


__all__ = [
    "CONTEXTS",
    "DEFAULT_POLICY_PATH",
    "POLICY_SHA256",
    "PROVIDER_JOINTS",
    "PoseBenchmarkError",
    "build_report",
    "load_policy",
    "validate_policy",
    "verify_report",
]
