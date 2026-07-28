from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from maskfactory.cli import main
from maskfactory.daz.control import (
    DazControlError,
    initialize_daz_root,
    initialize_state_database,
    load_control_configuration,
)
from maskfactory.daz.monitoring import (
    build_daily_report,
    build_dashboard,
    collect_monitoring_snapshot,
    evaluate_alerts,
    load_alert_policy,
    validate_monitoring_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "daz"
POLICY = CONFIG / "alerts.yaml"
SCHEMA_ROOT = ROOT / "src" / "maskfactory" / "schemas"
CAPTURED = datetime(2026, 7, 19, 5, 0, tzinfo=UTC)
GIB = 1024**3


def _fixture_configuration(tmp_path: Path):
    config = tmp_path / "configs"
    shutil.copytree(CONFIG, config)
    daz_root = tmp_path / "DAZ Root"
    paths_file = config / "paths.yaml"
    paths = yaml.safe_load(paths_file.read_text(encoding="utf-8"))
    paths.update(
        {
            "root": str(daz_root),
            "root_identity": str(daz_root / "00_control" / "root_identity.json"),
            "acquisition_database": str(daz_root / "00_control" / "acquisition.sqlite3"),
            "state_database": str(daz_root / "10_queue" / "queue.sqlite"),
        }
    )
    paths_file.write_text(yaml.safe_dump(paths, sort_keys=False), encoding="utf-8")
    capacity_file = config / "acquisition_capacity.yaml"
    capacity = yaml.safe_load(capacity_file.read_text(encoding="utf-8"))
    capacity["root"] = str(daz_root)
    capacity_file.write_text(yaml.safe_dump(capacity, sort_keys=False), encoding="utf-8")
    initialize_daz_root(daz_root, apply=True)
    configuration = load_control_configuration(config)
    initialize_state_database(configuration.paths.state_database)
    return config, configuration


def _snapshot(**overrides):
    document = {
        "schema_version": "1.0.0",
        "captured_at": "2026-07-19T05:00:00Z",
        "machine": {
            "f_free_bytes": 200 * GIB,
            "database_integrity": "ok",
            "source_assets_in_git": 0,
            "maintenance_planned": False,
        },
        "pipeline": {
            "retry_rate": 0.0,
            "worker_crashes": 0,
            "accepted_semantic_defects": 0,
            "mapping_mismatches": 0,
            "stale_certificates": 0,
            "accepted_synthetic_scenes": 2,
        },
        "corpus": {
            "asset_snapshot_changes": 0,
            "synthetic_training_authority": "train_only_synthetic",
        },
    }
    for section, values in overrides.items():
        document[section].update(values)
    return document


def test_alert_and_snapshot_schemas_are_closed_and_policy_is_local_only() -> None:
    for name in ("daz_alerts.schema.json", "daz_monitoring_snapshot.schema.json"):
        Draft202012Validator.check_schema(
            json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
        )
    policy = load_alert_policy(POLICY)
    assert policy.document["local_only"] is True
    assert len(policy.rules) == len({rule["rule_id"] for rule in policy.rules}) == 11


def test_hard_disk_alert_suppresses_soft_duplicate_and_orders_severity() -> None:
    evaluation = evaluate_alerts(
        load_alert_policy(POLICY),
        _snapshot(
            machine={"f_free_bytes": 99 * GIB},
            pipeline={"worker_crashes": 3, "retry_rate": 0.5},
        ),
    )
    ids = [row["rule_id"] for row in evaluation["alerts"]]
    assert ids == ["hard_disk_floor", "repeated_worker_crash", "rising_retry_rate"]
    assert "soft_disk_floor" not in ids
    assert evaluation["highest_severity"] == "high"
    assert evaluation["required_actions"] == [
        "drain_affected_work",
        "pause_planning_investigate",
    ]


@pytest.mark.parametrize(
    ("section", "metric", "value", "rule_id"),
    [
        ("machine", "database_integrity", "malformed", "database_corrupt"),
        ("machine", "source_assets_in_git", 1, "source_asset_in_git"),
        ("pipeline", "accepted_semantic_defects", 1, "accepted_semantic_defect"),
    ],
)
def test_critical_alerts_stop_ingestion_and_preserve_evidence(
    section: str, metric: str, value, rule_id: str
) -> None:
    evaluation = evaluate_alerts(load_alert_policy(POLICY), _snapshot(**{section: {metric: value}}))
    assert evaluation["highest_severity"] == "critical"
    assert evaluation["alerts"][0]["rule_id"] == rule_id
    assert evaluation["required_actions"][0] == "stop_ingestion_preserve_evidence"


def test_alert_evaluation_is_deterministic_and_invalid_snapshot_fails_closed() -> None:
    policy = load_alert_policy(POLICY)
    snapshot = _snapshot(corpus={"asset_snapshot_changes": 1})
    assert evaluate_alerts(policy, snapshot) == evaluate_alerts(policy, snapshot)
    snapshot["unknown"] = {}
    with pytest.raises(DazControlError, match="closed schema|Additional properties"):
        validate_monitoring_snapshot(snapshot)


def test_collector_reads_queue_reservation_and_events_without_mutating_state(
    tmp_path: Path,
) -> None:
    _, configuration = _fixture_configuration(tmp_path)
    database = configuration.paths.state_database
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO scene_recipes VALUES ('scene_a','family','ready','{}')")
        connection.execute("INSERT INTO jobs VALUES ('job_a','scene_a','complete',2)")
        connection.execute(
            "INSERT INTO storage_reservations VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "reservation_a",
                "job_a",
                "standard",
                10,
                12,
                15,
                "consumed",
                "2026-07-19T04:00:00Z",
                None,
                "{}",
            ),
        )
        connection.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
            (
                "event_crash",
                "2026-07-19T04:30:00Z",
                "worker.crash",
                "job",
                "job_a",
                "job_a",
                2,
                "{}",
            ),
        )
    before = database.read_bytes()
    snapshot = collect_monitoring_snapshot(
        configuration,
        observed_f_free_bytes=200 * GIB,
        observed_c_free_bytes=50 * GIB,
        captured_at=CAPTURED,
    )
    assert snapshot["pipeline"]["accepted_synthetic_scenes"] == 1
    assert snapshot["pipeline"]["retry_count"] == 1
    assert snapshot["pipeline"]["worker_crashes"] == 1
    assert snapshot["machine"]["f_committed_bytes"] == 15
    assert snapshot["corpus"]["synthetic_training_authority"] == "train_only_synthetic"
    assert database.read_bytes() == before


def test_dashboard_and_daily_report_keep_synthetic_truth_and_actions_explicit() -> None:
    snapshot = _snapshot(machine={"f_free_bytes": 149 * GIB})
    alerts = evaluate_alerts(load_alert_policy(POLICY), snapshot)
    dashboard = build_dashboard(snapshot, alerts)
    daily = build_daily_report(snapshot, alerts)
    assert dashboard["truth_labels"]["authority"] == "train_only_synthetic"
    assert dashboard["truth_labels"]["accepted_scene_metric"] == "accepted_synthetic_scenes"
    assert dashboard["alerts"]["highest_severity"] == "warning"
    assert daily["actions_needed"] == ["pause_planning_investigate"]
    assert "not real gold" in daily["truth_boundary"]


def test_monitor_cli_emits_one_local_truth_labeled_bundle(tmp_path: Path) -> None:
    config, _ = _fixture_configuration(tmp_path)
    result = CliRunner().invoke(
        main,
        [
            "daz",
            "monitor",
            "snapshot",
            "--config-root",
            str(config),
            "--policy",
            str(config / "alerts.yaml"),
            "--f-free-bytes",
            str(149 * GIB),
            "--c-free-bytes",
            str(50 * GIB),
        ],
    )
    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    assert document["reason"] == "daz_monitoring_snapshot"
    assert document["data"]["alerts"]["highest_severity"] == "warning"
    assert document["data"]["dashboard"]["truth_labels"]["authority"] == ("train_only_synthetic")
