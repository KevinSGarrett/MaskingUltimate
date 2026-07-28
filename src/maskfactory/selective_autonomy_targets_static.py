"""STATIC binders for MF-P9-15.01 quality targets and MF-P9-15.03 labor targets.

Freezes product-acceptance thresholds from configs/autonomous_masks.yaml and Plan
doc 23. Fixture- and config-bound only. Never claims blinded holdout measurement,
production labor measurement, doctor-green, gold, Main-complete, or
PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from .validation import validate_document

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "selective_autonomy_targets_static_report"
AUTHORITY = "selective_autonomy_targets_static_only_no_holdout_no_production_labor_measurement"
SCHEMA_VERSION = "1.0.0"
AUTONOMY_CONFIG_PATH = Path("configs/autonomous_masks.yaml")

# MF-P9-15.01 / Plan 23 §1 — quality acceptance floors (minimums).
EXPECTED_QUALITY_TARGETS = {
    "ordinary_part_mean_iou": 0.95,
    "ordinary_boundary_f1": 0.90,
    "hard_anatomy_mean_iou": 0.85,
}

# MF-P9-15.03 / Plan 23 §1 — labor targets (direction-aware).
EXPECTED_LABOR_TARGETS = {
    "zero_touch_fraction_minimum": 0.95,
    "routine_human_touch_fraction_maximum": 0.05,
    "manual_pixel_edit_fraction_maximum": 0.01,
}

# Aggregate results cannot hide a failing stratum (Plan 23 §1).
REQUIRED_ANTI_COLLAPSE_BUCKETS = (
    "label",
    "multi_person_stratum",
    "clothing_nudity_state",
    "pose",
    "occlusion",
    "hard_bucket",
)

HARD_ANATOMY_SCOPES = (
    "fingers",
    "toes",
    "hair",
    "anatomy_clothing_boundaries",
)

QUALITY_CONFIG_KEYS = {
    "ordinary_part_mean_iou": "target_ordinary_part_mean_iou",
    "ordinary_boundary_f1": "target_ordinary_boundary_f1",
    "hard_anatomy_mean_iou": "target_hard_anatomy_mean_iou",
}

LABOR_CONFIG_KEYS = {
    "zero_touch_fraction_minimum": "target_zero_touch_fraction",
    "routine_human_touch_fraction_maximum": "maximum_routine_human_touch_fraction",
    "manual_pixel_edit_fraction_maximum": "target_manual_pixel_edit_fraction",
}

FORBIDDEN_LABOR_PROXY_FIELDS = (
    "review_minutes_per_image",
    "operator_minutes",
    "cvat_click_count_as_zero_touch",
    "review_time_proxy_zero_touch",
    "review_time_proxy_manual_pixel_edit",
)

HONEST_NON_CLAIMS = (
    "mf_p9_15_01_complete",
    "mf_p9_15_03_complete",
    "blinded_human_anchor_holdout_measured",
    "production_labor_measured",
    "review_time_proxy_accepted",
    "doctor_green",
    "gold",
    "VISUAL_QA_PASS_BOUNDED",
    "Main-complete",
    "PRODUCTION_EVIDENCE_PASS",
)


class SelectiveAutonomyTargetsStaticError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _load_operational_targets(config_path: Path = AUTONOMY_CONFIG_PATH) -> dict[str, Any]:
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SelectiveAutonomyTargetsStaticError(f"autonomy_config_unreadable:{exc}") from exc
    if not isinstance(document, Mapping):
        raise SelectiveAutonomyTargetsStaticError("autonomy_config_not_mapping")
    targets = document.get("operational_targets")
    if not isinstance(targets, Mapping):
        raise SelectiveAutonomyTargetsStaticError("operational_targets_missing")
    return dict(targets)


def bind_quality_targets_from_config(
    config_path: Path = AUTONOMY_CONFIG_PATH,
) -> dict[str, float]:
    """Prove config floors match frozen MF-P9-15.01 product targets."""

    targets = _load_operational_targets(config_path)
    bound: dict[str, float] = {}
    for logical, config_key in QUALITY_CONFIG_KEYS.items():
        if config_key not in targets:
            raise SelectiveAutonomyTargetsStaticError(f"quality_target_missing:{config_key}")
        value = float(targets[config_key])
        expected = EXPECTED_QUALITY_TARGETS[logical]
        if abs(value - expected) > 1e-12:
            raise SelectiveAutonomyTargetsStaticError(
                f"quality_target_drift:{logical}:{value}!={expected}"
            )
        bound[logical] = value
    if set(bound) != set(EXPECTED_QUALITY_TARGETS):
        raise SelectiveAutonomyTargetsStaticError("quality_targets_incomplete")
    return bound


def bind_labor_targets_from_config(
    config_path: Path = AUTONOMY_CONFIG_PATH,
) -> dict[str, float]:
    """Prove config labor bounds match frozen MF-P9-15.03 product targets."""

    targets = _load_operational_targets(config_path)
    bound: dict[str, float] = {}
    for logical, config_key in LABOR_CONFIG_KEYS.items():
        if config_key not in targets:
            raise SelectiveAutonomyTargetsStaticError(f"labor_target_missing:{config_key}")
        value = float(targets[config_key])
        expected = EXPECTED_LABOR_TARGETS[logical]
        if abs(value - expected) > 1e-12:
            raise SelectiveAutonomyTargetsStaticError(
                f"labor_target_drift:{logical}:{value}!={expected}"
            )
        bound[logical] = value
    if set(bound) != set(EXPECTED_LABOR_TARGETS):
        raise SelectiveAutonomyTargetsStaticError("labor_targets_incomplete")
    return bound


def refuse_quality_overclaim(document: Mapping[str, Any]) -> None:
    """Fail closed on MF-P9-15.01 completion / measured-holdout overclaims."""

    for key in (
        "mf_p9_15_01_complete",
        "blinded_human_anchor_holdout_measured",
        "holdout_metrics_pass_claimed",
        "doctor_green_claimed",
        "gold_claimed",
        "production_evidence_pass_claimed",
    ):
        if document.get(key) is True:
            raise SelectiveAutonomyTargetsStaticError(f"quality_overclaim:{key}")


def refuse_labor_overclaim(document: Mapping[str, Any]) -> None:
    """Fail closed on MF-P9-15.03 completion / production-measurement overclaims."""

    for key in (
        "mf_p9_15_03_complete",
        "production_labor_measured",
        "review_time_proxy_accepted",
        "doctor_green_claimed",
        "gold_claimed",
        "production_evidence_pass_claimed",
    ):
        if document.get(key) is True:
            raise SelectiveAutonomyTargetsStaticError(f"labor_overclaim:{key}")


def evaluate_anti_bucket_collapse(claim: Mapping[str, Any]) -> dict[str, bool]:
    """Reject aggregate-only wins that hide a failing anti-collapse bucket."""

    buckets = claim.get("bucket_passes")
    if not isinstance(buckets, Mapping):
        raise SelectiveAutonomyTargetsStaticError("anti_collapse_buckets_missing")
    missing = [name for name in REQUIRED_ANTI_COLLAPSE_BUCKETS if name not in buckets]
    if missing:
        raise SelectiveAutonomyTargetsStaticError(
            "anti_collapse_buckets_incomplete:" + ",".join(missing)
        )

    aggregate_pass = bool(claim.get("aggregate_pass"))
    all_buckets_pass = all(bool(buckets[name]) for name in REQUIRED_ANTI_COLLAPSE_BUCKETS)
    if aggregate_pass and not all_buckets_pass:
        raise SelectiveAutonomyTargetsStaticError("bucket_collapse_hidden_by_aggregate")

    hard_scopes = claim.get("hard_anatomy_scope_passes")
    if not isinstance(hard_scopes, Mapping):
        raise SelectiveAutonomyTargetsStaticError("hard_anatomy_scopes_missing")
    missing_scopes = [name for name in HARD_ANATOMY_SCOPES if name not in hard_scopes]
    if missing_scopes:
        raise SelectiveAutonomyTargetsStaticError(
            "hard_anatomy_scopes_incomplete:" + ",".join(missing_scopes)
        )
    if aggregate_pass and not all(bool(hard_scopes[name]) for name in HARD_ANATOMY_SCOPES):
        raise SelectiveAutonomyTargetsStaticError("hard_anatomy_collapse_hidden_by_aggregate")

    return {
        "required_buckets_present": True,
        "aggregate_cannot_hide_failing_bucket": True,
        "hard_anatomy_scopes_present": True,
        "aggregate_cannot_hide_failing_hard_anatomy_scope": True,
    }


def evaluate_review_time_proxy_refusal(report: Mapping[str, Any]) -> dict[str, bool]:
    """Labor evidence must use package/pixel denominators, not review-time proxies."""

    for field in FORBIDDEN_LABOR_PROXY_FIELDS:
        if field in report and report.get(field) is not None:
            raise SelectiveAutonomyTargetsStaticError(f"review_time_proxy_present:{field}")
    if report.get("labor_authority") == "review_time_proxy":
        raise SelectiveAutonomyTargetsStaticError("review_time_proxy_authority")
    if report.get("zero_touch_derived_from_review_minutes") is True:
        raise SelectiveAutonomyTargetsStaticError("zero_touch_from_review_minutes")
    return {
        "forbidden_proxy_fields_absent": True,
        "review_time_proxy_authority_rejected": True,
        "requires_measured_production_denominators": True,
    }


def _fixture_anti_collapse_claim(*, hide_failure: bool) -> dict[str, Any]:
    bucket_passes = {name: True for name in REQUIRED_ANTI_COLLAPSE_BUCKETS}
    hard_scopes = {name: True for name in HARD_ANATOMY_SCOPES}
    if hide_failure:
        bucket_passes["hard_bucket"] = False
        hard_scopes["fingers"] = False
    return {
        "aggregate_pass": True,
        "bucket_passes": bucket_passes,
        "hard_anatomy_scope_passes": hard_scopes,
    }


def run_selective_autonomy_targets_static_suite(
    *,
    config_path: Path = AUTONOMY_CONFIG_PATH,
) -> dict[str, Any]:
    """Execute MF-P9-15.01/15.03 STATIC binders and seal a schema-valid report."""

    quality = bind_quality_targets_from_config(config_path)
    labor = bind_labor_targets_from_config(config_path)

    # Positive anti-collapse fixture (all buckets pass).
    anti_collapse_ok = evaluate_anti_bucket_collapse(
        _fixture_anti_collapse_claim(hide_failure=False)
    )
    # Negative: aggregate pass with failing hard bucket must fail closed.
    try:
        evaluate_anti_bucket_collapse(_fixture_anti_collapse_claim(hide_failure=True))
        raise SelectiveAutonomyTargetsStaticError("bucket_collapse_negative_fixture_passed")
    except SelectiveAutonomyTargetsStaticError as exc:
        if "bucket_collapse_hidden" not in exc.reason:
            raise
        anti_collapse_negative_blocked = True

    proxy_refusal = evaluate_review_time_proxy_refusal(
        {
            "labor_authority": "measured_production_report",
            "zero_touch_derived_from_review_minutes": False,
        }
    )
    try:
        evaluate_review_time_proxy_refusal(
            {
                "labor_authority": "review_time_proxy",
                "review_minutes_per_image": 12.0,
            }
        )
        raise SelectiveAutonomyTargetsStaticError("review_time_proxy_negative_fixture_passed")
    except SelectiveAutonomyTargetsStaticError as exc:
        if "review_time_proxy" not in exc.reason:
            raise
        proxy_negative_blocked = True

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "items": ["MF-P9-15.01", "MF-P9-15.03"],
        "quality_targets": dict(sorted(quality.items())),
        "labor_targets": dict(sorted(labor.items())),
        "hard_anatomy_scopes": list(HARD_ANATOMY_SCOPES),
        "anti_collapse_buckets": list(REQUIRED_ANTI_COLLAPSE_BUCKETS),
        "anti_collapse_checks": dict(sorted(anti_collapse_ok.items())),
        "anti_collapse_negative_fixture_blocked": anti_collapse_negative_blocked,
        "labor_proxy_refusal_checks": dict(sorted(proxy_refusal.items())),
        "labor_proxy_negative_fixture_blocked": proxy_negative_blocked,
        "checks": {
            "quality_targets_bound": "pass",
            "labor_targets_bound": "pass",
            "anti_bucket_collapse": "pass",
            "review_time_proxy_refusal": "pass",
        },
        "mf_p9_15_01_complete": False,
        "mf_p9_15_03_complete": False,
        "blinded_human_anchor_holdout_measured": False,
        "production_labor_measured": False,
        "review_time_proxy_accepted": False,
        "holdout_metrics_pass_claimed": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": list(HONEST_NON_CLAIMS),
    }
    refuse_quality_overclaim(draft)
    refuse_labor_overclaim(draft)

    digest = _sha(draft)
    draft["report_id"] = f"sats_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})

    issues = validate_document(draft, "selective_autonomy_targets_static_report")
    if issues:
        detail = "; ".join(
            f"{getattr(issue, 'pointer', None) or '/'}: {issue.message}" for issue in issues
        )
        raise SelectiveAutonomyTargetsStaticError(f"schema_validation_failed:{detail}")
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "EXPECTED_LABOR_TARGETS",
    "EXPECTED_QUALITY_TARGETS",
    "FORBIDDEN_LABOR_PROXY_FIELDS",
    "HARD_ANATOMY_SCOPES",
    "HONEST_NON_CLAIMS",
    "PROOF_TIER",
    "REQUIRED_ANTI_COLLAPSE_BUCKETS",
    "SCHEMA_VERSION",
    "SelectiveAutonomyTargetsStaticError",
    "bind_labor_targets_from_config",
    "bind_quality_targets_from_config",
    "evaluate_anti_bucket_collapse",
    "evaluate_review_time_proxy_refusal",
    "refuse_labor_overclaim",
    "refuse_quality_overclaim",
    "run_selective_autonomy_targets_static_suite",
]
