import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from maskfactory.autonomy.calibration import AutonomyCalibrationError, load_autonomy_config
from maskfactory.autonomy.metrics import (
    AutonomyMetricsError,
    build_autonomy_metrics_report,
    build_autonomy_metrics_report_from_inputs,
    render_autonomy_metrics_dashboard,
    validate_autonomy_metrics_report,
)
from maskfactory.validation import validate_document

ROOT = Path(__file__).resolve().parents[1]
HASH_A = "a" * 64
HASH_B = "b" * 64


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _inputs() -> dict:
    return {
        "schema_version": "1.0.0",
        "cohort_id": "autonomy-ops-20260715",
        "observed_at": "2026-07-15T12:00:00Z",
        "input_manifest_sha256": HASH_A,
        "pipeline_fingerprint_sha256": HASH_B,
        "truth_tier_counts": {
            "human_anchor_gold_packages": 40,
            "autonomous_certified_gold_packages": 340,
            "machine_candidate_packages": 12,
            "weighted_pseudo_label_packages": 8,
        },
        "zero_touch_packages": 380,
        "eligible_packages": 400,
        "routine_human_touched_packages": 20,
        "residual_review_packages": 12,
        "human_touch_count": 32,
        "manually_changed_pixels": 400,
        "predicted_pixels": 1_000_000,
        "blinded_evaluated_packages": 40,
        "mask_iou_sum": 36.4,
        "boundary_f1_sum": 33.6,
        "audited_packages": 300,
        "false_accepts": 1,
        "serious_false_accepts": 0,
        "confidence_level": 0.95,
    }


def _report() -> dict:
    return build_autonomy_metrics_report_from_inputs(_inputs())


def _reseal(report: dict) -> None:
    report["sha256"] = _canonical_sha256(
        {key: value for key, value in report.items() if key != "sha256"}
    )


def test_autonomy_metrics_schemas_and_dashboard_keep_all_domains_separate() -> None:
    for schema_name in ("autonomy_metrics_inputs", "autonomy_metrics"):
        schema = json.loads(
            (ROOT / f"src/maskfactory/schemas/{schema_name}.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
    report = _report()
    assert validate_document(_inputs(), "autonomy_metrics_inputs") == ()
    assert validate_document(report, "autonomy_metrics") == ()
    dashboard = render_autonomy_metrics_dashboard(report)
    assert "Cohort: autonomy-ops-20260715" in dashboard
    assert f"Input manifest SHA-256: {HASH_A}" in dashboard
    assert "Zero-touch throughput: 95.000% (380/400)" in dashboard
    assert "Human-anchor gold: 40" in dashboard
    assert "Human touches per 100 images: 8.000 (32/400)" in dashboard
    assert "Audited fraction: 75.000% (300/400)" in dashboard
    assert "Residual-review fraction: 3.000% (12/400)" in dashboard
    assert "40.000 (400/1000000)" in dashboard
    assert "Mean mask IoU: 0.910000 (sum=36.400000, n=40)" in dashboard
    assert "Observed audit false-accept rate: 0.003333 (1/300)" in dashboard
    assert "Zero-touch throughput is not an accuracy, quality, or confidence claim." in dashboard


def test_direct_builder_requires_hash_bound_cohort_and_quality_sums() -> None:
    inputs = _inputs()
    inputs.pop("schema_version")
    report = build_autonomy_metrics_report(**inputs)
    assert report["schema_version"] == "3.0.0"
    assert report["source_input_sha256"] == _canonical_sha256(_inputs())
    assert report["blinded_quality"]["mean_boundary_f1"] == pytest.approx(0.84)


@pytest.mark.parametrize("conflated_field", ["accuracy", "confidence", "quality"])
def test_schema_rejects_zero_touch_conflation(conflated_field: str) -> None:
    report = _report()
    report["throughput"][conflated_field] = report["throughput"]["zero_touch_fraction"]
    _reseal(report)
    with pytest.raises(AutonomyMetricsError, match="invalid autonomy metrics report"):
        validate_autonomy_metrics_report(report)


def test_schema_rejects_conflated_zero_touch_label() -> None:
    report = _report()
    report["throughput"]["label"] = "Zero-touch accuracy/confidence"
    _reseal(report)
    with pytest.raises(AutonomyMetricsError, match="invalid autonomy metrics report"):
        validate_autonomy_metrics_report(report)


def test_autonomy_config_rejects_reporting_contract_drift(tmp_path: Path) -> None:
    config = load_autonomy_config(ROOT / "configs/autonomous_masks.yaml")
    drifted = copy.deepcopy(config)
    drifted["reporting"]["human_workload"]["metrics"]["audited_fraction"][1] = "audited_packages"
    path = tmp_path / "autonomous_masks.yaml"
    path.write_text(yaml.safe_dump(drifted, sort_keys=False), encoding="utf-8")
    with pytest.raises(AutonomyCalibrationError, match="exact denominators"):
        load_autonomy_config(path)


def test_autonomy_config_requires_closed_bulk_semantic_alignment_contract(
    tmp_path: Path,
) -> None:
    config = load_autonomy_config(ROOT / "configs/autonomous_masks.yaml")
    drifted = copy.deepcopy(config)
    drifted["package_semantic_alignment"]["execution_mode"] = "one_case_at_a_time"
    path = tmp_path / "autonomous_masks.yaml"
    path.write_text(yaml.safe_dump(drifted, sort_keys=False), encoding="utf-8")
    with pytest.raises(AutonomyCalibrationError, match="semantic-alignment contract"):
        load_autonomy_config(path)


@pytest.mark.parametrize(
    ("domain", "field"),
    [
        ("cohort", "eligible_packages"),
        ("throughput", "eligible_packages"),
        ("truth_tier_breakdown", "eligible_packages"),
        ("human_workload", "eligible_packages"),
        ("human_workload", "predicted_pixels"),
        ("blinded_quality", "evaluated_packages"),
        ("blinded_quality", "mask_iou_sum"),
        ("statistical_confidence", "audited_packages"),
    ],
)
def test_report_rejects_missing_denominators_and_numerators(domain: str, field: str) -> None:
    report = _report()
    del report[domain][field]
    _reseal(report)
    with pytest.raises(AutonomyMetricsError, match="invalid autonomy metrics report"):
        validate_autonomy_metrics_report(report)


@pytest.mark.parametrize(
    ("domain", "field", "value"),
    [
        ("throughput", "zero_touch_fraction", 0.5),
        ("human_workload", "routine_human_touch_fraction", 0.5),
        ("human_workload", "audited_fraction", 0.5),
        ("human_workload", "residual_review_fraction", 0.5),
        ("human_workload", "human_touches_per_100_images", 999.0),
        ("human_workload", "manual_changed_pixels_per_100k", 999.0),
        ("blinded_quality", "mean_mask_iou", 0.5),
        ("blinded_quality", "mean_boundary_f1", 0.5),
        ("statistical_confidence", "audit_false_accept_rate", 0.5),
        ("statistical_confidence", "serious_false_accept_rate", 0.5),
        ("statistical_confidence", "false_accept_upper_bound", 0.5),
        ("statistical_confidence", "serious_false_accept_upper_bound", 0.5),
    ],
)
def test_report_rejects_every_derived_metric_drift(domain: str, field: str, value: float) -> None:
    report = _report()
    report[domain][field] = value
    _reseal(report)
    with pytest.raises(AutonomyMetricsError, match="denominator"):
        validate_autonomy_metrics_report(report)


def test_report_rejects_mismatched_audit_denominators_after_resealing() -> None:
    report = _report()
    report["human_workload"]["audited_packages"] = 299
    report["human_workload"]["audited_fraction"] = 299 / 400
    _reseal(report)
    with pytest.raises(AutonomyMetricsError, match="audit denominators differ"):
        validate_autonomy_metrics_report(report)


def test_builder_rejects_residual_review_outside_routine_touched_subset() -> None:
    inputs = _inputs()
    inputs["residual_review_packages"] = 21
    with pytest.raises(AutonomyMetricsError, match="counts or denominators"):
        build_autonomy_metrics_report_from_inputs(inputs)


def test_builder_rejects_truth_tier_counts_that_do_not_reconcile() -> None:
    inputs = _inputs()
    inputs["truth_tier_counts"]["machine_candidate_packages"] = 11
    with pytest.raises(AutonomyMetricsError, match="do not reconcile"):
        build_autonomy_metrics_report_from_inputs(inputs)


def test_report_rejects_outer_and_source_hash_tampering() -> None:
    report = _report()
    report["sha256"] = "0" * 64
    with pytest.raises(AutonomyMetricsError, match="report hash mismatch"):
        validate_autonomy_metrics_report(report)
    report = _report()
    report["source_input_sha256"] = "0" * 64
    _reseal(report)
    with pytest.raises(AutonomyMetricsError, match="source-input hash mismatch"):
        validate_autonomy_metrics_report(report)


def test_exact_serious_failure_bound_handles_positive_defects() -> None:
    inputs = _inputs()
    inputs["false_accepts"] = 2
    inputs["serious_false_accepts"] = 1
    report = build_autonomy_metrics_report_from_inputs(inputs)
    bound = report["statistical_confidence"]["serious_false_accept_upper_bound"]
    assert 1 / 300 < bound < 1


@pytest.mark.parametrize(
    "missing",
    [
        "eligible_packages",
        "predicted_pixels",
        "blinded_evaluated_packages",
        "audited_packages",
        "input_manifest_sha256",
        "pipeline_fingerprint_sha256",
        "truth_tier_counts",
    ],
)
def test_input_schema_rejects_missing_binding_or_denominator(missing: str) -> None:
    inputs = _inputs()
    del inputs[missing]
    assert validate_document(inputs, "autonomy_metrics_inputs")


def test_cli_builds_verifies_and_renders_exact_report(tmp_path: Path) -> None:
    inputs_path = tmp_path / "inputs.json"
    report_path = tmp_path / "report.json"
    dashboard_path = tmp_path / "dashboard.md"
    inputs_path.write_text(json.dumps(_inputs()), encoding="utf-8")
    built = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/autonomy_metrics_report.py"),
            str(inputs_path),
            "--output",
            str(report_path),
            "--dashboard",
            str(dashboard_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(built.stdout)["cohort_id"] == "autonomy-ops-20260715"
    verify = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/autonomy_metrics_report.py"),
            str(report_path),
            "--verify",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert (
        json.loads(verify.stdout)["sha256"]
        == json.loads(report_path.read_text(encoding="utf-8"))["sha256"]
    )
    assert "(300/400)" in dashboard_path.read_text(encoding="utf-8")
