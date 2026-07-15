"""Strictly separated autonomy throughput, quality, and confidence reporting."""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Mapping

from ..validation import validate_document


class AutonomyMetricsError(ValueError):
    """Autonomy reporting is missing evidence or conflates metric meanings."""


def _unit_interval(name: str, value: float) -> float:
    normalized = float(value)
    if not math.isfinite(normalized) or not 0 <= normalized <= 1:
        raise AutonomyMetricsError(f"{name} must be finite and in 0..1")
    return normalized


def _wilson_upper(defects: int, total: int, confidence: float) -> float:
    z = NormalDist().inv_cdf(confidence)
    rate = defects / total
    denominator = 1 + z * z / total
    center = rate + z * z / (2 * total)
    radius = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
    return min(1.0, (center + radius) / denominator)


def build_autonomy_metrics_report(
    *,
    zero_touch_packages: int,
    eligible_packages: int,
    routine_human_touched_packages: int,
    residual_review_packages: int,
    human_touch_count: int,
    manually_changed_pixels: int,
    predicted_pixels: int,
    blinded_evaluated_packages: int,
    mean_mask_iou: float,
    mean_boundary_f1: float,
    audited_packages: int,
    false_accepts: int,
    serious_false_accepts: int,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Build three evidence domains without allowing cross-domain inference."""
    counts = (
        zero_touch_packages,
        eligible_packages,
        routine_human_touched_packages,
        residual_review_packages,
        human_touch_count,
        manually_changed_pixels,
        predicted_pixels,
        blinded_evaluated_packages,
        audited_packages,
        false_accepts,
        serious_false_accepts,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in counts):
        raise AutonomyMetricsError("autonomy metric counts must be integers")
    if (
        eligible_packages < 1
        or predicted_pixels < 1
        or blinded_evaluated_packages < 1
        or audited_packages < 1
        or not 0 <= zero_touch_packages <= eligible_packages
        or not 0 <= routine_human_touched_packages <= eligible_packages
        or zero_touch_packages + routine_human_touched_packages != eligible_packages
        or not 0 <= residual_review_packages <= eligible_packages
        or not 0 <= audited_packages <= eligible_packages
        or human_touch_count < routine_human_touched_packages
        or not 0 <= manually_changed_pixels <= predicted_pixels
        or not 0 <= serious_false_accepts <= false_accepts <= audited_packages
    ):
        raise AutonomyMetricsError("autonomy metric counts or denominators are invalid")
    if confidence_level != 0.95:
        raise AutonomyMetricsError("autonomy dashboard requires the predeclared 95% bound")
    serious_upper = (
        1.0 - (1.0 - confidence_level) ** (1.0 / audited_packages)
        if serious_false_accepts == 0
        else 1.0
    )
    report: dict[str, Any] = {
        "schema_version": "2.0.0",
        "throughput": {
            "label": "Zero-touch throughput",
            "zero_touch_packages": zero_touch_packages,
            "eligible_packages": eligible_packages,
            "zero_touch_fraction": zero_touch_packages / eligible_packages,
        },
        "human_workload": {
            "label": "Human intervention workload",
            "eligible_packages": eligible_packages,
            "routine_human_touched_packages": routine_human_touched_packages,
            "routine_human_touch_fraction": routine_human_touched_packages / eligible_packages,
            "audited_packages": audited_packages,
            "audited_fraction": audited_packages / eligible_packages,
            "residual_review_packages": residual_review_packages,
            "residual_review_fraction": residual_review_packages / eligible_packages,
            "human_touch_count": human_touch_count,
            "human_touches_per_100_images": human_touch_count / eligible_packages * 100,
            "manually_changed_pixels": manually_changed_pixels,
            "predicted_pixels": predicted_pixels,
            "manual_changed_pixels_per_100k": manually_changed_pixels / predicted_pixels * 100_000,
        },
        "blinded_quality": {
            "label": "Blinded quality against human-anchor holdout",
            "truth_tier": "human_anchor_gold",
            "truth_partition": "holdout",
            "blinded": True,
            "evaluated_packages": blinded_evaluated_packages,
            "mean_mask_iou": _unit_interval("mean_mask_iou", mean_mask_iou),
            "mean_boundary_f1": _unit_interval("mean_boundary_f1", mean_boundary_f1),
        },
        "statistical_confidence": {
            "label": "95% one-sided failure-rate upper bounds",
            "confidence_level": confidence_level,
            "audited_packages": audited_packages,
            "false_accepts": false_accepts,
            "serious_false_accepts": serious_false_accepts,
            "audit_false_accept_rate": false_accepts / audited_packages,
            "serious_false_accept_rate": serious_false_accepts / audited_packages,
            "false_accept_upper_bound": _wilson_upper(
                false_accepts, audited_packages, confidence_level
            ),
            "serious_false_accept_upper_bound": serious_upper,
        },
    }
    validate_autonomy_metrics_report(report)
    return report


def validate_autonomy_metrics_report(report: Mapping[str, Any]) -> None:
    issues = validate_document(dict(report), "autonomy_metrics")
    if issues:
        raise AutonomyMetricsError(
            "invalid autonomy metrics report: "
            + "; ".join(f"{issue.pointer or '/'} {issue.message}" for issue in issues)
        )
    throughput = report["throughput"]
    expected = throughput["zero_touch_packages"] / throughput["eligible_packages"]
    if not math.isclose(throughput["zero_touch_fraction"], expected, abs_tol=1e-12):
        raise AutonomyMetricsError("zero_touch_fraction does not match its throughput denominator")
    workload = report["human_workload"]
    workload_checks = {
        "routine_human_touch_fraction": workload["routine_human_touched_packages"]
        / workload["eligible_packages"],
        "audited_fraction": workload["audited_packages"] / workload["eligible_packages"],
        "residual_review_fraction": workload["residual_review_packages"]
        / workload["eligible_packages"],
        "human_touches_per_100_images": workload["human_touch_count"]
        / workload["eligible_packages"]
        * 100,
        "manual_changed_pixels_per_100k": workload["manually_changed_pixels"]
        / workload["predicted_pixels"]
        * 100_000,
    }
    for field, expected_value in workload_checks.items():
        if not math.isclose(workload[field], expected_value, abs_tol=1e-12):
            raise AutonomyMetricsError(f"{field} does not match its declared denominator")
    if (
        throughput["eligible_packages"] != workload["eligible_packages"]
        or throughput["zero_touch_packages"] + workload["routine_human_touched_packages"]
        != workload["eligible_packages"]
    ):
        raise AutonomyMetricsError("throughput and workload populations differ")
    confidence = report["statistical_confidence"]
    for field, numerator in (
        ("audit_false_accept_rate", confidence["false_accepts"]),
        ("serious_false_accept_rate", confidence["serious_false_accepts"]),
    ):
        expected_rate = numerator / confidence["audited_packages"]
        if not math.isclose(confidence[field], expected_rate, abs_tol=1e-12):
            raise AutonomyMetricsError(f"{field} does not match its audit denominator")


def render_autonomy_metrics_dashboard(report: Mapping[str, Any]) -> str:
    """Render labels whose wording cannot present throughput as quality/confidence."""
    validate_autonomy_metrics_report(report)
    throughput = report["throughput"]
    workload = report["human_workload"]
    quality = report["blinded_quality"]
    confidence = report["statistical_confidence"]
    return "\n".join(
        (
            "# Autonomous Mask Metrics",
            "",
            "## Throughput",
            f"- Zero-touch throughput: {throughput['zero_touch_fraction']:.3%} "
            f"({throughput['zero_touch_packages']}/{throughput['eligible_packages']})",
            "",
            "## Human intervention workload",
            f"- Human touches per 100 images: {workload['human_touches_per_100_images']:.3f} ",
            f"- Audited fraction: {workload['audited_fraction']:.3%} ",
            f"- Residual-review fraction: {workload['residual_review_fraction']:.3%} ",
            f"- Routine human-touch fraction: {workload['routine_human_touch_fraction']:.3%} ",
            "- Manually changed pixels per 100,000 predicted pixels: "
            f"{workload['manual_changed_pixels_per_100k']:.3f}",
            "",
            "## Blinded quality",
            f"- Mean mask IoU: {quality['mean_mask_iou']:.6f}",
            f"- Mean boundary F1: {quality['mean_boundary_f1']:.6f}",
            f"- Human-anchor holdout packages: {quality['evaluated_packages']}",
            "",
            "## Statistical confidence",
            f"- 95% false-accept upper bound: " f"{confidence['false_accept_upper_bound']:.6f}",
            f"- 95% serious-failure upper bound: "
            f"{confidence['serious_false_accept_upper_bound']:.6f}",
            f"- Observed audit false-accept rate: {confidence['audit_false_accept_rate']:.6f}",
            f"- Observed serious false-accept rate: "
            f"{confidence['serious_false_accept_rate']:.6f}",
            f"- Audited packages: {confidence['audited_packages']}",
            "",
            "Zero-touch throughput is not an accuracy, quality, or confidence claim.",
        )
    )


__all__ = [
    "AutonomyMetricsError",
    "build_autonomy_metrics_report",
    "render_autonomy_metrics_dashboard",
    "validate_autonomy_metrics_report",
]
