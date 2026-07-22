"""Frozen SAM 3D Body versus DensePose human-anchor benchmark contract."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..validation import ArtifactValidationError, require_valid_document

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY_PATH = (
    ROOT / "qa" / "governance" / "benchmark_matrices" / "geometry_variant_benchmark_v1.json"
)
POLICY_SHA256 = "914b6304f7e7598f62f6272ef4d5e7a0e049e76952912400e8d9af69f68d3944"
PROVIDERS = ("densepose_r50_fpn_s1x", "sam3d_body")
CONTEXTS = (
    "geometry_prior",
    "contact",
    "crowding",
    "identity_ambiguity",
    "occlusion",
    "rear_view",
    "front_view",
    "scale_disparity",
    "truncation",
)
COUNT_PAIRS = (
    ("evaluated_projection_count", "consistent_projection_count"),
    ("visible_surface_truth_count", "visible_surface_hit_count"),
    ("predicted_surface_count", "background_bleed_count"),
    ("predicted_surface_count", "cross_person_bleed_count"),
    ("side_eligible_count", "left_right_error_count"),
    ("front_back_eligible_count", "front_back_error_count"),
    ("identity_eligible_count", "identity_assignment_error_count"),
    ("hard_qa_eligible_count", "hard_qa_failure_count"),
)
RATE_FIELDS = {
    "projection_consistency": ("consistent_projection_count", "evaluated_projection_count"),
    "visible_surface_recall": ("visible_surface_hit_count", "visible_surface_truth_count"),
    "background_bleed_rate": ("background_bleed_count", "predicted_surface_count"),
    "cross_person_bleed_rate": ("cross_person_bleed_count", "predicted_surface_count"),
    "left_right_error_rate": ("left_right_error_count", "side_eligible_count"),
    "front_back_error_rate": ("front_back_error_count", "front_back_eligible_count"),
    "identity_assignment_error_rate": (
        "identity_assignment_error_count",
        "identity_eligible_count",
    ),
    "hard_qa_failure_rate": ("hard_qa_failure_count", "hard_qa_eligible_count"),
}
SOURCE_FILES = (
    "env/source_builds.lock",
    "qa/governance/benchmark_matrices/specialist_margins_v1.json",
    "qa/live_verification/sam3d_body_source_gate_20260715.json",
    "src/maskfactory/lanes/prior3d.py",
    "src/maskfactory/providers/contracts.py",
)


class GeometryBenchmarkError(ValueError):
    """The frozen geometry policy, observations, or report are invalid."""


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
        raise GeometryBenchmarkError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise GeometryBenchmarkError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def _count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GeometryBenchmarkError(f"{field} must be a nonnegative integer")
    return value


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GeometryBenchmarkError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise GeometryBenchmarkError(f"{field} must be finite and nonnegative")
    return result


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def validate_policy(
    document: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_sha256: str | None = POLICY_SHA256,
) -> None:
    try:
        require_valid_document(document, "geometry_variant_benchmark_policy")
    except ArtifactValidationError as exc:
        raise GeometryBenchmarkError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != _canonical_sha256(payload):
        raise GeometryBenchmarkError("geometry benchmark policy hash mismatch")
    if expected_sha256 is not None and document["sha256"] != expected_sha256:
        raise GeometryBenchmarkError("geometry benchmark policy differs from locked hash")
    if tuple(document["required_contexts"]) != CONTEXTS:
        raise GeometryBenchmarkError("geometry benchmark context vocabulary drifted")
    if set(document["providers"]) != set(PROVIDERS):
        raise GeometryBenchmarkError("geometry benchmark provider set drifted")
    if set(document["source_hashes"]) != set(SOURCE_FILES):
        raise GeometryBenchmarkError("geometry benchmark source hash set is incomplete")
    for relative in SOURCE_FILES:
        source = Path(root) / relative
        if not source.is_file() or _file_sha256(source) != document["source_hashes"][relative]:
            raise GeometryBenchmarkError(f"governing source hash drift: {relative}")
    margin_path = Path(root) / "qa/governance/benchmark_matrices/specialist_margins_v1.json"
    margins = json.loads(margin_path.read_text(encoding="utf-8"))["roles"]["geometry_provider"]
    requirements = document["pass_requirements"]
    if (
        requirements["minimum_overall_projection_consistency_improvement"]
        != margins["primary_objective"]["minimum_improvement"]
        or requirements["max_context_projection_consistency_drop"]
        != margins["context_margins"]["image_projection_consistency"]
        or requirements["max_context_visible_surface_recall_drop"]
        != margins["context_margins"]["visible_surface_recall"]
        or document["zero_regression_metrics"]
        != [
            "background_bleed_rate",
            "cross_person_bleed_rate",
            "front_back_error_rate",
            "hard_qa_failure_rate",
            "identity_assignment_error_rate",
            "left_right_error_rate",
        ]
    ):
        raise GeometryBenchmarkError("geometry benchmark specialist margins drifted")
    densepose = document["providers"]["densepose_r50_fpn_s1x"]
    sam3d = document["providers"]["sam3d_body"]
    if densepose["frozen_artifact_hashes"] != {
        "checkpoint": "b8a7382001b16e453bad95ca9dbc68ae8f2b839b304cf90eaf5c27fbdb4dae91"
    }:
        raise GeometryBenchmarkError("DensePose frozen artifact drifted")
    if sam3d["frozen_artifact_hashes"] or sam3d["authority"] != (
        "planned_source_only_until_governed_installation"
    ):
        raise GeometryBenchmarkError("SAM 3D Body source-only gate was overclaimed")


def load_policy(path: Path = DEFAULT_POLICY_PATH, *, root: Path = ROOT) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise GeometryBenchmarkError("geometry benchmark policy is not an object")
    validate_policy(document, root=root)
    return document


def _validate_runtime(provider: str, runtime: Mapping[str, Any]) -> None:
    for field in ("cold_latency_ms", "warm_latency_ms", "peak_vram_bytes"):
        _finite(runtime[field], f"{provider}.{field}")
    for field in ("oom_count", "crash_count", "repeat_count"):
        _count(runtime[field], f"{provider}.{field}")
    hashes = runtime["deterministic_output_sha256"]
    if len(hashes) != runtime["repeat_count"] or len(set(hashes)) != 1:
        raise GeometryBenchmarkError(f"{provider} deterministic repeat evidence failed")


def _validate_provider(
    provider: str, evidence: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    spec = policy["providers"][provider]
    if evidence["source_revision"] != spec["source_revision"]:
        raise GeometryBenchmarkError(f"{provider} source revision mismatch")
    if evidence["checkpoint_revision"] != spec["checkpoint_revision"]:
        raise GeometryBenchmarkError(f"{provider} checkpoint revision mismatch")
    hashes = evidence["artifact_hashes"]
    if set(hashes) != set(spec["required_artifact_keys"]):
        raise GeometryBenchmarkError(f"{provider} artifact set is incomplete")
    if any(hashes.get(key) != value for key, value in spec["frozen_artifact_hashes"].items()):
        raise GeometryBenchmarkError(f"{provider} frozen artifact identity mismatch")
    observations: dict[str, Mapping[str, Any]] = {}
    for row in evidence["observations"]:
        context = row["context"]
        if context not in CONTEXTS or context in observations:
            raise GeometryBenchmarkError(f"{provider} context coverage is invalid")
        for denominator, numerator in COUNT_PAIRS:
            denominator_value = _count(row[denominator], f"{provider}.{denominator}")
            numerator_value = _count(row[numerator], f"{provider}.{numerator}")
            if numerator_value > denominator_value:
                raise GeometryBenchmarkError(
                    f"{provider}.{numerator} exceeds its explicit denominator"
                )
        observations[context] = row
    if set(observations) != set(CONTEXTS):
        raise GeometryBenchmarkError(f"{provider} does not cover every geometry context")
    _validate_runtime(provider, evidence["runtime_metrics"])
    return observations


def _aggregate(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    totals = {
        field: sum(int(row[field]) for row in rows)
        for field in {name for pair in COUNT_PAIRS for name in pair}
    }
    return {
        **totals,
        **{
            rate: _rate(totals[numerator], totals[denominator])
            for rate, (numerator, denominator) in RATE_FIELDS.items()
        },
    }


def build_report(
    cases_document: Mapping[str, Any],
    *,
    truth_manifest_path: Path,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    policy_document = dict(policy) if policy is not None else load_policy(root=root)
    validate_policy(policy_document, root=root)
    try:
        require_valid_document(cases_document, "geometry_variant_benchmark_cases")
    except ArtifactValidationError as exc:
        raise GeometryBenchmarkError(str(exc)) from exc
    payload = {key: value for key, value in cases_document.items() if key != "sha256"}
    if cases_document["sha256"] != _canonical_sha256(payload):
        raise GeometryBenchmarkError("geometry benchmark cases hash mismatch")
    if cases_document["policy_sha256"] != policy_document["sha256"]:
        raise GeometryBenchmarkError("geometry benchmark cases policy hash mismatch")
    if (cases_document["truth_tier"], cases_document["truth_partition"]) != (
        "human_anchor_gold",
        "holdout",
    ):
        raise GeometryBenchmarkError("only human-anchor holdout truth is eligible")
    if _timestamp(cases_document["results_opened_at"], "results_opened_at") <= _timestamp(
        policy_document["frozen_at"], "frozen_at"
    ):
        raise GeometryBenchmarkError("geometry benchmark results predate frozen policy")
    truth = Path(truth_manifest_path)
    if not truth.is_file() or _file_sha256(truth) != cases_document["truth_manifest_sha256"]:
        raise GeometryBenchmarkError("human-anchor truth manifest hash mismatch")
    if set(cases_document["providers"]) != set(PROVIDERS):
        raise GeometryBenchmarkError("geometry evidence provider set is incomplete")

    provider_rows: dict[str, dict[str, Any]] = {}
    context_rows: dict[str, dict[str, Mapping[str, Any]]] = {}
    for provider in PROVIDERS:
        evidence = cases_document["providers"][provider]
        observations = _validate_provider(provider, evidence, policy_document)
        context_rows[provider] = observations
        provider_rows[provider] = {
            "provider": provider,
            "source_revision": evidence["source_revision"],
            "checkpoint_revision": evidence["checkpoint_revision"],
            "artifact_hashes": evidence["artifact_hashes"],
            "runtime_fingerprint": evidence["runtime_fingerprint"],
            "context_metrics": [
                {"context": context, **_aggregate([observations[context]])} for context in CONTEXTS
            ],
            "overall_metrics": _aggregate(list(observations.values())),
            "runtime_metrics": evidence["runtime_metrics"],
        }

    baseline = provider_rows["densepose_r50_fpn_s1x"]
    challenger = provider_rows["sam3d_body"]
    requirements = policy_document["pass_requirements"]
    findings: list[str] = []
    overall_delta = (
        challenger["overall_metrics"]["projection_consistency"]
        - baseline["overall_metrics"]["projection_consistency"]
    )
    if overall_delta < requirements["minimum_overall_projection_consistency_improvement"]:
        findings.append("projection_consistency_primary_win_failed")
    context_deltas = []
    for context in CONTEXTS:
        baseline_metric = _aggregate([context_rows["densepose_r50_fpn_s1x"][context]])
        challenger_metric = _aggregate([context_rows["sam3d_body"][context]])
        projection_delta = (
            challenger_metric["projection_consistency"] - baseline_metric["projection_consistency"]
        )
        recall_delta = (
            challenger_metric["visible_surface_recall"] - baseline_metric["visible_surface_recall"]
        )
        rate_deltas = {
            metric: challenger_metric[metric] - baseline_metric[metric]
            for metric in policy_document["zero_regression_metrics"]
        }
        if projection_delta < -requirements["max_context_projection_consistency_drop"]:
            findings.append(f"{context}:projection_consistency_noninferiority_failed")
        if recall_delta < -requirements["max_context_visible_surface_recall_drop"]:
            findings.append(f"{context}:visible_surface_recall_noninferiority_failed")
        for metric, delta in rate_deltas.items():
            if delta > requirements["max_zero_regression_rate_delta"]:
                findings.append(f"{context}:{metric}_regression")
        context_deltas.append(
            {
                "context": context,
                "projection_consistency_delta": projection_delta,
                "visible_surface_recall_delta": recall_delta,
                "zero_regression_rate_deltas": rate_deltas,
            }
        )
    runtime = challenger["runtime_metrics"]
    if runtime["peak_vram_bytes"] > requirements["max_peak_vram_bytes"]:
        findings.append("peak_vram_limit_failed")
    if runtime["oom_count"] + runtime["crash_count"] > requirements["max_oom_or_crash_count"]:
        findings.append("runtime_failure")
    if runtime["repeat_count"] != requirements["require_deterministic_repeats"]:
        findings.append("determinism_repeat_count_failed")
    fallback = cases_document["fallback_drill"]
    if (
        fallback["challenger"] != "sam3d_body"
        or fallback["expected_provider"] != requirements["require_fallback_to"]
        or fallback["observed_provider"] != requirements["require_fallback_to"]
        or fallback["active_provider_after"] != "densepose_r50_fpn_s1x"
        or fallback["rollback_provider_after"] != "densepose_r50_fpn_s1x"
    ):
        findings.append("fallback_drill_failed")

    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "benchmark_id": cases_document["benchmark_id"],
        "evaluated_at": cases_document["results_opened_at"],
        "policy_sha256": policy_document["sha256"],
        "source_cases_sha256": cases_document["sha256"],
        "truth_manifest_sha256": cases_document["truth_manifest_sha256"],
        "pipeline_fingerprint_sha256": cases_document["pipeline_fingerprint_sha256"],
        "hardware_fingerprint_sha256": cases_document["hardware_fingerprint_sha256"],
        "providers": [provider_rows[name] for name in PROVIDERS],
        "comparison": {
            "challenger": "sam3d_body",
            "baseline": "densepose_r50_fpn_s1x",
            "overall_projection_consistency_delta": overall_delta,
            "context_deltas": context_deltas,
        },
        "fallback_drill": fallback,
        "findings": findings,
        "result": "pass" if not findings else "fail",
        "authority": ("benchmark_evidence_only_no_installation_promotion_mask_or_gold_authority"),
    }
    report["sha256"] = _canonical_sha256(report)
    require_valid_document(report, "geometry_variant_benchmark_report")
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
    try:
        require_valid_document(report, "geometry_variant_benchmark_report")
    except ArtifactValidationError as exc:
        raise GeometryBenchmarkError(str(exc)) from exc
    expected = build_report(
        cases_document,
        truth_manifest_path=truth_manifest_path,
        policy=policy,
        root=root,
    )
    if dict(report) != expected:
        raise GeometryBenchmarkError("geometry benchmark report recomputation mismatch")
    if require_pass and report["result"] != "pass":
        raise GeometryBenchmarkError("geometry benchmark gates failed")


__all__ = [
    "CONTEXTS",
    "DEFAULT_POLICY_PATH",
    "GeometryBenchmarkError",
    "POLICY_SHA256",
    "PROVIDERS",
    "build_report",
    "load_policy",
    "validate_policy",
    "verify_report",
]
