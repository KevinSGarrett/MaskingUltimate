from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from jsonschema import Draft202012Validator

from .control import DazControlError, DazErrorCode


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
                if not isinstance(value, str) or len(value) != 64:
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
    if not isinstance(value, str) or len(value) != 64:
        raise DazControlError(
            DazErrorCode.CONFIG_INVALID, f"content hash invalid for {artifact_id}"
        )
    return value


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = ["RecoveryPolicy", "evaluate_recovery_matrix", "load_recovery_policy"]
