"""Hash-bound autonomy workload, quality, and confidence reporting."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from functools import lru_cache
from statistics import NormalDist
from typing import Any, Mapping

from ..validation import validate_document

TRUTH_TIER_FIELDS = (
    "human_anchor_gold_packages",
    "autonomous_certified_gold_packages",
    "machine_candidate_packages",
    "weighted_pseudo_label_packages",
)


class AutonomyMetricsError(ValueError):
    """Autonomy reporting is missing evidence or conflates metric meanings."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _timestamp(value: str, field: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise AutonomyMetricsError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise AutonomyMetricsError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _wilson_upper(defects: int, total: int, confidence: float) -> float:
    z = NormalDist().inv_cdf(confidence)
    rate = defects / total
    denominator = 1 + z * z / total
    center = rate + z * z / (2 * total)
    radius = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
    return min(1.0, (center + radius) / denominator)


def _binomial_cdf(defects: int, total: int, probability: float) -> float:
    return sum(
        math.comb(total, value) * probability**value * (1.0 - probability) ** (total - value)
        for value in range(defects + 1)
    )


@lru_cache(maxsize=256)
def _exact_binomial_upper(defects: int, total: int, confidence: float) -> float:
    """One-sided Clopper-Pearson upper bound without a SciPy dependency."""
    if defects == total:
        return 1.0
    target = 1.0 - confidence
    low, high = defects / total, 1.0
    for _ in range(100):
        midpoint = (low + high) / 2.0
        if _binomial_cdf(defects, total, midpoint) > target:
            low = midpoint
        else:
            high = midpoint
    return high


def _validate_input_counts(inputs: Mapping[str, Any]) -> dict[str, int]:
    count_fields = (
        "zero_touch_packages",
        "eligible_packages",
        "routine_human_touched_packages",
        "residual_review_packages",
        "human_touch_count",
        "manually_changed_pixels",
        "predicted_pixels",
        "blinded_evaluated_packages",
        "audited_packages",
        "false_accepts",
        "serious_false_accepts",
    )
    counts: dict[str, int] = {}
    for field in count_fields:
        value = inputs[field]
        if isinstance(value, bool) or not isinstance(value, int):
            raise AutonomyMetricsError("autonomy metric counts must be integers")
        counts[field] = value
    if (
        counts["eligible_packages"] < 1
        or counts["predicted_pixels"] < 1
        or counts["blinded_evaluated_packages"] < 1
        or counts["audited_packages"] < 1
        or not 0 <= counts["zero_touch_packages"] <= counts["eligible_packages"]
        or not 0 <= counts["routine_human_touched_packages"] <= counts["eligible_packages"]
        or counts["zero_touch_packages"] + counts["routine_human_touched_packages"]
        != counts["eligible_packages"]
        or not 0 <= counts["residual_review_packages"] <= counts["routine_human_touched_packages"]
        or not 0 <= counts["audited_packages"] <= counts["eligible_packages"]
        or not 0 < counts["blinded_evaluated_packages"] <= counts["eligible_packages"]
        or counts["human_touch_count"] < counts["routine_human_touched_packages"]
        or not 0 <= counts["manually_changed_pixels"] <= counts["predicted_pixels"]
        or not 0
        <= counts["serious_false_accepts"]
        <= counts["false_accepts"]
        <= counts["audited_packages"]
    ):
        raise AutonomyMetricsError("autonomy metric counts or denominators are invalid")
    return counts


def _normalize_truth_tiers(value: Mapping[str, Any], eligible: int) -> dict[str, int]:
    if set(value) != set(TRUTH_TIER_FIELDS):
        raise AutonomyMetricsError("truth-tier breakdown is incomplete")
    result: dict[str, int] = {}
    for field in TRUTH_TIER_FIELDS:
        count = value[field]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise AutonomyMetricsError("truth-tier counts must be nonnegative integers")
        result[field] = count
    if sum(result.values()) != eligible:
        raise AutonomyMetricsError("truth-tier counts do not reconcile to the eligible cohort")
    return result


def _input_payload(
    *,
    cohort_id: str,
    observed_at: str,
    input_manifest_sha256: str,
    pipeline_fingerprint_sha256: str,
    truth_tier_counts: Mapping[str, int],
    zero_touch_packages: int,
    eligible_packages: int,
    routine_human_touched_packages: int,
    residual_review_packages: int,
    human_touch_count: int,
    manually_changed_pixels: int,
    predicted_pixels: int,
    blinded_evaluated_packages: int,
    mask_iou_sum: float,
    boundary_f1_sum: float,
    audited_packages: int,
    false_accepts: int,
    serious_false_accepts: int,
    confidence_level: float,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "cohort_id": cohort_id,
        "observed_at": observed_at,
        "input_manifest_sha256": input_manifest_sha256,
        "pipeline_fingerprint_sha256": pipeline_fingerprint_sha256,
        "truth_tier_counts": dict(truth_tier_counts),
        "zero_touch_packages": zero_touch_packages,
        "eligible_packages": eligible_packages,
        "routine_human_touched_packages": routine_human_touched_packages,
        "residual_review_packages": residual_review_packages,
        "human_touch_count": human_touch_count,
        "manually_changed_pixels": manually_changed_pixels,
        "predicted_pixels": predicted_pixels,
        "blinded_evaluated_packages": blinded_evaluated_packages,
        "mask_iou_sum": mask_iou_sum,
        "boundary_f1_sum": boundary_f1_sum,
        "audited_packages": audited_packages,
        "false_accepts": false_accepts,
        "serious_false_accepts": serious_false_accepts,
        "confidence_level": confidence_level,
    }


def build_autonomy_metrics_report(
    *,
    cohort_id: str,
    observed_at: str,
    input_manifest_sha256: str,
    pipeline_fingerprint_sha256: str,
    truth_tier_counts: Mapping[str, int],
    zero_touch_packages: int,
    eligible_packages: int,
    routine_human_touched_packages: int,
    residual_review_packages: int,
    human_touch_count: int,
    manually_changed_pixels: int,
    predicted_pixels: int,
    blinded_evaluated_packages: int,
    mask_iou_sum: float,
    boundary_f1_sum: float,
    audited_packages: int,
    false_accepts: int,
    serious_false_accepts: int,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Build four separate, denominator-explicit evidence domains for one cohort."""
    if not isinstance(cohort_id, str) or not cohort_id.strip():
        raise AutonomyMetricsError("cohort_id is required")
    normalized_time = _timestamp(observed_at, "observed_at")
    if not _is_sha256(input_manifest_sha256) or not _is_sha256(pipeline_fingerprint_sha256):
        raise AutonomyMetricsError("cohort manifest and pipeline fingerprints must be SHA-256")
    raw_inputs = _input_payload(
        cohort_id=cohort_id,
        observed_at=normalized_time,
        input_manifest_sha256=input_manifest_sha256,
        pipeline_fingerprint_sha256=pipeline_fingerprint_sha256,
        truth_tier_counts=truth_tier_counts,
        zero_touch_packages=zero_touch_packages,
        eligible_packages=eligible_packages,
        routine_human_touched_packages=routine_human_touched_packages,
        residual_review_packages=residual_review_packages,
        human_touch_count=human_touch_count,
        manually_changed_pixels=manually_changed_pixels,
        predicted_pixels=predicted_pixels,
        blinded_evaluated_packages=blinded_evaluated_packages,
        mask_iou_sum=mask_iou_sum,
        boundary_f1_sum=boundary_f1_sum,
        audited_packages=audited_packages,
        false_accepts=false_accepts,
        serious_false_accepts=serious_false_accepts,
        confidence_level=confidence_level,
    )
    input_issues = validate_document(raw_inputs, "autonomy_metrics_inputs")
    if input_issues:
        raise AutonomyMetricsError(
            "invalid autonomy metrics inputs: "
            + "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in input_issues)
        )
    counts = _validate_input_counts(raw_inputs)
    tiers = _normalize_truth_tiers(truth_tier_counts, counts["eligible_packages"])
    if confidence_level != 0.95:
        raise AutonomyMetricsError("autonomy dashboard requires the predeclared 95% bound")
    iou_sum = float(mask_iou_sum)
    boundary_sum = float(boundary_f1_sum)
    evaluated = counts["blinded_evaluated_packages"]
    if (
        not math.isfinite(iou_sum)
        or not math.isfinite(boundary_sum)
        or not 0 <= iou_sum <= evaluated
        or not 0 <= boundary_sum <= evaluated
    ):
        raise AutonomyMetricsError("blinded quality sums exceed their evaluated denominator")

    report: dict[str, Any] = {
        "schema_version": "3.0.0",
        "source_input_sha256": _canonical_sha256(raw_inputs),
        "cohort": {
            "cohort_id": cohort_id,
            "observed_at": normalized_time,
            "input_manifest_sha256": input_manifest_sha256,
            "pipeline_fingerprint_sha256": pipeline_fingerprint_sha256,
            "eligible_packages": counts["eligible_packages"],
        },
        "throughput": {
            "label": "Zero-touch throughput",
            "zero_touch_packages": counts["zero_touch_packages"],
            "eligible_packages": counts["eligible_packages"],
            "zero_touch_fraction": counts["zero_touch_packages"] / counts["eligible_packages"],
        },
        "truth_tier_breakdown": {
            "label": "Final truth-tier package counts",
            "eligible_packages": counts["eligible_packages"],
            **tiers,
        },
        "human_workload": {
            "label": "Human intervention workload",
            "eligible_packages": counts["eligible_packages"],
            "routine_human_touched_packages": counts["routine_human_touched_packages"],
            "routine_human_touch_fraction": counts["routine_human_touched_packages"]
            / counts["eligible_packages"],
            "audited_packages": counts["audited_packages"],
            "audited_fraction": counts["audited_packages"] / counts["eligible_packages"],
            "residual_review_packages": counts["residual_review_packages"],
            "residual_review_fraction": counts["residual_review_packages"]
            / counts["eligible_packages"],
            "human_touch_count": counts["human_touch_count"],
            "human_touches_per_100_images": counts["human_touch_count"]
            / counts["eligible_packages"]
            * 100,
            "manually_changed_pixels": counts["manually_changed_pixels"],
            "predicted_pixels": counts["predicted_pixels"],
            "manual_changed_pixels_per_100k": counts["manually_changed_pixels"]
            / counts["predicted_pixels"]
            * 100_000,
        },
        "blinded_quality": {
            "label": "Blinded quality against human-anchor holdout",
            "truth_tier": "human_anchor_gold",
            "truth_partition": "holdout",
            "blinded": True,
            "evaluated_packages": evaluated,
            "mask_iou_sum": iou_sum,
            "mean_mask_iou": iou_sum / evaluated,
            "boundary_f1_sum": boundary_sum,
            "mean_boundary_f1": boundary_sum / evaluated,
        },
        "statistical_confidence": {
            "label": "95% one-sided failure-rate upper bounds",
            "confidence_level": confidence_level,
            "audited_packages": counts["audited_packages"],
            "false_accepts": counts["false_accepts"],
            "serious_false_accepts": counts["serious_false_accepts"],
            "audit_false_accept_rate": counts["false_accepts"] / counts["audited_packages"],
            "serious_false_accept_rate": counts["serious_false_accepts"]
            / counts["audited_packages"],
            "false_accept_upper_bound": _wilson_upper(
                counts["false_accepts"], counts["audited_packages"], confidence_level
            ),
            "serious_false_accept_upper_bound": _exact_binomial_upper(
                counts["serious_false_accepts"],
                counts["audited_packages"],
                confidence_level,
            ),
        },
    }
    report["sha256"] = _canonical_sha256(report)
    validate_autonomy_metrics_report(report)
    return report


def build_autonomy_metrics_report_from_inputs(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Build from the exact schema-bound one-command input document."""
    issues = validate_document(dict(inputs), "autonomy_metrics_inputs")
    if issues:
        raise AutonomyMetricsError(
            "invalid autonomy metrics inputs: "
            + "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
        )
    kwargs = {key: value for key, value in inputs.items() if key != "schema_version"}
    return build_autonomy_metrics_report(**kwargs)


def _inputs_from_report(report: Mapping[str, Any]) -> dict[str, Any]:
    cohort = report["cohort"]
    throughput = report["throughput"]
    tiers = report["truth_tier_breakdown"]
    workload = report["human_workload"]
    quality = report["blinded_quality"]
    confidence = report["statistical_confidence"]
    return _input_payload(
        cohort_id=cohort["cohort_id"],
        observed_at=cohort["observed_at"],
        input_manifest_sha256=cohort["input_manifest_sha256"],
        pipeline_fingerprint_sha256=cohort["pipeline_fingerprint_sha256"],
        truth_tier_counts={field: tiers[field] for field in TRUTH_TIER_FIELDS},
        zero_touch_packages=throughput["zero_touch_packages"],
        eligible_packages=throughput["eligible_packages"],
        routine_human_touched_packages=workload["routine_human_touched_packages"],
        residual_review_packages=workload["residual_review_packages"],
        human_touch_count=workload["human_touch_count"],
        manually_changed_pixels=workload["manually_changed_pixels"],
        predicted_pixels=workload["predicted_pixels"],
        blinded_evaluated_packages=quality["evaluated_packages"],
        mask_iou_sum=quality["mask_iou_sum"],
        boundary_f1_sum=quality["boundary_f1_sum"],
        audited_packages=confidence["audited_packages"],
        false_accepts=confidence["false_accepts"],
        serious_false_accepts=confidence["serious_false_accepts"],
        confidence_level=confidence["confidence_level"],
    )


def validate_autonomy_metrics_report(report: Mapping[str, Any]) -> None:
    issues = validate_document(dict(report), "autonomy_metrics")
    if issues:
        raise AutonomyMetricsError(
            "invalid autonomy metrics report: "
            + "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
        )
    claimed = report["sha256"]
    payload = {key: value for key, value in report.items() if key != "sha256"}
    if claimed != _canonical_sha256(payload):
        raise AutonomyMetricsError("autonomy metrics report hash mismatch")
    inputs = _inputs_from_report(report)
    if report["source_input_sha256"] != _canonical_sha256(inputs):
        raise AutonomyMetricsError("autonomy metrics source-input hash mismatch")
    counts = _validate_input_counts(inputs)
    tiers = _normalize_truth_tiers(inputs["truth_tier_counts"], counts["eligible_packages"])
    cohort = report["cohort"]
    throughput = report["throughput"]
    workload = report["human_workload"]
    quality = report["blinded_quality"]
    confidence = report["statistical_confidence"]
    if not (
        cohort["eligible_packages"]
        == throughput["eligible_packages"]
        == workload["eligible_packages"]
        == report["truth_tier_breakdown"]["eligible_packages"]
    ):
        raise AutonomyMetricsError("cohort population denominators differ")
    if (
        throughput["zero_touch_packages"] + workload["routine_human_touched_packages"]
        != counts["eligible_packages"]
    ):
        raise AutonomyMetricsError("throughput and workload populations differ")
    if workload["audited_packages"] != confidence["audited_packages"]:
        raise AutonomyMetricsError("workload and confidence audit denominators differ")
    if workload["residual_review_packages"] > workload["routine_human_touched_packages"]:
        raise AutonomyMetricsError("residual review is not a subset of routine human touch")
    derived_checks = {
        "zero_touch_fraction": (
            throughput["zero_touch_fraction"],
            throughput["zero_touch_packages"] / throughput["eligible_packages"],
        ),
        "routine_human_touch_fraction": (
            workload["routine_human_touch_fraction"],
            workload["routine_human_touched_packages"] / workload["eligible_packages"],
        ),
        "audited_fraction": (
            workload["audited_fraction"],
            workload["audited_packages"] / workload["eligible_packages"],
        ),
        "residual_review_fraction": (
            workload["residual_review_fraction"],
            workload["residual_review_packages"] / workload["eligible_packages"],
        ),
        "human_touches_per_100_images": (
            workload["human_touches_per_100_images"],
            workload["human_touch_count"] / workload["eligible_packages"] * 100,
        ),
        "manual_changed_pixels_per_100k": (
            workload["manual_changed_pixels_per_100k"],
            workload["manually_changed_pixels"] / workload["predicted_pixels"] * 100_000,
        ),
        "mean_mask_iou": (
            quality["mean_mask_iou"],
            quality["mask_iou_sum"] / quality["evaluated_packages"],
        ),
        "mean_boundary_f1": (
            quality["mean_boundary_f1"],
            quality["boundary_f1_sum"] / quality["evaluated_packages"],
        ),
        "audit_false_accept_rate": (
            confidence["audit_false_accept_rate"],
            confidence["false_accepts"] / confidence["audited_packages"],
        ),
        "serious_false_accept_rate": (
            confidence["serious_false_accept_rate"],
            confidence["serious_false_accepts"] / confidence["audited_packages"],
        ),
        "false_accept_upper_bound": (
            confidence["false_accept_upper_bound"],
            _wilson_upper(
                confidence["false_accepts"],
                confidence["audited_packages"],
                confidence["confidence_level"],
            ),
        ),
        "serious_false_accept_upper_bound": (
            confidence["serious_false_accept_upper_bound"],
            _exact_binomial_upper(
                confidence["serious_false_accepts"],
                confidence["audited_packages"],
                confidence["confidence_level"],
            ),
        ),
    }
    for field, (actual, expected) in derived_checks.items():
        if not math.isclose(actual, expected, abs_tol=1e-12):
            raise AutonomyMetricsError(f"{field} does not match its declared denominator")
    if {field: report["truth_tier_breakdown"][field] for field in TRUTH_TIER_FIELDS} != tiers:
        raise AutonomyMetricsError("truth-tier breakdown drifted")


def render_autonomy_metrics_dashboard(report: Mapping[str, Any]) -> str:
    """Render labels whose wording cannot present throughput as quality/confidence."""
    validate_autonomy_metrics_report(report)
    cohort = report["cohort"]
    throughput = report["throughput"]
    tiers = report["truth_tier_breakdown"]
    workload = report["human_workload"]
    quality = report["blinded_quality"]
    confidence = report["statistical_confidence"]
    return "\n".join(
        (
            "# Autonomous Mask Metrics",
            "",
            f"- Cohort: {cohort['cohort_id']}",
            f"- Observed at: {cohort['observed_at']}",
            f"- Input manifest SHA-256: {cohort['input_manifest_sha256']}",
            f"- Pipeline fingerprint SHA-256: {cohort['pipeline_fingerprint_sha256']}",
            "",
            "## Throughput",
            f"- Zero-touch throughput: {throughput['zero_touch_fraction']:.3%} "
            f"({throughput['zero_touch_packages']}/{throughput['eligible_packages']})",
            "",
            "## Final truth-tier package counts",
            f"- Human-anchor gold: {tiers['human_anchor_gold_packages']}",
            f"- Autonomous-certified gold: {tiers['autonomous_certified_gold_packages']}",
            f"- Machine candidates: {tiers['machine_candidate_packages']}",
            f"- Weighted pseudo-labels: {tiers['weighted_pseudo_label_packages']}",
            f"- Eligible cohort denominator: {tiers['eligible_packages']}",
            "",
            "## Human intervention workload",
            f"- Human touches per 100 images: {workload['human_touches_per_100_images']:.3f} "
            f"({workload['human_touch_count']}/{workload['eligible_packages']})",
            f"- Audited fraction: {workload['audited_fraction']:.3%} "
            f"({workload['audited_packages']}/{workload['eligible_packages']})",
            f"- Residual-review fraction: {workload['residual_review_fraction']:.3%} "
            f"({workload['residual_review_packages']}/{workload['eligible_packages']})",
            f"- Routine human-touch fraction: {workload['routine_human_touch_fraction']:.3%} "
            f"({workload['routine_human_touched_packages']}/{workload['eligible_packages']})",
            "- Manually changed pixels per 100,000 predicted pixels: "
            f"{workload['manual_changed_pixels_per_100k']:.3f} "
            f"({workload['manually_changed_pixels']}/{workload['predicted_pixels']})",
            "",
            "## Blinded quality",
            f"- Mean mask IoU: {quality['mean_mask_iou']:.6f} "
            f"(sum={quality['mask_iou_sum']:.6f}, n={quality['evaluated_packages']})",
            f"- Mean boundary F1: {quality['mean_boundary_f1']:.6f} "
            f"(sum={quality['boundary_f1_sum']:.6f}, n={quality['evaluated_packages']})",
            "",
            "## Statistical confidence",
            f"- 95% false-accept upper bound: {confidence['false_accept_upper_bound']:.6f}",
            "- 95% serious-failure upper bound: "
            f"{confidence['serious_false_accept_upper_bound']:.6f}",
            f"- Observed audit false-accept rate: {confidence['audit_false_accept_rate']:.6f} "
            f"({confidence['false_accepts']}/{confidence['audited_packages']})",
            "- Observed serious false-accept rate: "
            f"{confidence['serious_false_accept_rate']:.6f} "
            f"({confidence['serious_false_accepts']}/{confidence['audited_packages']})",
            "",
            "Zero-touch throughput is not an accuracy, quality, or confidence claim.",
        )
    )


__all__ = [
    "AutonomyMetricsError",
    "build_autonomy_metrics_report",
    "build_autonomy_metrics_report_from_inputs",
    "render_autonomy_metrics_dashboard",
    "validate_autonomy_metrics_report",
]
