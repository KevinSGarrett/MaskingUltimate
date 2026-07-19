from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from .control import DazControlError, DazErrorCode
from .policy import DazConfiguration

SEVERITIES = ("info", "warning", "high", "critical")


@dataclass(frozen=True)
class AlertPolicy:
    document: Mapping[str, Any]
    sha256: str
    rules: tuple[Mapping[str, Any], ...]


def load_alert_policy(path: Path) -> AlertPolicy:
    path = Path(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        schema = json.loads(_schema_path("daz_alerts.schema.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"alert policy is unreadable: {exc}",
            evidence_paths=(str(path),),
        ) from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.path)
    )
    if errors:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"alert policy violates its closed schema: {errors[0].message}",
            evidence_paths=(str(path),),
        )
    rule_ids = [str(rule["rule_id"]) for rule in document["rules"]]
    if len(rule_ids) != len(set(rule_ids)):
        raise DazControlError(DazErrorCode.CONFIG_INVALID, "alert rule IDs must be unique")
    canonical = _canonical_bytes(document)
    return AlertPolicy(
        document=document,
        sha256=hashlib.sha256(canonical).hexdigest(),
        rules=tuple(document["rules"]),
    )


def validate_monitoring_snapshot(snapshot: Mapping[str, Any]) -> None:
    schema = json.loads(
        _schema_path("daz_monitoring_snapshot.schema.json").read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(snapshot), key=lambda item: list(item.path)
    )
    if errors:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"monitoring snapshot violates its closed schema: {errors[0].message}",
        )


def collect_monitoring_snapshot(
    configuration: DazConfiguration,
    *,
    observed_f_free_bytes: int,
    observed_c_free_bytes: int,
    signals: Mapping[str, Mapping[str, Any]] | None = None,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Collect DB-backed counters plus explicit host signals without launching DAZ."""
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (observed_f_free_bytes, observed_c_free_bytes)
    ):
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID, "monitoring free-space readings must be integers"
        )
    database = configuration.paths.state_database
    try:
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        job_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute("SELECT state,count(*) FROM jobs GROUP BY state")
        }
        attempts = int(
            connection.execute("SELECT coalesce(sum(attempt),0) FROM jobs").fetchone()[0]
        )
        active_leases = int(connection.execute("SELECT count(*) FROM leases").fetchone()[0])
        committed = int(
            connection.execute(
                "SELECT coalesce(sum(required_bytes),0) FROM storage_reservations "
                "WHERE state IN ('active','consumed')"
            ).fetchone()[0]
        )
        package_count = int(
            connection.execute("SELECT count(*) FROM package_exports").fetchone()[0]
        )
        dataset_rows = int(
            connection.execute("SELECT count(*) FROM dataset_membership").fetchone()[0]
        )
        event_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT event_type,count(*) FROM events GROUP BY event_type"
            )
        }
    except sqlite3.Error as exc:
        raise DazControlError(
            DazErrorCode.STATE_INTEGRITY_FAILED,
            f"monitoring state read failed: {exc}",
            evidence_paths=(str(database),),
        ) from exc
    finally:
        if "connection" in locals():
            connection.close()
    completed = int(job_counts.get("complete", 0))
    rejected = int(job_counts.get("rejected", 0) + job_counts.get("failed", 0))
    attempted_jobs = sum(job_counts.values())
    retries = max(0, attempts - attempted_jobs)
    machine = {
        "f_free_bytes": observed_f_free_bytes,
        "f_committed_bytes": committed,
        "c_free_bytes": observed_c_free_bytes,
        "database_integrity": "ok" if integrity == "ok" else integrity,
        "source_assets_in_git": 0,
        "maintenance_planned": False,
    }
    pipeline = {
        "queue_depth": int(job_counts.get("pending", 0) + job_counts.get("retry", 0)),
        "active_leases": active_leases,
        "attempted_synthetic_scenes": attempted_jobs,
        "accepted_synthetic_scenes": completed,
        "rejected_synthetic_scenes": rejected,
        "retry_count": retries,
        "retry_rate": retries / attempts if attempts else 0.0,
        "worker_crashes": _event_family_count(event_counts, ("crash",)),
        "worker_timeouts": _event_family_count(event_counts, ("timeout",)),
        "interactive_prompts": _event_family_count(event_counts, ("prompt", "dialog")),
        "accepted_semantic_defects": 0,
        "mapping_mismatches": 0,
        "stale_certificates": 0,
        "package_count": package_count,
    }
    corpus = {
        "dataset_membership_rows": dataset_rows,
        "asset_snapshot_changes": _event_family_count(event_counts, ("asset.snapshot",)),
        "accepted_synthetic_scenes": completed,
        "synthetic_training_authority": "train_only_synthetic",
    }
    for section_name, values in (signals or {}).items():
        if section_name not in {"machine", "pipeline", "corpus"} or not isinstance(values, Mapping):
            raise DazControlError(
                DazErrorCode.CONFIG_INVALID, "monitoring signal sections must be closed"
            )
        target = {"machine": machine, "pipeline": pipeline, "corpus": corpus}[section_name]
        target.update(values)
    snapshot = {
        "schema_version": "1.0.0",
        "captured_at": _timestamp(captured_at),
        "machine": machine,
        "pipeline": pipeline,
        "corpus": corpus,
    }
    validate_monitoring_snapshot(snapshot)
    return snapshot


def evaluate_alerts(policy: AlertPolicy, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate local-only alerts and suppress lower-severity duplicates by group."""
    validate_monitoring_snapshot(snapshot)
    matches: list[dict[str, Any]] = []
    for rule in policy.rules:
        actual = _metric(snapshot, str(rule["metric_path"]))
        if actual is None or not _compare(actual, str(rule["operator"]), rule["threshold"]):
            continue
        matches.append(
            {
                "rule_id": rule["rule_id"],
                "severity": rule["severity"],
                "metric_path": rule["metric_path"],
                "actual": actual,
                "operator": rule["operator"],
                "threshold": rule["threshold"],
                "action": rule["action"],
                "suppression_group": rule.get("suppression_group"),
            }
        )
    matches.sort(key=lambda row: (-SEVERITIES.index(str(row["severity"])), str(row["rule_id"])))
    selected: list[dict[str, Any]] = []
    occupied_groups: set[str] = set()
    for match in matches:
        group = match.get("suppression_group")
        if group is not None and str(group) in occupied_groups:
            continue
        selected.append(match)
        if group is not None:
            occupied_groups.add(str(group))
    highest = selected[0]["severity"] if selected else None
    body = {
        "schema_version": "1.0.0",
        "captured_at": snapshot["captured_at"],
        "policy_sha256": policy.sha256,
        "local_only": True,
        "highest_severity": highest,
        "alerts": selected,
        "required_actions": list(dict.fromkeys(row["action"] for row in selected)),
    }
    return {**body, "evaluation_sha256": hashlib.sha256(_canonical_bytes(body)).hexdigest()}


def build_dashboard(
    snapshot: Mapping[str, Any], alert_evaluation: Mapping[str, Any]
) -> dict[str, Any]:
    """Build a truth-labeled machine/pipeline/corpus dashboard document."""
    validate_monitoring_snapshot(snapshot)
    return {
        "schema_version": "1.0.0",
        "captured_at": snapshot["captured_at"],
        "truth_labels": {
            "accepted_scene_metric": "accepted_synthetic_scenes",
            "authority": "train_only_synthetic",
            "not_claimed": ["real_image_accuracy", "real_gold_count", "zero_touch_operation"],
        },
        "machine": dict(snapshot["machine"]),
        "pipeline": dict(snapshot["pipeline"]),
        "coverage_and_corpus": dict(snapshot["corpus"]),
        "alerts": {
            "highest_severity": alert_evaluation["highest_severity"],
            "count": len(alert_evaluation["alerts"]),
            "required_actions": list(alert_evaluation["required_actions"]),
        },
    }


def build_daily_report(
    snapshot: Mapping[str, Any], alert_evaluation: Mapping[str, Any]
) -> dict[str, Any]:
    """Render the actionable daily report fields available from current governed state."""
    validate_monitoring_snapshot(snapshot)
    pipeline = snapshot["pipeline"]
    corpus = snapshot["corpus"]
    machine = snapshot["machine"]
    return {
        "schema_version": "1.0.0",
        "captured_at": snapshot["captured_at"],
        "backlog_and_leases": {
            "queue_depth": pipeline.get("queue_depth"),
            "active_leases": pipeline.get("active_leases"),
        },
        "scene_outcomes": {
            "attempted_synthetic_scenes": pipeline.get("attempted_synthetic_scenes"),
            "accepted_synthetic_scenes": pipeline.get("accepted_synthetic_scenes"),
            "rejected_synthetic_scenes": pipeline.get("rejected_synthetic_scenes"),
            "retry_count": pipeline.get("retry_count"),
        },
        "resources": {
            "f_free_bytes": machine.get("f_free_bytes"),
            "f_committed_bytes": machine.get("f_committed_bytes"),
            "c_free_bytes": machine.get("c_free_bytes"),
        },
        "integrity": {
            "database_integrity": machine.get("database_integrity"),
            "accepted_semantic_defects": pipeline.get("accepted_semantic_defects"),
            "package_count": pipeline.get("package_count"),
        },
        "coverage_and_downstream": dict(corpus),
        "actions_needed": list(alert_evaluation["required_actions"]),
        "truth_boundary": "Synthetic counts are train-only and are not real gold or real-image accuracy.",
    }


def _event_family_count(event_counts: Mapping[str, int], needles: tuple[str, ...]) -> int:
    return sum(
        count
        for event_type, count in event_counts.items()
        if any(needle in event_type.lower() for needle in needles)
    )


def _metric(snapshot: Mapping[str, Any], path: str) -> Any:
    section, key = path.split(".", 1)
    values = snapshot.get(section)
    return values.get(key) if isinstance(values, Mapping) else None


def _compare(actual: Any, operator: str, threshold: Any) -> bool:
    try:
        if operator == "eq":
            return actual == threshold
        if operator == "ne":
            return actual != threshold
        if operator == "gt":
            return actual > threshold
        if operator == "gte":
            return actual >= threshold
        if operator == "lt":
            return actual < threshold
        if operator == "lte":
            return actual <= threshold
        raise KeyError(operator)
    except (KeyError, TypeError) as exc:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID, "alert comparison types or operator are invalid"
        ) from exc


def _timestamp(value: datetime | None) -> str:
    captured = value or datetime.now(UTC)
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    return captured.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _schema_path(name: str) -> Path:
    return Path(__file__).parents[1] / "schemas" / name


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = [
    "AlertPolicy",
    "SEVERITIES",
    "build_daily_report",
    "build_dashboard",
    "collect_monitoring_snapshot",
    "evaluate_alerts",
    "load_alert_policy",
    "validate_monitoring_snapshot",
]
