"""Frozen adult-corpus holdout policy and live source-binding validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

POLICY_KEYS = frozenset(
    {
        "schema_version",
        "policy_id",
        "status",
        "registry_sha256",
        "shard_index_sha256",
        "dataset_id",
        "source_role",
        "assigned_partition",
        "sample_count",
        "split_group_count",
        "ordered_sample_ids_sha256",
        "source_bindings_sha256",
        "shard_descriptor_sha256",
        "shard_file_sha256",
        "split_mapping_file_sha256",
        "training_eligible",
        "critic_calibration_eligible",
        "first_evaluation_completed",
        "policy_sha256",
    }
)


class NudeHoldoutPolicyError(ValueError):
    """The frozen holdout policy or its source bindings drifted."""


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise NudeHoldoutPolicyError(f"{field}_invalid")
    return value


def policy_sha256(policy: Mapping[str, Any]) -> str:
    return _canonical_sha256(
        {key: value for key, value in policy.items() if key != "policy_sha256"}
    )


def validate_holdout_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if set(policy) != POLICY_KEYS:
        raise NudeHoldoutPolicyError("holdout_policy_fields_invalid")
    if policy.get("schema_version") != "maskfactory.nude_holdout_policy.v1":
        raise NudeHoldoutPolicyError("holdout_policy_schema_invalid")
    if policy.get("status") != "frozen_before_first_evaluation":
        raise NudeHoldoutPolicyError("holdout_policy_status_invalid")
    if policy.get("source_role") != "bbox_evaluation_only":
        raise NudeHoldoutPolicyError("holdout_source_role_invalid")
    if policy.get("assigned_partition") != "holdout":
        raise NudeHoldoutPolicyError("holdout_partition_invalid")
    if policy.get("training_eligible") is not False:
        raise NudeHoldoutPolicyError("holdout_training_must_be_false")
    if policy.get("critic_calibration_eligible") is not False:
        raise NudeHoldoutPolicyError("holdout_critic_calibration_must_be_false")
    if policy.get("first_evaluation_completed") is not False:
        raise NudeHoldoutPolicyError("holdout_policy_not_frozen_before_evaluation")
    if not isinstance(policy.get("sample_count"), int) or policy["sample_count"] < 1:
        raise NudeHoldoutPolicyError("holdout_sample_count_invalid")
    if (
        not isinstance(policy.get("split_group_count"), int)
        or not 1 <= policy["split_group_count"] <= policy["sample_count"]
    ):
        raise NudeHoldoutPolicyError("holdout_split_group_count_invalid")
    for field in (
        "registry_sha256",
        "shard_index_sha256",
        "ordered_sample_ids_sha256",
        "source_bindings_sha256",
        "shard_descriptor_sha256",
        "shard_file_sha256",
        "split_mapping_file_sha256",
        "policy_sha256",
    ):
        _sha256(policy.get(field), field)
    if policy["policy_sha256"] != policy_sha256(policy):
        raise NudeHoldoutPolicyError("holdout_policy_hash_mismatch")
    return dict(policy)


def validate_live_holdout_bindings(
    policy: Mapping[str, Any], *, shard_path: Path, split_mapping_path: Path
) -> dict[str, Any]:
    """Prove the frozen sample/source/group set still matches live adopted evidence."""

    validated = validate_holdout_policy(policy)
    shard_raw = Path(shard_path).read_bytes()
    if hashlib.sha256(shard_raw).hexdigest() != validated["shard_file_sha256"]:
        raise NudeHoldoutPolicyError("holdout_shard_file_drift")
    try:
        shard = json.loads(shard_raw)
    except json.JSONDecodeError as exc:
        raise NudeHoldoutPolicyError("holdout_shard_json_invalid") from exc
    if (
        shard.get("batch_lane") != validated["source_role"]
        or shard.get("sample_count") != validated["sample_count"]
        or shard.get("self_sha256") != validated["shard_descriptor_sha256"]
    ):
        raise NudeHoldoutPolicyError("holdout_shard_descriptor_drift")
    sample_ids = shard.get("ordered_sample_ids")
    samples = shard.get("samples")
    if (
        not isinstance(sample_ids, list)
        or not isinstance(samples, list)
        or len(sample_ids) != validated["sample_count"]
        or len(samples) != validated["sample_count"]
        or len(set(sample_ids)) != len(sample_ids)
    ):
        raise NudeHoldoutPolicyError("holdout_shard_sample_set_invalid")
    if _canonical_sha256(sample_ids) != validated["ordered_sample_ids_sha256"]:
        raise NudeHoldoutPolicyError("holdout_ordered_sample_set_drift")
    by_sample = {str(row.get("sample_id")): row for row in samples if isinstance(row, Mapping)}
    if set(by_sample) != set(sample_ids):
        raise NudeHoldoutPolicyError("holdout_shard_rows_do_not_match_order")
    split_path = Path(split_mapping_path)
    if (
        hashlib.sha256(split_path.read_bytes()).hexdigest()
        != validated["split_mapping_file_sha256"]
    ):
        raise NudeHoldoutPolicyError("holdout_split_mapping_file_drift")
    wanted = set(sample_ids)
    split_rows: dict[str, Mapping[str, Any]] = {}
    group_partitions: dict[str, set[str]] = {}
    group_member_counts: dict[str, int] = {}
    with split_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise NudeHoldoutPolicyError(
                    f"holdout_split_mapping_json_invalid:{line_number}"
                ) from exc
            sample_id = str(row.get("sample_id"))
            group_id = str(row.get("split_group_id"))
            group_partitions.setdefault(group_id, set()).add(str(row.get("assigned_partition")))
            group_member_counts[group_id] = group_member_counts.get(group_id, 0) + 1
            if sample_id in wanted:
                if sample_id in split_rows:
                    raise NudeHoldoutPolicyError("holdout_split_mapping_duplicate")
                split_rows[sample_id] = row
    if set(split_rows) != wanted:
        raise NudeHoldoutPolicyError("holdout_split_mapping_incomplete")
    bindings = []
    groups = set()
    for sample_id in sample_ids:
        source = by_sample[sample_id]
        split = split_rows[sample_id]
        if (
            source.get("source_role") != "bbox_evaluation_only"
            or split.get("source_role") != "bbox_evaluation_only"
            or split.get("assigned_partition") != "holdout"
            or source.get("source_sha256") != split.get("source_sha256")
        ):
            raise NudeHoldoutPolicyError("holdout_source_or_partition_binding_drift")
        group_id = str(split.get("split_group_id"))
        groups.add(group_id)
        bindings.append(
            {
                "sample_id": sample_id,
                "source_sha256": source["source_sha256"],
                "split_group_id": group_id,
                "assigned_partition": "holdout",
            }
        )
    if len(groups) != validated["split_group_count"]:
        raise NudeHoldoutPolicyError("holdout_split_group_count_drift")
    leaking_groups = {
        group_id: sorted(group_partitions.get(group_id, set()))
        for group_id in groups
        if group_partitions.get(group_id, set()) != {"holdout"}
    }
    if leaking_groups:
        raise NudeHoldoutPolicyError("holdout_group_partition_leak")
    if _canonical_sha256(bindings) != validated["source_bindings_sha256"]:
        raise NudeHoldoutPolicyError("holdout_source_bindings_drift")
    return {
        "status": "PASS_FROZEN_HOLDOUT_BINDINGS",
        "policy_sha256": validated["policy_sha256"],
        "sample_count": len(sample_ids),
        "split_group_count": len(groups),
        "holdout_group_member_count": sum(group_member_counts[group_id] for group_id in groups),
        "cross_partition_group_count": 0,
        "training_eligible": False,
        "critic_calibration_eligible": False,
        "first_evaluation_completed": False,
    }


__all__ = [
    "NudeHoldoutPolicyError",
    "policy_sha256",
    "validate_holdout_policy",
    "validate_live_holdout_bindings",
]
