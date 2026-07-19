"""Fail-closed DAZ storage reservations and deterministic file retention."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from .control import (
    DazControlError,
    DazErrorCode,
    build_event,
    result_envelope,
    set_control_state,
)
from .policy import DazConfiguration

GIB = 1024**3
RETENTION_CLASSES = ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7")
PROTECTED_RETENTION_CLASSES = frozenset({"R0", "R1", "R2", "R7"})


@dataclass(frozen=True)
class RetentionClassPolicy:
    deletable: bool
    minimum_age_hours: int
    purge_priority: int


@dataclass(frozen=True)
class RetentionPolicy:
    document: Mapping[str, Any]
    sha256: str
    numerator: int
    denominator: int
    classes: Mapping[str, RetentionClassPolicy]


def load_retention_policy(path: Path) -> RetentionPolicy:
    """Load the closed checked-in R0-R7 policy without using mutable package validation state."""
    path = Path(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        schema_path = Path(__file__).parents[1] / "schemas" / "daz_retention.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"retention policy is unreadable: {exc}",
            evidence_paths=(str(path),),
        ) from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.path)
    )
    if errors:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"retention policy violates its closed schema: {errors[0].message}",
            evidence_paths=(str(path),),
        )
    classes = {
        name: RetentionClassPolicy(**document["classes"][name]) for name in RETENTION_CLASSES
    }
    canonical = _canonical_bytes(document)
    return RetentionPolicy(
        document=document,
        sha256=hashlib.sha256(canonical).hexdigest(),
        numerator=int(document["reservation_multiplier_numerator"]),
        denominator=int(document["reservation_multiplier_denominator"]),
        classes=classes,
    )


def required_reservation_bytes(
    profile_estimate_bytes: int,
    profile_p95_bytes: int,
    *,
    numerator: int = 5,
    denominator: int = 4,
) -> int:
    """Compute ceil(max(estimate,p95) * 1.25) with integer arithmetic."""
    values = (profile_estimate_bytes, profile_p95_bytes, numerator, denominator)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "storage reservation inputs must be integers",
        )
    if profile_estimate_bytes < 0 or profile_p95_bytes < 0 or numerator <= 0 or denominator <= 0:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "storage reservation inputs are invalid",
        )
    baseline = max(profile_estimate_bytes, profile_p95_bytes)
    if baseline == 0:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "storage reservation cannot be zero",
        )
    return (baseline * numerator + denominator - 1) // denominator


def storage_capacity_decision(
    configuration: DazConfiguration,
    *,
    observed_free_bytes: int,
    committed_bytes: int = 0,
    requested_bytes: int = 0,
) -> dict[str, Any]:
    """Return exact raw-floor action and post-commit reservation eligibility."""
    for value in (observed_free_bytes, committed_bytes, requested_bytes):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DazControlError(
                DazErrorCode.SCHEDULER_REFUSED,
                "storage capacity observations must be non-negative integers",
            )
    thresholds = configuration.paths.storage_thresholds_gib
    soft = int(thresholds.soft * GIB)
    hard = int(thresholds.hard * GIB)
    emergency = int(thresholds.emergency * GIB)
    if observed_free_bytes < emergency:
        state, action = "emergency", "stop"
    elif observed_free_bytes < hard:
        state, action = "hard", "drain"
    elif observed_free_bytes < soft:
        state, action = "soft", "pause"
    else:
        state, action = "healthy", "none"
    projected = observed_free_bytes - committed_bytes - requested_bytes
    reservation_allowed = state == "healthy" and projected >= soft
    return {
        "state": state,
        "action": action,
        "observed_free_bytes": observed_free_bytes,
        "committed_bytes": committed_bytes,
        "requested_bytes": requested_bytes,
        "projected_uncommitted_free_bytes": projected,
        "soft_floor_bytes": soft,
        "hard_floor_bytes": hard,
        "emergency_floor_bytes": emergency,
        "new_reservation_allowed": reservation_allowed,
    }


def apply_capacity_control(
    configuration: DazConfiguration,
    *,
    observed_free_bytes: int,
    reason: str,
    apply: bool,
) -> dict[str, Any]:
    """Map exact raw free-space floors to pause, drain, or controlled stop."""
    decision = storage_capacity_decision(configuration, observed_free_bytes=observed_free_bytes)
    action = str(decision["action"])
    if action == "none":
        return result_envelope(reason="storage_capacity_healthy", data={"decision": decision})
    from .control import read_control_state

    current = read_control_state(configuration)
    if action == "pause" and current["enabled"] is not True:
        return result_envelope(
            reason="storage_capacity_already_nonleasing",
            data={"decision": decision, "control": current, "apply": apply},
        )
    transition = set_control_state(
        configuration,
        action,
        reason=f"storage_{decision['state']}: {reason.strip()}",
        apply=apply,
    )
    return result_envelope(
        reason=f"storage_capacity_{action}_{'applied' if apply else 'planned'}",
        evidence_paths=tuple(transition["evidence_paths"]),
        data={"decision": decision, "transition": transition["data"]},
    )


def reserve_job_storage(
    configuration: DazConfiguration,
    policy: RetentionPolicy,
    *,
    job_id: str,
    profile_id: str,
    profile_estimate_bytes: int,
    profile_p95_bytes: int,
    observed_free_bytes: int,
    reservation_id: str | None = None,
    now: datetime | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Persist one capacity-backed reservation before the job becomes leaseable."""
    if not job_id or not profile_id:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED, "storage reservation identity is invalid"
        )
    required = required_reservation_bytes(
        profile_estimate_bytes,
        profile_p95_bytes,
        numerator=policy.numerator,
        denominator=policy.denominator,
    )
    captured = _as_utc(now)
    path = configuration.paths.state_database
    connection = _open_database(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        job = connection.execute("SELECT state FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if job is None or str(job[0]) not in {"pending", "retry"}:
            raise DazControlError(
                DazErrorCode.SCHEDULER_REFUSED,
                "storage reservation requires a pending or retry job",
                entity_ids=(job_id,),
            )
        committed = int(
            connection.execute(
                "SELECT coalesce(sum(required_bytes),0) FROM storage_reservations "
                "WHERE state IN ('active','consumed')"
            ).fetchone()[0]
        )
        decision = storage_capacity_decision(
            configuration,
            observed_free_bytes=observed_free_bytes,
            committed_bytes=committed,
            requested_bytes=required,
        )
        if not decision["new_reservation_allowed"]:
            raise DazControlError(
                DazErrorCode.SCHEDULER_REFUSED,
                f"storage reservation refused: {decision['state']}",
                entity_ids=(job_id,),
                retryable=True,
            )
        identity = reservation_id or f"reservation_{uuid.uuid4().hex}"
        payload = {
            "policy_sha256": policy.sha256,
            "observed_free_bytes": observed_free_bytes,
            "committed_before_bytes": committed,
            "projected_uncommitted_free_bytes": decision["projected_uncommitted_free_bytes"],
        }
        connection.execute(
            "INSERT INTO storage_reservations VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                identity,
                job_id,
                profile_id,
                profile_estimate_bytes,
                profile_p95_bytes,
                required,
                "active",
                _timestamp(captured),
                None,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            ),
        )
        event = build_event(
            "storage.reserved",
            "job",
            job_id,
            {"reservation_id": identity, "required_bytes": required, **payload},
            job_id=job_id,
            timestamp=_timestamp(captured),
            event_id=event_id,
        )
        _append_event(connection, event)
        connection.commit()
    except DazControlError:
        connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"storage reservation transaction failed: {exc}",
            retryable=True,
            evidence_paths=(str(path),),
        ) from exc
    finally:
        connection.close()
    return result_envelope(
        reason="storage_reserved",
        entity_ids=(job_id, identity),
        evidence_paths=(str(path),),
        data={
            "reservation_id": identity,
            "job_id": job_id,
            "profile_id": profile_id,
            "required_bytes": required,
            "state": "active",
            "capacity": decision,
        },
    )


def register_retention_artifact(
    configuration: DazConfiguration,
    *,
    artifact_id: str,
    path: Path,
    retention_class: str,
    created_at: datetime,
    protected_reference_count: int = 0,
    live_lease_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Register one immutable file observation under the governed DAZ root."""
    if not artifact_id or retention_class not in RETENTION_CLASSES or protected_reference_count < 0:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED, "retention artifact identity is invalid"
        )
    candidate = _safe_file(path, configuration.paths.root)
    size = candidate.stat().st_size
    digest = _sha256(candidate)
    captured = _as_utc(created_at)
    database = configuration.paths.state_database
    connection = _open_database(database)
    try:
        if live_lease_id is not None:
            exists = connection.execute(
                "SELECT 1 FROM leases WHERE lease_id=?", (live_lease_id,)
            ).fetchone()
            if exists is None:
                raise DazControlError(
                    DazErrorCode.SCHEDULER_REFUSED,
                    "retention artifact references a nonexistent live lease",
                    entity_ids=(artifact_id, live_lease_id),
                )
        connection.execute(
            "INSERT INTO retention_artifacts VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                artifact_id,
                str(candidate),
                retention_class,
                size,
                digest,
                _timestamp(captured),
                "active",
                protected_reference_count,
                live_lease_id,
                json.dumps(dict(payload or {}), sort_keys=True, separators=(",", ":")),
            ),
        )
        connection.commit()
    except DazControlError:
        connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"retention artifact registration failed: {exc}",
            entity_ids=(artifact_id,),
            evidence_paths=(str(database), str(candidate)),
        ) from exc
    finally:
        connection.close()
    return result_envelope(
        reason="retention_artifact_registered",
        entity_ids=(artifact_id,),
        evidence_paths=(str(candidate), str(database)),
        data={
            "path": str(candidate),
            "retention_class": retention_class,
            "bytes": size,
            "content_sha256": digest,
        },
    )


def build_retention_plan(
    configuration: DazConfiguration,
    policy: RetentionPolicy,
    *,
    observed_free_bytes: int,
    target_free_bytes: int,
    as_of: datetime,
    persist: bool,
) -> dict[str, Any]:
    """Build a deterministic deletion plan; planning never deletes or marks a file."""
    if target_free_bytes < observed_free_bytes or observed_free_bytes < 0:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED, "retention free-space target is invalid"
        )
    captured = _as_utc(as_of)
    required = target_free_bytes - observed_free_bytes
    database = configuration.paths.state_database
    connection = _open_database(database)
    try:
        active_leases = {str(row[0]) for row in connection.execute("SELECT lease_id FROM leases")}
        rows = connection.execute(
            "SELECT artifact_id,path,retention_class,bytes,content_sha256,created_at,"
            "protected_reference_count,live_lease_id FROM retention_artifacts "
            "WHERE state='active' ORDER BY artifact_id"
        ).fetchall()
    finally:
        connection.close()
    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for row in rows:
        artifact = {
            "artifact_id": str(row[0]),
            "path": str(row[1]),
            "retention_class": str(row[2]),
            "bytes": int(row[3]),
            "content_sha256": str(row[4]),
            "created_at": str(row[5]),
            "protected_reference_count": int(row[6]),
            "live_lease_id": str(row[7]) if row[7] is not None else None,
        }
        reason = _retention_exclusion(configuration, policy, artifact, captured, active_leases)
        if reason is None:
            class_policy = policy.classes[artifact["retention_class"]]
            artifact["purge_priority"] = class_policy.purge_priority
            candidates.append(artifact)
        else:
            excluded.append({"artifact_id": artifact["artifact_id"], "reason": reason})
    candidates.sort(
        key=lambda row: (
            int(row["purge_priority"]),
            str(row["created_at"]),
            str(row["path"]).casefold(),
            str(row["artifact_id"]),
        )
    )
    selected: list[dict[str, Any]] = []
    selected_bytes = 0
    for candidate in candidates:
        if selected_bytes >= required:
            break
        selected.append(
            {
                key: candidate[key]
                for key in (
                    "artifact_id",
                    "path",
                    "retention_class",
                    "bytes",
                    "content_sha256",
                )
            }
        )
        selected_bytes += int(candidate["bytes"])
    body = {
        "schema_version": "1.0.0",
        "artifact_type": "daz_retention_plan",
        "as_of": _timestamp(captured),
        "root": str(configuration.paths.root.resolve()),
        "policy_sha256": policy.sha256,
        "observed_free_bytes": observed_free_bytes,
        "target_free_bytes": target_free_bytes,
        "required_bytes": required,
        "selected_bytes": selected_bytes,
        "target_satisfied": selected_bytes >= required,
        "items": selected,
        "exclusions": sorted(excluded, key=lambda row: row["artifact_id"]),
    }
    plan_sha256 = hashlib.sha256(_canonical_bytes(body)).hexdigest()
    document = {
        **body,
        "plan_id": f"retplan_{plan_sha256[:24]}",
        "plan_sha256": plan_sha256,
    }
    if persist:
        _persist_retention_plan(configuration, document)
    return document


def apply_retention_plan(
    configuration: DazConfiguration,
    *,
    plan_id: str,
    dry_run: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Revalidate and then mark/delete exact immutable plan files under the DAZ root."""
    captured = _as_utc(now)
    database = configuration.paths.state_database
    connection = _open_database(database)
    try:
        plan_row = connection.execute(
            "SELECT status,payload_json FROM retention_plans WHERE plan_id=?", (plan_id,)
        ).fetchone()
        if plan_row is None:
            raise DazControlError(
                DazErrorCode.SCHEDULER_REFUSED,
                "retention plan does not exist",
                entity_ids=(plan_id,),
            )
        if str(plan_row[0]) != "planned":
            raise DazControlError(
                DazErrorCode.SCHEDULER_REFUSED,
                "retention plan is no longer applicable",
                entity_ids=(plan_id,),
            )
        document = json.loads(str(plan_row[1]))
        items = connection.execute(
            "SELECT i.artifact_id,i.path,i.retention_class,i.bytes,i.content_sha256,"
            "a.state,a.protected_reference_count,a.live_lease_id "
            "FROM retention_plan_items i JOIN retention_artifacts a "
            "ON a.artifact_id=i.artifact_id WHERE i.plan_id=? ORDER BY i.ordinal",
            (plan_id,),
        ).fetchall()
        active_leases = {str(row[0]) for row in connection.execute("SELECT lease_id FROM leases")}
    finally:
        connection.close()
    verified: list[dict[str, Any]] = []
    for row in items:
        artifact = {
            "artifact_id": str(row[0]),
            "path": str(row[1]),
            "retention_class": str(row[2]),
            "bytes": int(row[3]),
            "content_sha256": str(row[4]),
            "state": str(row[5]),
            "protected_reference_count": int(row[6]),
            "live_lease_id": str(row[7]) if row[7] is not None else None,
        }
        _verify_planned_artifact(configuration, artifact, active_leases)
        verified.append(artifact)
    if dry_run:
        return result_envelope(
            reason="retention_apply_dry_run",
            entity_ids=(plan_id,),
            evidence_paths=(str(database),),
            data={
                "dry_run": True,
                "applicable": True,
                "item_count": len(verified),
                "selected_bytes": int(document["selected_bytes"]),
            },
        )
    connection = _open_database(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for artifact in verified:
            connection.execute(
                "UPDATE retention_artifacts SET state='marked' "
                "WHERE artifact_id=? AND state='active'",
                (artifact["artifact_id"],),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise DazControlError(
                    DazErrorCode.SCHEDULER_REFUSED,
                    "retention artifact changed before mark",
                    entity_ids=(artifact["artifact_id"],),
                )
        connection.commit()
    except DazControlError:
        connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"retention mark transaction failed: {exc}",
            entity_ids=(plan_id,),
        ) from exc
    finally:
        connection.close()
    deleted: list[str] = []
    failures: list[dict[str, str]] = []
    for artifact in verified:
        try:
            _delete_marked_artifact(configuration, plan_id=plan_id, artifact=artifact)
            deleted.append(artifact["artifact_id"])
        except (DazControlError, OSError) as exc:
            failures.append({"artifact_id": artifact["artifact_id"], "reason": str(exc)})
    connection = _open_database(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for artifact_id in deleted:
            connection.execute(
                "UPDATE retention_artifacts SET state='deleted' "
                "WHERE artifact_id=? AND state='marked'",
                (artifact_id,),
            )
        status = "partial" if failures else "applied"
        connection.execute("UPDATE retention_plans SET status=? WHERE plan_id=?", (status, plan_id))
        event = build_event(
            "retention.plan_applied" if not failures else "retention.plan_partial",
            "retention_plan",
            plan_id,
            {
                "deleted_artifact_ids": deleted,
                "failures": failures,
                "artifact_promoted": False,
            },
            timestamp=_timestamp(captured),
            event_id=f"evt_{plan_id}_apply",
        )
        _append_event(connection, event)
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"retention outcome recording failed: {exc}",
            entity_ids=(plan_id,),
        ) from exc
    finally:
        connection.close()
    return result_envelope(
        code=0 if not failures else int(DazErrorCode.SCHEDULER_REFUSED),
        reason="retention_plan_applied" if not failures else "retention_plan_partial",
        entity_ids=(plan_id,),
        evidence_paths=(str(database),),
        data={
            "dry_run": False,
            "deleted_artifact_ids": deleted,
            "deleted_bytes": sum(
                int(row["bytes"]) for row in verified if row["artifact_id"] in deleted
            ),
            "failures": failures,
            "artifact_promoted": False,
        },
    )


def _delete_marked_artifact(
    configuration: DazConfiguration,
    *,
    plan_id: str,
    artifact: Mapping[str, Any],
) -> None:
    """Recheck mutable guards and unlink while preventing concurrent DB writers."""
    connection = _open_database(configuration.paths.state_database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT i.path,i.retention_class,i.bytes,i.content_sha256,"
            "a.state,a.protected_reference_count,a.live_lease_id "
            "FROM retention_plan_items i JOIN retention_artifacts a "
            "ON a.artifact_id=i.artifact_id "
            "WHERE i.plan_id=? AND i.artifact_id=?",
            (plan_id, artifact["artifact_id"]),
        ).fetchone()
        if row is None:
            raise DazControlError(
                DazErrorCode.SCHEDULER_REFUSED,
                "retention plan item disappeared before deletion",
                entity_ids=(plan_id, str(artifact["artifact_id"])),
            )
        current = {
            "artifact_id": str(artifact["artifact_id"]),
            "path": str(row[0]),
            "retention_class": str(row[1]),
            "bytes": int(row[2]),
            "content_sha256": str(row[3]),
            "state": str(row[4]),
            "protected_reference_count": int(row[5]),
            "live_lease_id": str(row[6]) if row[6] is not None else None,
        }
        for field in ("path", "retention_class", "bytes", "content_sha256"):
            if current[field] != artifact[field]:
                raise DazControlError(
                    DazErrorCode.SCHEDULER_REFUSED,
                    "retention artifact identity changed before deletion",
                    entity_ids=(str(artifact["artifact_id"]),),
                )
        active_leases = {
            str(lease_row[0]) for lease_row in connection.execute("SELECT lease_id FROM leases")
        }
        _verify_planned_artifact(configuration, current, active_leases)
        Path(current["path"]).unlink()
        connection.commit()
    except (DazControlError, OSError):
        connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"retention deletion guard failed: {exc}",
            entity_ids=(str(artifact["artifact_id"]),),
        ) from exc
    finally:
        connection.close()


def _persist_retention_plan(configuration: DazConfiguration, document: Mapping[str, Any]) -> None:
    database = configuration.paths.state_database
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
    connection = _open_database(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT payload_json FROM retention_plans WHERE plan_id=?", (document["plan_id"],)
        ).fetchone()
        if existing is not None:
            if str(existing[0]) != payload:
                raise DazControlError(
                    DazErrorCode.SCHEDULER_REFUSED,
                    "retention plan identity collision",
                    entity_ids=(str(document["plan_id"]),),
                )
            connection.rollback()
            return
        connection.execute(
            "INSERT INTO retention_plans VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                document["plan_id"],
                document["as_of"],
                document["root"],
                document["policy_sha256"],
                document["plan_sha256"],
                document["observed_free_bytes"],
                document["target_free_bytes"],
                document["selected_bytes"],
                "planned",
                payload,
            ),
        )
        for ordinal, item in enumerate(document["items"]):
            connection.execute(
                "INSERT INTO retention_plan_items VALUES (?,?,?,?,?,?,?,?)",
                (
                    document["plan_id"],
                    item["artifact_id"],
                    ordinal,
                    item["path"],
                    item["retention_class"],
                    item["bytes"],
                    item["content_sha256"],
                    "delete_file",
                ),
            )
        event = build_event(
            "retention.plan_created",
            "retention_plan",
            str(document["plan_id"]),
            {
                "plan_sha256": document["plan_sha256"],
                "selected_bytes": document["selected_bytes"],
                "target_satisfied": document["target_satisfied"],
            },
            timestamp=str(document["as_of"]),
            event_id=f"evt_{document['plan_id']}_created",
        )
        _append_event(connection, event)
        connection.commit()
    except DazControlError:
        connection.rollback()
        raise
    except sqlite3.Error as exc:
        connection.rollback()
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"retention plan persistence failed: {exc}",
            entity_ids=(str(document["plan_id"]),),
        ) from exc
    finally:
        connection.close()


def _retention_exclusion(
    configuration: DazConfiguration,
    policy: RetentionPolicy,
    artifact: Mapping[str, Any],
    as_of: datetime,
    active_leases: set[str],
) -> str | None:
    class_policy = policy.classes[str(artifact["retention_class"])]
    if not class_policy.deletable:
        return "protected_retention_class"
    if int(artifact["protected_reference_count"]) > 0:
        return "protected_reference"
    lease_id = artifact.get("live_lease_id")
    if lease_id is not None and str(lease_id) in active_leases:
        return "active_lease"
    created = _parse_timestamp(str(artifact["created_at"]))
    age_hours = (as_of - created).total_seconds() / 3600
    if age_hours < class_policy.minimum_age_hours:
        return "minimum_age"
    try:
        candidate = _safe_file(Path(str(artifact["path"])), configuration.paths.root)
    except DazControlError:
        return "unsafe_or_missing_file"
    if candidate.stat().st_size != int(artifact["bytes"]):
        return "size_drift"
    if _sha256(candidate) != str(artifact["content_sha256"]):
        return "hash_drift"
    return None


def _verify_planned_artifact(
    configuration: DazConfiguration,
    artifact: Mapping[str, Any],
    active_leases: set[str],
) -> None:
    if artifact["retention_class"] in PROTECTED_RETENTION_CLASSES:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "retention plan contains a protected class",
            entity_ids=(str(artifact["artifact_id"]),),
        )
    if artifact["state"] not in {"active", "marked"}:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "retention artifact is no longer active",
            entity_ids=(str(artifact["artifact_id"]),),
        )
    if int(artifact["protected_reference_count"]) > 0:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "retention artifact gained a protected reference",
            entity_ids=(str(artifact["artifact_id"]),),
        )
    lease_id = artifact.get("live_lease_id")
    if lease_id is not None and str(lease_id) in active_leases:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "retention artifact is protected by a live lease",
            entity_ids=(str(artifact["artifact_id"]),),
        )
    candidate = _safe_file(Path(str(artifact["path"])), configuration.paths.root)
    if candidate.stat().st_size != int(artifact["bytes"]):
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "retention artifact size drifted",
            entity_ids=(str(artifact["artifact_id"]),),
        )
    if _sha256(candidate) != str(artifact["content_sha256"]):
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            "retention artifact hash drifted",
            entity_ids=(str(artifact["artifact_id"]),),
        )


def _safe_file(path: Path, root: Path) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise DazControlError(
            DazErrorCode.PATH_ESCAPE, "retention path must be an existing non-symlink file"
        )
    resolved_root = Path(root).resolve(strict=True)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise DazControlError(
            DazErrorCode.PATH_ESCAPE, "retention path escapes the governed DAZ root"
        ) from exc
    return resolved


def _open_database(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(path, timeout=10)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
    except sqlite3.Error as exc:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED,
            f"storage database open failed: {exc}",
            retryable=True,
            evidence_paths=(str(path),),
        ) from exc


def _append_event(connection: sqlite3.Connection, event: Mapping[str, Any]) -> None:
    connection.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
        (
            event["event_id"],
            event["timestamp"],
            event["event_type"],
            event["entity_type"],
            event["entity_id"],
            event["job_id"],
            event["attempt"],
            json.dumps(event["data"], sort_keys=True, separators=(",", ":")),
        ),
    )


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_utc(value: datetime | None) -> datetime:
    captured = value or datetime.now(UTC)
    if captured.tzinfo is None:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED, "storage timestamps must be timezone-aware"
        )
    return captured.astimezone(UTC)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED, "retention timestamp is invalid"
        ) from exc
    return _as_utc(parsed)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "GIB",
    "PROTECTED_RETENTION_CLASSES",
    "RETENTION_CLASSES",
    "RetentionClassPolicy",
    "RetentionPolicy",
    "apply_capacity_control",
    "apply_retention_plan",
    "build_retention_plan",
    "load_retention_policy",
    "register_retention_artifact",
    "required_reservation_bytes",
    "reserve_job_storage",
    "storage_capacity_decision",
]
