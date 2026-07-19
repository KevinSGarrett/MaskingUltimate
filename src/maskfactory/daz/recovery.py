from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from jsonschema import Draft202012Validator

from .control import STATE_SCHEMA_VERSION, DazControlError, DazErrorCode
from .policy import DazConfiguration

RETENTION_TO_RECOVERY_TIER = {
    "R0": "A",
    "R1": "B",
    "R2": "B",
    "R3": "C",
    "R4": "C",
    "R5": "C",
    "R6": "C",
    "R7": "C",
}


@dataclass(frozen=True)
class RecoveryPolicy:
    document: Mapping[str, Any]
    sha256: str


def load_recovery_policy(path: Path) -> RecoveryPolicy:
    path = Path(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        schema_path = Path(__file__).parents[1] / "schemas" / "daz_recovery.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"recovery policy is unreadable: {exc}",
            evidence_paths=(str(path),),
        ) from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.path)
    )
    if errors:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"recovery policy violates its closed schema: {errors[0].message}",
        )
    return RecoveryPolicy(document, hashlib.sha256(_canonical_bytes(document)).hexdigest())


def evaluate_recovery_matrix(
    policy: RecoveryPolicy,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Fail closed unless every artifact has a permitted, evidenced recovery path."""
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    blockers: list[dict[str, str]] = []
    for record in records:
        artifact_id = str(record.get("artifact_id", ""))
        if not artifact_id or artifact_id in seen:
            raise DazControlError(
                DazErrorCode.CONFIG_INVALID, "recovery artifact IDs must be non-empty and unique"
            )
        seen.add(artifact_id)
        tier = str(record.get("tier", ""))
        strategy = str(record.get("strategy", ""))
        artifact_type = str(record.get("artifact_type", ""))
        if not artifact_type:
            raise DazControlError(
                DazErrorCode.CONFIG_INVALID, f"recovery artifact type missing for {artifact_id}"
            )
        if not isinstance(record.get("referenced"), bool):
            raise DazControlError(
                DazErrorCode.CONFIG_INVALID, f"recovery reference flag invalid for {artifact_id}"
            )
        referenced = record.get("referenced") is True
        reason = _block_reason(policy, record, tier, strategy, artifact_type, referenced)
        row = {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "tier": tier,
            "strategy": strategy,
            "referenced": referenced,
            "bytes": _non_negative_integer(record.get("bytes"), artifact_id),
            "content_sha256": _sha256_field(record.get("content_sha256"), artifact_id),
            "recoverable": reason is None,
            "block_reason": reason,
        }
        normalized.append(row)
        if reason is not None:
            blockers.append({"artifact_id": artifact_id, "reason": reason})
    normalized.sort(key=lambda row: row["artifact_id"])
    body = {
        "schema_version": "1.0.0",
        "policy_sha256": policy.sha256,
        "recoverable": not blockers,
        "record_count": len(normalized),
        "backup_bytes": sum(row["bytes"] for row in normalized if row["strategy"] == "backup"),
        "optional_bulk_bytes": sum(row["bytes"] for row in normalized if row["tier"] == "C"),
        "records": normalized,
        "blockers": blockers,
    }
    return {**body, "matrix_sha256": hashlib.sha256(_canonical_bytes(body)).hexdigest()}


def build_recovery_records_from_state(configuration: DazConfiguration) -> list[dict[str, Any]]:
    """Read exact active artifact/package state and verify file-backed bytes fail-closed."""
    database = configuration.paths.state_database
    try:
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if schema_version != STATE_SCHEMA_VERSION:
            raise DazControlError(
                DazErrorCode.STATE_DATABASE_INVALID,
                f"recovery state schema {schema_version} requires migration to {STATE_SCHEMA_VERSION}",
                evidence_paths=(str(database),),
            )
        artifacts = connection.execute(
            "SELECT artifact_id,path,retention_class,bytes,content_sha256,"
            "protected_reference_count,payload_json FROM retention_artifacts "
            "WHERE state='active' ORDER BY artifact_id"
        ).fetchall()
        packages = connection.execute(
            "SELECT p.package_id,p.payload_json,p.state,"
            "EXISTS(SELECT 1 FROM dataset_membership d WHERE d.package_id=p.package_id) "
            "FROM package_exports p ORDER BY p.package_id"
        ).fetchall()
    except DazControlError:
        raise
    except sqlite3.Error as exc:
        raise DazControlError(
            DazErrorCode.STATE_DATABASE_INVALID,
            f"recovery state read failed: {exc}",
            evidence_paths=(str(database),),
        ) from exc
    finally:
        if "connection" in locals():
            connection.close()
    records: list[dict[str, Any]] = []
    root = configuration.paths.root.resolve(strict=True)
    for row in artifacts:
        artifact_id = str(row[0])
        try:
            path = Path(str(row[1])).resolve(strict=True)
        except OSError as exc:
            raise DazControlError(
                DazErrorCode.STATE_DATABASE_INVALID,
                "recovery artifact file is missing",
                entity_ids=(artifact_id,),
            ) from exc
        if not path.is_relative_to(root) or path.is_symlink() or not path.is_file():
            raise DazControlError(
                DazErrorCode.STATE_DATABASE_INVALID,
                "recovery artifact path is unsafe",
                entity_ids=(artifact_id,),
            )
        expected_bytes = int(row[3])
        expected_hash = str(row[4])
        if path.stat().st_size != expected_bytes or _sha256_file(path) != expected_hash:
            raise DazControlError(
                DazErrorCode.STATE_DATABASE_INVALID,
                "recovery artifact bytes drifted",
                entity_ids=(artifact_id,),
            )
        try:
            payload = json.loads(str(row[6]))
        except json.JSONDecodeError as exc:
            raise DazControlError(
                DazErrorCode.STATE_DATABASE_INVALID,
                "recovery artifact payload is invalid",
                entity_ids=(artifact_id,),
            ) from exc
        retention_class = str(row[2])
        tier = RETENTION_TO_RECOVERY_TIER.get(retention_class, "")
        strategy = str(payload.get("recovery_strategy", "backup"))
        record = {
            "artifact_id": f"retention:{artifact_id}",
            "artifact_type": str(payload.get("artifact_type", "file_artifact")),
            "tier": tier,
            "strategy": strategy,
            "referenced": int(row[5]) > 0,
            "bytes": expected_bytes,
            "content_sha256": expected_hash,
        }
        for field in ("source_sha256", "rebuild_recipe_id", "toolchain_sha256"):
            if field in payload:
                record[field] = payload[field]
        records.append(record)
    for row in packages:
        package_id = str(row[0])
        payload_text = str(row[1])
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise DazControlError(
                DazErrorCode.STATE_DATABASE_INVALID,
                "package metadata payload is invalid",
                entity_ids=(package_id,),
            ) from exc
        canonical = _canonical_bytes(payload)
        records.append(
            {
                "artifact_id": f"package:{package_id}",
                "artifact_type": "package_metadata",
                "tier": "A",
                "strategy": "backup",
                "referenced": bool(row[3]) or str(row[2]) in {"accepted", "active"},
                "bytes": len(canonical),
                "content_sha256": hashlib.sha256(canonical).hexdigest(),
            }
        )
    return sorted(records, key=lambda record: str(record["artifact_id"]))


def publish_recovery_matrix(matrix: Mapping[str, Any], output: Path) -> dict[str, Any]:
    """Publish one immutable matrix; identical publication is idempotent."""
    expected = str(matrix.get("matrix_sha256", ""))
    body = {key: value for key, value in matrix.items() if key != "matrix_sha256"}
    if len(expected) != 64 or hashlib.sha256(_canonical_bytes(body)).hexdigest() != expected:
        raise DazControlError(DazErrorCode.CONFIG_INVALID, "recovery matrix seal mismatch")
    path = Path(output)
    payload = json.dumps(dict(matrix), indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return {"published": False, "path": str(path), "matrix_sha256": expected}
        raise DazControlError(
            DazErrorCode.SCHEDULER_REFUSED, "recovery matrix output already exists with drift"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"published": True, "path": str(path), "matrix_sha256": expected}


def load_recovery_matrix(path: Path, *, require_recoverable: bool = True) -> dict[str, Any]:
    """Load a published matrix and verify its self-seal and recovery verdict."""
    source = Path(path)
    try:
        matrix = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID,
            f"recovery matrix is unreadable: {exc}",
            evidence_paths=(str(source),),
        ) from exc
    if not isinstance(matrix, dict):
        raise DazControlError(DazErrorCode.CONFIG_INVALID, "recovery matrix must be an object")
    expected = str(matrix.get("matrix_sha256", ""))
    body = {key: value for key, value in matrix.items() if key != "matrix_sha256"}
    if len(expected) != 64 or hashlib.sha256(_canonical_bytes(body)).hexdigest() != expected:
        raise DazControlError(DazErrorCode.CONFIG_INVALID, "recovery matrix seal mismatch")
    if require_recoverable and matrix.get("recoverable") is not True:
        raise DazControlError(DazErrorCode.SCHEDULER_REFUSED, "recovery matrix is blocked")
    return matrix


def _block_reason(
    policy: RecoveryPolicy,
    record: Mapping[str, Any],
    tier: str,
    strategy: str,
    artifact_type: str,
    referenced: bool,
) -> str | None:
    tiers = policy.document["tiers"]
    if tier not in tiers:
        return "unknown_tier"
    if artifact_type == "package_metadata" and tier != policy.document["package_metadata_tier"]:
        return "package_metadata_not_tier_a"
    tier_policy = tiers[tier]
    if strategy not in tier_policy["allowed_strategies"]:
        return "strategy_not_allowed_for_tier"
    if referenced and tier_policy["referenced_requires_backup"] and strategy != "backup":
        return "referenced_authority_requires_backup"
    if strategy in {"rebuild", "omit"}:
        for field in policy.document["rebuild_requires"]:
            value = record.get(field)
            if field.endswith("sha256"):
                if not _is_sha256(value):
                    return f"missing_{field}"
            elif not isinstance(value, str) or not value.strip():
                return f"missing_{field}"
    return None


def _non_negative_integer(value: Any, artifact_id: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID, f"recovery bytes invalid for {artifact_id}"
        )
    return value


def _sha256_field(value: Any, artifact_id: str) -> str:
    if not _is_sha256(value):
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID, f"content hash invalid for {artifact_id}"
        )
    return value


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "RETENTION_TO_RECOVERY_TIER",
    "RecoveryPolicy",
    "build_recovery_records_from_state",
    "evaluate_recovery_matrix",
    "load_recovery_policy",
    "load_recovery_matrix",
    "publish_recovery_matrix",
]
