"""Focused closure checks for the canonical frozen-holdout policy."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from maskfactory.nude_holdout_policy import (
    NudeHoldoutPolicyError,
    policy_sha256,
    validate_holdout_policy,
    validate_live_holdout_bindings,
)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _write_fixture(tmp_path: Path) -> tuple[dict[str, object], Path, Path]:
    sample_ids = ["sample-a", "sample-b"]
    samples = [
        {
            "sample_id": "sample-a",
            "source_role": "bbox_evaluation_only",
            "source_sha256": "a" * 64,
        },
        {
            "sample_id": "sample-b",
            "source_role": "bbox_evaluation_only",
            "source_sha256": "b" * 64,
        },
    ]
    descriptor = {
        "batch_lane": "bbox_evaluation_only",
        "sample_count": 2,
        "ordered_sample_ids": sample_ids,
        "samples": samples,
    }
    descriptor["self_sha256"] = _canonical_sha256(descriptor)
    shard_path = tmp_path / "holdout_shard.json"
    shard_path.write_text(json.dumps(descriptor, sort_keys=True), encoding="utf-8")
    split_rows = [
        {
            "sample_id": "sample-a",
            "split_group_id": "group-a",
            "source_role": "bbox_evaluation_only",
            "assigned_partition": "holdout",
            "source_sha256": "a" * 64,
        },
        {
            "sample_id": "sample-b",
            "split_group_id": "group-b",
            "source_role": "bbox_evaluation_only",
            "assigned_partition": "holdout",
            "source_sha256": "b" * 64,
        },
    ]
    split_path = tmp_path / "split_mapping.jsonl"
    split_path.write_text(
        "".join(f"{json.dumps(row, sort_keys=True)}\n" for row in split_rows), encoding="utf-8"
    )
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
        "policy_id": "closure-fixture",
        "status": "frozen_before_first_evaluation",
        "registry_sha256": "1" * 64,
        "shard_index_sha256": "2" * 64,
        "dataset_id": "fixture",
        "source_role": "bbox_evaluation_only",
        "assigned_partition": "holdout",
        "sample_count": 2,
        "split_group_count": 2,
        "ordered_sample_ids_sha256": _canonical_sha256(sample_ids),
        "source_bindings_sha256": _canonical_sha256(bindings),
        "shard_descriptor_sha256": descriptor["self_sha256"],
        "shard_file_sha256": hashlib.sha256(shard_path.read_bytes()).hexdigest(),
        "split_mapping_file_sha256": hashlib.sha256(split_path.read_bytes()).hexdigest(),
        "training_eligible": False,
        "critic_calibration_eligible": False,
        "first_evaluation_completed": False,
    }
    policy["policy_sha256"] = policy_sha256(policy)
    return policy, shard_path, split_path


def test_exact_full_product_policy_contract_is_frozen_and_nontraining() -> None:
    full_ref = "7d66ca27781d899a43eb644c0378bcf1478045a7"
    policy_path = Path("configs/nude_holdout_policy.json")
    module_path = Path("src/maskfactory/nude_holdout_policy.py")
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    validated = validate_holdout_policy(policy)
    assert validated["status"] == "frozen_before_first_evaluation"
    assert validated["training_eligible"] is False
    assert validated["critic_calibration_eligible"] is False
    assert (
        subprocess.check_output(
            ["git", "rev-parse", f"{full_ref}:configs/nude_holdout_policy.json"], text=True
        ).strip()
        == subprocess.check_output(["git", "hash-object", str(policy_path)], text=True).strip()
    )
    assert (
        subprocess.check_output(
            ["git", "rev-parse", f"{full_ref}:src/maskfactory/nude_holdout_policy.py"], text=True
        ).strip()
        == subprocess.check_output(["git", "hash-object", str(module_path)], text=True).strip()
    )


def test_live_frozen_holdout_requires_exact_source_and_group_bindings(tmp_path: Path) -> None:
    policy, shard_path, split_path = _write_fixture(tmp_path)
    result = validate_live_holdout_bindings(
        policy, shard_path=shard_path, split_mapping_path=split_path
    )
    assert result["status"] == "PASS_FROZEN_HOLDOUT_BINDINGS"
    assert result["cross_partition_group_count"] == 0


@pytest.mark.parametrize("field", ["training_eligible", "critic_calibration_eligible"])
def test_holdout_policy_rejects_training_or_critic_reuse(tmp_path: Path, field: str) -> None:
    policy, _, _ = _write_fixture(tmp_path)
    policy[field] = True
    policy["policy_sha256"] = policy_sha256(policy)
    with pytest.raises(NudeHoldoutPolicyError, match="holdout_.*must_be_false"):
        validate_holdout_policy(policy)


def test_live_binding_rejects_cross_partition_related_group(tmp_path: Path) -> None:
    policy, shard_path, split_path = _write_fixture(tmp_path)
    extra = {
        "sample_id": "outside-sample",
        "split_group_id": "group-a",
        "source_role": "bbox_evaluation_only",
        "assigned_partition": "training",
        "source_sha256": "c" * 64,
    }
    split_path.write_text(
        split_path.read_text(encoding="utf-8") + json.dumps(extra) + "\n", encoding="utf-8"
    )
    policy["split_mapping_file_sha256"] = hashlib.sha256(split_path.read_bytes()).hexdigest()
    policy["policy_sha256"] = policy_sha256(policy)
    with pytest.raises(NudeHoldoutPolicyError, match="holdout_group_partition_leak"):
        validate_live_holdout_bindings(policy, shard_path=shard_path, split_mapping_path=split_path)
