from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from maskfactory.nude_holdout_policy import (
    NudeHoldoutPolicyError,
    policy_sha256,
    validate_holdout_policy,
    validate_live_holdout_bindings,
)


def _write_fixture(tmp_path: Path) -> tuple[dict[str, object], Path, Path]:
    samples = [
        {
            "sample_id": "one",
            "source_role": "bbox_evaluation_only",
            "source_sha256": "a" * 64,
        },
        {
            "sample_id": "two",
            "source_role": "bbox_evaluation_only",
            "source_sha256": "b" * 64,
        },
    ]
    shard = {
        "batch_lane": "bbox_evaluation_only",
        "sample_count": 2,
        "ordered_sample_ids": ["one", "two"],
        "samples": samples,
        "self_sha256": "c" * 64,
    }
    shard_path = tmp_path / "holdout.json"
    shard_path.write_text(json.dumps(shard), encoding="utf-8")
    split_rows = [
        {
            "sample_id": "one",
            "source_role": "bbox_evaluation_only",
            "source_sha256": "a" * 64,
            "assigned_partition": "holdout",
            "split_group_id": "group-one",
        },
        {
            "sample_id": "two",
            "source_role": "bbox_evaluation_only",
            "source_sha256": "b" * 64,
            "assigned_partition": "holdout",
            "split_group_id": "group-two",
        },
    ]
    split_path = tmp_path / "split.jsonl"
    split_path.write_text("".join(json.dumps(row) + "\n" for row in split_rows), encoding="utf-8")

    def canonical(value: object) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    bindings = [
        {
            "sample_id": row["sample_id"],
            "source_sha256": row["source_sha256"],
            "split_group_id": row["split_group_id"],
            "assigned_partition": "holdout",
        }
        for row in split_rows
    ]
    policy: dict[str, object] = {
        "schema_version": "maskfactory.nude_holdout_policy.v1",
        "policy_id": "fixture",
        "status": "frozen_before_first_evaluation",
        "registry_sha256": "d" * 64,
        "shard_index_sha256": "e" * 64,
        "dataset_id": "fixture",
        "source_role": "bbox_evaluation_only",
        "assigned_partition": "holdout",
        "sample_count": 2,
        "split_group_count": 2,
        "ordered_sample_ids_sha256": canonical(["one", "two"]),
        "source_bindings_sha256": canonical(bindings),
        "shard_descriptor_sha256": "c" * 64,
        "shard_file_sha256": hashlib.sha256(shard_path.read_bytes()).hexdigest(),
        "split_mapping_file_sha256": hashlib.sha256(split_path.read_bytes()).hexdigest(),
        "training_eligible": False,
        "critic_calibration_eligible": False,
        "first_evaluation_completed": False,
    }
    policy["policy_sha256"] = policy_sha256(policy)
    return policy, shard_path, split_path


def test_frozen_policy_validates_exact_live_bindings(tmp_path: Path) -> None:
    policy, shard, split = _write_fixture(tmp_path)
    assert validate_holdout_policy(policy)["sample_count"] == 2
    result = validate_live_holdout_bindings(policy, shard_path=shard, split_mapping_path=split)
    assert result["status"] == "PASS_FROZEN_HOLDOUT_BINDINGS"
    assert result["training_eligible"] is False


def test_holdout_cannot_be_training_or_critic_calibration(tmp_path: Path) -> None:
    policy, _, _ = _write_fixture(tmp_path)
    policy["training_eligible"] = True
    policy["policy_sha256"] = policy_sha256(policy)
    with pytest.raises(NudeHoldoutPolicyError, match="training_must_be_false"):
        validate_holdout_policy(policy)


def test_partition_or_source_drift_fails_closed(tmp_path: Path) -> None:
    policy, shard, split = _write_fixture(tmp_path)
    rows = [json.loads(line) for line in split.read_text().splitlines()]
    rows[0]["assigned_partition"] = "train"
    split.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    policy["split_mapping_file_sha256"] = hashlib.sha256(split.read_bytes()).hexdigest()
    policy["policy_sha256"] = policy_sha256(policy)
    with pytest.raises(NudeHoldoutPolicyError, match="partition_binding_drift"):
        validate_live_holdout_bindings(policy, shard_path=shard, split_mapping_path=split)


def test_related_group_member_cannot_remain_in_training(tmp_path: Path) -> None:
    policy, shard, split = _write_fixture(tmp_path)
    rows = [json.loads(line) for line in split.read_text().splitlines()]
    rows.append(
        {
            "sample_id": "correlated-train-copy",
            "source_role": "bbox_prompt_supervision",
            "source_sha256": "f" * 64,
            "assigned_partition": "train",
            "split_group_id": "group-one",
        }
    )
    split.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    policy["split_mapping_file_sha256"] = hashlib.sha256(split.read_bytes()).hexdigest()
    policy["policy_sha256"] = policy_sha256(policy)
    with pytest.raises(NudeHoldoutPolicyError, match="group_partition_leak"):
        validate_live_holdout_bindings(policy, shard_path=shard, split_mapping_path=split)
