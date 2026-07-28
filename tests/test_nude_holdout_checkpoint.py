from __future__ import annotations

import hashlib
import json
from pathlib import Path

from maskfactory.nude_holdout_checkpoint import run_holdout_checkpoint_canary
from maskfactory.nude_holdout_policy import policy_sha256


def test_holdout_canary_checkpoints_and_replays_without_training_authority(tmp_path: Path) -> None:
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
            "sample_id": sample["sample_id"],
            "source_role": "bbox_evaluation_only",
            "source_sha256": sample["source_sha256"],
            "assigned_partition": "holdout",
            "split_group_id": f"group-{sample['sample_id']}",
        }
        for sample in samples
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
    policy = {
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
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    queue_path = tmp_path / "queue.sqlite"
    report_path = tmp_path / "report.json"
    result = run_holdout_checkpoint_canary(
        policy_path=policy_path,
        shard_path=shard_path,
        split_mapping_path=split_path,
        queue_path=queue_path,
        report_path=report_path,
    )
    assert result["queue_summary"]["outcomes"] == {"holdout": 2}
    assert result["idempotent_replay_passed"] is True
    assert result["authority"]["training_eligible"] is False
    second = run_holdout_checkpoint_canary(
        policy_path=policy_path,
        shard_path=shard_path,
        split_mapping_path=split_path,
        queue_path=queue_path,
        report_path=report_path,
    )
    assert second["queue_summary"] == result["queue_summary"]
