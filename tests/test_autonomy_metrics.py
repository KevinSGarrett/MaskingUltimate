import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from maskfactory.autonomy.calibration import AutonomyCalibrationError, load_autonomy_config
from maskfactory.autonomy.metrics import (
    AutonomyMetricsError,
    build_autonomy_metrics_report,
    render_autonomy_metrics_dashboard,
    validate_autonomy_metrics_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _report() -> dict:
    return build_autonomy_metrics_report(
        zero_touch_packages=380,
        eligible_packages=400,
        routine_human_touched_packages=20,
        residual_review_packages=12,
        human_touch_count=32,
        manually_changed_pixels=400,
        predicted_pixels=1_000_000,
        blinded_evaluated_packages=40,
        mean_mask_iou=0.91,
        mean_boundary_f1=0.84,
        audited_packages=300,
        false_accepts=1,
        serious_false_accepts=0,
    )


def test_autonomy_metrics_schema_and_dashboard_keep_three_domains_separate() -> None:
    schema = json.loads(
        (ROOT / "src/maskfactory/schemas/autonomy_metrics.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    report = _report()
    assert list(Draft202012Validator(schema).iter_errors(report)) == []
    dashboard = render_autonomy_metrics_dashboard(report)
    assert "Zero-touch throughput: 95.000% (380/400)" in dashboard
    assert "Mean mask IoU: 0.910000" in dashboard
    assert "Human touches per 100 images: 8.000" in dashboard
    assert "Manually changed pixels per 100,000 predicted pixels: 40.000" in dashboard
    assert "95% false-accept upper bound:" in dashboard
    assert "Zero-touch accuracy" not in dashboard
    assert "Zero-touch confidence" not in dashboard


@pytest.mark.parametrize("conflated_field", ["accuracy", "confidence", "quality"])
def test_schema_rejects_zero_touch_conflation(conflated_field: str) -> None:
    report = _report()
    report["throughput"][conflated_field] = report["throughput"]["zero_touch_fraction"]
    with pytest.raises(AutonomyMetricsError, match="invalid autonomy metrics report"):
        validate_autonomy_metrics_report(report)


def test_schema_rejects_conflated_zero_touch_label() -> None:
    report = _report()
    report["throughput"]["label"] = "Zero-touch accuracy/confidence"
    with pytest.raises(AutonomyMetricsError, match="invalid autonomy metrics report"):
        validate_autonomy_metrics_report(report)


def test_autonomy_config_rejects_reporting_label_drift(tmp_path: Path) -> None:
    config = load_autonomy_config(ROOT / "configs/autonomous_masks.yaml")
    drifted = copy.deepcopy(config)
    drifted["reporting"]["throughput"]["label"] = "Zero-touch accuracy"
    path = tmp_path / "autonomous_masks.yaml"
    import yaml

    path.write_text(yaml.safe_dump(drifted, sort_keys=False), encoding="utf-8")
    with pytest.raises(AutonomyCalibrationError, match="keep throughput"):
        load_autonomy_config(path)


@pytest.mark.parametrize(
    ("domain", "field"),
    [
        ("throughput", "eligible_packages"),
        ("human_workload", "eligible_packages"),
        ("human_workload", "predicted_pixels"),
        ("statistical_confidence", "audited_packages"),
    ],
)
def test_report_rejects_missing_denominators(domain: str, field: str) -> None:
    report = _report()
    del report[domain][field]
    with pytest.raises(AutonomyMetricsError, match="invalid autonomy metrics report"):
        validate_autonomy_metrics_report(report)


@pytest.mark.parametrize(
    ("domain", "field", "value"),
    [
        ("throughput", "zero_touch_fraction", 0.5),
        ("human_workload", "audited_fraction", 0.5),
        ("human_workload", "manual_changed_pixels_per_100k", 999.0),
        ("statistical_confidence", "audit_false_accept_rate", 0.5),
    ],
)
def test_report_rejects_denominator_drift(domain: str, field: str, value: float) -> None:
    report = _report()
    report[domain][field] = value
    with pytest.raises(AutonomyMetricsError, match="denominator"):
        validate_autonomy_metrics_report(report)
