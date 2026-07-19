"""Isolated deterministic DAZ failure exercises and recovery contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from .control import DazControlError, DazErrorCode
from .protocol import prepare_job_files
from .runtime import DazRuntimeProfile
from .worker import WindowObservation, _watch_process

SCENARIOS = ("drive_loss", "db_corruption", "crash", "popup", "oom")


@dataclass(frozen=True)
class FailureCampaignPolicy:
    document: Mapping[str, Any]
    sha256: str


@dataclass
class _FakeProcess:
    pid: int
    exit_code: int | None

    def poll(self) -> int | None:
        return self.exit_code

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.exit_code = -9
        return self.exit_code


def load_failure_campaign_policy(path: Path) -> FailureCampaignPolicy:
    path = Path(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        schema = json.loads(
            (
                Path(__file__).parents[1] / "schemas/daz_failure_campaign_policy.schema.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"failure campaign policy is unreadable: {exc}",
            evidence_paths=(str(path),),
        ) from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.path)
    )
    if errors:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"failure campaign policy violates its closed schema: {errors[0].message}",
            evidence_paths=(str(path),),
        )
    return FailureCampaignPolicy(document, hashlib.sha256(_canonical_bytes(document)).hexdigest())


def plan_failure_campaign(
    policy: FailureCampaignPolicy,
    workspace_root: Path,
    *,
    live_root: Path,
    campaign_id: str,
) -> dict[str, Any]:
    workspace, live = _validate_isolation(workspace_root, live_root, campaign_id=campaign_id)
    return {
        "schema_version": "1.0.0",
        "campaign_id": campaign_id,
        "campaign_kind": "isolated_deterministic_fixture",
        "apply": False,
        "policy_sha256": policy.sha256,
        "workspace_root": str(workspace),
        "live_root": str(live),
        "required_scenarios": list(SCENARIOS),
        "live_runtime_started": False,
        "live_bytes_mutated": False,
    }


def run_failure_campaign(
    policy: FailureCampaignPolicy,
    workspace_root: Path,
    *,
    live_root: Path,
    campaign_id: str,
    runtime_profile: DazRuntimeProfile,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Run all destructive-looking exercises against a new disposable fixture only."""
    workspace, live = _validate_isolation(workspace_root, live_root, campaign_id=campaign_id)
    if workspace.exists():
        if any(workspace.iterdir()):
            raise DazControlError(
                DazErrorCode.SCHEDULER_REFUSED,
                "failure campaign workspace is not empty",
                evidence_paths=(str(workspace),),
            )
    else:
        workspace.mkdir(parents=True)
    marker = workspace / "fixture_boundary.json"
    marker.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "campaign_id": campaign_id,
                "fixture_only": True,
                "live_root": str(live),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    scenarios = [
        _exercise_drive_loss(workspace),
        _exercise_db_corruption(workspace),
        _exercise_crash(workspace, runtime_profile),
        _exercise_popup(workspace, runtime_profile),
        _exercise_oom(workspace, policy),
    ]
    captured = _as_utc(captured_at)
    body = {
        "schema_version": "1.0.0",
        "campaign_id": campaign_id,
        "campaign_kind": "isolated_deterministic_fixture",
        "captured_at": captured.isoformat().replace("+00:00", "Z"),
        "policy_sha256": policy.sha256,
        "workspace_root": str(workspace),
        "live_root": str(live),
        "passed": all(row["passed"] for row in scenarios),
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
    }
    report = {**body, "report_sha256": hashlib.sha256(_canonical_bytes(body)).hexdigest()}
    _validate_report(report)
    report_path = workspace / "failure_campaign_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**report, "report_path": str(report_path)}


def build_oom_recovery_decision(
    policy: FailureCampaignPolicy,
    original_recipe: Mapping[str, Any],
    *,
    completed_lower_cost_retries: int,
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    """Permit one bounded retry while refusing semantic or renderer drift."""
    oom = policy.document["oom"]
    maximum = int(oom["maximum_lower_cost_retries"])
    if completed_lower_cost_retries < 0:
        raise DazControlError(DazErrorCode.CONFIG_INVALID, "OOM retry count cannot be negative")
    if completed_lower_cost_retries >= maximum:
        return {
            "action": str(oom["persistent_failure_action"]),
            "reason": "oom_retry_budget_exhausted",
            "retry_recipe": None,
            "completed_lower_cost_retries": completed_lower_cost_retries,
        }
    allowed = set(oom["allowed_override_fields"])
    if not overrides or not set(overrides).issubset(allowed):
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID, "OOM retry overrides exceed the lower-cost allowlist"
        )
    retry = copy.deepcopy(dict(original_recipe))
    payload = retry.get("payload")
    if not isinstance(payload, dict):
        raise DazControlError(DazErrorCode.CONFIG_INVALID, "OOM retry recipe payload is invalid")
    for field, value in overrides.items():
        prior = _field(original_recipe, f"payload.{field}")
        if (
            isinstance(prior, bool)
            or not isinstance(prior, int)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value >= prior
        ):
            raise DazControlError(
                DazErrorCode.CONFIG_INVALID,
                f"OOM retry override must be a positive integer lower than payload.{field}",
            )
        payload[field] = value
    changed = sorted(
        field
        for field in allowed
        if _field(original_recipe, f"payload.{field}") != _field(retry, f"payload.{field}")
    )
    if not changed:
        raise DazControlError(DazErrorCode.CONFIG_INVALID, "OOM retry must lower resource cost")
    for field in oom["protected_recipe_fields"]:
        if _field(original_recipe, str(field)) != _field(retry, str(field)):
            raise DazControlError(
                DazErrorCode.CONFIG_INVALID, f"OOM retry changed protected recipe field: {field}"
            )
    return {
        "action": "retry_lower_cost",
        "reason": "oom_first_failure_bounded_retry",
        "retry_recipe": retry,
        "changed_fields": [f"payload.{field}" for field in changed],
        "completed_lower_cost_retries": completed_lower_cost_retries,
    }


def _exercise_drive_loss(workspace: Path) -> dict[str, Any]:
    root = workspace / "drive_loss/fixture_drive"
    staged = root / "20_tmp/partial.bin"
    accepted = root / "14_scene_packages/accepted.bin"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"partial-not-authoritative")
    offline = root.with_name("fixture_drive.offline")
    os.replace(root, offline)
    refused = False
    reason = ""
    try:
        _guard_promotion(staged, accepted, required_root=root)
    except DazControlError as exc:
        refused = True
        reason = exc.reason
    finally:
        os.replace(offline, root)
    accepted_exists = accepted.exists()
    passed = refused and not accepted_exists and staged.exists()
    return {
        "scenario": "drive_loss",
        "passed": passed,
        "expected": {"action": "pause_and_drain", "artifact_promoted": False},
        "observed": {
            "promotion_refused": refused,
            "reason": reason,
            "artifact_promoted": accepted_exists,
            "partial_preserved_unaccepted": staged.exists(),
        },
        "evidence": [str(staged), str(workspace / "fixture_boundary.json")],
    }


def _exercise_db_corruption(workspace: Path) -> dict[str, Any]:
    root = workspace / "db_corruption"
    root.mkdir(parents=True)
    active = root / "queue.sqlite"
    snapshot = root / "queue.snapshot.sqlite"
    corrupt_original = root / "queue.corrupt.preserved.sqlite"
    restored = root / "queue.restored.sqlite"
    with sqlite3.connect(active) as connection:
        connection.execute(
            "CREATE TABLE accepted_artifacts(artifact_id TEXT PRIMARY KEY, sha256 TEXT)"
        )
        connection.execute("INSERT INTO accepted_artifacts VALUES ('artifact_a', ?)", ("a" * 64,))
    _sqlite_backup(active, snapshot)
    active.write_bytes(b"not-a-sqlite-database")
    shutil.copyfile(active, corrupt_original)
    corrupt_integrity = _sqlite_integrity(active)
    _sqlite_backup(snapshot, restored)
    restored_integrity = _sqlite_integrity(restored)
    with sqlite3.connect(restored) as connection:
        rows = list(connection.execute("SELECT artifact_id,sha256 FROM accepted_artifacts"))
    passed = (
        corrupt_integrity != "ok"
        and restored_integrity == "ok"
        and rows == [("artifact_a", "a" * 64)]
        and active.read_bytes() == corrupt_original.read_bytes()
        and restored.resolve() != active.resolve()
    )
    return {
        "scenario": "db_corruption",
        "passed": passed,
        "expected": {
            "corruption_detected": True,
            "corrupt_original_preserved": True,
            "restore_to_new_path": True,
            "duplicate_acceptance": False,
        },
        "observed": {
            "corrupt_integrity": corrupt_integrity,
            "restored_integrity": restored_integrity,
            "corrupt_original_preserved": active.read_bytes() == corrupt_original.read_bytes(),
            "restored_to_new_path": restored.resolve() != active.resolve(),
            "accepted_row_count": len(rows),
            "accepted_ids_unique": len(rows) == len({row[0] for row in rows}),
        },
        "evidence": [str(corrupt_original), str(snapshot), str(restored)],
    }


def _exercise_crash(workspace: Path, profile: DazRuntimeProfile) -> dict[str, Any]:
    recipe = _fixture_recipe("job_failure_crash")
    files = prepare_job_files(workspace / "crash/jobs", recipe["job_id"])
    files.partial_result.write_text('{"state":"rendering"}\n', encoding="utf-8")
    process = _FakeProcess(31001, 137)
    outcome = _watch_process(
        process,
        profile=profile,
        files=files,
        recipe=recipe,
        allowed_artifact_roots=(workspace,),
        timeout_seconds=60,
        started_monotonic=0.0,
        popup_detector=lambda _pid, _patterns: None,
    )
    accepted = files.job_directory / "accepted.json"
    evidence_path = files.job_directory / "crash_decision.json"
    evidence_path.write_text(
        json.dumps(
            {
                "status": outcome.status,
                "reason": outcome.reason,
                "exit_code": outcome.exit_code,
                "artifact_promoted": accepted.exists(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    passed = (
        outcome.status == "failed"
        and outcome.reason == "process_exited_without_terminal_result"
        and files.partial_result.exists()
        and not accepted.exists()
    )
    return {
        "scenario": "crash",
        "passed": passed,
        "expected": {"terminal_state": "failed", "artifact_promoted": False},
        "observed": {
            "status": outcome.status,
            "reason": outcome.reason,
            "exit_code": outcome.exit_code,
            "partial_preserved_unaccepted": files.partial_result.exists(),
            "artifact_promoted": accepted.exists(),
        },
        "evidence": [str(files.partial_result), str(evidence_path)],
    }


def _exercise_popup(workspace: Path, profile: DazRuntimeProfile) -> dict[str, Any]:
    recipe = _fixture_recipe("job_failure_popup")
    files = prepare_job_files(workspace / "popup/jobs", recipe["job_id"])
    files.partial_result.write_text('{"state":"loading"}\n', encoding="utf-8")
    process = _FakeProcess(31002, None)
    terminated: list[int] = []

    def terminate(candidate: _FakeProcess) -> None:
        terminated.append(candidate.pid)
        candidate.exit_code = -9

    outcome = _watch_process(
        process,
        profile=profile,
        files=files,
        recipe=recipe,
        allowed_artifact_roots=(workspace,),
        timeout_seconds=60,
        started_monotonic=0.0,
        popup_detector=lambda pid, _patterns: WindowObservation(pid, "Missing File", "#32770"),
        process_terminator=terminate,
    )
    watchdog = json.loads(files.watchdog_evidence.read_text(encoding="utf-8"))
    accepted = files.job_directory / "accepted.json"
    passed = (
        outcome.status == "quarantined"
        and outcome.reason == "dialog_detected"
        and terminated == [process.pid]
        and watchdog["action"] == "process_tree_terminated_without_ui_input"
        and not accepted.exists()
    )
    return {
        "scenario": "popup",
        "passed": passed,
        "expected": {
            "terminal_state": "quarantined",
            "process_tree_terminated": True,
            "ui_input_sent": False,
            "artifact_promoted": False,
        },
        "observed": {
            "status": outcome.status,
            "reason": outcome.reason,
            "terminated_pids": terminated,
            "watchdog_action": watchdog["action"],
            "ui_input_sent": False,
            "artifact_promoted": accepted.exists(),
        },
        "evidence": [str(files.watchdog_evidence), str(files.partial_result)],
    }


def _exercise_oom(workspace: Path, policy: FailureCampaignPolicy) -> dict[str, Any]:
    recipe = _fixture_recipe("job_failure_oom", operation="render_scene")
    first = build_oom_recovery_decision(
        policy,
        recipe,
        completed_lower_cost_retries=0,
        overrides={"render_samples": 32, "tile_size": 128},
    )
    second = build_oom_recovery_decision(
        policy,
        first["retry_recipe"],
        completed_lower_cost_retries=1,
        overrides={"render_samples": 16},
    )
    protected = policy.document["oom"]["protected_recipe_fields"]
    unchanged = all(
        _field(recipe, str(field)) == _field(first["retry_recipe"], str(field))
        for field in protected
    )
    evidence_path = workspace / "oom/decision.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps({"first_failure": first, "persistent_failure": second}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    passed = (
        first["action"] == "retry_lower_cost"
        and second["action"] == "quarantine"
        and unchanged
        and first["changed_fields"] == ["payload.render_samples", "payload.tile_size"]
    )
    return {
        "scenario": "oom",
        "passed": passed,
        "expected": {
            "lower_cost_retry_count": 1,
            "persistent_failure_action": "quarantine",
            "semantic_fields_unchanged": True,
        },
        "observed": {
            "first_action": first["action"],
            "second_action": second["action"],
            "changed_fields": first["changed_fields"],
            "protected_fields_unchanged": unchanged,
        },
        "evidence": [str(evidence_path)],
    }


def _guard_promotion(staged: Path, destination: Path, *, required_root: Path) -> None:
    root = Path(required_root)
    if not root.is_dir():
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "required storage root unavailable; pause and drain before acceptance",
            evidence_paths=(str(root),),
        )
    staged = Path(staged).resolve(strict=True)
    destination = Path(destination).resolve()
    resolved_root = root.resolve(strict=True)
    if not staged.is_relative_to(resolved_root) or not destination.is_relative_to(resolved_root):
        raise DazControlError(DazErrorCode.SCHEDULER_REFUSED, "artifact promotion escaped root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, destination)


def _validate_isolation(
    workspace_root: Path, live_root: Path, *, campaign_id: str
) -> tuple[Path, Path]:
    if not campaign_id.startswith("failure_campaign_"):
        raise DazControlError(DazErrorCode.CONFIG_INVALID, "failure campaign ID is invalid")
    workspace = Path(workspace_root).resolve()
    live = Path(live_root).resolve(strict=True)
    if workspace == live or workspace.is_relative_to(live) or live.is_relative_to(workspace):
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "failure campaign workspace must be outside the live DAZ root",
        )
    if workspace.parent == workspace:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED, "drive root cannot be a campaign workspace"
        )
    return workspace, live


def _fixture_recipe(job_id: str, operation: str = "runtime_probe") -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "job_id": job_id,
        "recipe_id": f"recipe_{job_id}",
        "created_at": "2026-07-19T00:00:00Z",
        "bundle_version": "1.0.0",
        "operation": operation,
        "requires_gpu": operation != "runtime_probe",
        "content_directories": ["fixture/content"],
        "payload": {
            "renderer": "iray",
            "annotation_width": 1024,
            "annotation_height": 1024,
            "ontology_id": "maskfactory_v1",
            "render_samples": 64,
            "tile_size": 256,
        },
    }


def _sqlite_backup(source: Path, target: Path) -> None:
    if target.exists():
        target.unlink()
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as source_db:
        with sqlite3.connect(target) as target_db:
            source_db.backup(target_db)


def _sqlite_integrity(path: Path) -> str:
    try:
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    except sqlite3.Error as exc:
        return f"error:{exc.__class__.__name__}"


def _field(document: Mapping[str, Any], dotted: str) -> Any:
    value: Any = document
    for component in dotted.split("."):
        if not isinstance(value, Mapping) or component not in value:
            return None
        value = value[component]
    return value


def _validate_report(report: Mapping[str, Any]) -> None:
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/daz_failure_campaign_report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(report), key=lambda item: list(item.path)
    )
    if errors:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"failure campaign report violates its closed schema: {errors[0].message}",
        )


def _as_utc(value: datetime | None) -> datetime:
    captured = value or datetime.now(UTC)
    if captured.tzinfo is None:
        raise DazControlError(DazErrorCode.CONFIG_INVALID, "campaign timestamp must be aware")
    return captured.astimezone(UTC)


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


__all__ = [
    "FailureCampaignPolicy",
    "SCENARIOS",
    "build_oom_recovery_decision",
    "load_failure_campaign_policy",
    "plan_failure_campaign",
    "run_failure_campaign",
]
