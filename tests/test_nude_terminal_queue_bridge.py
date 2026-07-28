from __future__ import annotations

import json
from pathlib import Path

import pytest

from maskfactory.nude_batch_queue import NudeBatchQueue
from maskfactory.nude_terminal_queue_bridge import (
    NudeTerminalQueueBridgeError,
    bridge_terminal_batch_to_queue,
)


def _terminal_entry(index: int) -> dict:
    return {
        "record": {
            "sample_id": f"sample-{index}",
            "source_sha256": f"{index + 1:064x}",
            "source_role": "polygon_external_supervision",
            "registry_sha256": "a" * 64,
            "shard_sha256": "b" * 64,
            "outcome": "quarantined",
            "reasons": ["fixture_input_quarantine"],
            "input_report_sha256": "c" * 64,
        },
        "panels": None,
    }


def _bridge_entry(index: int) -> dict:
    return {"sample_index": index, "terminal_entry": _terminal_entry(index)}


def _queue(tmp_path: Path, *, count: int) -> tuple[NudeBatchQueue, dict]:
    queue = NudeBatchQueue(tmp_path / "queue.sqlite")
    queue.seed(
        [
            {
                "platform": "local",
                "path": "local/polygon.0001.json",
                "lane": "polygon_external_supervision",
                "self_sha256": "d" * 64,
                "sample_count": count,
            }
        ],
        platform="local",
    )
    lease = queue.claim(platform="local", owner="fixture", lease_seconds=3600)
    assert lease is not None
    return queue, lease


def test_bridge_checkpoints_all_valid_records_and_is_replayable(tmp_path: Path) -> None:
    queue, lease = _queue(tmp_path, count=2)
    entries = [_bridge_entry(0), _bridge_entry(1)]
    kwargs = {
        "source_manifest_sha256": "e" * 64,
        "output_root": tmp_path / "out",
        "queue": queue,
        "platform": "local",
        "shard_path": lease["shard_path"],
        "lease_token": lease["lease_token"],
    }
    first = bridge_terminal_batch_to_queue(entries, **kwargs)
    second = bridge_terminal_batch_to_queue(entries, **kwargs)
    assert first == second
    assert first["checkpoint_ready_prefix_count"] == 2
    assert first["processing_error_count"] == 0
    assert first["durable_checkpoint"] == {"next_sample_index": 2, "complete": True}
    assert queue.summary(platform="local")["outcomes"] == {"quarantined": 2}


def test_bridge_processes_later_records_but_checkpoints_only_prefix_before_error(
    tmp_path: Path,
) -> None:
    queue, lease = _queue(tmp_path, count=3)
    entries = [_bridge_entry(0), _bridge_entry(1), _bridge_entry(2)]
    entries[1]["terminal_entry"]["record"]["source_sha256"] = "invalid"
    result = bridge_terminal_batch_to_queue(
        entries,
        source_manifest_sha256="f" * 64,
        output_root=tmp_path / "out",
        queue=queue,
        platform="local",
        shard_path=lease["shard_path"],
        lease_token=lease["lease_token"],
    )
    assert result["qualified_artifact_count"] == 2
    assert result["processing_error_count"] == 1
    assert result["checkpoint_ready_prefix_count"] == 1
    assert result["first_error_ordinal"] == 1
    assert result["noncheckpointed_record_count"] == 2
    assert result["deferred_after_error_count"] == 1
    assert queue.summary(platform="local")["checkpointed_records"] == 1
    assert (tmp_path / "out/terminal/records/record_000002_quarantined.json").is_file()


def test_bridge_emits_zero_gap_coverage_after_checkpoint(tmp_path: Path) -> None:
    queue, lease = _queue(tmp_path, count=2)
    records_path = tmp_path / "registry.jsonl"
    registry_rows = [
        {
            "sample_id": f"sample-{index}",
            "source_sha256": f"{index + 1:064x}",
            "dataset_id": "dataset-a",
            "source_role": "polygon_external_supervision",
            "media_domain": "photo",
            "source_split": "train",
            "lineage_group": f"family-{index}",
            "source_labels": ["breast"],
        }
        for index in range(2)
    ]
    records_path.write_text(
        "".join(json.dumps(row) + "\n" for row in registry_rows), encoding="utf-8"
    )
    crosswalk = tmp_path / "crosswalk.json"
    crosswalk.write_text(
        json.dumps({"anatomy_aliases": {"breast": {}}, "scene_and_action_labels": {}}),
        encoding="utf-8",
    )
    result = bridge_terminal_batch_to_queue(
        [_bridge_entry(0), _bridge_entry(1)],
        source_manifest_sha256="1" * 64,
        output_root=tmp_path / "out",
        queue=queue,
        platform="local",
        shard_path=lease["shard_path"],
        lease_token=lease["lease_token"],
        registry_records=records_path,
        ontology_crosswalk=crosswalk,
    )
    coverage = json.loads((tmp_path / "out/dataset_coverage.json").read_text())
    assert result["coverage_status"] == "PASS"
    assert coverage["processed_record_count"] == 2
    assert coverage["remaining_record_count"] == 0
    assert coverage["quarantine_count"] == 2
    assert coverage["certification_yield"] == 0.0


def test_bridge_rejects_noncontiguous_indices_and_partial_coverage_inputs(tmp_path: Path) -> None:
    queue, lease = _queue(tmp_path, count=2)
    common = {
        "source_manifest_sha256": "2" * 64,
        "output_root": tmp_path / "out",
        "queue": queue,
        "platform": "local",
        "shard_path": lease["shard_path"],
        "lease_token": lease["lease_token"],
    }
    with pytest.raises(NudeTerminalQueueBridgeError, match="contiguous"):
        bridge_terminal_batch_to_queue([_bridge_entry(0), _bridge_entry(2)], **common)
    with pytest.raises(NudeTerminalQueueBridgeError, match="supplied_together"):
        bridge_terminal_batch_to_queue(
            [_bridge_entry(0)], registry_records=tmp_path / "registry.jsonl", **common
        )
