"""STATIC binders for MF-P9-12 DAZ unattended ops / resilience contracts.

Fixture-bound only. Proves Tier-A backup/restore, scheduler pause/drain,
storage reservation policy, recovery matrix evaluation, and failure-campaign
policy binding. Never claims seven-day soak, live DAZ activation, doctor-green,
gold, Main-complete, or PRODUCTION_EVIDENCE_PASS.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..validation import validate_document
from . import (
    initialize_daz_root,
    initialize_state_database,
    load_control_configuration,
    load_failure_campaign_policy,
    plan_failure_campaign,
)
from .backup import (
    create_tier_a_backup,
    load_tier_a_backup_policy,
    restore_tier_a_test,
    verify_tier_a_backup,
)
from .control import set_control_state
from .recovery import evaluate_recovery_matrix, load_recovery_policy
from .scheduler import scheduler_status
from .storage import load_retention_policy, required_reservation_bytes

PROOF_TIER = "STATIC_PASS"
ARTIFACT_TYPE = "daz_ops_static_contracts_report"
AUTHORITY = "daz_ops_static_only_no_soak_no_live_daz_activation_no_gold_or_production_authority"
SCHEMA_VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "configs" / "daz"
BACKUP_POLICY = CONFIG / "backup.yaml"
RECOVERY_POLICY = CONFIG / "recovery.yaml"
RETENTION_POLICY = CONFIG / "retention.yaml"
FAILURE_CAMPAIGN_POLICY = CONFIG / "failure_campaign.yaml"
CAPTURED = datetime(2026, 7, 19, 18, 50, tzinfo=UTC)

TRACKER_ITEMS = (
    "MF-P9-12.01",
    "MF-P9-12.02",
    "MF-P9-12.03",
    "MF-P9-12.04",
    "MF-P9-12.05",
    "MF-P9-12.06",
    "MF-P9-12.08",
)

BACKUP_CHECKS = (
    "tier_a_policy_loads",
    "fixture_backup_create_verify",
    "fixture_clean_root_restore_bit_identical",
    "restore_refuses_overclaim_semantic_replay",
)
SCHEDULER_CHECKS = (
    "control_pause_drain_resume_cycle",
    "scheduler_status_reflects_drain",
    "leasing_blocked_while_paused",
)
STORAGE_CHECKS = (
    "retention_policy_loads",
    "reservation_bytes_deterministic",
    "soft_floor_bound",
)
RECOVERY_CHECKS = (
    "recovery_policy_loads",
    "fixture_recovery_matrix_evaluates",
    "non_recoverable_rows_fail_closed",
)
FAILURE_CAMPAIGN_CHECKS = (
    "failure_campaign_policy_loads",
    "fixture_campaign_plan_closed",
    "overclaim_soak_activation_refused",
)

HONEST_NON_CLAIMS = (
    "mf_p9_12_01_complete",
    "mf_p9_12_07_soak_complete",
    "mf_p9_12_09_activation_complete",
    "live_daz_execution",
    "seven_day_soak",
    "doctor_green",
    "gold",
    "Main-complete",
    "PRODUCTION_EVIDENCE_PASS",
)


class DazOpsStaticError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha(document: Mapping[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refuse_daz_ops_overclaim(document: Mapping[str, Any]) -> None:
    """Fail closed on soak / activation / live-DAZ / gold overclaims."""
    forbidden_true = (
        "mf_p9_12_01_complete",
        "mf_p9_12_07_soak_complete",
        "mf_p9_12_09_activation_complete",
        "live_daz_execution",
        "seven_day_soak",
        "doctor_green_claimed",
        "gold_claimed",
        "visual_qa_pass_claimed",
        "main_complete_claimed",
        "production_evidence_pass_claimed",
    )
    for key in forbidden_true:
        if document.get(key) is True:
            raise DazOpsStaticError(f"daz_ops_overclaim:{key}")


def _backup_source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    files = {
        "00_control/root_identity.json": b"control",
        "04_runtime/runtime_snapshots/runtime.json": b"runtime",
        "05_registry/snapshots/registry.json": b"registry",
        "07_mappings/genesis9/map.json": b"mapping",
        "09_generation/scene_recipes/recipe.json": b"recipe",
        "14_scene_packages/accepted/package.json": b"package",
        "15_datasets/manifests/lineage.json": b"lineage",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    queue = root / "10_queue" / "queue.sqlite"
    queue.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(queue) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE events(id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        connection.execute("INSERT INTO events VALUES ('event_a','immutable')")
    return root


def run_fixture_backup_restore(tmp_path: Path) -> dict[str, Any]:
    """Tier-A backup create/verify/clean-root restore with bit-identical payload."""
    if not BACKUP_POLICY.is_file():
        raise DazOpsStaticError("backup_policy_missing")
    policy = load_tier_a_backup_policy(BACKUP_POLICY)
    source = _backup_source(tmp_path)
    mapping_before = (source / "07_mappings/genesis9/map.json").read_bytes()
    manifest = create_tier_a_backup(
        source,
        tmp_path / "backups",
        policy,
        backup_id="backup_ops_static_a",
        captured_at=CAPTURED,
    )
    backup = Path(manifest["backup_path"])
    verification = verify_tier_a_backup(backup, policy)
    if verification.get("passed") is not True:
        raise DazOpsStaticError("backup_verify_failed")
    restored = restore_tier_a_test(backup, tmp_path / "restore", policy)
    if restored.get("passed") is not True:
        raise DazOpsStaticError("restore_failed")
    if restored.get("semantic_replay_executed") is not False:
        raise DazOpsStaticError("restore_semantic_replay_overclaim")
    if restored.get("lineage_query_executed") is not False:
        raise DazOpsStaticError("restore_lineage_overclaim")
    restored_mapping = (tmp_path / "restore/07_mappings/genesis9/map.json").read_bytes()
    if restored_mapping != mapping_before:
        raise DazOpsStaticError("restore_bytes_mismatch")
    return {
        "tier_a_policy_loads": True,
        "fixture_backup_create_verify": True,
        "fixture_clean_root_restore_bit_identical": True,
        "restore_refuses_overclaim_semantic_replay": True,
        "backup_policy_sha256": _file_sha(BACKUP_POLICY),
        "backup_id": manifest.get("backup_id"),
    }


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
    return configuration


def run_fixture_scheduler_control(tmp_path: Path) -> dict[str, Any]:
    """Pause → drain → resume control cycle with scheduler status honesty."""
    configuration = _fixture_configuration(tmp_path)
    set_control_state(
        configuration,
        "enable",
        reason="ops_static_enable",
        apply=True,
        free_gib=500.0,
    )
    set_control_state(configuration, "pause", reason="ops_static_pause", apply=True)
    paused = scheduler_status(configuration)
    if paused["data"]["control"]["paused"] is not True:
        raise DazOpsStaticError("pause_not_reflected")
    if paused["data"]["leasing_allowed"] is not False:
        raise DazOpsStaticError("leasing_allowed_while_paused")

    set_control_state(configuration, "drain", reason="ops_static_drain", apply=True)
    drained = scheduler_status(configuration)
    if drained["data"]["control"]["drain"] is not True:
        raise DazOpsStaticError("drain_not_reflected")
    if drained["data"]["leasing_allowed"] is not False:
        raise DazOpsStaticError("leasing_allowed_while_draining")

    set_control_state(
        configuration,
        "resume",
        reason="ops_static_resume",
        apply=True,
        free_gib=500.0,
    )
    resumed = scheduler_status(configuration)
    if resumed["data"]["control"]["paused"] is not False:
        raise DazOpsStaticError("resume_still_paused")
    if resumed["data"]["control"]["drain"] is not False:
        raise DazOpsStaticError("resume_still_draining")

    return {
        "control_pause_drain_resume_cycle": True,
        "scheduler_status_reflects_drain": True,
        "leasing_blocked_while_paused": True,
    }


def evaluate_storage_static_binder() -> dict[str, Any]:
    """Bind retention / reservation contracts without live F-drive fill/drain."""
    if not RETENTION_POLICY.is_file():
        raise DazOpsStaticError("retention_policy_missing")
    policy = load_retention_policy(RETENTION_POLICY)
    bytes_a = required_reservation_bytes(
        1_048_576,
        2_097_152,
        numerator=policy.numerator,
        denominator=policy.denominator,
    )
    bytes_b = required_reservation_bytes(
        1_048_576,
        2_097_152,
        numerator=policy.numerator,
        denominator=policy.denominator,
    )
    if bytes_a != bytes_b or bytes_a <= 0:
        raise DazOpsStaticError("reservation_bytes_nondeterministic")
    paths_doc = yaml.safe_load((CONFIG / "paths.yaml").read_text(encoding="utf-8"))
    thresholds = paths_doc.get("storage_thresholds_gib") or {}
    soft_floor = thresholds.get("soft")
    if soft_floor is None:
        raise DazOpsStaticError("soft_floor_unbound")
    if len(policy.classes) < 1:
        raise DazOpsStaticError("retention_classes_empty")
    return {
        "retention_policy_loads": True,
        "reservation_bytes_deterministic": True,
        "soft_floor_bound": True,
        "reservation_bytes": int(bytes_a),
        "soft_floor_gib": float(soft_floor),
        "retention_policy_sha256": _file_sha(RETENTION_POLICY),
        "retention_class_count": len(policy.classes),
    }


def evaluate_recovery_static_binder() -> dict[str, Any]:
    """Evaluate recovery matrix with recoverable + blocked fixture rows."""
    if not RECOVERY_POLICY.is_file():
        raise DazOpsStaticError("recovery_policy_missing")
    policy = load_recovery_policy(RECOVERY_POLICY)
    recoverable = evaluate_recovery_matrix(
        policy,
        [
            {
                "artifact_id": "control",
                "artifact_type": "package_metadata",
                "tier": "A",
                "strategy": "backup",
                "referenced": True,
                "bytes": 10,
                "content_sha256": "a" * 64,
            }
        ],
    )
    if recoverable.get("recoverable") is not True:
        raise DazOpsStaticError("recoverable_matrix_failed")

    blocked = evaluate_recovery_matrix(
        policy,
        [
            {
                "artifact_id": "orphan_blob",
                "artifact_type": "unknown_type",
                "tier": "Z",
                "strategy": "invented",
                "referenced": True,
                "bytes": 10,
                "content_sha256": "b" * 64,
            }
        ],
    )
    if blocked.get("recoverable") is not False or not blocked.get("blockers"):
        raise DazOpsStaticError("non_recoverable_rows_not_blocked")

    return {
        "recovery_policy_loads": True,
        "fixture_recovery_matrix_evaluates": True,
        "non_recoverable_rows_fail_closed": True,
        "recovery_policy_sha256": _file_sha(RECOVERY_POLICY),
        "recoverable_record_count": recoverable.get("record_count"),
        "blocked_count": len(blocked.get("blockers") or ()),
    }


def evaluate_failure_campaign_static_binder(tmp_path: Path) -> dict[str, Any]:
    """Bind failure-campaign policy and closed plan without soak/activation claims."""
    if not FAILURE_CAMPAIGN_POLICY.is_file():
        raise DazOpsStaticError("failure_campaign_policy_missing")
    policy = load_failure_campaign_policy(FAILURE_CAMPAIGN_POLICY)
    workspace = tmp_path / "campaign_workspace"
    live_root = tmp_path / "live_root_protected"
    live_root.mkdir(parents=True, exist_ok=True)
    (live_root / "marker.txt").write_text("protected", encoding="utf-8")
    plan = plan_failure_campaign(
        policy,
        workspace,
        live_root=live_root,
        campaign_id="failure_campaign_ops_static_v1",
    )
    if plan.get("live_runtime_started") is not False:
        raise DazOpsStaticError("campaign_live_runtime_overclaim")
    if plan.get("live_bytes_mutated") is not False:
        raise DazOpsStaticError("campaign_live_bytes_overclaim")
    if plan.get("apply") is not False:
        raise DazOpsStaticError("campaign_apply_overclaim")
    required = plan.get("required_scenarios") or []
    if not isinstance(required, list) or len(required) < 1:
        raise DazOpsStaticError("campaign_scenarios_empty")

    try:
        refuse_daz_ops_overclaim(
            {
                "mf_p9_12_07_soak_complete": True,
                "mf_p9_12_09_activation_complete": False,
            }
        )
        raise DazOpsStaticError("soak_overclaim_negative_passed")
    except DazOpsStaticError as exc:
        if "mf_p9_12_07_soak_complete" not in exc.reason:
            raise
        overclaim_refused = True

    return {
        "failure_campaign_policy_loads": True,
        "fixture_campaign_plan_closed": True,
        "overclaim_soak_activation_refused": overclaim_refused,
        "failure_campaign_policy_sha256": _file_sha(FAILURE_CAMPAIGN_POLICY),
        "required_scenario_count": len(required),
    }


def run_daz_ops_static_suite(*, workspace: Path | None = None) -> dict[str, Any]:
    """Execute MF-P9-12 STATIC binders and seal a schema-valid report."""
    storage = evaluate_storage_static_binder()
    recovery = evaluate_recovery_static_binder()

    if workspace is not None:
        tmp_root = Path(workspace)
        tmp_root.mkdir(parents=True, exist_ok=True)
        backup = run_fixture_backup_restore(tmp_root / "backup")
        scheduler = run_fixture_scheduler_control(tmp_root / "scheduler")
        failure = evaluate_failure_campaign_static_binder(tmp_root / "failure")
    else:
        with tempfile.TemporaryDirectory(
            prefix="mf_daz_ops_static_", ignore_cleanup_errors=True
        ) as tmp:
            tmp_root = Path(tmp)
            backup = run_fixture_backup_restore(tmp_root / "backup")
            scheduler = run_fixture_scheduler_control(tmp_root / "scheduler")
            failure = evaluate_failure_campaign_static_binder(tmp_root / "failure")

    backup_checks = {key: bool(backup[key]) for key in BACKUP_CHECKS}
    scheduler_checks = {key: bool(scheduler[key]) for key in SCHEDULER_CHECKS}
    storage_checks = {key: bool(storage[key]) for key in STORAGE_CHECKS}
    recovery_checks = {key: bool(recovery[key]) for key in RECOVERY_CHECKS}
    failure_checks = {key: bool(failure[key]) for key in FAILURE_CAMPAIGN_CHECKS}

    for name, checks in (
        ("backup", backup_checks),
        ("scheduler", scheduler_checks),
        ("storage", storage_checks),
        ("recovery", recovery_checks),
        ("failure", failure_checks),
    ):
        if not all(checks.values()):
            raise DazOpsStaticError(f"{name}_checks_failed")

    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "proof_tier": PROOF_TIER,
        "authority": AUTHORITY,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "items": list(TRACKER_ITEMS),
        "backup_checks": dict(sorted(backup_checks.items())),
        "scheduler_checks": dict(sorted(scheduler_checks.items())),
        "storage_checks": dict(sorted(storage_checks.items())),
        "recovery_checks": dict(sorted(recovery_checks.items())),
        "failure_campaign_checks": dict(sorted(failure_checks.items())),
        "checks": {
            "tier_a_backup_restore_binder": "pass",
            "scheduler_pause_drain_binder": "pass",
            "storage_reservation_binder": "pass",
            "recovery_matrix_binder": "pass",
            "failure_campaign_binder": "pass",
        },
        "mf_p9_12_01_complete": False,
        "mf_p9_12_07_soak_complete": False,
        "mf_p9_12_09_activation_complete": False,
        "live_daz_execution": False,
        "seven_day_soak": False,
        "doctor_green_claimed": False,
        "gold_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
        "honest_non_claims": list(HONEST_NON_CLAIMS),
        "bindings": {
            "backup_policy_sha256": backup["backup_policy_sha256"],
            "retention_policy_sha256": storage["retention_policy_sha256"],
            "recovery_policy_sha256": recovery["recovery_policy_sha256"],
            "failure_campaign_policy_sha256": failure["failure_campaign_policy_sha256"],
            "soft_floor_gib": storage["soft_floor_gib"],
            "reservation_bytes": storage["reservation_bytes"],
        },
        "implementation": {
            "module": "src/maskfactory/daz/ops_static_contracts.py",
            "configs": [
                "configs/daz/backup.yaml",
                "configs/daz/retention.yaml",
                "configs/daz/recovery.yaml",
                "configs/daz/failure_campaign.yaml",
            ],
            "tests": ["tests/test_daz_ops_static_contracts.py"],
        },
    }
    refuse_daz_ops_overclaim(draft)
    digest = _sha(draft)
    draft["report_id"] = f"dos_{digest[:24]}"
    draft["seal_sha256"] = digest
    draft["sha256"] = _sha({key: value for key, value in draft.items() if key != "sha256"})

    issues = validate_document(draft, "daz_ops_static_contracts_report")
    if issues:
        detail = "; ".join(
            f"{getattr(issue, 'pointer', None) or '/'}: {issue.message}" for issue in issues
        )
        raise DazOpsStaticError(f"schema_validation_failed:{detail}")
    return draft


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY",
    "BACKUP_CHECKS",
    "FAILURE_CAMPAIGN_CHECKS",
    "HONEST_NON_CLAIMS",
    "PROOF_TIER",
    "RECOVERY_CHECKS",
    "SCHEDULER_CHECKS",
    "SCHEMA_VERSION",
    "STORAGE_CHECKS",
    "TRACKER_ITEMS",
    "DazOpsStaticError",
    "evaluate_failure_campaign_static_binder",
    "evaluate_recovery_static_binder",
    "evaluate_storage_static_binder",
    "refuse_daz_ops_overclaim",
    "run_daz_ops_static_suite",
    "run_fixture_backup_restore",
    "run_fixture_scheduler_control",
]
