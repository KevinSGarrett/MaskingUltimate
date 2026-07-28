"""Execute the frozen adult holdout through the durable terminal-outcome queue."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .nude_batch_queue import NudeBatchQueue
from .nude_holdout_policy import validate_live_holdout_bindings
from .nude_record_qualification import qualify_input_terminal_record


class NudeHoldoutCheckpointError(RuntimeError):
    """The live holdout shard could not be checkpointed without drift."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def run_holdout_checkpoint_canary(
    *,
    policy_path: Path,
    shard_path: Path,
    split_mapping_path: Path,
    queue_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    binding_result = validate_live_holdout_bindings(
        policy, shard_path=shard_path, split_mapping_path=split_mapping_path
    )
    shard = json.loads(Path(shard_path).read_text(encoding="utf-8"))
    sample_ids = list(shard["ordered_sample_ids"])
    by_sample = {str(row["sample_id"]): row for row in shard["samples"]}
    wanted = set(sample_ids)
    split_rows: dict[str, dict[str, Any]] = {}
    with Path(split_mapping_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            sample_id = str(row.get("sample_id"))
            if sample_id in wanted:
                split_rows[sample_id] = row
    if set(split_rows) != wanted:
        raise NudeHoldoutCheckpointError("holdout split bindings incomplete")
    queue = NudeBatchQueue(queue_path)
    queue.seed(
        [
            {
                "platform": "local",
                "path": shard["batch_lane"] + ".0001.json",
                "lane": shard["batch_lane"],
                "self_sha256": shard["self_sha256"],
                "sample_count": shard["sample_count"],
            }
        ],
        platform="local",
    )
    initial = queue.summary(platform="local")
    replay_passed = initial["checkpointed_records"] == shard["sample_count"]
    if not replay_passed:
        lease = queue.claim(platform="local", owner="nude-holdout-checkpoint-canary")
        if lease is None or lease["shard_path"] != shard["batch_lane"] + ".0001.json":
            raise NudeHoldoutCheckpointError("expected holdout lease unavailable")
        outcomes = []
        for sample_index, sample_id in enumerate(sample_ids):
            source = by_sample[sample_id]
            split = split_rows[sample_id]
            receipt = qualify_input_terminal_record(
                {
                    "sample_id": sample_id,
                    "source_sha256": source["source_sha256"],
                    "source_role": source["source_role"],
                    "registry_sha256": policy["registry_sha256"],
                    "shard_sha256": shard["self_sha256"],
                    "outcome": "holdout",
                    "reasons": ["frozen_original_evaluation_holdout"],
                    "input_report_sha256": policy["policy_sha256"],
                    "holdout_policy_sha256": policy["policy_sha256"],
                    "split_group_id": split["split_group_id"],
                }
            )
            receipt["sample_index"] = sample_index
            outcomes.append(receipt)
        midpoint = len(outcomes) // 2
        first = queue.checkpoint(
            platform="local",
            shard_path=lease["shard_path"],
            lease_token=lease["lease_token"],
            outcomes=outcomes[:midpoint],
        )
        replay = queue.checkpoint(
            platform="local",
            shard_path=lease["shard_path"],
            lease_token=lease["lease_token"],
            outcomes=outcomes[:midpoint],
        )
        replay_passed = bool(replay.get("idempotent_replay")) and replay["inserted"] == 0
        final_checkpoint = queue.checkpoint(
            platform="local",
            shard_path=lease["shard_path"],
            lease_token=lease["lease_token"],
            outcomes=outcomes[midpoint:],
        )
        if first["next_sample_index"] != midpoint or not final_checkpoint["complete"]:
            raise NudeHoldoutCheckpointError("holdout checkpoint did not complete")
    summary = queue.summary(platform="local")
    if (
        summary["checkpointed_records"] != shard["sample_count"]
        or summary["states"] != {"complete": 1}
        or summary["outcomes"] != {"holdout": shard["sample_count"]}
        or not replay_passed
    ):
        raise NudeHoldoutCheckpointError("holdout queue reconciliation failed")
    with sqlite3.connect(queue_path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    report = {
        "schema_version": "maskfactory.nude_holdout_checkpoint.v1",
        "artifact_type": "adult_holdout_durable_queue_canary",
        "status": "PASS",
        "policy_sha256": policy["policy_sha256"],
        "binding_result": binding_result,
        "queue_summary": summary,
        "idempotent_replay_passed": replay_passed,
        "queue_file_sha256": hashlib.sha256(Path(queue_path).read_bytes()).hexdigest(),
        "queue_path": str(Path(queue_path).resolve()),
        "authority": {
            "training_eligible": False,
            "critic_calibration_eligible": False,
            "mask_generated": False,
            "production_mask_authority": False,
        },
    }
    report["self_sha256"] = _canonical_sha256(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


__all__ = ["NudeHoldoutCheckpointError", "run_holdout_checkpoint_canary"]
