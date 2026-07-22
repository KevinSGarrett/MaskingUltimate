from __future__ import annotations

import json
from pathlib import Path

from maskfactory.nude_batch_queue import NudeBatchQueue
from maskfactory.nude_dataset_coverage import build_nude_dataset_coverage
from maskfactory.nude_record_qualification import qualify_input_terminal_record


def test_coverage_reconciles_input_and_terminal_strata_without_hiding_gaps(tmp_path: Path) -> None:
    records = [
        {
            "sample_id": "one",
            "source_sha256": "a" * 64,
            "dataset_id": "dataset-a",
            "source_role": "bbox_evaluation_only",
            "media_domain": "photo",
            "source_split": "test",
            "lineage_group": "family-a",
            "source_labels": ["breast", "Sex"],
        },
        {
            "sample_id": "two",
            "source_sha256": "b" * 64,
            "dataset_id": "dataset-b",
            "source_role": "reference_and_tournament_input",
            "media_domain": "illustration",
            "source_split": "reference",
            "lineage_group": "family-b",
            "source_labels": [],
        },
    ]
    records_path = tmp_path / "records.jsonl"
    records_path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    crosswalk = tmp_path / "crosswalk.json"
    crosswalk.write_text(
        json.dumps(
            {
                "anatomy_aliases": {"breast": {}},
                "scene_and_action_labels": {"Sex": "sexual_activity_scene"},
            }
        ),
        encoding="utf-8",
    )
    queue = NudeBatchQueue(tmp_path / "queue.sqlite")
    queue.seed(
        [
            {
                "platform": "local",
                "path": "local/holdout.json",
                "lane": "bbox_evaluation_only",
                "self_sha256": "c" * 64,
                "sample_count": 1,
            }
        ],
        platform="local",
    )
    lease = queue.claim(platform="local", owner="fixture")
    assert lease is not None
    receipt = qualify_input_terminal_record(
        {
            "sample_id": "one",
            "source_sha256": "a" * 64,
            "source_role": "bbox_evaluation_only",
            "registry_sha256": "d" * 64,
            "shard_sha256": "e" * 64,
            "outcome": "holdout",
            "reasons": ["evaluation_only"],
            "input_report_sha256": "f" * 64,
            "holdout_policy_sha256": "1" * 64,
            "split_group_id": "group-one",
        }
    )
    receipt["sample_index"] = 0
    queue.checkpoint(
        platform="local",
        shard_path=lease["shard_path"],
        lease_token=lease["lease_token"],
        outcomes=[receipt],
    )
    report = build_nude_dataset_coverage(
        registry_records=records_path,
        ontology_crosswalk=crosswalk,
        queue_path=tmp_path / "queue.sqlite",
        platform="local",
    )
    assert report["status"] == "PASS"
    assert report["registry_record_count"] == 2
    assert report["processed_record_count"] == 1
    assert report["remaining_record_count"] == 1
    assert report["population_label_kind_counts"] == {
        "action_or_scene": 1,
        "anatomy": 1,
        "unlabeled": 1,
    }
    assert report["processed_label_kind_counts"] == {"action_or_scene": 1, "anatomy": 1}
    assert report["outcome_counts"] == {"holdout": 1}
    assert report["certification_yield"] == 0.0
    assert report["unprocessed_strata"]["dataset_id"] == ["dataset-b"]
